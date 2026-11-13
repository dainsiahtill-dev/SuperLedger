"""Loopback, read-only HTTP API. Only bundled assets and attempt evidence served."""
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime, timezone
from urllib.parse import urlsplit, unquote, parse_qs
import json
import mimetypes
import os
import re
import threading
import uuid
from .projection import ViewStore, SnapshotExpired, build, canonical, sha, clean, ID
from .io import safe_path

STATIC=Path(__file__).parent/'static'

class WorkbenchServer(ThreadingHTTPServer):
    daemon_threads=True;allow_reuse_address=True
    def __init__(self,root,port,host='127.0.0.1',ledger=None):
        if host not in ('127.0.0.1','localhost','::1'):raise ValueError('Read-only ledger service is loopback-only')
        self.reload_ledger=ledger is None
        if ledger is None:
            from .engine import Ledger
            ledger=Ledger(Path(root))
        self.ledger=ledger;self.root=Path(root).resolve();self.store=ViewStore(self.root,ledger.config)
        self.identity={'schema':'super-ledger/health@1','pid':os.getpid(),'instanceId':uuid.uuid4().hex,'projectId':ledger.config['project']['id'],'startedAt':datetime.now(timezone.utc).isoformat()}
        self.refresh_lock=threading.Lock();self.last_revision=None;self.audit=None
        super().__init__((host,port),WorkbenchHandler);self.identity['port']=self.server_port
        self.refresh()
    def refresh(self):
        with self.refresh_lock:
            # Each CLI catalog transaction can add packages/tasks. A new Ledger
            # still validates the persistent config/registry binding and journal.
            from .engine import Ledger
            if self.reload_ledger:self.ledger=Ledger(self.root)
            bundle=build(self.ledger)
            observed=sha(canonical(bundle))
            if self.last_revision!=observed or not self.store.manifest_path.exists():
                self.store.publish(bundle);self.last_revision=observed
            manifest=self.store.manifest()
            if manifest['authorityRevision']!=bundle['authorityRevision'] or manifest['projectId']!=bundle['projectId']:
                raise ValueError('Snapshot authority differs from the successful audit')
            for name in ('summary','tasks'):self.store.read(name,manifest['snapshotId'])
            # Refresh observations without producing another immutable cache
            # generation. Failed authority/evidence/shard reads never advance it.
            audit={'auditedAt':datetime.now(timezone.utc).isoformat(),
                   'snapshotId':manifest['snapshotId'],'authorityRevision':bundle['authorityRevision'],
                   'observationRevision':observed}
            self.audit=audit
            return {**manifest,'auditedAt':audit['auditedAt']}
    def bootstrap(self):
        config=self.ledger.config;project=config['project']
        return {'projectId':project['id'],'title':project['name'],'subtitle':project.get('description','逆向项目 · 证据驱动的任务交接'),'phases':config.get('phases',[]),'runtime':project.get('runtime',{}),'projectRoot':str(self.root),'commandPrefix':['python','-m','super_ledger','--project',str(self.root)],'progressDoc':'','maintenanceSupported':False}

