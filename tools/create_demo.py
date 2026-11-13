"""Create a labelled demo using real parser execution and independent handoff.

This is a synthetic 4-byte format example, never evidence of a game/runtime.
Grants remain only in this process memory.
"""
from pathlib import Path
import json,subprocess,sys
from super_ledger.config import initialize_project
from super_ledger.engine import Ledger
from super_ledger.io import hash_file
from super_ledger.publication import Publisher

REPO=Path(__file__).resolve().parents[1]
root=REPO/'build/demo-project'
config=json.loads((REPO/'examples/binary-format.json').read_bytes())
config['project'].update(id='super-ledger-demo',name='Super Ledger · 示例逆向项目',description='真实四字节解析器示例 · 有界交付、发布、独立审核与证据分层')
task=config['packages'][0]['tasks'][0]
task['acceptance']=['四字节小端输入2a000000由实际解析器输出42。','截断输入由同一实际解析器拒绝。']
initialize_project(root,config)
ledger=Ledger(root)
def write(path,content):
 p=root/path;p.parent.mkdir(parents=True,exist_ok=True)
 if isinstance(content,str):content=content.encode('utf-8')
 if p.exists():raise ValueError('Do not overwrite demo evidence')
 p.write_bytes(content);return {'path':path,'sha256':hash_file(p)}
def revision(tid='read-header'):return ledger.identity('FORMAT',tid)['revision']
author=ledger.take('FORMAT','read-header','example-implementer','python-cli',revision())
source='def parse(data):\n    if len(data)!=4: raise ValueError("truncated")\n    return int.from_bytes(data,"little")\n'
candidate=write(author['scope']+'/candidate.py',source)
command=[sys.executable,'-c','import runpy;parse=runpy.run_path('+repr(str(root/candidate['path']))+')["parse"];assert parse(bytes.fromhex("2a000000"))==42;print("candidate checked")']
run=subprocess.run(command,capture_output=True,text=True,check=True)
receipt=write(author['scope']+'/publication-check.json',json.dumps({'command':command,'exitCode':run.returncode,'checks':1,'stdout':run.stdout,'stderr':run.stderr}))
target=task['publicTargets'][0]
manifest=write(author['scope']+'/publication.json',json.dumps({'schema':'super-ledger/publication@1','files':{target:{'candidate':candidate['path'],'preimage':None,'postimage':candidate['sha256']}},'dependencies':{},'verification':receipt}))
publication=Publisher(ledger).integrate(author,revision(),manifest['path'])
report=write(author['scope']+'/report.md','# 示例实现交付\n\n实现四字节小端读取，候选真实运行并正式发布。等待另一执行者覆盖截断反例并逐句审核。本示例不代表任何游戏逆向完成。\n')
ledger.wait(author,revision(),report['path'],'由不同执行者运行消费者与截断反例后逐句审核。')
identity=ledger.identity('FORMAT','read-header')
reviewer=ledger.take('FORMAT','read-header','example-reviewer','independent-python',identity['revision'],identity['reportSha256'],True)
driver=write(reviewer['scope']+'/check.py','import runpy\nparse=runpy.run_path('+repr(str(root/target))+')["parse"]\nassert parse(bytes.fromhex("2a000000"))==42\ntry: parse(b"\\x00")\nexcept ValueError: pass\nelse: raise AssertionError("truncation accepted")\nprint("2 assertions passed")\n')
command=[sys.executable,str(root/driver['path'])];run=subprocess.run(command,cwd=root,capture_output=True,text=True,check=True)
check=write(reviewer['scope']+'/check.json',json.dumps({'command':command,'exitCode':run.returncode,'checks':2,'stdout':run.stdout,'stderr':run.stderr}))
verification=write(reviewer['scope']+'/verification.json',json.dumps({'schema':'super-ledger/verification@1','contractSha256':identity['contractSha256'],'tier':'module','command':command,'exitCode':run.returncode,'checks':2,'inputs':{driver['path']:driver['sha256']},'artifacts':{target:hash_file(root/target)},'receipts':[check]}))
ledger.register_verification(reviewer,revision(),verification['path'])
completion=write(reviewer['scope']+'/completion.json',json.dumps({'schema':'super-ledger/completion@1','contractSha256':identity['contractSha256'],'submissionSha256':identity['reportSha256'],'acceptance':[{'text':text,'passed':True} for text in task['acceptance']],'verification':[verification]}))
ledger.end(reviewer,revision(),completion['path'])
second=ledger.take('FORMAT','read-directory','example-next-worker','python-cli',revision('read-directory'))
report=write(second['scope']+'/report.md','# 示例有界交付\n\n已核对前置解析器和索引反例范围。目录记录的具体字段与实际消费者尚未实现，保持OPEN；本轮等待独立接手继续，不能end。\n')
ledger.wait(second,revision('read-directory'),report['path'],'复用已完成头部解析器，只实现一项目录记录读取及越界反例。')
result={'demo':True,'syntheticFormat':True,'project':str(root),'stateCounts':{'ended':1,'waiting':1},'actualParserChecks':2,'publicationId':publication['id'],'unityExecuted':False}
(REPO/'evidence').mkdir(exist_ok=True)
(REPO/'evidence/demo.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))
