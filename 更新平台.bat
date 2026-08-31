@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo   正在更新平台，请勿关闭窗口…
echo.
if not exist "host\deploy\update.py" (
  echo   ** 找不到 host\deploy\update.py **
  echo   先在项目文件夹里手动跑一次 git pull，再双击本文件。
  echo.
  pause
  exit /b 1
)
python "host\deploy\update.py"
echo.
pause
