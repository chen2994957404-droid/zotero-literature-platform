@echo off
echo %date% %time% bat-ran >> "%~dp0_launch_probe.log"
chcp 65001 >nul
cd /d "%~dp0"
start "" /min python 平台管理\panel_launch.py
timeout /t 2 /nobreak >nul
start "" http://127.0.0.1:8777/
exit
