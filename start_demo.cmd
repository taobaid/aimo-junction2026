@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 (
    echo Install Python 3.11 or newer from python.org, then run this file again.
    pause
    exit /b 1
  )
)
.venv\Scripts\python.exe -c "import fastapi,uvicorn,httpx,pydantic; assert int(pydantic.__version__.split('.')[0])==2" >nul 2>&1
if errorlevel 1 (
  .venv\Scripts\python.exe -m pip install -r requirements-lock.txt
  if errorlevel 1 (
    echo Dependency installation failed. Check internet access and try again.
    pause
    exit /b 1
  )
)
.venv\Scripts\python.exe demo.py
pause
