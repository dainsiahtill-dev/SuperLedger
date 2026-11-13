import copy,json,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from super_ledger.config import initialize_project
from super_ledger.engine import Ledger
from super_ledger.io import stable_hash
from super_ledger.catalog import Catalog,bootstrap

class CatalogTests(unittest.TestCase):
 def setUp(self):
  base=Path(__file__).resolve().parents[1]/'build/test-tmp';base.mkdir(parents=True,exist_ok=True)
  self.temp=tempfile.TemporaryDirectory(dir=base);self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  initialize_project(self.root,bootstrap('lab','逆向项目','lead','cli'))
 def cat(self):return Catalog(self.root)
 def edit(self,config,**kwargs):return self.cat().apply(config,'lead','cli',self.cat().show()['revision'],'test change',**kwargs)
 def package(self):
  c=self.cat().show()['config'];c['packages'].append({'id':'FORMAT','title':'格式','phase':'core','tasks':[]});self.edit(c)
 def task(self,tid='header',dependencies=None):return {'id':tid,'title':tid,'objective':'Read actual bytes','acceptance':['Read actual bytes','Reject truncation'],'dependencies':dependencies or [],'publicTargets':[]}
 def add(self,tid='header'):
  c=self.cat().show()['config'];c['packages'][0]['tasks'].append(self.task(tid));self.edit(c)
 def test_empty_then_package_then_task(self):
  self.assertEqual(Ledger(self.root).snapshot()['slots'],{});self.package();self.add()
  self.assertEqual(set(Ledger(self.root).catalog),{'FORMAT/header'})
 def test_all_bootstrap_templates_and_unity_scene_gate(self):
  for template in ('generic','binary','unity'):
   root=self.root/template;initialize_project(root,bootstrap('p-'+template,template,'lead','cli',template))
   ledger=Ledger(root);self.assertEqual(ledger.config['policy']['sceneRequired'],template=='unity')
 def test_stale_coordinator_cycle_and_policy_rejected(self):
  self.package();self.add();cat=self.cat();c=cat.show()['config'];rev=cat.show()['revision']
  with self.assertRaises(ValueError):cat.apply(c,'worker','cli',rev,'bad')
  with self.assertRaises(ValueError):cat.apply(c,'lead','cli','0'*64,'stale')
  bad=copy.deepcopy(c);bad['policy']['sceneRequired']=True
  with self.assertRaises(ValueError):self.edit(bad)
  c['packages'][0]['tasks'][0]['dependencies']=['FORMAT/header']
  with self.assertRaises(ValueError):self.edit(c)
 def test_add_preserves_running_grant_but_contract_edit_rejected(self):
  self.package();self.add();ledger=Ledger(self.root);grant=ledger.take('FORMAT','header','worker','any',ledger.identity('FORMAT','header')['revision'])
  before=ledger.snapshot()['slots']['FORMAT/header'];self.add('directory')
  self.assertEqual(Ledger(self.root).snapshot()['slots']['FORMAT/header'],before)
  c=self.cat().show()['config'];c['packages'][0]['tasks'][0]['acceptance']=['weaker']
  with self.assertRaises(ValueError):self.edit(c)
  note=self.root/grant['scope']/'progress.md';note.write_text('Still working')
  new=Ledger(self.root);new.progress(grant,new.identity('FORMAT','header')['revision'],note.relative_to(self.root).as_posix())
 def test_recovery_after_config_write_and_third_state(self):
  self.package();c=self.cat().show()['config'];c['packages'][0]['tasks'].append(self.task())
  import super_ledger.catalog as module
  original=module.RegistryStore.commit
  with patch.object(module.RegistryStore,'commit',side_effect=OSError('interrupted')):
   with self.assertRaises(OSError):self.edit(c)
  with self.assertRaises(ValueError):Ledger(self.root).snapshot()
  pending=json.loads((self.root/'.super-ledger/pending-catalog.json').read_bytes())
  file=self.root/'super-ledger.json';post=file.read_bytes();file.write_bytes(post+b' ')
  with self.assertRaises(ValueError):self.cat().recover('lead','cli',pending['id'])
  file.write_bytes(post);self.cat().recover('lead','cli',pending['id'])
  self.assertEqual(len(Ledger(self.root).catalog),1)
 def test_cli_first_project_package_task(self):
  target=self.root/'new';base=[sys.executable,'-m','super_ledger','--project',str(target)]
  def run(*args):
   r=subprocess.run(base+list(args),capture_output=True,encoding='utf-8');self.assertEqual(r.returncode,0,r.stderr);return json.loads(r.stdout)
  run('init','--id','another','--name','新项目','--owner','lead','--client','cli')
  identity=run('project','show');run('package','create','FORMAT','--title','格式','--owner','lead','--client','cli','--expected-revision',identity['revision'],'--reason','first package')
  spec=self.root/'task.json';spec.write_text(json.dumps(self.task()),encoding='utf-8');identity=run('project','show')
  run('task','create','FORMAT','--spec',str(spec),'--owner','lead','--client','cli','--expected-revision',identity['revision'],'--reason','first task')
  self.assertEqual(run('doctor')['ready'],True);self.assertEqual(len(run('task','list')['tasks']),1)
 def test_initialization_recovers_and_dry_run_does_not_write(self):
  other=self.root/'interrupted';config=bootstrap('recovery','Recovery','lead','cli')
  import super_ledger.catalog as module
  with patch.object(module.RegistryStore,'commit',side_effect=OSError('interrupted init')):
   with self.assertRaises(OSError):initialize_project(other,config)
  pending=json.loads((other/'.super-ledger/pending-catalog.json').read_bytes())
  Catalog(other).recover('lead','cli',pending['id']);self.assertEqual(Ledger(other).snapshot()['slots'],{})
  self.package();c=self.cat().show()['config'];c['packages'][0]['tasks'].append(self.task())
  before=Ledger(self.root).snapshot();result=self.edit(c,dry_run=True)
  self.assertTrue(result['dryRun']);self.assertEqual(before,Ledger(self.root).snapshot())
 def test_split_preserves_parent_acceptance_and_blocks_direct_claim_of_children_cycle(self):
  self.package();self.add();spec=self.root/'children.json';spec.write_text(json.dumps([self.task('field'),self.task('boundary')]))
  command=[sys.executable,'-m','super_ledger','--project',str(self.root),'task','split','FORMAT','header','--spec',str(spec),'--owner','lead','--client','cli','--expected-revision',self.cat().show()['revision'],'--reason','bounded slices']
  result=subprocess.run(command,capture_output=True,encoding='utf-8');self.assertEqual(result.returncode,0,result.stderr)
  ledger=Ledger(self.root);parent=ledger.catalog['FORMAT/header']
  self.assertEqual(parent['acceptance'],self.task()['acceptance']);self.assertEqual(parent['role'],'gate');self.assertEqual(ledger.identity('FORMAT','header')['state'],'idle')
  self.assertEqual(set(parent['dependencies']),{'FORMAT/field','FORMAT/boundary'})
  self.assertEqual({t['taskId'] for t in ledger.candidates('worker','cli')['tasks']},{'field','boundary'})
 def test_live_http_sees_empty_project_then_catalog_additions(self):
  import threading,urllib.request
  from super_ledger.server import make_server
  server=make_server(self.root,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   def tasks():
    base='http://127.0.0.1:'+str(server.server_port)
    with urllib.request.urlopen(base+'/api/workbench/manifest') as r:manifest=json.load(r)
    with urllib.request.urlopen(base+'/api/workbench/snapshots/'+manifest['snapshotId']+'/tasks') as r:return json.load(r)['items']
   self.assertEqual(tasks(),[]);self.package();self.add();self.assertEqual(tasks()[0]['taskId'],'header')
  finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main()
