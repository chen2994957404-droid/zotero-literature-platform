@echo off
chcp 65001 >nul
title 连上文献平台

REM 给编程机上的 Antigravity 用：把主力机的 MCP 服务接到本机来。
REM
REM 为什么要这一步：主力机的 MCP 服务**只绑 127.0.0.1**，公网上摸不到 ——
REM 它能花钱、能写你的 Zotero 库，绝不能直接挂在公网上。
REM 这个窗口开一条 SSH 隧道，把它安全地接到本机的 8778 端口，
REM 认证走你的 SSH 密钥。
REM
REM 这个窗口**别关**。关了 Antigravity 就连不上文献平台了。

set KEY=%USERPROFILE%\.ssh\id_ed25519_zotero_b
set HOSTADDR=211.83.153.16
set PORT=8778

echo.
echo   正在连接主力机...
echo.

ssh -i "%KEY%" -N -o BatchMode=yes -o ExitOnForwardFailure=yes ^
    -o ServerAliveInterval=30 -o ServerAliveCountMax=3 ^
    -L %PORT%:127.0.0.1:%PORT% Administrator@%HOSTADDR%

echo.
echo   [!] 连接断开了。
echo.
echo   常见原因：
echo     1. 主力机关机了，或者它换了网络（那台机器的地址会变）
echo     2. 主力机上的 MCP 服务没在跑
echo     3. 本机的 %PORT% 端口被别的程序占了
echo.
echo   把上面的报错整段发给 Claude，它知道该往哪查。
echo.
pause
