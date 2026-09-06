# -*- coding: utf-8 -*-
"""pdf_fetch 自测：纯离线。

**这块的主体逻辑在别人家的浏览器里跑，本机验不了** —— 所以这里只验
「不碰浏览器也必须成立」的那部分：模块在没装 playwright 的机器上也能 import、
DOI 长相判断、PDF 魔数识别、reason 表跟代码没走散。

浏览器那半只能在真机上验：`python -m tools.getpdf --probe`。
"""
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.adapters import pdf_fetch


def main():
    ok = total = 0

    total += 1
    if pdf_fetch.cdp_url().startswith('http'):
        print(f'  [PASS] 调试口地址可取：{pdf_fetch.cdp_url()}'); ok += 1
    else:
        print(f'  [FAIL] 调试口地址不像话：{pdf_fetch.cdp_url()}')

    total += 1
    good = ['10.1016/j.cej.2025.164092', '10.1002/adma.202100000']
    bad = ['', 'not a doi', 'https://doi.org/10.1016/x', '10.1/x']
    if all(pdf_fetch.is_doi(d) for d in good) and not any(pdf_fetch.is_doi(d) for d in bad):
        print('  [PASS] DOI 长相判断'); ok += 1
    else:
        print('  [FAIL] DOI 判断把好的漏了或把坏的放了')

    total += 1
    # 魔数比 MIME 可信：出版商常把 Content-Type 写成 octet-stream
    if (pdf_fetch._looks_like_pdf(b'%PDF', 'application/octet-stream')
            and pdf_fetch._looks_like_pdf(b'\x00\x00\x00\x00', 'application/pdf')
            and not pdf_fetch._looks_like_pdf(b'<!DO', 'text/html')):
        print('  [PASS] PDF 识别：魔数优先，MIME 兜底，HTML 认得出'); ok += 1
    else:
        print('  [FAIL] PDF 识别不对')

    total += 1
    import base64
    # _decode 是两趟取字节共用的收尾。它松一点，SI 就会冒充正文（2026-09-05 中过）
    pdf_ok = {'ok': True, 'type': 'application/pdf',
              'b64': base64.b64encode(b'%PDF-1.7 x').decode()}
    html = {'ok': True, 'type': 'text/html',
            'b64': base64.b64encode(b'<!doctype html>').decode()}
    if (pdf_fetch._decode(pdf_ok) == b'%PDF-1.7 x'
            and pdf_fetch._decode(html) is None
            and pdf_fetch._decode({'ok': False}) is None
            and pdf_fetch._decode(None) is None):
        print('  [PASS] 取回来的东西不是 PDF 就当没拿到'); ok += 1
    else:
        print('  [FAIL] _decode 放行了不该放的东西')

    total += 1
    # 补充材料必须在候选阶段就被滤掉 —— 这是最阴的一种错：
    # 文件下来了、格式也对，内容却是 SI 不是正文
    js = pdf_fetch._JS_STATE
    if all(w in js for w in ('downloadSupplement', 'suppl_file', 'SuppMat')):
        print('  [PASS] 候选里排除了补充材料的链接'); ok += 1
    else:
        print('  [FAIL] 没有排除补充材料，SI 会冒充正文')

    total += 1
    # reason 表和代码走散过一次就再也对不上了 —— 让自测盯着
    used = {'ok', 'captcha', 'no_access', 'no_pdf_link',
            'not_pdf', 'too_big', 'navigate_failed', 'no_si'}
    if used == set(pdf_fetch.REASONS):
        print(f'  [PASS] reason 表与代码一致（{len(used)} 种）'); ok += 1
    else:
        print(f'  [FAIL] reason 对不上：表里多了 {set(pdf_fetch.REASONS) - used}，'
              f'代码里多了 {used - set(pdf_fetch.REASONS)}')

    total += 1
    # 没装 playwright 的机器（比如编程端）必须给人话，不是 ImportError
    if pdf_fetch.is_available():
        print('  [PASS] 本机装了 playwright'); ok += 1
    else:
        try:
            pdf_fetch.fetch('10.1016/x')
            print('  [FAIL] 没装 playwright 却没拦住')
        except pdf_fetch.PlaywrightMissing as e:
            print(f'  [PASS] 没装 playwright，给的是人话：{str(e)[:30]}…'); ok += 1
        except Exception as e:
            print(f'  [FAIL] 抛的不是 PlaywrightMissing，是 {type(e).__name__}')

    total += 1
    # SI 要按**类型**挑，不是按顺序取第一个（2026-09-06 实测：Wiley 的正文 SI
    # 和演示视频编号都是 sup-0001，按序号排根本分不开）。这两组是真机抓的数据。
    els = [{'url': 'x/1-s2.0-S1385894725049277-mmc1.docx',
            'text': 'Download: Download Word document (12MB)'},
           {'url': 'x/mmc2.mp4', 'text': 'Download: Download video (7MB)'}]
    wil = [{'url': 'x/downloadSupplement?a=1',
            'text': 'adfm202009017-sup-0001-SuppMat.pdf'},
           {'url': 'x/downloadSupplement?a=2',
            'text': 'adfm202009017-sup-0001-MovieS1.mp4'}]
    if (pdf_fetch.pick_si(els)['url'].endswith('mmc1.docx')
            and pdf_fetch.pick_si(wil)['text'].endswith('SuppMat.pdf')
            and pdf_fetch.pick_si([{'url': 'a.mp4', 'text': 'video'}]) is None
            and pdf_fetch.pick_si([]) is None):
        print('  [PASS] SI 挑得对：要文档不要视频（拿真机数据验的）'); ok += 1
    else:
        print('  [FAIL] SI 挑错了 —— 会把演示视频当成实验数据下回来')

    total += 1
    # SI 允许 docx（库里实测 19 pdf + 13 docx，docx 占四成），
    # 但**永远不许**放行 HTML —— 那是被挡回登录页/验证页的样子
    docx = {'ok': True,
            'type': 'application/vnd.openxmlformats-officedocument'
                    '.wordprocessingml.document',
            'b64': base64.b64encode(b'PKrest').decode()}
    htm = {'ok': True, 'type': 'text/html',
           'b64': base64.b64encode(b'<!doctype html>').decode()}
    if (pdf_fetch._decode(docx, 'si') is not None
            and pdf_fetch._decode(docx, 'pdf') is None
            and pdf_fetch._decode(htm, 'si') is None):
        print('  [PASS] SI 收 docx、正文只收 PDF、两者都不收 HTML'); ok += 1
    else:
        print('  [FAIL] SI/正文的格式判断不对')

    print(f'\n{ok}/{total} 通过')
    sys.exit(0 if ok == total else 1)


if __name__ == '__main__':
    main()
