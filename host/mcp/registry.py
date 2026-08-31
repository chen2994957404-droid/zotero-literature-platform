# -*- coding: utf-8 -*-
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
"""host.mcp.registry · 工具清单：读每个 `tools/<t>/tool.toml`，挂上它的 `mcp.py`。

**这里没有任何硬编码的工具名。** 加一个工具 = 建一个 `tools/<新名>/` 文件夹，
放上 `tool.toml` 与 `mcp.py`，MCP 服务下次启动就有了 —— 不用改这里，
也不用改服务端。R4 窗之前不是这样：`zotero_server.py` 里手写着 10 个工具的
注册表，加一个能力要改三处，于是没人加。

`tool.toml` 的字段（格式见 REBUILD.md 第二节）：

| 字段 | 意思 |
|---|---|
| `name` / `one_line`  | 工具名 / 一句话说明（给人和模型看的第一印象）|
| `expose`             | 主暴露方式：tool / resource / prompt / internal |
| `costs_money`        | 跑一次会不会花钱 |
| `side_effects`       | 会改哪些外部状态（写 Zotero、写数据目录…）|
| `requires_role`      | 需要哪档机器角色：none / test / prod |
| `prompts`            | 用到的提示词版本，如 `["main@v2"]`；`check()` 会核对文件真在 |

**一条安全铁律，本文件负责执行**（`check()`）：
**花钱的、有副作用的工具，不许注册成 MCP `tool`。**
tool 是模型可以自己调的，prompt 是人在客户端里点的 ——
钱和副作用必须停在人这一侧。只读又免费的才配当 tool。

对外接口：
  - slices()              : [(名字, 目录, 清单 dict)]，按名字排序
  - register_all(server)   : 把所有工具的 MCP 面挂上去，返回每个工具注册了什么
  - check()               : 清单与实际注册是否一致 → 问题列表（空 = 全对）
"""
import tomllib

from shared.kernel import prompts as _prompts

from shared.kernel import paths

TOOLS_DIR = os.path.join(paths.ROOT, 'tools')
KINDS = ('tool', 'resource', 'prompt', 'internal')

REQUIRED = ('name', 'one_line', 'expose')


def slices():
    """所有工具切片：[(name, dir, manifest)]。没有 tool.toml 的目录 manifest 为 None。"""
    out = []
    if not os.path.isdir(TOOLS_DIR):
        return out
    for name in sorted(os.listdir(TOOLS_DIR)):
        d = os.path.join(TOOLS_DIR, name)
        if not os.path.isfile(os.path.join(d, '__init__.py')):
            continue
        out.append((name, d, load_manifest(d)))
    return out


def load_manifest(tool_dir):
    """读一个 tool.toml；没有或读不动返回 None（由调用方报告，不在这里炸）。"""
    p = os.path.join(tool_dir, 'tool.toml')
    if not os.path.isfile(p):
        return None
    try:
        with open(p, 'rb') as f:
            return tomllib.load(f)
    except Exception:
        return None


def register_all(server):
    """把每个工具的 `mcp.py` 挂到 server 上。

    返回 [(名字, 清单, {'tool': [名], 'resource': [uri], 'prompt': [名]})]。
    某个工具的 mcp.py 挂了不该拖垮整个服务 —— 记下来继续，客户端至少还能用别的。
    """
    import importlib
    report = []
    for name, d, man in slices():
        if not man or man.get('expose') == 'internal':
            continue
        before = _snapshot(server)
        try:
            mod = importlib.import_module(f'tools.{name}.mcp')
            mod.register(server)
        except Exception as e:
            report.append((name, man, {'error': f'{type(e).__name__}: {e}'}))
            continue
        report.append((name, man, _diff(before, _snapshot(server))))
    return report


def _snapshot(server):
    return ([t['name'] for t in server._tools],
            [r['uri'] for r in server._resources],
            [p['name'] for p in server._prompts])


def _diff(before, after):
    return {k: [x for x in a if x not in b]
            for k, b, a in zip(('tool', 'resource', 'prompt'), before, after)}


def check(report=None):
    """清单自洽吗？返回问题列表（空 = 全对）。`--list` 与自测都靠它。"""
    from host.mcp.stdio import MCPStdioServer
    if report is None:
        report = register_all(MCPStdioServer('check', '0'))
    problems = []
    for name, d, man in slices():
        if man is None:
            problems.append(f'{name}: 缺 tool.toml（R4 窗要求每个工具都有）')
            continue
        for f in REQUIRED:
            if not man.get(f):
                problems.append(f'{name}: tool.toml 缺字段 {f}')
        if man.get('expose') not in KINDS:
            problems.append(f"{name}: expose={man.get('expose')!r} 不在 {KINDS}")
        if man.get('name') != name:
            problems.append(f"{name}: tool.toml 里的 name={man.get('name')!r} 与文件夹名不一致")
        for f in ('cli.py', 'mcp.py', 'README.md', 'SKILL.md'):
            if not os.path.isfile(os.path.join(d, f)):
                problems.append(f'{name}: 缺 {f}')
        # R5：声明用了哪版提示词，那一版就得真的在盘上。
        # 不查的话，`prompts = ["main@v3"]` 可以一直写着而文件只有 v2，
        # 直到某天真去调模型才炸 —— 那时已经花了解析的钱。
        for spec in man.get('prompts') or []:
            try:
                _prompts.load(name, spec)
            except Exception as e:
                problems.append(f'{name}: tool.toml 声明 prompts={spec!r}，但读不到 —— {e}')

    for name, man, got in report:
        if 'error' in got:
            problems.append(f"{name}: mcp.py 挂了 —— {got['error']}")
            continue
        expose = man.get('expose')
        if expose in ('tool', 'resource', 'prompt') and not got.get(expose):
            problems.append(f'{name}: 声明 expose={expose}，但 mcp.py 一个都没注册')
        # ★ 安全铁律：花钱/有副作用的，不许当模型能自己调的 tool
        if got.get('tool') and (man.get('costs_money') or man.get('side_effects')):
            problems.append(
                f"{name}: 花钱或有副作用（costs_money={man.get('costs_money')}, "
                f"side_effects={man.get('side_effects')}），却注册了 tool "
                f"{got['tool']} —— 这类只能注册成 prompt（由人点）")
    return problems
