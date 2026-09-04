# -*- coding: utf-8 -*-
"""从编程端（A 机）操作主力机（B 机）—— 把那条 SSH 通路包成一个能用的工具。

用法:
    python host/deploy/remote.py check                # 连得上吗、是谁、代码到哪一版
                                                      #（多个地址按顺序试，见 HOSTS）
    python host/deploy/remote.py wake                 # 睡着了就发个网络唤醒包
    python host/deploy/remote.py run "<PowerShell>"   # 跑一条只读命令
    python host/deploy/remote.py logs [名字] [行数]   # 看日志尾部（默认 zotero_watcher）
    python host/deploy/remote.py deploy               # git pull + 装包 + 修任务 + 重启 + 体检
    python host/deploy/remote.py task <任务名>        # 触发一个已注册的计划任务
    python host/deploy/remote.py push <本地文件> <远端相对路径>   # 传个脚本过去
    python host/deploy/remote.py job --install        # 装「作业通道」（只做一次）
    python host/deploy/remote.py job "<PowerShell>"   # 让 B 用自己的身份跑（**能读密钥**）
                                                      #   --async 不等它 / --tail 看进展

## 为什么值得包一层，而不是每次现敲 ssh

那条命令有**三个已经用血换来的细节**，现敲必漏其一：

1. **用户名是 `Administrator`，不是 `吧啦吧啦`**（那是计算机名）。
   踩坑 #74：用错时 sshd 只回 `Permission denied (publickey,...)` ——
   这句话对「账号不存在」和「公钥不对」**是同一句**，客户端侧根本分不出来，
   于是能白查两轮密钥。本工具连不上时会直接把这条判据打出来。
2. **中文要套 UTF-8 外壳**：B 那边控制台默认 GBK，不套壳中文输出全是乱码
   （踩坑 #54 同源）。
3. **复杂脚本别硬拼引号**，用 `push` 传过去再执行。

## ⚠ 这条路打不通的那一半（技术限制，不是权限问题）

**SSH 会话里读不到密钥。** `get_key('DEEPSEEK_KEY')` 返回空串 ——
公钥登录建立的是网络登录会话，拿不到解开 Windows 凭据库所需的凭据。
所以**任何要花钱的作业（精读、抽取、向量化）从 SSH 发起都会在第一次调模型时废掉**，
而且是跑到一半才废，白花前面的解析额度。

能远程做：`git pull` / 装包 / pytest / 离线体检 / 读日志读数据 / 重建查询库 /
改计划任务 / 重启服务。
不能远程发起：任何调付费 API 的作业。

**绕法（2026-09-03 已实测证实）**：计划任务的登录会话**能**读凭据库。

证据不是推断，是 B 机 `zotero_watcher.log` 里的真实记录：那天 11:43–11:45，
由计划任务拉起的 watcher 完整跑完一篇 —— 读 .docx SI、精读、合并、
结构化抽取（**做了两轮自检重抽，那是付费云端模型**）、回写 Zotero 附件、改标签。
同一时刻从 SSH 会话里读 `DEEPSEEK_KEY` 拿到的是空串。

所以 `task <已注册任务名>` 触发的作业**能**花钱、能写 Zotero。
它的边界是「只能做那个任务本来就做的事」。

**`job` 子命令就是把这条绕法一般化**（2026-09-03 加）：注册一个按需触发的
计划任务，它跑什么由 A 机现写。于是上面那条「不能远程发起」的限制没了 ——
A 机能让 B 做任何事，包括花钱的和写 Zotero 的。详见下面 JOB_TASK 那一段。
"""
import io
import os
import socket
import sys

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.kernel import subproc as _sp
from shared.kernel.cli import flag, opt, positionals, wants_help

