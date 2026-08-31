# -*- coding: utf-8 -*-
"""paper_db · 文献查询库（定理）：175 个 JSON + 一张 md 表 → 一个能查的库。

**回答一类此前答不了的问题**：
    「所有含硼、拉伸强度 > 10 MPa 的体系，按动态键类型分组」
    「哪些篇有合成条件但没有性能数值」
    「精层里 self_healing 有值的有几篇，粗层呢」

为什么此前答不了：`key_properties` 存的是 `'tensile strength: 12 MPa'` 这种人话，
人能看，机器比不了大小；而 `compare.md` 是一张给人竖着看的表，不能筛也不能分组。

设计约定（与 `shared.kernel.jobs` 一致，理由也一致）：
    · **库是索引，不是真相。**真相永远是 `structured/<key>.json`。
      删了随时 `rebuild()` 重建，代价是零 —— 所以本模块从不「增量维护」，
      只有整库重建，省掉一整类「库和文件不同步」的 bug。
    · 只依赖标准库 sqlite3，零新依赖。
    · **不做单位换算**：MPa 和 kPa 混着时宁可让人看见。查询按「名字 + 单位」一起筛。

它组合了什么：
    shared.kernel.paths（库文件放哪、去哪读 JSON）
  + shared.domain.schema（有哪些字段、来源档次、性能字符串怎么拆成数）

两张表：
    papers      一篇一行，schema 的每个字段一列，外加 tier / source / si_used / schema_ver
    properties  一条性能一行（key, name, value, value_max, unit, cmp, raw）—— 能比大小的那张

用法：
    from pipelines import paper_db
    paper_db.rebuild()                                   # 重建（抽取完顺手跑）
    paper_db.query('SELECT tier, COUNT(*) FROM papers GROUP BY tier')
    paper_db.find(text='boron', prop='tensile', min_value=10)
    paper_db.stats()                                     # 各档次 × 各字段有值率
"""
import io
import json
import os
import sqlite3

from shared.kernel import paths
from shared.domain import schema

# schema 的字段都存成 TEXT（列表字段 join 成一行文本，原样可读）
_FIELDS = list(schema.SCHEMA.keys())

_DDL = """
CREATE TABLE IF NOT EXISTS papers (
  key         TEXT PRIMARY KEY,
  title       TEXT,
  doi         TEXT,
  tier        TEXT,
  source      TEXT,
  si_used     INTEGER,
  schema_ver  INTEGER,
  is_review   INTEGER,
  %s
);
CREATE TABLE IF NOT EXISTS properties (
  key       TEXT,
  name      TEXT,
  value     REAL,
  value_max REAL,
  unit      TEXT,
  cmp       TEXT,
  raw       TEXT
);
CREATE INDEX IF NOT EXISTS idx_prop_name  ON properties(name);
CREATE INDEX IF NOT EXISTS idx_prop_value ON properties(value);
CREATE INDEX IF NOT EXISTS idx_papers_tier ON papers(tier);
""" % (',\n  '.join(f'"{f}" TEXT' for f in _FIELDS))

_conn_cache = {}


def db_path():
    """查询库文件在哪。"""
    return paths.papers_db()


