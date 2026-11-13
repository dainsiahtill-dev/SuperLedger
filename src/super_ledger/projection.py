"""Audited read-only snapshots. Observation never authorizes a task mutation.

Adapted from the Spore workbench immutable-view protocol; project rules come
only from the standalone Ledger/configuration.
"""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import shutil
import uuid
from .io import atomic, locked as _cache_lock, safe_path

ID = r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}'

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')

def sha(raw): return hashlib.sha256(raw).hexdigest()
def now(): return datetime.now(timezone.utc).isoformat()

def clean(value):
    if isinstance(value, dict):
        return {k: clean(v) for k,v in value.items() if k not in {'token','tokenHash','content','historyRef','rosterCanonical'}}
    if isinstance(value, list): return [clean(v) for v in value]
    return value

class SnapshotExpired(FileNotFoundError): pass

class ViewStore:
    def __init__(self, root, config=None):
        self.root=Path(root).resolve(); self.base=self.root/'.super-ledger/view'
        self.snapshots=self.base/'snapshots'; self.manifest_path=self.base/'view.json'
        self.policy=(config or {}).get('policy',{})

    def _safe_cache(self):
        for p in (self.base,self.snapshots,self.manifest_path,self.base/'.build.lock'):
            self._path(p)

    def _path(self,path):
        """Check every lexical ancestor and the target before any cache I/O."""
        return safe_path(self.root,Path(path).relative_to(self.root).as_posix())

    def manifest(self):
        self._safe_cache()
        m=json.loads(self._path(self.manifest_path).read_bytes())
        if m.get('schema')!='super-ledger/workbench-view@1': raise ValueError('Invalid view schema')
        if not re.fullmatch('[a-f0-9]{32}',m.get('snapshotId','')):raise ValueError('Invalid current snapshot identity')
        return m

    def publish(self,bundle):
        self._safe_cache()
        with _cache_lock(self._path(self.base/'.build.lock')):
            self._safe_cache()
            sid=uuid.uuid4().hex; staging=self._path(self.snapshots/('.building-'+sid))
            payloads={'summary':bundle['summary'],'tasks':{'items':bundle['tasks'],'total':len(bundle['tasks'])}}
            for kind, source in [('details','details'),('history','histories'),('releases','releases')]:
                for key,value in bundle.get(source,{}).items():
                    if not re.fullmatch(ID+'/'+ID,key): raise ValueError('Invalid task key')
                    payloads[kind+'/'+key]=value if isinstance(value,dict) else {'items':value}
            files={}
            for name,body in payloads.items():
                value={**clean(body),'schema':'super-ledger/workbench-'+name.split('/')[0]+'@1','snapshotId':sid}
                if '/' in name:value['taskKey']=name.split('/',1)[1]
                raw=canonical(value);atomic(self._path(staging/(name+'.json')),raw);files[name]={'sha256':sha(raw),'bytes':len(raw)}
            manifest={'schema':'super-ledger/workbench-view@1','snapshotId':sid,'generatedAt':now(),'auditedAt':now(),'admissionEvaluated':False,'authorityRevision':bundle['authorityRevision'],'projectId':bundle['projectId'],'files':files}
            atomic(self._path(staging/'manifest.json'),canonical(manifest))
            for name,meta in files.items():
                if sha(self._path(staging/(name+'.json')).read_bytes())!=meta['sha256']: raise ValueError('Prepared shard changed')
            self._safe_cache();self._path(staging).rename(self._path(self.snapshots/sid))
            pointer={**manifest,'files':{k:v for k,v in files.items() if k in ('summary','tasks')}}
            atomic(self._path(self.manifest_path),canonical(pointer));self._prune_locked()
            return pointer

    def _prune_locked(self):
        self._safe_cache(); current=self.manifest()['snapshotId']
        keep=self.policy.get('snapshotKeep',5);budget=self.policy.get('snapshotBytes',268435456)
        if type(keep) is not int or keep<1 or type(budget) is not int or budget<1: raise ValueError('Invalid cache policy')
        entries=[]
        for folder in self.snapshots.iterdir():
            if not folder.is_dir() or not re.fullmatch(r'(?:[a-f0-9]{32}|\.building-[a-f0-9]{32})',folder.name):continue
            self._path(folder)
            for parent,dirs,files in os.walk(folder,followlinks=False):
                for name in dirs+files:
                    self._path(Path(parent)/name)
            if folder.is_symlink() or getattr(folder,'is_junction',lambda:False)() or folder.resolve().parent!=self.snapshots.resolve(): raise ValueError('Unsafe cache directory')
            if folder.name.startswith('.building-'):shutil.rmtree(self._path(folder));continue
            size=sum(self._path(p).stat().st_size for p in folder.rglob('*') if p.is_file());entries.append((folder,size,folder.stat().st_mtime_ns))
        total=sum(x[1] for x in entries);count=len(entries);removed=[]
        for folder,size,_ in sorted(entries,key=lambda x:x[2]):
            if count<=keep and total<=budget:break
            if folder.name==current:continue
            self._safe_cache();shutil.rmtree(self._path(folder));total-=size;count-=1;removed.append(folder.name)
        return {'remainingSnapshots':count,'remainingBytes':total,'budgetExceeded':total>budget,'removed':removed}

    def prune(self):
        self._safe_cache()
        with _cache_lock(self._path(self.base/'.build.lock')):
            self._safe_cache();return self._prune_locked()

    def read(self,name,sid):
        self._safe_cache()
        if not re.fullmatch('[a-f0-9]{32}',sid):raise ValueError('Invalid snapshot')
        if name not in ('summary','tasks') and not re.fullmatch(r'(details|history|releases)/'+ID+'/'+ID,name):raise ValueError('Invalid shard')
        folder=self._path(self.snapshots/sid)
        try:
            m=json.loads(self._path(folder/'manifest.json').read_bytes());raw=self._path(folder/(name+'.json')).read_bytes()
        except FileNotFoundError:
            if not folder.exists() and sid!=self.manifest()['snapshotId']:raise SnapshotExpired('Snapshot expired; refresh manifest')
            raise
        if m.get('snapshotId')!=sid or sha(raw)!=m['files'][name]['sha256']:raise ValueError('Shard SHA mismatch')
        value=json.loads(raw)
        if value.get('snapshotId')!=sid:raise ValueError('Shard generation mismatch')
        return value

