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
echo   开始之前只要做一件事：**把 Claude Code 关掉**。
echo   （编辑器、停在这个文件夹里的命令行窗口，也一并关掉。）
echo.
echo   控制面板的后台进程不用管，脚本会自己停掉它 ——
echo   那个进程没有窗口，你在任务栏上是看不见的。
echo.
echo   万一还有别的程序占着，脚本会把它的名字告诉你，然后停下，
echo   不会改坏任何东西。
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
