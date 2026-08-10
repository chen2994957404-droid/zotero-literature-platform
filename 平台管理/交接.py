# -*- coding: utf-8 -*-
"""自动生成交接文件 HANDOVER.md —— 新对话开头读它，就知道「我们停在哪」。

## 为什么必须自动生成

标准做法是 `CLAUDE.md` + `HANDOVER.md` 配合：前者说「这个项目是什么」，
后者说「我们做到哪了、试过什么、下一步是什么」。

但**靠人（或 AI）记得更新的文档一定会过时** —— 本项目已经证明过三次：
待办与需求过时（列着早已修好的 bug）、CLAUDE.md 的密钥说明过时（还写着 .env）、
docs 里留着教人跑 `docker ps` 的 n8n 时代教程。

所以这份交接文件的内容**全部从系统真实状态抓取**：
git 提交历史、体检结果、评测集进展、待办、最近踩的坑。
没有一处需要人手写 —— 也就没有过时的可能。

用法:
  python 平台管理/交接.py           生成/更新 HANDOVER.md
  python 平台管理/交接.py --print    只打印不写文件
"""
import os, sys, io, glob, re, json, time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from modules.subproc import out as _out

HANDOVER = os.path.join(ROOT, 'HANDOVER.md')


def git(args, default=''):
    return _out(['git'] + args, timeout=30, default=default).strip()


def recent_commits(n=8):
    raw = git(['log', f'-{n}', '--pretty=format:%ad|%s', '--date=format:%m-%d'])
    rows = []
    for ln in raw.split('\n'):
        if '|' in ln:
            d, _, s = ln.partition('|')
            rows.append((d.strip(), s.strip()[:78]))
    return rows


def health():
    """跑一次体检拿当前状态。慢（约 40 秒）但这正是交接最该说清的事。"""
    txt = _out([sys.executable, os.path.join(SCRIPT_DIR, 'health_check.py')],
               timeout=300, default='')
    m = re.search(r'结果：(\d+) 通过，(\d+) 警告，(\d+) 失败', txt)
    problems = [l.strip() for l in txt.split('\n')
                if l.startswith('[FAIL]') or l.startswith('[WARN]')]
    return {'summary': m.group(0) if m else '（体检没跑起来）', 'problems': problems}


def blocks():
    rows = []
    for f in sorted(glob.glob(os.path.join(ROOT, 'modules', '*', '__init__.py'))):
        name = os.path.basename(os.path.dirname(f))
        doc = ''
        try:
            import ast
            doc = (ast.get_docstring(ast.parse(open(f, encoding='utf-8').read())) or '')
            doc = doc.split('\n')[0].replace(f'{name} · ', '').split('（')[0][:26]
        except Exception:
            pass
        rows.append((name, doc))
    return rows


def flows():
    skip = {'modules', 'docs', 'workflow_data', 'n8n_data', 'wf_backup'}
    rows = []
    for d in sorted(os.listdir(ROOT)):
        p = os.path.join(ROOT, d)
        if (not os.path.isdir(p) or d in skip or d.startswith(('.', 'zotero_backup'))
                or not glob.glob(os.path.join(p, '*.py'))):
            continue
        desc = ''
        cm = os.path.join(p, 'CLAUDE.md')
        if os.path.exists(cm):
            for ln in open(cm, encoding='utf-8', errors='replace'):
                ln = ln.strip()
                if ln and not ln.startswith(('#', '>', '`', '|', '-')):
                    desc = ln[:52]
                    break
        rows.append((d, len(glob.glob(os.path.join(p, '*.py'))), desc))
    return rows


def evalset_state():
    try:
        from modules import evalset as E
        s = E.stats()
        return s
    except Exception:
        return None


def recent_pitfalls(n=5):
    """最近踩的几个坑（只取标题）。踩坑记录 47KB，新对话读不完，给个索引。"""
    p = os.path.join(ROOT, 'docs', '踩坑记录.md')
    if not os.path.exists(p):
        return []
    titles = re.findall(r'^## (踩坑 #\d+[：:].+)$',
                        open(p, encoding='utf-8', errors='replace').read(), re.M)
    return titles[-n:]