# ── 连接参数 ──────────────────────────────────────────────────────────
# ⚠ `Administrator` 是**账号**；`吧啦吧啦` 是**计算机名**，不是账号（踩坑 #74）。
# B 机可能有两个地址：同一局域网时的内网 IP，和装了组网软件之后的虚拟 IP。
# **两个都留着，按顺序试** —— 笔记本到处跑，哪个能通取决于此刻在哪个网。
#   B_HOSTS  逗号分隔，前面的先试（局域网直连更快，所以排前面）
# ⚠ **兜底地址这一格现在是空的，而且是有意空着的**（2026-09-04）。
#
# 试过 Tailscale：装上、登录、实测都通，连故障演练都过了（把局域网地址换成死地址，
# 命令自动绕到 100.x 并跑通）。**但用户的 VPN 因此连不上了，卸掉才恢复。**
# 根因是同一层的东西在抢：Tailscale 的虚拟网卡会动默认路由与 DNS，
# 而这两台机器都靠代理上网。**能用 ≠ 能共存。**
#
# 所以别再往这里填一个「组网软件的虚拟 IP」，除非先解决共存问题
# （代理的分流规则里放行 100.64.0.0/10，或改用不抢默认路由的方案）。
# 待办里记着这件事的完整来龙去脉。
#
# 现状：只有局域网一个地址。B 的无线一周天天在抖（08-31 那天 114 条断连事件），
# 所以连不上是常态，不是异常 —— **应对办法是作业用 `job ... --async` 交出去就不管**，
# 连接断了不影响 B 那边干活，重连后再取结果。这条今晚救回过一次精读。
_DEFAULT_HOSTS = '192.168.123.216'
HOSTS = [h.strip() for h in
         os.environ.get('B_HOSTS', os.environ.get('B_HOST', _DEFAULT_HOSTS)).split(',')
         if h.strip()]
HOST = HOSTS[0]          # 兼容旧写法（诊断文案里还会引用它）

# 上次连通的是哪个地址。**记住它是为了省时间**：一个连不上的地址要等满
# ConnectTimeout 才放弃，候选多了每次都从头试会让每条命令都慢十几秒。
LAST_GOOD = os.path.join(os.path.expanduser('~'), '.ssh', 'b_last_good_host.txt')


def candidates():
    """按「最可能通」的顺序给出候选地址。"""
    order = list(HOSTS)
    try:
        last = io.open(LAST_GOOD, encoding='utf-8').read().strip()
    except OSError:
        last = ''
    if last in order:
        order.remove(last)
        order.insert(0, last)
    return order


def _remember_good(host):
    try:
        os.makedirs(os.path.dirname(LAST_GOOD), exist_ok=True)
        with io.open(LAST_GOOD, 'w', encoding='utf-8') as fh:
            fh.write(host + _NL)
    except OSError:
        pass
USER = os.environ.get('B_USER', 'Administrator')
KEY = os.path.expanduser(os.environ.get('B_KEY', '~/.ssh/id_ed25519_zotero_b'))
ROOT_B = os.environ.get('B_ROOT', 'D:/02_AI/Projects/zotero-literature-platform')

# B 那边控制台默认 GBK，不套这层壳中文输出全是乱码
_UTF8 = ("$OutputEncoding=[System.Text.Encoding]::UTF8; "
         "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
         "$env:PYTHONIOENCODING='utf-8'; ")

CONNECT_TIMEOUT = 10

# 换行写成常量：这个文件里的多行提示被 shell/heredoc 吃过一次转义，
# 用常量拼接就不会再被任何一层工具链改写（同 tests/test_architecture.py 的做法）。
_NL = chr(10)


def ssh_argv(script, timeout=None, host=None):
    """组一条 ssh 命令行。script 是要在 B 上跑的 PowerShell。"""
    return ['ssh', '-i', KEY, '-o', 'BatchMode=yes',
            '-o', f'ConnectTimeout={timeout or CONNECT_TIMEOUT}',
            f'{USER}@{host or HOST}', _UTF8 + script]


