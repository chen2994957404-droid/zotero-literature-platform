@echo off
chcp 65001 >nul
cd /d "%~dp0.."
start "" /min python -m tools.deepread.watchdog
exit
