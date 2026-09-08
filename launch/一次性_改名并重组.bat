@echo off
chcp 65001 >nul
rem All user-facing text lives in the Python script.
rem Chinese inside a .bat gets mangled by cmd's codepage handling
rem and breaks line parsing (2026-09-08, incident #147).
rem cd to the PARENT of the project so nothing holds the folder open.
cd /d "%~dp0..\.."
if not exist "%~dp0..\host\deploy\migrate_rename.py" (
  echo.
  echo   migrate_rename.py not found - already migrated?
  echo   Look in D:\dev\literature-platform
  echo.
  pause
  exit /b 1
)
python -B "%~dp0..\host\deploy\migrate_rename.py"
echo.
pause
