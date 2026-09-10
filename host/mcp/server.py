# -*- coding: utf-8 -*-
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
"""host.mcp.server · 平台的 MCP 服务：把各工具包的 `mcp.py` 聚合成一个服务。

MCP 客户端（Claude Code / Cursor / DSH…）以 stdio 子进程方式启动本文件。
服务端自己**不知道有哪些工具** —— 它去 `tools/*/tool.toml` 现读现挂
（见 `host/mcp/registry.py`）。加能力不用碰这个文件。

启动方式（给 MCP 客户端配）：
    command: python
    args:    [ <项目根>/host/mcp/server.py ]

人看清单：`python host/mcp/server.py --list`

三类的分工就是安全边界（REBUILD.md R4 判据，registry.check() 强制）：
  tool     模型可以自己调 —— **只读且免费**
  resource 模型可以自己读 —— 只读数据（对比表这种）
  prompt   **由人在客户端里点** —— 花钱的、有副作用的一律走这里
"""
from shared.kernel.cli import flag, opt
from host.mcp import registry
from host.mcp.stdio import MCPStdioServer

VERSION = '0.2.0'          # 0.1 = 手写 10 个 zotero 工具；0.2 = 按工具包聚合
NAME = 'zotero-platform'


def build_server():
    """装配服务：先挂服务自己的 ping，再把各工具包挂上去。"""
    s = MCPStdioServer(NAME, VERSION)
    s.register_tool('ping', '存活检查：确认 MCP 服务本身在跑。',
                    {'type': 'object', 'properties': {}},
                    lambda a: {'text': f'{NAME} {VERSION} 在跑',
                               'structured': {'ok': True, 'server': NAME,
                                              'version': VERSION}})
    # 「取全文跑到哪了」——**平台自身的运行状态**，跟 ping 同类，所以挂在这里。
    # 为什么不挂在 getpdf 工具包里（2026-09-08）：那个工具包是「花钱」档，
    # 守卫要求它的每个 tool 都带 confirm；而轮询工具每次弹窗，
    # 等于把「后台发起 + 轮询」这个设计废掉。只读的东西不该被工具包的档位连坐。
    s.register_tool('fulltext_status',
                    '看后台取全文跑到哪了（只读、零成本、不弹窗）。'
                    '跑完会给出每篇的 id 与来源，然后用 library_outline 看菜单。',
                    {'type': 'object', 'properties': {}},
                    lambda a: {'text': _fulltext_status()})
    # 「这篇精读到哪一步了」——同一条判例（2026-09-10）：deepread 那个工具包是
    # 「花钱」档，守卫要求它注册的每个 tool 都 confirm；而查进度是**发起之后必然
    # 要反复做的动作**，每次弹窗等于把「排队 + 轮询」这个设计废掉。
    # 只读、零成本的东西不该被工具包的档位连坐，所以挂在平台层。
    s.register_tool('deepread_status',
                    '看某篇文献精读到哪一步了（只读、零成本、不弹窗）。'
                    '同时报 Zotero 的状态标签与本地产物 —— 两者可能不一致'
                    '（回写失败时产物已经在盘上了）。用 deepread_request 排队之后靠它轮询。',
                    {'type': 'object',
                     'properties': {'itemKey': {'type': 'string',
                                                'description': 'Zotero 条目 key'}},
                     'required': ['itemKey']},
                    lambda a: {'text': _deepread_status(a.get('itemKey') or ''),
                               'structured': _deepread_status_raw(a.get('itemKey') or '')})
    s._report = registry.register_all(s)      # --list 与自测要看这份账
    return s


def _deepread_status_raw(key):
    from tools import deepread
    return deepread.status(key)


def _deepread_status(key):
    """→ 给人/模型看的一行话。不猜、不报错：查不到就说查不到。"""
    if not key:
        return '要给 itemKey（Zotero 条目 key，8 位字母数字）。'
    d = _deepread_status_raw(key)
    made = []
    if d['summary']:
        made.append('正文精读')
    if d['summary_full']:
        made.append('正文+SI 合并版')
    return ('{0}{1}\n  状态标签：{2}\n  本地产物：{3}{4}'.format(
        key, ('　' + d['title']) if d['title'] else '',
        d['tag'] or '（没有）', '、'.join(made) or '（还没有）',
        ('\n  ' + d['note']) if d.get('note') else ''))


