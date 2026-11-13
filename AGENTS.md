# Super Ledger

All shell commands begin with `rtk`; use `rtk proxy` for commands without a native wrapper. Read README.md and docs/ARCHITECTURE.md before editing workflow rules.

Keep this project independent of any source game's repository or assets. Project-specific IDs, paths, coordinators, phases, runtime/MCP requirements and publication allowlists belong in configuration. Do not add hardcoded game names, default worker impersonation or hidden model launchers.

Preserve ownership + client + attempt + token authentication, full history validation and CAS under the OS lock, frozen handoff reports, distinct delivery/publication/module/scene/end stages and exact original acceptance clauses. Suggestions and web pages are read-only. Never mark a task ended by bypassing original dependencies or independent review.

Run `rtk proxy python -m unittest discover -s tests -v` after installing this package locally. Real HTTP/subprocess checks need the host environment. Do not claim a generated test receipt proves a game runtime was executed.
