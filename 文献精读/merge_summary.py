# -*- coding: utf-8 -*-
"""把正文精读 + SI 实验细节精读合并成一份 HTML，并回写 Zotero。

设计（用户定，2026-07-25）：
  - **生成独立**：正文精读(deepread_v4) 与 SI 精读(si_deepread) 各自单独生成、互不影响。
    好处：后补 SI 时不必重跑正文精读；SI 后到也能随时补。
  - **展示合并**：最后拼成一份文档（正文在前、SI 在后），Zotero 里一个附件看全。

用法：
  python merge_summary.py <ZoteroKey>            # 合并并回写 Zotero
  python merge_summary.py <ZoteroKey> --no-upload  # 只生成不回写
"""
import os, sys, re, io

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
from core import paths
from core.paths import ROOT as _ROOT

from modules.cli import pos, flag

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)     # 同文件夹脚本互相 import（upload_summaries 等）
ROOT = _ROOT
LIBRARY = paths.LIBRARY


def _body_of(html):
    """取出 <body> 内部内容（去掉 html/head/style 外壳）。"""
    m = re.search(r'<body[^>]*>(.*)</body>', html, re.S | re.I)
    return m.group(1) if m else html


def _style_of(html):
    m = re.search(r'<style>(.*?)</style>', html, re.S | re.I)
    return m.group(1) if m else ''


def merge(key, upload=True):
    d = os.path.join(LIBRARY, key)
    main_p = os.path.join(d, 'summary.html')
    si_p = os.path.join(d, 'si_summary.html')
    if not os.path.exists(main_p):
        print(f'[跳过] {key} 无正文精读 summary.html'); return None
    main = io.open(main_p, encoding='utf-8').read()
    if not os.path.exists(si_p):
        print(f'[提示] {key} 无 SI 精读，无需合并'); return main_p

    si = io.open(si_p, encoding='utf-8').read()
    # 样式取正文的（主），SI 的分隔样式补充进去
    css = _style_of(main) + '\n' + (
        '.si-divider{margin:48px 0 8px;padding:14px 20px;background:linear-gradient(90deg,#e8934a,#d4703a);'
        'color:#fff;border-radius:10px;font-size:20px;font-weight:bold;text-align:center}'
        '.si-note{color:#8a6d3b;background:#fcf8e3;border-left:4px solid #e8934a;padding:10px 14px;'
        'margin:12px 0;border-radius:4px;font-size:14px}')
    merged = (f'<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">'
              f'<title>文献精读（含SI实验细节）</title><style>{css}</style></head><body>'
              + _body_of(main)
              + '<div class="si-divider">补充材料（SI）· 实验细节精读</div>'
              + '<div class="si-note">以下内容来自本文的补充材料（Supporting Information），'
                '聚焦「复现实验」所需的原料规格、精确投料、反应条件与对照组设计。</div>'
              + _body_of(si)
              + '</body></html>')
    out = os.path.join(d, 'summary_full.html')
    io.open(out, 'w', encoding='utf-8').write(merged)
    print(f'[合并完成] {out}  {round(os.path.getsize(out)/1024/1024,1)} MB')

    if upload:
        try:
            from upload_summaries import do_one_file
            do_one_file(key, out, 'summary')
        except ImportError:
            # upload_summaries 没有该函数则走通用逻辑
            import upload_summaries as us
            orig = os.path.join(d, 'summary.html')
            bak = orig + '.orig'
            os.replace(orig, bak)          # 临时把合并版当作 summary 上传
            os.replace(out, orig)
            try:
                us.do_one(key)
            finally:
                os.replace(orig, out)
                os.replace(bak, orig)
            print('[已回写 Zotero] 附件 summary（合并版）')
    return out


def main():
    key = pos(0)
    if not key:
        print('用法: python merge_summary.py <ZoteroKey> [--no-upload]'); sys.exit(1)
    merge(key, upload=not flag('--no-upload'))


if __name__ == '__main__':
    main()