def diagnose(stderr):
    """连不上时，把「看起来一样但根因完全不同」的几种情况分开。

    这是本工具存在的一半理由：sshd 对「账号不存在」和「公钥不对」
    回的是**同一句** `Permission denied (publickey,...)`（踩坑 #74），
    从 A 机怎么看都像密钥问题，能白查两轮。
    """
    e = (stderr or '').lower()
    if 'kex_exchange_identification' in e or 'connection closed by' in e:
        # ⚠ 这一条有**两种**根因，实测都见过。别只报一种 ——
        #   2026-09-03 我第一版只写了「睡眠」，结果连一个根本不存在的地址
        #   也被诊断成「机器在睡眠」。**言之凿凿的错判比不给判断更糟。**
        return ('TCP 连上了，但 sshd **还没打招呼就断开** —— 密钥交换都没开始，' + _NL
                + '  所以跟账号、公钥全无关（别往那查）。两种可能：' + _NL
                + '  ① 那台机器在睡眠，被网络活动短暂唤醒又睡回去；' + _NL
                + '  ② 本机的代理/VPN 接管了这个连接，自己应答后又断开' + _NL
                + '     （判据：连一个**确定不存在**的 IP 的 22 端口，'
                + '如果它也「连上」了，就是这一种）。' + _NL
                + '  ①的解法：wake 发唤醒包，或让那台机器别睡（它本来就该常开）。' + _NL
                + '  ②的解法：把这个地址加进代理的直连/绕过规则。')
    if 'connection timed out' in e or 'no route to host' in e:
        # ⚠ 2026-09-04：这里原来只写「多半是关机或睡眠」，**又一次把人带偏了**
        #   （同踩坑 #97 的教训，换了个错误码复发）。当时 B 其实醒着 ——
        #   事后查它的系统日志：三小时内零条电源事件，已连续运行 133 小时。
        #   断的是**路**，不是机器。而最可能接管这条路的，是 A 机自己的代理。
        return ('B 机没应答。**别先认定它睡了** —— 三种原因，症状一模一样：\n'
                '  ① 本机代理/VPN 接管了到局域网的路由（A 机有 singbox_tun，'
                '**优先查这条**）\n'
                '     判据：`ping ' + HOST + '` 也不通，但 B 那边其实一直在跑。\n'
                '     解法：把这个网段加进代理的直连/绕过规则。\n'
                '  ② B 换了 IP（笔记本换网络时会）。\n'
                '  ③ 真的关机或睡眠 —— **这条要拿证据**，别猜：\n'
                '     等它回来后查 `Get-WinEvent -ProviderName Microsoft-Windows-Kernel-Power`，\n'
                '     没有电源事件就说明它压根没睡过。\n'
                '  这一条跟密钥、账号都无关，别往那个方向查。')
    if 'permission denied' in e:
        return ('被拒了。**这句话对「账号不存在」和「公钥不对」是同一句**（踩坑 #74），\n'
                '  在 A 机这边分不出来。决定性证据只在 B 机的 sshd 日志里 ——\n'
                '  让用户在主力机上跑一条：\n'
                '    Get-WinEvent -LogName OpenSSH/Operational -MaxEvents 12 | '
                'Select TimeCreated,Message\n'
                f'  写着 `Invalid user` = 账号错（现在用的是 {USER!r}，'
                '注意别用计算机名）；否则才是公钥的事。')
    if 'host key verification failed' in e:
        return ('主机密钥对不上 —— B 机重装过 sshd，或者你连到了别的机器上。\n'
                '  确认真的是那台之后，删掉 known_hosts 里那一行再连。')
    if 'no such file' in e and 'ssh' in e:
        return f'找不到私钥 {KEY} —— 换过电脑或换过用户目录？'
    return ''


# ssh 客户端自己刷的告警，跟我们要做的事无关，但它**每条命令都出现，而且在最后**。
# 后果不只是刷屏：`call()` 失败时只打印最后一行，于是真正的错误被这句挡住 ——
# 2026-09-04 装 Tailscale 时，脚本报的错整段看不见，只看到「服务器该升级了」。
# **噪音盖住信号，就不只是噪音了。**
_SSH_NOISE = ('post-quantum', 'store now, decrypt later', 'openssh.com/pq.html',
              'The server may need to be upgraded')


def clean(out):
    """滤掉 ssh 客户端的固定告警，只留真正的输出。"""
    return _NL.join(l for l in (out or '').splitlines()
                    if not any(n in l for n in _SSH_NOISE)).strip()


