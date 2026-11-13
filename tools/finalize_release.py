"""Finalize a versioned release proof without rewriting previous releases."""
from pathlib import Path
import argparse,hashlib,json,tomllib

ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--installation',type=Path,required=True);parser.add_argument('--browser',type=Path,required=True);args=parser.parse_args()
 version=tomllib.loads((ROOT/'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
 receipt_path=max((ROOT/'evidence').glob('verification-*/receipt.json'),key=lambda p:p.stat().st_mtime_ns)
 receipt=json.loads(receipt_path.read_bytes());assert receipt['exitCode']==0 and all(c['exitCode']==0 for c in receipt['commands'])
 for relative,digest in receipt['inputs'].items():assert sha(ROOT/relative)==digest,relative
 installation=ROOT/args.installation;browser=ROOT/args.browser;proof=json.loads(installation.read_bytes());wheel=ROOT/('releases/super_ledger-'+version+'-py3-none-any.whl')
 assert proof['exitCode']==0 and proof['wheelSha256']==sha(wheel) and browser.stat().st_size>10000
 files=[receipt_path,installation,browser,wheel]
 result={'schema':'super-ledger/release@1','version':version,'exitCode':0,'pythonTests':receipt['commands'][0]['checks'],'sourceInputs':receipt['inputs'],'evidence':{p.relative_to(ROOT).as_posix():sha(p) for p in files},'runtimeAcceptance':'Ledger CLI/HTTP/browser acceptance only; no game runtime acceptance'}
 target=ROOT/('evidence/release-'+version+'.json');raw=json.dumps(result,ensure_ascii=False,indent=2).encode('utf-8')
 if target.exists() and target.read_bytes()!=raw:raise ValueError('Versioned proof already exists with different content; preserve it')
 target.write_bytes(raw);print(json.dumps({'exitCode':0,'version':version,'pythonTests':result['pythonTests'],'proof':target.relative_to(ROOT).as_posix()}))
if __name__=='__main__':main()
