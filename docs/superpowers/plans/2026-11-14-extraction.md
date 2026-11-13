# Super Ledger Extraction Implementation Plan

> For agentic workers: use superpowers:executing-plans. Three disjoint implementers work against the shared API; Root integrates and performs actual CLI, HTTP and browser acceptance.

**Goal:** independently installable, configurable task ledger preserving ownership, evidence and completion boundaries.

**Architecture:** standard-library Python kernel, controlled publication, immutable read models and adapted existing web UI. No Spore runtime dependencies.

**Tech Stack:** Python >=3.11, stdlib unittest, plain JS/CSS/HTML, optional Node protocol checks.

**Spec:** ../specs/2026-11-14-extraction-design.md

## Global constraints

- Shell commands start RTK; no model CLI launches, no Unity operations.
- New code only in super-ledger; existing project contracts/history unchanged.
- No persisted plaintext grants, no web writes, no history reset, no false acceptance.

## Review focus

- Fresh CAS and full history validation on every mutation, including same-second ABA.
- Publication rejects path escapes/links/governance files and preserves third-party edits during recovery.
- Independently tested exact clauses, evidence hashes, reviewer and dependency requirements.
- Generic IDs/phases and project-scoped browser cache; no source-repo runtime imports.
- Current/building snapshots survive pruning, private files are never served.

## Task 1 — Generic kernel (core implementer)

Create src/super_ledger/{io,config,storage,evidence,engine}.py. Implement config validation, metadata/full storage, grant/CAS transitions and strict evidence. Write focused negative tests first; run them through stdlib unittest. Public API is fixed in spec. Deliver implementation plus actual test output; no Git commits while others share checkout.

## Task 2 — Projection/service/UI (UI implementer)

Create src/super_ledger/{projection,server}.py and static/. Reuse four existing web assets with documented changes; config drives every project-specific label/phase/ID. Test snapshot retention/410/current corruption/path guards and adapt browser protocol. Use read-only Ledger API; do not edit core or CLI.

## Task 3 — Independent acceptance (test implementer)

Create tests/test_acceptance.py and examples/{binary-format,unity-runtime}.json. Real subprocess CLI tests must include concurrent claim, wait/new reviewer/end, bad token/CAS/report/evidence/dependency and isolated installation. Start with RED evidence until CLI exists. Do not edit implementation files.

## Task 4 — CLI/publication/package (Root)

Create pyproject.toml, __main__.py, cli.py, publication.py, generic prompt and provenance/user docs. CLI follows spec API; grant stdin for authenticated commands. Verify package wheel installs without source repo, end-to-end publish, HTTP and actual browser; review merged changes once, fix material issues and run scoped/full checks. Initialize Git and commit; push only if a configured verified remote exists.

## Task 5 — Delivery

Mark actual completed steps, retain receipts/screenshots under evidence/, state unavailable capabilities precisely, commit exact changes and report project location/commands/proof/remaining limits.


Completed: Tasks1–5 implemented, independently reviewed, and verified. See evidence/DELIVERY.md and release-verification.json. Git publication is tracked by the actual repository commit/remote, not by invented test progress.
