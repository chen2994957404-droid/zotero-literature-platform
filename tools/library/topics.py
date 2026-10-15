# -*- coding: utf-8 -*-
"""tools.library.topics · 专题：把一批文献归到一个有名字的组里（2026-10-15 用户提）。

**为什么要有**：用户让 Claude Science 辅助写综述，它借平台下了很多篇；都在库里，但一篇篇打开找太麻烦。
用户的原话：「给 Claude 权限把这篇论文相关的参考文献专门放到个类似团队里」。
于是：一个专题 = 一个名字 + 若干篇文献（每篇可带一句备注，比如「第 3 节引用」）。
文献库应用里跟「团队」一样能按专题筛；Claude Science 在 /science 上建、加、删。

**存在 `paths.topics_db()`（SQLite，state 层）**：这是人 / agent 整理出来的，**不可重建**。
用 SQLite 而不是 JSON：应用后台、MCP 服务、命令行三个进程会同时读写，靠它的锁。

文献用证据库 id 记；加的时候可以给 DOI（含 doi.org 前缀、文件夹名写法）或 id（旧的 8 位编号也认）。
证据库里还没有的，不记、在 `missing` 里如实报出来 —— 先取全文进库再加。

| 函数 | 干什么 |
|---|---|
| `list_topics()` | 全部专题（名字、备注、篇数、谁建的、更新时间）|
| `add(topic, refs, note, by)` | 往专题里加文献；专题不存在就新建 → {topic, added, already, missing} |
| `remove(topic, refs)` | 从专题里拿掉文献（文献本身不动）|
| `delete_topic(topic)` / `rename(topic, new)` / `set_note(topic, note)` | 管专题本身 |
| `items(topic)` | 专题里的文献 [{pid, note, added_by, added_at}] |
| `pids(topic)` / `topics_of(pid)` | 给检索筛选与文献卡片用 |
"""
import os
import sqlite3
import time

from shared.kernel import catalog, paths


def _con():
    os.makedirs(os.path.dirname(paths.topics_db()), exist_ok=True)
    con = sqlite3.connect(paths.topics_db(), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute('pragma foreign_keys = on')
    con.execute('create table if not exists topics (id integer primary key autoincrement, name text unique not null, '
                "note text default '', created_by text default '', created_at real, updated_at real)")
    con.execute('create table if not exists items (topic_id integer not null references topics(id) on delete cascade, '
                "pid text not null, note text default '', added_by text default '', added_at real, "
                'primary key (topic_id, pid))')
    return con


def _norm_name(name):
    return ' '.join((name or '').split())


def _topic_row(con, topic):
    """名字或数字 id → 行；没有返回 None。"""
    t = str(topic or '').strip()
    if t.isdigit():
        r = con.execute('select * from topics where id=?', (int(t),)).fetchone()
        if r:
            return r
    return con.execute('select * from topics where name=?', (_norm_name(t),)).fetchone()


def resolve_ref(ref):
    """DOI / 证据库 id → 证据库里的 id；不在库里返回 ''。"""
    ref = (ref or '').strip()
    if not ref:
        return ''
    doi = catalog.norm_doi(ref.replace('doi_', '', 1) if ref.lower().startswith('doi_10.') else ref)
    if doi.startswith('10.'):
        pid = catalog.find(doi)
        if pid:
            return pid
    try:
        pid = catalog.resolve(ref)
    except paths.BadKeyError:
        return ''
    return pid if (os.path.isdir(paths.paper_dir(pid)) or os.path.isdir(paths.paper_raw_dir(pid))) else ''


def list_topics():
    with _con() as con:
        rows = con.execute('select t.*, (select count(*) from items i where i.topic_id=t.id) as n '
                           'from topics t order by t.updated_at desc').fetchall()
        return [dict(r) for r in rows]


def get(topic):
    with _con() as con:
        r = _topic_row(con, topic)
        return dict(r) if r else None


def add(topic, refs, note='', by='', topic_note=None):
    """往专题里加文献；专题不存在就新建。重复加同一篇不报错（备注给了就更新）。"""
    name = _norm_name(topic)
    if not name:
        raise ValueError('专题名不能为空')
    now = time.time()
    out = {'topic': name, 'added': [], 'already': [], 'missing': []}
    with _con() as con:
        r = _topic_row(con, name)
        if r is None:
            con.execute('insert into topics (name, note, created_by, created_at, updated_at) values (?,?,?,?,?)',
                        (name, topic_note or '', by, now, now))
            r = _topic_row(con, name)
        elif topic_note is not None:
            con.execute('update topics set note=? where id=?', (topic_note, r['id']))
        tid = r['id']
        out['topic'] = r['name']
        for ref in refs or []:
            pid = resolve_ref(ref)
            if not pid:
                out['missing'].append(ref)
                continue
            have = con.execute('select 1 from items where topic_id=? and pid=?', (tid, pid)).fetchone()
            if have:
                if note:
                    con.execute('update items set note=? where topic_id=? and pid=?', (note, tid, pid))
                out['already'].append(pid)
            else:
                con.execute('insert into items (topic_id, pid, note, added_by, added_at) values (?,?,?,?,?)',
                            (tid, pid, note or '', by, now))
                out['added'].append(pid)
        con.execute('update topics set updated_at=? where id=?', (now, tid))
    return out


def remove(topic, refs):
    out = {'topic': '', 'removed': [], 'not_in_topic': []}
    with _con() as con:
        r = _topic_row(con, topic)
        if r is None:
            raise ValueError(f'没有专题「{topic}」')
        out['topic'] = r['name']
        for ref in refs or []:
            pid = resolve_ref(ref) or ref
            n = con.execute('delete from items where topic_id=? and pid=?', (r['id'], pid)).rowcount
            (out['removed'] if n else out['not_in_topic']).append(pid)
        con.execute('update topics set updated_at=? where id=?', (time.time(), r['id']))
    return out


def delete_topic(topic):
    with _con() as con:
        r = _topic_row(con, topic)
        if r is None:
            return False
        con.execute('delete from topics where id=?', (r['id'],))
        return True


def rename(topic, new_name):
    new_name = _norm_name(new_name)
    if not new_name:
        raise ValueError('新名字不能为空')
    with _con() as con:
        r = _topic_row(con, topic)
        if r is None:
            raise ValueError(f'没有专题「{topic}」')
        con.execute('update topics set name=?, updated_at=? where id=?', (new_name, time.time(), r['id']))
    return new_name


def set_note(topic, note):
    with _con() as con:
        r = _topic_row(con, topic)
        if r is None:
            raise ValueError(f'没有专题「{topic}」')
        con.execute('update topics set note=?, updated_at=? where id=?', (note or '', time.time(), r['id']))


def items(topic):
    with _con() as con:
        r = _topic_row(con, topic)
        if r is None:
            return []
        return [dict(x) for x in con.execute('select pid, note, added_by, added_at from items where topic_id=? '
                                             'order by added_at', (r['id'],))]


def pids(topic):
    return {x['pid'] for x in items(topic)}


def topics_of(pid):
    """这篇在哪些专题里 → [{name, note}]（note 是这篇在该专题里的备注）。"""
    with _con() as con:
        return [dict(x) for x in con.execute('select t.name, i.note from items i join topics t on t.id=i.topic_id '
                                             'where i.pid=? order by t.name', (pid,))]


def membership():
    """{pid: [专题名…]} —— 检索结果一次性带上专题，不必每篇问一次库。"""
    out = {}
    with _con() as con:
        for x in con.execute('select i.pid, t.name from items i join topics t on t.id=i.topic_id'):
            out.setdefault(x['pid'], []).append(x['name'])
    return out
