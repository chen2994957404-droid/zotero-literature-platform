# -*- coding: utf-8 -*-
"""cnki 自测：结果行（学位论文 / 专利两种列）、各库条数、总数与页码、摘要页解析、拼图验证码的位置判断，
都用 2026-10-09 主力机实测到的页面离线验。真去知网查一次藏在 --live 后面。"""
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass

from shared.adapters import cnki
from shared.kernel.cli import flag


def cell(cls, text, links=None):
    return {'cls': cls, 'text': text, 'links': links or []}


THESIS_ROW = {'href': 'https://kns.cnki.net/kcms2/article/abstract?v=abc', 'db': 'CMFD', 'fn': '1025839145.nh',
              'cells': [cell('seq', '11'), cell('name', '聚乙二醇-SiO2与聚硼硅氧烷改性聚氨酯的制备及力学性能研究'),
                        cell('author', '夏俊', ['夏俊']), cell('source', '西安理工大学'), cell('date', '2025-06-30'),
                        cell('data', '硕士'), cell('quote', ''), cell('download', '165'), cell('operat', '下载 原版阅读')]}
PATENT_ROW = {'href': 'https://kns.cnki.net/kcms2/article/abstract?v=def', 'db': 'SCPD', 'fn': 'CN122788335A',
              'cells': [cell('seq', '1'), cell('name', '一种蜂窝夹芯复合材料及其制备方法'),
                        cell('inventor', '张三;李四', ['张三', '李四']), cell('applicant', '某某大学', ['某某大学']),
                        cell('data', '中国专利'), cell('date', '2026-03-01'), cell('date', '2026-08-26'), cell('operat', '')]}

DETAIL = '\n'.join([
    '目录',
    '第五章 含Si-O-B键的聚硼硅氧烷的水解性能电化学高灵敏检测',
    '\t5.1 前言',
    '\t5.2 实验部分',
    '第七章 总结与展望',
    '附录',
    '',
    '苯并噁嗪树脂与聚硼硅氧烷杂化对材料性能有何影响？',
    '服务推荐',
    '推广 X',
    '山东大学山东省211工程院校985工程院校教育部直属院校一流大学',
    '含Si、B和Ti的苯并噁嗪树脂的合成及其性能研究',
    '刘宝良',
    '山东大学',
    '摘要：\t苯并噁嗪树脂是一种新型的高性能热固性树脂,其开环聚合无小分子物质释放。... 更多',
    '关键词：\t苯并噁嗪树脂;Si-O-C键;Si-O-B键;Si-O-Ti键;',
    'DOI：\t10.27272/d.cnki.gshdu.2024.000361',
    '分类号：\tTQ323',
    '导师：\t鲁在君',
    '学科专业：\t高分子化学与物理',
])


def main():
    ok = total = 0

    def check(name, cond, detail: object = ''):
        nonlocal ok, total
        total += 1
        if cond:
            print(f'  [PASS] {name}'); ok += 1
        else:
            print(f'  [FAIL] {name}  {detail}')

    th, pa = cnki.parse_rows([THESIS_ROW, PATENT_ROW])
    check('学位论文行：标题 / 作者 / 学校 / 日期 / 类型 / 下载数',
          (th['rank'], th['authors'], th['source'], th['date'], th['type'], th['downloads'], th['cited']) ==
          (11, ['夏俊'], '西安理工大学', '2025-06-30', '硕士', 165, 0), th)
    check('学位论文行：库名与文件名留着（以后对账用）', th['db'] == 'CMFD' and th['filename'] == '1025839145.nh')
    check('专利行：发明人、申请人、申请日与公开日分开、专利号',
          (pa['inventors'], pa['applicants'], pa['date_applied'], pa['date_published'], pa['patent_no']) ==
          (['张三', '李四'], ['某某大学'], '2026-03-01', '2026-08-26', 'CN122788335A'), pa)
    check('没有标题的行丢掉', cnki.parse_rows([{'cells': [cell('seq', '1')]}]) == [])

    check('各库条数', cnki.parse_counts([{'name': '学术期刊', 'n': '47'}, {'name': '学位论文', 'n': '34'},
                                       {'name': '博士', 'n': '4'}, {'name': '专利', 'n': ''}]) ==
          {'学术期刊': 47, '学位论文': 34, '博士': 4})
    check('总数与页码', cnki.parse_total('共找到 498 条结果 1/25 >> 全选') == (498, 1, 25)
          and cnki.parse_total('共找到 4 条结果  全选') == (4, 1, 1)
          and cnki.parse_total('没有') == (None, None, None))

    d = cnki.parse_detail(DETAIL)
    f = d['fields']
    check('摘要页：标题 / 作者 / 学校', (d.get('title'), d.get('authors_line'), d.get('institution')) ==
          ('含Si、B和Ti的苯并噁嗪树脂的合成及其性能研究', '刘宝良', '山东大学'), d)
    check('摘要页：摘要去掉「更多」', f.get('摘要', '').endswith('无小分子物质释放。'), f.get('摘要'))
    check('摘要页：关键词拆成列表', f.get('关键词') == ['苯并噁嗪树脂', 'Si-O-C键', 'Si-O-B键', 'Si-O-Ti键'], f.get('关键词'))
    check('摘要页：DOI / 导师 / 学科专业', (f.get('DOI'), f.get('导师'), f.get('学科专业')) ==
          ('10.27272/d.cnki.gshdu.2024.000361', '鲁在君', '高分子化学与物理'), f)
    check('摘要页：章节目录到问答推荐之前为止', d['outline'][0].startswith('第五章') and d['outline'][-1] == '附录'
          and len(d['outline']) == 5, d['outline'])

    check('验证码：挂在屏幕外、透明 → 没弹',
          not cnki.captcha_active({'top': -1000000, 'w': 218, 'h': 279, 'op': '0', 'disp': 'block', 'vis': 'visible'}))
    check('验证码：挪进屏幕、看得见 → 弹了',
          cnki.captcha_active({'top': 230, 'w': 340, 'h': 300, 'op': '1', 'disp': 'block', 'vis': 'visible'}))
    check('验证码：没有这个元素 → 没弹', not cnki.captcha_active(None))
    check('库名对应的标签', cnki.kind_selector('phd').endswith('"CDFD"]') and cnki.kind_selector('all') is None)
    for bad, fn in (('book', cnki.check_kind), ('newest', cnki.check_sort)):
        try:
            fn(bad)
            check(f'不认的参数「{bad}」要拒', False)
        except ValueError:
            check(f'不认的参数「{bad}」要拒', True)

    if flag('--live'):
        st = cnki.status()
        print('  [LIVE] status:', st)
        if not st.get('captcha'):
            r = cnki.search('聚硼硅氧烷', kind='phd')
            check('[LIVE] 查聚硼硅氧烷博士论文', r['code'] in ('OK', 'NO_RESULTS'), r.get('why'))
    else:
        print('  [SKIP] 真查知网（加 --live；只在主力机上有意义）')

    print(f'\ncnki selftest: {ok}/{total} passed')
    return 0 if ok == total else 1


if __name__ == '__main__':
    sys.exit(main())
