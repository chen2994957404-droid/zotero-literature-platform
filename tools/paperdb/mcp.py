# -*- coding: utf-8 -*-
"""paperdb 的 MCP 面：10 个只读工具（模型可以自己调，不花钱、不改任何东西）。

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
            'tier': {'type': 'string', 'description': '抽取档次：精+SI / 精层 / 粗层'},
            'journal': {'type': 'string',
                        'description': '期刊档次：顶刊 / 一流 / 常规 / 一般 / 慎用'},
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
            journal=a.get('journal'),
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
        'paperdb_samples',
        '样品层：一行一个配方（哪篇的、什么组成、怎么做的、什么动态键）。',
        {'type': 'object', 'properties': {
            'key': {'type': 'string', 'description': '只看某一篇（Zotero key）'},
            'text': {'type': 'string', 'description': '组成/制备里含这个词'},
            'limit': {'type': 'integer', 'minimum': 1, 'maximum': 500},
        }},
        lambda a: _json(paperdb.samples(key=a.get('key'), text=a.get('text'),
                                        limit=a.get('limit', 200))))

    server.register_tool(
        'paperdb_measurements',
        '测量层：一行一个数字，带样品、测试条件与出处（表几图几）。'
        'located=true 只要能追溯到原文的那些 —— 要引进论文就筛这个。',
        {'type': 'object', 'properties': {
            'prop': {'type': 'string', 'description': '性能名，如 tensile strength（会先按统一词表归一）'},
            'min_value': {'type': 'number'},
            'max_value': {'type': 'number'},
            'unit': {'type': 'string', 'description': '单位（**不做换算**，要连单位一起筛）'},
            'tier': {'type': 'string', 'description': '档次：精+SI / 精层 / 粗层'},
            'section': {'type': 'string', 'description': "'main' 正文 / 'si' 补充材料"},
            'located': {'type': 'boolean', 'description': 'true=只要有出处的；false=只要还没定位的'},
            'key': {'type': 'string', 'description': '只看某一篇'},
            'limit': {'type': 'integer', 'minimum': 1, 'maximum': 500},
        }},
        lambda a: _json(paperdb.measurements(
            prop=a.get('prop'), min_value=a.get('min_value'),
            max_value=a.get('max_value'), unit=a.get('unit'), tier=a.get('tier'),
            section=a.get('section'), located=a.get('located'), key=a.get('key'),
            limit=a.get('limit', 200))))

    server.register_tool(
        'paperdb_provenance',
        '这库里的数字有多少能追溯到原文（带出处 / 带测试条件 / 挂到了具体样品）。',
        {'type': 'object', 'properties': {}},
        lambda a: _json(paperdb.provenance()))

    server.register_tool(
        'paperdb_journals',
        '期刊视角：库里的文献发在哪些刊上、各是什么档次（顶刊/一流/常规/一般/慎用）、各多少篇。'
        '「这条数据有多可信」的第二条腿 —— 第一条是数字能不能追溯到原文。',
        {'type': 'object', 'properties': {
            'tier': {'type': 'string', 'description': '只看某一档：顶刊 / 一流 / 常规 / 一般 / 慎用'},
            'limit': {'type': 'integer', 'minimum': 1, 'maximum': 500},
        }},
        lambda a: _json(paperdb.journals(tier=a.get('tier'), limit=a.get('limit', 200))))

    server.register_tool(
        'paperdb_curves',
        '曲线层：从论文图里抠下来的曲线（哪篇第几张图、什么曲线、多少个点、多确信）。'
        '曲线的峰值同时也在测量层里，method=curve。',
        {'type': 'object', 'properties': {
            'key': {'type': 'string', 'description': '只看某一篇'},
            'limit': {'type': 'integer', 'minimum': 1, 'maximum': 500},
        }},
        lambda a: _json(paperdb.curves(key=a.get('key'), limit=a.get('limit', 200))))

    server.register_tool(
        'paperdb_curve_points',
        '某条曲线的原始点（[[x, y], ...]），要画图或再分析时用。',
        {'type': 'object', 'properties': {
            'key': {'type': 'string'},
            'fig': {'type': 'string', 'description': '图号，如 3'},
            'series': {'type': 'string', 'description': '同一张图有多条时指名字'},
        }, 'required': ['key', 'fig']},
        lambda a: _json(paperdb.curve_points(a['key'], a['fig'], a.get('series'))))

    server.register_tool(
        'paperdb_sql',
        '只读 SQL 查询（**只接受 SELECT / WITH**）。三张表：papers（一篇一行）、'
        'samples（一个配方一行）、measurements（一个数字一行，带条件与出处）、'
        'curves（从图里抠下来的曲线）；'
        'properties 是 measurements 的兼容视图。',
        {'type': 'object', 'properties': {
            'sql': {'type': 'string', 'description': 'SELECT / WITH 开头的语句'},
        }, 'required': ['sql']},
        lambda a: _json(paperdb.query(a['sql'])))
