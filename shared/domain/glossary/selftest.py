# -*- coding: utf-8 -*-
"""glossary 自测：纯逻辑，不联网、不碰用户数据。

测的是四条承诺：
  ① 挖得出「中文（英文）」对，且能去掉粘在前面的动词
  ② 洗表：后缀变体合并、一次性的不要、歧义都留
  ③ 只把这篇原文里出现过的词塞进提示词
  ④ 产出里译名与表不符的能抓出来，符合的不误报
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass

from shared.domain.glossary import build, lookup, mine, mismatches, prompt_block

_fail = []


def check(name, cond, extra=''):
    print(('  [PASS] ' if cond else '  [FAIL] ') + name + (('  ' + extra) if extra else ''))
    if not cond:
        _fail.append(name)


def main():
    print('glossary 自测')
    texts = ['采用扫描电子显微镜（SEM）观察，聚偏氟乙烯（PVDF）为粘结剂，单宁酸（TA）交联',
             '通过扫描电子显微镜（SEM）表征；以聚偏氟乙烯（PVDF）为对照；硫辛酸（TA）；单宁酸（TA）',
             '扫描电子显微镜（SEM）；硫辛酸（TA）；一次性错译（PVDF）']
    c = mine(texts)
    check('挖对 + 去动词', c['SEM']['扫描电子显微镜'] == 3 and c['PVDF']['聚偏氟乙烯'] == 2, str(dict(c['SEM'])))
    t = build(c)
    check('一次性的不要', lookup(t, 'PVDF') == ['聚偏氟乙烯'], str(lookup(t, 'PVDF')))
    check('歧义都留', set(lookup(t, 'TA')) == {'单宁酸', '硫辛酸'}, str(lookup(t, 'TA')))
    pb = prompt_block(t, 'We used SEM and PVDF binder. DMF was the solvent.')
    check('只列原文里有的', 'SEM=扫描电子显微镜' in pb and 'PVDF=聚偏氟乙烯' in pb and 'TA' not in pb, pb)
    t['PVDF']['n'] = 9                                   # 票够多、无歧义 → 强制
    m = mismatches(t, '以聚丙烯腈（PVDF）为粘结剂，用扫描电子显微镜（SEM）观察，硫辛酸（TA）交联')
    check('抓错译不误报', m == [('PVDF', '聚丙烯腈', '聚偏氟乙烯')], str(m))
    t['PVDF']['n'] = 2
    check('票少的不强制', mismatches(t, '聚丙烯腈（PVDF）') == [] and mismatches(t, '石墨烯（TA）') == [])
    print('\n%d/%d 通过' % (5 - len(_fail), 5))
    return 0 if not _fail else 1


if __name__ == '__main__':
    sys.exit(main())
