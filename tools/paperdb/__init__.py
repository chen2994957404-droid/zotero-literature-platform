# -*- coding: utf-8 -*-
"""paperdb · 文献查询库：一堆结构化 JSON → 一个能筛、能分组、能比大小的库。

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

**对外契约**（别的地方只许调这些；`cli.py` / `mcp.py` 也只许调这些）：

| 入口 | 干什么 |
|---|---|
| `rebuild(records=None)` | 从 `structured/*.json` 整库重建（秒级、不花钱） |
| `query(sql, args)`      | **只读**查询（只接受单条 SELECT / WITH） |
| `find(text, tier, field, prop, min_value, max_value, unit)` | 常用筛法，不用手写 SQL |
| `samples()` / `measurements()` / `provenance()` | 样品层 / 测量层（带条件与出处）/ 可追溯体温计 |
| `curves()` / `curve_points(key, fig)` | 从图上抠下来的曲线，以及它的原始点 |
| `stats()`               | 各档次篇数 + 各字段有值率 |
| `props(name_like)`      | 抽到过哪些性能、各多少条、范围多大 |
| `db_path()` / `connect()` / `close()` | 库文件在哪 / 连接管理 |
| `query.main`            | 人的命令行入口 |

用法：
    from tools import paperdb
    paperdb.rebuild()                                   # 重建（抽取完顺手跑）
    paperdb.query('SELECT tier, COUNT(*) FROM papers GROUP BY tier')
    paperdb.find(text='boron', prop='tensile', min_value=10)
    paperdb.stats()                                     # 各档次 × 各字段有值率
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
CREATE TABLE IF NOT EXISTS samples (
  key          TEXT,
  sample_id    TEXT,
  composition  TEXT,
  preparation  TEXT,
  dynamic_bond TEXT,
  role         TEXT,
  PRIMARY KEY (key, sample_id)
);
CREATE TABLE IF NOT EXISTS measurements (
  key       TEXT,
  sample_id TEXT,
  name      TEXT,
  raw_name  TEXT,
  value     REAL,
  value_max REAL,
  unit      TEXT,
  cmp       TEXT,
  "condition" TEXT,
  location  TEXT,
  section   TEXT,
  method    TEXT,
  raw       TEXT
);
CREATE TABLE IF NOT EXISTS curves (
  key        TEXT,
  fig        TEXT,
  series     TEXT,
  chart_type TEXT,
  x_label    TEXT,
  x_unit     TEXT,
  y_label    TEXT,
  y_unit     TEXT,
  n_points   INTEGER,
  confidence TEXT,
  caption    TEXT,
  points     TEXT
);
CREATE INDEX IF NOT EXISTS idx_curves_key ON curves(key);
-- 旧名字保留成视图：老查询、老 evals、老 SQL 照样跑（三层是加出来的，不是换掉的）
CREATE VIEW IF NOT EXISTS properties AS
  SELECT key, name, value, value_max, unit, cmp, raw FROM measurements;
CREATE INDEX IF NOT EXISTS idx_meas_name    ON measurements(name);
CREATE INDEX IF NOT EXISTS idx_meas_value   ON measurements(value);
CREATE INDEX IF NOT EXISTS idx_meas_key     ON measurements(key, sample_id);
CREATE INDEX IF NOT EXISTS idx_papers_tier  ON papers(tier);
""" % (',\n  '.join(f'"{f}" TEXT' for f in _FIELDS))

_conn_cache = {}


def _migrate(conn):
    """把 v1 库里的 `properties` **表**换成视图（同名，查询一行不用改）。

    为什么必须换：三层之后一个数字要带样品、条件、出处，列多了一倍。
    与其让两份数值并存（必然对不上），不如让 properties 变成 measurements 的一个视图 ——
    **一个真相，两个看法。**库本来就是可再生索引，换掉零风险。
    """
    row = conn.execute("SELECT type FROM sqlite_master WHERE name='properties'").fetchone()
    if row is not None and row[0] == 'table':
        conn.executescript('DROP TABLE properties;')
        conn.commit()


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
    _migrate(conn)
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


_MEAS_COLS = ['key', 'sample_id', 'name', 'raw_name', 'value', 'value_max', 'unit',
              'cmp', 'condition', 'location', 'section', 'method', 'raw']