class WorkbenchHandler(BaseHTTPRequestHandler):
    server_version='SuperLedger/1'
    def log_message(self,*args): pass
    def _send(self,raw,status=200,kind='application/json; charset=utf-8',immutable=False):
        etag='"'+sha(raw)+'"'
        if status==200 and self.headers.get('If-None-Match')==etag:
            self.send_response(304);self.send_header('ETag',etag);self.end_headers();return
        self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(raw)));self.send_header('ETag',etag)
        self.send_header('X-Content-Type-Options','nosniff');self.send_header('Cache-Control','private, max-age=31536000, immutable' if immutable else 'no-store, max-age=0');self.end_headers()
        if self.command!='HEAD':self.wfile.write(raw)
    def _json(self,value,status=200,immutable=False):self._send(canonical(clean(value)),status,immutable=immutable)
    def do_HEAD(self):self.do_GET()
    def do_GET(self):
        try:self._get()
        except (BrokenPipeError,ConnectionResetError):pass
        except SnapshotExpired as error:self._json({'error':str(error),'code':'snapshot-expired','recover':'refresh-manifest'},410)
        except (ValueError,KeyError,TypeError) as error:self._json({'error':str(error),'readOnly':True,'writeAuthorized':False},400)
        except (OSError,TimeoutError) as error:self._json({'error':str(error),'readOnly':True,'writeAuthorized':False},503)
    def _get(self):
        uri=urlsplit(self.path);path=unquote(uri.path);query=parse_qs(uri.query)
        if path=='/healthz':self._json(self.server.identity);return
        if path in ('/readyz','/api/workbench/manifest'):
            m=self.server.refresh()
            readiness={'ready':True,'status':'current','authorityMatches':True,'auditedAt':m['auditedAt']}
            self._json({**readiness,'service':self.server.identity} if path=='/readyz' else {**m,'readiness':readiness,'service':self.server.identity});return
        if path=='/config.js':self._send(('globalThis.WorkbenchConfig='+json.dumps(self.server.bootstrap(),ensure_ascii=False).replace('<','\\u003c')+';').encode('utf-8'),kind='application/javascript; charset=utf-8');return
        if path=='/api/workbench/maintenance':self._json({'schema':'super-ledger/maintenance@1','tasks':[],'receipts':[],'pending':None,'supported':False});return
        if path.startswith('/api/workbench/identity/'):
            key=path.removeprefix('/api/workbench/identity/')
            if not re.fullmatch(ID+'/'+ID,key):raise ValueError('Invalid task identity')
            identity=self.server.ledger.identity(*key.split('/'))
            fields={'schema','readOnly','admissionEvaluated','packageId','taskId','state','attempt','generation','revision','revisionKind','contractSha256','reportPath','reportSha256','reportError','capturedAt'}
            self._json({**{k:v for k,v in identity.items() if k in fields},'writeAuthorized':False});return
        prefix='/api/workbench/snapshots/'
        if path.startswith(prefix):
            sid,name=path.removeprefix(prefix).split('/',1);value=self.server.store.read(name,sid)
            if name.startswith(('history/','releases/')):
                items=value['items'];offset=int(query.get('offset',['0'])[0]);limit=int(query.get('limit',['20'])[0])
                if offset<0 or not 1<=limit<=250:raise ValueError('Invalid pagination')
                value={**value,'items':items[offset:offset+limit],'total':len(items),'offset':offset,'limit':limit,'nextOffset':offset+limit if offset+limit<len(items) else None}
            self._json(value,immutable=True);return
        if path.startswith('/api/evidence/'):
            relative=path.removeprefix('/api/evidence/')
            if not re.fullmatch(r'ledger-work/'+ID+'/'+ID+'/attempts/'+ID+r'/(?:[^/]+/)*[^/]+',relative):raise ValueError('Only attempt evidence can be viewed')
            if any(p.startswith('.') or p.casefold() in {'grant.json','registry.json'} for p in relative.split('/')):raise ValueError('Private evidence path')
            p=safe_path(self.server.root,relative)
            if not p.is_file():self._json({'error':'Evidence not found'},404);return
            allowed={'.md','.json','.txt','.log','.png','.jpg','.jpeg','.webp','.svg','.csv'}
            if p.suffix.lower() not in allowed:raise ValueError('Unsupported evidence type')
            mime='text/plain; charset=utf-8' if p.suffix.lower() in {'.md','.txt','.log','.svg'} else mimetypes.guess_type(p.name)[0] or 'application/octet-stream'
            self._send(p.read_bytes(),kind=mime);return
        asset='index.html' if path=='/' else path.removeprefix('/')
        if asset not in {'index.html','app.css','app.js','workbench-data.js','README.md'}:self._json({'error':'Not found'},404);return
        p=STATIC/asset
        self._send(p.read_bytes(),kind=(mimetypes.guess_type(asset)[0] or 'text/plain')+'; charset=utf-8')

def make_server(root,port,host='127.0.0.1',ledger=None):return WorkbenchServer(root,port,host,ledger)

def serve(root:Path,host='127.0.0.1',port=5198):
    server=make_server(root,port,host)
    print(json.dumps(server.identity),flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
