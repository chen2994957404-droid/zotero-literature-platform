# -*- coding: utf-8 -*-
"""决定层：从上次检索结果里按编号挑几篇收进 Zotero。

**为什么单独做这一步**：搜到不等于要收，收了不等于要精读。
这两个决定都该由你自己做，而不是被自动化替你决定 ——
尤其精读要花钱（MineRU 解析 + 大模型），不该被顺手触发。

用法（编号来自 `python -m tools.discover` 的输出，不用抄 DOI）：
  python -m tools.discover.collect 1,3,5-7        收进库，**不**打标签、不精读
  python -m tools.discover.collect 1,3 --精读      收进库并打「待处理」→ 自动精读
  python -m tools.discover.collect --看            再看一遍上次的检索结果
  python -m tools.discover.collect 全部            收下列表里所有的（慎用）

收进库但没精读的，以后随时可以在 Zotero 里补打「待处理」标签。
"""
import io
import json
import os
import sys

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.kernel import paths
from shared.kernel.cli import flag, positionals
from tools.discover.importer import import_dois
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
    for it in data['items']:
        rel = it.get('relevance')
        bar = '█' * int((rel or 0) * 10) if rel is not None else '?'
        print(f'{it["n"]:2d}. [{it.get("year") or "????"}] 相关度 {rel} {bar:<10} '
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

    deep = flag('--精读') or flag('--deepread')
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
        pass          # 查不了就照常走，导入本身仍会由 Zotero 端兜底

    print(f'\n准备收下 {len(chosen)} 篇：')
    for c in chosen:
        print(f'  {c["n"]:2d}. {(c.get("title") or "")[:68]}')
        print(f'      DOI:{c["doi"]}')
    if no_doi:
        print(f'\n有 {len(no_doi)} 篇没有 DOI，无法自动导入，需要手动加：')
        for c in no_doi:
            print(f'  {c["n"]:2d}. {(c.get("title") or "")[:68]}')
    if not chosen:
        return

    print()
    if deep:
        print('★ 会打「待处理」标签 → 收进库后**立刻自动精读**（消耗 MineRU 与大模型额度）')
    else:
        print('· 只收进 Zotero，**不精读**。以后想读，在 Zotero 里补打「待处理」标签即可')

    # 去掉 BOM 等不可见字符：某些 shell 管道会在输入前加 ﻿，
    # 不处理会导致「明明输了 y 却被当成取消」这种莫名其妙的行为
    ans = input('\n确认执行？(y/回车确认，其他取消): ').strip().lstrip('﻿').strip().lower()
    if ans not in ('', 'y', 'yes', '是'):
        print('已取消，什么都没做。')
        return

    try:
        r = import_dois([c['doi'] for c in chosen], ['待处理'] if deep else [])
    except Exception as e:
        print(f'导入失败：{e}')
        return

    print(f'\n成功收下 {len(r["ok"])} 篇：')
    for doi, title, key in r['ok']:
        print(f'  ✓ {title[:68]}')
    if r['failed']:
        print(f'\n失败 {len(r["failed"])} 篇：')
        for doi, why in r['failed']:
            print(f'  ✗ {doi} — {why}')
    if deep and r['ok']:
        print('\n精读服务会在 1 分钟内开始，完成后可在 Zotero 里点开 summary 附件查看。')
    elif r['ok']:
        print('\n已收进库（未精读）。想读时在 Zotero 打「待处理」标签即可。')


if __name__ == '__main__':
    main()
