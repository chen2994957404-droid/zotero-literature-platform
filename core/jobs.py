# -*- coding: utf-8 -*-
"""core.jobs —— 任务状态库（SQLite，标准库，零新依赖）。

**回答一个问题：这篇文献的这一步，做过没有？做成了吗？谁做的？**

为什么需要它（见 docs/架构重构_v2总体设计.md 第三节 A）：

    重构前，一篇文献做到哪一步，唯一的记录是 Zotero 上的标签 +
    「文件在不在」。于是：
      · 「只补缺的部分」要靠翻文件系统猜（有 summary.html 就算精读过了）
      · 失败了没有原因 —— 日志翻过去就没了，下次还是从头再来
      · 中断了不能续跑，重跑就要重新烧一次 MineRU + DeepSeek 的钱
      · 不知道某份 summary 是哪个模型、哪版提示词产的
      · 提示词升级后，没办法回答「哪些该重跑」

    一行记录 = 某篇文献的某个步骤的一次执行。有了它，
    「只补缺的部分」从文件系统考古变成一句 SQL。

用法（典型）：

    from core import jobs

    if jobs.is_done(key, 'main_summary', require='summary'):
        ...跳过...

    with jobs.track(key, 'main_summary', model='deepseek-v4-flash',
                    prompt_ver=2) as run:
        html = do_the_work()
        run.note(cost=0.12)            # 做完才知道的东西，补记进去
    # 正常退出 → status='ok'；抛异常 → status='failed'，记下异常文本后照样抛

    jobs.last(key, 'main_summary')     # 最后一次执行的完整记录（dict）
    jobs.history(key)                  # 这篇的全部执行记录
    jobs.stale('main_summary', prompt_ver=3)   # 提示词升到 3 之后，谁该重跑

设计约定：
    · **状态库是索引，不是真相。**真相永远是硬盘上的产物文件。
      库没了可以删掉重建（代价只是丢历史与溯源），产物没了才是真丢数据。
      所以 `is_done()` 默认还要求产物文件存在（require 参数）。
    · 只依赖标准库 sqlite3；开 WAL，允许 watcher 与控制面板同时读写。
    · **任何数据库故障都不许拖垮主流程** —— 记录失败只打日志，不抛异常。
      状态库是辅助设施，它坏了顶多让人少看见一些信息，不该让精读白做。
"""
import os
import sqlite3
import time

from core import paths
from core.log import get_logger

_log = get_logger('jobs')

# 状态取值（就这三个，别再加同义词）
RUNNING = 'running'
OK = 'ok'
FAILED = 'failed'

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    item_key    TEXT    NOT NULL,
    step        TEXT    NOT NULL,
    status      TEXT    NOT NULL,
    started_at  REAL    NOT NULL,
    finished_at REAL,
    producer    TEXT,
    prompt_ver  INTEGER,
    schema_ver  INTEGER,
    model       TEXT,
    cost        REAL,
    error       TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_key_step ON runs(item_key, step);
