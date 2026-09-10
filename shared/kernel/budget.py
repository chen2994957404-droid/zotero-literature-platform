# -*- coding: utf-8 -*-
"""budget · 每天花多少的账本与闸门 —— **不依赖客户端，装在服务端**。

## 为什么必须在服务端（2026-09-10）

平台原本的花钱防线是 MCP 的 `confirm=True`：客户端每次调用都弹窗、且不给
「不再询问」。**但那个标记是 Claude Code 专有的**（`anthropic/requiresUserInteraction`），
不是 MCP 标准 —— **Antigravity 直接忽略它**，花钱的工具在那边退化成普通工具。
`stdio.py` 里早就写着这句话，2026-09-10 变成了现实：外部 agent 一次批量精读
10 篇，余额从 2.48 元掉到 1.04 元，全程没有任何人确认。

`role.require_prod` 挡不住这个 —— 它管的是「能不能在这台机器上写」，
**不管「要不要花这笔钱」**。所以需要这一块：

> **边界管种类，限额管量级，两个都要。**

## 设计上的三个取舍

1. **默认只记账、不拦。** 往一条正在生产上跑的流水线里塞硬性中断，
   是比超支更糟的意外（watcher 可能跑到一半被砍）。所以限额默认 0 = 不限；
   先让用户看见「今天花了多少」，再由他自己定这个数。
2. **拦在调用之前，不在中途。** 一次调用要么完整发生要么不发生 ——
   半截的精读比不精读更难收拾。
3. **账本坏了不能挡住干活。** 读写账本的任何异常都吞掉并放行：
   记账是辅助，不是主线。宁可少记一笔，不可因为记账失败而停摆。

## 用法

```python
from shared.kernel import budget

budget.check('deepread')            # 超了抛 BudgetExceeded；没设限额时永远放行
budget.record(prompt=1200, completion=8000, model='deepseek-v4-flash')
budget.today()                      # {'date','calls','prompt','completion','limit_*'}
```

## 限额怎么设

走 `shared.kernel.config`，用户在控制面板里填：

| 配置项 | 含义 | 默认 |
|---|---|---|
| `DAILY_LLM_CALLS` | 一天最多多少次付费调用 | 0＝不限 |
| `DAILY_LLM_TOKENS` | 一天最多多少产出 token（精读这类长文的主要成本） | 0＝不限 |
"""
import io
import json
import os
import time

from shared.kernel import paths
from shared.kernel.errors import PlatformError

LEDGER = 'llm_budget.json'          # 落在 logs/ 下，跟心跳、锁同处，便于一并清理


class BudgetExceeded(PlatformError):
    """今天的额度用完了。**这不是故障，是刹车。**"""


def _today():
    return time.strftime('%Y-%m-%d')


def _limits():
    """从配置读限额。读不到或读到垃圾一律当 0（不限）—— 配置错不该变成拦路虎。"""
    from shared.kernel.config import get_key
    out = {}
    for name, key in (('calls', 'DAILY_LLM_CALLS'), ('tokens', 'DAILY_LLM_TOKENS')):
        try:
            out[name] = max(0, int(str(get_key(key, default='') or '0').strip() or 0))
        except (TypeError, ValueError):
            out[name] = 0
    return out


def _load():
    """读今天的账。**换了一天就自动从零开始**，不必有人来清。"""
    blank = {'date': _today(), 'calls': 0, 'prompt': 0, 'completion': 0, 'models': {}}
    try:
        d = json.load(io.open(paths.runtime(LEDGER), encoding='utf-8'))
        if d.get('date') != blank['date']:
            return blank                      # 昨天的账，今天重新算
        for k in ('calls', 'prompt', 'completion'):
            d[k] = int(d.get(k) or 0)
        d.setdefault('models', {})
        return d
    except Exception:
        return blank                          # 没有 / 坏了 / 正在写 → 当作今天还没花过


def _save(d):
    """原子写：先写临时文件再替换，避免别人读到写了一半的账。"""
    p = paths.runtime(LEDGER)
    tmp = p + '.tmp'
    try:
        with io.open(tmp, 'w', encoding='utf-8', newline='') as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, p)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass                              # 记账失败不许影响主线


def today():
    """今天花了多少 + 限额是多少。给体检和控制面板看。"""
    d = _load()
    lim = _limits()
    d['limit_calls'] = lim['calls']
    d['limit_tokens'] = lim['tokens']
    return d


def check(what='调用大模型'):
    """还有额度吗。超了抛 `BudgetExceeded`，没设限额时永远放行。

    `what` 会原样出现在给用户的话里，写人话（「精读一篇」而不是「chat()」）。
    """
    lim = _limits()
    if not lim['calls'] and not lim['tokens']:
        return                                # 没设限额 = 只记账不拦
    d = _load()
    if lim['calls'] and d['calls'] >= lim['calls']:
        raise BudgetExceeded(
            f'今天的调用次数用完了（{d["calls"]}/{lim["calls"]} 次），'
            f'所以没有执行「{what}」。要继续就去控制面板把 DAILY_LLM_CALLS 调大，'
            f'或者等明天自动清零。')
    if lim['tokens'] and d['completion'] >= lim['tokens']:
        raise BudgetExceeded(
            f'今天的产出额度用完了（{d["completion"]}/{lim["tokens"]} token），'
            f'所以没有执行「{what}」。要继续就去控制面板把 DAILY_LLM_TOKENS 调大，'
            f'或者等明天自动清零。')


def record(prompt=0, completion=0, model=''):
    """记一笔。**任何异常都吞掉** —— 记账是辅助，不能因为它把主线弄挂。"""
    try:
        d = _load()
        d['calls'] += 1
        d['prompt'] += int(prompt or 0)
        d['completion'] += int(completion or 0)
        if model:
            m = d['models'].setdefault(model, {'calls': 0, 'completion': 0})
            m['calls'] += 1
            m['completion'] += int(completion or 0)
        _save(d)
    except Exception:
        pass
