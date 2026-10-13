# -*- coding: utf-8 -*-
"""deepread · 批量：一批 key → 精读。（2026-10-13 起不再回写 Zotero —— Zotero 移出平台。）

R2 窗（2026-08-30）把 `文献精读/` 下六个各自为政的脚本并进这一个文件：

    deepread_batch.py       批量正文精读
    si_batch.py             批量补 SI 精读（原来靠 subprocess 拉起兄弟脚本）
    rerun_pro.py            用 pro 重跑某篇
    upload_summaries.py     批量回写 summary 附件 + 打标签
    refresh_summary_file.py 把新版精读刷进本地 storage
    merge_summary.py        合并后回写（合并本身在 merge.py）

为什么并：它们做的是同一件事的六个切面，却各自实现了一遍
「找附件 / 传附件 / 铺本地文件 / 打标签」—— 同一个 bug 要修四遍
（踩坑 #28 的「先删后传」就修了一份忘了另一份）。

**对外契约**（`cli.py` 与 `mcp.py` 只许调这些，R4 窗接）：

| 函数 | 干什么 | 花钱 |
|---|---|---|
| `read_many(keys, force)`     | 批量正文精读（复用已有解析） | 是 |
| `si_many(keys)`              | 批量补 SI → 合并 | 是 |
| `rerun_candidates()`         | 哪些篇可以用 pro 重跑（解析还在） | 否 |
| `rerun_with_pro(key, title)` | 用 pro 重跑一篇正文精读 | 是 |

**花钱的一律在函数体里先过 `role.require_prod`**（见 code-redlines）。
"""
import json
import os
import shutil

from shared.kernel import jobs, paths, role
from shared.kernel.config import get_key, get_model
from tools.deepread import main_text, merge as _merge, si as _si
from tools.deepread import STEP_MAIN, STEP_SI

PROVIDER = 'deepseek'
PRO_MODEL = 'deepseek-v4-pro'      # 想细品的那几篇才用它（贵约 3 倍）


def _model():
    """老接口：面板里的模型设置项。批量入口的日志用；真正走哪条路由看 _route_model。"""
    return get_model('DEEPREAD_MODEL')


def _route_model():
    """路由表实际会用的「通道/模型」，记进状态库。"""
    from shared.kernel.config import routing
    p = routing.purposes()['DEEPREAD']
    return '%s/%s' % (p['channel'], p['model'])


# ───────────────────────── 批量精读 ─────────────────────────

def read_one(key, force=False, model=None, log=print):
    """精读一篇正文，**复用已有的 MineRU 解析结果**（不再消耗解析额度）。

    没有解析结果就跳过 —— 要连解析一起做请走 `deepread.run(key)`。
    """
    key = paths.check_key(key)
    model = model or None          # None = 让路由表定（显式给 PRO_MODEL 才覆盖）
    parsed = paths.parsed_dir(key)
    if not os.path.exists(paths.layout(key)):
        log('  [跳过] 无 parsed 解析结果（需先精抽/MineRU）')
        return False
    out_html = paths.summary(key)
    if os.path.exists(out_html) and not force:
        log('  [复用] 已有 summary.html（force 可强制重跑）')
        return True
    if force and os.path.exists(out_html):
        # 重跑前备份旧的，万一新的更差还能还原（可逆是自主执行的前提）
        bak = out_html + '.bak'
        if not os.path.exists(bak):
            shutil.copy2(out_html, bak)
            log('  [备份] 旧版存为 summary.html.bak')
    # 直接调函数，不再拉子进程 —— 失败拿得到原因，不只是退出码。
    # 每次执行都记进 shared.kernel.jobs（哪个模型、哪版提示词、失败原因）。
    with jobs.track(key, STEP_MAIN, producer=main_text.PRODUCER,
                    model=model or _route_model(), prompt_ver=main_text.PROMPT_VER):
        main_text.read_main(parsed, out_html, provider=PROVIDER, model=model, log=log,
                            paper_key=key)
    log(f'  [完成] summary.html {round(os.path.getsize(out_html) / 1024)} KB')
    return True


