# -*- coding: utf-8 -*-
"""正文的 LaTeX 必须洗掉，否则整段被判成「没有数字」直接不喂给模型（踩坑 #143）。

实测起因：P2Q5TYFR 全文 22168 字符，只有 38% 被喂进模型；
`10^{-10} M`、`-23 mV` 所在的两段被判成「数字太少」丢掉，
于是三个模型在这篇上一起 0 分 —— **不是它们同时变笨，是料没到它们手里。**
"""
from shared.domain.schema import scan
from tools.extract.bench_chunk import split_chunks


class Test洗正文:
    def test_科学计数法要保住指数(self):
        c = scan.clean_body(r'the limit of $10^{-10}\;\mathrm{M}$ in water')
        assert '10^-10' in c, c
        assert '10-10' not in c.replace('10^-10', ''), '塌成 10-10 会被读成区间'

    def test_误差棒不再冒充数值(self):
        c = scan.clean_body(r'strength of $9.8 \pm 0.3$ MPa')
        vals = [n['value'] for n in scan.scan_numbers(c)]
        assert 9.8 in vals and 0.3 not in vals, (c, vals)

    def test_千分位空格要并起来(self):
        c = scan.clean_body(r'$M_{n}$ of >40 000 g/mol')
        assert [n['value'] for n in scan.scan_numbers(c)] == [40000.0], c

    def test_下标照旧塌掉(self):
        assert 'Mn' in scan.clean_body(r'$M_{n}$')
        assert 'Tg' in scan.clean_body(r'$T_{g}$')

    def test_换行与表格行要留着(self):
        c = scan.clean_body('# 标题\n\n| a | b |\n| 1 | 2 |\n')
        assert c.count('\n') >= 3 and '| a | b |' in c


class Test选段:
    BODY = ('The measured slope was $-23$ mV per decade and the detection limit '
            r'reached $10^{-10}\;\mathrm{M}$ in aqueous media, far below others. ')

    def test_含LaTeX数字的段落不能被丢掉(self):
        md = '## APPLICATION\n' + self.BODY * 4
        assert len(split_chunks(md)) == 1, '这段全是数据，不该被判成没有数字'

    def test_参考文献不喂给模型(self):
        md = ('## REFERENCES\n' + '(1) Filler, R. Future Med. Chem. 2009, 1, 777-791. ' * 8)
        assert split_chunks(md) == [], '参考文献数字最多，但一条性能都没有'

    def test_致谢与作者信息也不喂(self):
        md = '## AUTHOR INFORMATION\n' + 'Corresponding Author, 100 Main St, 2009. ' * 8
        assert split_chunks(md) == []
