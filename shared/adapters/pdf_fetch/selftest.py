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
    # reason 表和代码走散过一次就再也对不上了 —— 让自测盯着
    used = {'ok', 'captcha', 'no_access', 'no_pdf_link',
            'not_pdf', 'too_big', 'navigate_failed'}
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

    print(f'\n{ok}/{total} 通过')
    sys.exit(0 if ok == total else 1)


if __name__ == '__main__':
    main()
