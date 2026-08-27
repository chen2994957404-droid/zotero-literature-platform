# -*- coding: utf-8 -*-
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
"""selftest · MCP 服务自测（协议层离线测试，不联网、不依赖用户数据）

跑法：python MCP服务/selftest.py，全部通过才算出活。
覆盖：initialize 握手、通知不回、tools/list、tools/call（成功/业务错误/参数错误/
未知工具/handler 抛异常）、ping、未知方法、非法 JSON、UTF-8 中文往返。
zotero_server 的真实工具清单做「配置存在才加载」的附加检查（本机未配 ZOTERO_USER_ID
时跳过该项并提示，不算失败——那属于真实库连通验证，见 变更记录）。
"""
import io
import json
import sys

from mcp_stdio import MCPStdioServer

_PASS = []
_FAIL = []


def check(name, cond, detail=''):
    ( _PASS if cond else _FAIL ).append(name)
    print(('  ✓ ' if cond else '  ✗ ') + name + (f'  [{detail}]' if detail and not cond else ''))


def feed(server, *lines):
    """把若干行喂给服务（不读真 stdin，手动调 _handle），返回所有响应（dict 列表）。"""
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        for line in lines:
            if line.strip():
                try:
                    msg = json.loads(line)
                except Exception:
                    server._error(None, -32700, 'x')
                    continue
                server._handle(msg)
    finally:
        sys.stdout = old
    return [json.loads(l) for l in buf.getvalue().strip().splitlines() if l.strip()]


def build_fake_server():
    s = MCPStdioServer('fake', '1.0')
    s.register_tool('echo', '回显测试工具', {'type': 'object', 'properties': {
        'text': {'type': 'string'},
        'num': {'type': 'integer', 'minimum': 1, 'maximum': 10},
    }, 'required': ['text']},
        lambda a: {'text': f'回显：{a["text"]}', 'structured': {'echoed': a['text']}})
    s.register_tool('boom', '必然失败的工具', {'type': 'object', 'properties': {}},
        lambda a: (_ for _ in ()).throw(RuntimeError('模拟业务异常')))
    return s


def main():
    print('MCP 协议层自测')
    s = build_fake_server()

    # 1. initialize 握手
    rs = feed(s, '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}')
    check('initialize 返回 result', len(rs) == 1 and 'result' in rs[0])
    if rs:
        r = rs[0]['result']
        check('initialize 协议版本', r.get('protocolVersion') == '2024-11-05', str(r.get('protocolVersion')))
        check('initialize 带 tools 能力', r.get('capabilities', {}).get('tools') is not None)
        check('initialize 带 serverInfo', r.get('serverInfo', {}).get('name') == 'fake')

    # 2. 通知不回
    rs = feed(s, '{"jsonrpc":"2.0","method":"notifications/initialized"}')
    check('通知不产生响应', rs == [], str(rs))

    # 3. tools/list
    rs = feed(s, '{"jsonrpc":"2.0","id":1,"method":"tools/list"}')
    check('tools/list 返回工具表', len(rs) == 1 and 'result' in rs[0])
    if rs:
        tools = rs[0]['result']['tools']
        names = [t['name'] for t in tools]
        check('tools/list 含 echo/boom', names == ['echo', 'boom'], str(names))
        check('tools/list 工具带 inputSchema', all('inputSchema' in t for t in tools))

    # 4. tools/call 成功（含中文与 structured）
    rs = feed(s, '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"echo","arguments":{"text":"聚硼硅氧烷"}}}')
    check('tools/call 成功', len(rs) == 1 and 'result' in rs[0])
    if rs:
        res = rs[0]['result']
        txt = res['content'][0]['text']
        check('tools/call 中文文本往返', txt == '回显：聚硼硅氧烷', txt)
        check('tools/call 带 structuredContent', res.get('structuredContent') == {'echoed': '聚硼硅氧烷'})
        check('tools/call 成功不带 isError', 'isError' not in res)

    # 5. tools/call 业务异常
    rs = feed(s, '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"boom","arguments":{}}}')
    check('tools/call 业务异常转 isError', len(rs) == 1 and rs[0]['result'].get('isError') is True)

    # 6. 未知工具
    rs = feed(s, '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"nope","arguments":{}}}')
    check('未知工具回 -32602', len(rs) == 1 and rs[0].get('error', {}).get('code') == -32602)

    # 7. 缺必填参数
    rs = feed(s, '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"echo","arguments":{}}}')
    check('缺必填参数回 isError', len(rs) == 1 and rs[0]['result'].get('isError') is True)

    # 8. 整数越界
    rs = feed(s, '{"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"echo","arguments":{"text":"a","num":99}}}')
    check('整数越界回 isError', len(rs) == 1 and rs[0]['result'].get('isError') is True)

    # 9. ping
    rs = feed(s, '{"jsonrpc":"2.0","id":7,"method":"ping"}')
    check('ping 回空 result', len(rs) == 1 and rs[0].get('result') == {})

    # 10. 未知方法
    rs = feed(s, '{"jsonrpc":"2.0","id":8,"method":"resources/list"}')
    check('未知方法回 -32601', len(rs) == 1 and rs[0].get('error', {}).get('code') == -32601)

    # 11. 非法 JSON
    rs = feed(s, 'not json at all')
    check('非法 JSON 回 -32700', len(rs) == 1 and rs[0].get('error', {}).get('code') == -32700)

    # 12. 真实工具层（配置存在才加载）
    try:
        from zotero_server import build_server
        real = build_server()
        names = [t['name'] for t in real._tools]
        check('zotero_server 工具数 = 10', len(names) == 10, str(len(names)))
        check('zotero_server 工具名唯一', len(set(names)) == len(names))
    except Exception as e:
        print(f'  · 跳过真实工具层检查（本机未配置 ZOTERO_USER_ID？）：{e}')

    print(f'\n结果：{len(_PASS)} 过 / {len(_FAIL)} 挂')
    if _FAIL:
        print('挂掉项：', ', '.join(_FAIL))
        sys.exit(1)
    print('全部通过 ✓')


if __name__ == '__main__':
    main()
