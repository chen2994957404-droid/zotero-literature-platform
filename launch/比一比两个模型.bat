@echo off
chcp 65001 >nul
cd /d "%~dp0.."
set PYTHONIOENCODING=utf-8
python -m tools.extract.compare_models --n 3
pause
