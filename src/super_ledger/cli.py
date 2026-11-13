"""CLI is the only mutation surface. The HTTP service is read-only."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Super Ledger — evidence-gated task handoff")
    p.add_argument("--project", type=Path, default=Path.cwd(), help="Project containing super-ledger.json")
    sub = p.add_subparsers(dest="action", required=True)
    init = sub.add_parser("init", help="Initialize a new independent project without overwriting a ledger")
    init.add_argument("--config", type=Path)
    init.add_argument("--id")
    init.add_argument("--name")
    init.add_argument("--owner")
    init.add_argument("--client")
    init.add_argument("--template",choices=['generic','binary','unity'],default='generic')
    init.add_argument("--json", action="store_true")
    candidates = sub.add_parser("candidates", help="Read bounded suggestions; this grants no write permission")
    candidates.add_argument("--owner", required=True)
    candidates.add_argument("--client", required=True)
    candidates.add_argument("--phase", default="")
    candidates.add_argument("--limit", type=int, default=3)
    candidates.add_argument("--offset", type=int, default=0)
    candidates.add_argument("--json", action="store_true")
    for action in ("show", "take", "take-handoff", "progress", "wait", "resume", "verify", "end", "publish", "recover", "requeue"):
        command = sub.add_parser(action)
        command.add_argument("package")
        command.add_argument("task")
        command.add_argument("--json", action="store_true")
        if action == "show":
            command.add_argument("--identity", action="store_true")
            continue
        command.add_argument("--expected-revision", required=True)
        if action in {"take", "take-handoff", "requeue"}:
            command.add_argument("--owner", required=True)
            command.add_argument("--client", required=True)
        else:
            command.add_argument("--grant-stdin", action="store_true", required=True, help="Read the grant JSON from stdin; never store it in the registry")
        if action == "take-handoff":
            command.add_argument("--report-sha", required=True)
        if action in {"progress", "requeue"}:
            command.add_argument("--note", required=True)
        if action == "requeue":
            command.add_argument("--revoke-running", action="store_true")
        if action == "wait":
            command.add_argument("--report", required=True)
            command.add_argument("--next-action", required=True)
            command.add_argument("--delivery-status", default="implementation", choices=["implementation", "integration", "review", "source", "dependency", "external"])
            command.add_argument("--blocker", default="")
        if action in {"verify", "end"}:
            command.add_argument("--evidence", required=True)
        if action == "publish":
            command.add_argument("--manifest", required=True)
        if action == "recover":
            command.add_argument("--publication", required=True)
    validate = sub.add_parser("validate", help="Validate configuration, registry and full immutable object closure")
    validate.add_argument("--json", action="store_true")
    serve = sub.add_parser("serve", help="Serve the read-only dashboard on loopback")
    serve.add_argument("--host", default="127.0.0.1", choices=["127.0.0.1", "localhost", "::1"])
    serve.add_argument("--port", type=int, default=5198)
    run = sub.add_parser("run-check", help="Execute a real argv, retain output, and generate a scoped receipt")
    run.add_argument("--receipt", required=True, help="Path inside a ledger-work attempt")
    run.add_argument("--timeout", type=float, default=120)
    run.add_argument("--grant-stdin", action="store_true", required=True)
    run.add_argument("--expected-revision", required=True)
    run.add_argument("command", nargs=argparse.REMAINDER)
    from .catalog_cli import add_catalog_commands
    add_catalog_commands(sub)
    return p


def run_check(ledger, args: argparse.Namespace) -> dict:
    from .io import atomic, safe_path, locked
    root = ledger.root
    grant = json.load(sys.stdin)
    argv = list(args.command)
    if argv and argv[0] == "--":
        argv.pop(0)
    if not argv or args.timeout <= 0:
        raise ValueError("run-check requires a command and positive timeout")
    # Validate before opening the per-attempt runner lock. This lock is private
    # metadata; no artifact is written into an obsolete handoff scope.
    with ledger._writer_lock():
        ledger._check_pending()
        data = ledger.snapshot()
        slot = ledger._slot(data, ledger._key(grant.get("packageId"), grant.get("taskId")))
        ledger._auth(slot, grant)
        ledger._cas(slot, args.expected_revision)
        target = safe_path(root, args.receipt, scope=slot["scope"])
        attempt = slot["attempt"]
    runner_lock = safe_path(root, ".super-ledger/check-locks/" + attempt + ".lock")
    with locked(runner_lock):
        stdout = safe_path(root, target.with_name(target.stem + ".stdout.txt").relative_to(root).as_posix(), scope=grant["scope"])
        stderr = safe_path(root, target.with_name(target.stem + ".stderr.txt").relative_to(root).as_posix(), scope=grant["scope"])
        if any(p.exists() for p in (target, stdout, stderr)):
            raise ValueError("receipt or output already exists; preserve the previous run")
        start = time.monotonic()
        try:
            result = subprocess.run(argv, cwd=root, capture_output=True, timeout=args.timeout)
            code, out, err = result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired as error:
            code, out, err = 124, error.stdout or b"", (error.stderr or b"") + b"\ncheck timed out\n"
        with ledger.authorized(grant, args.expected_revision) as (_, slot):
            target, stdout, stderr = [safe_path(root, p.relative_to(root).as_posix(), scope=slot["scope"]) for p in (target, stdout, stderr)]
            if any(p.exists() for p in (target, stdout, stderr)):
                raise ValueError("receipt/output changed while command ran; preserve it")
            atomic(stdout, out)
            atomic(stderr, err)
            receipt = {"schema": "super-ledger/check@1", "command": argv, "exitCode": code, "checks": 1,
                       "seconds": time.monotonic() - start, "output": {
                           str(p.relative_to(root)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in (stdout, stderr)}}
            atomic(target, json.dumps(receipt, ensure_ascii=False, indent=2).encode("utf-8"))
    return receipt


def execute(args: argparse.Namespace):
    from .engine import Ledger
    root = args.project.resolve()
    if args.action == "init":
        from .config import initialize_project
        from .catalog import bootstrap
        if args.config:
            if any((args.id,args.name,args.owner,args.client)) or args.template!='generic':raise ValueError('Use either --config or explicit empty-project fields')
            config=json.loads(args.config.read_bytes())
        else:
            if not all((args.id,args.name,args.owner,args.client)):raise ValueError('Empty project needs --id --name --owner --client')
            config=bootstrap(args.id,args.name,args.owner,args.client,args.template)
        initialize_project(root, config)
        return {"initialized": True, "project": str(root)}
    if args.action in {'project','package','task','catalog','doctor'}:
        from .catalog_cli import execute_catalog
        return execute_catalog(root,args)
    ledger = Ledger(root)
    if args.action == "serve":
        from .server import serve
        serve(root, host=args.host, port=args.port)
        return None
    if args.action == "run-check":
        return run_check(ledger, args)
    if args.action == "validate":
        data = ledger.snapshot()
        return {"valid": True, "projectId": data["projectId"], "tasks": len(ledger.catalog), "historyValidated": True}
    if args.action == "candidates":
        return ledger.candidates(args.owner, args.client, phase=args.phase, limit=args.limit, offset=args.offset)
    if args.action == "show":
        identity = ledger.identity(args.package, args.task)
        if args.identity:
            return identity
        key = args.package + "/" + args.task
        from .engine import public_slot
        return {"identity": identity, "task": ledger.catalog[key], "slot": public_slot(ledger.snapshot()["slots"][key])}
    if args.action in {"take", "take-handoff"}:
        return ledger.take(args.package, args.task, args.owner, args.client, args.expected_revision,
                           report_sha=getattr(args, "report_sha", None), handoff=args.action == "take-handoff")
    if args.action == "requeue":
        return ledger.requeue(args.package, args.task, args.owner, args.client, args.expected_revision, args.note, args.revoke_running)
    grant = json.load(sys.stdin)
    if (grant.get("packageId"), grant.get("taskId")) != (args.package, args.task):
        raise ValueError("grant task does not match CLI target")
    if args.action == "progress":
        return ledger.progress(grant, args.expected_revision, args.note)
    if args.action == "resume":
        return ledger.resume(grant, args.expected_revision)
    if args.action == "wait":
        return ledger.wait(grant, args.expected_revision, args.report, args.next_action, args.delivery_status, args.blocker)
    if args.action == "verify":
        return ledger.register_verification(grant, args.expected_revision, args.evidence)
    if args.action == "end":
        return ledger.end(grant, args.expected_revision, args.evidence)
    from .publication import Publisher
    publisher = Publisher(ledger)
    if args.action == "publish":
        return publisher.integrate(grant, args.expected_revision, args.manifest)
    if args.action == "recover":
        return publisher.recover(grant, args.expected_revision, args.publication)
    raise ValueError("unsupported action")


def main(argv=None) -> int:
    # Machine-readable JSON must keep the same encoding in Windows pipes,
    # including python -I, which ignores PYTHONUTF8 and user configuration.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="strict")
    args = parser().parse_args(argv)
    try:
        result = execute(args)
        if result is not None:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.action == 'doctor' and not result.get('ready'):return 1
        return int(result.get("exitCode", 0)) if args.action == "run-check" and isinstance(result, dict) else 0
    except (ValueError, OSError, KeyError, TimeoutError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
