import copy,json,tempfile,unittest
from pathlib import Path
from super_ledger.config import initialize_project
from super_ledger.engine import Ledger
from super_ledger.io import hash_file,safe_path

def config():
    return {'schema':'super-ledger/project@1','project':{'id':'core-test','name':'测试','runtime':{'name':'Reader','entrypoint':'src/read.py','verificationMethod':'test-mcp'}},'phases':[{'id':'decode','title':'解码'}],'policy':{'coordinator':{'owner':'chief','client':'test'},'publicPaths':['src/'],'sceneRequired':False},'packages':[{'id':'format','title':'格式','phase':'decode','priority':1,'tasks':[{'id':'header','title':'头部','objective':'读取头部','acceptance':['读取有效头部','拒绝截断输入'],'dependencies':[],'role':'implementation','publicTargets':['src/read.py']}]}]}

class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);initialize_project(self.root,config());self.ledger=Ledger(self.root)
    def tearDown(self):self.tmp.cleanup()
    def take(self,owner='worker'):
        i=self.ledger.identity('format','header');return self.ledger.take('format','header',owner,'test',i['revision'])
    def current(self):return self.ledger.identity('format','header')['revision']
    def write(self,path,text):
        p=self.root/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text,encoding='utf-8');return path
    def test_claim_token_and_cas(self):
        g=self.take()
        with self.assertRaises(ValueError):self.take('racer')
        note=self.write(g['scope']+'/report.md','work');old=g['revision']
        with self.assertRaises(ValueError):self.ledger.progress({**g,'token':'bad'},old,note)
        self.ledger.progress(g,old,note)
        with self.assertRaises(ValueError):self.ledger.wait(g,old,note,'review')
        self.assertNotIn(g['token'],(self.root/'.super-ledger/registry.json').read_text())
    def test_wait_resume_then_handoff_revokes_old_grant(self):
        g=self.take();note=self.write(g['scope']+'/report.md','work');self.ledger.wait(g,self.current(),note,'review');self.ledger.resume(g,self.current());self.ledger.wait(g,self.current(),note,'review');i=self.ledger.identity('format','header')
        with self.assertRaises(ValueError):self.ledger.take('format','header','worker','test',i['revision'],i['reportSha256'],True)
        with self.assertRaises(ValueError):self.ledger.take('format','header','reviewer','test',i['revision'],'0'*64,True)
        review=self.ledger.take('format','header','reviewer','test',i['revision'],i['reportSha256'],True)
        with self.assertRaises(ValueError):self.ledger.resume(g,self.current())
        self.assertNotEqual(g['attempt'],review['attempt'])
    def test_independent_exact_completion(self):
        g=self.take();note=self.write(g['scope']+'/report.md','work');self.ledger.wait(g,self.current(),note,'review');i=self.ledger.identity('format','header');r=self.ledger.take('format','header','reviewer','test',i['revision'],i['reportSha256'],True)
        artifact=self.write('src/read.py','print(1)');receipt={'command':['python','src/read.py'],'exitCode':0,'checks':2};rp=self.write(r['scope']+'/run.json',json.dumps(receipt))
        proof={'schema':'super-ledger/verification@1','contractSha256':i['contractSha256'],'tier':'module',**receipt,'inputs':{},'artifacts':{artifact:hash_file(self.root/artifact)},'receipts':[{'path':rp,'sha256':hash_file(self.root/rp)}]};vp=self.write(r['scope']+'/verify.json',json.dumps(proof));self.ledger.register_verification(r,self.current(),vp)
        c={'schema':'super-ledger/completion@1','contractSha256':i['contractSha256'],'submissionSha256':i['reportSha256'],'acceptance':[{'text':t,'passed':True} for t in config()['packages'][0]['tasks'][0]['acceptance']],'verification':[{'path':vp,'sha256':hash_file(self.root/vp)}]};cp=self.write(r['scope']+'/complete.json',json.dumps(c));bad=copy.deepcopy(c);bad['acceptance'].reverse();bp=self.write(r['scope']+'/bad.json',json.dumps(bad))
        with self.assertRaises(ValueError):self.ledger.end(r,self.current(),bp)
        with self.assertRaises(ValueError):self.ledger.end(r,self.current(),cp)
        with self.ledger.authorized(r,self.current()) as (_,slot):slot['integrations'].append({'id':'test-publisher','status':'committed','artifacts':{artifact:hash_file(self.root/artifact)},'attempt':r['attempt']})
        self.ledger.end(r,self.current(),cp);self.assertEqual(self.ledger.identity('format','header')['state'],'ended')
    def test_config_cycle_and_overwrite(self):
        c=config();c['packages'][0]['tasks'][0]['dependencies']=['format/header']
        with tempfile.TemporaryDirectory() as p:
            with self.assertRaises(ValueError):initialize_project(Path(p),c)
        with self.assertRaises(ValueError):initialize_project(self.root,config())
    def test_bad_history_blocks_writers(self):
        g=self.take();note=self.write(g['scope']+'/report.md','work');self.ledger.wait(g,self.current(),note,'review');i=self.ledger.identity('format','header');r=self.ledger.take('format','header','reviewer','test',i['revision'],i['reportSha256'],True)
        objects=list((self.root/'.super-ledger/objects').glob('*.json'));self.assertTrue(objects);objects[0].write_text('{}');self.ledger.candidates('other','test')
        with self.assertRaises(ValueError):self.ledger.snapshot()
    def test_pending_publication_blocks_general_mutation(self):
        g=self.take();note=self.write(g['scope']+'/report.md','work');self.write('.super-ledger/pending-publication.json','{}')
        with self.assertRaisesRegex(ValueError,'pending'):self.ledger.progress(g,self.current(),note)
        with self.ledger.authorized(g,self.current(),allow_pending=True) as (_,slot):slot['publisherProbe']=True
    def test_requeue_revokes_grant_preserves_history_without_process_claim(self):
        g=self.take();note=self.write('review.md','administrative review')
        with self.assertRaises(ValueError):self.ledger.requeue('format','header','worker','test',self.current(),note,True)
        with self.assertRaises(ValueError):self.ledger.requeue('format','header','chief','test',self.current(),note)
        result=self.ledger.requeue('format','header','chief','test',self.current(),note,True)
        self.assertFalse(result['processStoppedClaimed']);self.assertEqual('idle',result['state'])
        with self.assertRaises(ValueError):self.ledger.resume(g,self.current())
        self.assertTrue(self.ledger.snapshot()['slots']['format/header']['history'][-1]['terminalUnknown'])
    def test_path_guards_and_changed_config(self):
        for bad in ('../escape','C:/escape','src/../escape','CON/file','src/file.','src\\bad'):
            with self.assertRaises(ValueError):safe_path(self.root,bad)
        self.write('src/Read.py','x')
        with self.assertRaises(ValueError):safe_path(self.root,'src/read.py')
        g=self.take();note=self.write(g['scope']+'/report.md','work');c=json.loads((self.root/'super-ledger.json').read_bytes());c['project']['name']='changed';self.write('super-ledger.json',json.dumps(c))
        with self.assertRaisesRegex(ValueError,'contracts/policy changed'):self.ledger.progress(g,g['revision'],note)
    def test_false_receipt_and_scene_without_mcp_rejected(self):
        g=self.take();artifact=self.write('src/read.py','x');receipt={'command':['python','check.py'],'exitCode':0,'checks':1};rp=self.write(g['scope']+'/run.json',json.dumps({**receipt,'exitCode':1}))
        v={'schema':'super-ledger/verification@1','contractSha256':self.ledger.identity('format','header')['contractSha256'],'tier':'module',**receipt,'inputs':{},'artifacts':{artifact:hash_file(self.root/artifact)},'receipts':[{'path':rp,'sha256':hash_file(self.root/rp)}]};vp=self.write(g['scope']+'/verify.json',json.dumps(v))
        with self.assertRaisesRegex(ValueError,'receipt differs'):self.ledger.register_verification(g,self.current(),vp)
        self.write(rp,json.dumps(receipt));v['receipts'][0]['sha256']=hash_file(self.root/rp);v['tier']='scene';self.write(vp,json.dumps(v))
        with self.assertRaisesRegex(ValueError,'MCP method'):self.ledger.register_verification(g,self.current(),vp)
    def test_reloaded_ledger_rejects_changed_original_policy(self):
        c=json.loads((self.root/'super-ledger.json').read_bytes());c['policy']['sceneRequired']=True;self.write('super-ledger.json',json.dumps(c));fresh=Ledger(self.root)
        with self.assertRaisesRegex(ValueError,'configuration contract'):fresh.snapshot()
        with self.assertRaisesRegex(ValueError,'configuration contract'):fresh.candidates('worker','test')
    def test_metadata_link_rejected_before_external_writes(self):
        import os
        external=self.root/'external';external.mkdir();linked=self.root/'linked-project';linked.mkdir()
        try:os.symlink(external,linked/'.super-ledger',target_is_directory=True)
        except OSError:self.skipTest('OS does not permit symlink creation')
        try:
            with self.assertRaises(ValueError):initialize_project(linked,config())
            self.assertEqual([],list(external.iterdir()))
        finally:(linked/'.super-ledger').unlink()
    def test_candidates_prioritize_prerequisite_before_alphabetical_id(self):
        c=config();task=copy.deepcopy(c['packages'][0]['tasks'][0]);task.update(id='directory',dependencies=['format/header']);c['packages'][0]['tasks'].insert(0,task);other=self.root/'another';initialize_project(other,c)
        result=Ledger(other).candidates('worker','test')
        self.assertEqual(['header','directory'],[t['taskId'] for t in result['tasks']]);self.assertFalse(result['admissionEvaluated'])

if __name__=='__main__':unittest.main()
