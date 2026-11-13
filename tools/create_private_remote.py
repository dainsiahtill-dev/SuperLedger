"""Optional maintainer utility: create this repository's private GitHub remote.

Uses the existing Git credential helper in memory. Never prints or persists
credentials, never guesses another account, and never overwrites a remote.
Not imported by the ledger package.
"""
from pathlib import Path
import json,os,subprocess,urllib.request,urllib.error

ROOT=Path(__file__).resolve().parents[1]
EXPECTED_OWNER='dainsiahtill-dev'
def git(*args,input=None):return subprocess.run(['rtk','proxy','git',*args],cwd=ROOT,input=input,capture_output=True,check=True,env={**os.environ,'GIT_TERMINAL_PROMPT':'0','GCM_INTERACTIVE':'never'}).stdout
if git('remote').strip():raise SystemExit('A remote already exists; preserve it and inspect manually')
git('rev-parse','HEAD')
raw=git('credential','fill',input=b'protocol=https\nhost=github.com\n\n')
credential=dict(line.split('=',1) for line in raw.decode('utf-8').splitlines() if '=' in line)
token=credential.get('password')
if not token:raise SystemExit('Existing Git credential helper did not authorize GitHub; no repository created')
def api(path,data=None):
 request=urllib.request.Request('https://api.github.com'+path,data=json.dumps(data).encode() if data is not None else None,headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','Content-Type':'application/json','User-Agent':'super-ledger-maintainer'},method='POST' if data is not None else 'GET')
 with urllib.request.urlopen(request,timeout=20) as response:return json.load(response)
try:
 profile=api('/user')
 if profile.get('login','').casefold()!=EXPECTED_OWNER.casefold():raise SystemExit('Authenticated account differs from the existing source repository owner; no remote created')
 try:repo=api('/repos/'+EXPECTED_OWNER+'/super-ledger')
 except urllib.error.HTTPError as error:
  if error.code!=404:raise
  repo=api('/user/repos',{'name':'super-ledger','description':'Independent evidence-gated task ledger for reverse-engineering projects','private':True,'auto_init':False})
 if repo.get('private') is not True or repo.get('owner',{}).get('login','').casefold()!=EXPECTED_OWNER.casefold():raise SystemExit('Unexpected remote ownership/visibility; local repository preserved')
 url=repo['clone_url']
 if url!='https://github.com/'+EXPECTED_OWNER+'/super-ledger.git':raise SystemExit('Unexpected remote URL')
 git('remote','add','origin',url)
 print(json.dumps({'remote':url,'private':True,'createdOrVerified':True}))
except urllib.error.HTTPError as error:raise SystemExit('GitHub request rejected with HTTP '+str(error.code)+'; credentials not logged')
finally:
 token=None;credential.clear();raw=b''
