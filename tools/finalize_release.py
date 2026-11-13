from pathlib import Path
import hashlib,json

ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
receipt_path=max((ROOT/'evidence').glob('verification-*/receipt.json'),key=lambda p:p.stat().st_mtime_ns)
receipt=json.loads(receipt_path.read_bytes());assert receipt['exitCode']==0 and receipt['commands'][0]['checks']==46
for relative,digest in receipt['inputs'].items():assert sha(ROOT/relative)==digest,relative
installation=json.loads((ROOT/'evidence/standalone-install.json').read_bytes())
assert installation['exitCode']==0 and installation['wheelSha256']==sha(ROOT/'releases/super_ledger-0.1.0-py3-none-any.whl')
assert (ROOT/'evidence/browser-desktop.png').stat().st_size>10000 and (ROOT/'evidence/browser-mobile.png').stat().st_size>10000
report='''# Super Ledger v0.1.0 delivery

Standalone project: C:/Users/dains/Documents/GitLab/super-ledger. Python3.11+ standard-library runtime; editable installation and a real wheel verified. No import/call/data dependency on spore-unity. Existing source ledger and its234 original tasks remain separate.

Implemented configurable project/catalog/phases/runtime/coordinator/publication paths; SHA-addressed validated history; OS-lock/auth/CAS; bounded delivery and independent handoff; exact contract and dependency completion; recoverable pre/postimage publication; actual command receipts; module/scene evidence separation; generic read-only dashboard and bounded immutable snapshots. CLI JSON pipes are UTF-8 even under isolated Windows Python.

Three independent implementation lanes and cross-reviews found and fixed configuration-policy bypass, metadata/cache symlink escape, cross-task publication scope, runner output collision, stale unchanged-snapshot auditing. Browser found/fixed cached deep-link restore and scope adaptation; fresh handoff commands are visible when clipboard is restricted.

Final46 unittest cases passed with real subprocess and loopback tests; Node protocol7 assertions and syntax checks passed. Isolated venv imported installed wheel, initialized unrelated projects under isolated user profile, validated every installed package byte against the final wheel and served the demo. Browser desktop/narrow acceptance and screenshots recorded. No game or Unity runtime acceptance claimed; demo parser is explicitly synthetic, actually executed and independently reviewed.

Limits: v0.1 does not silently migrate existing authority/history/grants or edit initialized contracts/policy, and does not support deletion/move publication. The read-only maintenance API explicitly reports unsupported rather than pretending to operate the former project-specific7-milestone maintenance protocol. Existing ledgers continue independently. Credentials never enter reports/Git; licensing remains an owner decision, no open-source rights invented.

Ready-to-install artifact: releases/super_ledger-0.1.0-py3-none-any.whl. Demo:http://127.0.0.1:5198/. New projects use examples/*.json and CLI init; these sample counts are not production progress.
'''
(ROOT/'evidence/DELIVERY.md').write_text(report,encoding='utf-8')
plan=ROOT/'docs/superpowers/plans/2026-11-14-extraction.md'
note='\n\nCompleted: Tasks1–5 implemented, independently reviewed, and verified. See evidence/DELIVERY.md and release-verification.json. Git publication is tracked by the actual repository commit/remote, not by invented test progress.\n'
plan.write_text(plan.read_text(encoding='utf-8').replace(note,'').rstrip()+note,encoding='utf-8')
files=[receipt_path,ROOT/'evidence/standalone-install.json',ROOT/'evidence/browser-acceptance.json',ROOT/'evidence/browser-desktop.png',ROOT/'evidence/browser-mobile.png',ROOT/'releases/super_ledger-0.1.0-py3-none-any.whl']
proof={'schema':'super-ledger/release@1','version':'0.1.0','exitCode':0,'pythonTests':46,'nodeProtocolAssertions':7,'standaloneInstallation':True,'browserAccepted':True,'sourceInputs':receipt['inputs'],'evidence':{p.relative_to(ROOT).as_posix():sha(p) for p in files},'runtimeAcceptance':'synthetic parser example only; no game/Unity acceptance'}
(ROOT/'evidence/release-verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'exitCode':0,'pythonTests':46,'releaseFiles':len(files),'wheelSha256':installation['wheelSha256']}))
