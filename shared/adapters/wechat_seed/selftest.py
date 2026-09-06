# -*- coding: utf-8 -*-
"""wechat_seed 自测：验证从公众号 md 里提 DOI 和推送日期。
用法: python shared/adapters/wechat_seed/selftest.py

重点测两个真实踩过的坑：
  ① DOI 里的**非断行连字符 U+2011** —— 不归一化会白丢文献
  ② DOI 后面紧跟中文标点（「。」「）」）—— 不剔掉会带进 OpenAlex 查不到
"""
import os
import shutil
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import io as _io
from shared.adapters import wechat_seed as ws

ok = True


def check(name, cond, detail=''):
    global ok
    print(('  [OK]   ' if cond else '  [FAIL] ') + name + (('  ' + detail) if detail else ''))
    if not cond:
        ok = False


print('== 1. 正常一篇 ==')
doi, date = ws.extract('标题\n\n_2026年8月1日 09:46_ 江苏\n\n原文链接 '
                       'https://doi.org/10.1021/acsami.5c03066\n')
check('提到 DOI', doi == '10.1021/acsami.5c03066', doi)
check('提到日期', date == '2026-08-01', date)

print('== 2. 非断行连字符（踩坑）==')
doi, _ = ws.extract('doi: 10.1038/s41467‑026‑77296‑4')
check('U+2011 归一成 -', doi == '10.1038/s41467-026-77296-4', doi)

print('== 3. 尾部中文标点 ==')
for raw, want in [('见 10.1021/acsnano.6c06313。', '10.1021/acsnano.6c06313'),
                  ('（10.1002/adfm.77041）', '10.1002/adfm.77041'),
                  ('10.1039/d3gc00123a，很好', '10.1039/d3gc00123a')]:
    got, _ = ws.extract(raw)
    check('剔掉尾部标点: %s' % raw[:18], got == want, got)

print('== 4. 非论文推送（会议通知/招聘）==')
doi, date = ws.extract('会议邀请 相约大理\n\n_2026年7月5日 10:00_\n\n报名从速')
check('没有 DOI 时返回空串', doi == '', repr(doi))
check('日期仍然提得到', date == '2026-07-05', date)

print('== 5. 大小写与前缀规范化 ==')
check('去 https 前缀 + 小写',
      ws.normalize_doi('HTTPS://DOI.ORG/10.1021/ABC') == '10.1021/abc')

print('== 6. 扫目录 ==')
d = tempfile.mkdtemp(prefix='wxseed_')
try:
    _io.open(os.path.join(d, 'AdvMater某某某.md'), 'w', encoding='utf-8').write(
        '_2026年6月1日 08:00_\n10.1002/adma.202400001\n')
    _io.open(os.path.join(d, '会议邀请某会.md'), 'w', encoding='utf-8').write(
        '_2025年12月1日 08:00_\n没有链接\n')
    seeds = ws.scan(d)
    check('扫到 2 篇', len(seeds) == 2, str(len(seeds)))
    st = ws.stats(seeds)
    check('统计 with_doi=1', st['with_doi'] == 1, str(st['with_doi']))
    check('统计日期范围', st['earliest'] == '2025-12-01' and st['latest'] == '2026-06-01',
          '%s ~ %s' % (st['earliest'], st['latest']))
    check('文件名猜期刊', seeds[0]['journal_hint'] == 'AdvMater', seeds[0]['journal_hint'])

    print('== 7. 目录不对时报错清楚 ==')
    empty = tempfile.mkdtemp(prefix='wxempty_')
    try:
        try:
            ws.scan(empty)
            check('空目录应报错', False)
        except ws.SeedError as e:
            check('空目录报 SeedError', 'md' in str(e))
    finally:
        shutil.rmtree(empty, ignore_errors=True)
    try:
        ws.scan(os.path.join(d, '不存在'))
        check('不存在的目录应报错', False)
    except ws.SeedError:
        check('不存在的目录报 SeedError', True)
finally:
    shutil.rmtree(d, ignore_errors=True)

print('== 8. 取正文：头尾的平台噪音与品牌图要被剥掉 ==')
ART = """#  【ACS AMI】某某策略：某某弹性体！

原创  PolyScientist  高分子学人

_2026年08月17日 08:34_ __ _ _ 江苏  _

在小说阅读器读本章

去阅读

![](https://mmbiz.qpic.cn/head/640?wx_fmt=png)

近期，Xiaobo Wei, Dong
Wang 等开发出一条温和路线，解决了强度与拉伸
无法兼顾的老问题。

![](https://mmbiz.qpic.cn/fig1/640?wx_fmt=png)

总之，本论文的创新点在于某某。

![](https://mmbiz.qpic.cn/card/640?wx_fmt=png)

https://doi.org/  10.1021/acsami.6c10893

![](https://mmbiz.qpic.cn/qrcode/640?wx_fmt=png)

预览时标签不可点

知道了
"""
a = ws.parse_article(ART)
check('标题去掉井号', a['title'].startswith('【ACS AMI】'), a['title'])
check('DOI 中间有空格也认得', a['doi'] == '10.1021/acsami.6c10893', a['doi'])
check('推送日期', a['pubdate'] == '2026-08-17', a['pubdate'])
imgs = [b['url'] for b in a['blocks'] if b['kind'] == 'img']
check('头图被剥掉', not any('head' in u for u in imgs), str(imgs))
check('二维码被剥掉（在 DOI 行之后）', not any('qrcode' in u for u in imgs), str(imgs))
check('文献配图留下了', any('fig1' in u for u in imgs), str(imgs))
ps = [b['text'] for b in a['blocks'] if b['kind'] == 'p']
check('署名/日期/平台按钮都不算正文', all('去阅读' not in t and '原创' not in t for t in ps))
check('英文折行用空格接回', 'Xiaobo Wei, Dong Wang' in ps[0], ps[0][:40])
check('中文折行不加空格', '强度与拉伸无法兼顾' in ps[0], ps[0][-30:])
check('段落按图切开', len(ps) == 2, str(len(ps)))


print('')
print('全部通过' if ok else '有失败项')
sys.exit(0 if ok else 1)
