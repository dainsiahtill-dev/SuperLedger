"""Filesystem and canonical identities adapted from the original workbench."""
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
import hashlib
import json
import os
import re
import tempfile
import time


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')


def digest(content):return hashlib.sha256(content).hexdigest()
def stable_hash(value):return digest(canonical(value))
def hash_file(path):
    path=Path(path)
    return digest(path.read_bytes()) if path.is_file() else None


def safe_root(root):
    """Project roots and their ancestors must be physical directories, not links."""
    path=Path(root).absolute()
    for current in reversed([path,*path.parents]):
        if current.is_symlink() or getattr(current,'is_junction',lambda:False)():raise ValueError('Linked project root is forbidden')
    return path.resolve()


def safe_path(root,relative,scope=None):
    root=safe_root(root)
    if not isinstance(relative,str) or not relative or '\\' in relative or ':' in relative or PurePosixPath(relative).is_absolute():
        raise ValueError('Expected a portable relative path')
    parts=relative.split('/')
    if any(p in ('','.','..') or p[-1:] in (' ','.') or any(ord(c)<32 for c in p) or re.match(r'^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)',p,re.I) for p in parts):
        raise ValueError('Unsafe path component')
    current=root
    for part in parts:
        if current.is_dir():
            aliases=[p.name for p in current.iterdir() if p.name.casefold()==part.casefold() and p.name!=part]
            if aliases:raise ValueError('Case-colliding path')
        current=current/part
        if current.is_symlink() or getattr(current,'is_junction',lambda:False)():raise ValueError('Linked paths are forbidden')
    if not current.resolve().is_relative_to(root):raise ValueError('Path escapes project')
    if scope is not None:
        bound=safe_path(root,scope) if isinstance(scope,str) else Path(scope).resolve()
        if not current.resolve().is_relative_to(bound):raise ValueError('Artifact outside current attempt')
    return current


def atomic(path,content):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.ledger-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:stream.write(content);stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)


@contextmanager
def locked(path,timeout=60):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+b') as stream:
        stream.seek(0,2)
        if stream.tell()==0:stream.write(b'\0');stream.flush()
        deadline=time.monotonic()+timeout
        while True:
            stream.seek(0)
            try:
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic()>=deadline:raise TimeoutError('Ledger writer lock is busy')
                time.sleep(.05)
        try:yield
        finally:
            stream.seek(0)
            if os.name=='nt':msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(stream.fileno(),fcntl.LOCK_UN)
