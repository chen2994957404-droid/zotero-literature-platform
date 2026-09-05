@echo off
chcp 65001 >nul
title 取全文用的浏览器

REM 开一个"专门给取全文用"的浏览器窗口。
REM
REM 为什么要单独一个：取全文的程序要接管一个浏览器（走调试口 9222）。
REM 用你平时那个的话，你一关窗口程序就断，你开新标签它也可能受影响。
REM 单独一个互不打扰，而且它记得住"人机验证已经过了"这件事，下次不用再点。
REM
REM 里面不用登录任何账号 —— 学校订阅认的是这台机器的上网出口，不是账号。

set PROFILE=%LOCALAPPDATA%\zotero-getpdf-browser
set EDGE=C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe
set CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe

echo.
echo   正在打开"取全文专用"的浏览器窗口...
echo.

if exist "%EDGE%" (
  start "" "%EDGE%" --remote-debugging-port=9222 --user-data-dir="%PROFILE%" --no-first-run --no-default-browser-check "https://www.sciencedirect.com/"
) else if exist "%CHROME%" (
  start "" "%CHROME%" --remote-debugging-port=9222 --user-data-dir="%PROFILE%" --no-first-run --no-default-browser-check "https://www.sciencedirect.com/"
) else (
  echo   [x] 没找到 Edge 也没找到 Chrome。
  echo       如果装在别的位置，请告诉 Claude。
  pause
  exit /b 1
)

echo   打开了。第一次用请做两件事：
echo.
echo     1. 如果跳出"验证您是真人"之类的页面，点一下通过
echo     2. 随便打开一篇学校有订阅的文章，确认能看到 PDF 下载按钮
echo.
echo   做完这两件事就可以晾着不管了 —— 这个窗口**别关**，取全文的时候要用它。
echo   下次再双击本文件，它会记得已经验证过，不用再点。
echo.
pause
