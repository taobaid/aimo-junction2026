"""Single-process web-service entry point. Secrets stay in server configuration."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import sqlite3
import threading
from copy import deepcopy
from functools import lru_cache
from collections.abc import Mapping
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


class DiskFields(Mapping):
    def __init__(self,product,names):self.product=product;self.names=names
    def __getitem__(self,key):
        if key=='names':return self.names
        return self.product.body().get('synkkaData',{})[key]
    def __iter__(self):return iter(self.product.body().get('synkkaData',{}))
    def __len__(self):return len(self.product.body().get('synkkaData',{}))
    def __deepcopy__(self,memo):return deepcopy(self.product.body().get('synkkaData',{}),memo)


class DiskProduct(Mapping):
    """Small product reference; large original fields stay on disk."""
    def __init__(self,catalogue,row):
        self.catalogue=catalogue;self.number=row[0]
        self.fields=json.loads(row[1])
        self.names=json.loads(row[2])
    def body(self):return self.catalogue.load(self.number)
    def __getitem__(self,key):
        if key in self.fields:return self.fields[key]
        if key=='synkkaData' and self.names is not None:return DiskFields(self,self.names)
        return self.body()[key]
    def __iter__(self):return iter(self.body())
    def __len__(self):return len(self.body())
    def __deepcopy__(self,memo):return deepcopy(self.body(),memo)


class DiskCatalogue:
    """List-compatible iteration/indexing without retaining full products."""
    def __init__(self,source):
        self.path=Path(str(source)+'.index.sqlite3')
        temporary=Path(str(self.path)+'.building')
        temporary.unlink(missing_ok=True)
        connection=sqlite3.connect(temporary)
        try:
            connection.execute('PRAGMA cache_size=-2048')
            connection.execute('CREATE TABLE products (number INTEGER PRIMARY KEY, fields TEXT, names TEXT, body TEXT)')
            count=0
            for count,product in enumerate(iter_catalogue(source),1):
                # Small, frequently searched fields avoid reading heavy bodies.
                fields={k:product[k] for k in ('id','deleted','countryOfOrigin','salesUnit','baseUnit','allowedLotSize') if k in product}
                names=product.get('synkkaData',{}).get('names',[]) if isinstance(product.get('synkkaData'),dict) else None
                connection.execute('INSERT INTO products VALUES (?,?,?,?)',(count-1,json.dumps(fields,ensure_ascii=False),json.dumps(names,ensure_ascii=False),json.dumps(product,ensure_ascii=False)))
                if count%500==0:connection.commit()
            if not count:raise ValueError('Catalogue is empty.')
            connection.commit()
        except BaseException:
            connection.close();temporary.unlink(missing_ok=True);raise
        connection.close();temporary.replace(self.path)
        self.count=count;self.local=threading.local()
        self.load=lru_cache(maxsize=32)(self._load)
    def connection(self):
        if not hasattr(self.local,'connection'):
            self.local.connection=sqlite3.connect(self.path)
            self.local.connection.execute('PRAGMA cache_size=-2048')
            self.local.connection.execute('PRAGMA query_only=ON')
        return self.local.connection
    def _load(self,number):
        return json.loads(self.connection().execute('SELECT body FROM products WHERE number=?',(number,)).fetchone()[0])
    def __len__(self):return self.count
    def __iter__(self):
        cursor=self.connection().execute('SELECT number,fields,names FROM products ORDER BY number')
        try:
            for row in cursor:yield DiskProduct(self,row)
        finally:cursor.close()
    def __getitem__(self,index):
        if isinstance(index,slice):return [self[i] for i in range(*index.indices(self.count))]
        if index<0:index+=self.count
        row=self.connection().execute('SELECT number,fields,names FROM products WHERE number=?',(index,)).fetchone()
        if row is None:raise IndexError(index)
        return DiskProduct(self,row)


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
        print('Indexing complete catalogue on disk (low-memory mode)...',flush=True)
        g._catalogue_cache=DiskCatalogue(catalogue)
        print('Catalogue ready: '+str(len(g._catalogue_cache))+' products; complete records remain on disk.',flush=True)
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
