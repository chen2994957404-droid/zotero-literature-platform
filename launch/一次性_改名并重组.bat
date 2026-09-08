@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo.
echo   ================================================================
echo     一次性搬迁：给项目改名 + 把通用工具收进 toolbox
echo   ================================================================
echo.
echo   这一步只动你现在这台机器，B 机（主力机）完全不受影响。
echo.
echo   开始之前请先确认：
echo     * Claude Code 已经关掉了
echo     * 没有编辑器/命令行窗口停在这个项目文件夹里
echo.
echo   否则 Windows 不让改文件夹的名字，脚本会报错停下（不会改坏东西）。
echo.
pause

if not exist "host\deploy\migrate_rename.py" (
  echo.
  echo   ** 找不到 host\deploy\migrate_rename.py **
  echo   你可能已经跑过一次、项目已经改名了。去 D:\dev\literature-platform 看看。
  echo.
  pause
  exit /b 1
)

rem 脚本要改的目录就是它自己住的目录 —— 先复制到临时区，从那边跑，
rem 免得 Windows 因为「文件夹正被占用」而拒绝改名。
copy /y "host\deploy\migrate_rename.py" "%TEMP%\migrate_rename.py" >nul
cd /d D:\dev
python -B "%TEMP%\migrate_rename.py"

echo.
pause
