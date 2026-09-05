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
                '都在它身上。请主人先这样启动它：msedge --remote-debugging-port=9222')

    r = getpdf.fetch_one(doi)
    if r['reason'] == 'exists':
        return f'{doi} 盘上已经有了：{r["path"]}（{r["bytes"] // 1024} KB），没有重下。'
    if r['ok']:
        return (f'拿到了：{r["path"]}（{r["bytes"] // 1024} KB）\n'
                f'  标题：{r["title"][:80]}\n  来源：{r["landing"][:100]}\n'
                f'（如果这次调用超时了，文件多半还是下下来了，重调一次会直接告诉你在哪。）')
    return (f'{doi} 没拿到 —— {pdf_fetch.REASONS.get(r["reason"], r["reason"])}\n'
            f'  落地页：{r["landing"][:100]}')


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