def _curves():
    """读回全部抠过的曲线：`{key: {图号: 结果}}`（坏文件跳过）。

    真相是 `curated/<key>/curves.json`（`tools.digitize` 写的），
    这里只是把它也编进索引 —— 曲线上抠下来的数字和文字里抽出来的数字
    本来就该放在一起比大小，只是 `method` 不同、可信度不同。
    """
    out = {}
    for key in paths.all_keys():
        p = paths.curves(key)
        if not os.path.exists(p):
            continue
        try:
            d = json.load(io.open(p, encoding='utf-8'))
        except Exception:
            continue
        if isinstance(d, dict) and d:
            out[key] = d
    return out


def _insert_curves(conn, curves_by_key):
    """曲线进 `curves` 表 + 派生的峰值进 `measurements`。返回 (曲线条数, 测量条数)。"""
    sql_c = ('INSERT INTO curves (key,fig,series,chart_type,x_label,x_unit,y_label,'
             'y_unit,n_points,confidence,caption,points) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)')
    sql_m = ('INSERT INTO measurements (' + ','.join(f'"{c}"' for c in _MEAS_COLS)
             + ') VALUES (' + ','.join('?' * len(_MEAS_COLS)) + ')')
    n_c = n_m = 0
    for key, figs in curves_by_key.items():
        for fig, cur in sorted(figs.items(), key=lambda kv: str(kv[0])):
            if not isinstance(cur, dict) or cur.get('error'):
                continue
            x_ax, y_ax = cur.get('x_axis') or {}, cur.get('y_axis') or {}
            for s in (cur.get('series') or []):
                if not isinstance(s, dict):
                    continue
                pts = s.get('points') or []
                conn.execute(sql_c, (key, str(fig), _flat(s.get('name')),
                                     _flat(cur.get('chart_type')),
                                     _flat(x_ax.get('label')), _flat(x_ax.get('unit')),
                                     _flat(y_ax.get('label')), _flat(y_ax.get('unit')),
                                     len(pts), _flat(cur.get('confidence')),
                                     _flat(cur.get('caption')),
                                     json.dumps(pts, ensure_ascii=False)))
                n_c += 1
            for m in schema.curve_measurements(cur, fig=fig):
                conn.execute(sql_m, [key] + [m.get(c) for c in _MEAS_COLS[1:]])
                n_m += 1
    return n_c, n_m


def rebuild(records=None, log=print):
    """从 `structured/*.json` 整库重建。返回 (篇数, 样品数, 测量条数)。

    **三层一起建**：一篇 → 若干样品 → 若干测量。
    v1 老记录没有样品与出处，`shared.domain.schema` 会合成一个 'main' 样品、
    出处留空 —— 所以新旧记录混在一个库里也查得动，空出处本身就是「还没定位」的信息。

    **只有整库重建，没有增量**：重建 175 篇不到一秒，
    而「增量维护」会引入一整类「库里还留着已删记录」的 bug。
    """
    records = _records() if records is None else records
    conn = connect()
    cols = ['key', 'title', 'doi', 'tier', 'source', 'si_used', 'schema_ver',
            'is_review'] + _FIELDS
    sql = ('INSERT OR REPLACE INTO papers (' + ','.join(f'"{c}"' for c in cols)
           + ') VALUES (' + ','.join('?' * len(cols)) + ')')
    sql_s = ('INSERT OR REPLACE INTO samples '
             '(key,sample_id,composition,preparation,dynamic_bond,role)'
             ' VALUES (?,?,?,?,?,?)')
    sql_m = ('INSERT INTO measurements (' + ','.join(f'"{c}"' for c in _MEAS_COLS)
             + ') VALUES (' + ','.join('?' * len(_MEAS_COLS)) + ')')
    n_samp = n_meas = 0
    with conn:
        conn.execute('DELETE FROM papers')
        conn.execute('DELETE FROM samples')
        conn.execute('DELETE FROM measurements')
        conn.execute('DELETE FROM curves')
        for r in records:
            key = r.get('key') or ''
            row = [key, r.get('title', ''), r.get('doi', ''),
                   schema.tier_label(r), r.get('source', schema.SOURCE_FINE),
                   1 if r.get('si_used') else 0, r.get('schema_ver'),
                   1 if schema.is_review(r) else 0] + [_flat(r.get(f)) for f in _FIELDS]
            conn.execute(sql, row)
            for s in schema.samples_of(r):
                conn.execute(sql_s, (key, s['sample_id'], s['composition'],
                                     s['preparation'], s['dynamic_bond'], s['role']))
                n_samp += 1
            for m in schema.iter_measurements(r):
                conn.execute(sql_m, [key] + [m.get(c) for c in _MEAS_COLS[1:]])
                n_meas += 1
        n_curve, n_cm = _insert_curves(conn, _curves())
        n_meas += n_cm
    log(f'[查询库] {len(records)} 篇、{n_samp} 个样品、{n_meas} 条数值'
        + (f'（其中 {n_cm} 条抠自 {n_curve} 条曲线）' if n_curve else '')
        + f' → {db_path()}')
    return len(records), n_samp, n_meas


