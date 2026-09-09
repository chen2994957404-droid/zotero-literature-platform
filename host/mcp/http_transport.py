# -*- coding: utf-8 -*-
"""http_transport · MCP 的 Streamable HTTP 传输（stdio 之外的第二条腿）。

⚠ **文件名不能叫 `http.py`**：`python host/mcp/server.py` 会把 `host/mcp/`
塞进 `sys.path[0]`，于是本文件会把标准库的 `http` 包整个顶掉，
`from http.server import ...` 变成 import 自己 —— 报的是
「No module named 'http.server'; 'http' is not a package」，
看起来像标准库坏了。2026-09-09 现场踩过一次。

## 为什么需要它（2026-09-09）

编程端的 Antigravity 通过 `ssh ... python host/mcp/server.py` 连主力机，走的是 stdio。
那条路**永远写不了 Zotero、也调不了任何要密钥的工具** —— 公钥 SSH 建立的是
**网络登录会话**，Windows 凭据管理器在这种会话里整个打不开（踩坑 #101）。
实测：`getpdf_stash_one` 在那条链路上三次全部返回「没有 ZOTERO_API_KEY」。

HTTP 传输把「谁来跑这个进程」和「谁来连它」拆开了：
**服务进程由主力机自己以交互式会话启动**（跟 watcher 一样，凭据库读得到），
客户端只是连上来发 JSON-RPC。于是 32 个工具全部可用。

## 安全（这一节不是形式）

主力机的有线网卡**直接挂着一个公网 IP**。而本服务能花钱、能写用户的 Zotero 库。
所以：

1. **只绑 127.0.0.1**，绝不绑 0.0.0.0（规范里的 SHOULD，在这台机器上是 MUST）
2. **校验 Origin 头**，挡 DNS 重绑定（规范里的 MUST）
3. **可选 Bearer 令牌**：配了 `MCP_HTTP_TOKEN` 就强制校验
4. 跨机访问**走 SSH 端口转发**，不开公网端口 —— 认证交给 SSH 密钥

## 实现到什么程度（对着 2025-03-26 规范核过）

- 单端点同时支持 POST 与 GET
- POST 体可以是单条消息，也可以是数组（批）
- **只含通知/响应** → `202 Accepted`，空体
- **含请求** → `Content-Type: application/json`，返回一个 JSON（规范允许不开 SSE 流）
- GET → `405`（本服务不提供服务端主动推流，规范明确允许这么答）
- **不使用会话**：不发 `Mcp-Session-Id`，客户端也就不必回传（规范里 MAY）

## 为什么不引第三方框架

平台「少依赖」的准则；而且这层薄到用标准库 `http.server` 就够。
业务逻辑一行都不在这里 —— 它把消息交给 `MCPStdioServer._handle`，
和 stdio 那条腿共用同一份行为，不会各说各话。
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from shared.kernel.config import get_key
from shared.kernel.log import get_logger

log = get_logger('mcp_http')

ENDPOINT = '/mcp'
DEFAULT_PORT = 8778
MAX_BODY = 4 * 1024 * 1024          # 4 MB：再大的请求不是正常用法

# 允许的 Origin。浏览器发来的跨站请求会带上真实 Origin，挡的就是它。
# 非浏览器客户端（Antigravity、curl）通常不带 Origin —— 那是允许的。
_LOCAL_ORIGINS = ('http://localhost', 'https://localhost',
                  'http://127.0.0.1', 'https://127.0.0.1')

# 工具不是线程安全的（它们会写文件、连浏览器、拿进程锁），所以同一时刻只跑一个。
_run_lock = threading.Lock()


def _is_local_origin(origin):
    """Origin 头是不是本机来的。空 Origin 放行（非浏览器客户端不发这个头）。"""
    if not origin:
        return True
    return any(origin == o or origin.startswith(o + ':') for o in _LOCAL_ORIGINS)


def _dispatch(server, messages):
    """把若干条 JSON-RPC 消息交给协议层，收集它写出来的响应。

    复用 `_out`（协议专用输出流，见 stdio.serve 的 out 参数）把响应接进内存 ——
    这样 HTTP 与 stdio **共用同一份 `_handle`**，行为不会分叉。
    """
    buf = io.StringIO()
    with _run_lock:
        old = getattr(server, '_out', None)
        server._out = buf
        try:
            for m in messages:
                server._handle(m)
        finally:
            server._out = old
    out = []
    for line in buf.getvalue().splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except Exception:
                log.warn(f'协议层写出了不能解析的一行（已丢弃）：{line[:120]}')
    return out


def make_handler(server, token=''):
    """造一个绑定到这个 MCP 服务的 HTTP 处理器类。"""

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        server_version = 'literature-platform-mcp'

        # 默认实现会把每条请求打到 stderr，噪音很大；改成走平台日志
        def log_message(self, fmt, *args):
            log.info('%s - %s' % (self.client_address[0], fmt % args))

        # ── 三道闸 ───────────────────────────────────────────────────
        def _guard(self):
            """通过返回 True；否则已经把错误答复写出去了，调用方直接 return。"""
            if not _is_local_origin(self.headers.get('Origin')):
                self._plain(403, '拒绝：Origin 不是本机（防 DNS 重绑定）')
                return False
            if token:
                auth = self.headers.get('Authorization') or ''
                if auth != f'Bearer {token}':
                    self._plain(401, '拒绝：Authorization 不对')
                    return False
            if self.path.split('?')[0].rstrip('/') not in (ENDPOINT, ENDPOINT.rstrip('/')):
                self._plain(404, f'本服务的 MCP 端点是 {ENDPOINT}')
                return False
            return True

        # ── 输出 ─────────────────────────────────────────────────────
        def _plain(self, code, text):
            body = text.encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code, obj):
            body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _empty(self, code):
            self.send_response(code)
            self.send_header('Content-Length', '0')
            self.end_headers()

        # ── 方法 ─────────────────────────────────────────────────────
        def do_GET(self):
            if not self._guard():
                return
            # 规范：不提供服务端主动推流就回 405，客户端据此不再等 SSE
            self._plain(405, '本服务不提供服务端主动推流（SSE）；请用 POST 发 JSON-RPC。')

        def do_DELETE(self):
            if not self._guard():
                return
            self._plain(405, '本服务不使用会话，没有会话可以结束。')

        def do_POST(self):
            if not self._guard():
                return
            try:
                n = int(self.headers.get('Content-Length') or 0)
            except ValueError:
                n = 0
            if n <= 0:
                self._json(400, {'jsonrpc': '2.0', 'id': None,
                                 'error': {'code': -32700, 'message': '空请求体'}})
                return
            if n > MAX_BODY:
                self._plain(413, '请求体过大')
                return
            raw = self.rfile.read(n)
            try:
                payload = json.loads(raw.decode('utf-8'))
            except Exception as e:
                self._json(400, {'jsonrpc': '2.0', 'id': None,
                                 'error': {'code': -32700, 'message': f'JSON 解析失败：{e}'}})
                return

            batch = isinstance(payload, list)
            messages = payload if batch else [payload]
            if not messages:
                self._json(400, {'jsonrpc': '2.0', 'id': None,
                                 'error': {'code': -32600, 'message': '空批'}})
                return

            # 规范：整批只含通知/响应（都没有 id 的请求）→ 202，空体
            has_request = any(isinstance(m, dict) and m.get('method') and 'id' in m
                              for m in messages)
            replies = _dispatch(server, messages)
            if not has_request:
                self._empty(202)
                return
            if not replies:
                self._empty(202)
                return
            self._json(200, replies if batch else replies[0])

    return Handler


def serve(server, port=DEFAULT_PORT, host='127.0.0.1', token=None):
    """起 HTTP 服务并阻塞。**只绑 127.0.0.1** —— 跨机访问走 SSH 端口转发。"""
    if token is None:
        token = get_key('MCP_HTTP_TOKEN', default='') or ''
    httpd = ThreadingHTTPServer((host, int(port)), make_handler(server, token))
    log.info(f'MCP HTTP 服务起来了：http://{host}:{port}{ENDPOINT}'
             + ('（带令牌校验）' if token else '（没配 MCP_HTTP_TOKEN，只靠绑本机保护）'))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log.info('收到中断，退出')
    finally:
        httpd.server_close()
