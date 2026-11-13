"""One audited transaction interface for project/package/task catalog changes."""
from datetime import datetime,timezone
from pathlib import Path
import copy,json,re,uuid
from .config import validate_config,load_config,catalog_for,contract_hash
from .io import safe_root,safe_path,canonical,stable_hash,hash_file,atomic,locked
from .storage import RegistryStore

def bootstrap(pid,name,owner,client,template='generic'):
 runtimes={'generic':{'name':'Project runtime','entrypoint':'Task-specific consumer','verificationMethod':'Explicit command receipt'},'binary':{'name':'Binary reader','entrypoint':'src/reader.py','verificationMethod':'CLI and byte-exact fixture comparison'},'unity':{'name':'Unity Editor','entrypoint':'Assets/Scenes/Main.unity','verificationMethod':'Unity MCP'}}
 if template not in runtimes:raise ValueError('Unknown project template')
 return {'schema':'super-ledger/project@1','project':{'id':pid,'name':name,'runtime':runtimes[template]},'phases':[{'id':'core','title':'核心主线'},{'id':'support','title':'基础支撑'},{'id':'later','title':'后置工作'}],'policy':{'coordinator':{'owner':owner,'client':client},'publicPaths':['src/','tests/','docs/']+(['Assets/','Packages/','ProjectSettings/'] if template=='unity' else ['assets/']),'sceneRequired':template=='unity'},'packages':[]}

def new_slot(task):
 return {'state':'idle','worker':None,'attempt':'','generation':0,'scope':'','updated':'','sequence':0,'contractSha256':contract_hash(task),'note':'','nextAction':'','blocker':'','deliveryStatus':'','history':[],'integrations':[],'verifications':[]}

def initialize_catalog(root,config):
 root=safe_root(root);root.mkdir(parents=True,exist_ok=True);store=RegistryStore(root)
 with locked(store.lock):
  store.validate_paths()
  if safe_path(root,'super-ledger.json').exists() or store.path.exists() or safe_path(root,'.super-ledger/pending-catalog.json').exists():raise ValueError('Project is already initialized or needs catalog recovery')
  data={'schema':'super-ledger/registry@1','projectId':config['project']['id'],'configSha256':stable_hash(config),'version':0,'slots':{k:new_slot(t) for k,t in catalog_for(config).items()}}
  obj=Catalog(root);obj._transaction(None,None,config,data,config['policy']['coordinator'],'initialize project')

