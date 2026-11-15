"""Load private config.env locally, check prerequisites, then start the live gateway."""
from pathlib import Path
import os
import runpy

ROOT=Path(__file__).resolve().parent

def load_config(path):
    for number,line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(),1):
        line=line.strip()
        if not line or line.startswith('#'):continue
        name,separator,value=line.partition('=')
        if not separator or not name.strip().replace('_','').isalnum():
            raise ValueError('Invalid config.env entry on line '+str(number))
        value=value.strip()
        if len(value)>=2 and value[0]==value[-1] and value[0] in {'"',"'"}:value=value[1:-1]
        os.environ.setdefault(name.strip(),value)

def main():
    file=ROOT/'config.env'
    if file.exists():load_config(file)
    if not os.environ.get('AIMO_API_KEY','').strip():
        raise SystemExit('Set AIMO_API_KEY in config.env or this terminal. See LAPTOP_SETUP.md. For no-key testing use python demo.py.')
    catalogue=Path(os.environ.get('AIMO_CATALOG',str(ROOT/'valio_aimo_junction26_product_data.json'))).expanduser()
    if not catalogue.is_absolute():catalogue=ROOT/catalogue
    if not catalogue.is_file():raise SystemExit('Official catalogue missing. Place the organiser-supplied JSON beside run_live.py or set AIMO_CATALOG. For sample data use python demo.py.')
    os.environ['AIMO_CATALOG']=str(catalogue)
    if not os.environ.get('ANTHROPIC_API_KEY','').strip():
        print('Claude key is absent. Product lookup can work, but new recipe requests need ANTHROPIC_API_KEY.',flush=True)
    runpy.run_path(str(ROOT/'aimo_api.py'),run_name='__main__')

if __name__=='__main__':main()
