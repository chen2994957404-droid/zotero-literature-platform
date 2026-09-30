# -*- coding: utf-8 -*-
"""host.mcp.science · 给 Claude Science 的精简入口（HTTP 端点 `/science`）。

## 为什么单开一个（2026-09-29 用户定）

用户的判断：**Claude 这样的模型不需要一堆规矩，能拿到文献就够了。**
Claude Science 自己会检索（它有 OpenAlex），它缺的只有一样 ——
**付费墙后面的全文**。这台主力机有它没有的三样：校园网出口（教育网 211.83.153.16，
机构订阅认的是它）、一个过过人机验证的真实浏览器、MineRU 解析。

所以这里只挂「拿到 → 读」这一条线上的几件，别的（Zotero、抽取、精读、问答…）一概不给：

| 工具 | 干嘛 |
|---|---|
| `library_db_search` | 证据库里有没有这篇（零网络） |
| `library_retrieve`  | 证据库里哪一段讲了 X（向量检索） |
| `paper_fulltext`    | 给 DOI → 取正文+SI → 解析 → 返回 id 与骨架菜单（后台跑） |
| `fulltext_status`   | 轮询上面那个 |
| `library_outline` / `library_section` | 按菜单点节、段、表、图注 |
| `paper_files`       | 这篇的 PDF / SI / 全文 Markdown 在哪 —— 给 Linux 路径，Claude Science 的算力（B 机 WSL 的 science 账号）能直接读 |

## 规矩为什么几乎为零，却还留一条

完整入口 `/mcp` 给 `paper_fulltext` 打了 `confirm`（Claude Code 每次弹窗）。
这里**不打**：Claude Science 自己对每个新工具就先问人，人可以设成「总是允许」。

**唯一留下的一条是服务端强制的、不是写给模型看的**：取全文串行、每篇隔 20 秒、
一次最多 3 篇、**同一时刻只许一个取全文作业**。理由不是不信任模型 ——
出版商风控封的是**整个学校的出口 IP**，代价由全校承担。
「同一时刻只许一个」是这里新加的：`paper_fulltext` 后台 spawn 子进程，
MCP 的串行锁只锁到「发起」为止，模型并发调三次就是三个作业同时敲出版商，
20 秒间隔形同虚设。

## 挂法

不另起进程、不另开端口：`server.py --http` 同一个服务上多一个端点，
A 机那条现成的隧道（`LiteraturePlatformTunnel`，8778）直接可用。
Claude Science 里：Settings → Connectors → Add connector → Remote，
URL `http://127.0.0.1:8778/science`，传输选 Streamable HTTP。
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass

import time

from host.mcp.stdio import MCPStdioServer

ENDPOINT = '/science'
NAME = 'literature-science'
VERSION = '0.1.0'

# 从完整服务里借来的工具（名字不改 —— 两边说同一种话，日志好对）
# 2026-09-29 用户：「工具给真正有用的就行，描述写得好不等于起作用」。判据：它自己做不到、或做起来很费劲的才给。
#   留：取全文 + 轮询（校园网出口，它独有）、库里有没有（1100 篇的目录）、按意思找段落（向量库，它重建不起）、
#       骨架菜单 + 按节取（跨几十篇只看要的那节；出处能写成 id + s5.p3）、文件路径（它的算力能直接读原件）
#   去：library_refs —— 它有 OpenAlex，顺引用自己查更全
BORROW = ('library_db_search', 'library_retrieve', 'library_outline',
          'library_section', 'paper_fulltext', 'fulltext_status', 'ping')

# 进度文件多久没动就当那个作业已经死了（一篇取 + 解析通常 1 分钟内会写一次进度）
STALE_SECS = 600

INSTRUCTIONS = """\
这是一位材料学研究者（聚硼硅氧烷 / 动态键弹性体）的文献证据库，跑在他校园网里的主力机上。
你自己检索（OpenAlex 等）；这里负责你做不到的那件事：**拿到付费墙后面的全文**，并按节读。

- 先 `library_db_search` 看库里有没有（零成本）；有就直接读。
- 没有就 `paper_fulltext`（给 DOI，一次最多 3 篇，后台跑）→ `fulltext_status` 轮询 → 拿到 id。
  取全文走学校的机构订阅：串行、每篇隔 20 秒、同一时刻只跑一个作业 —— 这是服务端定死的，
  因为出版商风控封的是整个学校的出口 IP。一篇（取 + 解析）大约 1 分钟。
