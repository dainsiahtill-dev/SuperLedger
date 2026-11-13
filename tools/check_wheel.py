"""Prove installation without editable/source/user-profile imports; start demo."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,subprocess,sys,time,urllib.request,zipfile

ROOT=Path(__file__).resolve().parents[1]
confirm='--confirm-existing' in sys.argv
base=max((p.parent for p in (ROOT/'build').glob('standalone-proof-*/server.stdout.log')),key=lambda p:p.stat().st_mtime_ns) if confirm else ROOT/'build'/('standalone-proof-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
if not confirm:base.mkdir(parents=True,exist_ok=False)
wheel=ROOT/'dist/super_ledger-0.1.0-py3-none-any.whl'
commands=[]
def run(argv,**kwargs):
 result=subprocess.run(argv,cwd=base,capture_output=True,**kwargs)
 row={'command':[str(x) for x in argv],'exitCode':result.returncode};commands.append(row)
 if result.returncode:raise RuntimeError(result.stderr.decode('utf-8',errors='replace'))
 return result.stdout
envdir=base/'env'
if not confirm:run([sys.executable,'-m','venv','--without-pip',str(envdir)])
windows=os.name=='nt';python=envdir/('Scripts/python.exe' if windows else 'bin/python')
site=envdir/('Lib/site-packages' if windows else 'lib/python'+str(sys.version_info.major)+'.'+str(sys.version_info.minor)+'/site-packages')
if not confirm:run([sys.executable,'-m','pip','install','--no-index','--no-deps','--target',str(site),str(wheel)])
isolated=os.environ.copy()
for key in ('PYTHONPATH','PYTHONHOME'):isolated.pop(key,None)
profile=base/'profile';profile.mkdir(exist_ok=confirm)
isolated.update(USERPROFILE=str(profile),APPDATA=str(profile),LOCALAPPDATA=str(profile),XDG_CONFIG_HOME=str(profile),XDG_DATA_HOME=str(profile))
location=json.loads(run([str(python),'-I','-c','import json,super_ledger;print(json.dumps({"file":super_ledger.__file__}))'],env=isolated))['file']
assert Path(location).is_relative_to(envdir) and not Path(location).is_relative_to(ROOT/'src')
project=base/('fresh-validation-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') if confirm else 'unrelated-project');config=base/'config.json';config.write_bytes((ROOT/'examples/binary-format.json').read_bytes())
run([str(python),'-I','-m','super_ledger','--project',str(project),'init','--config',str(config)],env=isolated)
validation=json.loads(run([str(python),'-I','-m','super_ledger','--project',str(project),'validate'],env=isolated));assert validation['valid']
candidates=json.loads(run([str(python),'-I','-m','super_ledger','--project',str(project),'candidates','--owner','independent-worker','--client','any-cli','--limit','3'],env=isolated));assert candidates['candidateCount']==2
with zipfile.ZipFile(wheel) as archive:
 for asset in ['app.js','app.css','workbench-data.js','index.html']:assert 'super_ledger/static/'+asset in archive.namelist()
 for name in archive.namelist():
  if name.startswith('super_ledger/') and not name.endswith('/'):assert (site/name).read_bytes()==archive.read(name),'Installed wheel content differs: '+name
demo=ROOT/'build/demo-project'
if not confirm:
 try:
  with urllib.request.urlopen('http://127.0.0.1:5198/healthz',timeout=.5):raise RuntimeError('Port5198 already occupied; preserve its service')
 except urllib.error.URLError:pass
 with (base/'server.stdout.log').open('wb') as out,(base/'server.stderr.log').open('wb') as err:
  process=subprocess.Popen([str(python),'-I','-m','super_ledger','--project',str(demo),'serve','--port','5198'],cwd=base,env=isolated,stdin=subprocess.DEVNULL,stdout=out,stderr=err,creationflags=(getattr(subprocess,'CREATE_NO_WINDOW',0)|getattr(subprocess,'DETACHED_PROCESS',0)),start_new_session=not windows)
health=None
for _ in range(40):
 try:
  with urllib.request.urlopen('http://127.0.0.1:5198/healthz',timeout=.5) as response:health=json.load(response)
  break
 except urllib.error.URLError:
  if not confirm and process.poll() is not None:raise RuntimeError('Demo service exited; inspect persistent logs')
  time.sleep(.15)
started=json.loads((base/'server.stdout.log').read_text(encoding='utf-8').splitlines()[0])
assert health and health==started and health['projectId']=='super-ledger-demo'
with urllib.request.urlopen('http://127.0.0.1:5198/readyz',timeout=3) as response:assert json.load(response)['ready']
result={'schema':'super-ledger/standalone-install-check@1','exitCode':0,'checks':12,'wheelSha256':hashlib.sha256(wheel.read_bytes()).hexdigest(),'wheelBytes':wheel.stat().st_size,'packageImportedFrom':location,'isolatedUserProfile':True,'sourceImportRequired':False,'commands':commands,'demoService':health,'url':'http://127.0.0.1:5198/','gameRuntimeAcceptance':False}
(ROOT/'evidence/standalone-install.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in result.items() if k!='commands'},ensure_ascii=False))