def read_many(keys, force=False, log=print):
    """批量正文精读。返回 (成功, 失败/跳过)。"""
    role.require_prod('批量精读（调用付费 API）', force=force)
    # ⚠ 别把老设置项 DEEPREAD_MODEL 当模型显式传下去（2026-09-17 真撞上）：路由表已指向本地 Ollama，
    #   显式传 'deepseek-v4-flash' 等于让 Ollama 找一个它没有的模型 → 404 → 每一栏都静默切到云端备用，
    #   看日志才知道「本地精读」其实一行都没在本地跑。model=None = 路由表说了算。
    model = None
    log(f'批量精读 {len(keys)} 篇（{_route_model()}{"，强制重跑" if force else ""}）\n')
    ok = fail = 0
    for i, key in enumerate(keys, 1):
        log(f'[{i}/{len(keys)}] {key}')
        try:
            if read_one(key, force=force, model=model, log=log):
                ok += 1
            else:
                fail += 1
        except Exception as e:
            log(f'  [出错] {e}')
            fail += 1
    log(f'\n完成：成功 {ok}，失败/跳过 {fail}')
    return ok, fail


def si_many(keys, force=False, log=print):
    """给「已有正文精读 + 有 SI」的文献批量补 SI 精读，再合并成全文精读。

    原来是三次 subprocess（si_deepread → merge_summary → 回写），
    错在哪只拿得到一坨 stdout。现在是三次函数调用。返回 (成功, 失败)。
    """
    role.require_prod('批量 SI 精读（调用付费 API）', force=force)
    log(f'批量补 SI 精读：{len(keys)} 篇\n')
    ok = fail = 0
    for i, key in enumerate(keys, 1):
        log(f'[{i}/{len(keys)}] {key}')
        try:
            with jobs.track(key, STEP_SI, producer=_si.PRODUCER,
                            prompt_ver=_si.PROMPT_VER):
                si_html = _si.read_si(key, log=log)
        except Exception as e:
            log(f'  SI精读失败: {str(e)[:200]}')
            fail += 1
            continue
        if not si_html:
            log('  这篇没有 SI 附件，跳过')
            continue
        log('  SI精读完成')
        try:
            _merge.merge(key, log=log)
            ok += 1
        except Exception as e:
            log(f'  合并失败: {e}')
            fail += 1
    log(f'\n完成：成功 {ok}，失败 {fail}')
    return ok, fail


# ───────────────────────── 用 pro 重跑 ─────────────────────────

def rerun_candidates():
    """能重跑的文献 = 解析结果还在的（不用再调 MineRU）。返回 [(key, 标题)]。"""
    out = []
    for key in paths.all_keys():
        if not os.path.exists(paths.layout(key)):
            continue
        title = key
        if os.path.exists(paths.meta(key)):
            try:
                title = json.load(open(paths.meta(key), encoding='utf-8')).get('title') or key
            except Exception:
                pass
        out.append((key, title))
    return out


def rerun_with_pro(key, title='', force=False, log=print):
    """用 pro 重跑正文精读（更准，适合重要文献）。旧版先备份。

    日常精读用 flash（输出长，省钱）；这里用 pro 重跑你想细品的那几篇。
    **解析结果直接复用**，所以这一步只花一次 LLM 的钱。
    """
    role.require_prod('用 pro 重跑精读（调用付费 API）', force=force)
    key = paths.check_key(key)
    out_html = paths.summary(key)
    if os.path.exists(out_html):
        shutil.copy2(out_html, out_html + '.bak')    # 留的是「上一版」
        log('  [备份] 旧版 → summary.html.bak')
    log(f'用 {PRO_MODEL} 重跑：{(title or key)[:50]}')
    with jobs.track(key, STEP_MAIN, producer=main_text.PRODUCER,
                    model=PRO_MODEL, prompt_ver=main_text.PROMPT_VER):
        main_text.read_main(paths.parsed_dir(key), out_html, provider=PROVIDER,
                            model=PRO_MODEL, key=get_key('DEEPSEEK_KEY'), log=log,
                            paper_key=key)
    log(f'\n完成，结果已更新：{out_html}')
    log('（想看旧版：同目录下的 summary.html.bak）')
    return out_html
