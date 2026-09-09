# -*- coding: utf-8 -*-
"""从这台机器操作另一台 Windows —— 把那条 SSH 通路包成一个能用的工具。

    python remote.py check                # 连得上吗、是谁、代码到哪一版
    python remote.py wake                 # 睡着了就发个网络唤醒包
    python remote.py run "<PowerShell>"   # 跑一条只读命令
    python remote.py logs [名字] [行数]   # 看日志尾部
    python remote.py deploy               # 在对面跑「上线脚本」（由配置指定）
    python remote.py task <任务名>        # 触发一个已注册的计划任务
    python remote.py push <本地文件> <远端相对路径>   # 传个脚本过去
    python remote.py job --install        # 装「作业通道」（每台机器只做一次）
    python remote.py job "<PowerShell>"   # 让对面用自己的身份跑（**能读密钥**）
                                          #   --async 不等它 / --tail 看进展

    共用参数：--machine <名字>  指定操作哪台（默认按当前目录自动选，见配置）

配置在 `~/.remote-machine/machines.toml`（照着仓库里的 machines.example.toml 抄）。
**这个工具跟任何具体项目都无关**，也不依赖任何第三方库 —— 放哪都能跑。

## 为什么值得包一层，而不是每次现敲 ssh

那条命令有**三个实测得出的细节**，现敲必漏其一：

1. **用户名是账号，不是计算机名**。用错时 sshd 只回
   `Permission denied (publickey,...)` —— 这句话对「账号不存在」和「公钥不对」
   **是同一句**，客户端侧根本分不出来，于是能白查两轮密钥。
   本工具连不上时会直接把这条判据打出来。
2. **中文要套 UTF-8 外壳**：Windows 那边控制台默认 GBK，不套壳中文输出全是乱码。
3. **复杂脚本别硬拼引号**，用 `push` 传过去再执行。

## ⚠ 这条路打不通的那一半（技术限制，不是权限问题）

**SSH 会话里读不到 Windows 凭据库。** 公钥登录建立的是*网络登录会话*，
拿不到解开凭据管理器所需的凭据 —— 实测报的是
`CredRead: 指定的登录会话不存在。可能已被终止。`
所以**任何要用到密钥的作业（调付费 API 之类）从 SSH 发起都会废**，
而且是跑到一半才废。

能远程做：拉代码 / 装包 / 跑测试 / 离线体检 / 读日志读数据 / 改计划任务 / 重启服务。
不能从 `run` 发起：任何要密钥的作业。

**绕法（已实测证实）**：计划任务跑在交互登录会话里，**能**读凭据库。
`job` 子命令就是把这条绕法一般化：注册一个按需触发的计划任务，
它跑什么由这边现写。于是「不能远程发起」的限制没了。
"""
import io
import os
import socket
import subprocess
import sys
import tempfile
import tomllib

# 强制 UTF-8 输出（中文 Windows 控制台默认 GBK）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# 换行写成常量：这个文件里的多行提示被 shell/heredoc 吃过一次转义，
# 用常量拼接就不会再被任何一层工具链改写。
_NL = chr(10)
_NOWIN = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0


# ── 自带的小零件 ──────────────────────────────────────────────────────
# 这个工具要能在任何项目里单独跑，所以**不 import 任何项目的东西**，
# 取参和跑子进程都自己带一份（各二十来行，比拖一个依赖便宜）。

def positionals():
    """位置参数 —— **只算到第一个 `--选项` 为止**。

    不能简单地「过滤掉带横杠的」：那样 `logs watcher --timeout 60` 里的 `60`
    会被当成第三个位置参数（于是「看 60 行」变成「看 watcher 的 60 行」还算走运，
    换个子命令就是**安静地做错事**）。选项后面跟的到底是它的值还是位置参数，
    从命令行本身无法判断 —— 所以约定：位置参数一律写在选项前面。
    """
    out = []
    for a in sys.argv[1:]:
        if a.startswith('-'):
            break
        out.append(a)
    return out


