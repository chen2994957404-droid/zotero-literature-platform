# -*- coding: utf-8 -*-
"""host.mcp.bridge · stdio ↔ HTTP 转接：让只认「本机命令」的客户端连上平台的 HTTP 端点。

## 为什么要它（2026-09-29）

Claude Science 的 Remote 连接器**只收公网 https 地址**，原话：
「Remote MCP servers must be reachable at a public https URL. For a server running on
this machine, add it as a local (stdio) server instead」。
而平台的服务绝不上公网（它能取全文、能写 Zotero，见 http_transport.py 的安全一节）。
所以反过来：客户端以「本机命令」拉起本文件，本文件把 stdin 上的每条 JSON-RPC
原样 POST 给 `http://127.0.0.1:8778/science`（A 机现成隧道 → B 机服务），答复写回 stdout。

为什么不直接在 A 机上 `ssh ... server.py`（stdio 走 SSH）：那是网络登录会话，
读不到 B 的凭据库（踩坑 #101），MineRU 解析一上来就没密钥。

## 刻意做成「只用标准库、不 import 项目」

它跑在**客户端的沙箱**里，用的是客户端找到的那个 python —— 不保证装过本项目
（`pip install -e .`）。所以这里一个项目模块都不 import，拷到哪都能跑。
也因此不走 shared.kernel.cli / config：地址从环境变量 `LIT_MCP_URL` 取，没有就用默认。

## Claude Science 里怎么配

Settings → Connectors → Add connector → Local command
  command: python
  args:    D:\\dev\\literature-platform\\host\\mcp\\bridge.py
沙箱出网有白名单：连不上 127.0.0.1 时，在 Settings → Network 里加 `127.0.0.1`。
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass

import json
import threading
import urllib.error
import urllib.request

DEFAULT_URL = 'http://127.0.0.1:8778/science'
TIMEOUT = 300            # 取全文是后台跑的，单次调用本不该超过一分钟；留足余量

_out_lock = threading.Lock()
# 直连，不走任何代理：目标是本机回环地址；沙箱若塞了代理变量，走代理反而会被它的白名单挡掉
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _write(obj):
    line = (json.dumps(obj, ensure_ascii=False) + '\n').encode('utf-8')
    with _out_lock:
        sys.stdout.buffer.write(line)
        sys.stdout.buffer.flush()


def _why(e):
    """连不上时给人看的原因 —— 写清该往哪查。"""
    return ('连不上文献平台（%s）。依次检查：① A 机到 B 机的隧道在不在'
            '（计划任务 LiteraturePlatformTunnel，本机 8778 端口应在监听）；'
            '② B 机上的服务在不在（host/mcp/server.py --http）；'
            '③ Claude Science 的沙箱是否放行 127.0.0.1（Settings → Network 里加上）。' % e)


def forward(msg, url, opener=None):
    """一条 JSON-RPC → POST 到 url → 返回要写回的答复（dict / list），通知返回 None。"""
    req = urllib.request.Request(url, data=json.dumps(msg, ensure_ascii=False).encode('utf-8'),
                                 headers={'Content-Type': 'application/json',
                                          'Accept': 'application/json, text/event-stream'},
                                 method='POST')
    is_request = isinstance(msg, dict) and 'id' in msg and msg.get('method')
    try:
        with (opener or _opener).open(req, timeout=TIMEOUT) as r:
            body = r.read().decode('utf-8')
            if r.status == 202 or not body.strip():
                return None
            return json.loads(body)
    except urllib.error.HTTPError as e:
        text = e.read().decode('utf-8', 'replace')[:300]
        err = 'HTTP %d：%s' % (e.code, text)
    except Exception as e:           # 连接被拒、超时、沙箱拦截……
        err = _why(e)
    if not is_request:
        return None                  # 通知出错也没有人等答复
    return {'jsonrpc': '2.0', 'id': msg['id'], 'error': {'code': -32603, 'message': err}}


def _handle(line, url):
    try:
        msg = json.loads(line)
    except Exception as e:
        _write({'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'JSON 解析失败：%s' % e}})
        return
    out = forward(msg, url)
    if out is not None:
        _write(out)


def main():
    url = os.environ.get('LIT_MCP_URL') or DEFAULT_URL
    # 每条消息一个线程：一次慢调用不该堵住客户端同时发来的 ping / 取消
    for raw in sys.stdin.buffer:
        line = raw.decode('utf-8', 'replace').strip()
        if line:
            threading.Thread(target=_handle, args=(line, url), daemon=True).start()
    # stdin 关了 = 客户端要我们退出；等手上的答复写完
    for t in threading.enumerate():
        if t is not threading.current_thread():
            t.join(timeout=TIMEOUT)
    return 0


if __name__ == '__main__':
    sys.exit(main())
