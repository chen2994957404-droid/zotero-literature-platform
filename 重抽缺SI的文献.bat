@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
if "%~1"=="-y" goto run
echo ================================================================
echo  重抽「有补充材料、但当初抽取没读它」的文献
echo.
echo  为什么要重抽：投料量、配比、温度时间几乎只写在补充材料里，
echo  2026-08-28 之前的抽取根本没打开过它（踩坑 #68）。
echo  每篇一次 DeepSeek 调用，不重新解析 PDF，不动 Zotero。
echo ================================================================
echo.
python 数据抽取\extract_structured.py --si-pending --list
echo.
echo  上面是待重抽清单。回车开始重抽，或关掉本窗口放弃。
pause
:run
python 数据抽取\extract_structured.py --si-pending > workflow_data\logs\si_rerun.log 2>&1
type workflow_data\logs\si_rerun.log
echo.
echo  完成。日志：workflow_data\logs\si_rerun.log
if "%~1"=="-y" exit /b
pause
