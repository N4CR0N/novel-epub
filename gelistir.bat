@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Geliştirici başlatıcısı: uygulamayı kaynak koddan kendi penceresinde açar (kod değişince kapat-aç).
if not exist .venv (
  echo Ilk kurulum yapiliyor...
  py -3 -m venv .venv || python -m venv .venv
)
.venv\Scripts\python -m pip install -q --upgrade pip
.venv\Scripts\python -m pip install -q -r requirements.txt pywebview pytest
start "" .venv\Scripts\pythonw.exe uygulama.py
