"""SHA-addressed immutable history; caller holds writer lock for commit."""
from pathlib import Path
import copy
import json
import re
from .io import atomic, canonical, digest, stable_hash, safe_path, safe_root

BLOB='$ledgerBlob'
EXTERNAL={'history','integrations','verifications'}


class RegistryStore:
    def __init__(self,root):
        self.root=safe_root(root);self.validate_paths()
    def validate_paths(self):
        self.base=safe_path(self.root,'.super-ledger');self.path=safe_path(self.root,'.super-ledger/registry.json');self.objects=safe_path(self.root,'.super-ledger/objects');self.lock=safe_path(self.root,'.super-ledger/writer.lock')
    def _object(self,sha):return safe_path(self.root,'.super-ledger/objects/'+sha+'.json')
    def physical(self):
        self.validate_paths()
        value=json.loads(self.path.read_bytes())
        if not isinstance(value,dict) or value.get('schema')!='super-ledger/storage@1' or not isinstance(value.get('body'),dict):raise ValueError('Unsupported registry storage')
        return value
    def _expand(self,value,stack=None):
        stack=set() if stack is None else stack
        if isinstance(value,dict):
            if BLOB in value:
                sha=value[BLOB]
                if set(value)!={BLOB} or not isinstance(sha,str) or not re.fullmatch('[a-f0-9]{64}',sha) or sha in stack:raise ValueError('Invalid history reference')
                try:raw=self._object(sha).read_bytes()
                except OSError as error:raise ValueError('Missing immutable history '+sha) from error
                if digest(raw)!=sha:raise ValueError('Immutable history SHA mismatch')
                return self._expand(json.loads(raw),stack|{sha})
            return {k:self._expand(v,stack) for k,v in value.items()}
        if isinstance(value,list):return [self._expand(v,stack) for v in value]
        return value
    def load(self):
        physical=self.physical();logical=self._expand(physical['body'])
        if logical.get('schema')!='super-ledger/registry@1' or not isinstance(logical.get('slots'),dict) or stable_hash(logical)!=physical.get('authorityRevision'):raise ValueError('Logical registry authority mismatch')
        return logical
    def _pack(self,value):
        if isinstance(value,dict):
            result={}
            for key,item in value.items():
                if key==BLOB:raise ValueError('Reserved storage reference')
                packed=self._pack(item)
                if key in EXTERNAL and item:
                    raw=canonical(packed);sha=digest(raw);path=self._object(sha)
                    if path.exists() and digest(path.read_bytes())!=sha:raise ValueError('Existing history object is corrupt')
                    if not path.exists():atomic(path,raw)
                    result[key]={BLOB:sha}
                else:result[key]=packed
            return result
        if isinstance(value,list):return [self._pack(v) for v in value]
        return value
    def commit(self,data):
        self.validate_paths()
        if data.get('schema')!='super-ledger/registry@1':raise ValueError('Unsupported logical schema')
        body=self._pack(data)
        if self._expand(body)!=data:raise ValueError('Storage roundtrip differs')
        atomic(self.path,canonical({'schema':'super-ledger/storage@1','authorityRevision':stable_hash(data),'body':body})+b'\n')
    def observe_current(self):
        self.validate_paths()
        raw=self.path.read_bytes();physical=json.loads(raw)
        if physical.get('schema')!='super-ledger/storage@1' or not isinstance(physical.get('body',{}).get('slots'),dict):raise ValueError('Unsupported registry metadata')
        body=physical['body'];slots={}
        for key,slot in body['slots'].items():
            if not isinstance(slot,dict) or BLOB in slot:raise ValueError('Current slots must be inline')
            slots[key]={k:copy.deepcopy(v) for k,v in slot.items() if k not in {'tokenHash','history','integrations','verifications','inheritedHandoff'}}
        return {'schema':body.get('schema'),'projectId':body.get('projectId'),'configSha256':body.get('configSha256'),'version':body.get('version'),'slots':slots,'readOnly':True,'admissionEvaluated':False,'historyValidated':False,'physicalSha256':digest(raw)}
