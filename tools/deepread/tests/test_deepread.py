# -*- coding: utf-8 -*-
"""精读编排的离线测试 —— 全程不联网、不花钱、不碰真实数据。

测的是**编排**（谁在什么条件下被调、失败了怎么办），不是各步骤内部实现。
把 MineRU / LLM 换成假货之后，这条流水线的状态机就能被秒级验证 ——
这正是阶段 3 把它从 subprocess 链搬进函数的直接收益。
"""
import os
import time

import pytest

from shared.kernel import jobs, paths
from tools import deepread
from tools.deepread import main_text, merge as merge_mod

KEY = 'ABCD1234'


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """把数据目录和状态库都指到临时目录。"""
    monkeypatch.setattr(paths, 'LIBRARY', str(tmp_path / 'library'))
    monkeypatch.setattr(paths, 'STRUCTURED', str(tmp_path / 'structured'))
    monkeypatch.setattr(jobs, 'db_path', lambda: str(tmp_path / 'state.db'))
    jobs.close()
    paths.paper_dir(KEY, create=True)
    yield tmp_path
    jobs.close()


def _fake_steps(monkeypatch, main=True, si=True, parse=True):
    """把三个花钱的步骤换成写占位文件的假货。"""
    calls = {'parse': 0, 'main': 0, 'si': 0}

    def fake_parse(key, pdf_path, force=False, log=print):
        calls['parse'] += 1
        if not parse:
            raise RuntimeError('MineRU 挂了')
        d = paths.parsed_dir(key, create=True)
        open(paths.layout(key), 'w', encoding='utf-8').write('{}')
        return d

    def fake_main(parsed_dir, out_html, **kw):
        calls['main'] += 1
        if not main:
            raise main_text.DeepreadFailed('LLM 只吐了 12 个字')
        open(out_html, 'w', encoding='utf-8').write('<html><body><p>正文</p></body></html>')
        return out_html

    def fake_si(key, out_html=None, model=None, log=print):
        calls['si'] += 1
        if si is None:
            return None                    # 这篇根本没有 SI 附件
        if not si:
            raise RuntimeError('SI 解析失败')
        p = out_html or paths.si_summary(key)
        open(p, 'w', encoding='utf-8').write('<html><body><p>SI</p></body></html>')
        return p

    monkeypatch.setattr(deepread, '_ensure_parsed', fake_parse)
    monkeypatch.setattr(main_text, 'read_main', fake_main)
    monkeypatch.setattr(deepread._si, 'read_si', fake_si)
    return calls


def test_正文加SI跑通并合并(sandbox, monkeypatch):
    calls = _fake_steps(monkeypatch)
    r = deepread.run(KEY, pdf_path='x.pdf', si_exists=True, log=lambda *a: None)
    assert r.state == 'full'
    assert r.final_html == paths.summary_full(KEY)
    assert os.path.exists(paths.summary_full(KEY))
    assert calls == {'parse': 1, 'main': 1, 'si': 1}
    # 每一步都记了账，产物知道自己是谁产的
    assert jobs.last(KEY, deepread.STEP_MAIN)['status'] == jobs.OK
    assert jobs.last(KEY, deepread.STEP_MAIN)['producer'] == main_text.PRODUCER


def test_只有正文时不合并(sandbox, monkeypatch):
    _fake_steps(monkeypatch)
    r = deepread.run(KEY, pdf_path='x.pdf', si_exists=False, log=lambda *a: None)
    assert r.state == 'main'
    assert r.final_html == paths.summary(KEY)
    assert not os.path.exists(paths.summary_full(KEY))


def test_没有任何附件就是nopdf(sandbox, monkeypatch):
    calls = _fake_steps(monkeypatch)
    r = deepread.run(KEY, pdf_path=None, si_exists=False, log=lambda *a: None)
    assert r.state == 'nopdf'
    assert calls['main'] == 0 and calls['parse'] == 0   # 一分钱都不花


