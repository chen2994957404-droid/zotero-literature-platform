@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo ============================================
echo   用 PRO 模型重跑精读（更准，适合重要文献）
echo ============================================
echo.
echo 日常精读用 flash（省钱）。这里用 pro 重跑你觉得重要、
echo 要细品的文献。前提是该文献已经跑过一次精读
echo （解析结果有缓存，重跑不再消耗 MineRU 额度）。
echo.
echo 密钥已存在系统凭据库，无需在这里设置。
echo.
python 文献精读\rerun_pro.py
echo.
set /p num=请输入要用PRO重跑的文献序号（直接回车退出）:
if "%num%"=="" goto end
python 文献精读\rerun_pro.py %num%
echo.
echo 完成！结果在 workflow_data\library\ 对应文献目录下。
:end
pause
