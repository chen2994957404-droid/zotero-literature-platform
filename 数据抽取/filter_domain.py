# -*- coding: utf-8 -*-
"""方向筛选：从 structured/ 的全库对比记录里，筛出真正属于
【软物质·动态键弹性体·自愈合·胶粘剂】方向的文献，单独出一张干净子表。

用途：全库粗抽后混入了有机金属/合成化学等无关文献（material_system=N/A 或跑题），
会淹没你真正的方向。这张干净子表让你横扫找规律时不被干扰。

判定逻辑（宽进严出，可调）：
  - 先剔除 material_system 为 N/A / 空的（无关文献的典型特征）
  - 再要求 材料体系 或 动态键类型 命中方向关键词（正向命中才算你的方向）
  产物: structured/compare_domain.md（干净子表） + structured/_domain_keys.txt（命中的key清单）

关键词集中在 KW，想放宽/收紧改这里即可。
用法: python filter_domain.py
"""
import os, sys, json, re

# 【标准开头】项目根加入 import 路径 + 强制 UTF-8 输出（详见 docs/代码规范_标准脚本模板.md）
_ROOT = os.path.dirname(os.path.abspath(__file__))
while True:
    if os.path.isdir(os.path.join(_ROOT, 'modules')):
        break                      # 项目根特征：modules/ 目录只在根存在
    parent = os.path.dirname(_ROOT)
    if parent == _ROOT:
        break                      # 到盘符根，兜底
    _ROOT = parent
sys.path.insert(0, _ROOT)
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

DIR = os.path.join(_ROOT, 'workflow_data', 'structured')

# 方向关键词（材料体系 / 动态键类型 命中任一即算本方向）
KW = re.compile(
    r'(弹性体|自愈|自修复|自复|超分子|动态键|动态共价|可逆交联|氢键|'
    r'聚氨酯|脲|尿烷|聚脲|硼硅|硼氧|siloxane|borosiloxane|PDMS|硅氧烷|'
    r'胶粘|粘合|粘附|胶带|adhesi|水凝胶|hydrogel|瓶刷|配位|金属超分子|'
    r'弹性|可回收.*聚合|玻璃体|vitrimer|elastomer|self-heal|supramolecul)',
    re.I)

def is_domain(rec):
    ms = (rec.get('material_system') or '').strip()
    if ms in ('', 'N/A', 'n/a', '未提及'):
        return False
    hay = ms + ' ' + str(rec.get('dynamic_bond_type', '')) + ' ' + str(rec.get('self_healing', ''))
    return bool(KW.search(hay))

def flat(v, n=80):
    if isinstance(v, dict):   # key_properties 可能是 {'拉伸强度: 142 MPa': ''} 形态
        v = '; '.join(v.keys())
    elif isinstance(v, list):
        v = '; '.join(str(x) for x in v)
    return str(v).replace('\n', ' ').replace('|', '/')[:n]

def main():
    recs = []
    for f in sorted(os.listdir(DIR)):
        if f.endswith('.json'):
            try:
                recs.append(json.load(open(os.path.join(DIR, f), encoding='utf-8')))
            except Exception:
                # 单个结果文件损坏就跳过，不参与领域判定，不影响主流程
                pass
    domain = [r for r in recs if is_domain(r)]
    domain.sort(key=lambda r: r.get('material_system', ''))

    cols = ['material_system', 'dynamic_bond_type', 'synthesis_conditions',
            'key_properties', 'self_healing', 'structure_property', 'key_finding']
    zh = ['材料体系', '动态键', '合成条件', '性能数值', '自愈合', '结构-性能', '核心发现']
    rows = ["# 方向子表 · 软物质/动态键弹性体（从全库筛出）", "",
            f"> 全库 {len(recs)} 篇 → 命中本方向 {len(domain)} 篇。剔除了 N/A 与跑题文献。",
            "> 竖着扫同一列找规律/空白/矛盾——这是找 idea 的地方。", "",
            '| # | 论文 | ' + ' | '.join(zh) + ' |',
            '|---|---|' + '---|' * len(cols)]
    for i, r in enumerate(domain, 1):
        cells = [str(i), r.get('title', '')[:34].replace('|', '/')] + [flat(r.get(c, 'N/A')) for c in cols]
        rows.append('| ' + ' | '.join(cells) + ' |')

    open(os.path.join(DIR, 'compare_domain.md'), 'w', encoding='utf-8').write('\n'.join(rows))
    open(os.path.join(DIR, '_domain_keys.txt'), 'w', encoding='utf-8').write(
        '\n'.join(r['key'] for r in domain))
    print(f'全库 {len(recs)} 篇 → 本方向 {len(domain)} 篇')
    print(f'干净子表: {os.path.join(DIR, "compare_domain.md")}')
    print(f'命中key清单: {os.path.join(DIR, "_domain_keys.txt")}（供后续精层批量重抽用）')

if __name__ == '__main__':
    main()