def todos():
    p = os.path.join(ROOT, 'docs', '待办与需求.md')
    if not os.path.exists(p):
        return []
    return re.findall(r'^## (.+)$',
                      open(p, encoding='utf-8', errors='replace').read(), re.M)[-6:]


def build():
    L = []
    a = L.append
    a('# 交接文件 · 我们做到哪了')
    a('')
    a(f'> **本文件由 `平台管理/交接.py` 自动生成，不要手改** —— 手写的文档一定会过时。')
    a(f'> 生成时间：{time.strftime("%Y-%m-%d %H:%M")}')
    a('')
    a('新对话请按这个顺序读：本文件 → `CLAUDE.md` → 需要动哪块就读那个文件夹的 `CLAUDE.md`。')
    a('')

    a('## 现在健康吗')
    a('')
    h = health()
    a(f'`{h["summary"]}`')
    if h['problems']:
        a('')
        for p in h['problems'][:6]:
            a(f'- {p}')
    a('')

    a('## 最近做了什么（git 提交，新到旧）')
    a('')
    for d, s in recent_commits(10):
        a(f'- `{d}` {s}')
    a('')

    ev = evalset_state()
    if ev is not None:
        a('## 精读质量评测集')
        a('')
        a(f'- 已评价 **{ev["total"]}** 篇（好 {ev["good"]} / 差 {ev["bad"]}）')
        if ev['ready']:
            a('- ✅ **好、差样本各已 ≥3 篇 —— 可以做「自动质量分」校准了**')
            c = ev['compare']
            a(f'- 好 vs 差 的客观差异：字数 {c["chars"]["good"]}/{c["chars"]["bad"]}、'
              f'图 {c["figures"]["good"]}/{c["figures"]["bad"]}、'
              f'数值 {c["numbers"]["good"]}/{c["numbers"]["bad"]}、'
              f'章节 {c["sections"]["good"]}/{c["sections"]["bad"]}')
        else:
            a('- ⏳ 还不够做校准（需好、差各 ≥3 篇）。'
              '用户在 Zotero 打「读完」标签 → 控制面板「精读评价」里评。')
        if ev['reasons']:
            a(f'- 差评原因排行：{"、".join(f"{k}×{v}" for k, v in ev["reasons"][:4])}')
        a('')

    a('## 项目组成')
    a('')
    a('| 文件夹 | 脚本数 | 是什么 |')
    a('|---|---|---|')
    for d, n, desc in flows():
        a(f'| `{d}` | {n} | {desc} |')
    a('')
    bs = blocks()
    a(f'**积木层 `modules/`（{len(bs)} 块）**：'
      + '、'.join(f'`{n}`' for n, _ in bs))
    a('')

    tl = todos()
    if tl:
        a('## 待办（可能已过时，动手前先核实）')
        a('')
        for t in tl:
            a(f'- {t}')
        a('')

    pf = recent_pitfalls()
    if pf:
        a('## 最近踩的坑（全文见 `docs/踩坑记录.md`）')
        a('')
        for t in pf:
            a(f'- {t}')
        a('')

    a('## 铁律提醒')
    a('')
    a('- **【零号判据】先看真实世界，别用记忆代替调研。**'
      '涉及外部现状/具体数字/API 行为，必须查、必须测。')
    a('- 改完**先跑体检再重启服务**：`python 平台管理/health_check.py`')
    a('- 花钱、不可逆、影响 Zotero 库的操作，**先问用户**。')
    a('- 每个改动记 `docs/变更记录.md`，踩坑记 `docs/踩坑记录.md`，并 git commit。')
    return '\n'.join(L)


def main():
    txt = build()
    if '--print' in sys.argv:
        print(txt)
        return
    io.open(HANDOVER, 'w', encoding='utf-8', newline='').write(txt + '\n')
    print(f'已生成 {HANDOVER}（{len(txt)} 字符）')


if __name__ == '__main__':
    main()