- 读：`library_outline` 看骨架菜单 → `library_section` 按地址取节 / 段（s5.p3）/ 表（t1）/ 图注（f2）；SI 传 si=true。
- 要原始 PDF / 图 / 整篇 Markdown 自己处理：`paper_files` 给出 Linux 路径，你的 SSH 算力（zotero-b）能直接读。
- 结论带出处：文献 id + 节地址，或 DOI。给用户看的用中文。"""


def _progress_path():
    from shared.kernel import paths
    return paths.runtime('fulltext_progress.json')


def running_job(path=None, now=None):
    """有没有一个取全文作业正在跑 → 给人看的一句话，或 ''。

    判据：进度文件存在、`done` 为假、而且最近 STALE_SECS 秒内还写过（死掉的作业不挡路）。
    """
    import io
    import json
    path = path or _progress_path()
    if not os.path.exists(path):
        return ''
    try:
        d = json.load(io.open(path, encoding='utf-8'))
    except Exception:
        return '有一个取全文作业正在写进度'      # 正在写 = 正在跑
    if d.get('done'):
        return ''
    age = (now or time.time()) - os.path.getmtime(path)
    if age > STALE_SECS:
        return ''
    return '上一个取全文作业还在跑（%d/%d 篇）' % (d.get('finished', 0), d.get('total', 0))


def _guarded_fulltext(handler):
    """包住 paper_fulltext：真要去取（allowFetch 且后台）时，先确认没有别的作业在跑。"""
    def run(a):
        if a.get('allowFetch', True) and a.get('background', True):
            busy = running_job()
            if busy:
                return busy + '。等它跑完再发起下一批 —— 用 fulltext_status 看进度（约每篇 1 分钟）。'
        return handler(a)
    return run


def to_wsl(path):
    """Windows 路径 → WSL 里看到的路径（D:\\a\\b → /mnt/d/a/b）。不是盘符路径就原样返回。"""
    p = (path or '').replace('\\', '/')
    if len(p) >= 2 and p[1] == ':':
        return '/mnt/' + p[0].lower() + p[2:]
    return p


def paper_files(key):
    """这篇手上有哪些文件 → [(说明, Windows 路径)]。只列真在盘上的。"""
    from shared.kernel import paths
    cands = [('正文 PDF', paths.local_pdf(key)),
             ('SI 原件', paths.find_local_si(key)),
             ('正文 Markdown（解析稿，图在同目录 images/）', paths.fulltext(key)),
             ('SI Markdown', paths.si_fulltext(key)),
             ('中文精读 HTML', paths.summary(key))]
    return [(what, p) for what, p in cands if p and os.path.exists(p)]


def _resolve(k):
    """itemKey 可以是证据库 id，也可以是 DOI（外部 agent 手里常常只有 DOI）。"""
    from shared.kernel import catalog, paths
    k = (k or '').strip()
    if k.startswith('10.') and '/' in k:
        pid = catalog.find(k)
        if not pid:
            raise ValueError(f'证据库里没有 DOI {k}（先用 paper_fulltext 把它拿进来）')
        return pid
    paths.check_key(k)
    return k


def _paper_files_text(a):
    pid = _resolve(a.get('itemKey'))
    got = paper_files(pid)
    if not got:
        return f'{pid}：盘上还没有这篇的任何文件（用 paper_fulltext 取）。'
    return (f'{pid} 的文件（左边是你 SSH 算力 zotero-b 里的路径，只读用）：\n'
            + '\n'.join(f'  {to_wsl(p)}　　{what}' for what, p in got))


def build(full):
    """从完整服务 `full` 里借工具，装成给 Claude Science 的精简服务。"""
    s = MCPStdioServer(NAME, VERSION, instructions=INSTRUCTIONS)
    have = {t['name']: t for t in full._tools}
    missing = [n for n in BORROW if n not in have]
    if missing:
        # 借不到 = 某个工具包没挂上；喊出来，别让它悄悄少一个工具（踩坑 #173 同类）
        print(f'⚠ /science 少了这些工具（完整服务里没有）：{", ".join(missing)}', file=sys.stderr)
    for n in BORROW:
        t = have.get(n)
        if not t:
            continue
        h = _guarded_fulltext(t['handler']) if n == 'paper_fulltext' else t['handler']
        s.register_tool(n, t['description'], t['inputSchema'], h)   # 不打 confirm：Claude Science 自己会问人
    s.register_tool(
        'paper_files',
        '这篇文献手上有哪些文件（正文 PDF / SI 原件 / 解析好的 Markdown / 中文精读），'
        '给出你 SSH 算力（zotero-b，B 机 WSL）里能直接读的路径。'
        '要自己看图、跑脚本、整篇处理时用；只是读几节用 library_section 更省。',
        {'type': 'object', 'properties': {
            'itemKey': {'type': 'string', 'description': '文献 id，或 DOI'}},
         'required': ['itemKey']},
        _paper_files_text)
    return s
