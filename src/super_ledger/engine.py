"""Generic ownership, bounded delivery and independent completion state machine."""
from contextlib import contextmanager
from datetime import datetime,timezone
from pathlib import Path
import copy
import hmac
import secrets
from .config import load_config,catalog_for,contract_hash
from .io import safe_path,safe_root,hash_file,stable_hash,digest,locked
from .storage import RegistryStore
from .evidence import report_snapshot,validate_verification,validate_completion


def now():return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def _public(value):
    if isinstance(value,dict):return {k:_public(v) for k,v in value.items() if k not in ('token','tokenHash','$ledgerBlob')}
    if isinstance(value,list):return [_public(v) for v in value]
    return value


def public_slot(slot):
    """Return a detached public observation, with all credential material removed."""
    return copy.deepcopy(_public(slot))


class Ledger:
    def __init__(self,root):
        self.root=safe_root(root);self.config=load_config(self.root);self.catalog=catalog_for(self.config);self.storage=RegistryStore(self.root);self._config_hash=hash_file(self.root/'super-ledger.json');self._policy_hash=stable_hash(self.config)
    def _key(self,package,task):
        key=str(package)+'/'+str(task)
        if key not in self.catalog:raise ValueError('Unknown task '+key)
        return key
    def _check_config(self):
        if hash_file(self.root/'super-ledger.json')!=self._config_hash:raise ValueError('Project contracts/policy changed; reload the ledger')
    def snapshot(self):
        self._check_config();data=self.storage.load()
        if data.get('projectId')!=self.config['project']['id'] or set(data.get('slots',{}))!=set(self.catalog) or data.get('configSha256')!=self._policy_hash:raise ValueError('Project configuration contract/registry mismatch; explicit migration is required')
        return data
    def _slot(self,data,key):
        slot=data['slots'][key]
        if slot.get('contractSha256')!=contract_hash(self.catalog[key]):raise ValueError('Task contract changed; existing attempt cannot authorize this contract')
        return slot
    def _commit(self,data,slot):
        self._check_config();slot['sequence']=slot.get('sequence',0)+1;slot['updated']=now();data['version']=data.get('version',0)+1;self.storage.commit(data)
    @staticmethod
    def _cas(slot,expected):
        if not isinstance(expected,str) or not expected or not hmac.compare_digest(stable_hash(slot),expected):raise ValueError('Task revision changed; obtain fresh identity')
    @staticmethod
    def _worker(owner,client):
        if not isinstance(owner,str) or not owner.strip() or not isinstance(client,str) or not client.strip():raise ValueError('Actual unique owner/client are required')
        return {'owner':owner,'client':client}
    def _auth(self,slot,grant,states=('running',)):
        if slot.get('state') not in states or slot.get('worker')!={'owner':grant.get('owner'),'client':grant.get('client')} or slot.get('attempt')!=grant.get('attempt') or slot.get('generation')!=grant.get('generation') or slot.get('scope')!=grant.get('scope'):raise ValueError('Current owner/attempt/grant mismatch')
        token=grant.get('token')
        if not isinstance(token,str) or not hmac.compare_digest(slot.get('tokenHash',''),digest(token.encode())):raise ValueError('Attempt token mismatch')
    @contextmanager
    def _writer_lock(self):
        self.storage.validate_paths()
        with locked(self.storage.lock):
            self.storage.validate_paths()
            yield
    @contextmanager
    def authorized(self,grant,expected_revision,*,allow_pending=False):
        with self._writer_lock():
            self._check_pending(allow_pending)
            data=self.snapshot();key=self._key(grant.get('packageId'),grant.get('taskId'));slot=self._slot(data,key);self._auth(slot,grant);self._cas(slot,expected_revision)
            yield data,slot
            self._commit(data,slot)
    def _check_pending(self,allow_pending=False):
        self.storage.validate_paths()
        if not allow_pending and safe_path(self.root,'.super-ledger/pending-publication.json').exists():raise ValueError('Recover pending controlled publication before any task mutation')
    def identity(self,package,task):
        key=self._key(package,task);data=self.snapshot();slot=self._slot(data,key);report=slot.get('report') or {};error=''
        if report:
            try:
                if hash_file(safe_path(self.root,report['path']))!=report['sha256']:error='Current report is missing or changed'
            except (OSError,ValueError,KeyError):error='Current report path is invalid'
        return {'schema':'super-ledger/identity@1','readOnly':True,'admissionEvaluated':False,'writeAuthorized':False,'projectId':data['projectId'],'packageId':package,'taskId':task,'state':slot['state'],'worker':copy.deepcopy(slot.get('worker')),'attempt':slot.get('attempt'),'generation':slot.get('generation'),'scope':slot.get('scope'),'revision':stable_hash(slot),'contractSha256':slot['contractSha256'],'reportPath':report.get('path',''),'reportSha256':report.get('sha256',''),'reportError':error,'nextAction':slot.get('nextAction',''),'blocker':slot.get('blocker','')}
    def candidates(self,owner,client,phase='',limit=3,offset=0):
        self._worker(owner,client)
        if type(limit) is not int or not 1<=limit<=50 or type(offset) is not int or offset<0:raise ValueError('Invalid candidate pagination')
        if phase and phase not in {p['id'] for p in self.config['phases']}:raise ValueError('Unknown phase')
        data=self.storage.observe_current();tasks=[]
        self._check_config()
        if data.get('projectId')!=self.config['project']['id'] or data.get('configSha256')!=self._policy_hash or set(data['slots'])!=set(self.catalog):raise ValueError('Project configuration contract/registry mismatch; explicit migration is required')
        for package in self.config['packages']:
            if phase and package['phase']!=phase:continue
            for task in package['tasks']:
                if task['role']=='gate':continue
                key=package['id']+'/'+task['id'];slot=data['slots'].get(key,{})
                if slot.get('state')=='idle':action='take'
                elif slot.get('state')=='waiting' and (slot.get('worker') or {}).get('owner')!=owner:action='take-handoff'
                else:continue
                report=slot.get('report') or {};error=''
                if action=='take-handoff':
                    try:
                        if hash_file(safe_path(self.root,report.get('path','')))!=report.get('sha256'):error='Report missing or changed; coordinator recovery needed'
                    except (OSError,ValueError):error='Report missing or changed; coordinator recovery needed'
                tasks.append({'packageId':package['id'],'taskId':task['id'],'title':task['title'],'phase':package['phase'],'priority':package['priority'],'state':slot['state'],'suggestedAction':'inspect-recovery' if error else action,'nextDeliverable':slot.get('nextAction') or 'Deliver one bounded implementation and counterexample, then wait','reportPath':report.get('path',''),'reportError':error,'dependencyObservations':[{'key':d,'state':data['slots'].get(d,{}).get('state','missing')} for d in task['dependencies']],'admissionEvaluated':False})
        tasks.sort(key=lambda t:(bool(t['reportError']),t['state']!='waiting',t['priority'],sum(d['state']!='ended' for d in t['dependencyObservations']),t['packageId'],t['taskId']))
        return {'schema':'super-ledger/candidates@1','readOnly':True,'admissionEvaluated':False,'writeAuthorized':False,'candidateCount':len(tasks),'tasks':tasks[offset:offset+limit],'nextOffset':offset+limit if offset+limit<len(tasks) else None,'historyValidated':False}
    def take(self,package,task,owner,client,expected_revision,report_sha=None,handoff=False):
        worker=self._worker(owner,client);key=self._key(package,task)
        with self._writer_lock():
            self._check_pending()
            data=self.snapshot();old=self._slot(data,key);self._cas(old,expected_revision)
            if handoff:
                if old.get('state')!='waiting' or not old.get('worker') or old['worker']['owner']==owner:raise ValueError('Independent handoff requires waiting and a different owner')
                submitted=old.get('report') or {};actual=report_snapshot(self.root,submitted.get('path',''),old['scope'])
                if actual!=submitted or report_sha!=actual['sha256']:raise ValueError('Handoff report SHA changed')
            elif old.get('state')!='idle' or old.get('worker'):raise ValueError('Task is already owned')
            attempt=secrets.token_hex(8);token=secrets.token_hex(24);scope=f'ledger-work/{package}/{task}/attempts/{attempt}'
            safe_path(self.root,scope).mkdir(parents=True,exist_ok=False)
            slot={'state':'running','worker':worker,'attempt':attempt,'generation':old.get('generation',0)+1,'scope':scope,'tokenHash':digest(token.encode()),'sequence':old.get('sequence',0),'updated':'','contractSha256':old['contractSha256'],'executionStage':'implementation','note':'','nextAction':'','blocker':'','deliveryStatus':'','history':copy.deepcopy(old.get('history',[])),'integrations':[],'verifications':[]}
            if handoff:
                previous={k:copy.deepcopy(v) for k,v in old.items() if k not in ('history','tokenHash')};slot['history'].append({'mode':'handoff','slot':previous,'at':now()});slot['inheritedHandoff']=previous
            else:
                if old.get('inheritedHandoff'):slot['inheritedHandoff']=copy.deepcopy(old['inheritedHandoff'])
            data['slots'][key]=slot;self._commit(data,slot)
            return {'schema':'super-ledger/grant@1','packageId':package,'taskId':task,**worker,'attempt':attempt,'generation':slot['generation'],'scope':scope,'token':token,'revision':stable_hash(slot),'state':'running'}
    def progress(self,grant,expected_revision,note):
        with self.authorized(grant,expected_revision) as (_,slot):
            report=report_snapshot(self.root,note,slot['scope']);slot['note']=note;slot.setdefault('progress',[]).append({**report,'at':now()})
        return {'recorded':True,'revision':stable_hash(slot),'state':slot['state']}
    def wait(self,grant,expected_revision,report,next_action,delivery_status='implementation',blocker=''):
        if not isinstance(next_action,str) or not next_action.strip():raise ValueError('Bounded delivery needs an exact next action')
        if delivery_status not in ('implementation','integration','review','source','external','dependency'):raise ValueError('Invalid delivery status')
        with self.authorized(grant,expected_revision) as (_,slot):
            slot['report']=report_snapshot(self.root,report,slot['scope']);slot.update(state='waiting',note=report,nextAction=next_action,deliveryStatus=delivery_status,blocker=blocker)
        return {'state':'waiting','revision':stable_hash(slot),'reportSha256':slot['report']['sha256']}
    def resume(self,grant,expected_revision):
        with self._writer_lock():
            self._check_pending()
            data=self.snapshot();key=self._key(grant.get('packageId'),grant.get('taskId'));slot=self._slot(data,key);self._auth(slot,grant,('waiting',));self._cas(slot,expected_revision);slot['state']='running';self._commit(data,slot)
        return {'state':'running','revision':stable_hash(slot)}
    def register_verification(self,grant,expected_revision,evidence):
        with self.authorized(grant,expected_revision) as (_,slot):
            task=self.catalog[self._key(grant['packageId'],grant['taskId'])];record=validate_verification(self.root,self.config,task,evidence,slot['scope']);record.update(attempt=slot['attempt'],performedBy=copy.deepcopy(slot['worker']),at=now());slot['verifications'].append(record)
        return {'registered':True,'revision':stable_hash(slot),'tier':record['tier'],'fullTaskAccepted':False}
    def _ended_valid(self,data,key,seen=None):
        seen=set() if seen is None else seen
        if key in seen:return False
        slot=self._slot(data,key)
        if slot.get('state')!='ended' or not slot.get('completion'):return False
        record=slot['completion']
        try:
            if hash_file(safe_path(self.root,record['path'],slot['scope']))!=record['sha256']:return False
            self._check_publication(self.catalog[key],slot)
            validate_completion(self.root,self.config,self.catalog[key],slot,record['path'])
            return all(self._ended_valid(data,d,seen|{key}) for d in self.catalog[key]['dependencies'])
        except (KeyError,ValueError,OSError):return False
    def ended_valid(self,package,task,data=None):
        """Read-only current evidence validity, separate from recorded state."""
        return self._ended_valid(self.snapshot() if data is None else data,self._key(package,task))
    def end(self,grant,expected_revision,evidence):
        with self.authorized(grant,expected_revision) as (data,slot):
            key=self._key(grant['packageId'],grant['taskId']);task=self.catalog[key]
            if any(not self._ended_valid(data,d) for d in task['dependencies']):raise ValueError('Original task dependencies are not currently accepted')
            self._check_publication(task,slot)
            slot['completion']=validate_completion(self.root,self.config,task,slot,evidence);slot['state']='ended';slot.pop('tokenHash',None)
        return {'state':'ended','revision':stable_hash(slot),'fullTaskAccepted':True}
    def _check_publication(self,task,slot):
        targets=task.get('publicTargets',[])
        if not targets and not self.config['policy'].get('requirePublication',False):return
        receipts=[];current=slot
        while current:
            receipts.extend(current.get('integrations',[]));current=current.get('inheritedHandoff') or {}
        covered=set();found=False
        for receipt in receipts:
            if receipt.get('status')!='committed':continue
            artifacts=receipt.get('artifacts',{})
            if not isinstance(artifacts,dict) or not artifacts:continue
            if all(hash_file(safe_path(self.root,path))==sha for path,sha in artifacts.items()):covered.update(artifacts);found=True
        if not found or not set(targets).issubset(covered):raise ValueError('Task public targets need a current matching controlled publication')
    def requeue(self,package,task,owner,client,expected_revision,note,revoke_running=False):
        if self._worker(owner,client)!=self.config['policy']['coordinator']:raise ValueError('Only the configured coordinator may revoke an occupancy')
        with self._writer_lock():
            self._check_pending()
            data=self.snapshot();key=self._key(package,task);slot=self._slot(data,key);self._cas(slot,expected_revision)
            if slot['state'] not in ('running','waiting'):raise ValueError('Only active occupancy may be requeued')
            if slot['state']=='running' and revoke_running is not True:raise ValueError('Running authorization requires explicit revoke_running')
            evidence=report_snapshot(self.root,note,None);old={k:copy.deepcopy(v) for k,v in slot.items() if k not in ('history','tokenHash')};history=copy.deepcopy(slot.get('history',[]));history.append({'mode':'requeue','slot':old,'at':now(),'review':evidence,'terminalUnknown':slot['state']=='running','processStoppedClaimed':False})
            fresh={'state':'idle','worker':None,'attempt':'','generation':slot['generation']+1,'scope':'','sequence':slot['sequence'],'updated':'','contractSha256':slot['contractSha256'],'note':note,'nextAction':'Reuse the preceding artifacts; inspect history before taking','blocker':'','deliveryStatus':'','history':history,'integrations':[],'verifications':[]}
            data['slots'][key]=fresh;self._commit(data,fresh)
        return {'state':'idle','revision':stable_hash(fresh),'revoked':True,'processStoppedClaimed':False}
