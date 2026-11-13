# Super Ledger extraction design

User intent: a standalone, reusable ledger for future reverse-engineering projects. The target directory was empty. The existing Spore ledger remains operational and authoritative; extraction does not migrate or modify its task contracts.

User delegated decisions and opted out of further questions. Root chooses a Python 3.11+ standard-library package and the existing plain JavaScript UI. This is an internal extraction; no third-party assets or new open-source license grants.

## Approach

Copying the whole 4000-line generator would retain Spore paths and policies. Replacing it with a superficial tracker would lose evidence and authorization. Selected approach: adapt proven storage/locking and workflow rules into a configuration-driven kernel, reuse the UI and immutable snapshot protocol, and record provenance. No runtime import, subprocess, symlink, or data dependency on spore-unity is allowed.

## Configuration and files

`super-ledger.json` uses schema `super-ledger/project@1`: project {id,name,description,runtime:{name,entrypoint,verificationMethod}}, phases [{id,title}], policy {coordinator:{owner,client},publicPaths:[relative prefixes],sceneRequired:boolean,snapshotKeep:5,snapshotBytes:268435456}, packages [{id,title,phase,priority,tasks:[{id,title,objective,acceptance:[original strings],dependencies:[package/task],role:implementation|gate,publicTargets:[],counterexamples:[],consumer:string}]}]. IDs match `[A-Za-z0-9][A-Za-z0-9_-]{0,63}`. Reject duplicate IDs, missing dependencies and task cycles. Configuration is a contract, not a cached UI hint.

State lives in `.super-ledger/registry.json` with SHA-addressed immutable history objects. Attempt artifacts live in `ledger-work/<package>/<task>/attempts/<random-id>/`. No token is persisted; grants appear once in CLI output and are submitted over stdin for later operations. Snapshots/cache can be regenerated and never authorize mutations.

## Kernel API shared by implementers

`Ledger(root: Path)` exposes `root`, `config`, `catalog` mapping `package/task` to task dictionaries containing packageId, and `storage`. `snapshot()` returns full validated registry `{schema,projectId,version,slots:{key:slot}}`. `identity(package, task)` returns read-only revision/state/attempt/generation/report SHA/contract SHA, never grants. `candidates(owner,client,phase='',limit=3,offset=0)` returns metadata-only suggestions with admissionEvaluated false.

Operations: `take(package,task,owner,client,expected_revision,report_sha=None,handoff=False)`; `progress(grant,expected_revision,note)`; `wait(grant,expected_revision,report,next_action,delivery_status='implementation',blocker='')`; `resume(grant,expected_revision)`; `register_verification(grant,expected_revision,evidence)`; `end(grant,expected_revision,evidence)`; `requeue(package,task,owner,client,expected_revision,note,revoke_running=False)`. Every operation has an OS lock around read/auth/CAS/commit. Grant contains packageId,taskId,owner,client,attempt,generation,scope,token,revision.

`authorized(grant,expected_revision)` is a context manager yielding `(data, slot)` under lock after full object integrity, contract, current running grant and CAS validation; on normal exit increments sequence/updated and commits. Used by controlled Publisher; exceptions commit nothing. `safe_path(root,relative,scope=None)` rejects absolute/traversal/reserved names/case collisions/links/escape. `hash_file`, canonical SHA helpers are shared.

Slot shape includes state, worker {owner,client}, attempt,generation,scope,updated,sequence,tokenHash,contractSha256,note,nextAction,blocker,deliveryStatus,report {path,sha256},history[],integrations[],verifications[],inheritedHandoff. Public observations strip hashes of credentials and storage references. Full mutation loads and verifies history.

## Evidence and publication

Wait freezes a scoped nonempty UTF-8 Markdown report and records its SHA. Resume may use the retained grant; a new handoff/requeue invalidates it. Independent handoff requires different actual owner plus fresh revision/report SHA and preserves the predecessor. End requires implementation handoff, unchanged prior report, a different reviewer, all dependencies ended with current evidence, and a scoped completion proof. Exact original acceptance strings appear in exact order, all passed, with nonzero checks, integer exitCode 0, actual command receipts and current input/artifact hashes. Module and scene verification remain distinct; scene policy requires configured MCP method, tool-call evidence and screenshot artifacts, never a compile-only claim.

Publisher manifest schema `super-ledger/publication@1` contains files {target:{candidate,preimage,postimage}}, dependencies {path:sha}, verification {path,sha256}. Verify scope and allowlist, freeze inputs before mutation, journal before writes, recover only known pre/postimages, never overwrite a third state. Configuration/state/attempt history are protected from ordinary publication. No deletion support in initial extraction; unsupported capability fails explicitly.

## Read-only service and UI

`python -m super_ledger --project PROJECT serve --port PORT` binds loopback by default. Serve only bundled static resources and allowlisted attempt evidence, never arbitrary project files or registry/grants. Keep manifest/shard SHA checks, fresh identity GET, explicit expired snapshot 410 and current-corruption errors. Snapshot builders and pruning share one lock; hidden build directories never enter pruning candidates. UI title, phases, runtime instructions, CLI prefix and IDs come from config; local cache keys include projectId. No web mutation or automatic worker launch.

## Acceptance

Install/build/import independently, initialize two unrelated project configs including non-CRE IDs, real CLI grant/competing claim/wait/handoff/verification/end, negative auth and evidence cases, controlled publication and recovery, actual browser desktop/narrow views, HTTP guards and cache retention. Preserve previous failure receipts. Source import remains opt-in and read-only; no live Spore grant migrates. If importing historical catalogs cannot be fully verified this release, explicitly reject unsupported import rather than silently reinterpret history.
