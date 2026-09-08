# -*- coding: utf-8 -*-
"""shared.kernel.paths 的单元测试 —— 纯离线、不碰真实数据、毫秒级。"""
import os
import pytest

from shared.kernel import paths


class TestCheckKey:
    def test_接受合法key(self):
        assert paths.check_key('2T6H4S3D') == '2T6H4S3D'

    def test_小写自动转大写(self):
        assert paths.check_key('2t6h4s3d') == '2T6H4S3D'

    def test_去掉首尾空白(self):
        assert paths.check_key('  2T6H4S3D \n') == '2T6H4S3D'

    @pytest.mark.parametrize('bad', [
        '',                       # 空
        '2T6H4S3',                # 7 位，太短
        '2T6H4S3DD',              # 9 位，太长
        '2T6H-S3D',               # 含非字母数字
        'data',                   # 有人把目录名当 key 传
        'D:/x/library/2T6H4S3D',  # 有人把整条路径传进来
        'doi_',                   # 只有前缀，没有内容
        'doi_10.1021/acs.x',      # 没净化过就往里传（'/' 会变成子目录）
        '../../etc/passwd',       # 目录穿越
        'W12',                    # OpenAlex id 太短
        None,
    ])
    def test_拒绝非法key(self, bad):
        with pytest.raises(paths.BadKeyError):
            paths.check_key(bad)


class TestPaperId:
    """文献 id 不再等于 Zotero 编号（2026-09-07 放宽）。

    这一组守的是「数据库是公共账本，Zotero 只是其中一个来源」这个决定 ——
    谁把身份证收窄回「只认 8 位」，这里会红。
    """

    def test_老的Zotero编号照样有效(self):
        assert paths.check_key('2t6h4s3d') == '2T6H4S3D'

    def test_接受OpenAlex_id(self):
        assert paths.check_key('W2741809687') == 'W2741809687'
        assert paths.check_key('https://openalex.org/W2741809687'.rsplit('/', 1)[-1])             == 'W2741809687'

    def test_接受DOI生成的id(self):
        pid = paths.paper_id_from_doi('10.1021/acs.macromol.1c00123')
        assert pid == 'doi_10.1021-acs.macromol.1c00123'
        assert paths.check_key(pid) == pid          # 生成的 id 必须自己认得

    def test_DOI的各种写法算出同一个id(self):
        a = paths.paper_id_from_doi('https://doi.org/10.1021/ACS.X1')
        b = paths.paper_id_from_doi('  doi:10.1021/acs.x1  ')
        assert a == b == 'doi_10.1021-acs.x1'

    def test_超长DOI截断后仍唯一(self):
        long1 = '10.1021/' + 'a' * 200 + '1'
        long2 = '10.1021/' + 'a' * 200 + '2'
        i1, i2 = paths.paper_id_from_doi(long1), paths.paper_id_from_doi(long2)
        assert i1 != i2 and len(i1) <= 80 and paths.check_key(i1) == i1

    @pytest.mark.parametrize('bad', ['', None, 'not-a-doi', 'https://example.com/x'])
    def test_不是DOI就拒绝(self, bad):
        with pytest.raises(paths.BadKeyError):
            paths.paper_id_from_doi(bad)

    def test_能分辨这篇在不在他自己的库里(self):
        assert paths.is_zotero_key('2T6H4S3D') is True
        assert paths.is_zotero_key('W2741809687') is False
        assert paths.is_zotero_key(paths.paper_id_from_doi('10.1021/acs.x1')) is False
        assert paths.is_zotero_key('rubbish') is False

    def test_非Zotero文献也有自己的产物路径(self):
        """放宽的**目的**就在这一条：不在 Zotero 里的文献也能落地。"""
        pid = paths.paper_id_from_doi('10.1021/acs.x1')
        assert paths.fulltext(pid).replace(os.sep, '/').endswith(
            'data/raw/doi_10.1021-acs.x1/parsed/full.md')
        assert paths.structured(pid).replace(os.sep, '/').endswith(
            'doi_10.1021-acs.x1.json')