def call(script, timeout=180):
    """在 B 上跑一段 PowerShell。逐个候选地址试，返回 (成功?, 输出)。

    只有**全部**候选都失败才算失败 —— 报错时把每个地址各自的原因都列出来，
    因为它们可能完全不同（局域网那个是「不在同一个网」，
    组网那个可能是「组网软件没开」），只报最后一个会把人带偏。
    """
    tried = []
    for host in candidates():
        r = _sp.run(ssh_argv(script, host=host), timeout=timeout)
        out = (r.stdout or '') + (r.stderr or '')
        if r.returncode == 0:
            _remember_good(host)
            return True, clean(out)
        tried.append((host, clean(out)))

    lines = []
    for host, out in tried:
        tip = diagnose(out)
        # 给最后 8 行，不是最后 1 行 —— 报错常常是一整段（traceback、msiexec 的多行输出），
        # 只给一行等于把诊断信息扔掉。
        tail = out.splitlines()[-8:] if out else []
        lines.append(f'[{host}] ' + (_NL + '  ').join(['(以下是它的输出)'] + tail)
                     if tail else f'[{host}] （无输出）')
        if tip:
            lines.append(tip)
    return False, _NL.join(lines)


# ── 各条子命令 ────────────────────────────────────────────────────────

MAC_FILE = os.path.join(os.path.expanduser('~'), '.ssh', 'b_host_mac.txt')


def remember_mac():
    """趁 B 醒着，把它的 MAC 记下来 —— 唤醒包只能用 MAC 发。

    **只有它醒着时才拿得到**（ARP 要它回话）。所以每次连通都顺手记一次：
    等到真需要唤醒的那天，它已经睡了，那时再想拿就晚了。
    """
    from shared.kernel import subproc as sp
    out = sp.powershell(
        f"(Get-NetNeighbor -IPAddress {candidates()[0]} -ErrorAction SilentlyContinue | "
        f"Where-Object {{$_.State -ne 'Unreachable'}}).LinkLayerAddress", timeout=30)
    mac = (out or '').strip().splitlines()[0].strip() if (out or '').strip() else ''
    if len(mac) == 17 and mac.count('-') == 5 and not mac.startswith('00-00-00'):
        try:
            os.makedirs(os.path.dirname(MAC_FILE), exist_ok=True)
            with open(MAC_FILE, 'w', encoding='utf-8') as fh:
                fh.write(mac + _NL)
            return mac
        except OSError:
            pass
    return ''


def cmd_wake():
    """给 B 发网络唤醒包（Wake-on-LAN）。

    ⚠ **2026-09-04 实测：不管用。** MAC 拿到了（6C-4C-E2-…），包也发出去了，
      B 没醒。所以下面这两条至少有一条不成立：
      · B 的网卡与 BIOS 都开了「允许此设备唤醒计算机」
      · B 是有线连着的（大多数无线网卡睡眠后不响应唤醒包 —— B 走的是 WLAN，
        这一条基本可以确定就是原因）
      两条都只能在主力机上确认。**在那之前，别把这条路当成退路** ——
      「以为有退路」比「知道没有」更危险。

    真正一劳永逸的办法其实更简单：**主力机本来就该常开**（它跑着精读监听
    和每小时同步），把睡眠关掉即可 —— 醒着的时候一条命令就够：

        powercfg /change standby-timeout-ac 0
        powercfg /change hibernate-timeout-ac 0

    唤醒包是退路，不是正路；而实测证明这条退路在 B 上根本不存在。
    """
    mac = ''
    if os.path.isfile(MAC_FILE):
        mac = open(MAC_FILE, encoding='utf-8').read().strip()
    mac = (opt('--mac') or mac).replace(':', '-').upper()
    if len(mac) != 17:
        print('不知道 B 的 MAC，发不了唤醒包。' + _NL
              + '  它只能在 B 醒着的时候拿到 —— 下次连通时 check 会自动记下来。' + _NL
              + '  也可以直接给：remote.py wake --mac AA-BB-CC-DD-EE-FF')
        return 2
    # 唤醒包 = 6 个 0xFF 开头 + MAC 重复 16 次（这就是它的全部格式）
    packet = b'\xff' * 6 + bytes.fromhex(mac.replace('-', '')) * 16
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    for port in (9, 7):          # 9 是标准口，7 是老设备还在用的那个
        sock.sendto(packet, ('255.255.255.255', port))
    sock.close()
    print(f'已向 {mac} 发唤醒包（9 与 7 两个端口）。' + _NL
          + '等十几秒再 check。**没反应不代表包没发出去** —— '
          + '更可能是那台机器的网卡没开唤醒，或者走的是无线。')
    return 0


