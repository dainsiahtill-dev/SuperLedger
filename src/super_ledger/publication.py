"""Frozen, recoverable publication bound to a current authenticated attempt.

The implementation adapts the original workbench's pre/postimage journal
protocol. The registry writer lock also serializes public file publication.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import re
import uuid

from .io import atomic, canonical, digest, hash_file, safe_path, locked


class Publisher:
    def __init__(self, ledger):
        self.ledger = ledger
        self.root = ledger.root
        self.base = ledger.storage.base
        self.pending = self.base / "pending-publication.json"

    def _target(self, relative):
        path = safe_path(self.root, relative)
        parts = relative.split("/")
        if parts[0].casefold() in {".git", ".super-ledger", "ledger-work"} or relative.casefold() in {"super-ledger.json", "agents.md"}:
            raise ValueError("Governance and attempt files cannot be public targets")
        allowed = self.ledger.config["policy"].get("publicPaths", [])
        if not any(relative.startswith(prefix) for prefix in allowed):
            raise ValueError("Public target is outside configured publicPaths")
        return path

    def _journal_dir(self, publication):
        if not isinstance(publication, str) or not re.fullmatch("[0-9a-f]{32}", publication):
            raise ValueError("Invalid publication ID")
        return safe_path(self.root, ".super-ledger/publications/" + publication)

    @staticmethod
    def _binding(grant):
        return {k: grant[k] for k in ("packageId", "taskId", "owner", "client", "attempt", "generation", "scope")}

    def _prepare(self, grant, slot, manifest):
        path = safe_path(self.root, manifest, scope=slot["scope"])
        raw = path.read_bytes()
        value = json.loads(raw)
        if value.get("schema") != "super-ledger/publication@1" or not isinstance(value.get("files"), dict) or not value["files"]:
            raise ValueError("Publication requires a nonempty explicit files map")
        if value.get("deletions") or value.get("moves"):
            raise ValueError("Deletion and move publication are not supported")
        verification = value.get("verification") or {}
        check_path = safe_path(self.root, verification.get("path", ""), scope=slot["scope"])
        if hash_file(check_path) != verification.get("sha256"):
            raise ValueError("Publication verification receipt SHA changed")
        check = json.loads(check_path.read_bytes())
        if type(check.get("exitCode")) is not int or check["exitCode"] != 0 or type(check.get("checks")) is not int or check["checks"] < 1 or not isinstance(check.get("command"), list) or not check["command"] or any(not isinstance(x, str) for x in check["command"]):
            raise ValueError("Publication needs a passing actual command receipt")
        files = {}
        candidates = {}
        aliases = set()
        task_targets = self.ledger.catalog[grant["packageId"] + "/" + grant["taskId"]].get("publicTargets", [])
        for index, (relative, entry) in enumerate(value["files"].items()):
            if not isinstance(entry, dict):
                raise ValueError("Invalid publication file entry")
            target = self._target(relative)
            if relative not in task_targets:
                raise ValueError("Public target is outside this task's original contract")
            alias = relative.casefold()
            if alias in aliases:
                raise ValueError("Case-colliding publication targets")
            aliases.add(alias)
            if target.exists() and not target.is_file():
                raise ValueError("Target is not a regular file")
            if "preimage" not in entry or hash_file(target) != entry["preimage"]:
                raise ValueError("Public preimage changed: " + relative)
            candidate = safe_path(self.root, entry.get("candidate", ""), scope=slot["scope"])
            content = candidate.read_bytes()
            if digest(content) != entry.get("postimage"):
                raise ValueError("Candidate postimage changed: " + relative)
            files[relative] = {"preimage": entry["preimage"], "postimage": entry["postimage"], "frozen": str(index) + ".bin"}
            candidates[str(index) + ".bin"] = content
        dependencies = value.get("dependencies", {})
        if not isinstance(dependencies, dict):
            raise ValueError("Invalid publication dependencies")
        for relative, sha in dependencies.items():
            if relative in files or hash_file(safe_path(self.root, relative)) != sha or not isinstance(sha, str):
                raise ValueError("Publication dependency changed or overlaps target")
        publication = uuid.uuid4().hex
        directory = self._journal_dir(publication)
        directory.mkdir(parents=True, exist_ok=False)
        for name, content in candidates.items():
            atomic(directory / name, content)
        atomic(directory / "manifest.json", raw)
        atomic(directory / "verification.json", check_path.read_bytes())
        journal = {"schema": "super-ledger/publication-journal@1", "id": publication, "status": "prepared",
                   "binding": self._binding(grant), "contractSha256": slot["contractSha256"],
                   "manifest": {"path": manifest, "sha256": digest(raw)}, "files": files,
                   "dependencies": dependencies, "verificationSha256": verification["sha256"]}
        atomic(directory / "journal.json", canonical(journal))
        atomic(self.pending, canonical({"id": publication, "journalSha256": digest(canonical(journal))}))
        return journal

    def _finish(self, grant, slot, journal):
        if journal.get("binding") != self._binding(grant) or journal.get("contractSha256") != slot["contractSha256"]:
            raise ValueError("Publication belongs to another grant or contract")
        directory = self._journal_dir(journal["id"])
        if digest((directory / "manifest.json").read_bytes()) != journal["manifest"]["sha256"] or digest((directory / "verification.json").read_bytes()) != journal["verificationSha256"]:
            raise ValueError("Frozen publication metadata changed")
        for relative, sha in journal["dependencies"].items():
            if hash_file(safe_path(self.root, relative)) != sha:
                raise ValueError("Publication dependency changed during recovery")
        # Check every target first: a third state must prevent all further writes.
        for relative, entry in journal["files"].items():
            target = self._target(relative)
            if relative not in self.ledger.catalog[grant["packageId"] + "/" + grant["taskId"]].get("publicTargets", []):
                raise ValueError("Recovered public target is outside this task's contract")
            if hash_file(target) not in (entry["preimage"], entry["postimage"]):
                raise ValueError("Third-party public edit; preserve it: " + relative)
            frozen = safe_path(self.root, (directory / entry["frozen"]).relative_to(self.root).as_posix())
            if hash_file(frozen) != entry["postimage"]:
                raise ValueError("Frozen candidate changed")
        for relative, entry in journal["files"].items():
            target = self._target(relative)
            if hash_file(target) != entry["postimage"]:
                atomic(target, (directory / entry["frozen"]).read_bytes())
        existing = next((r for r in slot.get("integrations", []) if r.get("id") == journal["id"]), None)
        if existing:
            return existing
        receipt = {"id": journal["id"], "status": "committed", "attempt": slot["attempt"],
                   "committedAt": datetime.now(timezone.utc).isoformat(), "manifest": journal["manifest"],
                   "artifacts": {p: f["postimage"] for p, f in journal["files"].items()},
                   "dependencies": journal["dependencies"], "journal": str((directory / "journal.json").relative_to(self.root)).replace("\\", "/")}
        slot.setdefault("integrations", []).append(receipt)
        return receipt

    def _clear(self, journal):
        # Registry commit has succeeded before this point. The prepared journal
        # stays immutable; a separate commit marker records recovery completion.
        with self.ledger._writer_lock():
            atomic(self._journal_dir(journal["id"]) / "committed.json", canonical({"id": journal["id"], "status": "committed"}))
            if self.pending.exists() and json.loads(self.pending.read_bytes()).get("id") == journal["id"]:
                self.pending.unlink()

    def integrate(self, grant, expected_revision, manifest):
        with self.ledger.authorized(grant, expected_revision, allow_pending=True) as (_, slot):
            if self.pending.exists():
                raise ValueError("Pending publication exists; recover it before a new publication")
            journal = self._prepare(grant, slot, manifest)
            receipt = self._finish(grant, slot, journal)
        self._clear(journal)
        return receipt

    def recover(self, grant, expected_revision, publication):
        with self.ledger.authorized(grant, expected_revision, allow_pending=True) as (_, slot):
            if not self.pending.exists():
                raise ValueError("No pending publication")
            pending = json.loads(self.pending.read_bytes())
            if pending.get("id") != publication:
                raise ValueError("Another publication is pending")
            raw = (self._journal_dir(publication) / "journal.json").read_bytes()
            if digest(raw) != pending.get("journalSha256"):
                raise ValueError("Pending publication journal SHA changed")
            journal = json.loads(raw)
            receipt = self._finish(grant, slot, journal)
        self._clear(journal)
        return receipt
