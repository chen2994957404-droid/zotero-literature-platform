@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo   正在更新平台，请勿关闭窗口…
echo.
if not exist "平台管理\更新平台.py" (
  echo   ** 找不到 平台管理\更新平台.py **
  echo   先在项目文件夹里手动跑一次 git pull，再双击本文件。
  echo.
  pause
  exit /b 1
)
python "平台管理\更新平台.py"
echo.
pause
