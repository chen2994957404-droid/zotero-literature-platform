# -*- coding: utf-8 -*-
"""extract 的 MCP 面：一条提示词（花钱）+ 三张对比表（只读资源，免费）。

对比表是**只读数据**，按 R4 判据做成 resource：模型可以自己读，读它不花钱、
也不改任何东西。抽取本身花钱，所以是 prompt。本文件只做参数转换。
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import io

from shared.kernel import paths
from shared.kernel.mcp_prompt import card

TABLES = (
    ('compare', '研究论文横向对比表（找 idea 的主载体：精层 + 粗层）'),
    ('compare_PBS', '聚硼硅氧烷方向的精层子表（含真实数值）'),
    ('compare_reviews', '综述单列的对比表'),
)


def _read(name):
    """读一张对比表。没生成过就说清楚，别让模型以为库是空的。"""
    p = paths.compare(name)
    if not os.path.isfile(p):
        return f'（{name}.md 还没生成 —— 先跑一次结构化抽取）'
    return io.open(p, encoding='utf-8', errors='replace').read()


def _one(a):
    """抽一篇 → 给模型看的文本。

    ⚠ **可能超过 MCP 约 60 秒的调用上限**（长文过一次大模型）。超时也不要紧：
    产物照样会落盘，而且这一步是幂等的（抽过就跳过），重调一次几乎不花钱。
    这句话也写进了返回文本里 —— 模型看到超时才知道该怎么办。
    """
    import json
    from tools import extract as E
    rec = E.run(a['itemKey'])
    if not rec:
        return (f'{a["itemKey"]} 没抽出来 —— 多半是还没解析过（缺 full.md）。'
                f'先让用户在 Zotero 里给它打「待处理」标签走一遍精读。')
    keep = ('material_system', 'dynamic_bond', 'synthesis_conditions',
            'characterization', 'key_properties', 'conclusion')
    brief = {k: rec.get(k) for k in keep if rec.get(k)}
    tail = ('（已并入对比表。若刚才调用超时，产物其实已经落盘了 ——'
            '这一步幂等，再调一次就能拿到结果，几乎不花钱。）')
    return json.dumps(brief, ensure_ascii=False, indent=2) + '\n\n' + tail


def register(server):
    for name, desc in TABLES:
        server.register_resource(f'paper://{name}.md', f'{name}.md', desc,
                                 (lambda n: lambda: _read(n))(name))

    server.register_tool(
        'extract_one',
        '把**一篇**文献抽成统一 schema 的结构化字段，并刷新横向对比表。'
        '**要花钱**：这一篇过一次云端大模型，调用时会先弹窗让用户确认。'
        '⚠ 只是想看表就别抽 —— 直接读资源 `paper://compare.md`，免费。'
        '全库增量抽取要用 extract 那条提示词（人点）。',
        {'type': 'object',
         'properties': {'itemKey': {'type': 'string', 'description': 'Zotero 条目 key'}},
         'required': ['itemKey']},
        _one,
        confirm=True)      # ← 每次都弹窗，且没有「不再询问」

    server.register_prompt(
        'extract', '把文献抽成统一 schema 的结构化字段，并刷新横向对比表。',
        [{'name': 'itemKey', 'description': '只抽某一篇（留空 = 全库增量，花钱多）',
          'required': False}],
        lambda a: card(
            ('把文献 %s 的数据抽出来' % a['itemKey']) if a.get('itemKey')
            else '把全库还没抽过的文献的数据抽出来',
            cost='云端每篇都花钱（`--local` 改用本地模型不花钱，但准确度低一档）',
            steps=['python -m tools.extract %s --parse' % (a.get('itemKey') or '')],
            notes='抽完会自动刷新对比表。**只是想看表就别抽**：'
                  '直接读资源 `paper://compare.md`，免费。\n'
                  '不带 key 就是**全库作业**，只在主力机上能跑。'))