def cmd_check():
    """连得上吗、是谁、代码到哪一版、服务活着没。"""
    ok, out = call(
        'Write-Output ("主机名: " + $env:COMPUTERNAME); '
        'Write-Output ("账号:   " + (whoami)); '
        f'Set-Location "{ROOT_B}"; '
        'Write-Output ("代码:   " + (git log --oneline -1)); '
        'Write-Output ("分支:   " + (git rev-parse --abbrev-ref HEAD)); '
        "$t = Get-ScheduledTask | Where-Object {$_.TaskName -in "
        "@('ZoteroLiteratureWatcher','OllamaService','ZoteroApp','LiteratureAutoSync')}; "
        'foreach ($x in $t) { Write-Output ("任务:   " + $x.TaskName + " = " + $x.State) }',
        timeout=90)
    print(out)
    if ok:
        mac = remember_mac()
        if mac:
            print(f'MAC:    {mac}（已记下，睡着时可用 wake 唤醒）')
    return 0 if ok else 1


def cmd_run(script):
    ok, out = call(script, timeout=int(opt('--timeout') or 300))
    print(out)
    return 0 if ok else 1


def log_paths(name):
    """一个日志名 → 两种布局下它可能在的位置。

    B 机 2026-09-03 已经切到新布局（`data/logs/`），老布局这条本可以删了 ——
    **留着是因为 `workflow_data/` 那 1.22 GB 原目录还在**，
    真要回滚就又得读老位置。等原目录删掉那天，这里可以只留第一条。

    为什么当初要两条：写死一个的话，连上去只会看到「文件不存在」，
    而那看起来像「服务没在写日志」—— 一个足以让人查错方向的假象。
    """
    return [f'{ROOT_B}/data/logs/{name}.log',          # R6 之后的五层布局（现行）
            f'{ROOT_B}/workflow_data/logs/{name}.log']  # 重构前（回滚时才用得到）


def cmd_logs(name='zotero_watcher', lines=40):
    """看日志尾部。

    ⚠ **`-Encoding utf8` 一个都不能少。** 日志文件是 UTF-8，而 B 的
    PowerShell 默认按系统代码页（GBK）读文件 —— 顶上那层 UTF-8 外壳只管
    **输出**编码，管不到**读文件**这一步。少了它中文全是
    `[蹇冭烦] 杞姝ｅ父` 这种乱码（2026-09-03 实测撞到；踩坑 #60 说的
    「编码在三个地方分别咬人」，这是第三个地方）。
    """
    tried = ' , '.join(f"'{p}'" for p in log_paths(name))
    ok, out = call(
        f'$found = $false; '
        f'foreach ($p in @({tried})) {{ '
        f'  if (Test-Path $p) {{ '
        f'    Write-Output ("--- " + $p + " ---"); '
        f'    Get-Content $p -Tail {int(lines)} -Encoding utf8; '
        f'    $found = $true; break }} }} '
        f'if (-not $found) {{ Write-Output "两种布局下都没有这个日志：{name}" }}',
        timeout=120)
    print(out)
    return 0 if ok else 1


def cmd_deploy():
    """把 A 机推上去的代码在 B 上生效。**等价于用户双击一次「更新平台.bat」。**

    为什么不自己拼那几步：`host/deploy/update.py` 里已经有完整的六步
    （拉代码 → 装包 → 停旧面板 → 修计划任务并重启服务 → 离线体检 → 完整体检），
    而且它处理了「常驻进程不重启就一直跑旧代码」这件事（踩坑 #50）。
    在这里再抄一遍，两份迟早会不一致。
    """
    print('在 B 机上跑 update.py（等同于双击「更新平台.bat」）…\n')
    ok, out = call(f'Set-Location "{ROOT_B}"; python host/deploy/update.py',
                   timeout=int(opt('--timeout') or 1800))
    print(out)
    return 0 if ok else 1


