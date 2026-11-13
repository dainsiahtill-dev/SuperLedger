import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from super_ledger.config import initialize_project
from super_ledger.engine import Ledger


class RunCheckTests(unittest.TestCase):
    def setUp(self):
        base=Path(__file__).resolve().parents[1]/'build'/'test-tmp';base.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=base);self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        initialize_project(self.root,{'schema':'super-ledger/project@1','project':{'id':'runcheck','name':'Check','runtime':{'name':'CLI','entrypoint':'check','verificationMethod':'shell'}},'phases':[{'id':'core','title':'Core'}],'policy':{'coordinator':{'owner':'root','client':'tests'},'publicPaths':['src/']},'packages':[{'id':'FORMAT','title':'Format','phase':'core','tasks':[{'id':'header','title':'Header','objective':'Header','acceptance':['Read header'],'dependencies':[]}]}]})
        self.ledger=Ledger(self.root);self.grant=self.ledger.take('FORMAT','header','执行者','tests',self.rev());self.scope=self.root/self.grant['scope']
    def rev(self):return self.ledger.identity('FORMAT','header')['revision']
    def runcheck(self,path,code,grant=None):
        return subprocess.run([sys.executable,'-m','super_ledger','--project',str(self.root),'run-check','--receipt',path,'--grant-stdin','--expected-revision',self.rev(),'--',sys.executable,'-c',code],input=json.dumps(grant or self.grant),text=True,encoding='utf-8',capture_output=True,cwd=self.root)
    def test_real_success_and_nonzero_receipts(self):
        for name,code,expected in [('good','print("actual")',0),('bad','raise SystemExit(3)',3)]:
            rel=self.grant['scope']+'/'+name+'.json';result=self.runcheck(rel,code);self.assertEqual(result.returncode,expected,result.stderr)
            receipt=json.loads((self.root/rel).read_bytes());self.assertEqual(receipt['exitCode'],expected)
            for path,sha in receipt['output'].items():self.assertEqual(hashlib.sha256((self.root/path).read_bytes()).hexdigest(),sha)
    def test_collision_rejected_before_command(self):
        (self.scope/'same.stdout.txt').write_text('old')
        result=self.runcheck(self.grant['scope']+'/same.json','open("executed", "w").write("bad")')
        self.assertNotEqual(result.returncode,0);self.assertFalse((self.root/'executed').exists());self.assertEqual((self.scope/'same.stdout.txt').read_text(),'old')
    def test_forged_or_out_of_scope_grant_rejected(self):
        bad={**self.grant,'token':'invalid'};result=self.runcheck(self.grant['scope']+'/bad.json','open("executed", "w").write("bad")',bad)
        self.assertNotEqual(result.returncode,0);self.assertFalse((self.root/'executed').exists())
        result=self.runcheck('ledger-work/OTHER/task/attempts/notmine/check.json','print("bad")')
        self.assertNotEqual(result.returncode,0)
    def test_isolated_python_pipe_is_utf8(self):
        source=str(Path(__file__).resolve().parents[1]/'src')
        code='import sys;sys.path.insert(0,sys.argv[1]);from super_ledger.cli import main;raise SystemExit(main(sys.argv[2:]))'
        run=subprocess.run([sys.executable,'-I','-c',code,source,'--project',str(self.root),'show','FORMAT','header','--identity'],capture_output=True)
        self.assertEqual(run.returncode,0)
        identity=json.loads(run.stdout.decode('utf-8'))
        self.assertEqual(identity['worker']['owner'],'执行者')


if __name__=='__main__':unittest.main()
