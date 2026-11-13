"""Real installed-wheel first-project workflow; grants are never stored."""
from pathlib import Path
from datetime import datetime,timezone
import json,os,subprocess,sys,time,urllib.request,zipfile,hashlib
ROOT=Path(__file__).resolve().parents[1];proof=ROOT/'evidence/lifecycle-v0.2.json'
def run(argv,cwd):
 result=subprocess.run([str(x) for x in argv],cwd=cwd,capture_output=True)
 if result.returncode:raise RuntimeError(result.stderr.decode('utf-8',errors='replace'))
 return result.stdout
if '--verify-install' in sys.argv:
 value=json.loads(proof.read_bytes());base=Path(value['base']);site=Path(value['site']);assert base.is_relative_to(ROOT/'build') and site.is_relative_to(base)
 wheel=ROOT/'dist/super_ledger-0.2.0-py3-none-any.whl';run([sys.executable,'-m','pip','install','--no-index','--no-deps','--upgrade','--target',site,wheel],base)
 with zipfile.ZipFile(wheel) as archive:
  for name in archive.namelist():
   if name.startswith('super_ledger/') and not name.endswith('/'):assert (site/name).read_bytes()==archive.read(name)
 assert json.loads(run(value['launcher']+['doctor'],base))['ready']
 value['wheelSha256']=hashlib.sha256(wheel.read_bytes()).hexdigest();value['finalInstalledBytesVerified']=True
 proof.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
elif '--populate' not in sys.argv:
 base=ROOT/'build'/('lifecycle-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'));base.mkdir(parents=True)
 site=base/'site';wheel=ROOT/'dist/super_ledger-0.2.0-py3-none-any.whl'
 run([sys.executable,'-m','pip','install','--no-index','--no-deps','--target',site,wheel],base)
 with zipfile.ZipFile(wheel) as archive:
  for name in archive.namelist():
   if name.startswith('super_ledger/') and not name.endswith('/'):assert (site/name).read_bytes()==archive.read(name)
 project=base/'project'
 # Isolated Python ignores user site and source roots; only installed wheel path is added.
 launcher=[sys.executable,'-I','-c','import sys,runpy;sys.path.insert(0,sys.argv.pop(1));runpy.run_module("super_ledger",run_name="__main__")',str(site),'--project',str(project)]
 run(launcher+['init','--id','first-project-demo','--name','Super Ledger · 从零建账','--template','binary','--owner','demo-lead','--client','cli'],base)
 with (base/'server.stdout').open('wb') as out,(base/'server.stderr').open('wb') as err:
  proc=subprocess.Popen(launcher+['serve','--port','0'],cwd=base,stdin=subprocess.DEVNULL,stdout=out,stderr=err,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)|getattr(subprocess,'DETACHED_PROCESS',0),start_new_session=os.name!='nt')
 for _ in range(100):
  lines=(base/'server.stdout').read_bytes().splitlines()
  if lines:break
  if proc.poll() is not None:raise RuntimeError((base/'server.stderr').read_text())
  time.sleep(.1)
 health=json.loads(lines[0]);value={'schema':'super-ledger/lifecycle-smoke@1','python':sys.executable,'site':str(site),'project':str(project),'base':str(base),'launcher':launcher,'health':health,'url':'http://127.0.0.1:'+str(health['port'])+'/','wheelSha256':hashlib.sha256(wheel.read_bytes()).hexdigest(),'initialTaskCount':0}
 proof.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
else:
 value=json.loads(proof.read_bytes());base=Path(value['base']);assert base.is_relative_to(ROOT/'build');launcher=value['launcher']
 identity=json.loads(run(launcher+['project','show'],base));run(launcher+['package','create','FORMAT','--title','首个工作包','--owner','demo-lead','--client','cli','--expected-revision',identity['revision'],'--reason','first package'],base)
 identity=json.loads(run(launcher+['project','show'],base));run(launcher+['task','create','FORMAT','--spec',str(ROOT/'examples/first-task.json'),'--owner','demo-lead','--client','cli','--expected-revision',identity['revision'],'--reason','first bounded task'],base)
 assert json.loads(run(launcher+['doctor'],base))['ready'];value.update(populatedTaskCount=1,exitCode=0,checks=8)
 proof.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
with urllib.request.urlopen(value['url']+'api/workbench/manifest',timeout=5) as response:manifest=json.load(response)
with urllib.request.urlopen(value['url']+'api/workbench/snapshots/'+manifest['snapshotId']+'/tasks',timeout=5) as response:tasks=json.load(response)
assert tasks['total']==value.get('populatedTaskCount',0)
print(json.dumps({'url':value['url'],'tasks':tasks['total'],'installedWheel':True,'exitCode':0},ensure_ascii=False))
