# -*- coding: utf-8 -*-
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
"""mcp_stdio · 极简 MCP stdio 服务端协议层（零第三方依赖）

谁调用它：MCP 客户端（Claude Code / Cursor / DSH 等）以「子进程 + stdin/stdout」方式
启动本服务；上层的 zotero_server.py 等注册好业务工具后调 serve() 跑起来。

为什么手写协议、不引官方 mcp SDK（决策依据，详见 变更记录 2026-08-26）：
  - 平台「少依赖」宪法：一个只读工具面只需 ~200 行，引 SDK 会拖进 pydantic/httpx 等一堆包；
  - 协议极稳定且已实测：JSON-RPC 2.0 + 换行分隔，官方 SDK 的 ReadBuffer 就是按 \n 切帧
    （见 .dsh 部署里 @modelcontextprotocol/sdk/dist/esm/shared/stdio.js，序列化 = JSON + '\\n'）；
  - 可理解性：主导者能读懂这一层每行在干什么（宪法：牺牲可理解性换聪明实现，违背宪法）。
  日后若需非 stdio 传输（SSE/HTTP）再换官方 SDK，本层对外接口不变。

对外接口：
  - MCPStdioServer(name, version)                     : 建服务
  - server.register_tool(name, desc, input_schema, handler) : 注册一个工具
  - server.serve()                                    : 阻塞读 stdin，逐条响应（stdout 只写协议）
  工具 handler 契约：handler(arguments: dict) -> dict
    text       : str   必填，给模型读的文本（markdown 或纯文本）
    structured : 可选，结构化数据（会放进 structuredContent 供程序消费）
    is_error   : bool  可选，True 表示业务失败（放进 isError 字段）
"""
import json

# 官方 SDK 支持的旧版本号（实测 SDK dist/esm/types.js 的 SUPPORTED_PROTOCOL_VERSIONS），
# 工具面功能与最新版一致；客户端会按服务端返回的版本自适应，回旧版最稳。
PROTOCOL_VERSION = '2024-11-05'

# JSON-RPC 2.0 标准错误码
ERR_PARSE = -32700
ERR_INTERNAL = -32603
ERR_METHOD = -32601
ERR_PARAMS = -32602


