import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
import sys
import os
import subprocess
from datetime import datetime, timezone, timedelta
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))

try:
    from super_ledger.projection import ViewStore, SnapshotExpired, build
    from super_ledger.server import make_server
except ImportError:
    ViewStore = None


class FakeLedger:
    def __init__(self, root):
        self.root = root
        self.config = {'project': {'id': 'demo', 'name': '协议逆向', 'runtime': {'name': 'Native', 'verificationMethod': 'Debugger MCP'}}, 'phases': [{'id': 'decode', 'title': '解码'}], 'policy': {'snapshotKeep': 2}, 'packages': [{'id': 'FORMAT', 'title': '文件格式', 'phase': 'decode', 'tasks': [{'id': 'parse_header', 'title': '读取头部', 'objective': '解析', 'acceptance': ['准确'], 'dependencies': []}]}]}
        self.catalog = {'FORMAT/parse_header': {**self.config['packages'][0]['tasks'][0], 'packageId': 'FORMAT'}}
    def snapshot(self):
        return {'schema': 'super-ledger/registry@1', 'projectId': 'demo', 'version': 0, 'slots': {}}
    def identity(self, p, t):
        return {'schema': 'super-ledger/identity@1', 'readOnly': True, 'admissionEvaluated': False, 'packageId': p, 'taskId': t, 'state': 'idle', 'revision': '0'*64, 'tokenHash': 'never-broadcast'}


class WebTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(ViewStore, 'standalone web projection must exist')
        workspace=Path(__file__).resolve().parents[1]/'.test-work'
        workspace.mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=workspace)
        self.root = Path(self.tmp.name)
        self.ledger = FakeLedger(self.root)
        self.store = ViewStore(self.root, self.ledger.config)
    def tearDown(self):
        if hasattr(self, 'tmp'): self.tmp.cleanup()
    def test_generic_catalog_and_no_grants(self):
        b = build(self.ledger)
        m = self.store.publish(b)
        self.assertEqual(self.store.read('tasks', m['snapshotId'])['items'][0]['taskId'], 'parse_header')
        self.assertEqual(b['summary']['counts']['total'], 1)
        self.assertNotIn('tokenHash', json.dumps(b))
    def test_retention_expires_old_but_keeps_current(self):
        ids = [self.store.publish(build(self.ledger))['snapshotId'] for _ in range(4)]
        self.assertEqual(len([p for p in self.store.snapshots.iterdir() if not p.name.startswith('.')]), 2)
        with self.assertRaises(SnapshotExpired): self.store.read('summary', ids[0])
        self.assertEqual(self.store.read('summary', ids[-1])['snapshotId'], ids[-1])
    def test_current_damage_is_not_normal_expiry(self):
        m = self.store.publish(build(self.ledger))
        (self.store.snapshots/m['snapshotId']/'tasks.json').unlink()
        with self.assertRaises(FileNotFoundError) as cm: self.store.read('tasks', m['snapshotId'])
        self.assertNotIsInstance(cm.exception, SnapshotExpired)
    def test_sha_tampering_rejected(self):
        m = self.store.publish(build(self.ledger))
        (self.store.snapshots/m['snapshotId']/'tasks.json').write_text('{}')
        with self.assertRaises(ValueError): self.store.read('tasks', m['snapshotId'])
    def test_http_whitelist_fresh_identity_and_evidence(self):
        evidence = self.root/'ledger-work/FORMAT/parse_header/attempts/a/report.md'
        evidence.parent.mkdir(parents=True); evidence.write_text('proof')
        (self.root/'secret.txt').write_text('secret')
        server = make_server(self.root, 0, ledger=self.ledger)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        base = 'http://127.0.0.1:'+str(server.server_port)
        try:
            for route in ['/secret.txt', '/.super-ledger/registry.json', '/api/evidence/super-ledger.json', '/api/evidence/ledger-work/%2e%2e/secret.txt']:
                with self.assertRaises(urllib.error.HTTPError) as cm: urllib.request.urlopen(base+route)
                self.assertIn(cm.exception.code, (400,403,404))
                cm.exception.close()
            with urllib.request.urlopen(base+'/api/workbench/identity/FORMAT/parse_header') as r: identity=json.load(r)
            self.assertFalse(identity['writeAuthorized']); self.assertNotIn('tokenHash', identity)
            with urllib.request.urlopen(base+'/api/evidence/ledger-work/FORMAT/parse_header/attempts/a/report.md') as r: self.assertEqual(r.read(), b'proof')
            with urllib.request.urlopen(base+'/') as r: self.assertIn(b'Super Ledger', r.read())
        finally: server.shutdown();server.server_close();thread.join()

    def test_manifest_reaudits_report_after_external_change(self):
        report=self.root/'ledger-work/FORMAT/parse_header/attempts/a/report.md'
        report.parent.mkdir(parents=True);report.write_text('first')
        from super_ledger.projection import sha
        state={'schema':'super-ledger/registry@1','projectId':'demo','version':0,'slots':{'FORMAT/parse_header':{'state':'waiting','report':{'path':report.relative_to(self.root).as_posix(),'sha256':sha(report.read_bytes())}}}}
        self.ledger.snapshot=lambda: state
        server=make_server(self.root,0,ledger=self.ledger)
        try:
            old=server.store.manifest()['snapshotId'];report.write_text('changed');server.refresh()
            self.assertNotEqual(old,server.store.manifest()['snapshotId'])
        finally:server.server_close()

    def _link(self,target,path,directory=False):
        try:path.symlink_to(target,target_is_directory=directory)
        except OSError as error:
            if os.name!='nt' or not directory:self.skipTest('Symbolic links unavailable: '+str(error))
            quote=lambda value: "'"+str(value).replace("'","''")+"'"
            command='New-Item -ItemType Junction -Path '+quote(path)+' -Target '+quote(target)+' | Out-Null'
            result=subprocess.run(['rtk','proxy','powershell','-NoProfile','-Command',command],capture_output=True)
            if result.returncode:self.skipTest('Directory links unavailable')

    def test_read_rejects_snapshot_directory_link(self):
        m=self.store.publish(build(self.ledger));folder=self.store.snapshots/m['snapshotId']
        outside=self.root/'linked-snapshot';folder.rename(outside);self._link(outside,folder,True)
        with self.assertRaises(ValueError):self.store.read('summary',m['snapshotId'])

    def test_prune_checks_base_before_opening_lock(self):
        self.store.publish(build(self.ledger));outside=self.root/'linked-cache'
        self.store.base.rename(outside);(outside/'.build.lock').unlink();self._link(outside,self.store.base,True)
        with self.assertRaises(ValueError):self.store.prune()
        self.assertFalse((outside/'.build.lock').exists(),'must not create lock through a linked cache')

    def test_manifest_rejects_pointer_file_link(self):
        self.store.publish(build(self.ledger));outside=self.root/'pointer-copy.json'
        self.store.manifest_path.rename(outside);self._link(outside,self.store.manifest_path)
        with self.assertRaises(ValueError):self.store.manifest()

    def test_prune_rejects_build_lock_file_link(self):
        self.store.publish(build(self.ledger));outside=self.root/'external-lock';outside.write_bytes(b'')
        lock=self.store.base/'.build.lock';lock.unlink();self._link(outside,lock)
        with self.assertRaises(ValueError):self.store.prune()
        self.assertEqual(outside.read_bytes(),b'')

    def test_read_rejects_shard_file_link(self):
        m=self.store.publish(build(self.ledger));shard=self.store.snapshots/m['snapshotId']/'summary.json'
        outside=self.root/'summary-copy.json';shard.rename(outside);self._link(outside,shard)
        with self.assertRaises(ValueError):self.store.read('summary',m['snapshotId'])

    def test_http_reaudits_same_snapshot_without_rebuilding_cache(self):
        server=make_server(self.root,0,ledger=self.ledger)
        old=(datetime.now(timezone.utc)-timedelta(days=2)).isoformat()
        original=server.store.manifest();sid=original['snapshotId']
        server.store.manifest_path.write_text(json.dumps({**original,'generatedAt':old,'auditedAt':old}))
        before={p.name for p in server.store.snapshots.iterdir()}
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(server.server_port)
        try:
            with urllib.request.urlopen(base+'/api/workbench/manifest') as response:value=json.load(response)
            self.assertEqual(value['snapshotId'],sid);self.assertEqual(value['generatedAt'],old)
            self.assertLess((datetime.now(timezone.utc)-datetime.fromisoformat(value['auditedAt'])).total_seconds(),5)
            self.assertTrue(value['readiness']['ready'])
            with urllib.request.urlopen(base+'/readyz') as response:ready=json.load(response)
            self.assertLess((datetime.now(timezone.utc)-datetime.fromisoformat(ready['auditedAt'])).total_seconds(),5)
            self.assertEqual(before,{p.name for p in server.store.snapshots.iterdir()})
            self.assertEqual(server.store.manifest()['generatedAt'],old)
        finally:server.shutdown();server.server_close();thread.join()

    def test_failed_reaudit_does_not_advance_success_timestamp(self):
        server=make_server(self.root,0,ledger=self.ledger)
        try:
            previous=server.audit.copy()
            def fail():raise ValueError('Authority damaged')
            self.ledger.snapshot=fail
            with self.assertRaises(ValueError):server.refresh()
            self.assertEqual(server.audit,previous)
        finally:server.server_close()

if __name__ == '__main__': unittest.main()
