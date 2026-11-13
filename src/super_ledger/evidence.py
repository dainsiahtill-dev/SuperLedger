"""Evidence identity checks are strict; they do not invent runtime execution."""
import json
import re
from .config import contract_hash
from .io import safe_path, hash_file


def _json(root,path,scope=None):
    file=safe_path(root,path,scope)
    if not file.is_file():raise ValueError('Evidence file is missing')
    value=json.loads(file.read_bytes())
    if not isinstance(value,dict):raise ValueError('Evidence must be an object')
    return value


def checked_refs(root,refs,*,scope=None,nonempty=True):
    if isinstance(refs,dict):refs=[{'path':p,'sha256':h} for p,h in refs.items()]
    if not isinstance(refs,list) or (nonempty and not refs):raise ValueError('Evidence references are required')
    result={}
    for item in refs:
        if not isinstance(item,dict) or not isinstance(item.get('sha256'),str) or not re.fullmatch('[a-f0-9]{64}',item['sha256']):raise ValueError('Invalid evidence SHA')
        name=item.get('path');path=safe_path(root,name,scope)
        if name in result or hash_file(path)!=item['sha256']:raise ValueError('Evidence reference is duplicated, missing or changed')
        result[name]=item['sha256']
    return result


def report_snapshot(root,path,scope):
    file=safe_path(root,path,scope)
    if file.suffix.lower()!='.md' or not file.is_file():raise ValueError('A scoped Markdown report is required')
    raw=file.read_bytes()
    if not raw.decode('utf-8').strip():raise ValueError('Report is empty')
    return {'path':path,'sha256':hash_file(file)}


def validate_verification(root,config,task,path,scope):
    proof=_json(root,path,scope)
    if proof.get('schema')!='super-ledger/verification@1' or proof.get('contractSha256')!=contract_hash(task):raise ValueError('Verification contract/schema mismatch')
    command=proof.get('command')
    if not isinstance(command,list) or not command or not all(isinstance(x,str) and x for x in command) or type(proof.get('exitCode')) is not int or proof['exitCode']!=0 or type(proof.get('checks')) is not int or proof['checks']<1:raise ValueError('Passing actual command/check receipt is required')
    if proof.get('tier') not in ('module','scene'):raise ValueError('Verification tier must be module or scene')
    inputs=checked_refs(root,proof.get('inputs',{}),nonempty=False)
    artifacts=checked_refs(root,proof.get('artifacts'))
    receipts=checked_refs(root,proof.get('receipts'),scope=scope)
    for receipt in receipts:
        actual=_json(root,receipt,scope)
        if any(actual.get(k)!=proof[k] for k in ('command','exitCode','checks')):raise ValueError('Recorded command/check receipt differs')
    if proof['tier']=='scene':
        runtime=config['project']['runtime']
        if proof.get('method')!=runtime['verificationMethod'] or not isinstance(proof.get('toolCalls'),list) or not proof['toolCalls'] or not all(isinstance(call,(str,dict)) and bool(call) for call in proof['toolCalls']):raise ValueError('Scene proof needs the configured MCP method and tool calls')
        screenshots=checked_refs(root,proof.get('screenshots'),scope=scope)
        for image in screenshots:
            image_path=safe_path(root,image,scope)
            if image_path.suffix.lower() not in ('.png','.jpg','.jpeg','.webp'):raise ValueError('Scene proof needs screenshot artifacts')
            raw=image_path.read_bytes()
            if not (raw.startswith(b'\x89PNG\r\n\x1a\n') or raw.startswith(b'\xff\xd8\xff') or (raw.startswith(b'RIFF') and raw[8:12]==b'WEBP')):raise ValueError('Screenshot bytes are not a supported image')
    return {'path':path,'sha256':hash_file(safe_path(root,path,scope)),'tier':proof['tier'],'contractSha256':proof['contractSha256'],'artifacts':artifacts,'inputs':inputs,'receipts':receipts,'scope':scope,'checks':proof['checks']}


def validate_completion(root,config,task,slot,path):
    scope=slot['scope'];proof=_json(root,path,scope)
    prior=slot.get('inheritedHandoff') or {};submission=prior.get('report') or {}
    if proof.get('schema')!='super-ledger/completion@1' or proof.get('contractSha256')!=contract_hash(task) or proof.get('submissionSha256')!=submission.get('sha256'):raise ValueError('Completion contract/submission mismatch')
    previous=prior.get('worker') or {}
    if not previous.get('owner') or previous['owner']==(slot.get('worker') or {}).get('owner') or prior.get('executionStage')!='implementation':raise ValueError('Completion requires an independent implementation handoff')
    if not submission.get('path') or hash_file(safe_path(root,submission['path']))!=submission.get('sha256'):raise ValueError('Reviewed report has changed')
    clauses=proof.get('acceptance')
    if not isinstance(clauses,list) or len(clauses)!=len(task['acceptance']) or any(not isinstance(row,dict) or row.get('text')!=text or row.get('passed') is not True for row,text in zip(clauses,task['acceptance'])):raise ValueError('Every original acceptance clause must pass in original order')
    refs=checked_refs(root,proof.get('verification'),scope=scope)
    registered={(v['path'],v['sha256']) for v in slot.get('verifications',[])}
    records=[]
    for ref,sha in refs.items():
        if (ref,sha) not in registered:raise ValueError('Completion verification is not registered in this attempt')
        records.append(validate_verification(root,config,task,ref,scope))
    if config['policy']['sceneRequired'] and not any(v['tier']=='scene' for v in records):raise ValueError('Configured runtime scene verification is still missing')
    covered={path for row in records for path in row['artifacts']}
    if not set(task.get('publicTargets',[])).issubset(covered):raise ValueError('Completion does not bind all task public targets')
    consumer=task.get('consumer')
    if consumer and consumer not in covered and not any(consumer in row['inputs'] for row in records):raise ValueError('Actual consumer is not bound to verification')
    return {'path':path,'sha256':hash_file(safe_path(root,path,scope)),'contractSha256':proof['contractSha256'],'submissionSha256':proof['submissionSha256'],'verification':records,'scope':scope}
