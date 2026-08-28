# -*- coding: utf-8 -*-
"""schema 自测：纯逻辑，全离线、毫秒级。"""
import sys
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
from domain import schema


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
    t2 = schema.compare_table([{'title': '粗的', 'doc_type': 'research', 'source': 'coarse'},
                               {'title': '精的', 'doc_type': 'research', 'si_used': True}])
    if ('来源' in t2 and schema.TIER_COARSE in t2 and schema.TIER_FINE_SI in t2
            and t2.index('精的') < t2.index('| 粗的')):
        print('  [PASS] 对比表标出来源档次，且精层排在粗层前面'); ok += 1
    else:
        print('  [FAIL] 对比表没标来源或没排序')

    total += 1
    r = schema.make_record('ABCD1234', '标题', '10.1/x', {'material_system': 'PBS'},
                           si_used=True)
    if (r['schema_ver'] == schema.SCHEMA_VER and r['key'] == 'ABCD1234'
            and r['source'] == schema.SOURCE_FINE and r['si_used'] is True):
        print(f'  [PASS] 记录带 schema 版本号 v{r["schema_ver"]} + 来源档次 + 读没读 SI'); ok += 1
    else:
        print(f'  [FAIL] 记录缺版本号或来源：{r}')

    print(f'\n{ok}/{total} 通过')
    sys.exit(0 if ok == total else 1)


if __name__ == '__main__':
    main()
