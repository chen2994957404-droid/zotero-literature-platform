# -*- coding: utf-8 -*-
"""{{NAME}} —— {{DESC}}

    python {{NAME_MOD}}.py <子命令> [参数]
    python {{NAME_MOD}}.py --help

配置在 `~/.{{NAME}}/config.toml`（照着仓库里的 config.example.toml 抄）。
不依赖任何第三方库，Python 3.11+ 即可。
"""
import io
import os
import subprocess
import sys
import tomllib

# 中文 Windows 控制台默认 GBK，不这么写中文输出就是乱码
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

_NL = chr(10)
_NOWIN = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0

HOME = os.path.expanduser('~')
CONF_DIR = os.environ.get('{{ENV_PREFIX}}_HOME',
                          os.path.join(HOME, '.{{NAME}}'))
CONF_FILE = os.path.join(CONF_DIR, 'config.toml')


# ── 取参：自己带一份，免得为了三个函数拖一个依赖 ──────────────────────

def positionals():
    """位置参数 —— **只算到第一个 `--选项` 为止**。

    不能简单地「过滤掉带横杠的」：那样 `cmd 主题 --limit 20` 里的 `20`
    会被当成第三个位置参数，而这种错**不会报错，只会安静地做错事**。
    选项后面跟的到底是它的值还是位置参数，从命令行本身无法判断，
    所以约定：位置参数一律写在选项前面。
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
    a = sys.argv[1:]
    for i, x in enumerate(a):
        if x == name and i + 1 < len(a):
            return a[i + 1]
        if x.startswith(name + '='):
            return x.split('=', 1)[1]
    return default


def run(argv, timeout=180):
    """跑子进程，按 UTF-8 解码。返回 (退出码, 合并输出)。

    `errors='replace'` 不能省：一个解码异常会把整条命令的输出全丢掉，
    而那正是你要看的报错。

    ⚠ **光在这头按 UTF-8 解码是不够的**：Windows 上子进程默认按系统区域编码
    写 stdout（中文系统是 GBK），这头再怎么 UTF-8 解也是乱码。必须同时给子进程
    注入 PYTHONIOENCODING —— 骨架自带的冒烟测试就在验这一条，
    2026-09-08 它在一台 cp936 的机器上真的红了。
    """
    env = dict(os.environ)
    env.setdefault('PYTHONIOENCODING', 'utf-8')
    env.setdefault('PYTHONUTF8', '1')      # Python 3.7+ 的 UTF-8 模式，双保险
    try:
        p = subprocess.run(argv, capture_output=True, timeout=timeout,
                           env=env, creationflags=_NOWIN)
    except FileNotFoundError:
        return 127, f'找不到命令：{argv[0]}'
    except subprocess.TimeoutExpired:
        return 124, f'超时（{timeout} 秒）'

    def dec(b):
        return (b or b'').decode('utf-8', 'replace')

    return p.returncode, dec(p.stdout) + dec(p.stderr)


# ── 配置 ──────────────────────────────────────────────────────────────

def load_conf(path=None):
    try:
        with io.open(path or CONF_FILE, 'rb') as fh:
            return tomllib.load(fh)
    except OSError:
        return {}
    except tomllib.TOMLDecodeError as e:
        # 静默当成空配置，表现会是「怎么都不好使」，而人会去查错方向
        print(f'配置文件读不动（{path or CONF_FILE}）：{e}')
        return {}


CONF = load_conf()


def require_conf():
    """没配置就直接说清楚该做什么，别让人对着一个空壳查半天。"""
    if CONF:
        return True
    print('还没配置。' + _NL
          + f'  配置文件应该在：{CONF_FILE}' + _NL
          + '  照着仓库里的 config.example.toml 抄一份过去。')
    return False


# ── 子命令 ────────────────────────────────────────────────────────────

def cmd_hello():
    print('骨架跑通了。把真正的功能写在这里，然后删掉这条。')
    return 0


def main():
    args = positionals()
    action = (args[0] if args else '').lower()
    if not action or flag('-h') or flag('--help'):
        print(__doc__)
        print(f'配置文件：{CONF_FILE}'
              + ('（已读到）' if CONF else '（还不存在）'))
        return 0

    if action == 'hello':
        return cmd_hello()

    print(f'不认识的子命令：{action!r}')
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main())