CREATE INDEX IF NOT EXISTS idx_runs_step_status ON runs(step, status);
"""

# 可写字段白名单：防止 note(**kw) 把任意字符串拼进 SQL
FIELDS = ('producer', 'prompt_ver', 'schema_ver', 'model', 'cost', 'error')

_conn_cache = {}


def db_path():
    """状态库文件在哪。"""
    return paths.state_db()


def connect(path=None):
    """打开（必要时创建）状态库。同一路径复用连接。

    WAL + 忙等 10 秒：watcher 在写、控制面板在读，是常态。
    """
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
        pass          # 网络盘上 WAL 可能不可用，退回默认模式，不算错误
    conn.executescript(_SCHEMA)
    conn.commit()
    _conn_cache[p] = conn
    return conn


def close():
    """关掉所有连接（测试用；正常运行期不需要调）。"""
    for conn in _conn_cache.values():
        try:
            conn.close()
        except sqlite3.Error:
            pass
    _conn_cache.clear()


def _safe(fn, what, default=None):
    """状态库出任何问题都只记一笔日志 —— 它不该拖垮正在干活的主流程。"""
    try:
        return fn()
    except Exception as e:
        _log.warn(f'任务状态库{what}失败（不影响主流程）：{type(e).__name__}: {e}')
        return default


def _fields(kw):
    """挑出白名单字段，返回 (列名列表, 值列表)。不认识的键直接忽略。"""
    cols = [k for k in FIELDS if k in kw and kw[k] is not None]
    return cols, [kw[k] for k in cols]


# ── 写 ────────────────────────────────────────────────────────────────
def start(key, step, **kw):
    """记一笔「开始做了」，返回 run id（状态库不可用时返回 None）。"""
    k = paths.check_key(key)

    def go():
        cols, vals = _fields(kw)
        sql = ('INSERT INTO runs (item_key, step, status, started_at'
               + ''.join(', ' + c for c in cols) + ') VALUES (?,?,?,?'
               + ',?' * len(cols) + ')')
        conn = connect()
        cur = conn.execute(sql, [k, step, RUNNING, time.time()] + vals)
        conn.commit()
        return cur.lastrowid
    return _safe(go, '写入')


def finish(run_id, status=OK, **kw):
    """给一笔执行收尾。status ∈ {'ok','failed'}。"""
    if run_id is None:
        return

    def go():
        cols, vals = _fields(kw)
        sql = ('UPDATE runs SET status=?, finished_at=?'
               + ''.join(', ' + c + '=?' for c in cols) + ' WHERE id=?')
        conn = connect()
        conn.execute(sql, [status, time.time()] + vals + [run_id])
        conn.commit()
    _safe(go, '写入')


def fail(run_id, error, **kw):
    """失败收尾。异常文本截到 500 字 —— 状态库存的是线索，不是日志。"""
    kw.pop('error', None)
    finish(run_id, FAILED, error=str(error)[:500], **kw)


class track:
    """上下文管理器：进去 start，正常出来 finish，抛异常则 fail 后照样抛。

        with jobs.track(key, 'main_summary', model=MODEL) as run:
            ...
            run.note(cost=0.12)

    「照样抛」很重要：状态库负责**记录**发生了什么，不负责**改变**发生了什么。
    """

    def __init__(self, key, step, **kw):
        self.key, self.step, self.kw = key, step, dict(kw)
        self.id = None

    def __enter__(self):
        self.id = start(self.key, self.step, **self.kw)
        return self

    def note(self, **kw):
        """补记字段（做完才知道的东西：花了多少钱、实际用的哪个模型）。"""
        self.kw.update(kw)
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc is None:
            finish(self.id, OK, **self.kw)
        else:
            fail(self.id, exc_type.__name__ + ': ' + str(exc), **self.kw)
        return False          # 不吞异常


# ── 读 ────────────────────────────────────────────────────────────────
def _rows(sql, args=()):
    def go():
        return [dict(r) for r in connect().execute(sql, args).fetchall()]
    return _safe(go, '读取', default=[])


def last(key, step=None):
    """某篇（某步）最后一次执行的记录；没有则 None。"""
    k = paths.check_key(key)
    if step:
        rows = _rows('SELECT * FROM runs WHERE item_key=? AND step=?'
                     ' ORDER BY id DESC LIMIT 1', (k, step))
    else:
        rows = _rows('SELECT * FROM runs WHERE item_key=?'
                     ' ORDER BY id DESC LIMIT 1', (k,))
    return rows[0] if rows else None


def history(key, limit=200):
    """某篇的全部执行记录，新到旧。"""
    return _rows('SELECT * FROM runs WHERE item_key=? ORDER BY id DESC LIMIT ?',
                 (paths.check_key(key), limit))


def is_done(key, step, require=None, prompt_ver=None, schema_ver=None):
    """这一步做完了吗？—— 「只补缺的部分」的唯一判据。

    三个条件按「最不可能骗人」的顺序检查：

      1. `require`：产物文件在不在（**真相在硬盘上**，状态库只是索引）。
         传产物名（core.paths 里的产物函数名，如 'summary'）。
      2. 状态库里最后一次是不是 ok。
      3. 若给了 prompt_ver / schema_ver：产它的版本够不够新
         —— 提示词升级后，旧版本产物自动被判为「没做完」，进重跑清单。

    状态库不可用时退化成「只看产物文件」—— 这正是它作为索引而非真相的含义：
    没有它，系统只是少了溯源与断点，不会停摆。
    """
    if require and not paths.has(key, require):
        return False
    row = last(key, step)
    if row is None:
        # 状态库里没记录，产物却在 —— 那是状态库上线之前做的，认它。
        return bool(require)
    if row['status'] != OK:
        return False
    for name, want in (('prompt_ver', prompt_ver), ('schema_ver', schema_ver)):
        if want is not None and (row[name] or 0) < want:
            return False
    return True


def stale(step, prompt_ver=None, schema_ver=None):
    """哪些文献的这一步该重跑（版本落后，或上次没成功）。返回 key 列表。

    「升级即查询」：提示词升到 v3 → `stale('main_summary', prompt_ver=3)`
    就是待重跑清单，不用翻文件系统，也不用人肉记得改过什么。
    """
    rows = _rows(
        'SELECT r.* FROM runs r JOIN (SELECT item_key, MAX(id) mid FROM runs'
        ' WHERE step=? GROUP BY item_key) m ON r.id = m.mid', (step,))
    out = []
    for r in rows:
        if r['status'] != OK:
            out.append(r['item_key'])
            continue
        if ((prompt_ver is not None and (r['prompt_ver'] or 0) < prompt_ver)
                or (schema_ver is not None and (r['schema_ver'] or 0) < schema_ver)):
            out.append(r['item_key'])
    return sorted(set(out))


def summary(step=None):
    """按步骤统计 {步骤: {状态: 条数}}，给控制面板显示进度用。"""
    sql = 'SELECT step, status, COUNT(*) n FROM runs'
    args = ()
    if step:
        sql += ' WHERE step=?'
        args = (step,)
    sql += ' GROUP BY step, status'
    out = {}
    for r in _rows(sql, args):
        out.setdefault(r['step'], {})[r['status']] = r['n']
    return out


def running(older_than=None):
    """还挂着 running 的执行（进程被杀、断电会留下这种记录）。

    older_than：只列开始超过这么多秒的，用来区分「正在干活」和「早就死了」。
    """
    rows = _rows("SELECT * FROM runs WHERE status='running' ORDER BY id DESC")
    if older_than is None:
        return rows
    now = time.time()
    return [r for r in rows if now - (r['started_at'] or now) > older_than]