def flag(name):
    return name in sys.argv[1:]


def opt(name, default=None):
    """`--x 值` 或 `--x=值`。"""
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == name and i + 1 < len(args):
            return args[i + 1]
        if a.startswith(name + '='):
            return a.split('=', 1)[1]
    return default


def run(argv, timeout=180):
    """跑一个子进程，按 UTF-8 解码。返回 (退出码, 合并的输出)。

    ⚠ `errors='replace'` 不能省：ssh 客户端偶尔会吐非 UTF-8 的字节，
    一个解码异常会把整条命令的输出全丢掉 —— 而那正是你要看的报错。
    """
    try:
        p = subprocess.run(argv, capture_output=True, timeout=timeout,
                           creationflags=_NOWIN)
    except FileNotFoundError:
        return 127, (f'找不到命令：{argv[0]}'
                     '（Windows 10 起自带 OpenSSH，没有就去「可选功能」里装）')
    except subprocess.TimeoutExpired:
        return 124, f'超时（{timeout} 秒）'

    def dec(b):
        return (b or b'').decode('utf-8', 'replace')

    return p.returncode, dec(p.stdout) + dec(p.stderr)


def powershell(script, timeout=60):
    """在**本机**跑一条 PowerShell（只用于查 ARP 之类的本地事情）。"""
    rc, out = run(['powershell', '-NoProfile', '-NonInteractive', '-Command',
                   '[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; ' + script],
                  timeout=timeout)
    return out if rc == 0 else ''


# ── 配置 ──────────────────────────────────────────────────────────────
# 地址、账号、私钥、项目路径、任务名全部**在配置里**，代码里一个都不写死 ——
# 这是这个工具能跨项目复用的全部原因。

HOME = os.path.expanduser('~')
CONF_DIR = os.environ.get('REMOTE_MACHINE_HOME', os.path.join(HOME, '.remote-machine'))
CONF_FILE = os.environ.get('REMOTE_MACHINE_CONFIG',
                           os.path.join(CONF_DIR, 'machines.toml'))
STATE_DIR = os.path.join(CONF_DIR, 'state')

_DEFAULTS = {
    'label': '', 'hosts': [], 'user': '', 'key': '', 'root': '',
    'local': '', 'deploy_cmd': '', 'logs': ['logs/{name}.log'],
    'default_log': '', 'tasks': [], 'mac': '',
    'job_task': 'RemoteAgentJob', 'job_dir': 'C:/ProgramData/remote-agent',
}


def load_conf(path=None):
    try:
        with io.open(path or CONF_FILE, 'rb') as fh:
            return tomllib.load(fh)
    except OSError:
        return {}
    except tomllib.TOMLDecodeError as e:
        print(f'配置文件读不动（{path or CONF_FILE}）：{e}')
        return {}


def pick_machine(conf, name=None, cwd=None):
    """选出这次要操作哪台机器 → (名字, 配置)。

    顺序：`--machine` 指定的 → 当前目录落在哪台的 `local` 里 → 配置里的 `default`
    → 只有一台就是它。**按目录自动选**是为了让「在哪个项目里就连哪台」变成默认行为，
    不用每次都记得加参数 —— 忘了加参数而连错机器，是这类工具最贵的一种错。
    """
    machines = conf.get('machines') or {}
    if name:
        return name, machines.get(name)
    here = os.path.normcase(os.path.abspath(cwd or os.getcwd()))
    for n, m in machines.items():
        loc = (m or {}).get('local')
        if loc and here.startswith(os.path.normcase(os.path.abspath(loc))):
            return n, m
    d = conf.get('default')
    if d and d in machines:
        return d, machines[d]
    if len(machines) == 1:
        n = list(machines)[0]
        return n, machines[n]
    return '', None


