# -*- coding: utf-8 -*-
"""digitize 的 MCP 面：一条提示词（要云端视觉大模型 → 花钱 → prompt）。

本文件只做参数转换，一行业务逻辑都没有。
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.kernel.mcp_prompt import card


def _steps(a):
    """两条入口二选一：已精读的文献给 itemKey，散图给 imagePath。

    `itemKey` 排在前面是有原因的：用户手里通常是一篇文献，不是图片文件。
    走 itemKey 时裁图那步由工具自己做（`shared.domain.figure_crop`，
    踩坑 #7 的全部智慧在那里面），比让人先自己裁一遍可靠得多。
    """
    hint = ' --hint "%s"' % a['hint'] if a.get('hint') else ''
    if a.get('itemKey'):
        figs = ' --figures %s' % a['figures'] if a.get('figures') else ''
        return ['python -m tools.digitize --key %s%s%s' % (a['itemKey'], figs, hint)]
    return ['python -m tools.digitize "%s"%s' % (a.get('imagePath', ''), hint)]


def _one(a):
    """读一张图 → 给模型看的文本。**一次只读一张**，所以代价是可预期的。"""
    import json
    from tools import digitize as D
    r = D.digitize_paper(a['itemKey'], only=[int(a['figure'])])
    if not r:
        return (f'{a["itemKey"]} 没有可裁的图 —— 多半是还没解析过。'
                f'先让用户在 Zotero 里给它打「待处理」标签走一遍精读。')
    out = r.get(int(a['figure']))
    if out is None:
        return f'这篇没有第 {a["figure"]} 张图。它有的图号：{sorted(r)}'
    if out.get('error'):
        return f'读不出来：{out["error"]}'
    return json.dumps(out, ensure_ascii=False, indent=2)


def register(server):
    server.register_tool(
        'digitize_figure',
        '把一篇**已精读文献**里的某一张图读成 X-Y 数值（曲线/散点/柱状/箱线）。'
        '**要花钱**：调一次云端视觉大模型，调用时会先弹窗让用户确认。'
        '⚠ 一次只读一张 —— 整篇每张都读要用 digitize 那条提示词（人点）。',
        {'type': 'object',
         'properties': {
             'itemKey': {'type': 'string', 'description': '已精读文献的 Zotero key'},
             'figure': {'type': 'integer', 'description': '图号，如 3'}},
         'required': ['itemKey', 'figure']},
        _one,
        confirm=True)      # ← 每次都弹窗，且没有「不再询问」

    server.register_prompt(
        'digitize', '把论文图里的曲线/散点/柱状图读成 X-Y 数值。',
        [{'name': 'itemKey',
          'description': '已精读文献的 Zotero key（推荐；裁图由工具自己做）',
          'required': False},
         {'name': 'figures',
          'description': '只读哪几张图，如「2,3」。不给就整篇每张都读（每张各花一次钱）',
          'required': False},
         {'name': 'imagePath',
          'description': '图片文件路径（散图用；给了 itemKey 就不用它）',
          'required': False},
         {'name': 'hint', 'description': '额外提示，如「只读红色那条曲线」',
          'required': False}],
        lambda a: card(
            ('读文献 %s 的图' % a['itemKey']) if a.get('itemKey')
            else ('把图 %s 里的曲线读成数值' % a.get('imagePath', '')),
            cost='要调用云端视觉大模型；**整篇的话每张图各花一次**',
            steps=_steps(a),
            notes='⚠ **别为了省钱换本地 7B**：它会编出看似合理的假数据还标高置信度'
                  '（实测把 FTIR 光谱读成完美等差数列）。编的数字最像事实。\n'
                  '整篇之前先问用户要哪几张 —— `--figures 2,3` 比读十张便宜得多。'))
