# -*- coding: utf-8 -*-
"""汇总各工具的 `INCIDENTS.md` → `docs/incidents/README.md`（坑的总目录）。

用法: python host/codegen/incidents.py          生成
      python host/codegen/incidents.py --check  只检查是否同步（不写盘）

## 为什么是「汇总」而不是「切开」

`docs/incidents/踩坑记录.md` 有 90 条编号记录、140 KB，按**时间**排。
它必须原样留着：踩坑的现场感（当时怎么误判的、怎么绕回来的）是它最值钱的部分，
拆成十份就没了，而且同一条坑常常同时咬到两个工具。

所以分工是：
  · **总账**（`踩坑记录.md`）—— 全文，按时间，唯一真相，只增不改
  · **工具切片**（`tools/<t>/INCIDENTS.md`）—— 手写，只列「跟我有关的坑号 + 一句话」
  · **本文件生成的目录**（`docs/incidents/README.md`）—— 哪个工具有哪些坑，一眼看全

改工具切片之后跑一次这个脚本。守卫会检查两者同步。
"""
import io
import os
import re
import sys

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.kernel import paths
from shared.kernel.cli import flag

ROOT = paths.ROOT
TOOLS_DIR = os.path.join(ROOT, 'tools')
LEDGER = os.path.join(ROOT, 'docs', 'incidents', '踩坑记录.md')
OUT = os.path.join(ROOT, 'docs', 'incidents', 'README.md')

_ROW = re.compile(r'^\|\s*(#[\d\s#]+?)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*$', re.M)


def slices():
    """[(工具名, [(坑号, 现象, 意味着什么)])]，按工具名排序。"""
    out = []
    if not os.path.isdir(TOOLS_DIR):
        return out
    for name in sorted(os.listdir(TOOLS_DIR)):
        p = os.path.join(TOOLS_DIR, name, 'INCIDENTS.md')
        if not os.path.isfile(p):
            continue
        rows = _ROW.findall(io.open(p, encoding='utf-8').read())
        out.append((name, rows))
    return out


def ledger_count():
    """总账里有多少条编号记录（用来说明这份目录只是索引，不是全部）。"""
    if not os.path.isfile(LEDGER):
        return 0
    return len(re.findall(r'^##\s*(?:踩坑\s*)?#?\d+[.：:\s]',
                          io.open(LEDGER, encoding='utf-8').read(), re.M))


def build():
    data = slices()
    # ⚠ 按 (坑号, 现象) 合并，**不能只按坑号**：总账里的编号撞过车
    # （#15 / #16 / #43 各被用过两次，是并行记录时各自往下编的结果，见 #91）。
    # 只按号合并会把「find_pdf 误选 SI」和「本地 7B 编假数据」并成一条，
    # 然后在「咬过不止一个工具」表里报出一个根本不存在的关联 —— 生成的假事实
    # 比没有更糟，因为它看起来是统计出来的。
    seen = {}
    for tool, rows in data:
        for num, what, _ in rows:
            for one in num.replace('#', ' #').split():
                seen.setdefault((one, what), []).append(tool)

    L = ['# 坑的总目录（自动生成，别手改）', '',
         f'源：各 `tools/<工具>/INCIDENTS.md`。生成器：`host/codegen/incidents.py`。',
         '',
         f'**全文在 [踩坑记录.md](踩坑记录.md)**（{ledger_count()} 条，按时间排，唯一真相）。',
         '这里只回答一个问题：**我要改的这个工具，前人在哪些地方栽过？**', '']

    L += ['## 按工具', '']
    for tool, rows in data:
        L.append(f'### {tool}（{len(rows)} 条）')
        L.append('')
        if not rows:
            L.append('还没有本工具特有的坑。')
        else:
            L.append('| 坑号 | 现象 | 对这个工具意味着什么 |')
            L.append('|---|---|---|')
            for num, what, means in rows:
                L.append(f'| {num} | {what} | {means} |')
        L.append('')

    cross = {k: v for k, v in seen.items() if len(set(v)) > 1}
    if cross:
        L += ['## 咬过不止一个工具的', '',
              '这些值得特别小心 —— 它们不是某个工具的毛病，是**一类做法**的毛病。', '',
              '| 坑号 | 现象 | 咬过谁 |', '|---|---|---|']
        for num, what in sorted(cross, key=lambda x: (int(re.sub(r'\D', '', x[0]) or 0), x[1])):
            L.append(f'| {num} | {what} | {"、".join(sorted(set(cross[(num, what)])))} |')
        L.append('')

    L += ['## 平台自身的坑不在这里', '',
          '面板 / 体检 / 部署 / MCP / 常驻服务踩的坑（编码、弹窗、进程、部署、',
          'SSH、版本库冲突…）没有按工具切片 —— 它们本来就是平台级的，',
          '直接查总账，或看 `troubleshoot` skill 的「现象 → 坑号」速查表。', '']
    return '\n'.join(L)


def main():
    body = build()
    if flag('--check'):
        cur = io.open(OUT, encoding='utf-8').read() if os.path.isfile(OUT) else None
        if cur != body:
            print('docs/incidents/README.md 与各工具的 INCIDENTS.md 不同步；'
                  '跑一次 python host/codegen/incidents.py')
            sys.exit(1)
        print('坑的总目录与各工具同步')
        return
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    io.open(OUT, 'w', encoding='utf-8', newline='').write(body)
    n = sum(len(r) for _, r in slices())
    print(f'已生成 {os.path.relpath(OUT, ROOT)}：{len(slices())} 个工具、{n} 条索引')


if __name__ == '__main__':
    main()
