"""Run the real regression commands and retain immutable verification output."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,re,subprocess,sys,time

ROOT=Path(__file__).resolve().parents[1]
stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
directory=ROOT/'evidence'/('verification-'+stamp);directory.mkdir(parents=True,exist_ok=False)
inputs={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for folder in ['src','tests','examples'] for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts}
commands=[[sys.executable,'-m','unittest','discover','-s','tests','-v'],['node','tests/test_web_protocol.mjs'],['node','--check','src/super_ledger/static/app.js'],['node','--check','src/super_ledger/static/workbench-data.js']]
results=[]
for index,command in enumerate(commands):
    start=time.monotonic();run=subprocess.run(command,cwd=ROOT,capture_output=True)
    for kind,raw in [('stdout',run.stdout),('stderr',run.stderr)]:
        content=raw.decode('utf-8',errors='replace')
        content=re.sub(r'("token"\s*:\s*")[^"]*(")',r'\1<redacted>\2',content)
        (directory/(str(index)+'-'+kind+'.txt')).write_text(content,encoding='utf-8')
    match=re.search(rb'Ran (\d+) tests?',run.stderr)
    row={'command':command,'exitCode':run.returncode,'checks':int(match.group(1)) if match else 1,'seconds':time.monotonic()-start}
    results.append(row);print(json.dumps(row),flush=True)
    if run.returncode:break
result={'schema':'super-ledger/release-verification@1','exitCode':0 if len(results)==len(commands) and all(r['exitCode']==0 for r in results) else 1,'commands':results,'inputs':inputs,'receiptDirectory':directory.relative_to(ROOT).as_posix()}
(directory/'receipt.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'exitCode':result['exitCode'],'receipt':(directory/'receipt.json').relative_to(ROOT).as_posix()}))
sys.exit(result['exitCode'])
