# Catalog lifecycle design and implementation plan

User requested deep improvement of first-project, first-package and task creation. Native execution; no further questions per standing authorization.

Implement an empty-project bootstrap, then `project show`, `package list/create/update`, `task list/create/update/split`, `catalog apply/recover`, and `doctor`. File-based task specifications keep exact acceptance clauses and shell quoting simple. Every catalog mutation requires the configured coordinator, a fresh whole-project revision and a reason. Ordinary workers keep their current grant rules.

An initially empty project/package is valid. Contract edits and splits are allowed only before the task has ever been claimed. Adding unrelated tasks preserves existing slots, grants, reports and evidence. Splitting a draft preserves its original acceptance as a gate depending on explicit child tasks; it never ends the parent automatically. Existing dependencies must remain acyclic.

All mutations use one catalog module: normalize configuration, compare protected project policy/runtime, validate task differences and original state, construct new slots, write immutable before/after snapshots, persist a journal before changing config/registry. Pending catalog transactions block task operations; recovery checks exact known config bytes and logical registry identities and refuses third-party edits. Administrative changes cannot lower runtime/scene requirements or change coordinator policy.

The read-only server reloads a successfully validated project configuration each refresh, so new packages/tasks appear without restart. Empty views explain the next CLI operation. `doctor` reports pending recovery, contract mismatch, missing reports and historical evidence drift without claiming runtime acceptance.

Plan: (1) failing lifecycle/CLI/recovery tests; (2) implement shared catalog transaction and safe bootstrap; (3) wire CLI and server; (4) full regression and actual empty/new populated HTTP acceptance; (5) document commands, build0.2 wheel, commit/push. Preserve previous release evidence rather than overwrite it.