def cmd_task(name):
    """触发一个**已注册**的计划任务。

    ⚠ 这是目前唯一**可能**绕过「SSH 读不到密钥」的路：任务的登录会话能读凭据库
    （watcher 就是靠这个跑花钱的作业）。但**还没实测过**，
    第一次用完要核对日志确认它真的跑起来了、真的拿到了密钥。
    """
    safe = {'ZoteroLiteratureWatcher', 'OllamaService', 'ZoteroApp', 'LiteratureAutoSync'}
    if name not in safe:
        print(f'不认识的任务 {name!r}。已知的：{sorted(safe)}\n'
              '（白名单在这里是防手滑，不是防坏人 —— 真要跑别的，改这个集合。）')
        return 2
    ok, out = call(
        f"try {{ Start-ScheduledTask -TaskName '{name}' -ErrorAction Stop; "
        f"Write-Output '{name} 已触发' }} "
        f"catch {{ Write-Output ('触发失败：' + $_.Exception.Message) }}", timeout=90)
    print(out)
    if ok:
        print('\n⚠ 「触发了」不等于「跑成功了」—— 隔一会儿用 logs 看一眼它到底做了什么。')
    return 0 if ok else 1


def scp_to(local, remote_abs):
    """把一个本地文件传到 B 的**绝对路径**。返回 (成功?, 输出)。

    ⚠ 逐个候选地址试，跟 `call()` 一样 —— 早先这里写死了 `HOST`，
    于是「ssh 连得上、scp 连不上」：check 用的是记住的那个好地址，
    push 用的却永远是列表里的第一个。同一台机器，两条路不一致最难查。
    """
    out = ''
    for host in candidates():
        r = _sp.run(['scp', '-i', KEY, '-o', 'BatchMode=yes',
                     '-o', f'ConnectTimeout={CONNECT_TIMEOUT}',
                     local, f'{USER}@{host}:{remote_abs}'], timeout=300)
        out = clean((r.stdout or '') + (r.stderr or ''))
        if r.returncode == 0:
            _remember_good(host)
            return True, out
    return False, out


def cmd_push(local, remote_rel):
    """把一个本地文件传到 B 的项目目录下（复杂脚本别硬拼引号，传过去再跑）。"""
    if not os.path.isfile(local):
        print(f'找不到本地文件：{local}')
        return 2
    ok, out = scp_to(local, f'{ROOT_B}/{remote_rel}')
    if not ok:
        print(out)
        tip = diagnose(out)
        if tip:
            print(_NL + tip)
        return 1
    print(f'已传到 {ROOT_B}/{remote_rel}')
    print('⚠ 跑完记得删掉临时文件 —— B 机上别留一地的 _tmp。')
    return 0


# ── 作业通道：让 B 用「它自己的身份」干活 ────────────────────────────
# 为什么要有这一段（2026-09-03 实测出来的边界，不是推断）：
#   公钥 SSH 建立的是**网络登录会话**，Windows 凭据管理器在这种会话里打不开 ——
#   实测报的是 `CredRead: 指定的登录会话不存在。可能已被终止。`
#   所以从 SSH 直接发起的作业，`get_key('DEEPSEEK_KEY')` 拿到空串，
#   跑到第一次调模型才废，白花前面的解析额度。
#
#   而**计划任务**跑在交互登录会话里（B 上 watcher 的 principal 就是
#   `LogonType=Interactive`），那个会话解得开凭据库 —— watcher 天天在花钱、
#   天天在写 Zotero，就是活证据。
#
#   于是这条通道的做法是：**不新起常驻进程**，只注册一个按需触发的计划任务，
#   它执行一个固定的外壳；外壳读同目录下的 payload，跑完把输出和退出码落盘。
#   A 机写 payload → 触发 → 等 done 文件 → 取输出。
#   等于「让 B 自己去跑」，而不是「我在 B 上跑」—— 差的就是那把凭据。
JOB_TASK = 'ZoteroAgentJob'
# 放在仓库外：B 机迟早要换成重构后的目录，这条通道不该跟着一起搬
JOB_DIR = 'C:/ProgramData/zotero-agent'
JOB_WRAPPER = JOB_DIR + '/job.ps1'
JOB_PAYLOAD = JOB_DIR + '/payload.ps1'
JOB_OUT = JOB_DIR + '/job.out'
JOB_DONE = JOB_DIR + '/job.done'