def _ensure_fresh():
    """库比 `structured/*.json` 旧就自己重建一次（秒级、不花钱）。

    **R7 窗为什么加这个**：此前是「谁写完 JSON 谁负责刷索引」——
    于是 `tools/extract` 里写着 `from tools import paperdb`，
    违反 REBUILD.md 第三节硬规则 2（工具不许 import 工具）。

    真正的毛病不在那一行 import，而在**责任放错了地方**：索引的新鲜度
    是索引自己的事。让抽取方负责，就得每个写 JSON 的人都记得刷一次，
    漏一个（手改过 JSON、从别处拷进来一份）用户就查到旧数据 —— 而且不报错。

    判据只看时间戳：库文件比最新的那份 JSON 旧 = 该重建。
    重建 175 篇不到一秒，宁可多建一次，也不要给出旧答案。
    """
    p = db_path()
    try:
        db_mtime = os.path.getmtime(p)
    except OSError:
        db_mtime = -1                      # 库还不存在 → 一定要建
    newest = -1
    if os.path.isdir(paths.STRUCTURED):
        for f in os.listdir(paths.STRUCTURED):
            if f.endswith('.json'):
                try:
                    newest = max(newest, os.path.getmtime(
                        os.path.join(paths.STRUCTURED, f)))
                except OSError:
                    continue
    for key in paths.all_keys():          # 曲线也是源：抠完一张图，库该跟着新
        try:
            newest = max(newest, os.path.getmtime(paths.curves(key)))
        except OSError:
            continue
    if newest < 0 and db_mtime >= 0:
        return                             # 没有源 JSON，保持现状（多半是测试造的库）
    if db_mtime < newest:
        rebuild(log=lambda *_: None)       # 自动刷新不该往用户屏幕上刷字


def query(sql, args=()):
    """只读查询，返回 list[dict]。**只允许单条 SELECT / WITH** —— 这是查询库，不是写入口。"""
    head = sql.strip().lstrip('(').lstrip().lower()
    if not (head.startswith('select') or head.startswith('with')):
        raise ValueError('只允许 SELECT / WITH 查询（要改数据请改 structured/*.json 再 rebuild）')
    if ';' in sql.strip().rstrip(';'):
        raise ValueError('一次只允许一条语句')
    _ensure_fresh()
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


def samples(key=None, text=None, limit=200):
    """样品层：一行一个配方（哪篇的、什么组成、怎么做的、什么动态键）。

    `key` 只看某一篇；`text` 在组成/制备里搜词。
    """
    where, args = [], []
    if key:
        where.append('s.key = ?')
        args.append(key)
    if text:
        where.append('(s.composition LIKE ? OR s.preparation LIKE ? OR s.dynamic_bond LIKE ?)')
        args += ['%' + text + '%'] * 3
    sql = ('SELECT s.key, s.sample_id, p.title, s.composition, s.preparation, '
           's.dynamic_bond, s.role, p.tier FROM samples s '
           'LEFT JOIN papers p ON p.key = s.key')
    if where:
        sql += ' WHERE ' + ' AND '.join(where)
    sql += ' ORDER BY s.key, s.sample_id LIMIT ?'
    args.append(int(limit))
    return query(sql, args)


