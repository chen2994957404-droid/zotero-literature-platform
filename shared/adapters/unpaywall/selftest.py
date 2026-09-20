# -*- coding: utf-8 -*-
"""unpaywall 自测：字段映射离线验；联网那条查不通或没配邮箱就 SKIP。"""
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass

from shared.adapters import unpaywall

REC = {'is_oa': True,
       'best_oa_location': {'url_for_pdf': None, 'url': 'https://x/landing', 'version': 'publishedVersion', 'host_type': 'publisher'},
       'oa_locations': [{'url_for_pdf': None}, {'url_for_pdf': 'https://repo/x.pdf', 'version': 'acceptedManuscript', 'host_type': 'repository', 'license': 'cc-by'}]}


def main():
    ok = total = 0
    total += 1
    i = unpaywall.to_info(REC)
    if i and i['pdf_url'] == 'https://repo/x.pdf' and i['version'] == 'acceptedManuscript' and i['host'] == 'repository':
        print('  [PASS] 最佳位置没直链时退到别的位置找 PDF 直链'); ok += 1
    else:
        print('  [FAIL] 映射不对：%s' % i)
    total += 1
    if unpaywall.to_info({'is_oa': False}) is None and unpaywall.to_info(None) is None:
        print('  [PASS] 不开放 / 空记录 → None'); ok += 1
    else:
        print('  [FAIL] 不开放的没返回 None')
    if unpaywall.email():
        try:
            info = unpaywall.lookup('10.1038/s41467-024-45485-8')
            total += 1
            if info and info['pdf_url']:
                print('  [PASS] 真实查询：%s（%s）' % (info['version'], info['host'])); ok += 1
            else:
                print('  [FAIL] 真实查询没拿到直链：%s' % info)
        except unpaywall.UnpaywallError as e:
            print('  [SKIP] 连不上（%s）' % str(e)[:40])
    else:
        print('  [SKIP] 没配 UNPAYWALL_EMAIL，跳过联网那条')
    print('\n%d/%d 通过' % (ok, total))
    sys.exit(0 if ok == total else 1)


if __name__ == '__main__':
    main()
