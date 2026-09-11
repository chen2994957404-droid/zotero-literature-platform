# -*- coding: utf-8 -*-
"""大模型「通道 / 用途 / 备用」三段式的守卫（2026-09-11）。

测四件事，全部离线（不联网、不读用户的真实路由文件）：
  ① 路由表：明确指定的 > 老配置 + 前缀猜（且标 inferred）；同名通道用户的覆盖内置的
  ② 解析：主用在前、备用在后；指定了 model 时走该用途的通道但用指定模型
  ③ 切换：主用报「换条路可能有救」的错才切备用；请求本身的错不切
  ④ 账本：按 用途 × 通道 × 模型 记
"""
import json
import io

import pytest

from shared.kernel.config import routing
from shared.adapters import llm_client as L


@pytest.fixture(autouse=True)
def 隔离的路由文件(tmp_path, monkeypatch):
    f = tmp_path / 'llm_routing.json'
    monkeypatch.setattr(routing, 'ROUTING_FILE', str(f))
    # 老配置项都用内置默认，不受本机 .env 影响
    from shared.kernel import config
    monkeypatch.setattr(config, 'get_model',
                        lambda n: config.MODEL_SETTINGS[n][1])
    monkeypatch.setattr(config, 'get_site', lambda n: '')
    return f


# ── ① 路由表 ─────────────────────────────────────────────────────────
def test_没配路由时按前缀猜通道并标记inferred():
    p = routing.purposes()
    assert p['DEEPREAD']['channel'] == 'deepseek-官方'
    assert p['DEEPREAD']['inferred'] is True
    assert p['DIRECTION_QUAD']['channel'] == 'aliyun-百炼'   # qwen 开头


def test_明确指定的通道优先于猜(隔离的路由文件):
    routing.save(channels={'阿里云-中转': {'base': 'https://relay.example/v1',
                                          'key': 'RELAY_KEY'}},
                 purposes={'DEEPREAD': {'channel': '阿里云-中转',
                                         'model': 'deepseek-v4-flash'}})
    p = routing.purposes()['DEEPREAD']
    assert p['channel'] == '阿里云-中转' and p['inferred'] is False
    assert p['model'] == 'deepseek-v4-flash'


def test_同名通道用户的覆盖内置的(隔离的路由文件):
    """想把官方地址换成中转，改一条就行 —— 不用改用途表。"""
    routing.save(channels={'deepseek-官方': {'base': 'https://my-relay/v1',
                                             'key': 'DEEPSEEK_KEY'}})
    ch = routing.channels()['deepseek-官方']
    assert ch['base'] == 'https://my-relay/v1'
    assert ch['builtin'] is True, '覆盖了内置的仍标 builtin，面板才知道能「恢复默认」'


def test_密钥名以KEY或TOKEN结尾就算密钥():
    """用户给中转站起的密钥名不在固定表里，靠后缀规则认。"""
    from shared.kernel.config import is_secret
    assert is_secret('ALIYUN_RELAY_KEY') and is_secret('X_TOKEN')
    assert not is_secret('DEEPREAD_MODEL') and not is_secret('ROLE')


# ── ② 解析 ───────────────────────────────────────────────────────────
def test_解析顺序_主用在前备用在后(隔离的路由文件):
    routing.save(purposes={'ASK': {'channel': 'gemini-官方', 'model': 'gemini-3.8-flash',
                                   'fallback': 'deepseek-官方',
                                   'fallback_model': 'deepseek-flash'}})
    order = routing.resolve('ASK')
    assert [(n, m) for n, _, m in order] == [('gemini-官方', 'gemini-3.8-flash'),
                                             ('deepseek-官方', 'deepseek-flash')]


def test_指定了model就走该用途的通道但用指定模型(隔离的路由文件):
    routing.save(purposes={'DEEPREAD': {'channel': 'deepseek-官方', 'model': 'deepseek-flash',
                                        'fallback': 'gemini-官方'}})
    att = L._attempts('DEEPREAD', None, 'deepseek-v4-pro', None)
    assert att[0][2] == 'deepseek-v4-pro', '「用 pro 重跑」要能覆盖路由表里的模型'
    assert att[1][2] == 'deepseek-v4-pro', '备用没自己配模型时跟主用一样'


def test_未知用途要报清楚():
    with pytest.raises(KeyError):
        routing.resolve('不存在的用途')


def test_体检能指出没明确指定通道的用途():
    probs = routing.problems()
    assert any('没明确指定通道' in msg for _lvl, msg in probs)


# ── ③ 切换 ───────────────────────────────────────────────────────────
def _attempts_two():
    return [('主用', {'kind': 'openai', 'base': 'https://a/v1', 'key': ''}, 'm1'),
            ('备用', {'kind': 'openai', 'base': 'https://b/v1', 'key': ''}, 'm2')]


def test_主用报可切换的错就切到备用():
    seen = []
    def call(name, ch, model):
        seen.append(name)
        if name == '主用':
            raise L.LLMError('HTTP 402: Insufficient Balance', failover=True)
        return 'ok from ' + name
    assert L._run('ASK', _attempts_two(), call) == 'ok from 备用'
    assert seen == ['主用', '备用']


