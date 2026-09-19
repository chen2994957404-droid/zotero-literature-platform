# 编程机专用：把主力机的 MCP 服务（只绑它自己的 127.0.0.1:8778）通过 SSH 接到本机 8778，
# 给 Antigravity 用。和「连上文献平台（Antigravity用）.bat」是同一条隧道，
# 区别是这份**没有窗口、断了自己重连**，由计划任务 LiteraturePlatformTunnel 开机拉起。
#
# 为什么要循环：ssh -N 在对面重启、网络抖动、主力机换地址时都会退出；
# 计划任务的「失败重启」只认非零退出码，靠不住。这里自己兜住：退了等 20 秒再连。
# 注册 / 注销任务：python host/deploy/tunnel_task.py --install / --remove

$key  = Join-Path $env:USERPROFILE '.ssh\id_ed25519_zotero_b'
$port = 8778
$hosts = @('211.83.153.16', '192.168.123.216')   # 先公网、再局域网；哪个通用哪个

while ($true) {
    foreach ($h in $hosts) {
        & ssh -i $key -N -o BatchMode=yes -o ExitOnForwardFailure=yes `
            -o ConnectTimeout=8 -o ServerAliveInterval=30 -o ServerAliveCountMax=3 `
            -L "${port}:127.0.0.1:${port}" "Administrator@$h"
        # 走到这里说明连接结束了（成功连上过、后来断了；或者压根没连上）。换下一个地址再试。
    }
    Start-Sleep -Seconds 20
}