def resolve(name=None, conf=None):
    """把配置摊平成一个 dict，环境变量可以逐项盖过它。"""
    conf = load_conf() if conf is None else conf
    mname, m = pick_machine(conf, name)
    out = dict(_DEFAULTS)
    out.update({k: v for k, v in (m or {}).items() if v not in (None, '')})
    out['name'] = mname
    # 环境变量优先（临时试另一个地址时不用改配置文件）
    if os.environ.get('REMOTE_HOSTS'):
        out['hosts'] = [h.strip() for h in os.environ['REMOTE_HOSTS'].split(',')
                        if h.strip()]
    for env, key in (('REMOTE_USER', 'user'), ('REMOTE_KEY', 'key'),
                     ('REMOTE_ROOT', 'root')):
        if os.environ.get(env):
            out[key] = os.environ[env]
    out['key'] = os.path.expanduser(out['key']) if out['key'] else ''
    return out


M = resolve(opt('--machine'))
HOSTS = list(M['hosts'])     # 顺序不是形式：排在前面的先试，连不上要等满
HOST = HOSTS[0] if HOSTS else ''   # ConnectTimeout 才换下一个。把常年断着的
USER = M['user']                   # 那个放前面，等于每条命令都白等十秒。
KEY = M['key']
ROOT_R = M['root']


def require_conf():
    """没配置就直接说清楚该做什么 —— 别让人对着一个空地址查半天。"""
    if HOSTS and USER and KEY:
        return True
    print('还没配好要操作哪台机器。' + _NL
          + f'  配置文件应该在：{CONF_FILE}' + _NL
          + '  照着仓库里的 machines.example.toml 抄一份过去，'
            '填上地址、账号、私钥路径。' + _NL
          + (f'  （读到配置了，但缺 hosts/user/key 之一；'
             f'这次选中的是：{M["name"] or "没选中任何一台"}）'
             if load_conf() else '  （现在这个文件不存在）'))
    return False


# 上次连通的是哪个地址、对面的 MAC 是多少 —— 按机器分开存。
LAST_GOOD = os.path.join(STATE_DIR, f'{M["name"] or "default"}.last_good')
MAC_FILE = os.path.join(STATE_DIR, f'{M["name"] or "default"}.mac')

# 对面控制台默认 GBK，不套这层壳中文输出全是乱码
_UTF8 = ("$OutputEncoding=[System.Text.Encoding]::UTF8; "
         "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
         "$env:PYTHONIOENCODING='utf-8'; ")

CONNECT_TIMEOUT = 10


def split_hostport(addr):
    """`地址` 或 `地址:端口` → (地址, 端口或 None)。

    端口写进 `hosts` 里而不是单开一个配置项，是因为**端口是跟着地址走的**：
    直连那条走 22，内网穿透/跳板那条走别的口，同一台机器两条路两个口。
    单独一个 `port` 只能表达「所有地址共用一个口」，那是错的模型。

    ⚠ 只在「最后一个冒号后面全是数字」时才当端口拆 —— 裸 IPv6 地址
    自带冒号，不加这个判据会把它拆坏。
    """
    host, sep, tail = addr.rpartition(':')
    if sep and tail.isdigit() and host:
        return host, tail
    return addr, None


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
def ssh_argv(script, timeout=None, host=None):
    """组一条 ssh 命令行。script 是要在 B 上跑的 PowerShell。"""
    addr, port = split_hostport(host or HOST)
    return (['ssh', '-i', KEY, '-o', 'BatchMode=yes',
             '-o', f'ConnectTimeout={timeout or CONNECT_TIMEOUT}']
            + (['-p', port] if port else [])
            + [f'{USER}@{addr}', _UTF8 + script])


