# -*- coding: utf-8 -*-
"""semanticscholar 自测：字段映射离线验；联网那条连不上就 SKIP（公共池也能跑，不需要 key）。"""
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.adapters import semanticscholar as s2

REC = {'paperId': 'abc', 'externalIds': {'DOI': '10.1038/S41467-024-45485-8'}, 'title': 'Tough  double\nnetwork',
       'abstract': 'x' * 10, 'tldr': {'text': ' one line '}, 'citationCount': 348,
       'openAccessPdf': {'url': 'https://x/pdf'}, 'publicationDate': '2024-02-13'}


def main():
    ok = total = 0
    total += 1
    n = s2.normalize(REC)
    if (n['doi'] == '10.1038/s41467-024-45485-8' and n['title'] == 'Tough double network' and n['tldr'] == 'one line'
            and n['citations'] == 348 and n['oa_pdf'] == 'https://x/pdf'):
        print('  [PASS] 映射：DOI 小写、标题去换行、TLDR 去空白'); ok += 1
    else:
        print('  [FAIL] 映射不对：%s' % n)
    total += 1
    if s2.normalize(None) is None:
        print('  [PASS] 查不到 → None'); ok += 1
    else:
        print('  [FAIL] None 没原样返回')
    try:
        got = s2.papers(['10.1038/s41467-024-45485-8', '10.9999/not-a-real-doi'])
        total += 1
        if '10.1038/s41467-024-45485-8' in got and '10.9999/not-a-real-doi' not in got:
            print('  [PASS] 真实批量查询：有的在、没有的不在（被引 %d）' % got['10.1038/s41467-024-45485-8']['citations']); ok += 1
        else:
            print('  [FAIL] 批量查询结果不对：%s' % list(got))
    except s2.S2Error as e:
        print('  [SKIP] 连不上（%s）' % str(e)[:40])
    print('\n%d/%d 通过' % (ok, total))
    sys.exit(0 if ok == total else 1)


if __name__ == '__main__':
    main()
