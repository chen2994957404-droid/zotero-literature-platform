@echo off
chcp 65001 >nul
cd /d "%~dp0"
python "host\panel\open_panel.py"
if errorlevel 1 pause
