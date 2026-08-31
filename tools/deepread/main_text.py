# -*- coding: utf-8 -*-
"""正文精读这一步：解析目录 → 中文图文精读 HTML。

原来是 `文献精读/deepread_v4.py` 的 `main()`，被 watcher 用 subprocess 拉起来，
接口是「参数的先后顺序」。搬进来之后它是一个可以直接调、可以直接测的函数。

**行为与 deepread_v4 完全一致**，只做了一处去重：裁图不再在这里重写一遍，
改调 `shared.domain.figure_crop`（两边算法与阈值本来就逐字相同，见宪法铁律 1）。

流程（顺序即数据流，别打乱）：
    元数据 → 裁完整 Figure → 拼 LLM 输入 → 调模型 → 确定性插图 → 渲染 HTML
"""
import json
import os
import re
import time

from shared.adapters.llm_client import chat as _chat
from shared.domain.figure_crop import crop_figures

# 提示词版本：改了 _sys_prompt_v2.txt 的范式就 +1。
# 状态库据此回答「哪些精读该重跑」（jobs.stale('main_summary', prompt_ver=3)）。
PROMPT_VER = 2
PRODUCER = 'deepread_v4'

MIN_OK = 3000   # 精读正文低于这个字数就是废品，不许静默写盘

_PROMPT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            '_sys_prompt_v2.txt')


class DeepreadFailed(Exception):
    """这一步没能产出合格的精读。调用方据此决定「别标成已精读」。"""


def sys_prompt():
    return open(_PROMPT_FILE, encoding='utf-8').read()


def _pick(mo_dir, suffix, what):
    """解析结果不全时要说清缺什么。

    原来直接取 [0]，缺文件就抛裸 IndexError，调用方只能把
    「list index out of range」写进日志，看不出是 MineRU 没出全。
    """
    try:
        names = sorted(f for f in os.listdir(mo_dir) if f.endswith(suffix))
    except OSError as e:
        raise DeepreadFailed(f'读不到解析目录 {mo_dir}：{e}')
    if not names:
        raise DeepreadFailed(
            f'解析结果不完整：{mo_dir} 里没有{what}（*{suffix}）'
            f'—— 多半是 MineRU 解析失败或没解析完，删掉该目录重跑即可')
    return names[0]


def read_metadata(md, title=None, doi=None):
    """从解析出的 Markdown 里抓标题 / 作者 / DOI。纯文本处理，无 I/O。

    `title` / `doi` 是**调用方给的权威值**（来自 Zotero 条目）：给了就用它，
    只有没给时才去正文里猜。正则抓 DOI 在很多期刊的版式上抓不到，
    抓不到就空着 —— 精读的「文献信息」栏会因此缺 DOI，
    而这个信息编排层本来就有（与踩坑 #64 同一类错误：**有权威源就别猜**）。
    """
    def grab(pat, d=''):
        m = re.search(pat, md, re.M)
        return m.group(1).strip() if m else d

    title_en = title or grab(r'^#\s+(.+)$')
    doi = doi or grab(r'(10\.\d{4,}/[^\s)]+)')
    authors = ''
    mt = re.search(r'#\s+.+\n+(.+)', md)
    if mt and 'images/' not in mt.group(1):
        authors = re.sub(r'\$\^?\{?\*?\}?\$|\*', '', mt.group(1)).strip()
    return title_en, authors, doi


def build_llm_input(title_en, authors, doi, figs, md, limit=150000):
    """拼给模型看的输入。图只给题注，图片本身不喂（省钱且模型也用不上）。"""
    body_txt = re.sub(r'!\[\]\(images/[^)]+\)', '', md)
    s = (f'标题: {title_en}\n作者: {authors}\nDOI: {doi}\n\n'
         f'本文共有 {len(figs)} 张图，题注：\n')
    for i, fg in enumerate(figs, 1):
        s += f"【图{i}】{fg['caption'][:120]}\n"
    s += '\n请在讨论部分按顺序用【图N】标记每张图插入位置。\n\n正文:\n' + body_txt
    # V4 上下文 1M token，正文（约 3~6 万字符）完全放得下，不必粗暴截断。
    # 这个上限只为防解析异常产出的巨型垃圾文本。
    return s[:limit]


def insert_figures(content, figs):
    """确定性插图：模型只负责说「图放这儿」，图是脚本插的，不经过模型。"""
    used = set()

    def repl(m):
        n = int(m.group(1))
        used.add(n)
        return f'\n<img src="{figs[n-1]["b64"]}">\n' if 1 <= n <= len(figs) else ''

    content = re.sub(r'【图(\d+)】', repl, content)
    missing = [i for i in range(1, len(figs) + 1) if i not in used]
    if missing:
        add = ''.join(f'\n<img src="{figs[i-1]["b64"]}">\n' for i in missing)
        content = (content.replace('## 总结', '（补充图）' + add + '\n## 总结', 1)
                   if '## 总结' in content else content + add)
    return content


