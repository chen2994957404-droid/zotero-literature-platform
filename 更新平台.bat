@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo   ============ 更新平台 ============
echo.

echo   [1/4] 拉取最新代码…
git pull
if errorlevel 1 (
  echo.
  echo   ** 拉取失败 **
  echo   常见原因：这台机器上改过代码（本机不该改代码，改动请在编程端做）。
  echo   把上面的报错发给 Claude。
  echo.
  pause
  exit /b 1
)

echo.
echo   [2/4] 更新依赖登记…
python -m pip install -e . --no-deps -q
if errorlevel 1 (
  echo   ** 安装失败，把上面的报错发给 Claude ** & pause & exit /b 1
)

echo.
echo   [3/4] 离线体检（不依赖 Zotero/Ollama，这一档必须全绿）…
python 平台管理\health_check.py --offline
if errorlevel 1 (
  echo.
  echo   ** 离线体检有失败项 —— 不要继续使用，把上面的输出发给 Claude **
  echo.
  pause
  exit /b 1
)

echo.
echo   [4/4] 完整体检（会检查 Zotero / Ollama / 自启任务）…
python 平台管理\health_check.py

echo.
echo   ============ 更新完成 ============
echo.
echo   如果上面「机器角色」那一行不是「运行端」，
echo   请打开 控制面板.bat，在「本机设置」里把「机器角色」改成 prod。
echo   本机是主力机，角色必须是 prod，否则精读监听和全库作业都会被拒绝。
echo.
pause
