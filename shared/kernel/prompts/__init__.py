# -*- coding: utf-8 -*-
"""prompts · 提示词的唯一读取口（公理：一段提示词 = 一个只增不改的版本文件）

**为什么需要它**：重构前提示词有两种活法 —— 精读那段在
一个 `*_v2.txt` 文件里（版本写在文件名上），其余七八段直接以
`SYS = "..."` 的形式硬编码在 .py 里。后者有三个真实代价：

1. **改了看不出来**。改一句措辞和改一行逻辑在 diff 里长得一样，
   而「精读为什么突然变差了」这种问题，答案九成在提示词里。
2. **没有版本**。`jobs.stale('main_summary', prompt_ver=3)` 这套
   「提示词变了就该重跑」的机制，只有精读享受得到，因为只有它的版本号是真的。
3. **改不动**。用户不懂编程，让他去 .py 里找一段中文字符串等于不让他改。

所以规矩是：**提示词是数据，不是代码**，住在 `<工具>/prompts/<名>_v<N>.txt`，
**只增不改** —— 要改措辞就新建 v(N+1)，旧版本留着，
这样「用 v2 跑出来的」和「用 v3 跑出来的」永远能区分开。

## 为什么在 kernel 而不是 adapters

它只做「按名字和版本读一个文本文件」，不联网、不调模型、不认识任何外部服务。
外部世界变了它不用改 —— 那是 kernel 的判据。

对外接口：
  - load(owner, spec)      'main@v2' / 'main'（不写版本 = 最新）→ 提示词文本
  - latest(owner, name)    最大版本号；一个都没有返回 None
  - versions(owner, name)  [1, 2, 3]
  - listing(owner)         ['main@v2', 'si@v1'] —— 给 tool.toml 的 prompts 字段校验用
  - path(owner, name, ver) 文件路径（不检查存在性）
  - MissingPrompt          找不到时抛它（继承 DataError：重试没用，要人来看）

用法：
    from shared.kernel import prompts
    SYS = prompts.load('deepread', 'main@v2')          # 工具名 → tools/deepread/prompts/
    S   = prompts.load('shared/adapters/query_expand', 'survey@v1')   # 带斜杠 = 相对仓库根
"""
import os
import re

from shared.kernel import paths
from shared.kernel.errors import DataError

# 文件名形状：<名>_v<版本>.txt。名字只许小写字母数字下划线，
# 版本必须是纯数字 —— 这两条限制换来的是「文件名可以被机器可靠地解析回 name@vN」。
_FILE_RE = re.compile(r'^([a-z][a-z0-9_]*)_v([0-9]+)\.txt$')

_CACHE = {}     # 路径 → 文本。只增不改，所以读过一次就不会变（见上）


class MissingPrompt(DataError):
    """点名要的提示词不在盘上。消息里要列出现有哪些版本，否则没法自查。"""


def dir_of(owner):
    """owner → 它的 prompts 目录。

    owner 有两种写法，**带不带斜杠就是区别**：
      - `'deepread'`                        → `tools/deepread/prompts/`（工具，最常见）
      - `'shared/adapters/query_expand'`    → 相对仓库根的包路径（共用件也可以有提示词）
    """
    parts = owner.split('/') if '/' in owner else ('tools', owner)
    return os.path.join(paths.ROOT, *parts, 'prompts')


def parse_spec(spec):
    """`'main@v2'` → `('main', 2)`；`'main'` → `('main', None)`（None = 要最新的）。"""
    name, _, ver = (spec or '').partition('@')
    name = name.strip()
    if not name:
        raise ValueError(f'提示词标识不能为空：{spec!r}')
    ver = ver.strip()
    if not ver:
        return name, None
    if not (ver.startswith('v') and ver[1:].isdigit()):
        raise ValueError(f'提示词版本要写成 v<数字>，例如 main@v2；收到 {spec!r}')
    return name, int(ver[1:])


def versions(owner, name):
    """`owner` 下叫 `name` 的提示词有哪些版本，升序。目录不存在就是空列表。"""
    d = dir_of(owner)
    try:
        names = os.listdir(d)
    except OSError:
        return []
    out = []
    for fn in names:
        m = _FILE_RE.match(fn)
        if m and m.group(1) == name:
            out.append(int(m.group(2)))
    return sorted(out)


def latest(owner, name):
    """最大版本号；一个都没有返回 None。"""
    vs = versions(owner, name)
    return vs[-1] if vs else None


def listing(owner):
    """`owner` 现有的全部提示词，形如 `['main@v2', 'si@v1']`（每个名字只列最新版）。

    `host/mcp/registry.check()` 拿它对 `tool.toml` 的 `prompts` 字段做自洽校验。
    """
    d = dir_of(owner)
    try:
        names = os.listdir(d)
    except OSError:
        return []
    best = {}
    for fn in names:
        m = _FILE_RE.match(fn)
        if not m:
            continue
        n, v = m.group(1), int(m.group(2))
        if v > best.get(n, 0):
            best[n] = v
    return [f'{n}@v{best[n]}' for n in sorted(best)]


def path(owner, name, ver):
    """拼路径，不检查存在性。"""
    return os.path.join(dir_of(owner), f'{name}_v{ver}.txt')


def load(owner, spec):
    """读一段提示词。`spec` 写成 `'main@v2'`（钉死版本）或 `'main'`（要最新的）。

    **调用方应当钉死版本** —— 提示词版本要跟着结果一起进状态库，
    才能回答「这篇是哪一版跑的、该不该重跑」。不钉版本只适合一次性的探索。
    """
    name, ver = parse_spec(spec)
    if ver is None:
        ver = latest(owner, name)
        if ver is None:
            raise MissingPrompt(
                f'{dir_of(owner)} 里没有名叫 {name} 的提示词'
                f'（现有：{", ".join(listing(owner)) or "空"}）')
    p = path(owner, name, ver)
    if p in _CACHE:
        return _CACHE[p]
    try:
        with open(p, encoding='utf-8') as f:
            text = f.read()
    except OSError as e:
        raise MissingPrompt(
            f'读不到提示词 {name}@v{ver}：{p}'
            f'（该目录现有：{", ".join(listing(owner)) or "空"}）—— {e}')
    if not text.strip():
        raise MissingPrompt(f'提示词是空的：{p} —— 空提示词会让模型自由发挥，不许静默使用')
    _CACHE[p] = text
    return text
