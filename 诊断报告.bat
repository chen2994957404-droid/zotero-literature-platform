@echo off
chcp 65001 >nul
cd /d "%~dp0"
python "平台管理\诊断报告.py"
echo.
pause
