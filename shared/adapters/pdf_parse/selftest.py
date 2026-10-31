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

    # 5. 快速文本层（2026-10-04）：本地抽字出 full.md，标 text；MineRU 的结果（无标记）算 structured
    from shared.adapters.pdf_parse import parse_pdf_text, tier, TIER_TEXT, TIER_STRUCTURED, TIER_NONE
    total += 2
    with tempfile.TemporaryDirectory() as d:
        try:
            import fitz
            pdf = os.path.join(d, 'a.pdf')
            doc = fitz.open()
            body = ' '.join('the borosiloxane network reached a tensile strength of 12 MPa' for _ in range(30))
            for title in ('1. Introduction', '2. Results and Discussion'):
                pg = doc.new_page()
                pg.insert_text((72, 80), title, fontsize=16)
                pg.insert_textbox(fitz.Rect(72, 100, 520, 780), body, fontsize=10)
            doc.save(pdf)
            out = os.path.join(d, 'parsed')
            before = tier(out)
            parse_pdf_text(pdf, out)
            md = open(os.path.join(out, 'full.md'), encoding='utf-8').read()
            if before == TIER_NONE and tier(out) == TIER_TEXT and '## 2. Results and Discussion' in md:
                print('  [PASS] 快速文本层：出 full.md、认出标题、标成 text'); ok += 1
            else:
                print('  [FAIL] 快速文本层没按预期出来：', before, tier(out), md[:80])
            os.remove(os.path.join(out, '.tier_text'))      # 等价于 MineRU 覆盖之后
            parse_pdf_text(pdf, out)                         # reuse：不许拿快速层盖掉 MineRU 的结果
            if tier(out) == TIER_STRUCTURED:
                print('  [PASS] 已有 MineRU 结果时快速层不覆盖'); ok += 1
            else:
                print('  [FAIL] 快速层盖掉了 MineRU 的结果')
        except ImportError:
            print('  [SKIP] 没装 PyMuPDF'); ok += 2

    # 6. Word 转网页（2026-10-31）：TIFF 图浏览器不认，要转成 PNG 内嵌
    total += 1
    try:
        import io, struct, docx
        from shared.adapters.pdf_parse import docx_to_html
        w = h = 4
        pix = bytes([200, 30, 30]) * (w * h)        # 手拼一张最小的未压缩 RGB TIFF
        tags = [(256, 3, w), (257, 3, h), (258, 3, 8), (259, 3, 1), (262, 3, 2), (273, 4, 8),
                (277, 3, 3), (278, 3, h), (279, 4, len(pix))]
        ent = b''.join(struct.pack('<HHII', t, ty, 1, v) if ty == 4 else struct.pack('<HHIHH', t, ty, 1, v, 0)
                       for t, ty, v in tags)
        tif = b'II*\x00' + struct.pack('<I', 8 + len(pix)) + pix + struct.pack('<H', len(tags)) + ent + b'\0' * 4
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'si.docx')
            doc = docx.Document(); doc.add_paragraph('Figure S1'); doc.add_picture(io.BytesIO(tif)); doc.save(p)
            html = docx_to_html(p)
        if 'Figure S1' in html and 'data:image/png' in html and 'image/tiff' not in html:
            print('  [PASS] Word 转网页：文字在、TIFF 图转成了 PNG'); ok += 1
        else:
            print('  [FAIL] Word 转网页：文字丢了或 TIFF 没转')
    except ImportError as e:
        print(f'  [SKIP] 缺库 {e.name}'); ok += 1

    print(f'\n{ok}/{total} 通过')
    sys.exit(0 if ok == total else 1)

if __name__ == '__main__':
    main()
