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

**安全铁律，本文件负责执行**（`check()`）—— 2026-09-01 从「一律不许」改成**三档**：

原来的规则是「花钱的一律不许当 tool」。它把「问一次库（几分钱、不写任何东西）」
和「全库向量化（全库作业）」当成了同一件事 —— 代价差两三个数量级，
结果是用户日常最常做的事反而最别扭。

现在按**代价量级 + 可不可逆**分：

| 档 | 例子 | 怎么暴露 |
|---|---|---|
| 单次、便宜、可重来 | 问一次库、抽一篇、读一张图 | `tool` + `confirm=True` |
| 全库作业 | 全库重抽 / 向量化、建方向图 | `prompt`（人点） |
| 不可逆写 Zotero | 删条目、批量改名、改标签、按 DOI 导入 | `prompt`（人点） |

`confirm=True` 会给工具打上 `anthropic/requiresUserInteraction`，
Claude Code 于是**每次调用都弹窗，且不给「不再询问」的选项**
（查证 2026-09-01，需 ≥ 2.1.199）。

**两道闸，缺一不可**：
1. `tool.toml` 的 `agent_tools` 白名单 —— 哪几个入口允许模型发起，写在清单里，
   一眼能看见，加一个是显式动作。**这是给人看的那道闸。**
2. `confirm=True` —— 客户端强制弹窗。**这是给运行时的那道闸。**

⚠ 第 2 道是 **Claude Code 专有的**（`anthropic/` 前缀），换客户端会被忽略。
所以 `shared.kernel.role.require_prod` 那道机器角色闸**必须继续留着** ——
它不依赖任何客户端。

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


def check(report=None, server=None):
    """清单自洽吗？返回问题列表（空 = 全对）。`--list` 与自测都靠它。

    ⚠ `server` 必须是**真正注册过的那个**。`confirm` 标记只活在 server 的
    工具表里，report 里没有 —— 传进来 report 却不传 server 的话，这里会拿一个
    空壳去查，于是「漏了 confirm」永远查不出来（2026-09-01 验红时抓到）。
    所以不传 server 就自己重新注册一份，绝不拿空壳凑合。
    """
    from host.mcp.stdio import MCPStdioServer
    if server is None:
        server = MCPStdioServer('check', '0')
        if report is None:
            report = register_all(server)
        else:
            register_all(server)       # 只为拿到 confirm 标记，报告仍用传进来的
    elif report is None:
        report = register_all(server)
    server_tools = list(server._tools)
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
        # ★ 安全铁律（2026-09-01 从「一律不许」改成三档，理由见本文件顶部）
        risky = bool(man.get('costs_money')) or bool(man.get('side_effects'))

        # 白名单里写着、却根本没这个 tool —— 名单在说谎。
        # ⚠ 这条**必须独立于「这次注册了几个 tool」**：一个 tool 都没注册的工具
        #   照样可能有一份过时的白名单（改名或删掉入口时忘了跟着改）。
        #   第一版把它写在 `if got.get('tool')` 里面，于是那种情况永远查不到
        #   （2026-09-01 第三轮验红才抓到）。
        _names = {t['name'] for t in server_tools}
        ghost = [x for x in (man.get('agent_tools') or []) if x not in _names]
        if ghost:
            problems.append(
                f'{name}: agent_tools 里写着 {ghost}，但没有这个 tool —— '
                f'名单在说谎，改名或删掉入口时忘了跟着改')

        if got.get('tool') and risky:
            allowed = set(man.get('agent_tools') or [])
            outside = [t for t in got['tool'] if t not in allowed]
            if outside:
                problems.append(
                    f"{name}: 注册了 tool {outside}，但它们不在 tool.toml 的 "
                    f"agent_tools 白名单里（现在是 {sorted(allowed) or '空'}）。"
                    f"花钱/有副作用的入口要让模型能自己发起，必须先写进白名单 —— "
                    f"那张表就是给人看的那道闸")
            no_confirm = [t['name'] for t in server_tools
                          if t['name'] in got['tool'] and not t.get('confirm')]
            if no_confirm:
                problems.append(
                    f"{name}: tool {no_confirm} 花钱/有副作用，却没带 confirm=True —— "
                    f"客户端不会强制弹窗，用户点一次「不再询问」之后就再也不问了")
    return problems
