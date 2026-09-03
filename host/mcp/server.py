# -*- coding: utf-8 -*-
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
"""host.mcp.server · 平台的 MCP 服务：把各工具切片的 `mcp.py` 聚合成一个服务。

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
from shared.kernel.cli import flag
from host.mcp import registry
from host.mcp.stdio import MCPStdioServer

VERSION = '0.2.0'          # 0.1 = 手写 10 个 zotero 工具；0.2 = 按工具切片聚合
NAME = 'zotero-platform'


def build_server():
    """装配服务：先挂服务自己的 ping，再把各工具切片挂上去。"""
    s = MCPStdioServer(NAME, VERSION)
    s.register_tool('ping', '存活检查：确认 MCP 服务本身在跑。',
                    {'type': 'object', 'properties': {}},
                    lambda a: {'text': f'{NAME} {VERSION} 在跑',
                               'structured': {'ok': True, 'server': NAME,
                                              'version': VERSION}})
    s._report = registry.register_all(s)      # --list 与自测要看这份账
    return s


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

    print('\n■ 工具切片')
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


def main():
    """入口：--list 打印清单（给人看），否则启动 MCP stdio 服务。"""
    s = build_server()
    if flag('--list'):
        return print_list(s)
    s.serve()
    return 0


if __name__ == '__main__':
    sys.exit(main())
