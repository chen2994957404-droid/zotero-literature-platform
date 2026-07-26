@echo off
chcp 65001 >nul
REM 文献精读守护服务 —— 启动后常驻，监听 n8n 解析结果并自动生成精读HTML
cd /d "%~dp0"

echo ============================================
echo   文献图文精读 - 守护服务
echo ============================================
echo.
echo 正在检查 Ollama 模型路径...
setx OLLAMA_MODELS "D:\02_AI\models\Ollama\models" >nul

echo 正在启动守护脚本（监听 workflow_data\to_process）...
echo 提示：保持此窗口开启即可。上传PDF后精读会自动生成到 workflow_data\summary
echo 关闭窗口即停止服务。
echo.

REM DEEPSEEK_KEY 从系统环境变量读取（已用 setx 永久化）
if "%DEEPSEEK_KEY%"=="" echo [警告] 未设置 DEEPSEEK_KEY（DeepSeek），请先运行: setx DEEPSEEK_KEY "你的密钥"
python "scripts\watcher.py"

pause
