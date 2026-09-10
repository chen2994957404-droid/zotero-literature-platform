# -*- coding: utf-8 -*-
"""当日额度闸的守卫。

这块存在的理由见 `shared/kernel/budget.py` 的文档字符串：MCP 的 `confirm` 是
Claude Code 专有标记，换个客户端会被忽略，所以花钱的闸必须在服务端。

测的是四条承诺：
  ① 没设限额时**永远放行**（默认只记账不拦，不能把生产流水线打断）
  ② 设了限额且超了 → 抛 BudgetExceeded，且话是给人看的
  ③ 换一天自动清零，不需要有人来扫
  ④ 账本坏了/没有 → 当作今天还没花过，**不能因此挡住干活**
"""
import io
import json
import os

import pytest

from shared.kernel import budget


@pytest.fixture(autouse=True)
def 干净的账本(tmp_path, monkeypatch):
    """每条用例一份独立账本 + 默认不限额，互不干扰。"""
    ledger = tmp_path / 'llm_budget.json'
    monkeypatch.setattr(budget.paths, 'runtime', lambda name: str(ledger))
    monkeypatch.setattr(budget, '_limits', lambda: {'calls': 0, 'tokens': 0})
    return ledger


def _限额(monkeypatch, calls=0, tokens=0):
    monkeypatch.setattr(budget, '_limits', lambda: {'calls': calls, 'tokens': tokens})


def test_没设限额时永远放行():
    """默认必须是「只记账、不拦」—— 往生产流水线里塞硬中断比超支更糟。"""
    for _ in range(50):
        budget.record(prompt=1000, completion=100000, model='m')
    budget.check('精读一篇')          # 花了 500 万 token 也不该拦
    assert budget.today()['calls'] == 50


def test_超了调用次数就拦下(monkeypatch):
    _限额(monkeypatch, calls=3)
    for _ in range(3):
        budget.check('精读一篇')       # 前三次都该放行
        budget.record(completion=10, model='m')
    with pytest.raises(budget.BudgetExceeded) as e:
        budget.check('精读一篇')
    msg = str(e.value)
    assert '精读一篇' in msg, '报错里要带上「在做什么」，否则用户不知道被拦的是啥'
    assert 'DAILY_LLM_CALLS' in msg, '要告诉用户去哪调大，不能只说不行'


def test_超了产出token就拦下(monkeypatch):
    _限额(monkeypatch, tokens=1000)
    budget.record(completion=999, model='m')
    budget.check('精读一篇')           # 还差 1 个，放行
    budget.record(completion=1, model='m')
    with pytest.raises(budget.BudgetExceeded):
        budget.check('精读一篇')


def test_换一天自动清零(干净的账本, monkeypatch):
    _限额(monkeypatch, calls=1)
    budget.record(completion=10, model='m')
    with pytest.raises(budget.BudgetExceeded):
        budget.check('精读一篇')
    # 把账本改成昨天的
    d = json.load(io.open(str(干净的账本), encoding='utf-8'))
    d['date'] = '1999-01-01'
    io.open(str(干净的账本), 'w', encoding='utf-8', newline='').write(
        json.dumps(d, ensure_ascii=False))
    budget.check('精读一篇')           # 新的一天，重新开始
    assert budget.today()['calls'] == 0


def test_账本坏了也不许挡住干活(干净的账本, monkeypatch):
    """记账是辅助，不是主线。坏账本必须当作「今天还没花过」。"""
    io.open(str(干净的账本), 'w', encoding='utf-8').write('这不是 JSON{{{')
    _限额(monkeypatch, calls=5)
    budget.check('精读一篇')           # 不许抛
    budget.record(completion=1, model='m')   # 也不许抛
    assert budget.today()['calls'] == 1


def test_记账失败不许把主线弄挂(monkeypatch):
    """磁盘满了、目录没权限……record 都得默默咽下去。"""
    def 炸(*a, **kw):
        raise OSError('磁盘满了')
    monkeypatch.setattr(budget, '_save', 炸)
    budget.record(completion=1, model='m')   # 不许抛


def test_限额配错了当成不限(monkeypatch):
    """配置里填了「很多」「-1」这种，不该变成拦路虎。"""
    monkeypatch.setattr(budget, '_limits', budget._limits)   # 用真实实现
    from shared.kernel import config
    monkeypatch.setattr(config, 'get_key',
                        lambda name, default='', **kw: '不是数字' if 'DAILY' in name else default)
    assert budget._limits() == {'calls': 0, 'tokens': 0}


def test_分模型记账(monkeypatch):
    """要能看出钱花在哪个模型上，否则优化无从下手。"""
    budget.record(completion=100, model='deepseek-v4-flash')
    budget.record(completion=50, model='deepseek-v4-pro')
    budget.record(completion=30, model='deepseek-v4-flash')
    m = budget.today()['models']
    assert m['deepseek-v4-flash'] == {'calls': 2, 'completion': 130}
    assert m['deepseek-v4-pro'] == {'calls': 1, 'completion': 50}
