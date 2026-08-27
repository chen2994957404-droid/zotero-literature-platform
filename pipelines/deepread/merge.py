# -*- coding: utf-8 -*-
"""正文精读 + SI 精读 → 一份合并 HTML。

原来是 `文献精读/merge_summary.py` 的 `merge()`，watcher 用 subprocess 拉起来。
搬进来之后是普通函数，行为不变；**回写 Zotero 不在这一步**（那是界面/写回的事，
这一步只管拼文档）。

设计（用户 2026-07-25 定）：
  - **生成独立**：正文精读与 SI 精读各自单独生成、互不影响。
    好处：后补 SI 时不必重跑正文精读；SI 后到也能随时补。
  - **展示合并**：最后拼成一份文档（正文在前、SI 在后），Zotero 里一个附件看全。
"""
import io
import os
import re

from core import paths

SI_CSS = ('.si-divider{margin:48px 0 8px;padding:14px 20px;'
          'background:linear-gradient(90deg,#e8934a,#d4703a);color:#fff;border-radius:10px;'
          'font-size:20px;font-weight:bold;text-align:center}'
          '.si-note{color:#8a6d3b;background:#fcf8e3;border-left:4px solid #e8934a;'
          'padding:10px 14px;margin:12px 0;border-radius:4px;font-size:14px}')


def _body_of(html):
    """取出 <body> 内部内容（去掉 html/head/style 外壳）。"""
    m = re.search(r'<body[^>]*>(.*)</body>', html, re.S | re.I)
    return m.group(1) if m else html


def _style_of(html):
    m = re.search(r'<style>(.*?)</style>', html, re.S | re.I)
    return m.group(1) if m else ''


def merge_html(main_html, si_html):
    """两份 HTML 文本 → 一份。纯字符串处理，可离线测试。"""
    css = _style_of(main_html) + '\n' + SI_CSS
    return ('<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">'
            f'<title>文献精读（含SI实验细节）</title><style>{css}</style></head><body>'
            + _body_of(main_html)
            + '<div class="si-divider">补充材料（SI）· 实验细节精读</div>'
            + '<div class="si-note">以下内容来自本文的补充材料（Supporting Information），'
              '聚焦「复现实验」所需的原料规格、精确投料、反应条件与对照组设计。</div>'
            + _body_of(si_html)
            + '</body></html>')


def merge(key, log=print):
    """合并一篇的正文精读与 SI 精读，返回**最终该展示的那份**的路径。

    没有正文精读 → None；没有 SI → 直接返回正文精读（无需合并，不算失败）。
    """
    key = paths.check_key(key)
    main_p, si_p = paths.summary(key), paths.si_summary(key)
    if not os.path.exists(main_p):
        log(f'[跳过] {key} 无正文精读 summary.html')
        return None
    if not os.path.exists(si_p):
        log(f'[提示] {key} 无 SI 精读，无需合并')
        return main_p

    merged = merge_html(io.open(main_p, encoding='utf-8').read(),
                        io.open(si_p, encoding='utf-8').read())
    out = paths.summary_full(key)
    io.open(out, 'w', encoding='utf-8').write(merged)
    log(f'[合并完成] {out}  {round(os.path.getsize(out)/1024/1024,1)} MB')
    return out