class Catalog:
 def __init__(self,root):
  self.root=safe_root(root);self.store=RegistryStore(self.root);self.pending=safe_path(self.root,'.super-ledger/pending-catalog.json')
 def _path(self,relative):return safe_path(self.root,relative)
 def _lock(self):
  self.store.validate_paths();self._path('.super-ledger/writer.lock');return locked(self.store.lock)
 def _read(self):
  if self._path('.super-ledger/pending-catalog.json').exists():raise ValueError('Pending catalog transaction; run catalog recover')
  config=load_config(self.root);data=self.store.load()
  if data.get('configSha256')!=stable_hash(config) or set(data['slots'])!=set(catalog_for(config)):raise ValueError('Configuration/registry mismatch; direct JSON edits are not admitted')
  return config,data
 def show(self):
  config,data=self._read()
  return {'schema':'super-ledger/project-observation@1','readOnly':True,'revision':stable_hash(data),'config':config,'version':data['version'],'taskCount':len(data['slots']),'packageCount':len(config['packages'])}
 def apply(self,proposal,owner,client,expected_revision,reason,dry_run=False):
  with self._lock():
   before,data=self._read()
   if self._path('.super-ledger/pending-publication.json').exists():raise ValueError('Recover pending publication first')
   actor={'owner':owner,'client':client}
   if actor!=before['policy']['coordinator']:raise ValueError('Only configured coordinator may change catalog')
   if expected_revision!=stable_hash(data):raise ValueError('Project revision changed; refresh project show')
   if not isinstance(reason,str) or not reason.strip():raise ValueError('Catalog change needs a reason')
   after=validate_config(proposal)
   def protected(c):return {k:v for k,v in c.items() if k not in ('packages','phases','project')}, {k:v for k,v in c['project'].items() if k not in ('name','description')}
   if protected(before)!=protected(after):raise ValueError('Runtime/policy/identity changes require a separate explicit policy migration')
   old_packages={p['id']:p for p in before['packages']};new_packages={p['id']:p for p in after['packages']}
   old_tasks=catalog_for(before);new_tasks=catalog_for(after)
   if not set(old_packages)<=set(new_packages) or not set(old_tasks)<=set(new_tasks):raise ValueError('Removal would erase history; preserve existing IDs')
   changed=[];updated=copy.deepcopy(data)
   for key,task in new_tasks.items():
    if key not in old_tasks:updated['slots'][key]=new_slot(task);changed.append(key)
    elif task!=old_tasks[key]:
     slot=updated['slots'][key]
     if slot['state']!='idle' or slot.get('generation') or slot.get('attempt') or slot.get('history'):raise ValueError('Claimed task contract is frozen; create a follow-up task instead: '+key)
     slot['contractSha256']=contract_hash(task);slot['sequence']+=1;changed.append(key)
   if after==before:raise ValueError('No catalog changes')
   updated.update(configSha256=stable_hash(after),version=data['version']+1)
   updated.setdefault('catalogHistory',[]).append({'at':datetime.now(timezone.utc).isoformat(),'actor':actor,'reason':reason,'beforeConfigSha256':stable_hash(before),'afterConfigSha256':stable_hash(after),'changedTasks':changed})
   if dry_run:return {'dryRun':True,'writeAuthorized':False,'revision':stable_hash(data),'changedTasks':changed,'taskCount':len(new_tasks),'packageCount':len(after['packages'])}
   return self._transaction(before,data,after,updated,actor,reason)
 def _transaction(self,before,old_data,after,new_data,actor,reason):
  tid=uuid.uuid4().hex;prefix='.super-ledger/catalog-transactions/'+tid+'/'
  values={'before-config.json':self._path('super-ledger.json').read_bytes() if before is not None else b'null','after-config.json':canonical(after)+b'\n','before-registry.json':canonical(old_data),'after-registry.json':canonical(new_data)}
  hashes={}
  for name,content in values.items():p=self._path(prefix+name);atomic(p,content);hashes[name]=hash_file(p)
  journal={'schema':'super-ledger/catalog-transaction@1','id':tid,'actor':actor,'reason':reason,'files':hashes,'initializing':before is None}
  jp=self._path(prefix+'journal.json');atomic(jp,canonical(journal));atomic(self._path('.super-ledger/pending-catalog.json'),canonical({'id':tid,'sha256':hash_file(jp)}))
  return self._finish(journal)
 def _finish(self,journal):
  prefix='.super-ledger/catalog-transactions/'+journal['id']+'/'
  for name,sha in journal['files'].items():
   if hash_file(self._path(prefix+name))!=sha:raise ValueError('Frozen catalog transaction changed')
  before_raw=self._path(prefix+'before-config.json').read_bytes();after_raw=self._path(prefix+'after-config.json').read_bytes()
  before=json.loads(before_raw);after=validate_config(json.loads(after_raw));old_data=json.loads(self._path(prefix+'before-registry.json').read_bytes());new_data=json.loads(self._path(prefix+'after-registry.json').read_bytes())
  config_path=self._path('super-ledger.json');current=config_path.read_bytes() if config_path.exists() else b'null'
  if current not in (before_raw,after_raw):raise ValueError('Third-party configuration change; preserve it')
  actual=self.store.load() if self.store.path.exists() else None
  if stable_hash(actual) not in (stable_hash(old_data),stable_hash(new_data)):raise ValueError('Third-party registry change; preserve it')
  if new_data['configSha256']!=stable_hash(after):raise ValueError('Transaction config identity mismatch')
  atomic(config_path,after_raw);self.store.commit(new_data)
  atomic(self._path(prefix+'committed.json'),canonical({'id':journal['id'],'status':'committed'}));self._path('.super-ledger/pending-catalog.json').unlink()
  return {'committed':True,'transactionId':journal['id'],'revision':stable_hash(new_data),'taskCount':len(new_data['slots']),'packageCount':len(after['packages'])}
 def recover(self,owner,client,transaction):
  if not isinstance(transaction,str) or not re.fullmatch('[a-f0-9]{32}',transaction):raise ValueError('Invalid transaction ID')
  with self._lock():
   pending=json.loads(self._path('.super-ledger/pending-catalog.json').read_bytes());prefix='.super-ledger/catalog-transactions/'+transaction+'/'
   jp=self._path(prefix+'journal.json')
   if pending.get('id')!=transaction or hash_file(jp)!=pending.get('sha256'):raise ValueError('Pending transaction identity mismatch')
   journal=json.loads(jp.read_bytes())
   for name,sha in journal['files'].items():
    if hash_file(self._path(prefix+name))!=sha:raise ValueError('Frozen transaction changed')
   config=json.loads(self._path(prefix+('after-config.json' if journal['initializing'] else 'before-config.json')).read_bytes())
   if {'owner':owner,'client':client}!=config['policy']['coordinator']:raise ValueError('Only original coordinator may recover')
   return self._finish(journal)
