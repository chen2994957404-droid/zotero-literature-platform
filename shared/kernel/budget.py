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
3. **账本坏了：没设限额时不挡；设了限额时宁可先停。**（2026-09-30 改，原来是「一律吞掉放行」）
   原来的做法有个致命的副作用：账本一瞬间读不出来（另一个进程正在写）就当「今天还没花过」，
   接着 `record()` 拿这本空账**覆盖掉当天的真账** —— 限额这道唯一的硬闸就归零了。
   现在：没有账本 = 空账；读不出来先重试，还不行 → `record()` 不写、记一条错误日志；
   `check()` 在设了限额时报「账本读不了，先停」并告诉人怎么恢复（删掉那个文件）。
   没设限额时 `check()` 不读账本，照旧永远放行。

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
| `DAILY_LLM_YUAN` | 一天最多花多少元（按 `PRICE_YUAN_PER_M` 折算，宁高勿低） | 0＝不限 |

## 按元折算（2026-09-22 加，用户要「两块钱限额」）

次数和 token 都不是用户心里的那把尺子，他看的是余额掉了几块钱。
单价表 `PRICE_YUAN_PER_M` 是**外部事实**，会变：来源与查证日期写在表旁边，
用的是**高峰价、缓存未命中价**（官方非高峰半价、缓存命中更便宜）——
算高不算低，宁可早拦。表里没有的付费模型按表里最贵的算。
Jev（typesafe 通道）按美元计、有自己的月度额度，不从 DeepSeek 余额里扣，折算时记 0。
"""
import io
import json
import os
import time

from shared.kernel import paths
from shared.kernel.errors import PlatformError

LEDGER = 'llm_budget.json'

# 每百万 token 的（输入, 输出）元价。**高峰价 + 缓存未命中价**，宁高勿低。
# 来源：https://api-docs.deepseek.com/zh-cn/quick_start/pricing ，2026-09-22 查证。
# 按模型名前缀匹配，先长后短；没列的付费模型按最贵一行算。
PRICE_YUAN_PER_M = (
    ('deepseek-v4-pro', 9.0, 27.0),
    ('deepseek-v4-flash', 2.0, 8.0),       # 旧名，官方转发到 deepseek-flash
    ('deepseek-flash', 2.0, 8.0),
)
FREE_CHANNELS = ('typesafe',)              # 另有月度额度、不扣 DeepSeek 余额          # 落在 logs/ 下，跟心跳、锁同处，便于一并清理


class BudgetExceeded(PlatformError):
    """今天的额度用完了。**这不是故障，是刹车。**"""


def _today():
    return time.strftime('%Y-%m-%d')


def _limits():
    """从配置读限额。读不到或读到垃圾一律当 0（不限）—— 配置错不该变成拦路虎。"""
    from shared.kernel.config import get_key
    out = {}
    for name, key in (('calls', 'DAILY_LLM_CALLS'), ('tokens', 'DAILY_LLM_TOKENS'),
                      ('yuan', 'DAILY_LLM_YUAN')):
        try:
            v = max(0.0, float(str(get_key(key, default='') or '0').strip() or 0))
            out[name] = v if name == 'yuan' else int(v)
        except (TypeError, ValueError):
            out[name] = 0
    return out


def cost_yuan(model, prompt=0, completion=0, channel=''):
    """这次调用折成多少元。宁高勿低：没列的模型按最贵一行算。"""
    if channel in FREE_CHANNELS:
        return 0.0
    name = (model or '').lower()
    row = next((r for r in PRICE_YUAN_PER_M if name.startswith(r[0])), None)
    if row is None:
        row = max(PRICE_YUAN_PER_M, key=lambda r: r[2])
    return (int(prompt or 0) * row[1] + int(completion or 0) * row[2]) / 1e6


def _log():
    from shared.kernel.log import get_logger
    return get_logger('budget')


class LedgerUnreadable(Exception):
    """账本在、却读不出来（坏了，或一直被别人占着）。"""


def _load():
    """读今天的账。**换了一天就自动从零开始**，不必有人来清。

    ⚠ **「没有账本」和「账本读不出来」必须分开**（2026-09-30 排查「出错不报错」）：
    原来两者都当「今天还没花过」—— 于是另一个进程正在写的那一瞬读失败，
    `record()` 就拿一本空账把当天的真账**覆盖掉**，花钱上限这道唯一的硬闸当场归零。
    现在：没有 → 空账；读不出来 → 重试几次（多半是别人正在写）→ 还不行就抛 `LedgerUnreadable`。
    """
    blank = {'date': _today(), 'calls': 0, 'prompt': 0, 'completion': 0, 'yuan': 0.0,
             'models': {}, 'by_purpose': {}}
    p = paths.runtime(LEDGER)
    last = None
    for attempt in range(5):
        if not os.path.exists(p):
            return blank
        try:
            # 必须 with 关掉：读失败时异常会攥着这个句柄，Windows 上紧接着的 _save 就替换不了文件
            with io.open(p, encoding='utf-8') as f:
                d = json.load(f)
            if d.get('date') != blank['date']:
                return blank                  # 昨天的账，今天重新算
            for k in ('calls', 'prompt', 'completion'):
                d[k] = int(d.get(k) or 0)
            d.setdefault('models', {})
            d.setdefault('by_purpose', {})
            return d
        except Exception as e:
            last = '%s: %s' % (type(e).__name__, e)     # 只留文字，别攥着异常（它引用着栈帧和文件）
            time.sleep(0.2 * (attempt + 1))
    raise LedgerUnreadable(f'{p}：{last}')


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
    d['limit_yuan'] = lim.get('yuan', 0)
    d.setdefault('yuan', 0.0)
    return d


def check(what='调用大模型'):
    """还有额度吗。超了抛 `BudgetExceeded`，没设限额时永远放行。

    `what` 会原样出现在给用户的话里，写人话（「精读一篇」而不是「chat()」）。
    """
    lim = _limits()
    if not lim['calls'] and not lim['tokens'] and not lim.get('yuan'):
        return                                # 没设限额 = 只记账不拦
    try:
        d = _load()
    except LedgerUnreadable as e:
        # 设了限额却不知道今天花了多少 → **宁可先停**，不能当成没花过接着花
        raise BudgetExceeded(
            f'今天的花钱账本读不出来（{e}），为防超支先没有执行「{what}」。'
            f'把那个文件删掉即可恢复（今天的计数会从零开始）。')
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
    if lim.get('yuan') and d.get('yuan', 0.0) >= lim['yuan']:
        raise BudgetExceeded(
            f'今天的花费到上限了（约 {d.get("yuan", 0.0):.2f}/{lim["yuan"]:g} 元，按高峰价估，实际只会更少），'
            f'所以没有执行「{what}」。要继续就去控制面板把 DAILY_LLM_YUAN 调大，'
            f'或者等明天自动清零。')


def record(prompt=0, completion=0, model='', purpose='', channel=''):
    """记一笔。**任何异常都吞掉** —— 记账是辅助，不能因为它把主线弄挂。

    2026-09-11 起按**用途 × 通道 × 模型**记（用户要的第三部分：
    「日志记录哪些部分调用了哪些 API」）。`by_purpose` 的形状：
        {'DEEPREAD': {'deepseek-官方/deepseek-flash': {'calls': 3, 'completion': 29107}}}
    没传用途的（老路径）记在 '(未标用途)' 下 —— 让「还有谁没接进路由」一眼可见。
    """
    try:
        d = _load()
        d['calls'] += 1
        d['prompt'] += int(prompt or 0)
        d['completion'] += int(completion or 0)
        d['yuan'] = round(d.get('yuan', 0.0) + cost_yuan(model, prompt, completion, channel), 6)
        if model:
            m = d['models'].setdefault(model, {'calls': 0, 'completion': 0})
            m['calls'] += 1
            m['completion'] += int(completion or 0)
        pu = d.setdefault('by_purpose', {}).setdefault(purpose or '(未标用途)', {})
        row = pu.setdefault(f'{channel or "?"}/{model or "?"}', {'calls': 0, 'completion': 0})
        row['calls'] += 1
        row['completion'] += int(completion or 0)
        _save(d)
    except LedgerUnreadable as e:
        # 读不出来就**别写** —— 写就是拿空账覆盖真账。记不上这一笔要说出来，不许静默
        _log().error(f'花钱账本读不出来，这一笔没记上（{e}）')
    except Exception as e:
        _log().error(f'记账失败，这一笔没记上：{type(e).__name__}: {e}')
