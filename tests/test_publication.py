import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from super_ledger.config import initialize_project
from super_ledger.engine import Ledger
from super_ledger.io import hash_file
from super_ledger.publication import Publisher


class PublicationTests(unittest.TestCase):
    def setUp(self):
        base=Path(__file__).resolve().parents[1]/'build'/'test-tmp';base.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=base);self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        config={'schema':'super-ledger/project@1','project':{'id':'publication-test','name':'Publication','runtime':{'name':'Python','entrypoint':'output/parser.txt','verificationMethod':'shell'}},'phases':[{'id':'core','title':'Core'}],'policy':{'coordinator':{'owner':'coordinator','client':'test'},'publicPaths':['output/'],'sceneRequired':False},'packages':[{'id':'FORMAT','title':'Format','phase':'core','priority':1,'tasks':[{'id':'parse','title':'Parse','objective':'Parse','acceptance':['Parses bytes'],'dependencies':[],'publicTargets':['output/parser.txt'],'consumer':'output/parser.txt'}]}]}
        config['packages'][0]['tasks'][0]['publicTargets'] += ['output/first.txt','output/second.txt']
        initialize_project(self.root,config);self.ledger=Ledger(self.root);identity=self.ledger.identity('FORMAT','parse');self.grant=self.ledger.take('FORMAT','parse','worker','test',identity['revision']);self.scope=self.root/self.grant['scope'];self.publisher=Publisher(self.ledger)
    def rev(self):return self.ledger.identity('FORMAT','parse')['revision']
    def manifest(self,targets=None):
        targets=targets or {'output/parser.txt':b'parser-v1'};files={}
        for index,(target,content) in enumerate(targets.items()):
            candidate=self.scope/('candidate-'+str(index));candidate.write_bytes(content)
            files[target]={'candidate':candidate.relative_to(self.root).as_posix(),'preimage':hash_file(self.root/target),'postimage':hash_file(candidate)}
        result=subprocess.run([sys.executable,'-c','print("publication check")'],capture_output=True,check=False)
        proof=self.scope/'check.json';proof.write_text(json.dumps({'command':[sys.executable,'-c','print("publication check")'],'exitCode':result.returncode,'checks':1}),encoding='utf-8')
        manifest=self.scope/'manifest.json';manifest.write_text(json.dumps({'schema':'super-ledger/publication@1','files':files,'dependencies':{},'verification':{'path':proof.relative_to(self.root).as_posix(),'sha256':hash_file(proof)}}),encoding='utf-8')
        return manifest.relative_to(self.root).as_posix()
    def test_success_and_stale_cas(self):
        revision=self.rev();manifest=self.manifest();receipt=self.publisher.integrate(self.grant,revision,manifest)
        self.assertEqual((self.root/'output/parser.txt').read_bytes(),b'parser-v1');self.assertEqual(receipt['status'],'committed')
        self.assertEqual(self.ledger.snapshot()['slots']['FORMAT/parse']['integrations'][-1]['id'],receipt['id'])
        with self.assertRaises(ValueError):self.publisher.integrate(self.grant,revision,manifest)
    def test_invalid_target_or_proof_never_writes(self):
        for target in ['../escape','.super-ledger/registry.json','super-ledger.json','ledger-work/other.txt','private/secret','output/another-task.txt']:
            with self.subTest(target=target):
                with self.assertRaises(ValueError):self.publisher.integrate(self.grant,self.rev(),self.manifest({target:b'bad'}))
        manifest=self.manifest();(self.scope/'check.json').write_text('{}')
        with self.assertRaises(ValueError):self.publisher.integrate(self.grant,self.rev(),manifest)
        self.assertFalse((self.root/'output/parser.txt').exists())
    def test_recovery_keeps_third_party_content(self):
        manifest=self.manifest({'output/first.txt':b'one','output/second.txt':b'two'});revision=self.rev()
        import super_ledger.publication as publication
        atomic=publication.atomic
        def interrupted(path,content):
            if Path(path)==self.root/'output/second.txt':raise OSError('simulated interruption')
            return atomic(path,content)
        with patch.object(publication,'atomic',interrupted):
            with self.assertRaises(OSError):self.publisher.integrate(self.grant,revision,manifest)
        self.assertTrue((self.root/'.super-ledger/pending-publication.json').is_file())
        pending=json.loads((self.root/'.super-ledger/pending-publication.json').read_bytes())
        (self.root/'output/second.txt').write_bytes(b'external')
        with self.assertRaises(ValueError):self.publisher.recover(self.grant,revision,pending['id'])
        self.assertEqual((self.root/'output/second.txt').read_bytes(),b'external')
        (self.root/'output/second.txt').unlink()
        receipt=self.publisher.recover(self.grant,revision,pending['id'])
        self.assertEqual(receipt['status'],'committed');self.assertEqual((self.root/'output/second.txt').read_bytes(),b'two')
        self.assertFalse((self.root/'.super-ledger/pending-publication.json').exists())


if __name__=='__main__':unittest.main()
