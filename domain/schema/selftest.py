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
    recs = [{'title': 'A dynamic elastomer', 'doc_type': 'research', 'key_finding': 'x'},
            {'title': 'Recent advances in gels', 'doc_type': 'review', 'key_finding': 'y'}]
    t = schema.compare_table(recs)
    rv = schema.reviews_table(recs)
    if 'A dynamic elastomer' in t and 'Recent advances' not in t and 'Recent advances' in rv:
        print('  [PASS] 综述分流：研究论文进对比表，综述单列'); ok += 1
    else:
        print('  [FAIL] 综述分流不对')

    total += 1
    r = schema.make_record('ABCD1234', '标题', '10.1/x', {'material_system': 'PBS'})
    if r['schema_ver'] == schema.SCHEMA_VER and r['key'] == 'ABCD1234':
        print(f'  [PASS] 记录带 schema 版本号 v{r["schema_ver"]}（升版才知道谁该重抽）'); ok += 1
    else:
        print('  [FAIL] 记录缺版本号')

    print(f'\n{ok}/{total} 通过')
    sys.exit(0 if ok == total else 1)


if __name__ == '__main__':
    main()
