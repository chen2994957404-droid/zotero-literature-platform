@echo off
chcp 65001 >nul
REM ============================================
REM   Zotero 文献精读闭环服务
REM   在 Zotero 里给文献打「待精读」标签 → 自动精读 → 回写笔记 → 标签变「已精读」
REM ============================================
cd /d "%~dp0"

echo ============================================
echo   Zotero 图文精读闭环 - 守护服务
echo ============================================
echo.
echo 前提检查：
echo   1. Zotero 桌面程序必须开着（数据源）
echo   2. 保持此窗口开启
echo.
echo 用法：在 Zotero 里给想精读的文献打上「待精读」标签，
echo       稍等几分钟，精读笔记会自动出现在该文献下，
echo       完整含图版在 workflow_data\summary\ 目录。
echo.

REM ==== 配置（这些 key 建议定期轮换）====
REM DEEPSEEK_KEY 从系统环境变量读取（已用 setx 永久化）
if "%DEEPSEEK_KEY%"=="" echo [警告] 未设置 DEEPSEEK_KEY（DeepSeek），请先运行: setx DEEPSEEK_KEY "你的密钥"
REM MINERU_TOKEN 从系统环境变量读取（已用 setx 永久化）
if "%MINERU_TOKEN%"=="" echo [警告] 未设置 MINERU_TOKEN（MineRU），请先运行: setx MINERU_TOKEN "你的密钥"
REM ZOTERO_API_KEY 从系统环境变量读取（已用 setx 永久化）
if "%ZOTERO_API_KEY%"=="" echo [警告] 未设置 ZOTERO_API_KEY（Zotero Web API），请先运行: setx ZOTERO_API_KEY "你的密钥"
set PYTHONIOENCODING=utf-8
setx OLLAMA_MODELS "D:\02_AI\models\Ollama\models" >nul

echo 服务启动中...（关闭窗口即停止）
echo.
python "scripts\zotero_watcher.py"

pause