def test_请求本身的错不切备用():
    """400 / 截断 / 解析失败换了通道也一样 —— 切换只会把配置错误藏起来。"""
    seen = []
    def call(name, ch, model):
        seen.append(name)
        raise L.LLMError('HTTP 400: bad request', failover=False)
    with pytest.raises(L.LLMError):
        L._run('ASK', _attempts_two(), call)
    assert seen == ['主用'], '不该去碰备用'


def test_连不上也切备用():
    import urllib.error
    def call(name, ch, model):
        if name == '主用':
            raise urllib.error.URLError('connection refused')
        return 'ok'
    assert L._run('ASK', _attempts_two(), call) == 'ok'


def test_全都失败时把每条路的错都报出来():
    def call(name, ch, model):
        raise L.LLMError(f'{name} 挂了', failover=True)
    with pytest.raises(L.LLMError) as e:
        L._run('ASK', _attempts_two(), call)
    assert '主用' in str(e.value) or '备用' in str(e.value)


def test_401_402_403标为可切换_400不标():
    """闸门在 _cloud_chat 里：哪些 HTTP 码算「换条路可能有救」。"""
    import urllib.error, io as _io
    def fake_urlopen(code):
        def _open(req, timeout=0):
            raise urllib.error.HTTPError(req.full_url, code, 'x', {}, _io.BytesIO(b'{}'))
        return _open
    for code, want in ((402, True), (401, True), (403, True), (400, False), (404, False)):
        import urllib.request
        old = urllib.request.urlopen
        urllib.request.urlopen = fake_urlopen(code)
        try:
            with pytest.raises(L.LLMError) as e:
                L._cloud_chat([{'role': 'user', 'content': 'hi'}], 'm', 'k', 0.1, False,
                              None, endpoint='https://x/v1/chat/completions')
            assert e.value.failover is want, f'HTTP {code} 的 failover 应为 {want}'
        finally:
            urllib.request.urlopen = old


# ── ④ 账本 ───────────────────────────────────────────────────────────
def test_账本按用途通道模型记(tmp_path, monkeypatch):
    from shared.kernel import budget
    ledger = tmp_path / 'b.json'
    monkeypatch.setattr(budget.paths, 'runtime', lambda n: str(ledger))
    budget.record(completion=100, model='deepseek-flash', purpose='DEEPREAD', channel='阿里云-中转')
    budget.record(completion=50, model='deepseek-flash', purpose='DEEPREAD', channel='阿里云-中转')
    budget.record(completion=7, model='gemini-3.8-flash', purpose='ASK', channel='gemini-官方')
    budget.record(completion=1, model='x')          # 老路径，没标用途
    bp = budget.today()['by_purpose']
    assert bp['DEEPREAD']['阿里云-中转/deepseek-flash'] == {'calls': 2, 'completion': 150}
    assert bp['ASK']['gemini-官方/gemini-3.8-flash'] == {'calls': 1, 'completion': 7}
    assert '(未标用途)' in bp, '没接进路由的调用要一眼可见'


# ── 向量化的特殊约束 ──────────────────────────────────────────────────
def test_向量化在路由表里_默认本地bge(隔离的路由文件):
    p = routing.purposes()['EMBED']
    assert p['channel'] == 'ollama-本地' and p['model'] == 'bge-m3'
    assert p['no_fallback'] is True


def test_向量化即使配了备用也只解析出主用(隔离的路由文件):
    """换嵌入模型 = 整个向量库作废。所以备用**不生效**，且体检直接红。"""
    routing.save(purposes={'EMBED': {'channel': 'ollama-本地', 'model': 'bge-m3',
                                     'fallback': 'aliyun-百炼'}})
    assert [n for n, _, _ in routing.resolve('EMBED')] == ['ollama-本地']
    assert any(lvl == 'fail' and '向量库' in m for lvl, m in routing.problems())


# ── Ollama 的「关思考」必须在顶层（踩坑 #155）───────────────────────────
def test_ollama请求里think在顶层不在options里(monkeypatch):
    """options.think 是无效字段，Ollama 静默忽略 → 模型偷偷推理几千字再答。
    主力机实测：同一条打标签请求，放 options 里 53 秒，放顶层 2.8 秒。"""
    import urllib.request, io as _io
    seen = {}
    class _R:
        def read(self): return b'{"message": {"content": "{}"}, "eval_count": 1}'
    def fake(req, timeout=0):
        seen['body'] = json.loads(req.data.decode('utf-8')); return _R()
    monkeypatch.setattr(urllib.request, 'urlopen', fake)
    L._ollama([{'role': 'user', 'content': 'hi'}], 'qwen3.5:latest', 0.1, True, 4096,
              host='http://localhost:11434')
    assert seen['body'].get('think') is False, 'think 必须是顶层参数'
    assert 'think' not in seen['body'].get('options', {}), '放 options 里等于没关'