def test_做过的不重跑_这是省钱的关键(sandbox, monkeypatch):
    calls = _fake_steps(monkeypatch)
    deepread.run(KEY, pdf_path='x.pdf', si_exists=True, log=lambda *a: None)
    deepread.run(KEY, pdf_path='x.pdf', si_exists=True, log=lambda *a: None)
    assert calls == {'parse': 1, 'main': 1, 'si': 1}    # 第二遍一步都没重跑


def test_force能强制重跑(sandbox, monkeypatch):
    calls = _fake_steps(monkeypatch)
    deepread.run(KEY, pdf_path='x.pdf', si_exists=True, log=lambda *a: None)
    deepread.run(KEY, pdf_path='x.pdf', si_exists=True, force=True, log=lambda *a: None)
    assert calls['main'] == 2


def test_产物被删掉时会自动补做(sandbox, monkeypatch):
    """状态库说做完了，但 summary.html 没了 —— 真相在硬盘上，得重做。"""
    calls = _fake_steps(monkeypatch)
    deepread.run(KEY, pdf_path='x.pdf', si_exists=False, log=lambda *a: None)
    os.remove(paths.summary(KEY))
    deepread.run(KEY, pdf_path='x.pdf', si_exists=False, log=lambda *a: None)
    assert calls['main'] == 2


def test_SI失败不许拖累正文(sandbox, monkeypatch):
    """两件产物本来就各自独立生成（用户 2026-07-25 定的设计）。"""
    _fake_steps(monkeypatch, si=False)
    r = deepread.run(KEY, pdf_path='x.pdf', si_exists=True, log=lambda *a: None)
    assert r.state == 'main'
    assert r.main_done and not r.si_done
    assert os.path.exists(paths.summary(KEY))
    assert jobs.last(KEY, deepread.STEP_SI)['status'] == jobs.FAILED


def test_正文精读失败不写盘也不算做完(sandbox, monkeypatch):
    """宁可不产出，也不产出废品 —— 废品会被标成已精读，从此不再重跑。"""
    _fake_steps(monkeypatch, main=False)
    r = deepread.run(KEY, pdf_path='x.pdf', si_exists=False, log=lambda *a: None)
    assert r.state == 'failed'
    assert not os.path.exists(paths.summary(KEY))
    row = jobs.last(KEY, deepread.STEP_MAIN)
    assert row['status'] == jobs.FAILED and '12 个字' in row['error']


def test_解析失败时不会去调LLM(sandbox, monkeypatch):
    calls = _fake_steps(monkeypatch, parse=False)
    r = deepread.run(KEY, pdf_path='x.pdf', si_exists=False, log=lambda *a: None)
    assert r.state == 'failed'
    assert calls['main'] == 0
    assert 'MineRU' in r.error


def test_提示词升版后旧精读自动进重跑清单(sandbox, monkeypatch):
    calls = _fake_steps(monkeypatch)
    deepread.run(KEY, pdf_path='x.pdf', si_exists=False, log=lambda *a: None)
    monkeypatch.setattr(main_text, 'PROMPT_VER', main_text.PROMPT_VER + 1)
    deepread.run(KEY, pdf_path='x.pdf', si_exists=False, log=lambda *a: None)
    assert calls['main'] == 2      # 不用人肉记得改过什么，版本号自己说了算


def test_写meta给向量化用(sandbox, monkeypatch):
    _fake_steps(monkeypatch)
    item = {'key': KEY, 'data': {'title': '一篇论文', 'DOI': '10.1/x', 'date': '2026'}}
    deepread.run(KEY, item=item, pdf_path='x.pdf', si_exists=False, log=lambda *a: None)
    import json
    meta = json.load(open(paths.meta(KEY), encoding='utf-8'))
    assert meta['title'] == '一篇论文' and meta['DOI'] == '10.1/x'


def test_没拿到item时不许把已有元数据抹空(sandbox, monkeypatch):
    _fake_steps(monkeypatch)
    item = {'key': KEY, 'data': {'title': '一篇论文', 'DOI': '10.1/x'}}
    deepread.run(KEY, item=item, pdf_path='x.pdf', si_exists=False, log=lambda *a: None)
    deepread.run(KEY, pdf_path='x.pdf', si_exists=False, force=True, log=lambda *a: None)
    import json
    assert json.load(open(paths.meta(KEY), encoding='utf-8'))['title'] == '一篇论文'