def _file_current(root, report):
    if not isinstance(report,dict) or not report.get('path'):return False
    try:
        p=safe_path(root,report['path'])
        return p.is_file() and sha(p.read_bytes())==report.get('sha256')
    except (OSError,ValueError):return False

def _verification_current(ledger,task,record):
    from .evidence import validate_verification
    try:
        return _file_current(ledger.root,record) and bool(validate_verification(ledger.root,ledger.config,task,record['path'],record['scope']))
    except (OSError,ValueError,KeyError):return False

def _integration_current(root,record):
    artifacts=record.get('artifacts',{})
    return record.get('status')=='committed' and isinstance(artifacts,dict) and bool(artifacts) and all(_file_current(root,{'path':p,'sha256':h}) for p,h in artifacts.items())

def build(ledger):
    data=ledger.snapshot();config=ledger.config;rows=[];details={};histories={};releases={};packages=[]
    counts={k:0 for k in ['total','everDelivered','delivered','integrated','currentAttemptIntegrated','verified','currentVerified','sceneVerified','currentSceneVerified','ended']}
    freshness={'current':0,'needs-revalidation':0,'unverified':0};plans=[];batch=[]
    for package in config['packages']:
        pid=package['id'];remaining=[];implementation=0
        packages.append({k:package.get(k) for k in ['id','title','phase','priority','group']})
        for key,task in ledger.catalog.items():
            if task.get('packageId')!=pid:continue
            tid=task['id'];slot=data.get('slots',{}).get(key,{});state=slot.get('state','idle');report=slot.get('report')
            report_ok=_file_current(ledger.root,report);history=slot.get('history',[])
            previous=[h.get('slot',{}) for h in history]
            integrations=[i for h in previous for i in h.get('integrations',[])]+slot.get('integrations',[])
            integrations=[{**i,'artifactState':'current' if _integration_current(ledger.root,i) else 'changed'} for i in integrations]
            verifications=[v for h in previous for v in h.get('verifications',[])]+slot.get('verifications',[])
            verifications=[{**v,'artifactState':'current' if _verification_current(ledger,task,v) else 'changed','report':{'path':v.get('path',''),'sha256':v.get('sha256','')}} for v in verifications]
            verified=bool(verifications);scene=any(v.get('tier')=='scene' for v in verifications)
            current_verified=any(v['artifactState']=='current' for v in verifications)
            milestones={'delivered':state=='waiting' and report_ok,'everDelivered':bool(report or any(h.get('report') for h in previous)),'integrated':bool(integrations),'currentAttemptIntegrated':any(i.get('attempt')==slot.get('attempt') and i['artifactState']=='current' for i in integrations),'verified':verified,'currentVerified':current_verified,'sceneVerified':scene,'currentSceneVerified':any(v.get('tier')=='scene' and v['artifactState']=='current' for v in verifications),'ended':state=='ended'}
            lane='closed' if state=='ended' else 'active' if state=='running' else 'package-review' if task.get('role')=='gate' else 'handoff-repair' if state=='waiting' and not report_ok else 'independent-review' if state=='waiting' and slot.get('deliveryStatus')=='review' else 'publication-review' if state=='waiting' and slot.get('deliveryStatus')=='integration' else 'bounded-implementation'
            plan={'lane':lane,'responsibleRole':'independent-reviewer' if lane=='independent-review' else 'coordinator' if lane in ('package-review','active','handoff-repair') else 'worker','nextDeliverable':slot.get('nextAction') or task.get('objective') or task['title'],'currentGap':slot.get('blocker',''),'reuseReport':report.get('path','') if report else '', 'workstream':{'phase':package.get('phase',''),'label':package['title']}}
            blockers=[d for d in task.get('dependencies',[]) if data.get('slots',{}).get(d,{}).get('state')!='ended']
            ended_status='not-ended'
            if state=='ended':ended_status='current' if hasattr(ledger,'ended_valid') and ledger.ended_valid(pid,tid,data) else 'needs-revalidation' if slot.get('completion') else 'unverified'
            row={'packageId':pid,'taskId':tid,'title':task['title'],'role':task.get('role','implementation'),'state':state,'worker':clean(slot.get('worker',{})),'attempt':slot.get('attempt'),'generation':slot.get('generation'),'updated':slot.get('updated'),'delivery':{'recorded':report_ok,'status':slot.get('deliveryStatus',''),'nextAction':slot.get('nextAction',''),'blocker':slot.get('blocker','')},'reportPath':report.get('path','') if report else '', 'reportSha256':report.get('sha256','') if report else '', 'reportError':'Report missing or changed' if report and not report_ok else '', 'blockers':blockers,'milestones':milestones,'executionPlan':plan,'endedStatus':{'status':ended_status},'admissionEvaluated':False,'workPriority':package.get('priority',99)}
            rows.append(row);histories[key]=history;releases[key]=integrations
            base=['python','-m','super_ledger','--project',str(ledger.root)]
            commands={'identity':base+['show',pid,tid,'--identity'],'inspect':base+['show',pid,tid]}
            if state=='waiting' and report_ok:commands['takeHandoff']=base+['take-handoff',pid,tid,'--owner','<different-actual-owner>','--client','<actual-client>','--expected-revision','<fresh-revision>','--report-sha','<fresh-report-sha>']
            inherited=clean(slot.get('inheritedHandoff'))
            if inherited:inherited={**inherited,'submission':inherited.get('report')}
            details[key]={'task':task,'package':package,'slot':clean(slot),'identity':row,'executionPlan':plan,'currentReport':report if report_ok else None,'reportError':row['reportError'],'inheritedHandoff':inherited,'historyCount':len(history),'integrations':integrations,'verifications':verifications,'acceptanceChecklist':[{'text':x,'status':'not-reviewed-here'} for x in task.get('acceptance',[])],'commands':commands}
            counts['total']+=1
            for name,value in milestones.items():counts[name]+=int(bool(value))
            if state=='ended':freshness[ended_status]+=1
            else:remaining.append(tid)
            if task.get('role')!='gate':implementation+=1
            if len(batch)<3 and state in ('idle','waiting') and not blockers and task.get('role')!='gate':batch.append({'packageId':pid,'taskId':tid,'nextDeliverable':plan['nextDeliverable']})
        plans.append({'packageId':pid,'remainingOriginalTasks':remaining,'implementationTasks':implementation})
    return {'projectId':config['project']['id'],'authorityRevision':sha(canonical(data)),'summary':{'counts':counts,'packages':packages,'endedFreshness':freshness,'execution':{'privateBatch':batch,'packages':plans}},'tasks':rows,'details':details,'histories':histories,'releases':releases}
