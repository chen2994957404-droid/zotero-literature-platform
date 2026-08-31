# -*- coding: utf-8 -*-
"""问全世界的命令行入口。

用法:
  python -m tools.askworld "聚硼硅氧烷的剪切硬化机理是什么"
  python -m tools.askworld "B-N配位键如何提升自修复效率" --since 2020 --top 10
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.adapters.sciverse import SciverseError
from shared.kernel.cli import opt, positionals
from tools import askworld


def main():
    """解析参数 → 检索证据 → 打印答案与出处。"""
    args = positionals()
    if not args:
        print(__doc__)
        return
    question = ' '.join(args)
    top_k = 8
    _top = opt('--top')
    if _top and _top.isdigit():
        top_k = int(_top)          # 非数字的 --top 值按原行为忽略，保持默认 8
    year_from = opt('--since')

    if not askworld.available():
        print('未配置 SCIVERSE_KEY。请双击「控制面板.bat」，在 Sciverse 一栏填写。')
        print('（想问自己库里的文献，用：python -m tools.ask "问题"）')
        return

    print(f'正在向全球文献检索证据……（问题：{question}）\n')
    try:
        r = askworld.ask_world(question, top_k=top_k, year_from=year_from)
    except SciverseError as e:
        print(f'检索失败：{e}')
        return

    if r.get('query_used') and r['query_used'] != question:
        print(f'（检索用英文式：{r["query_used"]}）\n')
    if not r['evidence']:
        print('没有检索到足够相关的证据（已过滤掉低相关度的噪声片段）。')
        print('可以换个说法、放宽年份限制，或用 --top 调大候选数。')
        return

    print('=' * 78)
    print(r['answer'])
    print('=' * 78)
    print('\n📚 证据来源（可直接引用）：')
    for i, e in enumerate(r['evidence'], 1):
        page = f"  第{e['page']}页" if e.get('page') is not None else ''
        print(f"  [{i}] 《{e['title'][:64]}》")
        print(f"      {e['year'] or '????'} · {e['venue'][:34]} · 被引{e['citations']}"
              f"{page} · 相关度{e['score']}")
    print()


if __name__ == '__main__':
    main()
