@echo off
chcp 65001 >nul
cd /d "%~dp0"
REM DEEPSEEK_KEY 从系统环境变量读取（已用 setx 永久化）

if "%DEEPSEEK_KEY%"=="" echo [警告] 未设置 DEEPSEEK_KEY（DeepSeek），请先运行: setx DEEPSEEK_KEY "你的密钥"
set PYTHONIOENCODING=utf-8

echo ============================================
echo   用 PRO 版重跑精读（高质量，适合重要文献）
echo ============================================
echo.
echo 说明：日常精读默认用 flash（省钱）。这里用 pro 重跑你觉得
echo       重要、要细品的文献，质量更高。前提是该文献已经跑过
echo       一次精读（解析结果已缓存，重跑不再消耗MineRU）。
echo.

python 文献精读\rerun_pro.py

echo.
set /p num=请输入要用PRO重跑的文献序号（直接回车退出）:
if "%num%"=="" goto end
python 文献精读\rerun_pro.py %num%
echo.
echo 完成！PRO版精读在 workflow_data\summary\ 目录（文件名带 _PRO）

:end
pause