def diagnose(stderr):
    """连不上时，把「看起来一样但根因完全不同」的几种情况分开。

    这是本工具存在的一半理由：sshd 对「账号不存在」和「公钥不对」
    回的是**同一句** `Permission denied (publickey,...)`，
    从这边怎么看都像密钥问题，能白查两轮。
    """
    e = (stderr or '').lower()
    if 'kex_exchange_identification' in e or 'connection closed by' in e:
        # ⚠ 这一条有**两种**根因，实测都见过。别只报一种 ——
        #   第一版只写了「睡眠」，结果连一个根本不存在的地址
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
        # ⚠ 这里原来只写「多半是关机或睡眠」，**把人带偏过一整晚**：
        #   当时对面其实醒着 ——
        #   事后查它的系统日志：三小时内零条电源事件，已连续运行 133 小时。
        #   断的是**路**，不是机器。而最可能接管这条路的，是本机自己的代理。
        return ('对面没应答。**别先认定它睡了**，也**别拿 ping 当判据**：\n'
                '\n'
                '  ⚠ 很多机器的防火墙不回 ICMP —— 实测过：ping 收到 0 个回包的'
                '同一秒，\n'
                '    SSH 连得好好的。所以「ping 不通」在这种机器上**什么都不能证明**，\n'
                '    我曾拿它当过证据，白查了一轮。要探活只能用 22 端口本身。\n'
                '\n'
                '  几种真实原因，症状一模一样：\n'
                '  ① 本机代理/VPN 接管了到局域网的路由。\n'
                '     判据：`Find-NetRoute -RemoteIPAddress ' + split_hostport(HOST)[0] + '` 看走的是哪块网卡；\n'
                '     走的不是局域网那块就是它。解法：把网段加进代理的直连规则。\n'
                '  ② 对面换了 IP（笔记本换网络时会）。\n'
                '  ③ **它有好几条腿** —— 一台多网卡的机器，不同的路通往不同的它：\n'
                '     无线断了但有线还活着时，它照常干活，只是你走的那条路没了。\n'
                '  ④ 真的关机或睡眠 —— **这条要拿证据**，别猜：\n'
                '     `Get-WinEvent -ProviderName Microsoft-Windows-Kernel-Power`，\n'
                '     没有电源事件就说明它压根没睡过。\n'
                '\n'
                '  这一条跟密钥、账号都无关，别往那个方向查。\n'
                '  **另外：连不上是常态而非异常，长作业一律用 `job ... --async` 发** ——\n'
                '  交给对面的计划任务跑，断线不影响它干活，重连后取结果。')
    if 'permission denied' in e:
        return ('被拒了。**这句话对「账号不存在」和「公钥不对」是同一句**，\n'
                '  在这边分不出来。决定性证据只在对面的 sshd 日志里 ——\n'
                '  让人在那台机器上跑一条：\n'
                '    Get-WinEvent -LogName OpenSSH/Operational -MaxEvents 12 | '
                'Select TimeCreated,Message\n'
                f'  写着 `Invalid user` = 账号错（现在用的是 {USER!r}，'
                '注意别用计算机名）；否则才是公钥的事。')
    if 'host key verification failed' in e:
        return ('主机密钥对不上 —— 对面重装过 sshd，或者你连到了别的机器上。\n'
                '  确认真的是那台之后，删掉 known_hosts 里那一行再连。')
    if 'no such file' in e and 'ssh' in e:
        return f'找不到私钥 {KEY} —— 换过电脑或换过用户目录？'
    return ''


# ssh 客户端自己刷的告警，跟我们要做的事无关，但它**每条命令都出现，而且在最后**。
# 后果不只是刷屏：`call()` 失败时只打印最后一行，于是真正的错误被这句挡住 ——
# 真事：一次装网络软件时，脚本报的错整段看不见，只看到「服务器该升级了」。
# **噪音盖住信号，就不只是噪音了。**
_SSH_NOISE = ('post-quantum', 'store now, decrypt later', 'openssh.com/pq.html',
              'The server may need to be upgraded')


def clean(out):
    """滤掉 ssh 客户端的固定告警，只留真正的输出。"""
    return _NL.join(l for l in (out or '').splitlines()
                    if not any(n in l for n in _SSH_NOISE)).strip()


