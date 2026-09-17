# -*- coding: utf-8 -*-
"""host.daily —— 每天一次的作业：盯新刊 → 补摘要 / 分类 → 过线入队 → 自动升 1 级取件。

**为什么是自己的进程**（2026-09-17 用户定）：这一串原来挤在精读监听的循环里，
一天一次、一跑几十分钟（OpenAlex 补几千篇摘要、借浏览器取十篇），期间用户打的
「待处理」标签得干等。盯新刊和盯标签本来就是不同的活，就该是不同的进程。
由看门狗 `host.watcher.watchdog` 每天凌晨拉一次，跑完退出；有单实例锁，重复拉是安全的。

## 它为什么住在 host/

串了两个工具：`journalwatch`（雷达）→ `getpdf.land`（落正本）。跨工具编排只能上浮到 host。

## 每步花什么

| 步 | 问谁 | 花什么 |
|---|---|---|
| 盯新刊 | Crossref | 免费，几十次请求 |
| 补摘要 | OpenAlex ≤200 次 · Semantic Scholar ≤3000 篇 | 免费 |
| 补分类 | OpenAlex ≤100 次 | 免费 |
| 升 1 级 | 出版商（借浏览器，机构权限）≤ HARVEST_PER_DAY 篇 | 不花模型钱；随后 `host.ingest` 自动解析 |

    python -m host.daily            # 手动跑一次（主力机 / 测试角色）
"""
import time

from shared.kernel import heartbeat
from shared.kernel.log import get_logger

log = get_logger('daily')

BEACON = 'daily'
# 盯新刊过线后每天自动升 1 级的上限（2026-09-16）：MineRU 每天 1000 页优先额度 ≈ 25 篇，留一半给打标签的精读
HARVEST_PER_DAY = 10


def run(say=log):
    """跑一整天的活。每步各自 try：一步挂了不该拖累后面的（取件挂了也不该让补摘要白做）。"""
    from tools import journalwatch
    heartbeat.progress(BEACON)
    t0 = time.time()
    # ① 盯新刊：问 Crossref 登记处，新文章的题目 / 摘要 / 参考文献进雷达库
    r = journalwatch.patrol(days=3, log=lambda *a: None, only_new=True)
    say(f'[盯新刊] {r["n_journals"]} 本刊，首见 {len(r["items"])} 篇，'
        f'过线 {sum(1 for w in r["items"] if w.get("passes"))} 篇'
        + (f'；没查成：{"、".join(r["failed"])}' if r['failed'] else ''))
    heartbeat.progress(BEACON)
    # ② 补摘要 / 被引 / 开放获取直链
    for name, fn in (('OpenAlex', lambda: journalwatch.fill_abstracts(max_calls=200, log=lambda *a: None)),
                     ('Semantic Scholar', lambda: journalwatch.fill_from_s2(max_papers=3000, log=lambda *a: None))):
        try:
            f, n = fn()
            if n:
                say(f'[补摘要] {name} 问了 {n} 篇，补上 {f} 篇')
        except Exception as e:
            say(f'[补摘要失败] {name}: {type(e).__name__}: {e}')
        heartbeat.progress(BEACON)
    # ③ 补分类（门槛要看 OpenAlex 的学科分类）
    try:
        ft, nt = journalwatch.fill_topics(days=60, max_calls=100, log=lambda *a: None)
        if nt:
            say(f'[补分类] OpenAlex 问了 {nt} 篇，拿到 {ft} 篇')
    except Exception as e:
        say(f'[补分类失败] {type(e).__name__}: {e}')
    heartbeat.progress(BEACON)
    # ④ 过线 → 升 1 级：每天最多 HARVEST_PER_DAY 篇。取的是正本 + SI 落地（不精读、不花模型钱）；
    #    落地流水线随后自动解析 / 骨架 / 向量化。取不到的隔天再试（刚登记的全文常常几天后才挂出来）。
    got = 0
    q_new = journalwatch.enqueue_passing(r['items']) + journalwatch.enqueue_recent(days=60)
    todo = journalwatch.next_to_harvest(HARVEST_PER_DAY)
    if todo:
        from tools import getpdf
        for doi, info in todo:
            try:
                res = getpdf.land(doi, with_si=True)
                ok = bool(res.get('ok'))
                journalwatch.mark_harvest(doi, ok, res.get('note', ''))
                got += ok
                say(f'  [升1级] {"✓" if ok else "×"} {info.get("venue","")[:20]} 引{info.get("lib_cites",0)}篇 '
                    f'{info.get("title","")[:60]}' + ('' if ok else f' —— {res.get("note","")[:60]}'))
            except Exception as e:
                journalwatch.mark_harvest(doi, False, str(e))
                say(f'  [升1级失败] {doi}: {type(e).__name__}: {str(e)[:80]}')
            heartbeat.progress(BEACON)
    say(f'[升1级] 新入队 {q_new} 篇；今天取了 {got}/{len(todo)} 篇；全程 {int(time.time() - t0)} 秒')
    heartbeat.done(BEACON)
    return {'new': len(r['items']), 'queued': q_new, 'harvested': got, 'todo': len(todo)}
