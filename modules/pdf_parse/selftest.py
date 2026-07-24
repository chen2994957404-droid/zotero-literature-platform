# -*- coding: utf-8 -*-
"""pdf_parse 自测：不实际调 MineRU（省额度），只验证接口契约正确。
用法: python modules/pdf_parse/selftest.py
"""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from modules.pdf_parse import parse_pdf, is_parsed, PDFParseError

def main():
    ok = 0; total = 3

    # 1. is_parsed 对空目录应为 False，有 layout.json 应为 True
    with tempfile.TemporaryDirectory() as d:
        if not is_parsed(d):
            print('  [PASS] is_parsed 空目录=False'); ok += 1
        else:
            print('  [FAIL] is_parsed 空目录应为 False')
        open(os.path.join(d, 'layout.json'), 'w').write('{}')
        if is_parsed(d):
            print('  [PASS] is_parsed 有layout.json=True'); ok += 1
        else:
            print('  [FAIL] is_parsed 有layout.json应为 True')

    # 2. 缺 MINERU_TOKEN 时，parse_pdf 对未解析目录应正确报错（而非崩溃）
    old = os.environ.pop('MINERU_TOKEN', None)
    try:
        with tempfile.TemporaryDirectory() as d:
            try:
                parse_pdf('nonexistent.pdf', d, reuse=False)
                print('  [FAIL] 缺 token 应报 PDFParseError')
            except PDFParseError:
                print('  [PASS] 缺 token 正确报 PDFParseError'); ok += 1
            except Exception as e:
                print(f'  [FAIL] 报了非预期异常: {type(e).__name__}')
    finally:
        if old:
            os.environ['MINERU_TOKEN'] = old

    print(f'\n{ok}/{total} 通过')
    sys.exit(0 if ok == total else 1)

if __name__ == '__main__':
    main()
