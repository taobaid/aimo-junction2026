#!/usr/bin/env sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
if ! .venv/bin/python -c "import fastapi,uvicorn,httpx,pydantic; assert int(pydantic.__version__.split('.')[0])==2" >/dev/null 2>&1; then
  .venv/bin/python -m pip install -r requirements-lock.txt
fi
exec .venv/bin/python demo.py
