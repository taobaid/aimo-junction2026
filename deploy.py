"""Single-process web-service entry point. Secrets stay in server configuration."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler


def setting(name,default=''):return os.environ.get(name,default).strip()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):return None


def iter_catalogue(path):
    """Decode an array one product at a time, without a full-file text copy."""
    decoder=json.JSONDecoder()
    with Path(path).open('r',encoding='utf-8-sig') as source:
        buffer='';done=False
        def fill():
            nonlocal buffer,done
            chunk=source.read(65536)
            if chunk:buffer+=chunk
            else:done=True
        def whitespace():
            nonlocal buffer
            while True:
                buffer=buffer.lstrip()
                if buffer or done:return
                fill()
        whitespace()
        if not buffer.startswith('['):raise ValueError('Catalogue must be a JSON array.')
        buffer=buffer[1:];whitespace()
        if buffer.startswith(']'):
            buffer=buffer[1:]
        else:
            while True:
                while True:
                    try:item,end=decoder.raw_decode(buffer);break
                    except json.JSONDecodeError:
                        if done:raise ValueError('Invalid or truncated catalogue JSON.') from None
                        fill()
                if not isinstance(item,dict):raise ValueError('Catalogue products must be JSON objects.')
                buffer=buffer[end:]
                yield item
                whitespace()
                if buffer.startswith(']'):
                    buffer=buffer[1:];break
                if not buffer.startswith(','):raise ValueError('Invalid catalogue array separator.')
                buffer=buffer[1:];whitespace()
        whitespace()
        if buffer:raise ValueError('Unexpected data after catalogue array.')


def download_catalogue(url,target,expected_sha=''):
    """Owner-configured private HTTPS object, never a model/user supplied URL."""
    parsed=urlsplit(url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('AIMO_CATALOG_URL must be an HTTPS download URL without embedded username/password.')
    target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
    temp=None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent,delete=False) as f:
            temp=Path(f.name);digest=hashlib.sha256();size=0
            with build_opener(NoRedirect()).open(Request(url,headers={'Accept':'application/json'}),timeout=60) as response:
                while chunk:=response.read(1024*1024):
                    size+=len(chunk)
                    if size>300*1024*1024:raise ValueError('Catalogue download exceeds the 300 MB startup limit.')
                    digest.update(chunk);f.write(chunk)
        if expected_sha and digest.hexdigest()!=expected_sha.lower():raise ValueError('Catalogue checksum does not match AIMO_CATALOG_SHA256.')
        count=sum(1 for _ in iter_catalogue(temp))
        if not count:raise ValueError('Catalogue download must be a nonempty JSON product array.')
        temp.replace(target)
    except (HTTPError,URLError,OSError,ValueError) as exc:
        # Never echo signed URLs, provider bodies or credentials to public logs.
        code=exc.code if isinstance(exc,HTTPError) else None
        raise RuntimeError('Private catalogue startup download failed'+(' (HTTP '+str(code)+')' if code else '')+'. Check its HTTPS URL, expiry, JSON format and optional checksum.') from None
    finally:
        if temp and temp.exists():temp.unlink()


def create_hosted_app():
    mode=setting('DEMO_MODE','live').lower()
    if mode not in {'live','sample'}:raise RuntimeError('DEMO_MODE must be live or sample.')
    credentials={name:setting(name) for name in ('AIMO_AGENT_TOKEN','AIMO_REVIEWER_TOKEN')}
    if any(len(v)<16 for v in credentials.values()) or len(set(credentials.values()))!=2:
        raise RuntimeError('Configure distinct AIMO_AGENT_TOKEN and AIMO_REVIEWER_TOKEN values of at least 16 characters in the hosting dashboard.')
    if mode=='sample':
        from demo import create_demo
        folder=tempfile.TemporaryDirectory(prefix='hosted-sample-')
        g,_,_=create_demo(Path(folder.name)/'sample.sqlite3',credentials=credentials)
        g.app.state.sample_storage=folder
        return g.app
    if not setting('AIMO_API_KEY') or not setting('ANTHROPIC_API_KEY'):
        raise RuntimeError('Live hosting requires AIMO_API_KEY and ANTHROPIC_API_KEY on the server. Use DEMO_MODE=sample only for fixed sample data.')
    catalogue=Path(setting('AIMO_CATALOG','/tmp/trusted-trade-catalogue.json'))
    if not catalogue.is_file():
        if not setting('AIMO_CATALOG_URL'):raise RuntimeError('Provide a private AIMO_CATALOG file or an owner-configured AIMO_CATALOG_URL for live hosting.')
        download_catalogue(setting('AIMO_CATALOG_URL'),catalogue,setting('AIMO_CATALOG_SHA256'))
    os.environ['AIMO_CATALOG']=str(catalogue)
    os.environ.setdefault('RECIPE_PROVIDER','anthropic')
    os.environ.setdefault('AIMO_DB','/tmp/trusted-trade-purchases.sqlite3')
    import aimo_api as g
    # Populate the existing application's cache without its read_text/json.loads
    # full-file allocation. Endpoints continue using the same complete products.
    if getattr(g,'_catalogue_cache',None) is None:
        print('Loading complete catalogue with bounded input buffering...',flush=True)
        g._catalogue_cache=list(iter_catalogue(catalogue))
    if not g.catalogue():raise RuntimeError('Live catalogue is empty.')
    g.app.state.offline_demo=False
    return g.app


def main():
    import uvicorn
    app=create_hosted_app()
    port=int(setting('PORT','8000'))
    print('Trusted Trade web service starting. Access tokens are configured privately, not printed.',flush=True)
    uvicorn.run(app,host='0.0.0.0',port=port,workers=1)

if __name__=='__main__':main()
