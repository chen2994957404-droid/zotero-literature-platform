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
  python host/codegen/handover.py           生成/更新 HANDOVER.md
  python host/codegen/handover.py --print    只打印不写文件
"""
import io
import os, sys, io, glob, re, json, time

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
from shared.kernel import paths
from shared.kernel.paths import ROOT as _ROOT

from shared.kernel.cli import flag
from shared.kernel.subproc import out as _out

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = _ROOT

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
    txt = _out([sys.executable, os.path.join(ROOT, 'host', 'doctor', 'health_check.py')],
               timeout=300, default='')
    m = re.search(r'结果：(\d+) 通过，(\d+) 警告，(\d+) 失败', txt)
    problems = [l.strip() for l in txt.split('\n')
                if l.startswith('[FAIL]') or l.startswith('[WARN]')]
    return {'summary': m.group(0) if m else '（体检没跑起来）', 'problems': problems}


# 顶层代码包各自一句话。写在这里而不是各包的 __init__ 里，是因为这棵树要
# **一眼看完**，取不到就宁可不写 —— 生成的文档里不许出现编的描述。
_PKG_DESC = {
    'shared':          '共用件：被 ≥2 个工具用到才允许住这里',
    'shared/kernel':   '基础设施：谁都依赖它，它不依赖任何人',
    'shared/domain':   '纯逻辑：不联网、不知道文件放在哪',
    'shared/adapters': '外接口：唯一允许联网/用第三方库的一环',
    'host':            '平台自身：让平台活着的东西（没人 import 它）',
    'tools':           '工具切片：一个工具 = 一个自包含的包',
}


def _members(p):
    """一个包底下有哪些成员（子包 + 直接躺着的 .py），返回排好序的名字列表。"""
    subs = sorted(x for x in os.listdir(p)
                  if os.path.isdir(os.path.join(p, x)) and x not in paths.NOISE_DIRS)
    files = sorted(os.path.basename(f) for f in glob.glob(os.path.join(p, '*.py'))
                   if not os.path.basename(f).startswith('__'))
    return subs + files


def _pkg_lines(rel, p, indent=''):
    """画一个代码包：一行标题 + 一行成员。shared/ 这种有子环的会往下再画一层。"""
    out = []
    subrings = [r for r in paths.CODE_RINGS if r.startswith(rel + '/')]
    if subrings:
        out.append(f'{indent}{rel.split("/")[-1]}/  ← {_PKG_DESC.get(rel, "")}')
        for r in subrings:
            out += _pkg_lines(r, os.path.join(ROOT, *r.split('/')), indent + '    ')
        return out
    names = _members(p)
    out.append(f'{indent}{rel.split("/")[-1]}/  ← {_PKG_DESC.get(rel, "")}（{len(names)} 块）')
    if names:
        out.append(indent + '    ' + '、'.join(names))
    return out


def tree():
    """画一棵目录树，只含代码与文档。

    **为什么必须有这个（实测得出）**：让一个全新会话接手项目时，它的第一个动作
    通常是 glob 根目录 —— 结果返回 3318 个文件，前 100 个全是
    `workflow_data/library/<KEY>/parsed/images/*.jpg`，**完全看不出项目长什么样**。
    在交接文件里直接给出目录树，新会话就不必去 glob，也就不会被数据淹没。
    """
    skip_dir = paths.NOISE_DIRS   # 树里要显示 shared/ tests/，只跳数据与缓存
    lines = []
    for d in sorted(os.listdir(ROOT)):
        p = os.path.join(ROOT, d)
        if d.startswith('.') or d in skip_dir or d.startswith('zotero_backup'):
            continue
        if os.path.isdir(p):
            if d in ('shared', 'host', 'tools') or d in paths.CODE_RINGS:
                lines += _pkg_lines(d, p)
            elif d == 'docs':
                n = len(glob.glob(os.path.join(p, '*.md')))
                lines.append(f'{d}/                    ← 文档（{n} 份）')
            else:
                pys = sorted(os.path.basename(f) for f in glob.glob(os.path.join(p, '*.py')))
                lines.append(f'{d}/ （{len(pys)} 个脚本）')
                if pys:
                    lines.append('    ' + '、'.join(pys[:8])
                                 + ('…' if len(pys) > 8 else ''))
    files = sorted(f for f in os.listdir(ROOT)
                   if os.path.isfile(os.path.join(ROOT, f))
                   and not f.startswith(('.', '_'))     # 下划线开头的是临时脚本
                   and f != 'HANDOVER.md')
    lines.append('')
    lines.append('根目录文件：' + '、'.join(files))
    lines.append('')
    lines.append('（workflow_data/ 是数据目录，3000+ 文件，**不要去 glob 它**）')  # paths-exempt: 生成的文档正文
    return lines


def _current_stage():
    """从 CLAUDE.md 抽出「架构重构走到哪一阶段」。抽不到就返回 None（绝不编）。

    CLAUDE.md 是唯一事实来源，这里只做提取，不维护第二份 ——
    手写的第二份会过时，而过时的「下一步」会把新对话直接带偏。
    """
    try:
        lines = io.open(CLAUDE_MD, encoding='utf-8').read().split(chr(10))
    except Exception:
        return None
    for i, ln in enumerate(lines):
        if '已完成阶段' in ln:
            block = [ln.strip()]
            for nxt in lines[i + 1:i + 4]:
                t = nxt.strip()
                if not t or t.startswith('#') or t.startswith('```'):
                    break
                block.append(t)
            return '**架构重构（主线）**：' + ' '.join(block).replace('**', '')
    return None


def next_step():
    """推断「下一步该做什么」。

    **不手写** —— 手写的下一步和待办一样会过时（实测：待办里还挂着早已被
    proc_lock 解决的 watcher 重复实例）。这里全部依据系统的真实状态推断。
    """
    steps = []
    # 主线排第一：架构重构走到哪，是「我们做到哪了」最重要的一条
    stage = _current_stage()
    if stage:
        steps.append(stage)
    h = _HEALTH_CACHE.get('data') or {}
    if h.get('problems'):
        steps.append('**先修体检报的问题**（见上一节），其余都往后放')
    try:
        from shared.adapters import evalset as E
        s = E.stats()
        if not s['ready']:
            need_g, need_b = max(0, 3 - s['good']), max(0, 3 - s['bad'])
            steps.append(
                f'**攒精读评测集**：还差「好」{need_g} 篇、「差」{need_b} 篇。'
                f'用户在 Zotero 打「读完」标签 → 控制面板「精读评价」里评。'
                f'评够后即可做「自动质量分」校准，让系统自己发现精读退化。')
        else:
            steps.append('**做自动质量分校准**：评测集样本已够，'
                         '分析好/差两组的客观指标差异，做成能自动算的质量分。')
    except Exception:
        pass
    if not steps:
        steps.append('没有明确的进行中任务 —— 问用户想做什么。')
    return steps


_HEALTH_CACHE = {}


def blocks():
    rows = []
    for ring, name, d in paths.block_dirs():
        f = os.path.join(d, '__init__.py')
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
    """工作流 = 项目根下、含 .py、且不是代码包/数据/文档 的文件夹。

    R2/R3 窗把中文文件夹拆进 `tools/` 之后，这个数会归零 —— 那时它就该退休了。
    """
    skip = paths.NON_WORKFLOW_DIRS
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
        from shared.adapters import evalset as E
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
    a(f'> **本文件由 `host/codegen/handover.py` 自动生成，不要手改** —— 手写的文档一定会过时。')
    a(f'> 生成时间：{time.strftime("%Y-%m-%d %H:%M")}')
    a('')
    a('新对话请按这个顺序读：本文件 → `CLAUDE.md` → 需要动哪块就读那个文件夹的 `CLAUDE.md`。')
    a('')

    a('## 目录结构（**不要去 glob 根目录**，数据目录有 3000+ 文件会淹掉你）')
    a('')
    a('```')
    for ln in tree():
        a(ln)
    a('```')
    a('')

    a('## 现在健康吗')
    a('')
    h = health()
    _HEALTH_CACHE['data'] = h
    a(f'`{h["summary"]}`')
    if h['problems']:
        a('')
        for p in h['problems'][:6]:
            a(f'- {p}')
    a('')

    a('## 👉 下一步该做什么')
    a('')
    for s in next_step():
        a(f'- {s}')
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
    a(f'**积木层 `shared/`（{len(bs)} 块）**：'
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

    a('## 想深入时读哪份（**这两份是时间正序的长文件，用 tail 读末尾，别从头读**）')
    a('')
    for f, why in (('docs/踩坑记录.md', '所有踩过的坑，含根因与解法'),
                   ('docs/变更记录.md', '每次改动的来龙去脉'),
                   ('docs/架构宪法_第一性原理.md', '最高纲领：三条铁律 + 零号/首要判据'),
                   ('<某文件夹>/CLAUDE.md', '那一块的完整说明书，改哪块就读哪份')):
        size = ''
        p = os.path.join(ROOT, f)
        if os.path.exists(p):
            size = f'（{round(os.path.getsize(p) / 1024)} KB）'
        a(f'- `{f}`{size} — {why}')
    a('')

    a('## 铁律提醒')
    a('')
    a('- **【零号判据】先看真实世界，别用记忆代替调研。**'
      '涉及外部现状/具体数字/API 行为，必须查、必须测。')
    a('- 改完**先跑体检再重启服务**：`python host/doctor/health_check.py`')
    a('- 花钱、不可逆、影响 Zotero 库的操作，**先问用户**。')
    a('- 每个改动记 `docs/变更记录.md`，踩坑记 `docs/踩坑记录.md`，并 git commit。')
    return '\n'.join(L)


CLAUDE_MD = os.path.join(ROOT, 'CLAUDE.md')
AUTO_BEGIN = '<!-- AUTO:结构 开始 · 由 host/codegen/handover.py 生成，勿手改 -->'
AUTO_END = '<!-- AUTO:结构 结束 -->'

# ⚠ 认区块要用这个宽松的正则，**不能拿 AUTO_BEGIN 原样去比**。
# 标记里写着生成器自己的路径，生成器一搬家（core → host/codegen）字符串就变了，
# 旧区块认不出来 → 文档里同时躺着新旧两份结构树。实测发生过一次。
AUTO_BEGIN_RE = r'<!-- AUTO:结构 开始[^>]*-->'


def sync_claude_md():
    """把目录结构同步进 CLAUDE.md 的自动区块。

    **为什么必须写进 CLAUDE.md 而不是只写在 HANDOVER（实测得出）**：
    CLAUDE.md 是**唯一在任何工具调用之前**就进入上下文的文件。
    新会话的第一个动作往往是 glob 根目录，然后被 3000+ 个数据文件淹没 ——
    此时它还没读到 HANDOVER 里那句「不要 glob」。
    一个只能保护「已经读过它的人」的警告是没用的，必须提前到 CLAUDE.md。

    同时解决数字过时：手写的「10 块公理件」早已落后于实际的 16 块，
    而新会话若只读 CLAUDE.md 就会**自信地答错**。自动生成即永不过时。
    """
    # ⚠ 只有编程端才写 CLAUDE.md。
    #    CLAUDE.md 是版本库里的文件，而这个函数会重写它的结构区块。
    #    运行端的面板上也有「生成交接文件」按钮，用户会点 ——
    #    一点就产生本地改动，下次 git pull 必冲突（2026-08-26 真实发生过）。
    #    HANDOVER.md 本身已移出版本库，两台各生成各的，互不干扰。
    from shared.kernel import role
    if role.is_prod():          # 判据是「是不是运行端」，不是「是不是 dev」——
        # 测试端（test）也在同一台编程机器上，照样该更新 CLAUDE.md
        print('（运行端：只生成 HANDOVER.md，不改 CLAUDE.md —— 那是编程端的活）')
        return False
    if not os.path.exists(CLAUDE_MD):
        return False
    body = ['', AUTO_BEGIN, '',
            '## 项目结构（自动同步，**不要 glob 根目录**）', '',
            '> `workflow_data/` 有 3000+ 个数据文件，glob 根目录会直接淹掉你的上下文。',  # paths-exempt: 生成的文档正文
            '> 下面这棵树就是全部结构，不必再去扫。', '', '```']
    body += tree()
    body += ['```', '']
    fl = flows()
    bl = blocks()
    body += [f'**可枚举的块 {len(bl)} 个**（`tools/` 工具切片 + `shared/` 共用件，'
             f'每个都有 `__init__.py` 与 `selftest.py`）'
             + (f' · **还没切进 `tools/` 的老文件夹 {len(fl)} 个**' if fl else ''), '',
             '进度、健康状况、下一步做什么 → 见 `HANDOVER.md`', '',
             AUTO_END, '']
    block = '\n'.join(body)

    src = io.open(CLAUDE_MD, encoding='utf-8').read()
    if re.search(AUTO_BEGIN_RE, src) and AUTO_END in src:
        new = re.sub(AUTO_BEGIN_RE + r'[\s\S]*?' + re.escape(AUTO_END),
                     block.strip(), src)
    else:
        # 首次：插在第一个二级标题之前，确保足够靠前
        m = re.search(r'^## ', src, re.M)
        pos = m.start() if m else len(src)
        new = src[:pos] + block.strip() + '\n\n' + src[pos:]
    if new != src:
        io.open(CLAUDE_MD, 'w', encoding='utf-8', newline='').write(new)
    return True


def main():
    txt = build()
    if '--print' in sys.argv:
        print(txt)
        return
    io.open(HANDOVER, 'w', encoding='utf-8', newline='').write(txt + '\n')
    ok = sync_claude_md()
    print(f'已生成 {HANDOVER}（{len(txt)} 字符）'
          + ('；CLAUDE.md 的结构区块已同步' if ok else ''))


if __name__ == '__main__':
    main()
