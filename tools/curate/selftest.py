# -*- coding: utf-8 -*-
"""curate 自测：不连 Zotero、不写任何东西，验分组/改名/标签的判定逻辑。

这些判定一旦错，代价是**删错条目或改错附件名**，所以纯逻辑部分必须能离线测。
"""
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from tools.curate import journals, junk, rename, tags


def _item(key, title, doi='', n_children=0, item_type='journalArticle'):
    return {'key': key, 'meta': {'numChildren': n_children},
            'data': {'title': title, 'DOI': doi, 'itemType': item_type}}


def main():
    ok = total = 0

    # ── 垃圾条目分组：A 组删了不丢东西，B 组删了就真没了 ──────────────
    tops = [
        _item('K1', 'Shear stiffening gel', '10.1/a', n_children=2),   # 正版，带 PDF
        _item('K2', 'Shear-Stiffening  Gel!', '', n_children=0),       # 同名残留 → A
        _item('K3', 'Only copy in library', '10.1/z', n_children=0),   # 独一份 → B
        _item('K4', 'Dup by doi', '10.1/A', n_children=0),             # DOI 撞上 K1 → A
    ]
    A, B = junk.split_junk(tops)
    total += 1
    if [x['key'] for x in A] == ['K2', 'K4'] and [x['key'] for x in B] == ['K3']:
        print('  [PASS] 无 PDF 条目分组：重复残留归 A，独一份归 B'); ok += 1
    else:
        print(f'  [FAIL] 分组不对：A={[x["key"] for x in A]} B={[x["key"] for x in B]}')

    total += 1
    if not any(x['key'] == 'K1' for x in A + B):
        print('  [PASS] 带 PDF 的正版不会被列进待删'); ok += 1
    else:
        print('  [FAIL] 把带 PDF 的正版列进待删了')

    # ── 附件改名：认错 SI 的代价是「精读读了补充材料当正文」 ───────────
    cases = [
        ({'contentType': 'application/pdf', 'filename': 'paper.pdf', 'title': ''},
         'Full Text PDF', '正文 PDF'),
        ({'contentType': 'application/pdf', 'filename': 'acsami_suppmat.pdf', 'title': ''},
         'SI', '文件名里的 suppmat'),
        ({'contentType': 'application/pdf', 'filename': 'x.pdf', 'title': 'SI'},
         'SI', '标题就叫 SI'),
        ({'contentType': 'text/html', 'filename': '', 'title': 'Snap'},
         'Snapshot', '网页快照'),
        ({'contentType': 'application/epub', 'filename': 'b.epub', 'title': ''},
         None, '不认识的类型不动它'),
    ]
    for d, want, why in cases:
        total += 1
        got = rename.classify(d)
        if got == want:
            print(f'  [PASS] 附件分类：{why} → {want}'); ok += 1
        else:
            print(f'  [FAIL] 附件分类错了（{why}）：{got} ≠ {want}')

    # ── 标签改嵌套：只动维度标签，别的原样留着 ─────────────────────
    total += 1
    got = tags.nested_of([{'tag': 'topic:self-healing'}, {'tag': '待处理'},
                          {'tag': 'material:pdms'}])
    if got == [{'tag': 'topic/self-healing'}, {'tag': '待处理'}, {'tag': 'material/pdms'}]:
        print('  [PASS] 维度标签改嵌套，工作流标签原样保留'); ok += 1
    else:
        print(f'  [FAIL] 标签改造不对：{got}')

    total += 1
    if tags.nested_of([{'tag': '待处理'}, {'tag': 'topic/already'}]) is None:
        print('  [PASS] 没有可改的就返回 None（不产生一次无谓写回）'); ok += 1
    else:
        print('  [FAIL] 没东西可改却说要改')

    # ── 期刊分级：档次判定是纯逻辑，必须离线可测 ───────────────────────
    top = {'display_name': 'Advanced Materials', 'host_organization_name': 'Wiley',
           'summary_stats': {'2yr_mean_citedness': 22.4}}
    mid = {'display_name': 'Some Journal', 'summary_stats': {'2yr_mean_citedness': 9.1}}
    low = {'display_name': 'Tiny Journal', 'summary_stats': {'2yr_mean_citedness': 1.2}}
    unknown = {'display_name': 'No Metrics Journal'}
    mdpi = {'display_name': 'Polymers',
            'host_organization_name': 'Multidisciplinary Digital Publishing Institute',
            'summary_stats': {'2yr_mean_citedness': 7.3}}

    total += 1
    got = [journals.tier_of(x)[0] for x in (top, mid, low, unknown)]
    if got == ['顶刊', '一流', '一般', '一般']:
        print('  [PASS] 期刊分档按近两年篇均被引，查不到指标的算「一般」'); ok += 1
    else:
        print(f'  [FAIL] 分档不对：{got}')

    total += 1
    t, why = journals.tier_of(mdpi, journals.DEFAULT_OVERRIDES)
    t2, _ = journals.tier_of(mdpi)
    if t == '慎用' and '用户名单' in why and t2 == '常规':
        print('  [PASS] 用户名单压过指标（MDPI 指标不低，但用户说过不看不引）'); ok += 1
    else:
        print(f'  [FAIL] 用户名单没压过指标：{t} / {why} / 无名单时 {t2}')

    total += 1
    ov = {'journals': {'tiny journal': '慎用'}}
    if journals.tier_of(low, ov)[0] == '慎用' and journals.tier_of(top, ov)[0] == '顶刊':
        print('  [PASS] 名单也能按刊名单点某一本，不影响别的'); ok += 1
    else:
        print('  [FAIL] 按刊名的名单不生效')

    print(f'\n{ok}/{total} 通过')
    sys.exit(0 if ok == total else 1)


if __name__ == '__main__':
    main()
