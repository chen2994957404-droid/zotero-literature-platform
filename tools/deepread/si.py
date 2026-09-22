# -*- coding: utf-8 -*-
"""SI（补充材料）精读这一步：SI 附件 → 「实验细节精读」HTML。

原来是 `文献精读/si_deepread.py` 的 `main()`，被 watcher 用 subprocess 拉起来。
搬进来之后是一个能直接调、能直接测的函数，行为不变。

定位（与正文精读的分工，用户 2026-07-25 定）：
    正文精读 = 理解这篇做了什么；SI 精读 = 我要复现时查参数。
SI 里有正文完全没有的可复现细节：精确投料量、原料分子量、溶剂配比、对照组设计逻辑。
"""
import base64
import io
import os
import re
import zipfile

from shared.adapters.llm_client import chat
from shared.adapters.pdf_parse import parse_document, PDFParseError
from shared.adapters.zotero_client import find_si
from shared.kernel import paths, prompts
from shared.kernel.config import get_key
from shared.domain.figure_crop import crop_figures
from tools.deepread import si_slices
from shared.domain import numcheck

# 提示词版本：改范式 = 新建 prompts/si_<栏>_v<N+1>.txt，再把这里 +1（提示词只增不改）。
# v4（2026-09-22）：拆成四栏各调一次（原料 / 逐流程合成 / 表征 / 图表），每次只喂那一栏的材料（≤ 6000 字符）——
#   3 万字符一口气是本地模型做不好的形状，而且 80k 的 SI 直接被截。v3：缩写保持缩写；v2：只许照搬、禁推断；v1 的「复现指南」让本地模型编出整套通用流程
PROMPT_VER = 4
PRODUCER = 'si_deepread'

PROMPTS = {'materials': 'si_materials@v2', 'synthesis': 'si_synthesis@v2', 'methods': 'si_methods@v2', 'figures': 'si_figures@v2'}   # v2：明写「整段用中文」—— v1 试跑三栏整段照抄英文原句
TITLES = {'materials': '【原料与规格】', 'synthesis': '【合成步骤】', 'methods': '【表征与测试条件】', 'figures': '【补充图表要点】'}
EMPTY = {'materials': 'SI 未给出原料规格。', 'synthesis': 'SI 未给出合成细节。', 'methods': 'SI 未给出测试条件。', 'figures': 'SI 没有图表说明。'}


class SIFailed(Exception):
    """SI 这一步没能产出。与「这篇根本没有 SI」是两回事，别混。"""


def find_si_file(item_key):
    """定位 SI 文件 → (路径, 类型)。**本地正本优先**（raw/<id>/si.*），没有再问 Zotero。

    2026-09-13：正本搬到证据库之后，精读不该再只认 Zotero 的附件 ——
    `getpdf` 落地的文献（可能根本不在 Zotero 里）也要能精读。
    Zotero 那一半的查找逻辑下沉到了 `zotero_client.find_si`。
    """
    local = paths.find_local_si(item_key)
    if local:
        return local, os.path.splitext(local)[1].lstrip('.').lower()
    return find_si(item_key)


