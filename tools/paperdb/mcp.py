# -*- coding: utf-8 -*-
"""paperdb 的 MCP 面：4 个只读工具（模型可以自己调，不花钱、不改任何东西）。

查询库是 `structured/*.json` 的索引，读它零成本，所以按 R4 判据是 tool。
返回值直接给 JSON：结构化数值是**给机器用的原生数据**，不翻译、不排版
（见根目录 AGENTS.md 的语言约定）。本文件只做参数转换。
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import json

from tools import paperdb


def _json(obj):
    return {'text': json.dumps(obj, ensure_ascii=False, indent=2), 'structured': obj}


def register(server):
    server.register_tool(
        'paperdb_find',
        '按条件筛结构化记录：关键词 / 档次 / 某字段有值 / 某性能数值范围。',
        {'type': 'object', 'properties': {
            'text': {'type': 'string', 'description': '标题或字段里的关键词'},
            'tier': {'type': 'string', 'description': '档次：精层 / 粗层'},
            'field': {'type': 'string',
                      'description': '这个字段必须有值，如 synthesis_conditions'},
            'prop': {'type': 'string', 'description': '性能名，如 tensile'},
            'min_value': {'type': 'number', 'description': '性能数值下限'},
            'max_value': {'type': 'number', 'description': '性能数值上限'},
            'unit': {'type': 'string',
                     'description': '单位，如 MPa（**不做单位换算**，要连单位一起筛）'},
            'limit': {'type': 'integer', 'minimum': 1, 'maximum': 500},
        }},
        lambda a: _json(paperdb.find(
            text=a.get('text'), tier=a.get('tier'), field=a.get('field'),
            prop=a.get('prop'), min_value=a.get('min_value'),
            max_value=a.get('max_value'), unit=a.get('unit'),
            limit=a.get('limit', 100))))

    server.register_tool(
        'paperdb_stats', '库里有多少篇、每个字段的有值率多少（数据有多准）。',
        {'type': 'object', 'properties': {}},
        lambda a: _json(paperdb.stats()))

    server.register_tool(
        'paperdb_props', '抽到过哪些性能、各多少条、范围多大。',
        {'type': 'object', 'properties': {
            'name_like': {'type': 'string', 'description': '性能名里含这个词，如 tensile'},
            'limit': {'type': 'integer', 'minimum': 1, 'maximum': 500},
        }},
        lambda a: _json(paperdb.props(name_like=a.get('name_like'),
                                      limit=a.get('limit', 200))))

    server.register_tool(
        'paperdb_sql',
        '只读 SQL 查询（**只接受 SELECT / WITH**）。两张表：papers、properties。',
        {'type': 'object', 'properties': {
            'sql': {'type': 'string', 'description': 'SELECT / WITH 开头的语句'},
        }, 'required': ['sql']},
        lambda a: _json(paperdb.query(a['sql'])))