def connect(path=None):
    """打开（必要时创建）查询库。同一路径复用连接。"""
    p = path or db_path()
    conn = _conn_cache.get(p)
    if conn is not None:
        return conn
    d = os.path.dirname(p)
    if d:
        os.makedirs(d, exist_ok=True)
    conn = sqlite3.connect(p, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute('PRAGMA journal_mode=WAL')
    except sqlite3.Error:
        pass                    # 网络盘上 WAL 可能不可用，退回默认模式
    conn.executescript(_DDL)
    conn.commit()
    _conn_cache[p] = conn
    return conn


def close():
    """关掉所有连接（测试用）。"""
    for conn in _conn_cache.values():
        try:
            conn.close()
        except sqlite3.Error:
            pass
    _conn_cache.clear()


def _flat(v):
    """字段值 → 一行文本。列表 join 成 '; '，None → 空串。"""
    if v is None:
        return ''
    if isinstance(v, (list, tuple)):
        return '; '.join(str(x) for x in v)
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def _records():
    """读回全部结构化记录（坏 JSON 跳过，不让一个坏文件毁掉整库）。"""
    out = []
    if not os.path.isdir(paths.STRUCTURED):
        return out
    for f in sorted(os.listdir(paths.STRUCTURED)):
        if not f.endswith('.json'):
            continue
        try:
            out.append(json.load(io.open(os.path.join(paths.STRUCTURED, f),
                                         encoding='utf-8')))
        except Exception:
            continue
    return out


def rebuild(records=None, log=print):
    """从 `structured/*.json` 整库重建。返回 (篇数, 性能条数)。

    **只有整库重建，没有增量**：重建 175 篇不到一秒，
    而「增量维护」会引入一整类「库里还留着已删记录」的 bug。
    """
    records = _records() if records is None else records
    conn = connect()
    cols = ['key', 'title', 'doi', 'tier', 'source', 'si_used', 'schema_ver',
            'is_review'] + _FIELDS
    sql = ('INSERT OR REPLACE INTO papers (' + ','.join(f'"{c}"' for c in cols)
           + ') VALUES (' + ','.join('?' * len(cols)) + ')')
    n_prop = 0
    with conn:
        conn.execute('DELETE FROM papers')
        conn.execute('DELETE FROM properties')
        for r in records:
            key = r.get('key') or ''
            row = [key, r.get('title', ''), r.get('doi', ''),
                   schema.tier_label(r), r.get('source', schema.SOURCE_FINE),
                   1 if r.get('si_used') else 0, r.get('schema_ver'),
                   1 if schema.is_review(r) else 0] + [_flat(r.get(f)) for f in _FIELDS]
            conn.execute(sql, row)
            for p in schema.parse_properties(r):
                conn.execute(
                    'INSERT INTO properties (key,name,value,value_max,unit,cmp,raw)'
                    ' VALUES (?,?,?,?,?,?,?)',
                    (key, p['name'], p['value'], p['value_max'],
                     p['unit'], p['cmp'], p['raw']))
                n_prop += 1
    log(f'[查询库] {len(records)} 篇、{n_prop} 条性能数值 → {db_path()}')
    return len(records), n_prop


def query(sql, args=()):
    """只读查询，返回 list[dict]。**只允许单条 SELECT / WITH** —— 这是查询库，不是写入口。"""
    head = sql.strip().lstrip('(').lstrip().lower()
    if not (head.startswith('select') or head.startswith('with')):
        raise ValueError('只允许 SELECT / WITH 查询（要改数据请改 structured/*.json 再 rebuild）')
    if ';' in sql.strip().rstrip(';'):
        raise ValueError('一次只允许一条语句')
    return [dict(r) for r in connect().execute(sql, args).fetchall()]


def find(text=None, tier=None, field=None, prop=None,
         min_value=None, max_value=None, unit=None, limit=100):
    """常用筛法的快捷方式（不用手写 SQL）。

      text       任意字段里含这个词（体系、动态键、结论都算）
      tier       只要某一档：'精+SI' / '精层' / '粗层'
      field      这个字段必须有真值（不是 N/A）
      prop       性能名字里含这个词，例如 'tensile'
      min_value  / max_value / unit —— 配合 prop 用，比大小
    """
    where, args = [], []
    if text:
        cond = ' OR '.join(f'"{f}" LIKE ?' for f in ['title'] + _FIELDS)
        where.append('(' + cond + ')')
        args += ['%' + text + '%'] * (len(_FIELDS) + 1)
    if tier:
        where.append('tier = ?')
        args.append(tier)
    if field:
        if field not in _FIELDS:
            raise ValueError(f'没有这个字段: {field}')
        # 「有真值」的判据与 schema.has_value 保持一致（N/A、空、未提及都算没有）
        where.append(f'TRIM(LOWER("{field}")) NOT IN ({",".join("?" * len(schema.EMPTY_VALUES))})')
        args += sorted(schema.EMPTY_VALUES)
    if prop or min_value is not None or max_value is not None or unit:
        sub, sargs = ['properties.key = papers.key'], []
        if prop:
            sub.append('name LIKE ?')
            sargs.append('%' + prop.lower() + '%')
        if unit:
            sub.append('LOWER(unit) LIKE ?')
            sargs.append('%' + unit.lower() + '%')
        if min_value is not None:
            sub.append('value >= ?')
            sargs.append(min_value)
        if max_value is not None:
            sub.append('value <= ?')
            sargs.append(max_value)
        where.append('EXISTS (SELECT 1 FROM properties WHERE ' + ' AND '.join(sub) + ')')
        args += sargs
    sql = 'SELECT * FROM papers'
    if where:
        sql += ' WHERE ' + ' AND '.join(where)
    sql += ' ORDER BY CASE tier'
    for i, t in enumerate(schema.TIER_ORDER):       # 可信的排前面
        sql += f" WHEN '{t}' THEN {i}"
    sql += ' ELSE 99 END, title LIMIT ?'
    args.append(int(limit))
    return query(sql, args)


def stats():
    """各档次篇数 + 各字段有值率 —— 与对比表开头那张小表同源同口径。"""
    return schema.coverage(_records(), _FIELDS)


def props(name_like=None, limit=200):
    """性能数值总览（哪些性能被抽到过、各有多少条、范围多大）。"""
    sql = ('SELECT name, unit, COUNT(*) n, MIN(value) lo, MAX(value) hi '
           'FROM properties WHERE value IS NOT NULL')
    args = []
    if name_like:
        sql += ' AND name LIKE ?'
        args.append('%' + name_like.lower() + '%')
    sql += ' GROUP BY name, unit ORDER BY n DESC LIMIT ?'
    args.append(int(limit))
    return query(sql, args)
