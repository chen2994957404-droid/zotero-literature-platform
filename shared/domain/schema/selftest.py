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

    print(f'\n{ok}/{total} 通过')
    sys.exit(0 if ok == total else 1)


if __name__ == '__main__':
    main()
