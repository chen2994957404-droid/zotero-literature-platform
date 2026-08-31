# -*- coding: utf-8 -*-
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
"""selftest · MCP 服务自测（协议层离线测试，不联网、不依赖用户数据）

跑法：python host/mcp/selftest.py，全部通过才算出活。
覆盖：initialize 握手、通知不回、tools/list、tools/call（成功/业务错误/参数错误/
未知工具/handler 抛异常）、resources/list+read、prompts/list+get、ping、未知方法、
非法 JSON、UTF-8 中文往返；最后校验真实聚合（各 tools/*/tool.toml 与实际注册自洽）。
"""
import io
import json
import sys

from host.mcp.stdio import MCPStdioServer

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

    # 10. 未知方法（R4 起 resources/list 是真方法了，这里换一个真不存在的）
    rs = feed(s, '{"jsonrpc":"2.0","id":8,"method":"completion/complete"}')
    check('未知方法回 -32601', len(rs) == 1 and rs[0].get('error', {}).get('code') == -32601)

    # 11. 非法 JSON
    rs = feed(s, 'not json at all')
    check('非法 JSON 回 -32700', len(rs) == 1 and rs[0].get('error', {}).get('code') == -32700)

    # 12. 资源（R4 新增）
    s2 = build_fake_server()
    s2.register_resource('fake://a.md', 'a.md', '一份假资源', lambda: '内容：聚硼硅氧烷')
    rs = feed(s2, '{"jsonrpc":"2.0","id":9,"method":"resources/list"}')
    check('resources/list 列出资源',
          len(rs) == 1 and [r['uri'] for r in rs[0]['result']['resources']] == ['fake://a.md'])
    rs = feed(s2, '{"jsonrpc":"2.0","id":10,"method":"resources/read","params":{"uri":"fake://a.md"}}')
    c = rs[0]['result']['contents'][0] if rs and 'result' in rs[0] else {}
    check('resources/read 回 contents[{uri,mimeType,text}]',
          c.get('uri') == 'fake://a.md' and c.get('text') == '内容：聚硼硅氧烷', str(c)[:80])
    rs = feed(s2, '{"jsonrpc":"2.0","id":11,"method":"resources/read","params":{"uri":"fake://nope"}}')
    check('未知资源回 -32602', len(rs) == 1 and rs[0].get('error', {}).get('code') == -32602)

    # 13. 提示词（R4 新增）
    s3 = build_fake_server()
    s3.register_prompt('greet', '打个招呼',
                       [{'name': 'who', 'description': '跟谁', 'required': True}],
                       lambda a: f'你好，{a["who"]}')
    rs = feed(s3, '{"jsonrpc":"2.0","id":12,"method":"prompts/list"}')
    ps = rs[0]['result']['prompts'] if rs and 'result' in rs[0] else []
    check('prompts/list 列出提示词与参数',
          len(ps) == 1 and ps[0]['name'] == 'greet' and ps[0]['arguments'][0]['required'] is True,
          str(ps)[:90])
    rs = feed(s3, '{"jsonrpc":"2.0","id":13,"method":"prompts/get","params":{"name":"greet","arguments":{"who":"世界"}}}')
    m = rs[0]['result']['messages'][0] if rs and 'result' in rs[0] else {}
    check('prompts/get 回 messages[{role,content}]',
          m.get('role') == 'user' and m.get('content', {}).get('type') == 'text'
          and m['content']['text'] == '你好，世界', str(m)[:90])
    rs = feed(s3, '{"jsonrpc":"2.0","id":14,"method":"prompts/get","params":{"name":"greet","arguments":{}}}')
    check('提示词缺必填参数回 -32602',
          len(rs) == 1 and rs[0].get('error', {}).get('code') == -32602)

    # 14. 能力声明只报真的有的
    s4 = MCPStdioServer('bare', '1.0')
    rs = feed(s4, '{"jsonrpc":"2.0","id":15,"method":"initialize","params":{}}')
    caps = rs[0]['result']['capabilities'] if rs else {}
    check('没注册资源就不声明 resources 能力', 'resources' not in caps and 'prompts' not in caps,
          str(caps))

    # 15. 真实聚合：各 tools/*/tool.toml 与实际注册自洽
    from host.mcp import registry
    from host.mcp.server import build_server
    real = build_server()
    names = [t['name'] for t in real._tools]
    check('聚合后工具名唯一', len(set(names)) == len(names))
    check('聚合到了 tools（至少 library 的 9 个 + ping）', len(names) >= 10, str(len(names)))
    problems = registry.check(real._report)
    check('工具清单自洽（tool.toml ↔ 实际注册）', not problems,
          ' / '.join(problems[:3]))

    print(f'\n结果：{len(_PASS)} 过 / {len(_FAIL)} 挂')
    if _FAIL:
        print('挂掉项：', ', '.join(_FAIL))
        sys.exit(1)
    print('全部通过 ✓')


if __name__ == '__main__':
    main()
