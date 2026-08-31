# -*- coding: utf-8 -*-
"""deepread · 批量与回写：一批 key → 精读，以及把产物送回 Zotero。

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

| 函数 | 干什么 | 花钱 | 写 Zotero |
|---|---|---|---|
| `read_many(keys, force)`     | 批量正文精读（复用已有解析） | 是 | 否 |
| `si_many(keys)`              | 批量补 SI → 合并 → 回写 → 升级标签 | 是 | 是 |
| `rerun_candidates()`         | 哪些篇可以用 pro 重跑（解析还在） | 否 | 否 |
| `rerun_with_pro(key, title)` | 用 pro 重跑一篇正文精读 | 是 | 否 |
| `upload_many(keys)`          | 批量回写 summary 附件 + 「已精读」标签 | 否 | 是 |
| `upload_one(key, html)`      | 回写一篇（复用附件条目，不删不新建） | 否 | 是 |
| `refresh_local_file(key)`    | 只把新版铺进本地 storage，不动条目 | 否 | 否 |

**花钱的和写 Zotero 的一律在函数体里先过 `role.require_prod`**（见 code-redlines）。
"""
import json
import os
import shutil

from shared.adapters import zotero_client as zotero
from shared.kernel import jobs, paths, role
from shared.kernel.config import get_key, get_model
from tools.deepread import main_text, merge as _merge, si as _si, tags as _tags
from tools.deepread import STEP_MAIN, STEP_SI

PROVIDER = 'deepseek'
PRO_MODEL = 'deepseek-v4-pro'      # 想细品的那几篇才用它（贵约 3 倍）
DONE_TAG = '已精读'                # 只回写附件、不走状态机时打的兼容标签


def _model():
    """精读输出重 → 默认 flash 省钱；可在控制面板切换。"""
    return get_model('DEEPREAD_MODEL')


# ───────────────────────── 回写 Zotero ─────────────────────────

def _storage_filename(att_key):
    """Zotero 记录的附件文件名。取不到就用 summary.html。

    按它写，用户点开附件才不会「找不到文件」（si_batch 的老教训）。
    """
    try:
        info = zotero.zget(f'/users/{zotero.USER_ID}/items/{att_key}')
        return info['data'].get('filename') or 'summary.html'
    except Exception:
        return 'summary.html'


def _put_local(att_key, src):
    """把产物铺进 Zotero 本地 storage —— 用户点开即最新。"""
    d = os.path.join(zotero.STORAGE_DIR, att_key)
    os.makedirs(d, exist_ok=True)
    shutil.copy(src, os.path.join(d, _storage_filename(att_key)))
    return d


def upload_one(key, html=None, force=False, log=print):
    """把某篇的精读回写成 Zotero 的 summary 附件，返回附件 key。

    ⚠ **有就复用附件条目、只换文件内容**。原来的「先删旧附件、再传新的」
    正是踩坑 #28 的根因：删除动作会进 Zotero 同步链，于是每篇都弹一次
    「冲突解决」框。watcher 早改成复用，批量脚本却留着旧写法 ——
    同一个 bug 的两份实现，这也是把回写收进一处的直接理由。
    """
    role.require_prod('回写精读附件到 Zotero', force=force)
    src = html or paths.summary(key)
    if not os.path.exists(src):
        log('  [跳过] 无 summary.html')
        return None
    att_key = zotero.find_child_attachment(key, 'summary')
    if not att_key:
        att_key = zotero.upload_attachment(key, src, 'summary')
    _put_local(att_key, src)
    return att_key


def add_done_tag(key, log=print):
    """给文献加「已精读」标签（保留原有标签）。"""
    try:
        item = zotero.get_item(key)
        tags = item['data'].get('tags', [])
        if any(t.get('tag') == DONE_TAG for t in tags):
            return
        tags.append({'tag': DONE_TAG})
        zotero.replace_tags(key, tags, action='加「已精读」标签')
    except Exception as e:
        log(f'    (加标签失败: {e})')


def upload_many(keys, force=False, log=print):
    """批量回写精读附件 + 打「已精读」标签。返回成功篇数。"""
    role.require_prod('批量回写精读附件', force=force)
    ok = 0
    for i, key in enumerate(keys, 1):
        log(f'[{i}/{len(keys)}] {key}')
        try:
            if upload_one(key, force=force, log=log):
                add_done_tag(key, log=log)
                log('  [已上传] summary + 标签「已精读」')
                ok += 1
        except Exception as e:
            log(f'  [上传失败] {e}')
    log(f'\n完成：成功 {ok}/{len(keys)}')
    return ok


