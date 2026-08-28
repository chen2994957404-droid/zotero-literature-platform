@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
python 数据抽取\试一试本地模型.py --n 3
pause
