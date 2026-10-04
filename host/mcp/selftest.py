# -*- coding: utf-8 -*-
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
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
    # 踩坑 #150：handler 返回裸字符串是最容易犯的错。以前它会炸成协议级
    # 「内部错误」且不带工具名。下面两个工具把「宽容收下」和「其它类型要报清楚」
    # 都钉住。
    s.register_tool('bare_str', '返回裸字符串的工具', {'type': 'object', 'properties': {}},
        lambda a: '我是一个裸字符串')
    s.register_tool('bad_type', '返回错误类型的工具', {'type': 'object', 'properties': {}},
        lambda a: 42)
    # 踩坑 #151：工具往 stdout 打日志会污染报文流。协议流必须是私有的。
    s.register_tool('noisy', '往 stdout 打日志的工具', {'type': 'object', 'properties': {}},
        lambda a: (print('[日志] 我污染了 stdout'), {'text': '干完了'})[1])
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
        check('tools/list 按注册顺序列出全部假工具',
              names == ['echo', 'boom', 'bare_str', 'bad_type', 'noisy'], str(names))
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

    # 5b. handler 返回裸字符串 → 宽容收下，不许炸（踩坑 #150）
    rs = feed(s, '{"jsonrpc":"2.0","id":31,"method":"tools/call","params":{"name":"bare_str","arguments":{}}}')
    ok = (len(rs) == 1 and 'result' in rs[0]
          and rs[0]['result']['content'][0]['text'] == '我是一个裸字符串'
          and not rs[0]['result'].get('isError'))
    check('handler 返回裸字符串也能用（不炸成协议错误）', ok, str(rs[:1])[:120])

    # 5c. handler 返回其它类型 → 报成工具错误，且**必须带工具名**
    rs = feed(s, '{"jsonrpc":"2.0","id":32,"method":"tools/call","params":{"name":"bad_type","arguments":{}}}')
    res = rs[0].get('result', {}) if rs else {}
    txt = (res.get('content') or [{}])[0].get('text', '')
    check('handler 返回错误类型 → isError 而非协议错误',
          len(rs) == 1 and 'error' not in rs[0] and res.get('isError') is True, txt[:80])
    check('失败信息里带工具名（不带就没法排查）', 'bad_type' in txt, txt[:80])

    # 5d. 协议流必须私有：工具往 stdout 打的东西不许混进报文（踩坑 #151）
    proto = io.StringIO()
    s._out = proto
    noise = io.StringIO()
    _old = sys.stdout
    sys.stdout = noise                 # 模拟入口把 sys.stdout 指向 stderr 之后的样子
    try:
        s._handle(json.loads(
            '{"jsonrpc":"2.0","id":33,"method":"tools/call",'
            '"params":{"name":"noisy","arguments":{}}}'))
    finally:
        sys.stdout = _old
        s._out = None
    lines = [l for l in proto.getvalue().splitlines() if l.strip()]
    clean = True
    for l in lines:
        try:
            json.loads(l)
        except Exception:
            clean = False
    check('协议流里每一行都是合法 JSON（工具的日志没混进来）',
          clean and len(lines) == 1, repr(proto.getvalue())[:100])
    check('工具打的日志确实落在了另一条流上', '我污染了 stdout' in noise.getvalue())

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

    # 16. HTTP 传输（2026-09-09）。**只绑 127.0.0.1、端口取 0 让系统随便给**，
    #     所以它仍然满足「不联网、不依赖用户数据」——绑本机不是联网，也不会撞端口。
    #     测的是对着 2025-03-26 规范的那几条硬要求。
    import threading
    import urllib.error
    import urllib.request
    from http.server import ThreadingHTTPServer

    from host.mcp import http_transport as H

    check('Origin 判定：空 Origin 放行（非浏览器客户端不发这个头）',
          H._is_local_origin('') and H._is_local_origin(None))
    check('Origin 判定：本机放行', H._is_local_origin('http://127.0.0.1:8778'))
    check('Origin 判定：外站拒绝', not H._is_local_origin('https://evil.example.com'))

    httpd = ThreadingHTTPServer(('127.0.0.1', 0), H.make_handler(build_fake_server(), ''))
    port = httpd.server_address[1]
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    base = f'http://127.0.0.1:{port}{H.ENDPOINT}'

    def call(method='POST', body=None, headers=None, path=None):
        req = urllib.request.Request(
            path or base, method=method,
            data=(body.encode('utf-8') if body else None),
            headers=headers or {'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.headers.get('Content-Type', ''), r.read().decode('utf-8')
        except urllib.error.HTTPError as e:
            return e.code, e.headers.get('Content-Type', ''), e.read().decode('utf-8')

    try:
        st, ct, body = call(body='{"jsonrpc":"2.0","id":1,"method":"ping"}')
        check('HTTP：含请求 → 200 + application/json',
              st == 200 and 'application/json' in ct, f'{st} {ct}')
        check('HTTP：响应就是那条 JSON-RPC 结果',
              json.loads(body).get('id') == 1, body[:80])

        st, _, _ = call(body='{"jsonrpc":"2.0","method":"notifications/initialized"}')
        check('HTTP：只含通知 → 202 空体（规范 MUST）', st == 202, str(st))

        st, _, _ = call(method='GET', headers={'Accept': 'text/event-stream'})
        check('HTTP：GET → 405（本服务不推流，规范允许这么答）', st == 405, str(st))

        st, _, _ = call(body='{"jsonrpc":"2.0","id":2,"method":"ping"}',
                        headers={'Content-Type': 'application/json',
                                 'Origin': 'https://evil.example.com'})
        check('HTTP：外站 Origin → 403（防 DNS 重绑定，规范 MUST）', st == 403, str(st))

        st, _, _ = call(body='not json')
        check('HTTP：坏 JSON → 400', st == 400, str(st))

        st, _, body = call(body='[{"jsonrpc":"2.0","id":10,"method":"ping"},'
                                '{"jsonrpc":"2.0","id":11,"method":"tools/list"}]')
        arr = json.loads(body)
        check('HTTP：批请求 → 返回数组，一条对一条',
              st == 200 and isinstance(arr, list) and len(arr) == 2, f'{st} {body[:60]}')

        st, _, _ = call(body='{"jsonrpc":"2.0","id":3,"method":"ping"}',
                        path=f'http://127.0.0.1:{port}/nope')
        check('HTTP：错端点 → 404', st == 404, str(st))

        # 令牌那道闸
        httpd2 = ThreadingHTTPServer(('127.0.0.1', 0),
                                     H.make_handler(build_fake_server(), 'sekrit'))
        p2 = httpd2.server_address[1]
        threading.Thread(target=httpd2.serve_forever, daemon=True).start()
        try:
            st, _, _ = call(body='{"jsonrpc":"2.0","id":4,"method":"ping"}',
                            path=f'http://127.0.0.1:{p2}{H.ENDPOINT}')
            check('HTTP：配了令牌时，不带 Authorization → 401', st == 401, str(st))
            st, _, _ = call(body='{"jsonrpc":"2.0","id":5,"method":"ping"}',
                            headers={'Content-Type': 'application/json',
                                     'Authorization': 'Bearer sekrit'},
                            path=f'http://127.0.0.1:{p2}{H.ENDPOINT}')
            check('HTTP：带对令牌 → 200', st == 200, str(st))
        finally:
            httpd2.shutdown(); httpd2.server_close()
    finally:
        httpd.shutdown()
        httpd.server_close()

    # 独占端口：第二份进程必须绑不上（Windows 默认允许两份同占一个口，2026-09-29 真撞上过）
    a = H._ExclusiveServer(('127.0.0.1', 0), H.make_handler(build_fake_server(), ''))
    try:
        try:
            H._ExclusiveServer(('127.0.0.1', a.server_address[1]), H.make_handler(build_fake_server(), ''))
            dup = True
        except OSError:
            dup = False
        check('HTTP：同一端口第二份绑不上（独占）', not dup)
    finally:
        a.server_close()

    # 4. 握手说明（instructions.md）：里面提到的工具名必须真的存在 —— 说明与清单一分家，
    #    外部 agent 就会照着一个不存在的名字调（2026-09-18 加）
    import re
    from host.mcp import server as _srv
    real = _srv.build_server()
    rs = feed(real, '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}')
    ins = (rs[0].get('result') or {}).get('instructions', '') if rs else ''
    check('initialize 带 instructions（非空）', len(ins) > 200, f'{len(ins)} 字')
    names = {t['name'] for t in real._tools} | {q['name'] for q in real._prompts}
    ghosts = sorted(n for n in set(re.findall(r'`([a-z][a-z0-9_]+)`', ins))
                    if n not in names and n not in ('tool', 'prompt', 'resource'))
    check('instructions 提到的工具名都存在', not ghosts, '不存在的：' + ', '.join(ghosts))

    # 5. /science：给 Claude Science 的精简面（2026-09-29）
    import json as _json
    import tempfile
    import time
    from host.mcp import science as S
    sci = S.build(real)
    sn = {t['name'] for t in sci._tools}
    want = set(S.BORROW) | {t[0] for t in S.TOOLS} | {'ping'}
    check('/science 自己的 + 借来的工具都在', want == sn, '缺：' + ', '.join(sorted(want - sn)))
    pong = [t for t in sci._tools if t['name'] == 'ping'][0]['handler']({})
    check('/science 的 ping 报的是它自己的版本', pong['structured']['version'] == S.VERSION, str(pong))
    # v0.2（2026-09-30，按 Claude Science 的实测评估改）
    check('DOI 归一：带 doi.org / doi: 前缀都认',
          S.norm_doi('https://doi.org/10.1016/j.x.1') == '10.1016/j.x.1'
          and S.norm_doi('doi: 10.1021/a.b') == '10.1021/a.b' and S.norm_doi('HYZ9WTML') == '')
    figs = S.figure_images('\n'.join(['![](images/a.jpg)', 'Figure 1. Cap one', '', 'text',
                                      '![](images/b.jpg)  ', 'Fig. 2 cap', 'Figure 1 again']), 'IMG')
    check('图号 → 图片：图注前最近那张，同号只记一次',
          [(f['ref'], os.path.basename(f['image'])) for f in figs] == [('Figure 1', 'a.jpg'), ('Figure 2', 'b.jpg')],
          str(figs))
    dd = S.dedupe_hits([{'doi': '10.1/x', 'id': 'A', 'text': 'same'}, {'doi': '10.1/X', 'id': 'doi_x', 'text': 'same'},
                        {'doi': '10.1/x', 'id': 'A', 'text': 'other'}])
    check('检索去重：同一篇存两份时同一段只留一条', [d['id'] for d in dd] == ['A', 'A'], str(dd))
    cr = S.crossref_refs('10.1/p', fetch=lambda d: {'reference': [
        {'DOI': '10.1/A', 'unstructured': 'A et al.'}, {'article-title': 'B', 'year': '2020'}]})
    check('Crossref 参考文献：有序、DOI 小写、没有 unstructured 就拼题录',
          [c['doi'] for c in cr] == ['10.1/a', ''] and '2020' in cr[1]['text'], str(cr))
    rows = [{'n': 1, 'doi': ''}, {'n': 2, 'doi': ''}]
    check('Crossref 补 DOI：条数对得上按顺序补、标来源、对账证据库',
          S.enrich_refs(rows, cr, {'10.1/a': 'HAVE0001'}) and rows[0]['doi'] == '10.1/a'
          and rows[0]['doi_from'] == 'crossref' and rows[0]['id'] == 'HAVE0001' and rows[1]['doi'] == '')
    check('Crossref 补 DOI：条数对不上不硬对', S.enrich_refs([{'n': 1, 'doi': ''}], cr, {}) is False)
    from host.mcp import litcall as LC
    check('litcall：有结构化就只给结构化',
          LC.unpack({'result': {'content': [{'type': 'text', 'text': 't'}], 'structuredContent': {'a': 1}}}) == (False, {'a': 1}))
    check('litcall：工具报错 → 出错 + 原文',
          LC.unpack({'result': {'content': [{'type': 'text', 'text': '坏了'}], 'isError': True}}) == (True, {'error': '坏了'}))
    no_struct = [t['name'] for t in sci._tools if t['name'] in {x[0] for x in S.TOOLS}]
    check('/science 自己的工具都声明了参数表', all(sci._tools[i]['inputSchema'].get('type') == 'object'
                                                 for i in range(len(sci._tools))), ','.join(no_struct))
    check('/science 不打 confirm（Claude Science 自己会问人）',
          not any(t['confirm'] for t in sci._tools))
    check('/science 不含写 Zotero / 花钱的工具',
          not (sn & {'getpdf_stash_one', 'deepread_request', 'ask_library', 'extract_one'}))
    ghosts = sorted(n for n in set(re.findall(r'`([a-z][a-z0-9_]+)`', S.INSTRUCTIONS)) if n not in sn)
    check('/science 说明里提到的工具名都存在', not ghosts, ', '.join(ghosts))
    check('to_wsl：盘符路径换成 /mnt', S.to_wsl('D:\\02_AI\\x\\main.pdf') == '/mnt/d/02_AI/x/main.pdf')
    with tempfile.TemporaryDirectory() as td:
        pp = os.path.join(td, 'p.json')
        check('没有进度文件 → 没在跑', S.running_job(pp) == '')
        io.open(pp, 'w', encoding='utf-8').write(_json.dumps({'total': 3, 'finished': 1, 'done': False}))
        check('进度未完且新鲜 → 在跑', '1/3' in S.running_job(pp))
        check('进度未完但早就不动了 → 当它死了、不挡路',
              S.running_job(pp, now=time.time() + S.STALE_SECS + 5) == '')
        io.open(pp, 'w', encoding='utf-8').write(_json.dumps({'total': 3, 'finished': 3, 'done': True}))
        check('进度已完 → 没在跑', S.running_job(pp) == '')

        # v0.3（2026-10-04，桌面 literature_platform_spec_for_agent.md）
        big = S.cap('t', lambda a: {'text': 'x', 'structured': {'blob': 'y' * 60000, 'n': 3}}, spill_dir=td)
        r = big({})
        spilled = r['structured'].get('spilled', '')
        check('超 50 KB 的结果写文件、只回路径（不再给半截 JSON）',
              r['structured'].get('bytes', 0) > S.MAX_OUT and spilled
              and len(_json.dumps(r['structured'])) < 2000 and r['structured']['summary'].get('n') == 3, str(r)[:200])
        small = S.cap('t', lambda a: {'text': 'x', 'structured': {'a': 1}}, spill_dir=td)({})
        check('小结果原样回', small == {'text': 'x', 'structured': {'a': 1}})
        cap_line, grid = S.table_rows('Table 1. Props<table><tr><th>Sample</th><th colspan="2">σ (MPa)</th></tr>'
                                      '<tr><td rowspan="2">PBS-1</td><td>1.2</td><td>0.1</td></tr>'
                                      '<tr><td>1.5</td><td>0.2</td></tr></table>')
        check('表格转行列：colspan 展开、rowspan 往下补',
              cap_line == 'Table 1. Props' and grid == [['Sample', 'σ (MPa)', 'σ (MPa)'], ['PBS-1', '1.2', '0.1'],
                                                        ['PBS-1', '1.5', '0.2']], str(grid))
        check('表格转 CSV', S._as_csv(grid).splitlines()[0] == 'Sample,σ (MPa),σ (MPa)')
        keep, gone = S.precheck(['10.1/real', '10.1/fake'], exists_fn=lambda d: d.endswith('real'))
        check('DOI 预检：Crossref 查无此 DOI 的当场 NOT_FOUND，不占队列',
              keep == ['10.1/real'] and gone and gone[0]['doi'] == '10.1/fake' and gone[0]['code'] == 'NOT_FOUND')
        check('图号归一：Fig. 3b / Figure 3 对得上', S._fig_key('Fig. 3b') == S._fig_key('Figure 3') == 'figure 3')

    httpd3 = ThreadingHTTPServer(('127.0.0.1', 0),
                                 H.make_handler(build_fake_server(), '', {S.ENDPOINT: sci}))
    p3 = httpd3.server_address[1]
    threading.Thread(target=httpd3.serve_forever, daemon=True).start()
    try:
        import urllib.request
        def _list(path):
            req = urllib.request.Request(f'http://127.0.0.1:{p3}{path}', method='POST',
                                         data=b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}',
                                         headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=10) as r:
                return {t['name'] for t in _json.loads(r.read())['result']['tools']}
        check('HTTP 路由：/science 给精简面', _list(S.ENDPOINT) == sn)
        check('HTTP 路由：/mcp 仍是原来那个服务', 'paper_files' not in _list(H.ENDPOINT))
        # stdio ↔ HTTP 转接（Claude Science 只认本机命令，见 bridge.py）
        from host.mcp import bridge as B
        u = f'http://127.0.0.1:{p3}{S.ENDPOINT}'
        r = B.forward({'jsonrpc': '2.0', 'id': 7, 'method': 'tools/list'}, u)
        check('转接：请求原样转过去、答复原样带回',
              r and r.get('id') == 7 and {t['name'] for t in r['result']['tools']} == sn)
        check('转接：通知不回话', B.forward({'jsonrpc': '2.0', 'method': 'notifications/initialized'}, u) is None)
        r = B.forward({'jsonrpc': '2.0', 'id': 8, 'method': 'ping'}, 'http://127.0.0.1:1/science')
        check('转接：连不上 → 回一条带人话的 JSON-RPC 错误（不是崩掉）',
              r and r.get('id') == 8 and '隧道' in r['error']['message'])
    finally:
        httpd3.shutdown(); httpd3.server_close()

    print(f'\n结果：{len(_PASS)} 过 / {len(_FAIL)} 挂')
    if _FAIL:
        print('挂掉项：', ', '.join(_FAIL))
        sys.exit(1)
    print('全部通过 ✓')


if __name__ == '__main__':
    main()