def test_合并是纯字符串处理_正文在前SI在后():
    m = merge_mod.merge_html(
        '<html><head><style>CSSHERE</style></head><body><p>甲</p></body></html>',
        '<html><body><p>乙</p></body></html>')
    assert 'CSSHERE' in m and m.index('<p>甲</p>') < m.index('<p>乙</p>')


class TestMerge幂等:
    """合并不花钱，但每次要写十几 MB，还连带一次同样大小的 Zotero 回写。"""

    def _both(self, tmp):
        open(paths.summary(KEY), 'w', encoding='utf-8').write(
            '<html><body><p>正文</p></body></html>')
        open(paths.si_summary(KEY), 'w', encoding='utf-8').write(
            '<html><body><p>SI</p></body></html>')

    def test_输入没变就复用已有合并版(self, sandbox):
        self._both(sandbox)
        out = merge_mod.merge(KEY, log=lambda *a: None)
        first = os.path.getmtime(out)
        time.sleep(0.01)
        merge_mod.merge(KEY, log=lambda *a: None)
        assert os.path.getmtime(out) == first, '输入没变却重写了合并版'

    def test_正文更新了就重做(self, sandbox):
        self._both(sandbox)
        out = merge_mod.merge(KEY, log=lambda *a: None)
        first = os.path.getmtime(out)
        time.sleep(0.01)
        os.utime(paths.summary(KEY), (first + 10, first + 10))   # 假装正文刚被重写
        merge_mod.merge(KEY, log=lambda *a: None)
        assert os.path.getmtime(out) > first, '正文变了却没重新合并'

    def test_force能强制重做(self, sandbox):
        self._both(sandbox)
        out = merge_mod.merge(KEY, log=lambda *a: None)
        first = os.path.getmtime(out)
        time.sleep(0.01)
        merge_mod.merge(KEY, log=lambda *a: None, force=True)
        assert os.path.getmtime(out) > first


class Test元数据用权威值:
    """有权威源就别猜 —— 与踩坑 #64 同一类错误。"""

    MD = (chr(35) + ' 解析出来的标题' + chr(10)*2 + 'Zhao et al.'
          + chr(10)*2 + '正文里写着 10.9999/parsed')

    def test_没给就从正文里猜(self):
        title, _authors, doi = main_text.read_metadata(self.MD)
        assert title == '解析出来的标题' and doi == '10.9999/parsed'

    def test_给了就用给的(self):
        title, _a, doi = main_text.read_metadata(
            self.MD, title='Zotero 上的标题', doi='10.1038/nature11409')
        assert title == 'Zotero 上的标题' and doi == '10.1038/nature11409'

    def test_正文里没有DOI时权威值仍然生效(self):
        title, _a, doi = main_text.read_metadata('# 只有标题', doi='10.1038/x')
        assert doi == '10.1038/x'

    def test_编排层会把item里的标题和DOI传下去(self, sandbox, monkeypatch):
        """这条才是真正要防的回归：改对了函数，却忘了在 run() 里传。"""
        seen = {}

        def fake_main(parsed_dir, out_html, **kw):
            seen.update(kw)
            open(out_html, 'w', encoding='utf-8').write('<html><body>x</body></html>')
            return out_html

        monkeypatch.setattr(deepread, '_ensure_parsed',
                            lambda key, pdf, force=False, log=print: paths.parsed_dir(key, create=True))
        monkeypatch.setattr(main_text, 'read_main', fake_main)
        item = {'key': KEY, 'data': {'title': '权威标题', 'DOI': '10.1038/nature11409'}}
        deepread.run(KEY, item=item, pdf_path='x.pdf', si_exists=False, log=lambda *a: None)
        assert seen.get('title') == '权威标题'
        assert seen.get('doi') == '10.1038/nature11409'
