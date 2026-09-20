# -*- coding: utf-8 -*-
"""pdf_parse 自测：不实际调 MineRU（省额度），只验证接口契约正确。
用法: python shared/adapters/pdf_parse/selftest.py
"""
import sys, os, tempfile
from shared.adapters.pdf_parse import parse_pdf, parse_document, is_parsed, PDFParseError

def main():
    ok = 0; total = 5

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
    #    注：安全化后 _token() 会回退到 shared.kernel.config 读 .env，这是期望行为，
    #    所以测"能拿到 token"；真的没有时才验证报错（且错误信息要有修复指引）。
    from shared.adapters.pdf_parse import _token
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

    # 3. parse_document 按扩展名分派：不认识的扩展名要报错，不能静默跑到 MineRU 去
    with tempfile.TemporaryDirectory() as d:
        try:
            parse_document(os.path.join(d, 'x.txt'), d)
            print('  [FAIL] .txt 应当报错')
        except PDFParseError as e:
            if '.pdf' in str(e) and '.docx' in str(e):
                print('  [PASS] parse_document 拒绝未知扩展名并说明只认 pdf/docx'); ok += 1
            else:
                print('  [FAIL] 报错没说清只认什么')

    # 4. real_ext 看文件头不看扩展名：.docx 名字装着 PDF 要认成 .pdf（#181）
    from shared.adapters.pdf_parse import real_ext
    with tempfile.TemporaryDirectory() as d:
        fake = os.path.join(d, 'si.docx')
        open(fake, 'wb').write(b'%PDF-1.7 rest')
        if (real_ext(fake, '.docx') == '.pdf' and real_ext(b'PK\x03\x04xx', '.pdf') == '.docx'
                and real_ext(b'??', '.txt') == '.txt'):
            print('  [PASS] real_ext 按文件头判 pdf/docx，认不出退回兜底'); ok += 1
        else:
            print('  [FAIL] real_ext 判错')

    print(f'\n{ok}/{total} 通过')
    sys.exit(0 if ok == total else 1)

if __name__ == '__main__':
    main()
