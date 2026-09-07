# -*- coding: utf-8 -*-
"""schema 自测：纯逻辑，全离线、毫秒级。"""
import sys
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
from shared.domain import schema


def main():
    ok = total = 0

    total += 1
    p = schema.build_user_prompt('某篇论文', '正文内容')
    if all(f in p for f in schema.SCHEMA) and '某篇论文' in p:
        print(f'  [PASS] 抽取提示词含全部 {len(schema.SCHEMA)} 个字段'); ok += 1
    else:
        print('  [FAIL] 提示词缺字段')

    total += 1
    md = '正文正文\n\n## References\n\n[1] 某某\n' * 1
    body = schema.strip_refs('A' * 2000 + '\n## References\n' + 'B' * 500)
    if 'B' not in body and len(body) > 1000:
        print('  [PASS] 去参考文献'); ok += 1
    else:
        print(f'  [FAIL] 去参考文献异常（剩 {len(body)} 字符）')

    total += 1
    # 误判保护：切完剩不到两成就不切
    kept = schema.strip_refs('References\n' + 'X' * 3000)
    if len(kept) > 2000:
        print('  [PASS] 疑似误判时宁可不切'); ok += 1
    else:
        print('  [FAIL] 把正文切没了')

    total += 1
    long_md = ('# Title\n' + 'x' * 3000 + '\n## Introduction\n' + 'i' * 3000
               + '\n## Conclusion\n' + 'c' * 3000 + '\n## Acknowledgements\n' + 'a' * 9000)
    b = schema.hierarchical_body(long_md, budget=8000)
    if len(b) <= 12000 and 'c' * 100 in b:
        print('  [PASS] 层次化取正文：超预算时保住结论'); ok += 1
    else:
        print(f'  [FAIL] 层次化取正文异常（{len(b)} 字符）')

    total += 1
    si = ('## Results\n' + 'r' * 6000 + '\n## Materials and synthesis\n'
          + 'PDMS:boric acid = 10:1, cured at 150 °C for 2 h. ' + 'm' * 1000)
    b = schema.si_body(si, budget=4000)
    if '10:1' in b and 'r' * 100 not in b:
        print('  [PASS] SI 取文：抓住合成配方，丢掉纯结果段'); ok += 1
    else:
        print(f'  [FAIL] SI 取文没抓到配方（{len(b)} 字符）')

    total += 1
    p_si = schema.build_user_prompt('某篇', '正文', si='投料 10:1')
    p_no = schema.build_user_prompt('某篇', '正文')
    if '10:1' in p_si and 'SUPPLEMENTARY' in p_si and 'SUPPLEMENTARY' not in p_no:
        print('  [PASS] 有 SI 才把 SI 段加进提示词'); ok += 1
    else:
        print('  [FAIL] SI 提示词拼装不对')

    total += 1
    if (schema.tier_label({'source': 'coarse'}) == schema.TIER_COARSE
            and schema.tier_label({'si_used': True}) == schema.TIER_FINE_SI
            and schema.tier_label({}) == schema.TIER_FINE):     # 老记录没 source → 精层
        print('  [PASS] 来源档次：粗层 / 精层 / 精+SI 分得开'); ok += 1
    else:
        print('  [FAIL] 来源档次判断不对')

    total += 1
    if (schema.tier_label({'source': 'local', 'si_used': True}) == schema.TIER_LOCAL_SI
            and schema.tier_label({'source': 'local'}) == schema.TIER_LOCAL):
        print('  [PASS] 本地模型抽的单独一档，不冒充精层'); ok += 1
    else:
        print('  [FAIL] 本地档没分出来')

    total += 1
    if (not schema.has_value('N/A') and not schema.has_value([]) and not schema.has_value('未提及')
            and schema.has_value(['tensile strength: 12 MPa'])):
        print('  [PASS] 有值判据：N/A / 空列表 / 未提及 都算没值'); ok += 1
    else:
        print('  [FAIL] 有值判据不对')

    total += 1
    cov = schema.coverage([{'source': 'coarse', 'synthesis_conditions': 'N/A'},
                           {'si_used': True, 'synthesis_conditions': '150 °C, 2 h'}],
                          ['synthesis_conditions'])
    if (cov[schema.TIER_COARSE]['rate']['synthesis_conditions'] == 0.0
            and cov[schema.TIER_FINE_SI]['rate']['synthesis_conditions'] == 1.0):
        print('  [PASS] 有值率按档次分开统计'); ok += 1
    else:
        print(f'  [FAIL] 有值率统计不对：{cov}')

    total += 1
    recs = [{'title': 'A dynamic elastomer', 'doc_type': 'research', 'key_finding': 'x'},
            {'title': 'Recent advances in gels', 'doc_type': 'review', 'key_finding': 'y'}]
    t = schema.compare_table(recs)
    rv = schema.reviews_table(recs)
    if 'A dynamic elastomer' in t and 'Recent advances' not in t and 'Recent advances' in rv:
        print('  [PASS] 综述分流：研究论文进对比表，综述单列'); ok += 1
    else:
        print('  [FAIL] 综述分流不对')

    total += 1
    a = schema.parse_property('tensile strength: 12 MPa')
    b = schema.parse_property('Mn: 3.2×10^4 g/mol')
    c = schema.parse_property('degradation: 225-300 °C')
    d = schema.parse_property('stretchability: >20 times')
    if (a['value'] == 12 and a['unit'] == 'MPa' and b['value'] == 32000
            and c['value_max'] == 300 and d['cmp'] == '>'):
        print('  [PASS] 性能字符串拆成能比大小的数（含科学计数、区间、大于号）'); ok += 1
    else:
        print(f'  [FAIL] 性能解析不对：{a} {b} {c} {d}')

    total += 1
    e = schema.parse_property('self-healing: yes')
    ps = schema.parse_properties({'key_properties': ['tensile strength: 12 MPa',
                                                     'self-healing: yes']})
    if e['value'] is None and len(ps) == 2 and ps[0]['value'] == 12:
        print('  [PASS] 拆不出数字的也留着（只是不能比大小）'); ok += 1
    else:
        print(f'  [FAIL] 非数值性能被丢了：{ps}')

    total += 1
    t2 = schema.compare_table([{'title': '粗的', 'doc_type': 'research', 'source': 'coarse'},
                               {'title': '精的', 'doc_type': 'research', 'si_used': True}])
    if ('来源' in t2 and schema.TIER_COARSE in t2 and schema.TIER_FINE_SI in t2
            and t2.index('精的') < t2.index('| 粗的')):
        print('  [PASS] 对比表标出来源档次，且精层排在粗层前面'); ok += 1
    else:
        print('  [FAIL] 对比表没标来源或没排序')

    total += 1
    hit, tot, miss = schema.number_grounding(
        {'a': 'cured at 150 °C for 12 h', 'b': ['tensile strength: 99 MPa']},
        'The sample was cured at 150 °C for 12 h.')
    if hit == 2 and tot == 3 and miss == ['b: 99']:
        print('  [PASS] 数字回原文核对：编出来的那个 99 被挑出来了'); ok += 1
    else:
        print(f'  [FAIL] 数字核对不对：{hit}/{tot} {miss}')

    total += 1
    r = schema.make_record('ABCD1234', '标题', '10.1/x', {'material_system': 'PBS'},
                           si_used=True)
    if (r['schema_ver'] == schema.SCHEMA_VER and r['key'] == 'ABCD1234'
            and r['source'] == schema.SOURCE_FINE and r['si_used'] is True):
        print(f'  [PASS] 记录带 schema 版本号 v{r["schema_ver"]} + 来源档次 + 读没读 SI'); ok += 1
    else:
        print(f'  [FAIL] 记录缺版本号或来源：{r}')

    # ── v2：样品层与测量层 ────────────────────────────────────────────
    total += 1
    if (schema.normalize_property_name('Ultimate tensile stress') == 'tensile strength'
            and schema.normalize_property_name('断裂伸长率') == 'elongation at break'
            and schema.normalize_property_name('Healing efficiency') == 'self-healing efficiency'
            and schema.normalize_property_name('some odd prop') == 'some odd prop'):
        print('  [PASS] 性能名字归一：别名归到正名，词表外的原样留着'); ok += 1
    else:
        print('  [FAIL] 性能名字归一不对')

    v1 = {'key': 'K1', 'precursors': 'PDMS:boric acid = 10:1',
          'key_properties': ['tensile strength: 12 MPa', 'Mn: 3.2x10^4 g/mol']}
    total += 1
    s1 = schema.samples_of(v1)
    m1 = schema.iter_measurements(v1)
    if (len(s1) == 1 and s1[0]['sample_id'] == 'main'
            and len(m1) == 2 and m1[0]['value'] == 12.0
            and all(x['method'] == schema.METHOD_TEXT_V1 for x in m1)
            and all(x['location'] == '' for x in m1)):
        print('  [PASS] v1 老记录不重抽也能进三层（合成 main 样品，出处留空）'); ok += 1
    else:
        print(f'  [FAIL] v1 兼容不对：{s1} {m1}')

    v2 = {'key': 'K2',
          'samples': [{'sample_id': 'PBS-1', 'composition': 'a', 'preparation': 'b'},
                      {'sample_id': 'PBS-2', 'composition': 'c'}],
          'measurements': [
              {'sample_id': 'PBS-1', 'name': 'Ultimate tensile stress',
               'value_text': '12.4 MPa', 'condition': '100 mm/min',
               'location': 'Table 2', 'section': 'si'},
              {'sample_id': 'PBS-2', 'name': 'healing efficiency',
               'value_text': '95 %', 'location': '', 'section': 'main'}]}
    total += 1
    s2 = schema.samples_of(v2)
    m2 = schema.iter_measurements(v2)
    if (len(s2) == 2 and [x['sample_id'] for x in s2] == ['PBS-1', 'PBS-2']
            and len(m2) == 2 and m2[0]['name'] == 'tensile strength'
            and m2[0]['raw_name'] == 'Ultimate tensile stress'
            and m2[0]['value'] == 12.4 and m2[0]['unit'] == 'MPa'
            and m2[0]['location'] == 'Table 2' and m2[0]['section'] == 'si'
            and m2[1]['name'] == 'self-healing efficiency'):
        print('  [PASS] v2 记录：数字挂到样品上，条件与出处都留住了'); ok += 1
    else:
        print(f'  [FAIL] v2 读出不对：{s2} {m2}')

    total += 1
    st = schema.provenance_stats(m2)
    if st == {'n': 2, 'numeric': 2, 'located': 1, 'with_condition': 1, 'with_sample': 2}:
        print('  [PASS] 出处体温计：2 条数字里 1 条定位到了原文'); ok += 1
    else:
        print(f'  [FAIL] 出处统计不对：{st}')

    total += 1
    p = schema.build_user_prompt_v2('T', 'BODY', 'SIBODY')
    if ('"samples"' in p and '"measurements"' in p and 'sample_id' in p
            and 'Never convert units' in p and 'SIBODY' in p
            and 'material_system' in p):
        print('  [PASS] v2 提问同时要论文级字段、样品清单、带出处的测量清单'); ok += 1
    else:
        print('  [FAIL] v2 提问缺了某一部分')

    total += 1
    ms = schema.iter_measurements({'measurements': [
        {'sample_id': 'A', 'name': 'tensile strength', 'value_text': '12 MPa',
         'location': 'main text', 'section': 'main'},
        {'sample_id': 'A', 'name': 'toughness', 'value_text': '3 kJ/m^2',
         'location': 'SI', 'section': 'si'},
        {'sample_id': 'A', 'name': 'elongation at break', 'value_text': '300 %',
         'location': 'Fig. 3b', 'section': 'main'}]})
    if ([m['location'] for m in ms] == ['', '', 'Fig. 3b']
            and schema.provenance_stats(ms)['located'] == 1):
        print('  [PASS] 「main text / SI」不算出处（否则有出处率永远 100%）'); ok += 1
    else:
        print(f'  [FAIL] 废话出处没被清掉：{[m["location"] for m in ms]}')

    total += 1
    curve = {'chart_type': 'line', 'confidence': 'medium',
             'x_axis': {'label': 'Strain', 'unit': '%'},
             'y_axis': {'label': 'Stress', 'unit': 'MPa'},
             'series': [{'name': 'PBS-1',
                         'points': [[0, 0], [100, 8.2], [300, 12.4], [400, 5.0]]}]}
    cm = schema.curve_measurements(curve, fig=3)
    if (len(cm) == 2 and cm[0]['value'] == 12.4 and cm[0]['unit'] == 'MPa'
            and cm[1]['value'] == 300 and cm[0]['sample_id'] == 'PBS-1'
            and cm[0]['location'] == 'Fig. 3' and cm[0]['method'] == schema.METHOD_CURVE):
        print('  [PASS] 曲线 → 峰值与峰值处的 X，出处到图号、标明是抠图来的'); ok += 1
    else:
        print(f'  [FAIL] 曲线派生不对：{cm}')

    total += 1
    if (schema.curve_measurements({'error': '读不出'}, fig=1) == []
            and schema.curve_measurements(
                {'series': [{'name': 'a', 'points': []}]}, fig=1) == []):
        print('  [PASS] 读失败或没有点的曲线不派生任何数字（不许无中生有）'); ok += 1
    else:
        print('  [FAIL] 空曲线竟然派生出了数字')

    total += 1
    rec = {'samples': [{'sample_id': 'PBS-1', 'composition': 'a'}],
           'measurements': [
               {'sample_id': 'main', 'name': 'tensile strength', 'value_text': '12 MPa'},
               {'sample_id': 'PBS/LMMT-2wt%', 'name': 'toughness', 'value_text': '3 kJ/m^2'}]}
    ms = schema.iter_measurements(rec)
    sp = schema.samples_of(rec, ms)
    ids = [x['sample_id'] for x in sp]
    if (ids == ['PBS-1', 'PBS/LMMT-2wt%']
            and [m['sample_id'] for m in ms] == ['PBS-1', 'PBS/LMMT-2wt%']
            and '只在数值里出现过' in sp[1]['role']):
        print('  [PASS] 悬空的数值接回样品：main 归到唯一那个，具名的补一条样品'); ok += 1
    else:
        print(f'  [FAIL] 悬空数值没接回去：{ids} / {[m["sample_id"] for m in ms]}')

    total += 1
    rec2 = {'samples': [{'sample_id': 'A'}, {'sample_id': 'B'}],
            'measurements': [{'sample_id': 'main', 'name': 'x', 'value_text': '1 MPa'}]}
    ms2 = schema.iter_measurements(rec2)
    sp2 = schema.samples_of(rec2, ms2)
    if [x['sample_id'] for x in sp2] == ['A', 'B', 'main']:
        print('  [PASS] 有两个样品时不猜 main 归谁（单列出来，让人看见这个不确定）'); ok += 1
    else:
        print(f'  [FAIL] 不该猜的时候猜了：{[x["sample_id"] for x in sp2]}')

    total += 1
    import re as _re
    prompt = schema.build_user_prompt_v2('T', 'BODY')
    # 提示词里出现的每个数，除了 PART 1/2/3 这种序号，都是**给模型的现成答案**。
    # 2026-09-07 实测：gemma3:1b 抽摘要时把字段说明里的 12 / 3.2 / 10 原样吐了出来，
    # 数字接地率只有 3% —— 它读不动那份说明，就照着例子编。
    nums = set(_re.findall(r'(?<![\w<])\d+(?:\.\d+)?(?![\w>])', prompt)) - {'1', '2', '3'}
    if not nums:
        print('  [PASS] 提示词里没有示例数值（有的话小模型会照抄，实测接地率掉到 3%）'); ok += 1
    else:
        print(f'  [FAIL] 提示词里混进了具体数字，小模型会抄它们：{sorted(nums)[:8]}')

    # ── 洗表格：下面每一条都是 2026-09-07 在 42 篇真实全文里实测到的脏 ──
    from shared.domain.schema import scan

    total += 1
    cases = {r'$M_{n}$': 'Mn', r'$\overline{M}_{n}$': 'Mn',
             r'$T_{c,onset}$': 'Tc,onset', r'$k_{hn} \times 10^{-3}$': 'khn × 10-3'}
    bad = {k: scan.clean_label(k) for k, v in cases.items() if scan.clean_label(k) != v}
    if not bad:
        print('  [PASS] 表头里的 LaTeX 洗成人话（实测 150/428 条名字带 LaTeX）'); ok += 1
    else:
        print(f'  [FAIL] LaTeX 没洗干净：{bad}')

    total += 1
    # 误差棒和比号长得像单位。挂上假单位比没有单位更坏 —— 它会被当真去比大小。
    if (scan._clean_unit('± 1.7') == '' and scan._clean_unit(':1') == ''
            and scan._clean_unit('MPa') == 'MPa'):
        print('  [PASS] 误差棒与比号不当单位（实测 37 条挂过假单位）'); ok += 1
    else:
        print('  [FAIL] 假单位没拦住')

    total += 1
    # 一格塞两代样品，硬拆就是灌假数；误差棒是同一个数的精度，要留。
    if (scan._cell_number('PD 1.68 1.28') is None
            and scan._cell_number('12.4 (±0.10)') == '12.4'
            and scan._cell_number('10–20') == '10–20'):
        print('  [PASS] 一格多值不猜；误差棒剥掉、区间留住'); ok += 1
    else:
        print(f'  [FAIL] 一格多值判错：{scan._cell_number("PD 1.68 1.28")!r} / '
              f'{scan._cell_number("12.4 (±0.10)")!r} / {scan._cell_number("10–20")!r}')

    total += 1
    # 「名字里有两个数」当判据会误伤条件（200/800 是温度区间，不是数据）
    if (scan._is_collapsed('CFRP Laminate 8.31 13.74')
            and not scan._is_collapsed('Weight loss (%) 200/800')
            and not scan._is_collapsed('Energy loss coefficient 1st cycle')):
        print('  [PASS] 塌陷行整列丢掉，但不误伤「条件里带数字」的表头'); ok += 1
    else:
        print('  [FAIL] 塌陷判据误伤了正常表头')

    total += 1
    # 转置表：第一列是性能、表头是样品。**必须先洗 LaTeX 再判**，否则认不出来。
    t_md = ('Table 1. Properties.\n\n<table><tr><td></td><td>PDMS1</td><td>PDMS2</td></tr>'
            '<tr><td>$d_w$ (μm)</td><td>0.39</td><td>0.52</td></tr>'
            '<tr><td>apparent $E_a$ (kJ/mol)</td><td>61</td><td>72</td></tr></table>')
    rows = scan.scan_tables(t_md)
    sids = sorted({r['sample_id'] for r in rows})
    if sids == ['PDMS1', 'PDMS2'] and len(rows) == 4:
        print('  [PASS] 转置表转回来了（洗过 LaTeX 才认得出第一列是性能名）'); ok += 1
    else:
        print(f'  [FAIL] 转置表没转回来：样品={sids} 条数={len(rows)}')

    total += 1
    # 投料量属于配方，不该进测量层去跟别人比大小
    c_md = ('Table 2. Formulations.\n\n<table><tr><td>Sample</td><td>PA6 (wt%)</td>'
            '<td>Tensile strength (MPa)</td></tr>'
            '<tr><td>PA6/PBS-1</td><td>80</td><td>52.3</td></tr></table>')
    rows = scan.scan_tables(c_md)
    kinds = {r['raw_name']: r['kind'] for r in rows}
    if (kinds.get('PA6') == 'composition'
            and kinds.get('Tensile strength') == 'measurement'):
        print('  [PASS] 投料量与性能分开（wt% 的组分是配方，不是性能）'); ok += 1
    else:
        print(f'  [FAIL] 投料量没分出来：{kinds}')

    total += 1
    # 出处是脚本从同一段文字里读到的，不可能是编的
    if rows and all(r['location'] == 'Table 2' and r['method'] == 'script' for r in rows):
        print('  [PASS] 表格里的每条都带出处与 method=script'); ok += 1
    else:
        print(f'  [FAIL] 出处丢了：{[(r["location"], r["method"]) for r in rows]}')



    print(f'\n{ok}/{total} 通过')
    sys.exit(0 if ok == total else 1)


if __name__ == '__main__':
    main()