class MCPStdioServer:
    """MCP stdio 服务端：newline-delimited JSON-RPC 2.0，零依赖。"""

    def __init__(self, name, version):
        self.name = name
        self.version = version
        self._tools = []  # 每项 dict(name, description, inputSchema, handler)

    # ── 注册 ──────────────────────────────────────────────────────────

    def register_tool(self, name, description, input_schema, handler):
        """注册一个工具。input_schema 是 JSON Schema（type='object'）。"""
        self._tools.append({
            'name': name,
            'description': description,
            'inputSchema': input_schema,
            'handler': handler,
        })

    # ── 运行 ──────────────────────────────────────────────────────────

    def serve(self):
        """阻塞读 stdin 逐行处理，直到 EOF（客户端断开即退出）。stdout 只写协议。"""
        # ⚠ stdin 必须显式设成 UTF-8（踩坑 #43）。
        # MCP 协议规定报文是 UTF-8，但 Windows 上 sys.stdin 默认跟随系统代码页（本机 gbk），
        # 于是客户端发来的中文参数会被按 gbk 解码成乱码 ——
        # 「聚硼硅氧烷」变成「鑱氱〖纭呮哀鐑」，拿去搜库自然一篇都搜不到。
        # 标准开头只管了 stdout，读的那一头一直没人管；英文参数不受影响，所以一直没暴露。
        try:
            sys.stdin.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass
        for raw in sys.stdin:
            line = raw.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except Exception:
                self._error(None, ERR_PARSE, '请求不是合法 JSON')
                continue
            try:
                self._handle(msg)
            except Exception as e:  # 防御：任何未捕获异常都要回给客户端，不能静默
                self._error(msg.get('id') if isinstance(msg, dict) else None,
                            ERR_INTERNAL, f'内部错误：{e}')

    # ── 协议处理 ──────────────────────────────────────────────────────

    def _handle(self, msg):
        if not isinstance(msg, dict):
            self._error(None, ERR_PARSE, '请求必须是 JSON 对象')
            return
        method = msg.get('method')
        req_id = msg.get('id')            # 通知没有 id
        params = msg.get('params') or {}

        if method == 'initialize':
            self._respond(req_id, {
                'protocolVersion': PROTOCOL_VERSION,
                'capabilities': {'tools': {'listChanged': False}},
                'serverInfo': {'name': self.name, 'version': self.version},
            })
            return
        if req_id is None:
            return                        # 通知（initialized/cancelled 等）一律不回
        if method == 'ping':
            self._respond(req_id, {})
            return
        if method == 'tools/list':
            self._respond(req_id, {
                'tools': [{
                    'name': t['name'],
                    'description': t['description'],
                    'inputSchema': t['inputSchema'],
                } for t in self._tools],
            })
            return
        if method == 'tools/call':
            self._handle_call(req_id, params)
            return
        self._error(req_id, ERR_METHOD, f'方法不存在：{method}')

    def _handle_call(self, req_id, params):
        name = params.get('name') if isinstance(params, dict) else None
        arguments = params.get('arguments') if isinstance(params, dict) else None
        if not isinstance(arguments, dict):
            arguments = {}
        tool = next((t for t in self._tools if t['name'] == name), None)
        if tool is None:
            self._error(req_id, ERR_PARAMS, f'未知工具：{name}')
            return
        bad = self._validate(tool['inputSchema'], arguments)
        if bad:
            self._respond(req_id, {
                'content': [{'type': 'text', 'text': f'参数错误：{bad}'}],
                'isError': True,
            })
            return
        try:
            out = tool['handler'](arguments)
        except Exception as e:  # 业务异常 → 作为工具错误回给模型（isError），而非协议错误
            self._respond(req_id, {
                'content': [{'type': 'text', 'text': f'工具执行失败：{e}'}],
                'isError': True,
            })
            return
        result = {'content': [{'type': 'text', 'text': str(out.get('text', ''))}]}
        if out.get('structured') is not None:
            result['structuredContent'] = out['structured']
        if out.get('is_error'):
            result['isError'] = True
        self._respond(req_id, result)

    # ── 参数校验（轻量 JSON Schema 子集）──────────────────────────────

    def _validate(self, schema, args):
        required = schema.get('required') or []
        props = schema.get('properties') or {}
        for n in required:
            if n not in args:
                return f'缺少必填参数：{n}'
        for n, val in args.items():
            prop = props.get(n)
            if not prop:
                continue
            typ = prop.get('type')
            if typ == 'integer':
                if not isinstance(val, int) or isinstance(val, bool):
                    return f'参数 {n} 应为整数'
                lo, hi = prop.get('minimum'), prop.get('maximum')
                if lo is not None and val < lo:
                    return f'参数 {n} 最小为 {lo}'
                if hi is not None and val > hi:
                    return f'参数 {n} 最大为 {hi}'
            elif typ == 'number':
                if not isinstance(val, (int, float)) or isinstance(val, bool):
                    return f'参数 {n} 应为数字'
            elif typ == 'string':
                if not isinstance(val, str):
                    return f'参数 {n} 应为字符串'
                enum = prop.get('enum')
                if enum is not None and val not in enum:
                    return f'参数 {n} 只能取 {enum} 之一'
            elif typ == 'boolean':
                if not isinstance(val, bool):
                    return f'参数 {n} 应为布尔值'
        return None

    # ── 输出 ──────────────────────────────────────────────────────────

    def _send(self, msg):
        # 换行分隔 + ensure_ascii=False：官方 SDK 按 \n 切帧，中文保持可读
        sys.stdout.write(json.dumps(msg, ensure_ascii=False) + '\n')
        sys.stdout.flush()

    def _respond(self, req_id, result):
        self._send({'jsonrpc': '2.0', 'id': req_id, 'result': result})

    def _error(self, req_id, code, message):
        self._send({'jsonrpc': '2.0', 'id': req_id,
                    'error': {'code': code, 'message': message}})