def extract_docx_images(path, min_kb=15, log=print):
    """取出 .docx 里内嵌的图片（docx 本质是 zip，图在 word/media/）。

    返回 [{b64, caption, num}]，格式与 figure_crop 一致，可直接进渲染流程。
    过滤掉小图标（<min_kb），只留有意义的补充图。
    """
    figs = []
    try:
        with zipfile.ZipFile(path) as z:
            media = sorted(n for n in z.namelist()
                           if n.startswith('word/media/')
                           and n.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')))
            for name in media:
                data = z.read(name)
                if len(data) < min_kb * 1024:      # 滤掉小图标/装饰
                    continue
                ext = name.rsplit('.', 1)[-1].lower()
                mime = 'jpeg' if ext in ('jpg', 'jpeg') else ext
                figs.append({
                    'b64': f'data:image/{mime};base64,' + base64.b64encode(data).decode(),
                    'caption': '', 'num': len(figs) + 1})
    except Exception as e:
        log(f'  （docx 取图失败，跳过：{e}）')
    return figs


CSS = ('body{max-width:820px;margin:0 auto;padding:24px;font-family:-apple-system,'
       '"Microsoft YaHei",sans-serif;line-height:1.85;color:#222;background:#fafafa}'
       'h2.section{background:linear-gradient(90deg,#e8934a,#d4703a);color:#fff;padding:8px 20px;'
       'border-radius:20px;display:inline-block;font-size:19px;margin:34px 0 16px}'
       'h3{color:#c26a35;font-size:16px;margin-top:22px}p{margin:12px 0;text-align:justify}'
       'img{max-width:100%;display:block;margin:18px auto;border:1px solid #eee;'
       'border-radius:6px;box-shadow:0 2px 8px rgba(0,0,0,.06)}strong{color:#c0392b}')


def render_html(content, figs, title=''):
    """把 Markdown 式内容 + 图渲染成 HTML（复用精读线的确定性插图思路）。"""
    used = set()

    def repl(m):
        n = int(m.group(1))
        used.add(n)
        return f'\n<img src="{figs[n-1]["b64"]}">\n' if 1 <= n <= len(figs) else ''

    content = re.sub(r'【图(\d+)】', repl, content)
    missing = [i for i in range(1, len(figs) + 1) if i not in used]
    if missing:
        content += '\n\n（其余补充图）\n' + ''.join(
            f'\n<img src="{figs[i-1]["b64"]}">\n' for i in missing)
    out = []
    for ln in content.split('\n'):
        s = ln.strip()
        if s.startswith('<img'):
            out.append(s)
            continue
        s = re.sub(r'^#{4,6}\s*', '', s)
        if s.startswith('### '):
            out.append(f'<h3>{s[4:].strip()}</h3>')
            continue
        if s.startswith('## '):
            out.append(f'<h2 class="section">{s[3:].strip()}</h2>')
            continue
        if s.startswith('# '):
            out.append(f'<h2 class="section">{s[2:].strip()}</h2>')
            continue
        s = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', s)
        s = re.sub(r'^[-*]\s+', '· ', s)
        if s:
            out.append(f'<p>{s}</p>')
    return ('<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">'
            f'<title>SI实验细节精读</title><style>{CSS}</style></head><body>'
            '<h2 class="section">补充材料（SI）· 实验细节精读</h2>'
            + '\n'.join(out) + '</body></html>')


MIN_OK = 300        # SI 精读低于这个字数基本是废品。v2 起 SI 短的（只有几张图注）产出本来就短，下限从 800 降到 300

# 搪塞词：出现就说明模型在编「通用流程」而不是照搬 SI（2026-09-18 抽检三篇本地精读，SI 段两篇整段是编的：
# 「通常在碱性条件下」「光气法或 MDI 法」「需依据主文配方」—— 全是 SI 里没有的话）。
_HEDGE = re.compile(r'通常|一般(?:来说|而言|为)|建议|需(?:依据|参考|查阅|根据)|可选|根据经验|推断|标准操作|复现指南|隐含')

# 额度阶梯：**V4 的推理链计入 max_tokens**，给少了会「输出被截断且正文近乎为空」。
# 正文线早就是 32000 起 + 重试（实测教训教训第 1 条），SI 线却一直是 6000 ——
# 于是同一篇有时成、有时败，看起来像玄学。2026-08-27 真实撞上一次才发现。
_BUDGETS = (16000, 32000)


def problems(text, source):
    """这份 SI 段哪里不对：搪塞词（在编通用流程）/ 原文找不到的数。空列表 = 合格。"""
    out = []
    hedges = sorted(set(_HEDGE.findall(text or '')))
    if hedges:
        out.append('用了搪塞词 %s —— 这些话 SI 里没有，说明在编。只写 SI 明确写了的' % '、'.join(hedges[:5]))
    bad = numcheck.unverified_numbers(text or '', source)
    if bad:
        out.append('这些数 SI 里找不到：%s，删掉或改成 SI 的原话' % '、'.join(bad[:8]))
    return out


MIN_PART = 40       # 一块材料的产出低于这个字数当没写
_CJK = re.compile(r'[一-鿿]')


_EN_FUNC = re.compile(r'\b(the|was|were|and|of|with|to|at|for|in|is|are|by|from|using|into|under|after|as|on|or|that|then)\b', re.I)


def _mostly_english(text):
    """整段照抄了英文（v1 试跑三栏都这样）：英文虚词密度高 + 汉字少。
    不能只看汉字比例 —— 原料栏满是化学品名，中文写法也一半拉丁字母；虚词（the / was / were）才是「英文句子」的标志。"""
    letters = re.sub(r'[\s\d\W]', '', text or '')
    if len(letters) <= 40:
        return False
    cjk = len(_CJK.findall(letters)) / len(letters)
    func = len(_EN_FUNC.findall(text)) / max(1, len(text) / 100)      # 每百字符的英文虚词数
    return cjk < 0.5 and func >= 2


def _call_llm(sysp, user, model, log=print, source='', what='SI'):
    """调一块 → 查（字数 / 搪塞词 / 编数 / 漏数）→ 不合格带着原因重来，最多三次。三次都不干净就交最后一稿（调用方统计）。

    与正文分栏同一套纪律（`sectioned._with_fix`）。SI 段以前只查字数，本地模型写出整段「通用复现流程」照样过关。
    """
    must = numcheck.must_numbers(source, cap=40)
    note, last = '', ''
    for i in range(1, 4):
        budget = _BUDGETS[min(i, len(_BUDGETS)) - 1]
        try:
            # num_ctx 只对本地 Ollama 起作用：一块 ≤ 6000 字符 + 几千字输出，16k 够，给 24k 留余量（踩坑 #43）。
            out = chat(sysp, user + note, purpose='DEEPREAD', model=model,
                       temperature=0.3, max_tokens=budget, num_ctx=24576, thinking=False)
        except Exception as e:
            log(f'  {what} 第{i}次调用失败（额度 {budget}）：{str(e)[:120]}')
            continue
        out = re.sub(r'<think>[\s\S]*?</think>', '', out or '').strip()
        if len(out) < MIN_PART:
            if '未给出' in out or '没有' in out:        # 这块材料本来就没东西（脚注 / 坐标轴标签之类切进来的），模型如实说了，不算失败
                return ''
            log(f'  {what} 第{i}次输出仅 {len(out)} 字，重试…')
            continue
        probs = problems(out, source)
        if _mostly_english(out):
            probs.insert(0, '整段是英文 —— 全部用中文重写，只保留化学品名 / 缩写 / 仪器型号的英文')
        miss = numcheck.missing_numbers(out, must) if must else []
        if len(miss) > 0.25 * len(must):
            probs.append('漏了材料里的这些数：%s，把它们写进对应的句子里（带单位、带对象）' % '、'.join(miss[:12]))
        if not probs:
            return out
        last = out
        log(f'  {what} 第{i}次不合格：{probs[0][:60]}…，带着原因重写')
        note = '\n\n⚠ 上一稿的问题：' + '；'.join(probs) + '。其余保持不变，按同样格式重写。'
    return last


def compose(body, model, log=print, n_figs=0):
    """SI 全文 → 四栏（原料 / 合成 / 表征 / 图表）。每栏按 si_slices 切出的块逐块调模型，块与块的产出拼起来。

    返回 (四栏拼成的正文, 统计)。四栏全空（连图表都没有）才算失败。
    """
    parts = si_slices.slice(body)
    out, st = [], {'calls': 0, 'empty': [], 'failed': []}
    for kind in ('materials', 'synthesis', 'methods', 'figures'):
        blocks = parts.get(kind) or []
        if kind == 'figures' and parts.get('other'):
            blocks = blocks + [('补充讨论', t) for _, t in parts['other']]
        sysp = prompts.load('deepread', PROMPTS[kind])
        texts = []
        for j, (h, t) in enumerate(blocks, 1):
            user = ('SI 这部分文字（%s%s）：\n\n%s' % (TITLES[kind], ('，' + h) if h else '', t))
            if kind == 'figures' and n_figs:
                user = f'补充材料共有 {n_figs} 张图。\n\n' + user
            st['calls'] += 1
            got = _call_llm(sysp, user, model, log, source=t, what='%s %d/%d' % (TITLES[kind], j, len(blocks)))
            if got:
                texts.append(got)
            else:
                st['failed'].append('%s#%d' % (kind, j))
        if not texts:
            st['empty'].append(kind)
        out.append(TITLES[kind] + '\n' + ('\n\n'.join(texts) if texts else EMPTY[kind]))
        log('  %s：%d 块 → %d 字' % (TITLES[kind], len(blocks), sum(len(x) for x in texts)))
    if len(st['empty']) == 4:
        raise SIFailed('SI 四栏全空（切不出材料或模型三次都没通过校验），不写盘')
    return '\n\n'.join(out), st


def read_si(key, out_html=None, model=None, log=print):
    """跑一篇的 SI 精读。

    返回产物路径；**这篇根本没有 SI 附件时返回 None**（不是失败，别当失败记）。
    真出了问题抛 `SIFailed`。
    """
    key = paths.check_key(key)
    out_html = out_html or paths.si_summary(key)
    model = model or None          # None = 路由表定（2026-09-17 起精读走本地时，SI 线跟着走）

    si_file, kind = find_si_file(key)
    if not si_file:
        log(f'[跳过] {key} 没有 SI 附件')
        return None
    log(f'[SI] {os.path.basename(si_file)} ({kind})')

    parsed = paths.si_parsed_dir(key)
    # 解析（pdf 走 MineRU、docx 直接读字）只有适配层一份实现；落地流水线多半已经做过，这里直接复用
    try:
        parse_document(si_file, parsed)
    except PDFParseError as e:
        raise SIFailed(f'SI 解析失败：{e}')
    md = paths.si_fulltext(key)
    if not os.path.exists(md):
        raise SIFailed('SI 解析未生成 full.md')
    raw = io.open(md, encoding='utf-8').read()
    if kind == 'pdf':
        figs = crop_figures(parsed)
    else:                                   # docx：图不在版面里，从 zip 里取内嵌图片
        figs = extract_docx_images(si_file, log=log)
        log(f'  docx 读出 {len(raw)} 字符（含表格），取出内嵌图 {len(figs)} 张')

    log(f'  SI 原文 {len(raw)} 字符，补充图 {len(figs)} 张')
    content, st = compose(raw, model, log, n_figs=len(figs))
    log('  SI 四栏共调用 %d 次%s' % (st['calls'], ('，没写出来的块：' + '、'.join(st['failed'])) if st['failed'] else ''))
    os.makedirs(os.path.dirname(out_html), exist_ok=True)
    io.open(out_html, 'w', encoding='utf-8').write(render_html(content, figs))
    log(f'  [完成] {out_html}  {round(os.path.getsize(out_html)/1024)} KB')
    return out_html
