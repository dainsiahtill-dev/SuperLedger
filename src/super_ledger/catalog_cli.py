"""Small CLI adapter; all changes go through the same audited Catalog module."""
import json
from pathlib import Path
from .catalog import Catalog
from .io import safe_path

def admin(p,revision=True):
 p.add_argument('--owner',required=True);p.add_argument('--client',required=True)
 if revision:p.add_argument('--expected-revision',required=True);p.add_argument('--reason',required=True)
 p.add_argument('--json',action='store_true')

def add_catalog_commands(sub):
 project=sub.add_parser('project',help='Observe project revision or update its display name/description');sp=project.add_subparsers(dest='operation',required=True)
 sp.add_parser('show').add_argument('--json',action='store_true');p=sp.add_parser('update');p.add_argument('--name');p.add_argument('--description');admin(p)
 package=sub.add_parser('package',help='Create/list/update work packages');sp=package.add_subparsers(dest='operation',required=True)
 sp.add_parser('list').add_argument('--json',action='store_true')
 for op in ('create','update'):
  p=sp.add_parser(op);p.add_argument('package');p.add_argument('--title',required=op=='create');p.add_argument('--phase',default='core' if op=='create' else None);p.add_argument('--priority',type=int);admin(p)
 task=sub.add_parser('task',help='Create/list/update/split draft tasks');sp=task.add_subparsers(dest='operation',required=True)
 p=sp.add_parser('list');p.add_argument('--package');p.add_argument('--json',action='store_true')
 for op in ('create','update','split'):
  p=sp.add_parser(op);p.add_argument('package')
  if op!='create':p.add_argument('task')
  p.add_argument('--spec',type=Path,required=True,help='UTF-8 task object; split uses an array of child task objects');admin(p)
 catalog=sub.add_parser('catalog',help='Validate and apply a complete proposed catalog, or recover a pending transaction');sp=catalog.add_subparsers(dest='operation',required=True)
 p=sp.add_parser('apply');p.add_argument('--config',type=Path,required=True);p.add_argument('--dry-run',action='store_true');admin(p)
 p=sp.add_parser('recover');p.add_argument('--transaction',required=True);admin(p,False)
 p=sub.add_parser('doctor',help='Read-only readiness and evidence diagnostics');p.add_argument('--json',action='store_true')

def execute_catalog(root,args):
 cat=Catalog(root)
 if args.action=='catalog' and args.operation=='recover':return cat.recover(args.owner,args.client,args.transaction)
 if args.action=='doctor':
  issues=[]
  for name in ('pending-catalog.json','pending-publication.json'):
   p=safe_path(root,'.super-ledger/'+name)
   if p.exists():issues.append({'kind':'pending-recovery','path':str(p.relative_to(root)),'transaction':json.loads(p.read_bytes()).get('id')})
  if issues:return {'ready':False,'issues':issues,'readOnly':True}
  try:
   from .engine import Ledger
   ledger=Ledger(root);data=ledger.snapshot()
   for key,slot in data['slots'].items():
    identity=ledger.identity(*key.split('/'))
    if identity['reportError']:issues.append({'kind':'report-drift','task':key,'reason':identity['reportError']})
    if slot['state']=='ended' and not ledger.ended_valid(*key.split('/'),data):issues.append({'kind':'ended-needs-revalidation','task':key})
   return {'ready':not issues,'readOnly':True,'tasks':len(ledger.catalog),'packages':len(ledger.config['packages']),'issues':issues}
  except (ValueError,OSError,KeyError) as error:return {'ready':False,'readOnly':True,'issues':[{'kind':'invalid-project','reason':str(error)}]}
 observed=cat.show();config=observed['config']
 if args.action=='project' and args.operation=='show':return observed
 if args.action=='package' and args.operation=='list':return {'revision':observed['revision'],'packages':[{'id':p['id'],'title':p['title'],'phase':p['phase'],'priority':p['priority'],'taskCount':len(p['tasks'])} for p in config['packages']]}
 if args.action=='task' and args.operation=='list':return {'revision':observed['revision'],'tasks':[{**t,'packageId':p['id']} for p in config['packages'] if not args.package or p['id']==args.package for t in p['tasks']]}
 if args.action=='project':
  if args.name is not None:config['project']['name']=args.name
  if args.description is not None:config['project']['description']=args.description
 elif args.action=='catalog':config=json.loads(args.config.read_bytes())
 elif args.action=='package':
  matches=[p for p in config['packages'] if p['id']==args.package]
  if args.operation=='create':
   if matches:raise ValueError('Package already exists')
   config['packages'].append({'id':args.package,'title':args.title,'phase':args.phase,'priority':args.priority or 0,'tasks':[]})
  else:
   if not matches:raise ValueError('Unknown package')
   for key in ('title','phase','priority'):
    value=getattr(args,key)
    if value is not None:matches[0][key]=value
 elif args.action=='task':
  package=next((p for p in config['packages'] if p['id']==args.package),None)
  if package is None:raise ValueError('Unknown package')
  spec=json.loads(args.spec.read_bytes())
  if args.operation=='create':
   if not isinstance(spec,dict):raise ValueError('Task spec must be an object')
   package['tasks'].append(spec)
  else:
   original=next((t for t in package['tasks'] if t['id']==args.task),None)
   if original is None:raise ValueError('Unknown task')
   if args.operation=='update':
    if not isinstance(spec,dict) or spec.get('id')!=args.task:raise ValueError('Update must retain the original task ID')
    package['tasks'][package['tasks'].index(original)]=spec
   else:
    if not isinstance(spec,list) or not spec or any(not isinstance(t,dict) for t in spec):raise ValueError('Split needs child task objects')
    children=[args.package+'/'+t['id'] for t in spec]
    for task in spec:task['parentTask']=args.package+'/'+args.task
    original.update(role='gate',dependencies=list(dict.fromkeys(original['dependencies']+children)),splitChildren=children)
    package['tasks'].extend(spec)
 return cat.apply(config,args.owner,args.client,args.expected_revision,args.reason,dry_run=getattr(args,'dry_run',False))