def wrapper_source():
    """外壳脚本的内容。

    由这里生成而不是另存一个 .ps1，是为了让它和上面那几个常量、和 `ROOT_B`
    **只有一处定义** —— 两份迟早不一致，而不一致的那天看起来像「任务没触发」。
    """
    return _NL.join([
        "$ErrorActionPreference = 'Continue'",
        '$OutputEncoding = [System.Text.Encoding]::UTF8',
        '[Console]::OutputEncoding = [System.Text.Encoding]::UTF8',
        "$env:PYTHONIOENCODING = 'utf-8'",
        f"Remove-Item '{JOB_DONE}' -ErrorAction SilentlyContinue",
        f"Set-Location '{ROOT_B}'",
        '$code = 0',
        'try {',
        f"  & '{JOB_PAYLOAD}' *>&1 | Out-File -FilePath '{JOB_OUT}' -Encoding utf8",
        '  if ($null -ne $LASTEXITCODE) { $code = $LASTEXITCODE }',
        '} catch {',
        f"  $_ | Out-File -FilePath '{JOB_OUT}' -Encoding utf8 -Append",
        '  $code = 1',
        '}',
        f"Set-Content -Path '{JOB_DONE}' -Value $code -Encoding utf8",
        '',
    ])


def _write_temp(text, suffix='.ps1'):
    """写一个临时脚本，**带 BOM**。

    ⚠ `utf-8-sig` 不是洁癖：Windows PowerShell 5.1 读 `.ps1` **文件**时，
    没有 BOM 就按系统代码页（GBK）解，脚本里的中文在**执行之前**就已经烂了 ——
    实测第一版的输出是 `DEEPSEEK_KEY 闀垮害: 35`。
    这是编码咬人的第四个地方：前三个是控制台输出、子进程、读文件（踩坑 #60/#99），
    这个是**读脚本自身**。顶上那层 UTF-8 外壳管不到它，因为壳是在脚本被解析之后才生效的。
    """
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    with io.open(tmp, 'w', encoding='utf-8-sig') as fh:
        fh.write(text)
    return tmp


def cmd_job_install():
    """在 B 上装好这条通道（只需要做一次）。

    ⚠ `LogonType` 必须是 `Interactive` —— **能读凭据库的正是这一档**，
    照抄的是 watcher 那份被实践验证过的配置。改成 S4U / ServiceAccount
    就又读不到密钥了，而且失败的样子跟现在的 SSH 一模一样
    （空密钥、跑到一半才废），极难查。
    """
    ok, out = call(f"New-Item -ItemType Directory -Force -Path '{JOB_DIR}' | Out-Null; "
                   "Write-Output 'ok'", timeout=60)
    if not ok:
        print(out)
        return 1

    tmp = _write_temp(wrapper_source())
    ok, out = scp_to(tmp, JOB_WRAPPER)
    os.remove(tmp)
    if not ok:
        print('外壳脚本传不过去：' + out)
        return 1

    ok, out = call(
        "$a = New-ScheduledTaskAction -Execute 'powershell.exe' "
        # 路径里没有空格，所以**不给它套引号** —— 这条命令要穿过
        # ssh → PowerShell 两层解析，每多一层引号就多一个能咬人的地方。
        "-Argument '-NoProfile -NonInteractive -WindowStyle Hidden "
        f"-ExecutionPolicy Bypass -File {JOB_WRAPPER}'; "
        f"$p = New-ScheduledTaskPrincipal -UserId '{USER}' "
        '-LogonType Interactive -RunLevel Limited; '
        '$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries '
        '-DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 6) '
        '-MultipleInstances IgnoreNew; '
        f"Register-ScheduledTask -TaskName '{JOB_TASK}' -Action $a -Principal $p "
        "-Settings $s -Description 'A 机按需触发的作业通道' -Force | Out-Null; "
        f"$t = Get-ScheduledTask -TaskName '{JOB_TASK}'; "
        "Write-Output ('已注册: ' + $t.TaskName + ' / LogonType=' "
        "+ $t.Principal.LogonType + ' / ' + $t.State)", timeout=90)
    print(out)
    if ok:
        print(_NL + '⚠ 装完先验一次能不能读到密钥，别默认它成了。')
    return 0 if ok else 1


