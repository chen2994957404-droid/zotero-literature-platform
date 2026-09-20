# -*- coding: utf-8 -*-
"""生成《系统认识：各块的机制与弱点》—— 给 agent 的「这块大概怎么运转、靠什么、容易在哪坏」。

**为什么要有它**（2026-09-16 用户提的）：项目在做大，agent 不必记细节，但出问题时得知道
「这块是怎么做的 → 所以可能坏在哪」。这些信息本来就在，只是散在三处：
每块的文档字符串（它是什么）、`INCIDENTS.md` / 踩坑记录（它哪里坏过）、git（它最近动过什么）。
本生成器把三处**按块**拼到一起，每次改完随 handover 一起刷新，永不过时。

每块一段：一句话 · 外部依赖（它 import 了哪些 adapters / 第三方）· 写哪些数据 · 踩过的坑 · 最近改动。
「容易在哪坏」不靠人写：外部依赖 + 坑的历史就是答案。

用法:
  python host/codegen/mechanisms.py           写 docs/reference/系统认识_各块机制与弱点.md
  python host/codegen/mechanisms.py --print
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass
import ast
import io
import re
import time

from shared.kernel.cli import flag
from shared.kernel.paths import ROOT
from shared.kernel.subproc import out as _out

OUT = os.path.join(ROOT, 'docs', 'reference', '系统认识_各块机制与弱点.md')
INCIDENTS = os.path.join(ROOT, 'docs', 'incidents', '踩坑记录.md')
RINGS = (('tools', '工具'), ('host', '平台自身'), ('shared/adapters', '外接口'),
         ('shared/domain', '纯逻辑'), ('shared/kernel', '基础设施'))
# 第三方库 → 它背后的外部世界（只列会「变」的那些；标准库不算）
THIRD = {'fitz': 'PyMuPDF（读 PDF）', 'docx': 'python-docx', 'chromadb': 'Chroma 向量库',
         'requests': 'HTTP', 'websocket': 'WebSocket', 'sentence_transformers': '本地向量模型',
         'torch': 'PyTorch', 'numpy': 'numpy', 'PIL': 'Pillow', 'bs4': 'BeautifulSoup', 'lxml': 'lxml'}


def _blocks():
    """[(环, 名字, 目录)]。"""
    out = []
    for rel, label in RINGS:
        d = os.path.join(ROOT, rel)
        if not os.path.isdir(d):
            continue
        for n in sorted(os.listdir(d)):
            p = os.path.join(d, n)
            if n.startswith(('_', '.')) or n == 'tests':
                continue
            if os.path.isdir(p) and os.path.exists(os.path.join(p, '__init__.py')):
                out.append((label, rel + '/' + n, p))
            elif rel == 'shared/kernel' and n.endswith('.py'):
                out.append((label, rel + '/' + n, p))
    return out


def _pyfiles(p):
    if os.path.isfile(p):
        return [p]
    out = []
    for r, ds, fs in os.walk(p):
        ds[:] = [d for d in ds if d not in ('tests', '__pycache__', 'evals', 'prompts')]
        out += [os.path.join(r, f) for f in fs if f.endswith('.py') and f != 'selftest.py']
    return out


def _one_liner(p):
    """块的一句话：__init__.py（或文件）文档字符串第一行。"""
    f = p if os.path.isfile(p) else os.path.join(p, '__init__.py')
    try:
        doc = ast.get_docstring(ast.parse(io.open(f, encoding='utf-8').read())) or ''
    except Exception:
        return ''
    first = doc.strip().split('\n')[0].strip()
    return re.sub(r'^[\w./]+\s*[·—-]+\s*', '', first)[:110]


def _imports(files):
    """(用到的 adapters, 用到的 kernel 块, 第三方) —— 从 import 语句抓。"""
    ad, ke, th, dom = set(), set(), set(), set()
    for f in files:
        try:
            tree = ast.parse(io.open(f, encoding='utf-8').read())
        except Exception:
            continue
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module + '.' + a.name for a in node.names]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            for nm in names:
                parts = nm.split('.')
                if parts[:2] == ['shared', 'adapters'] and len(parts) > 2:
                    ad.add(parts[2])
                elif parts[:2] == ['shared', 'kernel'] and len(parts) > 2:
                    ke.add(parts[2])
                elif parts[:2] == ['shared', 'domain'] and len(parts) > 2:
                    dom.add(parts[2])
                elif parts[0] in THIRD:
                    th.add(THIRD[parts[0]])
                elif parts[0] in ('urllib', 'http', 'socket') and any('urlopen' in x or 'HTTPSConnection' in x for x in names):
                    th.add('直接 HTTP')
    return sorted(ad), sorted(ke), sorted(th), sorted(dom)


def _data_written(files):
    """写哪些数据：从 `paths.xxx(` 的调用名抓（不区分读写，但足以说明「它碰哪些数据」）。"""
    used = set()
    for f in files:
        try:
            txt = io.open(f, encoding='utf-8').read()
        except Exception:
            continue
        used |= set(re.findall(r'\bpaths\.([a-z_]+)\(', txt))
        used |= {m for m in re.findall(r'\bpaths\.([A-Z_]{3,})\b', txt)}
    return sorted(used)


def _pitfalls():
    """踩坑记录 → [(编号, 标题, 正文)]。"""
    try:
        txt = io.open(INCIDENTS, encoding='utf-8').read()
    except Exception:
        return []
    out = []
    for m in re.finditer(r'^## 踩坑 #(\d+)[：:](.*?)$([\s\S]*?)(?=^## 踩坑 #|\Z)', txt, re.M):
        out.append((int(m.group(1)), m.group(2).strip(), m.group(3)))
    return out


def _pitfalls_for(name, pits):
    """跟这块有关的坑：正文或标题里**明确**提到了它（限定名、反引号名、或词边界匹配的长名）。

    短名（ask / jobs / log）只认限定形式，否则 "ask" 会匹配到一半的记录。
    """
    base = name.split('/')[-1].replace('.py', '')
    pats = [re.escape(name), re.escape(name.replace('/', '.')), '`%s`' % re.escape(base),
            re.escape(base) + '/']
    if len(base) >= 6:
        pats.append(r'b%sb' % re.escape(base))
    extra = {'pdf_fetch': ['取件', '取全文'], 'pdf_parse': ['MineRU'], 'zotero_client': ['Zotero API', '附件'],
             'watcher': ['看门狗', '心跳'], 'llm_client': ['DeepSeek', 'Ollama'], 'vectordb': ['chromadb', '向量库'],
             'embed': ['bge-m3', '向量化'], 'figure_crop': ['裁图'], 'heartbeat': ['心跳'], 'budget': ['账本', '额度']}
    pats += [re.escape(x) for x in extra.get(base, [])]
    rx = re.compile('|'.join(pats))
    hits = [(n, t) for n, t, body in pits if rx.search(t) or rx.search(body)]
    return hits[-6:]


def _last_changes(rel, n=3):
    raw = _out(['git', 'log', f'-{n}', '--pretty=format:%ad|%s', '--date=format:%Y-%m-%d', '--', rel],
               timeout=30, default='')
    rows = []
    for ln in raw.split('\n'):
        if '|' in ln:
            d, _, s = ln.partition('|')
            rows.append('%s %s' % (d, s.strip()[:70]))
    return rows


def build():
    pits = _pitfalls()
    lines = ['# 系统认识：各块的机制与弱点',
             '',
             '<!-- 由 host/codegen/mechanisms.py 生成，**别手改**。改源：各块的文档字符串 / 踩坑记录 / git -->',
             '',
             '给 agent 的地图：**每块大概怎么运转、靠什么、容易在哪坏**。不必记细节，出问题时先来这里定位。',
             '「容易在哪坏」不靠人写 —— 一块的外部依赖 + 它踩过的坑，就是它的弱点清单。',
             '',
             '生成于 %s。共 %d 块。' % (time.strftime('%Y-%m-%d %H:%M'), 0),
             '']
    ring_now = None
    count = 0
    for label, rel, p in _blocks():
        files = _pyfiles(p)
        if not files:
            continue
        count += 1
        if label != ring_now:
            ring_now = label
            lines += ['', '## %s（%s）' % (label, rel.rsplit('/', 1)[0] if '/' in rel else rel), '']
        ad, ke, th, dom = _imports(files)
        data = _data_written(files)
        hits = _pitfalls_for(rel, pits)
        chg = _last_changes(rel)
        lines.append('### `%s`' % rel)
        one = _one_liner(p)
        if one:
            lines.append('%s' % one)
        dep = []
        if ad:
            dep.append('外接口 ' + '、'.join(ad))
        if th:
            dep.append('第三方 ' + '、'.join(th))
        if dom:
            dep.append('纯逻辑 ' + '、'.join(dom))
        lines.append('- **靠什么**：%s' % ('；'.join(dep) if dep else '只靠标准库与 kernel（不联网）'))
        if data:
            lines.append('- **碰哪些数据**：%s' % '、'.join('`%s`' % d for d in data[:14])
                         + ('…' if len(data) > 14 else ''))
        if hits:
            lines.append('- **踩过的坑**（弱点在这里）：' + '；'.join(
                '#%d %s' % (n, re.sub(r'[（(]\d{4}.*$', '', t)[:44]) for n, t in hits))
        else:
            lines.append('- **踩过的坑**：还没有记录在案的')
        if chg:
            lines.append('- **最近改动**：' + ' ｜ '.join(chg))
        lines.append('')
    lines[7] = '生成于 %s。共 %d 块。' % (time.strftime('%Y-%m-%d %H:%M'), count)
    return '\n'.join(lines) + '\n'


def main():
    txt = build()
    if flag('--print'):
        print(txt)
        return 0
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    io.open(OUT, 'w', encoding='utf-8').write(txt)
    print('写好：%s（%d 行）' % (os.path.relpath(OUT, ROOT), txt.count('\n')))
    return 0


if __name__ == '__main__':
    sys.exit(main())
