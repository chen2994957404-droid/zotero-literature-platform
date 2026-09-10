# -*- coding: utf-8 -*-
"""deepread · 精读一篇文献 → 一份中文图文精读报告。

平台最常用、最有价值的那条线。一个 Zotero item key 进去，
`library/<key>/summary.html`（必要时还有 `summary_full.html`）出来。

**对外契约**（别的地方只许调这些；`cli.py` / `mcp.py` 也只许调这些）：

| 入口 | 干什么 |
|---|---|
| `run(key, ...) → Result`   | **主入口**：解析 → 正文精读 →（有SI就精读SI）→ 合并 |
| `Result.state`             | `'full'/'main'/'si'/'nopdf'/'failed'` —— 实际做成了什么 |
| `Result.final_html`        | 该拿去回写 Zotero 的那份 |
| `DeepreadFailed` / `SIFailed` | 单步失败的异常类型 |
| `batch.read_many / si_many / upload_many / rerun_with_pro` | 批量与回写 |
| `tags.set_state_tag`       | 事实 → Zotero 状态标签（策略只在这一层） |

包内文件：`main_text.py` 正文 · `si.py` 补充材料 · `merge.py` 合并 ·
`batch.py` 批量与回写 · `tags.py` 标签状态机。
常驻服务（打标签即自动精读）不在这里，在 `host/watcher/` ——
它要串起 deepread 与 extract 两个工具，跨工具编排属于 host（R7 窗判定）。

**为什么是一个函数而不是一串脚本**：在它之前，这条工作流是 watcher 里五个
子进程调用串起来的，接口是「脚本路径 + 参数顺序」。于是改个参数次序运行时才炸；
失败只拿得到退出码和一坨 stdout；中断了不能续跑；不知道某份产物是谁产的。

现在它由 step 组成，每个 step 都：
  · **幂等** —— 产物在且状态库说做成了，就跳过（省 MineRU + DeepSeek 的钱）
  · **记账** —— 谁、哪个模型、哪版提示词、花了多久、失败原因，进 `shared.kernel.jobs`
  · **可单独失败** —— SI 失败不该让正文精读白做

用法：

    from tools import deepread
    r = deepread.run(key, provider='deepseek', model='deepseek-v4-flash')

**`run()` 不写 Zotero、不改标签**（那是 `host.watcher` / `batch` 的事，
也是两台机器分工的闸门所在）。`r.state` 是事实，标签怎么打由调用方决定。
"""
import json
import os
import time

from shared.kernel import jobs, paths

from tools.deepread import main_text, merge as _merge, si as _si
from tools.deepread.main_text import DeepreadFailed   # noqa: F401 —— 对外再导出
from tools.deepread.si import SIFailed                # noqa: F401

# 「没传」和「传了个空」是两回事：pdf_path=None 明确表示**这篇没有正文 PDF**，
# 不该被当成「你没告诉我，我自己去 Zotero 查」——后者会白跑一次网络调用，
# 在没开 Zotero 的机器上还会得出与调用方相反的结论。
_ASK = object()

STEP_PARSE = 'parse'
STEP_MAIN = 'main_summary'
STEP_SI = 'si_summary'
STEP_MERGE = 'merge'


class Result:
    """一次精读的结果。**只陈述事实，不做决定。**

    state 取值（这是「实际做成了什么」，不是 Zotero 标签名）：
        'full'   正文 + SI 都有了
        'main'   只有正文
        'si'     只有 SI（罕见）
        'nopdf'  没有任何可精读的附件
        'failed' 该做的没做成
    """

    def __init__(self, key):
        self.key = key
        self.main_done = False
        self.si_done = False
        self.final_html = None
        self.state = 'failed'
        self.steps = []          # [(step, 'ok'/'failed'/'skipped', 说明)]
        self.error = None

    def _mark(self, step, status, note=''):
        self.steps.append((step, status, note))

    def __repr__(self):
        return f'<Result {self.key} {self.state} steps={len(self.steps)}>'