CSS = ('body{max-width:820px;margin:0 auto;padding:24px;font-family:-apple-system,'
       '"Microsoft YaHei",sans-serif;line-height:1.85;color:#222;background:#fafafa}'
       'h2.section{background:linear-gradient(90deg,#7b9cf0,#a78bde);color:#fff;'
       'padding:8px 20px;border-radius:20px;display:inline-block;font-size:19px;'
       'margin:34px 0 16px}h3{color:#5a6ec0;font-size:16px;margin-top:22px}'
       'p{margin:12px 0;text-align:justify}img{max-width:100%;display:block;'
       'margin:18px auto;border:1px solid #eee;border-radius:6px;'
       'box-shadow:0 2px 8px rgba(0,0,0,.06)}strong{color:#c0392b}')


def render_html(content):
    """Markdown 式内容 → HTML。纯字符串处理。"""
    out = []
    for ln in content.split('\n'):
        s = ln.strip()
        if s.startswith('<img'):
            out.append(s)
            continue
        if s.startswith('## '):
            out.append(f'<h2 class="section">{s[3:].strip()}</h2>')
            continue
        if s.startswith('### '):
            out.append(f'<h3>{s[4:].strip()}</h3>')
            continue
        s = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', s)
        if s:
            out.append(f'<p>{s}</p>')
    return ('<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">'
            f'<title>文献精读</title><style>{CSS}</style></head><body>'
            + '\n'.join(out) + '</body></html>')


def read_main(parsed_dir, out_html, provider='deepseek', model='deepseek-v4-flash',
              key='', log=print, title=None, doi=None):
    """跑完整的一篇正文精读，写出 out_html，返回它的路径。

    失败一律抛 `DeepreadFailed` —— **宁可不产出，也不产出「只有图没有字」的
    废品精读**（否则它会被标成已精读、以后不再重跑）。
    """
    mdf = _pick(parsed_dir, '.md', 'Markdown 正文')
    layf = os.path.join(parsed_dir, 'layout.json')
    if not os.path.exists(layf):
        raise DeepreadFailed(
            f'解析结果不完整：{parsed_dir} 里没有 layout.json（版面数据）'
            f'—— 多半是 MineRU 解析失败或没解析完，删掉该目录重跑即可')
    _pick(parsed_dir, 'origin.pdf', '原始 PDF')     # 只为把缺失说清楚，裁图自己会再找

    md = open(os.path.join(parsed_dir, mdf), encoding='utf-8').read()
    json.load(open(layf, encoding='utf-8'))          # 提前炸出坏 layout.json

    title_en, authors, doi = read_metadata(md, title=title, doi=doi)
    figs = crop_figures(parsed_dir)
    log(f'元数据 title={title_en[:35]} doi={doi}')
    log(f'裁出 {len(figs)} 张完整图')

    llm_input = build_llm_input(title_en, authors, doi, figs, md)
    SYS = sys_prompt()

    t0 = time.time()
    content = ''
    # 两次尝试：先关思考 + 3.2 万额度（快且省）；不够则开思考 + 6.4 万额度（更强）
    for attempt, (mt, think) in enumerate([(32000, False), (64000, True)], 1):
        try:
            raw = _chat(SYS, llm_input, provider=provider, model=model, key=key,
                        temperature=0.3, max_tokens=mt, thinking=think)
            content = re.sub(r'<think>[\s\S]*?</think>', '', raw).strip()
        except Exception as e:
            log(f'  第{attempt}次调用失败: {e}')
            content = ''
        if len(content) >= MIN_OK:
            break
        log(f'  第{attempt}次输出仅 {len(content)} 字（<{MIN_OK}），重试更大额度…')
    log(f'LLM {round(time.time()-t0,1)}s 输出{len(content)}字')
    if len(content) < MIN_OK:
        raise DeepreadFailed(
            f'LLM 正文仅 {len(content)} 字，判定失败，不写盘。请检查模型/额度。')

    html = render_html(insert_figures(content, figs))
    d = os.path.dirname(out_html)
    if d:
        os.makedirs(d, exist_ok=True)
    open(out_html, 'w', encoding='utf-8').write(html)
    log(f'WROTE {out_html} {round(len(html)/1024)} KB 插图 {html.count("<img")}')
    return out_html
