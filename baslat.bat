@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv (
  echo Ilk kurulum yapiliyor...
  py -3 -m venv .venv || python -m venv .venv
  .venv\Scripts\python -m pip install -q --upgrade pip
  .venv\Scripts\python -m pip install -q -r requirements.txt
)
start "" http://127.0.0.1:5000
.venv\Scripts\python -m novel_epub %*
pause
