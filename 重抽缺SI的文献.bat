@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
if /i "%~2"=="local" set EXTRACT_PROVIDER=ollama
if "%~1"=="-y" goto run
echo ================================================================
echo  重抽「有补充材料、但当初抽取没读它」的文献
echo.
echo  为什么要重抽：投料量、配比、温度时间几乎只写在补充材料里，
echo  2026-08-28 之前的抽取根本没打开过它（踩坑 #68）。
echo  不重新解析 PDF，不动 Zotero，旧结果会先自动备份。
echo ================================================================
echo.
python 数据抽取\extract_structured.py --si-pending --list
echo.
echo  用哪个模型抽？
echo    [1] 云端 DeepSeek —— 准，快（约半分钟一篇），要密钥有效，花钱（很少）
echo    [2] 本地模型 Ollama —— 免费不限量，慢（约两分钟一篇），准确度低一档
echo        （本地抽的会标成「本地+SI」档，绝不冒充云端结果）
echo.
set /p mode=输入 1 或 2 后回车（直接关窗口=放弃）：
if "%mode%"=="2" set EXTRACT_PROVIDER=ollama
if not "%mode%"=="1" if not "%mode%"=="2" (
  echo 没选，退出。
  pause
  exit /b
)
:run
echo.
echo  开始了。这个窗口要一直开着，跑完会显示结果。
python 数据抽取\extract_structured.py --si-pending > workflow_data\logs\si_rerun.log 2>&1
type workflow_data\logs\si_rerun.log
echo.
echo  完成。日志：workflow_data\logs\si_rerun.log
if "%~1"=="-y" exit /b
pause