# ssh 的约定：**255 是它自己的错**（连不上、认证失败、密钥不对），
# 其余退出码是**远端命令自己的**。124/127 是本工具在 run() 里造的
# （超时 / 找不到 ssh）。
SSH_OWN_ERROR = 255
TIMED_OUT = 124
NO_SSH = 127


def _may_have_run(rc):
    """这条命令有没有可能**已经在对面跑过了**。

    ⚠ 这个判断是安全要害，不是洁癖。早先 `call()` 把任何非零退出码都当成
    「这个地址不通」，于是换个地址**把整条命令从头再跑一遍**。
    2026-09-05 实测撞到：一批下载跑了 4 分多钟、超过内部超时被判 124，
    工具接着换地址重跑，前 3 篇被下了两遍。
    那次侥幸没损失（作业是幂等的，盘上有就跳过），但**换成调付费 API 的作业
    就是实实在在付两次钱，而且从输出上完全看不出来**。

    - `255` → ssh 自己没连上，命令**肯定没跑**，换个地址是安全的
    - `124`（超时）→ **最危险的一种**：命令很可能已经跑了，甚至跑完了
    - 其余 → 命令确实跑了，只是它自己失败了
    """
    return rc not in (SSH_OWN_ERROR,)


def call(script, timeout=180):
    """在 B 上跑一段 PowerShell。逐个候选地址试，返回 (成功?, 输出)。

    **只有「肯定没跑过」才换下一个地址** —— 见 `_may_have_run`。
    全部地址都连不上才算连接失败，报错时把每个地址各自的原因都列出来，
    因为它们可能完全不同（局域网那个是「不在同一个网」，
    公网那个可能是「换地址了」），只报最后一个会把人带偏。
    """
    tried = []
    for host in candidates():
        rc, out = run(ssh_argv(script, host=host), timeout=timeout)
        if rc == 0:
            _remember_good(host)
            return True, clean(out)
        if rc == NO_SSH:
            return False, clean(out)      # 换地址也没用，是本机没有 ssh
        if _may_have_run(rc):
            # 连上了、命令也跑了（或超时，可能跑了一半甚至跑完了）。
            # **绝不能换个地址重跑** —— 那是二次执行。
            _remember_good(host)
            note = ''
            if rc == TIMED_OUT:
                note = (_NL + '⚠ 这条命令**超时了，但它很可能还在对面继续跑**。'
                        + _NL + '  没有换地址重试 —— 重试等于让它跑第二遍。'
                        + _NL + '  长作业请用 `job ... --async` 发，别用 run。')
            return False, clean(out) + note
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
    """趁对面醒着，把它的 MAC 记下来 —— 唤醒包只能用 MAC 发。

    **只有它醒着时才拿得到**（ARP 要它回话）。所以每次连通都顺手记一次：
    等到真需要唤醒的那天，它已经睡了，那时再想拿就晚了。
    """
    out = powershell(
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
    """发网络唤醒包（Wake-on-LAN）。

    ⚠ **别把这条当成退路 —— 实测过一次完全无效。** MAC 拿到了、包也发出去了，
      对面没醒。至少有一条不成立：网卡与 BIOS 开了「允许此设备唤醒计算机」、
      或者它是**有线**连着的（大多数无线网卡睡眠后根本不响应唤醒包）。
      两条都只能在那台机器跟前确认。**「以为有退路」比「知道没有」更危险。**

    该常开的机器，正路是干脆别让它睡：

        powercfg /change standby-timeout-ac 0
        powercfg /change hibernate-timeout-ac 0
    """
    mac = M.get('mac') or ''
    if not mac and os.path.isfile(MAC_FILE):
        mac = io.open(MAC_FILE, encoding='utf-8').read().strip()
    mac = (opt('--mac') or mac).replace(':', '-').upper()
    if len(mac) != 17:
        print('不知道对面的 MAC，发不了唤醒包。' + _NL
              + '  它只能在对面醒着的时候拿到 —— 下次连通时 check 会自动记下来。' + _NL
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
    """连得上吗、是谁、代码到哪一版、任务活着没。

    问的都是**配置里说了的**那些：没配 root 就不问代码版本，没配 tasks 就不问任务 ——
    对一台没有项目目录的机器打印一行 `Set-Location` 失败，只会让人以为连接坏了。
    """
    parts = ['Write-Output ("主机名: " + $env:COMPUTERNAME)',
             'Write-Output ("账号:   " + (whoami))']
    if ROOT_R:
        parts += [f'Set-Location "{ROOT_R}"',
                  'Write-Output ("代码:   " + (git log --oneline -1))',
                  'Write-Output ("分支:   " + (git rev-parse --abbrev-ref HEAD))']
    if M['tasks']:
        names = ','.join(f"'{t}'" for t in M['tasks'])
        parts += ['$t = Get-ScheduledTask | Where-Object {$_.TaskName -in @('
                  + names + ')}',
                  'foreach ($x in $t) { Write-Output ("任务:   " + $x.TaskName '
                  '+ " = " + $x.State) }']
    ok, out = call('; '.join(parts), timeout=90)
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
    """一个日志名 → 它可能在的位置（配置里的 `logs` 给模板，可以给多条）。

    为什么允许多条：写死一个的话，连上去只会看到「文件不存在」，
    而那看起来像**服务没在写日志** —— 一个足以让人查错方向的假象。
    改过目录布局的项目尤其要把老位置也留着，回滚时才读得到。
    """
    return [f'{ROOT_R}/' + t.format(name=name) for t in M['logs']]


def cmd_logs(name=None, lines=40):
    """看日志尾部。

    ⚠ **`-Encoding utf8` 一个都不能少。** 日志文件是 UTF-8，而对面的
    PowerShell 默认按系统代码页（GBK）读文件 —— 顶上那层 UTF-8 外壳只管
    **输出**编码，管不到**读文件**这一步。少了它中文全是
    `[蹇冭烦] 杞姝ｅ父` 这种乱码（实测撞到过）。编码会在三个地方分别咬人：
    控制台输出、子进程、**读文件** —— 这是第三个。
    """
    name = name or M['default_log']
    if not name:
        print('要给日志名：remote.py logs <名字>（或者在配置里写上 default_log）')
        return 2
    tried = ' , '.join(f"'{p}'" for p in log_paths(name))
    ok, out = call(
        f'$found = $false; '
        f'foreach ($p in @({tried})) {{ '
        f'  if (Test-Path $p) {{ '
        f'    Write-Output ("--- " + $p + " ---"); '
        f'    Get-Content $p -Tail {int(lines)} -Encoding utf8; '
        f'    $found = $true; break }} }} '
        f'if (-not $found) {{ Write-Output "这些位置下都没有这个日志：{name}" }}',
        timeout=120)
    print(out)
    return 0 if ok else 1


def cmd_deploy():
    """在对面跑「上线脚本」（`deploy_cmd`，由配置指定）。

    ⚠ **部署不等于把文件换掉。** 只要对面有常驻进程（服务、面板、守护任务），
    `git pull` 之后它们**照跑旧代码，而且没有任何迹象表明它是旧的** ——
    这条坑真咬过：更新完打开面板，新加的设置项根本不显示，
    因为老进程还占着端口跑着旧代码，新起的进程绑不上端口直接死了。

    所以这里**不自己拼** pull/装包/重启那几步，而是跑项目自己的上线脚本 ——
    只有它知道该重启谁。在这里抄一遍，两份迟早不一致。
    """
    if not M['deploy_cmd']:
        print('这台机器没配 deploy_cmd —— 在配置里写上「上线脚本怎么跑」再用这条。')
        return 2
    print(f'在对面跑：{M["deploy_cmd"]}' + _NL)
    ok, out = call(f'Set-Location "{ROOT_R}"; {M["deploy_cmd"]}',
                   timeout=int(opt('--timeout') or 1800))
    print(out)
    return 0 if ok else 1


def cmd_task(name):
    """触发一个**已注册**的计划任务。

    计划任务的登录会话**能读凭据库**（跟 SSH 会话不同），所以这条路跑得动
    要密钥的作业 —— 它的边界是「只能做那个任务本来就做的事」。要跑别的用 `job`。
    """
    safe = set(M['tasks'])
    if name not in safe:
        print(f'不认识的任务 {name!r}。配置里列出的：{sorted(safe)}' + _NL
              + '（白名单在这里是防手滑，不是防坏人 —— 真要跑别的，改配置里的 tasks。）')
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
    """把一个本地文件传到对面的**绝对路径**。返回 (成功?, 输出)。

    ⚠ 逐个候选地址试，跟 `call()` 一样 —— 早先这里写死了第一个地址，
    于是「ssh 连得上、scp 连不上」：ssh 用的是记住的那个好地址，
    push 用的却永远是列表里的第一个。同一台机器，两条路不一致最难查。
    """
    out = ''
    for host in candidates():
        addr, port = split_hostport(host)
        rc, out = run(['scp', '-i', KEY, '-o', 'BatchMode=yes',
                       '-o', f'ConnectTimeout={CONNECT_TIMEOUT}']
                      + (['-P', port] if port else [])   # scp 是 -P 不是 -p
                      + [local, f'{USER}@{addr}:{remote_abs}'], timeout=300)
        out = clean(out)
        if rc == 0:
            _remember_good(host)
            return True, out
    return False, out


def _push_via_ssh(local, remote_abs):
    """不用 scp，把文件 base64 塞进一条普通 ssh 命令里传过去。

    **为什么需要这条退路**（2026-09-06 实测）：内网穿透/端口映射这类通道
    （UU 远程那种）**转发得了 ssh、却扛不住 scp** —— scp 会另开连接谈 sftp 子系统，
    在那种通道上直接死在 banner exchange。症状很迷惑人：
    同一时刻 `ssh` 好好的，`scp` 连着六次退出码 255。

    所以判据是：**「ssh 通」不等于「传得了文件」**，这俩要分开验。

    代价：base64 会把体积撑大三分之一，而且整个塞进命令行，
    所以只当退路用，大文件仍应走 scp（或者先分卷）。
    """
    import base64
    with io.open(local, 'rb') as fh:
        b64 = base64.b64encode(fh.read()).decode('ascii')
    if len(b64) > 1_000_000:      # 命令行长度有上限，太大的别硬来
        return False, ('这个文件太大（base64 后 %.1f MB），塞不进命令行。'
                       '请改用能走 scp 的地址，或者先切小。' % (len(b64) / 1e6))
    dest = remote_abs.replace('/', chr(92))    # 正斜杠 → 反斜杠（Windows 路径）
    script = (f"$d = Split-Path '{dest}'; "
              f"if ($d -and -not (Test-Path $d)) "
              f"{{ New-Item -ItemType Directory -Force $d | Out-Null }}; "
              f"[IO.File]::WriteAllBytes('{dest}', "
              f"[Convert]::FromBase64String('{b64}')); "
              f"Write-Output ('已写入 ' + '{dest}')")
    return call(script, timeout=300)


def cmd_push(local, remote_rel):
    """把一个本地文件传到对面的项目目录下（复杂脚本别硬拼引号，传过去再跑）。"""
    if not os.path.isfile(local):
        print(f'找不到本地文件：{local}')
        return 2
    remote_abs = f'{ROOT_R}/{remote_rel}'
    ok, out = scp_to(local, remote_abs)
    if not ok:
        # scp 全军覆没时的退路：穿透通道常常「ssh 通但 scp 不通」，
        # 这条走普通 ssh，绕开 sftp 子系统。
        print('scp 走不通，改用 ssh 直传（穿透通道常这样）…')
        ok, out = _push_via_ssh(local, remote_abs)
    if not ok:
        print(out)
        tip = diagnose(out)
        if tip:
            print(_NL + tip)
        return 1
    print(f'已传到 {ROOT_R}/{remote_rel}')
    print('⚠ 跑完记得删掉临时文件 —— 别在对面留一地的 _tmp。')
    return 0


# ── 作业通道：让 B 用「它自己的身份」干活 ────────────────────────────
# 为什么要有这一段（实测出来的边界，不是推断）：
#   公钥 SSH 建立的是**网络登录会话**，Windows 凭据管理器在这种会话里打不开 ——
#   实测报的是 `CredRead: 指定的登录会话不存在。可能已被终止。`
#   所以从 SSH 直接发起的作业，读密钥拿到的是空串，
#   跑到第一次真要用它时才废 —— 前面花掉的额度全白费。
#
#   而**计划任务**跑在交互登录会话里（`LogonType=Interactive`），那个会话解得开
#   凭据库 —— 一台机器上按计划跑的付费作业天天在成功，就是活证据。
#
#   于是这条通道的做法是：**不新起常驻进程**，只注册一个按需触发的计划任务，
#   它执行一个固定的外壳；外壳读同目录下的 payload，跑完把输出和退出码落盘。
#   这边写 payload → 触发 → 等 done 文件 → 取输出。
#   等于「让它自己去跑」，而不是「我在它上面跑」—— 差的就是那把凭据。
JOB_TASK = M['job_task']
# 放在仓库外：项目目录迟早会搬，这条通道不该跟着一起搬
JOB_DIR = M['job_dir']
JOB_WRAPPER = JOB_DIR + '/job.ps1'
JOB_PAYLOAD = JOB_DIR + '/payload.ps1'
JOB_OUT = JOB_DIR + '/job.out'
JOB_DONE = JOB_DIR + '/job.done'


def wrapper_source():
    """外壳脚本的内容。

    由这里生成而不是另存一个 .ps1，是为了让它和上面那几个常量、和 `ROOT_R`
    **只有一处定义** —— 两份迟早不一致，而不一致的那天看起来像「任务没触发」。
    """
    return _NL.join([
        "$ErrorActionPreference = 'Continue'",
        '$OutputEncoding = [System.Text.Encoding]::UTF8',
        '[Console]::OutputEncoding = [System.Text.Encoding]::UTF8',
        "$env:PYTHONIOENCODING = 'utf-8'",
        f"Remove-Item '{JOB_DONE}' -ErrorAction SilentlyContinue",
        f"Set-Location '{ROOT_R}'",
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
    实测第一版的输出是 `瀵嗛挜闀垮害: 35` 这种。
    这是编码咬人的第四个地方：前三个是控制台输出、子进程、读文件，
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
    照抄一份「已经在跑付费作业」的任务的配置就对了。改成 S4U / ServiceAccount
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
        "-Settings $s -Description '远程按需触发的作业通道' -Force | Out-Null; "
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
        f"Start-ScheduledTask -TaskName '{JOB_TASK}'; Write-Output '已交给对面'",
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
    args = positionals()
    action = (args[0] if args else '').lower()
    if not action or flag('-h') or flag('--help'):
        print(__doc__)
        print(f'这次选中的机器：{M["name"] or "（一台都没选中）"}'
              + (f'  {M["label"]}' if M['label'] else '')
              + _NL + f'配置文件：{CONF_FILE}')
        return 0
    # 没配置就别往下走 —— 对着一个空地址报「连不上」，人会去查网络，
    # 而真相是这台机器根本没写进配置。
    if not require_conf():
        return 2

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
        return cmd_logs(args[1] if len(args) > 1 else None,
                        args[2] if len(args) > 2 else 40)
    if action == 'deploy':
        return cmd_deploy()
    if action == 'task':
        if len(args) < 2:
            print('要给任务名：remote.py task <名字>（配置里 tasks 列出的那些）')
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
