@echo off
chcp 65001 >nul
cd /d "%~dp0"
start "" pythonw scripts\panel.py --no-browser
timeout /t 2 /nobreak >nul
start "" http://127.0.0.1:8777/
exit
