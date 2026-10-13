# -*- coding: utf-8 -*-
"""决定层：从上次检索结果里按编号挑几篇，给出「收进证据库」的那条命令。

**为什么单独做这一步**：搜到不等于要收，收了不等于要精读 —— 这两个决定都该由你自己做。

2026-10-13 起 Zotero 移出平台：「收」= 用 `tools.getpdf` 把正文 + SI 取进证据库。
工具之间不许互相 import，所以这里不直接调 getpdf，而是挑好、去掉库里已有的，打印出那条命令。
精读在文献库应用里按篇点。

用法（编号来自 `python -m tools.discover` 的输出，不用抄 DOI）：
  python -m tools.discover.collect 1,3,5-7        挑这几篇，给出取全文的命令
  python -m tools.discover.collect --看            再看一遍上次的检索结果
  python -m tools.discover.collect 全部            列表里所有的（慎用）
"""
import io
import json
import os
import sys

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass

from shared.kernel import paths
from shared.kernel.cli import flag, positionals
from tools.discover.match import build_index


def load():
    """读上次检索的暂存结果；没有就提示先去搜。"""
    stash = paths.last_search()
    if not os.path.exists(stash):
        print('还没有检索记录。先跑：python -m tools.discover "你的关键词"')
        return None
    try:
        return json.load(io.open(stash, encoding='utf-8'))
    except Exception as e:
        print(f'读取检索记录失败：{e}')
        return None


def parse_picks(expr, maxn):
    """解析 '1,3,5-7' 这类编号表达式。返回去重且有序的编号列表。"""
    if expr.strip() in ('全部', 'all'):
        return list(range(1, maxn + 1))
    picks = []
    for part in expr.replace('，', ',').split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            a, _, b = part.partition('-')
            try:
                for n in range(int(a), int(b) + 1):
                    picks.append(n)
            except ValueError:
                print(f'  看不懂的范围「{part}」，已跳过')
        else:
            try:
                picks.append(int(part))
            except ValueError:
                print(f'  看不懂的编号「{part}」，已跳过')
    seen, out = set(), []
    for n in picks:
        if n in seen:
            continue
        seen.add(n)
        if 1 <= n <= maxn:
            out.append(n)
        else:
            print(f'  编号 {n} 超出范围（共 {maxn} 条），已跳过')
    return out


def show(data):
    print(f'\n上次检索：「{data["query"]}」  {data.get("time","")}')
    print('=' * 82)
    if data['items'] and all(it.get('relevance') is None for it in data['items']):
        print('⚠ 这次检索时本机没有向量库，没算「离你的库多近」，是按检索引擎相关度 + 年份排的。')
    for it in data['items']:
        rel = it.get('relevance')
        bar = '█' * int((rel or 0) * 10) if rel is not None else '—'
        print(f'{it["n"]:2d}. [{it.get("year") or "????"}] 相关度 {rel if rel is not None else "—"} {bar:<10} '
              f'被引{it.get("citations", 0)}')
        print(f'    {(it.get("title") or "")[:74]}')
    print('=' * 82)


def main():
    data = load()
    if not data:
        return
    items = data['items']
    args = positionals()

    if not args or flag('--看') or flag('--list'):
        show(data)
        print('\n收哪几篇：python -m tools.discover.collect 1,3,5-7  [--精读]')
        return

    picks = parse_picks(' '.join(args), len(items))
    if not picks:
        print('没有选中任何条目。')
        return

    chosen = [items[n - 1] for n in picks]
    no_doi = [c for c in chosen if not c.get('doi')]
    chosen = [c for c in chosen if c.get('doi')]

    # 导入前实时查一次库：检索结果可能是几分钟前的，期间你可能已经收过了。
    # 重复条目清理起来很麻烦（之前全库去重花了不少功夫），**从源头防住最省事**。
    try:
        _, have_dois = build_index(force=True)
        already = [c for c in chosen if (c.get('doi') or '').lower() in have_dois]
        if already:
            print(f'\n跳过 {len(already)} 篇（库里已经有了）：')
            for c in already:
                print(f'  {c["n"]:2d}. {(c.get("title") or "")[:66]}')
            chosen = [c for c in chosen if c not in already]
    except Exception:
        pass          # 查不了就照常走，取全文那一步还会按 DOI 再对一次账

    print(f'\n准备收下 {len(chosen)} 篇：')
    for c in chosen:
        print(f'  {c["n"]:2d}. {(c.get("title") or "")[:68]}')
        print(f'      DOI:{c["doi"]}')
    if no_doi:
        print(f'\n有 {len(no_doi)} 篇没有 DOI，没法按 DOI 取，需要手动找：')
        for c in no_doi:
            print(f'  {c["n"]:2d}. {(c.get("title") or "")[:68]}')
    if not chosen:
        return

    print('\n收进证据库（借取全文用的浏览器，用学校订阅）：')
    print('  python -m tools.getpdf ' + ' '.join(c['doi'] for c in chosen))


if __name__ == '__main__':
    main()
