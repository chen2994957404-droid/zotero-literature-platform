@echo off
chcp 65001 >nul
cd /d "%~dp0"
python "平台管理\打开面板.py"
if errorlevel 1 pause