def _fulltext_status():
    """读进度文件。没有就说没有 —— 不猜、不报错。"""
    import io
    import json
    import os

    from shared.kernel import paths
    from tools.getpdf import fulltext as F

    path = paths.runtime('fulltext_progress.json')
    if not os.path.exists(path):
        return '还没有跑过取全文（paper_fulltext）。'
    try:
        d = json.load(io.open(path, encoding='utf-8'))
    except Exception:
        return '进度文件正在写，读不完整。过几秒再看一次。'
    head = ('%d/%d 篇已处理，用时 %.0f 秒%s\n'
            % (d.get('finished', 0), d.get('total', 0), d.get('elapsed', 0),
               '' if d.get('done') else '（还在跑）'))
    return head + F.summarize(d.get('results') or [])


def print_list(s):
    """给人看的清单：三类分开列，末尾报清单与实际注册对不对得上。"""
    print(f'{NAME} {VERSION}\n')
    print(f'■ 工具 tool（模型可自己调，只读且免费）  {len(s._tools)} 个')
    for t in s._tools:
        print(f"    {t['name']:<26} {t['description']}")
    print(f'\n■ 资源 resource（模型可自己读的只读数据）  {len(s._resources)} 个')
    for r in s._resources:
        print(f"    {r['uri']:<26} {r['description']}")
    print(f'\n■ 提示词 prompt（花钱/有副作用，由人在客户端里点）  {len(s._prompts)} 个')
    for p in s._prompts:
        args = ', '.join(a['name'] + ('*' if a.get('required') else '')
                         for a in p['arguments'])
        print(f"    {p['name']:<26} {p['description']}" + (f'   ({args})' if args else ''))

    print('\n■ 工具包')
    for name, man, got in s._report:
        kinds = ' '.join(f'{k}×{len(v)}' for k, v in got.items() if v) or '（没注册东西）'
        print(f"    {name:<12} expose={man.get('expose'):<9} {kinds}")

    problems = registry.check(s._report, server=s)
    if problems:
        print('\n✗ 清单不自洽：')
        for p in problems:
            print('    - ' + p)
        return 1
    print('\n✓ 清单与各 tool.toml 一致')
    return 0


def _claim_stdout_for_protocol():
    """把 stdout 私有化给协议用，再让 `sys.stdout` 指向 stderr。返回真正的 stdout。

    **stdio 传输里 stdout 是协议通道，只许跑 JSON-RPC。** 而工具用
    `shared.kernel.log.get_logger()` 打的日志默认就往 stdout 写 ——
    `getpdf_one` 取到 PDF 时打的那行「DOI → 路径（N 字节）」直接混进了报文流里，
    宽容的客户端逐行解析能扛住，严格的会当场断会话（踩坑 #151）。

    为什么必须在**注册工具之前**做：日志器是模块级的
    （`tools/getpdf/__init__.py` 里 `log = get_logger('getpdf')`），
    `logging.StreamHandler(sys.stdout)` 在构造时就抓住了流对象，
    等 `serve()` 再换已经晚了。

    为什么不放进 `MCPStdioServer.__init__`：`--list` 是给人看的，那条路径要真 stdout。
    所以由入口按模式决定，别让协议层替所有调用方做这个决定。
    """
    real = sys.stdout
    try:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    sys.stdout = sys.stderr      # 之后任何 print / 日志都落到 stderr，不污染协议
    return real


def main():
    """入口：--list 看清单 · --http 起 HTTP 服务 · 默认 stdio。

    **两条腿的区别不在协议，在「谁来跑这个进程」**：
      · stdio  —— 客户端把本服务当子进程拉起来。客户端在哪台机器，进程就在哪台。
                  从 SSH 拉起时会落进**网络登录会话**，读不到系统凭据库（踩坑 #101），
                  于是所有要密钥的工具（写 Zotero、调大模型）都用不了。
      · http   —— 服务由**主力机自己**以交互式会话常驻（跟 watcher 一样），
                  凭据库正常可读，32 个工具全部可用；客户端只是连上来。
                  跨机访问走 SSH 端口转发，不开公网端口。
    """
    if flag('--list'):
        return print_list(build_server())        # 给人看的那条路，走真 stdout
    if flag('--http'):
        from host.mcp import http_transport as mcp_http
        # HTTP 那条腿不占用 stdout，日志照常打屏幕，所以不做私有化切换
        return mcp_http.serve(build_server(),
                              port=int(opt('--port') or mcp_http.DEFAULT_PORT)) or 0
    protocol_out = _claim_stdout_for_protocol()  # ⚠ 必须在 build_server() 之前
    s = build_server()
    s.serve(out=protocol_out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