def refresh_local_file(key):
    """把新版 summary.html 刷进 Zotero 本地 storage，覆盖旧附件文件。

    用途：精读被重跑之后，Zotero 里点开的还是旧文件。

    **只改文件内容、不动条目与版本号** —— 因此不触发同步冲突
    （踩坑 #18：「先删附件再传新的」会把删除动作推进同步链，反复弹冲突框）。
    返回 (是否成功, 说明)。
    """
    src = paths.summary(key)
    if not os.path.exists(src):
        return False, '本地无 summary.html'
    att_key = zotero.find_child_attachment(key, 'summary')
    if not att_key:
        return False, 'Zotero 里没有 summary 附件（需走 watcher 首次上传）'
    _put_local(att_key, src)
    return True, f'-> storage/{att_key}/ ({round(os.path.getsize(src) / 1024)} KB)'


# ───────────────────────── 批量精读 ─────────────────────────

def read_one(key, force=False, model=None, log=print):
    """精读一篇正文，**复用已有的 MineRU 解析结果**（不再消耗解析额度）。

    没有解析结果就跳过 —— 要连解析一起做请走 `deepread.run(key)`。
    """
    key = paths.check_key(key)
    model = model or _model()
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
                    model=model, prompt_ver=main_text.PROMPT_VER):
        main_text.read_main(parsed, out_html, provider=PROVIDER, model=model,
                            key=get_key('DEEPSEEK_KEY'), log=log)
    log(f'  [完成] summary.html {round(os.path.getsize(out_html) / 1024)} KB')
    return True


def read_many(keys, force=False, log=print):
    """批量正文精读。返回 (成功, 失败/跳过)。"""
    role.require_prod('批量精读（调用付费 API）', force=force)
    model = _model()
    log(f'批量精读 {len(keys)} 篇（模型 {model}{"，强制重跑" if force else ""}）\n')
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
    """给「已有正文精读 + 有 SI」的文献批量补 SI 精读，合并后回写并升级标签。

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
        merged = _merge.merge(key, log=log)
        final = merged or si_html
        try:
            att_key = upload_one(key, final, force=force, log=log)
            if att_key:
                log('  附件已更新')
            _tags.set_state_tag(key, _tags.TAG_FULL, log=log)
            ok += 1
        except Exception as e:
            log(f'  回写失败: {e}')
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
                            model=PRO_MODEL, key=get_key('DEEPSEEK_KEY'), log=log)
    log(f'\n完成，结果已更新：{out_html}')
    log('（想看旧版：同目录下的 summary.html.bak）')
    return out_html


# ───────────────────────── 命令行（R4 窗改由 cli.py 调用） ─────────────────────────

def main():
    """批量精读的命令行入口。

      python -m tools.deepread.batch KEY1 KEY2          批量正文精读
      python -m tools.deepread.batch --file keys.txt    从文件读 key（每行一个）
      python -m tools.deepread.batch --force ...        强制重跑（旧版自动备份 .bak）
      python -m tools.deepread.batch --si KEY1 KEY2     批量补 SI 精读 + 合并 + 回写
      python -m tools.deepread.batch --upload KEY1      批量回写 summary 附件 + 打标签
      python -m tools.deepread.batch --refresh KEY1     只把新版铺进本地 storage
      python -m tools.deepread.batch --rerun-pro        列出可用 pro 重跑的文献
      python -m tools.deepread.batch --rerun-pro 3      用 pro 重跑第 3 篇
    """
    import sys
    from shared.kernel.cli import flag, opt, positionals
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

    force = flag('--force')
    fp = opt('--file')
    keys = ([l.strip() for l in open(fp, encoding='utf-8') if l.strip()]
            if fp else positionals())

    if flag('--rerun-pro'):
        rows = rerun_candidates()
        idx_raw = opt('--rerun-pro') or (keys[0] if keys else '')
        if not idx_raw:
            print('=== 可用 pro 重跑的已解析文献 ===\n')
            for i, (_key, title) in enumerate(rows, 1):
                print(f'  [{i}] {title[:55]}')
            if not rows:
                print('  （没有已解析的文献 —— 先让 watcher 精读一篇）')
            print('\n用法：python -m tools.deepread.batch --rerun-pro 2')
            return
        try:
            idx = int(idx_raw) - 1
        except ValueError:
            raise SystemExit('序号要是数字')
        if not 0 <= idx < len(rows):
            raise SystemExit('序号超范围')
        rerun_with_pro(rows[idx][0], rows[idx][1], force=force)
        return

    if flag('--refresh'):
        for key in keys:
            good, msg = refresh_local_file(key)
            print(f'  {key}: {"OK " if good else "跳过 "}{msg}')
        return
    if not keys:
        print(main.__doc__)
        raise SystemExit(2)
    if flag('--upload'):
        upload_many(keys, force=force)
    elif flag('--si'):
        si_many(keys, force=force)
    else:
        read_many(keys, force=force)


if __name__ == '__main__':
    main()
