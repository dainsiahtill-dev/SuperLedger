"""Explicit portable project contracts; no source-repository discovery."""
from pathlib import Path
import copy
import json
import re
from .io import atomic, canonical, safe_path, safe_root, stable_hash, locked

CONFIG='super-ledger.json'
ID=re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}')


def identifier(value):
    if not isinstance(value,str) or not ID.fullmatch(value):raise ValueError('Invalid project/package/task identifier')
    return value


def contract_hash(task):return stable_hash(task)


def validate_config(value):
    data=copy.deepcopy(value)
    if not isinstance(data,dict) or data.get('schema')!='super-ledger/project@1':raise ValueError('Unsupported project schema')
    project=data.get('project')
    if not isinstance(project,dict):raise ValueError('Missing project')
    identifier(project.get('id'))
    if not isinstance(project.get('name'),str) or not project['name'].strip():raise ValueError('Project needs a name')
    runtime=project.get('runtime')
    if not isinstance(runtime,dict) or any(not isinstance(runtime.get(k),str) or not runtime[k].strip() for k in ('name','entrypoint','verificationMethod')):raise ValueError('Runtime needs name, entrypoint and verificationMethod')
    phases=data.get('phases')
    if not isinstance(phases,list) or not phases:raise ValueError('At least one phase is required')
    phase_ids=[]
    for phase in phases:
        if not isinstance(phase,dict) or not isinstance(phase.get('title'),str) or not phase['title'].strip():raise ValueError('Invalid phase')
        phase_ids.append(identifier(phase.get('id')))
    if len(set(p.casefold() for p in phase_ids))!=len(phase_ids):raise ValueError('Duplicate phase')
    policy=data.get('policy')
    if not isinstance(policy,dict):raise ValueError('Policy is required')
    coord=policy.get('coordinator')
    if not isinstance(coord,dict) or any(not isinstance(coord.get(k),str) or not coord[k].strip() for k in ('owner','client')):raise ValueError('Coordinator owner/client are required')
    paths=policy.get('publicPaths')
    if not isinstance(paths,list) or not paths:raise ValueError('Explicit publicPaths are required')
    for prefix in paths:
        if not isinstance(prefix,str) or not prefix.endswith('/') or prefix.startswith(('.super-ledger/','ledger-work/')):raise ValueError('publicPaths must be safe directory prefixes')
        safe_path(Path.cwd(),prefix.rstrip('/'))
    if len({p.casefold() for p in paths})!=len(paths):raise ValueError('Duplicate public path')
    policy.setdefault('sceneRequired',False);policy.setdefault('snapshotKeep',5);policy.setdefault('snapshotBytes',268435456)
    if type(policy['sceneRequired']) is not bool or type(policy['snapshotKeep']) is not int or not 1<=policy['snapshotKeep']<=100 or type(policy['snapshotBytes']) is not int or policy['snapshotBytes']<1:raise ValueError('Invalid scene/snapshot policy')
    if 'requirePublication' in policy and type(policy['requirePublication']) is not bool:raise ValueError('requirePublication must be boolean')
    packages=data.get('packages')
    if not isinstance(packages,list):raise ValueError('Packages must be a list')
    catalog={};package_ids=set()
    for package in packages:
        pid=identifier(package.get('id'))
        if pid.casefold() in package_ids:raise ValueError('Duplicate package')
        package_ids.add(pid.casefold())
        if package.get('phase') not in phase_ids or not isinstance(package.get('title'),str) or not package['title'].strip():raise ValueError('Package phase/title is invalid')
        package.setdefault('priority',0)
        if type(package['priority']) is not int:raise ValueError('Priority must be an integer')
        tasks=package.get('tasks')
        if not isinstance(tasks,list):raise ValueError('Package tasks must be a list')
        local=set()
        for task in tasks:
            if not isinstance(task,dict):raise ValueError('Task must be an object')
            tid=identifier(task.get('id'))
            if tid.casefold() in local:raise ValueError('Duplicate task')
            local.add(tid.casefold())
            if any(not isinstance(task.get(k),str) or not task[k].strip() for k in ('title','objective')):raise ValueError('Task title/objective are required')
            if not isinstance(task.get('acceptance'),list) or not task['acceptance'] or any(not isinstance(s,str) or not s.strip() for s in task['acceptance']):raise ValueError('Exact nonempty acceptance clauses are required')
            task.setdefault('role','implementation');task.setdefault('dependencies',[]);task.setdefault('publicTargets',[]);task.setdefault('counterexamples',[]);task.setdefault('consumer','')
            if task['role'] not in ('implementation','gate') or not isinstance(task['dependencies'],list) or not all(isinstance(d,str) for d in task['dependencies']):raise ValueError('Invalid task role/dependencies')
            if len(set(task['dependencies']))!=len(task['dependencies']):raise ValueError('Duplicate dependency')
            if not isinstance(task['publicTargets'],list):raise ValueError('Invalid publicTargets')
            for target in task['publicTargets']:
                safe_path(Path.cwd(),target)
                if not any(target.startswith(p) for p in paths):raise ValueError('Task target outside publicPaths')
            catalog[pid+'/'+tid]=task
    def visit(key,visiting,done):
        if key in visiting:raise ValueError('Task dependency cycle')
        if key in done:return
        visiting.add(key)
        for dep in catalog[key]['dependencies']:
            if dep not in catalog:raise ValueError('Unknown dependency '+dep)
            visit(dep,visiting,done)
        visiting.remove(key);done.add(key)
    done=set()
    for key in catalog:visit(key,set(),done)
    return data


def load_config(root):return validate_config(json.loads(safe_path(root,CONFIG).read_bytes()))


def catalog_for(config):
    return {p['id']+'/'+t['id']:{**copy.deepcopy(t),'packageId':p['id']} for p in config['packages'] for t in p['tasks']}


def initialize_project(root,config_dict):
    from .catalog import initialize_catalog
    initialize_catalog(root,validate_config(config_dict))
