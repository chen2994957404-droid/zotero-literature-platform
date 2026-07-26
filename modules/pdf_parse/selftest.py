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

    # 2. token 获取链路正常（环境变量 或 .env 都能拿到）
    #    注：安全化后 _token() 会回退到 modules.config 读 .env，这是期望行为，
    #    所以测"能拿到 token"；真的没有时才验证报错（且错误信息要有修复指引）。
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    from modules.pdf_parse import _token
    try:
        t = _token()
        if t:
            print('  [PASS] MINERU_TOKEN 链路正常（环境变量或 .env）'); ok += 1
        else:
            print('  [FAIL] token 为空但未报错')
    except PDFParseError as e:
        # 没配 token 也算通过——只要报错信息给出可操作指引
        if '.env' in str(e) or 'MINERU_TOKEN' in str(e):
            print('  [PASS] 无 token 时报错并给出指引'); ok += 1
        else:
            print('  [FAIL] 报错缺少修复指引')

    print(f'\n{ok}/{total} 通过')
    sys.exit(0 if ok == total else 1)

if __name__ == '__main__':
    main()