def measurements(prop=None, min_value=None, max_value=None, unit=None,
                 tier=None, located=None, section=None, key=None, limit=200):
    """测量层：一行一个数字，**带样品、条件、出处**。

    这是「能不能写进论文」的那张表：`located=True` 只要定位到了原文
    （表几图几）的那些 —— 其余的还得自己翻回去核对。

      prop      性能名（先按统一词表归一，再模糊匹配）
      located   True 只要有出处的；False 只要没出处的（= 待核清单）
      section   'main' 只要正文的；'si' 只要补充材料的
    """
    where, args = [], []
    if prop:
        canon = schema.normalize_property_name(prop)
        where.append('(m.name LIKE ? OR m.raw_name LIKE ?)')
        args += ['%' + canon + '%', '%' + prop.lower() + '%']
    if unit:
        where.append('LOWER(m.unit) LIKE ?')
        args.append('%' + unit.lower() + '%')
    if min_value is not None:
        where.append('m.value >= ?')
        args.append(min_value)
    if max_value is not None:
        where.append('m.value <= ?')
        args.append(max_value)
    if tier:
        where.append('p.tier = ?')
        args.append(tier)
    if section:
        where.append('m.section = ?')
        args.append(section)
    if key:
        where.append('m.key = ?')
        args.append(key)
    if located is not None:
        where.append("TRIM(COALESCE(m.location,'')) " + ('!=' if located else '=') + " ''")
    sql = ('SELECT m.key, p.title, m.sample_id, s.composition, m.name, m.value, '
           'm.value_max, m.unit, m.cmp, m."condition", m.location, m.section, '
           'm.method, p.tier, m.raw FROM measurements m '
           'LEFT JOIN papers p ON p.key = m.key '
           'LEFT JOIN samples s ON s.key = m.key AND s.sample_id = m.sample_id')
    if where:
        sql += ' WHERE ' + ' AND '.join(where)
    sql += ' ORDER BY m.name, m.value DESC LIMIT ?'
    args.append(int(limit))
    return query(sql, args)


def provenance():
    """数字的可追溯体温计：总条数里有多少带出处 / 带条件 / 挂到了具体样品。

    **这一栏才是数据库有没有长大的真指标** —— 篇数涨得再快，
    没有出处的数字依然不能写进论文（AGENTS.md 的零号判据同一个道理：
    「听起来很具体的数字最像事实，也最可能是编的」）。
    """
    rows = query(
        "SELECT COALESCE(p.tier,'(只有曲线)') tier, COUNT(*) n, "
        " SUM(CASE WHEN TRIM(COALESCE(m.location,'')) != '' THEN 1 ELSE 0 END) located,"
        " SUM(CASE WHEN TRIM(COALESCE(m.\"condition\",'')) != '' THEN 1 ELSE 0 END) with_condition,"
        " SUM(CASE WHEN COALESCE(m.sample_id,'main') != 'main' THEN 1 ELSE 0 END) with_sample,"
        ' SUM(CASE WHEN m.value IS NOT NULL THEN 1 ELSE 0 END) numeric,'
        " SUM(CASE WHEN m.section = 'si' THEN 1 ELSE 0 END) from_si"
        ' FROM measurements m LEFT JOIN papers p ON p.key = m.key'
        ' GROUP BY 1 ORDER BY n DESC')
    return rows

def curves(key=None, limit=200):
    """曲线层：一行一条曲线（哪篇的第几张图、什么曲线、多少个点、读得有多确信）。

    点本身存在 `points` 列里（JSON 字符串）—— 要画图或再分析就取那一列。
    """
    where, args = [], []
    if key:
        where.append('c.key = ?')
        args.append(key)
    sql = ('SELECT c.key, p.title, c.fig, c.series, c.chart_type, c.x_label, c.x_unit, '
           'c.y_label, c.y_unit, c.n_points, c.confidence, c.caption '
           'FROM curves c LEFT JOIN papers p ON p.key = c.key')
    if where:
        sql += ' WHERE ' + ' AND '.join(where)
    sql += ' ORDER BY c.key, c.fig, c.series LIMIT ?'
    args.append(int(limit))
    return query(sql, args)


def curve_points(key, fig, series=None):
    """某条曲线的原始点：`[[x, y], ...]`。同一张图有多条时 `series` 指名字。"""
    sql = 'SELECT series, points FROM curves WHERE key = ? AND fig = ?'
    args = [key, str(fig)]
    if series:
        sql += ' AND series = ?'
        args.append(series)
    out = []
    for r in query(sql, args):
        try:
            out.append({'series': r['series'], 'points': json.loads(r['points'] or '[]')})
        except Exception:
            out.append({'series': r['series'], 'points': []})
    return out