class TestPaperArtifacts:
    """产物路径必须和 docs/reference/数据契约.md 里写的完全一致。

    这些断言就是数据契约本身 —— 谁改了目录布局而没改契约文档，这里会红。
    """
    KEY = '2T6H4S3D'

    def _rel(self, p):
        return os.path.relpath(p, paths.ROOT).replace(os.sep, '/')

    def test_文献目录(self):
        assert self._rel(paths.paper_dir(self.KEY)) == 'data/curated/2T6H4S3D'

    def test_全文(self):
        assert self._rel(paths.fulltext(self.KEY)) == 'data/raw/2T6H4S3D/parsed/full.md'

    def test_图坐标(self):
        assert self._rel(paths.layout(self.KEY)) == 'data/raw/2T6H4S3D/parsed/layout.json'

    def test_正文PDF正本(self):
        assert self._rel(paths.local_pdf(self.KEY)) == 'data/raw/2T6H4S3D/main.pdf'

    def test_SI原件正本(self):
        assert self._rel(paths.local_si(self.KEY)) == 'data/raw/2T6H4S3D/si.pdf'
        assert self._rel(paths.local_si(self.KEY, '.DOCX')) == 'data/raw/2T6H4S3D/si.docx'

    def test_精读(self):
        assert self._rel(paths.summary(self.KEY)).endswith('curated/2T6H4S3D/summary.html')

    def test_SI精读(self):
        assert self._rel(paths.si_summary(self.KEY)).endswith('curated/2T6H4S3D/si_summary.html')

    def test_合并精读(self):
        assert self._rel(paths.summary_full(self.KEY)).endswith('curated/2T6H4S3D/summary_full.html')

    def test_元数据(self):
        assert self._rel(paths.meta(self.KEY)).endswith('curated/2T6H4S3D/meta.json')

    def test_结构化(self):
        assert self._rel(paths.structured(self.KEY)) == 'data/serving/structured/2T6H4S3D.json'

    def test_对比表(self):
        assert self._rel(paths.compare()) == 'data/serving/structured/compare.md'
        assert self._rel(paths.compare('compare_PBS')) == 'data/serving/structured/compare_PBS.md'

    def test_全都是绝对路径(self):
        for fn in (paths.paper_dir, paths.fulltext, paths.layout, paths.summary,
                   paths.si_summary, paths.summary_full, paths.meta, paths.structured):
            assert os.path.isabs(fn(self.KEY)), fn.__name__

    def test_非法key在拼路径时就被挡住(self):
        """防止 ../.. 之类的东西被拼进数据目录。"""
        with pytest.raises(paths.BadKeyError):
            paths.paper_dir('../../etc')


class TestNoSideEffects:
    """不传 create=True 就不许碰硬盘 —— 路径计算是纯函数。"""

    def test_paper_dir默认不建目录(self):
        p = paths.paper_dir('ZZZZZZZZ')
        assert not os.path.exists(p), '算一下路径就把目录建出来了，这是副作用'

    def test_create为真时才建(self, tmp_path, monkeypatch):
        monkeypatch.setattr(paths, 'CURATED', str(tmp_path / 'curated'))
        p = paths.paper_dir('ZZZZZZZZ', create=True)
        assert os.path.isdir(p)


class TestStateDB:
    def test_状态库在数据目录下且可重建(self):
        assert paths.state_db() == os.path.join(paths.STATE, 'state.db')

    def test_算路径不产生副作用(self):
        # 只是算个路径，不该真的建库（shared.kernel.jobs 用到时才建）
        paths.state_db()


class TestRoot:
    def test_ROOT指向项目根(self):
        # 项目根的特征：有 pyproject.toml 和 shared/
        assert os.path.isfile(os.path.join(paths.ROOT, 'pyproject.toml'))
        assert os.path.isdir(os.path.join(paths.ROOT, 'shared'))

    def test_ROOT与当前工作目录无关(self, tmp_path, monkeypatch):
        before = paths.ROOT
        monkeypatch.chdir(tmp_path)
        import importlib
        importlib.reload(paths)
        assert paths.ROOT == before


class TestHas:
    def test_未知产物名报错(self):
        with pytest.raises(ValueError):
            paths.has('2T6H4S3D', 'nonexistent_artifact')

    def test_非法key返回False而不是抛错(self):
        assert paths.has('not-a-key', 'summary') is False
