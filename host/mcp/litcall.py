# -*- coding: utf-8 -*-
"""host.mcp.litcall · 一行调一个文献平台工具（给 Claude Science 在 B 机 WSL 里用）。

    python3 litcall.py <工具名> '<JSON 参数>'         # 打印 structuredContent（JSON）
    python3 litcall.py --list                         # 工具清单：名字 + 一句话 + 参数
    python3 litcall.py --batch < calls.jsonl          # 一次会话跑多条：每行 {"tool": ..., "args": {...}}，每行出一个 JSON
    python3 litcall.py --version                      # litcall 与服务端的版本

## 输出不超过 50 KB（2026-10-04）

调用方经 SSH 读 stdout，过 64 KB 就被截断 —— 6 篇 outline 合一次 batch，JSON 断在中间。
服务端每个工具已经各自封顶 50 KB（超了写文件、回路径）；这里再管 `--batch` 的**总量**：
累计快到 50 KB 时，后面的每条写进 `~/.cache/litcall/` 的文件，那一行只印 `{"tool", "ok", "spilled": 路径}`。
每一行都是完整的 JSON，不会再有半截。

## 为什么要它（2026-09-30，Claude Science 的评估里提的）

它连平台的唯一通道是 `~/bin/litplatform`（MCP stdio，见 bridge.py 与 science.py 的说明），
每次都得自己拼 initialize 握手报文、再从 JSON-RPC 回复里抠结果。这里替它做掉：
握手、发请求、**只打印结构化那份**（文字摘要走 stderr），工具报错时退出码 1。
`--batch` 在同一个会话里跑多条 —— 握手只做一次。

## 刻意只用标准库、不 import 项目

它跑在 WSL 里、用的是那边的 python3，那里没装本项目。所以：
- 不走 shared.kernel.cli，用 argparse（**不认识的参数直接报错**，不会被当成「没给参数」走进
  最贵那条路 —— 踩坑 #85 要防的就是这个）；
- 连接命令从环境变量 `LITPLATFORM_CMD` 取，默认 `~/bin/litplatform`。
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass

import argparse
import json
import subprocess

VERSION = '0.7.5'
MAX_STDOUT = 48000          # 字节；留点余量给 SSH 那边的 64 KB 截断线

HANDSHAKE = [
    {'jsonrpc': '2.0', 'id': 0, 'method': 'initialize',
     'params': {'protocolVersion': '2024-11-05', 'capabilities': {},
                'clientInfo': {'name': 'litcall', 'version': '1'}}},
    {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
]


def session(messages, cmd=None, timeout=600):
    """握手 + 一串消息 → {id: 回复}（握手那条的 id 是 0）。一次 SSH 会话跑完。"""
    cmd = cmd or os.environ.get('LITPLATFORM_CMD') or os.path.expanduser('~/bin/litplatform')
    payload = ''.join(json.dumps(m, ensure_ascii=False) + '\n' for m in HANDSHAKE + messages)
    p = subprocess.run([cmd], input=payload.encode('utf-8'), capture_output=True, timeout=timeout,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))   # Linux 上是 0
    out = {}
    for line in p.stdout.decode('utf-8', 'replace').splitlines():
        try:
            m = json.loads(line)
        except ValueError:
            continue
        if isinstance(m, dict) and 'id' in m:
            out[m['id']] = m
    if not out and p.returncode:
        raise SystemExit('连不上文献平台：' + p.stderr.decode('utf-8', 'replace')[-500:])
    return out


def unpack(reply):
    """一条 tools/call 回复 → (是否出错, 结构化数据或文字)。"""
    if 'error' in reply:
        return True, {'error': reply['error'].get('message')}
    r = reply.get('result') or {}
    text = ''.join(c.get('text', '') for c in r.get('content') or [])
    if r.get('structuredContent') is not None:
        data = r['structuredContent']
    else:
        data = {'text': text}
    if r.get('isError'):
        return True, {'error': text}
    return False, data


def spill(text, n, root=None):
    """一条放不下的结果写进 ~/.cache/litcall/，回路径。留三天。"""
    import time
    root = root or os.path.expanduser('~/.cache/litcall')
    os.makedirs(root, exist_ok=True)
    now = time.time()
    for f in os.listdir(root):
        try:
            if now - os.path.getmtime(os.path.join(root, f)) > 3 * 86400:
                os.remove(os.path.join(root, f))
        except OSError:
            pass
    p = os.path.join(root, 'batch-%s-%d-%d.json' % (time.strftime('%Y%m%d-%H%M%S'), os.getpid(), n))
    with open(p, 'w', encoding='utf-8') as fh:
        fh.write(text)
    return p


def call(tool, args):
    return {'jsonrpc': '2.0', 'method': 'tools/call', 'params': {'name': tool, 'arguments': args}}


def main():
    ap = argparse.ArgumentParser(description='调文献平台的一个工具，打印结构化结果（JSON）')
    ap.add_argument('tool', nargs='?', help='工具名，如 library_db_search')
    ap.add_argument('args', nargs='?', default='{}', help='JSON 参数，如 \'{"query": "polyborosiloxane"}\'')
    ap.add_argument('--list', action='store_true', help='列出工具')
    ap.add_argument('--batch', action='store_true', help='从 stdin 读多行 {"tool","args"}，同一会话跑完')
    ap.add_argument('--version', action='store_true', help='litcall 与服务端的版本')
    a = ap.parse_args()

    if a.version:
        info = (session([]).get(0, {}).get('result') or {}).get('serverInfo') or {}
        print(json.dumps({'litcall': VERSION, 'server': info.get('name'), 'server_version': info.get('version')},
                         ensure_ascii=False))
        return 0

    if a.list:
        r = session([{'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}]).get(1, {})
        for t in (r.get('result') or {}).get('tools', []):
            props = (t.get('inputSchema') or {}).get('properties') or {}
            print(json.dumps({'name': t['name'], 'description': t['description'],
                              'args': sorted(props)}, ensure_ascii=False))
        return 0

    if a.batch:
        jobs = [json.loads(l) for l in sys.stdin if l.strip()]
        msgs = [dict(call(j['tool'], j.get('args') or {}), id=i + 1) for i, j in enumerate(jobs)]
        replies = session(msgs)
        bad, used = 0, 0
        for i, j in enumerate(jobs):
            err, data = unpack(replies.get(i + 1, {'error': {'message': '没有回复'}}))
            bad += err
            line = json.dumps({'tool': j['tool'], 'ok': not err, 'data': data}, ensure_ascii=False)
            size = len(line.encode('utf-8')) + 1
            if used + size > MAX_STDOUT:
                line = json.dumps({'tool': j['tool'], 'ok': not err, 'spilled': spill(line, i + 1),
                                   'bytes': size}, ensure_ascii=False)
                size = len(line.encode('utf-8')) + 1
            used += size
            print(line)
        return 1 if bad else 0

    if not a.tool:
        ap.print_help()
        return 2
    try:
        args = json.loads(a.args)
    except ValueError as e:
        raise SystemExit('参数不是合法 JSON：%s' % e)
    err, data = unpack(session([dict(call(a.tool, args), id=1)]).get(1, {'error': {'message': '没有回复'}}))
    line = json.dumps(data, ensure_ascii=False)
    if len(line.encode('utf-8')) > MAX_STDOUT:             # 服务端已封顶，这里兜底（老版本服务端）
        line = json.dumps({'spilled': spill(line, 1), 'bytes': len(line.encode('utf-8'))}, ensure_ascii=False)
    print(line)
    return 1 if err else 0


if __name__ == '__main__':
    sys.exit(main())
