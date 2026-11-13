"""Public CLI acceptance in unrelated projects and isolated user profiles.

Grants remain in memory and travel over stdin, never arguments or files. The
suite does not import the source project's kernel or patch module globals.
"""
from __future__ import annotations
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPOSITORY = Path(__file__).resolve().parents[1]

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

class CliAcceptance(unittest.TestCase):
    maxDiff = None
    def setUp(self):
        temporary_base = REPOSITORY / "build" / "test-tmp"
        temporary_base.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="accept-", dir=temporary_base)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.project = self.root / "unrelated-reverse-project"
        self.project.mkdir()
        self.profile = self.root / "isolated-profile"
        self.profile.mkdir()
        self.env = os.environ.copy()
        self.env.update(PYTHONPATH=str(REPOSITORY / "src"), PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1",
                        USERPROFILE=str(self.profile), APPDATA=str(self.profile), LOCALAPPDATA=str(self.profile),
                        XDG_CONFIG_HOME=str(self.profile), XDG_DATA_HOME=str(self.profile), TEMP=str(self.root), TMP=str(self.root))
        self.config = json.loads((REPOSITORY / "examples/binary-format.json").read_text(encoding="utf-8"))
        self.config["project"]["id"] = "independent-acceptance"
        self.config["policy"]["coordinator"] = {"owner": "reviewer", "client": "codex"}
        self.config["packages"][0]["tasks"][0]["acceptance"] = ["Header bytes are decoded exactly.", "Malformed input is rejected by the real consumer."]
        self.config_file = self.root / "project-config.json"
        self.config_file.write_text(json.dumps(self.config), encoding="utf-8")
        self.base_command = [sys.executable, "-m", "super_ledger", "--project", str(self.project)]
        self.report_counts = {}

    def run_cli(self, *arguments, grant=None, ok=True):
        result = subprocess.run([*self.base_command, *map(str, arguments)], cwd=self.project, env=self.env,
                                input=json.dumps(grant) if grant is not None else None,
                                text=True, encoding="utf-8", capture_output=True, timeout=30)
        displayed_output = "<grant omitted>" if '"token"' in result.stdout else result.stdout
        detail = f"command={arguments!r}\nstdout={displayed_output}\nstderr={result.stderr}"
        if ok:
            self.assertEqual(result.returncode, 0, detail)
            try: return json.loads(result.stdout)
            except json.JSONDecodeError as error: self.fail(f"Expected public JSON result: {detail}\n{error}")
        self.assertNotEqual(result.returncode, 0, detail)
        self.assertNotIn("No module named", result.stderr, detail)
        return result

    def initialize(self):
        return self.run_cli("init", "--config", self.config_file, "--json")

    def identity(self, task="read-header"):
        return self.run_cli("show", "FORMAT", task, "--identity", "--json")

    def take(self, owner="author", task="read-header", identity=None):
        identity = identity or self.identity(task)
        return self.run_cli("take", "FORMAT", task, "--owner", owner, "--client", "codex", "--expected-revision", identity["revision"], "--json")

    def file(self, path, content):
        target = self.project / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes): target.write_bytes(content)
        else: target.write_text(content, encoding="utf-8")
        return {"path": path, "sha256": sha(target)}

    def wait(self, grant, text="Implemented one bounded parser increment."):
        count = self.report_counts.get(grant["scope"], 0) + 1
        self.report_counts[grant["scope"]] = count
        filename = "report.md" if count == 1 else "report-" + str(count) + ".md"
        report = self.file(grant["scope"] + "/" + filename, text)
        self.run_cli("wait", grant["packageId"], grant["taskId"], "--grant-stdin", "--expected-revision", self.identity(grant["taskId"])["revision"],
                     "--report", report["path"], "--next-action", "Independently verify the real consumer.", "--delivery-status", "review", "--json", grant=grant)
        return self.identity(grant["taskId"])

    def handoff(self, identity, owner="reviewer", task="read-header", ok=True):
        return self.run_cli("take-handoff", "FORMAT", task, "--owner", owner, "--client", "codex", "--expected-revision", identity["revision"],
                            "--report-sha", identity["reportSha256"], "--json", ok=ok)

    def reviewer(self, task="read-header"):
        author = self.take(task=task)
        waiting = self.wait(author)
        return self.handoff(waiting, task=task), waiting

    def verification(self, grant, tier="module", register=True):
        """Execute a small real parser fixture and pin its actual inputs/results."""
        scope = grant["scope"]
        task = next(item for item in self.config["packages"][0]["tasks"] if item["id"] == grant["taskId"])
        parser = self.file(task["publicTargets"][0], "def parse(data):\n    if len(data) != 4: raise ValueError('truncated')\n    return int.from_bytes(data, 'little')\n")
        sample = self.file(scope + "/sample.bin", b"\x2a\x00\x00\x00")
        driver = self.file(scope + "/check.py", "import json,sys\nfrom pathlib import Path\nsys.path.insert(0," + repr(str((self.project / parser["path"]).parent)) + ")\nfrom " + Path(parser["path"]).stem + " import parse\nassert parse(Path(__file__).with_name('sample.bin').read_bytes()) == 42\ntry: parse(b'\\x00')\nexcept ValueError: pass\nelse: raise AssertionError('truncation accepted')\nprint(json.dumps({'checks':2}))\n")
        command = [sys.executable, str(self.project / driver["path"])]
        run = subprocess.run(command, cwd=self.project, env=self.env, capture_output=True, text=True, encoding="utf-8", timeout=15)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout)["checks"], 2)
        receipt_data = {"command": command, "exitCode": run.returncode, "checks": 2, "stdout": run.stdout, "stderr": run.stderr}
        receipt = self.file(scope + "/check-receipt.json", json.dumps(receipt_data))
        proof = {"schema": "super-ledger/verification@1", "contractSha256": self.identity(grant["taskId"])["contractSha256"],
                 "tier": tier, "command": command, "exitCode": run.returncode, "checks": 2,
                 "inputs": {parser["path"]: parser["sha256"], sample["path"]: sample["sha256"], driver["path"]: driver["sha256"]},
                 "artifacts": {parser["path"]: parser["sha256"]}, "receipts": [receipt]}
        evidence = self.file(scope + "/module-verification.json", json.dumps(proof))
        if register:
            self.run_cli("verify", "FORMAT", grant["taskId"], "--grant-stdin", "--expected-revision", self.identity(grant["taskId"])["revision"],
                         "--evidence", evidence["path"], "--json", grant=grant)
        return evidence, proof

    def completion(self, grant, prior, verification):
        task = next(item for item in self.config["packages"][0]["tasks"] if item["id"] == grant["taskId"])
        proof = {"schema": "super-ledger/completion@1", "contractSha256": self.identity(grant["taskId"])["contractSha256"],
                 "submissionSha256": prior["reportSha256"], "acceptance": [{"text": text, "passed": True} for text in task["acceptance"]],
                 "verification": verification}
        evidence = self.file(grant["scope"] + "/completion.json", json.dumps(proof))
        return evidence, proof

    def end(self, grant, evidence, ok=True):
        return self.run_cli("end", "FORMAT", grant["taskId"], "--grant-stdin", "--expected-revision", self.identity(grant["taskId"])["revision"],
                            "--evidence", evidence["path"], "--json", grant=grant, ok=ok)

    def publish_current(self, grant, verification):
        """Formally publish the exact parser bytes covered by the real receipt."""
        task = next(item for item in self.config["packages"][0]["tasks"] if item["id"] == grant["taskId"])
        target = task["publicTargets"][0]
        candidate = self.file(grant["scope"] + "/candidate-parser.py", (self.project / target).read_bytes())
        receipt = self.project / grant["scope"] / "check-receipt.json"
        manifest = {"schema": "super-ledger/publication@1",
                    "files": {target: {"candidate": candidate["path"], "preimage": sha(self.project / target), "postimage": candidate["sha256"]}},
                    "dependencies": {verification["path"]: verification["sha256"]},
                    "verification": {"path": receipt.relative_to(self.project).as_posix(), "sha256": sha(receipt)}}
        evidence = self.file(grant["scope"] + "/publication.json", json.dumps(manifest))
        return self.run_cli("publish", "FORMAT", grant["taskId"], "--grant-stdin", "--expected-revision", self.identity(grant["taskId"])["revision"],
                            "--manifest", evidence["path"], "--json", grant=grant)

    def test_init_custom_ids_isolated_project_and_read_only_discovery(self):
        self.initialize()
        self.assertTrue((self.project / "super-ledger.json").is_file())
        identity = self.identity()
        self.assertEqual(identity["state"], "idle")
        self.assertNotIn("tokenHash", json.dumps(identity))
        self.assertNotIn('"token"', json.dumps(identity))
        before = {p.relative_to(self.project).as_posix(): sha(p) for p in self.project.rglob("*") if p.is_file()}
        queue = self.run_cli("candidates", "--owner", "author", "--client", "codex", "--phase", "core", "--limit", "1", "--offset", "0", "--json")
        self.assertFalse(queue["admissionEvaluated"])
        self.assertEqual(queue["tasks"][0]["packageId"], "FORMAT")
        second_page = self.run_cli("candidates", "--owner", "author", "--client", "codex", "--phase", "core", "--limit", "1", "--offset", "1", "--json")
        self.assertEqual({queue["tasks"][0]["taskId"], second_page["tasks"][0]["taskId"]}, {"read-header", "read-directory"})
        self.assertEqual(before, {p.relative_to(self.project).as_posix(): sha(p) for p in self.project.rglob("*") if p.is_file()})
        self.run_cli("validate", "--json")

    def test_init_rejects_duplicate_tasks_without_partial_registry(self):
        tasks = self.config["packages"][0]["tasks"]
        tasks.append(copy.deepcopy(tasks[0]))
        self.config_file.write_text(json.dumps(self.config), encoding="utf-8")
        failure = self.run_cli("init", "--config", self.config_file, "--json", ok=False)
        self.assertIn("duplicate", failure.stderr.lower())
        self.assertFalse((self.project / ".super-ledger/registry.json").exists())

    def test_init_rejects_missing_dependency_and_actual_task_cycle(self):
        tasks = self.config["packages"][0]["tasks"]
        tasks[0]["dependencies"] = ["FORMAT/unknown-task"]
        self.config_file.write_text(json.dumps(self.config), encoding="utf-8")
        failure = self.run_cli("init", "--config", self.config_file, "--json", ok=False)
        self.assertIn("dependency", failure.stderr.lower())
        tasks[0]["dependencies"] = ["FORMAT/read-directory"]
        self.config_file.write_text(json.dumps(self.config), encoding="utf-8")
        failure = self.run_cli("init", "--config", self.config_file, "--json", ok=False)
        self.assertIn("cycle", failure.stderr.lower())
        self.assertFalse((self.project / ".super-ledger/registry.json").exists())

    def test_stale_claim_revision_and_aba_are_rejected(self):
        self.initialize()
        idle = self.identity()
        author = self.take(identity=idle)
        self.run_cli("take", "FORMAT", "read-header", "--owner", "competitor", "--client", "codex", "--expected-revision", idle["revision"], "--json", ok=False)
        waiting = self.wait(author)
        self.run_cli("resume", "FORMAT", "read-header", "--grant-stdin", "--expected-revision", waiting["revision"], "--json", grant=author)
        newer = self.wait(author, "Another bounded delivery in the same attempt.")
        self.assertNotEqual(waiting["revision"], newer["revision"])
        self.handoff(waiting, ok=False)
        self.assertEqual(self.identity()["revision"], newer["revision"])

    def test_real_process_competing_claim_has_exactly_one_winner(self):
        self.initialize()
        revision = self.identity()["revision"]
        processes = [subprocess.Popen([*self.base_command, "take", "FORMAT", "read-header", "--owner", owner, "--client", "codex", "--expected-revision", revision, "--json"],
                                     cwd=self.project, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8") for owner in ("racer-a", "racer-b")]
        results = []
        try:
            for process in processes:
                output, error = process.communicate(timeout=30)
                results.append((process.returncode, output, error))
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill(); process.communicate()
        self.assertEqual(sorted(code == 0 for code, _, _ in results), [False, True], [(code, error) for code, _, error in results])
        winner = json.loads(next(out for code, out, _ in results if code == 0))
        current = self.identity()
        self.assertEqual(current["attempt"], winner["attempt"])
        self.assertEqual(current["state"], "running")

    def test_handoff_preserves_report_and_revokes_old_or_forged_grant(self):
        self.initialize()
        author = self.take()
        waiting = self.wait(author)
        report_path = self.project / author["scope"] / "report.md"
        report_bytes = report_path.read_bytes()
        self.handoff(waiting, owner="author", ok=False)
        reviewer = self.handoff(waiting)
        self.assertNotEqual(author["token"], reviewer["token"])
        self.assertNotEqual(author["attempt"], reviewer["attempt"])
        self.assertEqual(report_path.read_bytes(), report_bytes)
        current = self.identity()
        self.run_cli("progress", "FORMAT", "read-header", "--grant-stdin", "--expected-revision", current["revision"], "--note", "old grant", "--json", grant=author, ok=False)
        forged = dict(reviewer, owner="someone-else")
        self.run_cli("progress", "FORMAT", "read-header", "--grant-stdin", "--expected-revision", current["revision"], "--note", "forged owner", "--json", grant=forged, ok=False)
        self.assertEqual(self.identity()["revision"], current["revision"])
        registry_text = (self.project / ".super-ledger/registry.json").read_text(encoding="utf-8")
        self.assertNotIn(author["token"], registry_text)
        self.assertNotIn(reviewer["token"], registry_text)

    def test_handoff_rejects_report_drift_without_changing_state(self):
        self.initialize()
        author = self.take()
        waiting = self.wait(author)
        (self.project / author["scope"] / "report.md").write_text("tampered report", encoding="utf-8")
        self.handoff(waiting, ok=False)
        self.assertEqual(self.identity()["state"], "waiting")

    def test_wrong_token_and_escaped_report_do_not_mutate_state(self):
        self.initialize()
        author = self.take()
        current = self.identity()
        forged = dict(author, token="definitely-not-the-current-token")
        self.run_cli("progress", "FORMAT", "read-header", "--grant-stdin", "--expected-revision", current["revision"], "--note", "wrong token", "--json", grant=forged, ok=False)
        self.file("outside-attempt.md", "Wrong report scope")
        self.run_cli("wait", "FORMAT", "read-header", "--grant-stdin", "--expected-revision", current["revision"], "--report", "outside-attempt.md", "--next-action", "review", "--delivery-status", "review", "--json", grant=author, ok=False)
        self.assertEqual(self.identity()["revision"], current["revision"])

    def test_source_repository_is_not_a_runtime_dependency(self):
        self.initialize()
        self.take()
        for path in (REPOSITORY / "src/super_ledger").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("C:\\Users\\dains\\Documents\\GitLab\\spore-unity", text, str(path))
            self.assertNotIn("C:/Users/dains/Documents/GitLab/spore-unity", text, str(path))

    def test_cross_owner_real_verification_and_complete_original_contract(self):
        self.initialize()
        reviewer, prior = self.reviewer()
        evidence, _ = self.verification(reviewer)
        self.assertEqual(self.identity()["state"], "running", "module verification must not end a task")
        self.publish_current(reviewer, evidence)
        completion, _ = self.completion(reviewer, prior, [evidence])
        self.end(reviewer, completion)
        self.assertEqual(self.identity()["state"], "ended")
        self.run_cli("validate", "--json")

    def test_missing_verification_and_reordered_acceptance_cannot_end(self):
        self.initialize()
        reviewer, prior = self.reviewer()
        evidence, _ = self.verification(reviewer)
        self.publish_current(reviewer, evidence)
        completion, _ = self.completion(reviewer, prior, [])
        missing = self.end(reviewer, completion, ok=False)
        self.assertIn("reference", missing.stderr.lower())
        completion, proof = self.completion(reviewer, prior, [evidence])
        proof["acceptance"].reverse()
        self.file(completion["path"], json.dumps(proof))
        reordered = self.end(reviewer, completion, ok=False)
        self.assertIn("acceptance", reordered.stderr.lower())
        self.assertEqual(self.identity()["state"], "running")

    def test_artifact_or_proof_drift_cannot_end(self):
        self.initialize()
        reviewer, prior = self.reviewer()
        evidence, proof = self.verification(reviewer)
        self.publish_current(reviewer, evidence)
        completion, _ = self.completion(reviewer, prior, [evidence])
        parser = next(iter(proof["artifacts"]))
        self.file(parser, "def parse(data): return 0\n")
        self.end(reviewer, completion, ok=False)
        self.assertEqual(self.identity()["state"], "running")

    def test_pending_dependency_allows_work_but_blocks_complete(self):
        self.initialize()
        reviewer, prior = self.reviewer(task="read-directory")
        evidence, _ = self.verification(reviewer)
        completion, _ = self.completion(reviewer, prior, [evidence])
        self.end(reviewer, completion, ok=False)
        self.assertEqual(self.identity("read-directory")["state"], "running")

    def test_boolean_exit_code_and_missing_scene_receipts_rejected(self):
        self.initialize()
        reviewer, _ = self.reviewer()
        evidence, proof = self.verification(reviewer, register=False)
        proof["exitCode"] = False
        self.file(evidence["path"], json.dumps(proof))
        before = self.identity()
        self.run_cli("verify", "FORMAT", "read-header", "--grant-stdin", "--expected-revision", before["revision"], "--evidence", evidence["path"], "--json", grant=reviewer, ok=False)
        proof["exitCode"] = 0
        proof["tier"] = "scene"
        self.file(evidence["path"], json.dumps(proof))
        self.run_cli("verify", "FORMAT", "read-header", "--grant-stdin", "--expected-revision", before["revision"], "--evidence", evidence["path"], "--json", grant=reviewer, ok=False)
        self.assertEqual(self.identity()["revision"], before["revision"])

if __name__ == "__main__":
    unittest.main()