def cmd_job(script, wait=True, timeout=1800):
    """把一段 PowerShell 交给 B，用它自己的身份跑。

    等待放在 **B 那边**（一条 ssh 里 `Start-Sleep` 轮询），不是 A 这边反复发 ssh ——
    每次连接都要重新握手，长作业轮询下来光握手就是几百秒。
    """
    tmp = _write_temp(script + _NL)
    ok, out = scp_to(tmp, JOB_PAYLOAD)
    os.remove(tmp)
    if not ok:
        print('作业内容传不过去（是不是还没 job --install？）：' + out)
        return 1

    ok, out = call(
        f"$t = Get-ScheduledTask -TaskName '{JOB_TASK}' -ErrorAction SilentlyContinue; "
        "if (-not $t) { Write-Output '还没装通道：先跑 remote.py job --install'; exit 9 }; "
        "if ($t.State -eq 'Running') { "
        "Write-Output '上一个作业还在跑（这条通道一次只跑一个）'; exit 9 }; "
        f"Remove-Item '{JOB_DONE}','{JOB_OUT}' -ErrorAction SilentlyContinue; "
        f"Start-ScheduledTask -TaskName '{JOB_TASK}'; Write-Output '已交给 B'",
        timeout=90)
    print(out)
    if not ok:
        return 1
    if not wait:
        print('（没等它跑完 —— 用 remote.py job --tail 看进展）')
        return 0
    return cmd_job_tail(timeout)


def cmd_job_tail(timeout=1800):
    """等作业结束并取回输出；超时就先把已有的输出给出来。"""
    ok, out = call(
        f'$d = (Get-Date).AddSeconds({int(timeout)}); '
        f"while (-not (Test-Path '{JOB_DONE}') -and (Get-Date) -lt $d) "
        '{ Start-Sleep -Seconds 2 }; '
        f"if (Test-Path '{JOB_OUT}') {{ Get-Content '{JOB_OUT}' -Encoding utf8 }}; "
        f"if (Test-Path '{JOB_DONE}') {{ "
        f"Write-Output ('[退出码] ' + (Get-Content '{JOB_DONE}' -Encoding utf8)) }} "
        "else { Write-Output '[还没跑完] 上面是目前为止的输出' }",
        timeout=int(timeout) + 60)
    print(out)
    return 0 if ok else 1


def main():
    if wants_help():
        print(__doc__)
        return 0
    args = positionals()
    action = (args[0] if args else '').lower()

    if action == 'check':
        return cmd_check()
    if action == 'wake':
        return cmd_wake()
    if action == 'run':
        if len(args) < 2:
            print('要给一条 PowerShell：remote.py run "<命令>"')
            return 2
        return cmd_run(args[1])
    if action == 'logs':
        return cmd_logs(args[1] if len(args) > 1 else 'zotero_watcher',
                        args[2] if len(args) > 2 else 40)
    if action == 'deploy':
        return cmd_deploy()
    if action == 'task':
        if len(args) < 2:
            print('要给任务名：remote.py task ZoteroLiteratureWatcher')
            return 2
        return cmd_task(args[1])
    if action == 'push':
        if len(args) < 3:
            print('用法：remote.py push <本地文件> <远端相对路径>')
            return 2
        return cmd_push(args[1], args[2])
    if action == 'job':
        if flag('--install'):
            return cmd_job_install()
        wait_s = int(opt('--timeout') or 1800)
        if flag('--tail'):
            return cmd_job_tail(wait_s)
        if len(args) < 2:
            print('要给一段 PowerShell：remote.py job "<命令>"'
                  + _NL + '（第一次用先 remote.py job --install）')
            return 2
        return cmd_job(args[1], wait=not flag('--async'), timeout=wait_s)

    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main())