def _write_meta(key, item=None, model=''):
    """meta.json —— 向量化与问答要靠它知道这篇是什么。写失败不影响精读。"""
    try:
        data = (item or {}).get('data', {}) if item else {}
        meta = {'key': key, 'title': data.get('title', ''),
                'DOI': data.get('DOI', ''), 'date': data.get('date', ''),
                'model': model, 'time': time.strftime('%Y-%m-%d %H:%M')}
        old = {}
        if os.path.exists(paths.meta(key)):
            try:
                old = json.load(open(paths.meta(key), encoding='utf-8'))
            except Exception:
                old = {}
        # 没拿到 item 时别把已有的标题/DOI 抹成空 —— 半成品元数据比没有更难查
        for k, v in list(meta.items()):
            if not v and old.get(k):
                meta[k] = old[k]
        paths.paper_dir(key, create=True)
        json.dump(meta, open(paths.meta(key), 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
    except Exception:
        pass


def run(key, item=None, pdf_path=_ASK, si_exists=_ASK, provider='deepseek',
        model='deepseek-v4-flash', llm_key='', force=False, log=print):
    """把一篇文献从 PDF 做成精读。**幂等**：做过的步骤自动跳过。

    参数：
      item       Zotero 条目（只用来写 meta.json；不传就只记 key）
      pdf_path   正文 PDF 路径；**不传**则自己去 Zotero 找（传 None = 明确没有）
      si_exists  这篇有没有 SI；**不传**则自己去 Zotero 问
      force      连做过的也重做（会重新花钱）

    返回 `Result`。**不抛异常**：单步失败记在 result 里，别的步骤照做。
    """
    key = paths.check_key(key)
    r = Result(key)

    if pdf_path is _ASK or si_exists is _ASK:
        from shared.adapters.zotero_client import find_pdf, has_si
        if pdf_path is _ASK:
            pdf_path = find_pdf(key)
        if si_exists is _ASK:
            si_exists = has_si(key)

    main_done = (not force) and jobs.is_done(key, STEP_MAIN, require='summary',
                                             prompt_ver=main_text.PROMPT_VER)
    si_done = (not force) and jobs.is_done(key, STEP_SI, require='si_summary',
                                           prompt_ver=_si.PROMPT_VER)
    log(f'  正文PDF:{"有" if pdf_path else "无"} SI:{"有" if si_exists else "无"} '
        f'| 已精读 正文:{"是" if main_done else "否"} SI:{"是" if si_done else "否"}')

    if not pdf_path and not si_exists:
        log('  [跳过] 无任何可精读的PDF附件')
        r.state = 'nopdf'
        r._mark(STEP_MAIN, 'skipped', '无附件')
        return r

    # ── A. 正文：有 PDF 且没精读过才做 ──
    if pdf_path and not main_done:
        try:
            parsed = _ensure_parsed(key, pdf_path, force=force, log=log)
            r._mark(STEP_PARSE, 'ok')
        except Exception as e:
            log(f'  [正文解析失败] {e}')
            r._mark(STEP_PARSE, 'failed', str(e)[:200])
            r.error = str(e)
            parsed = None
        if parsed:
            try:
                with jobs.track(key, STEP_MAIN, producer=main_text.PRODUCER,
                                model=model, prompt_ver=main_text.PROMPT_VER):
                    d = (item or {}).get('data', {}) if item else {}
                    main_text.read_main(parsed, paths.summary(key), provider=provider,
                                        model=model, key=llm_key, log=log,
                                        title=d.get('title'), doi=d.get('DOI'))
                main_done = True
                r._mark(STEP_MAIN, 'ok')
                log('  [正文精读完成]')
            except Exception as e:
                log(f'  [正文精读失败] {e}')
                r._mark(STEP_MAIN, 'failed', str(e)[:200])
                r.error = r.error or str(e)
    elif main_done:
        log('  [跳过正文] 已有精读，不重跑')
        r._mark(STEP_MAIN, 'skipped', '已有精读')

    # ── B. SI：有 SI 且没精读过才做 ──
    # SI 失败不许拖累正文 —— 两件产物本来就各自独立生成（用户 2026-07-25 定）。
    if si_exists and not si_done:
        try:
            with jobs.track(key, STEP_SI, producer=_si.PRODUCER,
                            prompt_ver=_si.PROMPT_VER) as t:
                out = _si.read_si(key, log=log)
                t.note(model=os.environ.get('SI_MODEL', 'deepseek-v4-flash'))
            si_done = bool(out)
            r._mark(STEP_SI, 'ok' if si_done else 'skipped',
                    '' if si_done else '没有 SI 附件')
        except Exception as e:
            log(f'  [SI精读失败] {e}')
            r._mark(STEP_SI, 'failed', str(e)[:200])
    elif si_done:
        log('  [跳过SI] 已有精读，不重跑')
        r._mark(STEP_SI, 'skipped', '已有精读')

    r.main_done, r.si_done = main_done, si_done

    # ── C. 合并（两者都有时）──
    final = paths.summary(key) if main_done else None
    if main_done and si_done:
        try:
            with jobs.track(key, STEP_MERGE, producer='merge_summary'):
                merged = _merge.merge(key, log=log)
            if merged:
                final = merged
                r._mark(STEP_MERGE, 'ok')
                log('  [已合并] 正文+SI')
        except Exception as e:
            log(f'  [合并失败] {e}')
            r._mark(STEP_MERGE, 'failed', str(e)[:200])
    elif si_done and not main_done:
        final = paths.si_summary(key)

    if not final or not os.path.exists(final):
        log('  [失败] 没有产出任何精读')
        r.state = 'failed'
        return r

    r.final_html = final
    r.state = 'full' if (main_done and si_done) else ('main' if main_done else 'si')
    _write_meta(key, item, model)
    return r


def _ensure_parsed(key, pdf_path, force=False, log=print):
    """PDF → parsed/（MineRU）。已解析则直接复用，**这是省钱的关键一步**。"""
    parsed = paths.parsed_dir(key, create=True)
    if not force and os.path.exists(paths.layout(key)):
        log('  [复用] 已有解析结果')
        return parsed
    from shared.adapters.pdf_parse import parse_pdf
    with jobs.track(key, STEP_PARSE, producer='mineru'):
        parse_pdf(pdf_path, parsed, reuse=not force)
    return parsed


# ── 排队与查进度（2026-09-10 加）──────────────────────────────────────
# **为什么是「排队」而不是「精读」**：精读一篇要跑几分钟，远超 MCP 约 60 秒的
# 调用上限，做不成同步 tool（`tool.toml` 里早写着这个判断）。
# 而平台本来就有一条更省事的路 —— 在 Zotero 打「待处理」标签，常驻服务自动做完全套。
# 所以给模型开的入口是**打标签**：快、幂等、可逆，真正花钱的活由 watcher 在后台干，
# 那一侧有 `shared.kernel.budget` 的当日额度闸兜着。

def request(item_key, log=print):
    """把一篇排进精读队列（= 打「待处理」标签）。返回 dict(ok, action, note)。

    **幂等**：已经在队列里就说在队列里，已经精读完的会告诉你到哪一步了 ——
    不重复打标签，也不谎称「已安排」。

    action：`queued`（排上了）/ `already_queued`（本来就在队里）/
            `already_done`（已经精读过，附带当前状态）/ `failed`
    """
    from shared.kernel import role
    from shared.adapters import zotero_client as zotero
    from tools.deepread import tags as T

    out = {'ok': False, 'action': 'failed', 'note': '', 'state': ''}
    try:
        role.require_prod(f'把文献 {item_key} 排进精读队列（会写 Zotero 标签，'
                          f'随后常驻服务会真的去精读 —— 那一步要花钱）')
        cur = zotero.get_item(item_key)
        have = [t.get('tag') for t in (cur.get('data') or {}).get('tags', [])
                if t.get('tag') in T.ALL_STATE_TAGS]
        out['state'] = '/'.join(have)
        if any(t in T.TRIGGER_TAGS for t in have):
            out.update(ok=True, action='already_queued',
                       note='本来就在队列里，没有重复打标签。')
            return out
        done = [t for t in have if t in (T.TAG_FULL, T.TAG_MAIN, T.TAG_MAIN_WX, T.TAG_SI)]
        if done:
            out.update(ok=True, action='already_done',
                       note=f'已经精读过（{"/".join(done)}）。'
                            f'要补 SI 或重跑，仍然可以再打一次「待处理」——'
                            f'状态机只会补缺的那部分，不会整篇重来。')
            return out
        T.set_state_tag(item_key, T.TRIGGER_TAG, log=log)
        out.update(ok=True, action='queued',
                   note='排上了。常驻服务下一轮轮询（约一分钟内）会接手，'
                        '一篇要跑几分钟。用 deepread_status 查进度，别干等。')
    except Exception as e:
        out['note'] = f'{type(e).__name__}: {e}'
    return out


def status(item_key):
    """这篇精读到哪一步了。**只读、免费** —— 给「发起后轮询」用。

    同时看两处，因为它们可能不一致（写回 Zotero 失败时产物已经在盘上了）：
      · Zotero 的状态标签  —— 用户在客户端里看到的
      · 本地产物文件       —— 真正做出来了什么
    """
    import os

    from shared.adapters import zotero_client as zotero
    from tools.deepread import tags as T

    out = {'key': item_key, 'tag': '', 'summary': False, 'summary_full': False,
           'title': '', 'note': ''}
    try:
        it = zotero.item(item_key)
        d = it.get('data', it)
        out['title'] = (d.get('title') or '')[:80]
        out['tag'] = '/'.join(t.get('tag') for t in (d.get('tags') or [])
                              if t.get('tag') in T.ALL_STATE_TAGS)
    except Exception as e:
        out['note'] = f'读 Zotero 失败：{type(e).__name__}'
    out['summary'] = os.path.exists(paths.summary(item_key))
    out['summary_full'] = os.path.exists(paths.summary_full(item_key))
    if not out['tag'] and not out['summary']:
        out['note'] = out['note'] or '还没排队，也没有任何精读产物。'
    elif out['tag'] in T.TRIGGER_TAGS and not out['summary']:
        out['note'] = '在队列里，还没轮到或正在跑。'
    return out
