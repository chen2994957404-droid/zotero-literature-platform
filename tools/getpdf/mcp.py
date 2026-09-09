# -*- coding: utf-8 -*-
"""getpdf 的 MCP 面：一条提示词（整批）+ 一个工具（取一篇，每次弹窗）。

**为什么整批只给 prompt**：取一篇是单次、不花钱、可重来；一整批的量能堆到
触发出版商风控，而被封的是**整个机构的 IP**。这个代价不可逆、也不由本人承担，
所以按 R4 判据留给人点。本文件只做参数转换。
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.adapters import pdf_fetch
from shared.kernel.mcp_prompt import card


def _one(a):
    """取一篇 → 给模型看的文本。

    ⚠ **可能超过 MCP 约 60 秒的调用上限**（出版商页面要等前端渲染完）。
    超时也不要紧：产物照样落盘，而且这一步是幂等的（盘上有了就跳过），
    重调一次几乎没有代价。这句也写进返回文本里 —— 模型看到超时才知道该怎么办。
    """
    from tools import getpdf
    doi = (a.get('doi') or '').strip()
    if not pdf_fetch.is_doi(doi):
        return f'「{doi}」不像一个 DOI（应该形如 10.1016/j.cej.2025.164092）。'

    p = getpdf.probe()
    if not p['ok']:
        return ('浏览器连不上（' + p['cdp'] + '）。取全文要借一个**带调试口启动、'
                '而且里面过过一次人机验证的**浏览器 —— 机构订阅权限和人机验证的通行证'
                '都在它身上。请主人先这样启动它：msedge --remote-debugging-port=9333')

    r = getpdf.fetch_one(doi)
    if r['reason'] == 'exists':
        return f'{doi} 盘上已经有了：{r["path"]}（{r["bytes"] // 1024} KB），没有重下。'
    if r['ok']:
        return (f'拿到了：{r["path"]}（{r["bytes"] // 1024} KB）\n'
                f'  标题：{r["title"][:80]}\n  来源：{r["landing"][:100]}\n'
                f'（如果这次调用超时了，文件多半还是下下来了，重调一次会直接告诉你在哪。）')
    return (f'{doi} 没拿到 —— {pdf_fetch.REASONS.get(r["reason"], r["reason"])}\n'
            f'  落地页：{r["landing"][:100]}')


def _stash_one(a):
    """取一篇 + 收进 Zotero（建条目 / 补齐已有条目、挂 PDF、归合集、打平台标签）。

    **为什么给模型开这条路**（2026-09-09）：本工具包整包是 prompt，模型在 MCP 上
    看不见它。于是当用户让外部 agent「把这几篇收进我的某个文件夹」时，
    它自己去读代码、绕过本流水线直接调了适配层的 `create_items` ——
    建出来的条目元数据是对的，但缺平台标签、缺摘要、没 PDF，对下游整个隐形。
    **堵不住（它能读代码跑命令），所以给正规入口。** 代价用三道闸框住：
    一次一篇、每次强制弹窗、`role.require_prod` 原样保留。
    """
    from tools import getpdf
    doi = (a.get('doi') or '').strip()
    purpose = (a.get('purpose') or '建库').strip()
    if not pdf_fetch.is_doi(doi):
        return f'「{doi}」不像一个 DOI（应该形如 10.1016/j.cej.2025.164092）。'
    if purpose not in getpdf.PURPOSES:
        return f'purpose 只能是 {" / ".join(getpdf.PURPOSES)}，给的是「{purpose}」。'

    p = getpdf.probe()
    r = getpdf.fetch_one(doi) if p['ok'] else {'ok': False, 'reason': 'no_browser', 'path': ''}
    pdf_path = r.get('path') if (r.get('ok') or r.get('reason') == 'exists') else ''

    s = getpdf.stash(doi, pdf_path, purpose=purpose)
    if not s['ok']:
        return f'{doi} 收进库没成：{s["note"]}'
    words = {'created': '新建了条目', 'attached': '条目本来就有，补了 PDF',
             'exists': '条目本来就有'}
    sub, _why = getpdf.PURPOSES[purpose]
    out = (f'{doi} → {words.get(s["action"], s["action"])}（{s["item"]}），'
           f'已归入「{getpdf.collection_top()}/{sub}」')
    if s.get('note'):
        out += f'\n  {s["note"]}'
    if not pdf_path:
        out += ('\n  ⚠ 这次**没有挂 PDF**：' +
                ('浏览器没开（先让主人双击「取全文用的浏览器.bat」），'
                 if not p['ok'] else
                 f'没取到 —— {pdf_fetch.REASONS.get(r.get("reason"), r.get("reason"))}，') +
                '补上之后重调一次本工具即可，已有的不会重建也不会重挂。')
    return out


def register(server):
    """把本工具的 MCP 面挂到 server 上（聚合入口 host/mcp/server.py 会调这个）。"""

    server.register_prompt(
        'getpdf_batch',
        '取一批文献的正文 PDF（借真实浏览器用机构订阅权限；量大有风控风险，所以由人发起）',
        [{'name': 'dois', 'description': '一批 DOI，空格或换行分隔', 'required': True}],
        lambda a: card(
            what='把这些文献的正文 PDF 取到本地',
            cost='要向出版商网站发真实请求 —— 量大会触发风控，'
                 '被封的是整个机构的 IP，代价由全校承担',
            steps=[
                'python -m tools.getpdf --probe',
                'python -m tools.getpdf ' + (a.get('dois') or '<DOI...>'),
            ],
            notes='默认每篇间隔 20 秒、单次最多 25 篇 —— 慢是故意的。\n'
                  '撞上人机验证会停下来等人去点，不会硬跑；'
                  '点过之后重跑同一条命令，已拿到的不会重下。'))

    server.register_tool(
        'getpdf_one', '取一篇文献的正文 PDF（给 DOI）。单次、不花钱、盘上有了会跳过。',
        {'type': 'object',
         'properties': {'doi': {'type': 'string',
                                'description': 'DOI，形如 10.1016/j.cej.2025.164092'}},
         'required': ['doi']},
        lambda a: _one(a),
        confirm=True)      # ← 每次都弹窗，且没有「不再询问」

    server.register_tool(
        'getpdf_stash_one',
        '把**一篇**文献收进用户的 Zotero：取正文 PDF → 建条目（已有就补齐）→ '
        '挂 PDF 附件 → 归入合集 → 打上平台标签。**会写用户的库**，每次调用都要他确认。'
        '一次只收一篇；一整批要走 getpdf_batch 那条人点的路（量大会封整个机构的 IP）。'
        '重调是安全的：条目和附件都不会重复建。',
        {'type': 'object', 'properties': {
            'doi': {'type': 'string',
                    'description': 'DOI，形如 10.1016/j.compositesb.2025.112845'},
            'purpose': {'type': 'string', 'enum': ['建库', '精读'],
                        'description': '建库=只解析向量化（默认）；精读=标成重点文章'}},
         'required': ['doi']},
        lambda a: _stash_one(a),
        confirm=True)      # ← 写库，必须每次弹窗

    # ── 跨付费墙的原子入口（2026-09-08）────────────────────────────
    # 通用 LLM 拿不到付费墙后面的东西。这台机器有三样它没有的：机构订阅权限、
    # 一个过过人机验证的浏览器、MineRU 额度。这两个工具就是把它们接到模型手上。
    server.register_tool(
        'paper_fulltext',
        '给 DOI，拿到 LLM 读得懂的全文（四层回退：缓存→本地→Zotero→去出版商取）。'
        '返回的是 id 与来源，**不是全文** —— 拿到 id 后用 library_outline 看菜单、'
        'library_section 按需取节。默认最多 3 篇；只想看手上有没有就传 allowFetch=false。',
        {'type': 'object', 'properties': {
            'dois': {'type': 'array', 'items': {'type': 'string'},
                     'description': 'DOI 列表，最多 3 个'},
            'allowFetch': {'type': 'boolean',
                           'description': '允许真去出版商取（默认 true）。'
                                          'false 时只查缓存/本地/Zotero，零代价'},
            'background': {'type': 'boolean',
                           'description': '后台跑（默认 true）。要取的那几篇合计可能'
                                          '几分钟，超过 MCP 的调用上限；后台跑之后用'
                                          'paper_fulltext_status 轮询'}},
         'required': ['dois']},
        lambda a: _fulltext(a),
        confirm=True)



# ══════════════════════════════════════════════════════════════════════
# 跨付费墙的入口：同步走一遍 or 后台发起 + 轮询
# ══════════════════════════════════════════════════════════════════════
_PROGRESS = 'fulltext_progress.json'


def _progress_path():
    from shared.kernel import paths
    return paths.runtime(_PROGRESS)


def _fulltext(a):
    """发起。默认后台跑 —— 取三篇加解析可能几分钟，MCP 只给约 60 秒。"""
    import io as _io
    import json
    from shared.kernel import paths, subproc
    from tools.getpdf import fulltext as F

    dois = [str(d).strip() for d in (a.get('dois') or []) if str(d).strip()][:3]
    if not dois:
        return '没给 DOI。'
    allow = a.get('allowFetch', True)
    if not a.get('background', True):
        # 前三层是零成本的，立等可取；只有第四层慢
        return F.summarize(F.many(dois, allow_fetch=bool(allow)))

    path = _progress_path()
    try:
        _io.open(path, 'w', encoding='utf-8').write(json.dumps(
            {'total': len(dois), 'finished': 0, 'done': False, 'elapsed': 0,
             'results': []}, ensure_ascii=False))
    except OSError:
        pass
    # 位置参数必须在选项**前面**（shared.kernel.cli 的约定）。写反了不会报错，
    # 只会安静地空跑 —— 第一次真跑时就是这么发现的（2026-09-08）。
    cmd = [sys.executable, '-m', 'tools.getpdf'] + dois + ['--fulltext']
    if not allow:
        cmd.append('--no-fetch')
    subproc.spawn(cmd, cwd=paths.ROOT)
    return ('已经在后台开跑：%s\n'
            '取一篇要 20 秒礼貌间隔 + 解析约半分钟，三篇大概两分钟。\n'
            '**这段时间别空等** —— 可以先读手上已有的、或把要回答的问题拆成证据清单。\n'
            '然后用 fulltext_status 看进度（那个在服务本身上，只读、不弹窗）。'
            % '、'.join(dois))


def _fulltext_status():
    import io as _io
    import json
    from tools.getpdf import fulltext as F
    path = _progress_path()
    if not os.path.exists(path):
        return '还没有跑过 paper_fulltext。'
    try:
        d = json.load(_io.open(path, encoding='utf-8'))
    except Exception:
        return '进度文件读不了（可能正在写）。过几秒再看一次。'
    head = ('%d/%d 篇已处理，用时 %.0f 秒%s\n'
            % (d.get('finished', 0), d.get('total', 0), d.get('elapsed', 0),
               '' if d.get('done') else '（还在跑）'))
    return head + F.summarize(d.get('results') or [])
