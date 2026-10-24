# -*- coding: utf-8 -*-
"""精读的命令行入口（只解析参数，逻辑在 tools/deepread 与 batch.py）。日常单篇精读在文献库应用里点。

⚠ **key 要写在选项前面**（`shared.kernel.cli.positionals()` 到第一个 `--` 就停）。
   写成 `--si KEY` 的话，key 根本不会被看见 —— 你会得到一份用法说明和退出码 2，
   而那看起来像「参数写错了」，不像「顺序反了」。
   这份文档自己就写错过（2026-09-03 实测撞上），所以下面每一条都按正确顺序重排。

用法:
    python -m tools.deepread KEY1 KEY2          批量正文精读
    python -m tools.deepread KEY1 --force       强制重跑（旧版自动备份 .bak）
    python -m tools.deepread KEY1 KEY2 --si     批量补 SI 精读 + 合并
    python -m tools.deepread --file keys.txt    从文件读 key（每行一个）
    python -m tools.deepread --rerun-pro        列出可用 pro 重跑的文献
    python -m tools.deepread --rerun-pro 3      用 pro 重跑第 3 篇

审稿（精读写完由另一个模型对着原文逐句判：编造 / 曲解 / 漏重点；正常精读里自动跑，这条是手动用）：
    python -m tools.deepread KEY1 --审稿                     审一篇已有的精读，报告写到 curated/<KEY>/review.json 并打印
⚠ 除 --rerun-pro 列清单外，每一条都**花钱**（付费大模型 + MineRU 额度），
   并且会把结果写回 Zotero。只允许在主力机上跑（role.require_prod 会拦）。

常驻服务另有自己的入口，不走这里：
    python -m host.watcher.service       盯着 Zotero 的「待处理」标签自动精读
    python -m host.watcher.watchdog      看门狗（守着它别死）
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass

from shared.kernel.cli import flag, opt, positionals, wants_help
from tools.deepread.batch import read_many, rerun_candidates, rerun_with_pro, si_many



def main():
    """用法见模块文档字符串（`python -m tools.deepread --help`）。"""
    if wants_help():
        print(__doc__)
        return 0
    force = flag('--force')
    fp = opt('--file')
    keys = ([l.strip() for l in open(fp, encoding='utf-8') if l.strip()]
            if fp else positionals())

    if flag('--审稿'):
        import io as _io, json as _json
        from shared.kernel import role, paths, catalog
        from shared.adapters.llm_client import chat_json
        from tools.deepread import review as RV
        local = flag('--本地')
        if not local:
            role.require_prod('审稿（调用付费大模型逐句判一篇精读）', force=force)
        for key in keys:
            html_p, md_p = paths.summary(key), paths.fulltext(key)
            if not (os.path.exists(html_p) and os.path.exists(md_p)):
                print(key, '缺精读或全文，跳过'); continue
            content = RV.html_to_content(_io.open(html_p, encoding='utf-8').read())
            md = _io.open(md_p, encoding='utf-8').read()
            sp = paths.si_fulltext(key)
            si = _io.open(sp, encoding='utf-8').read() if os.path.exists(sp) else ''
            m = catalog.read_meta(key)
            rep = RV.review(content, md, si, chat_json, {'title': m.get('title', ''), 'journal': m.get('journal', '')}, local=local)
            rep['needs_human'] = not rep['passed']
            _json.dump(rep, _io.open(paths.review_report(key), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
            print(RV.to_markdown(rep, key))
        return 0

    if flag('--rerun-pro'):
        rows = rerun_candidates()
        idx_raw = opt('--rerun-pro') or (keys[0] if keys else '')
        if not idx_raw:
            print('=== 可用 pro 重跑的已解析文献 ===\n')
            for i, (_key, title) in enumerate(rows, 1):
                print(f'  [{i}] {title[:55]}')
            if not rows:
                print('  （没有已解析的文献 —— 先让 watcher 精读一篇）')
            print('\n用法：python -m tools.deepread --rerun-pro 2')
            return
        try:
            idx = int(idx_raw) - 1
        except ValueError:
            raise SystemExit('序号要是数字')
        if not 0 <= idx < len(rows):
            raise SystemExit('序号超范围')
        rerun_with_pro(rows[idx][0], rows[idx][1], force=force)
        return

    if not keys:
        print(__doc__)
        raise SystemExit(2)
    if flag('--si'):
        si_many(keys, force=force)
    else:
        read_many(keys, force=force)


if __name__ == '__main__':
    main()
