# -*- coding: utf-8 -*-
"""精读的命令行入口（只解析参数，逻辑在 tools/deepread 与 batch.py）。

⚠ **key 要写在选项前面**（`shared.kernel.cli.positionals()` 到第一个 `--` 就停）。
   写成 `--si KEY` 的话，key 根本不会被看见 —— 你会得到一份用法说明和退出码 2，
   而那看起来像「参数写错了」，不像「顺序反了」。
   这份文档自己就写错过（2026-09-03 实测撞上），所以下面每一条都按正确顺序重排。

用法:
    python -m tools.deepread KEY1 KEY2          批量正文精读
    python -m tools.deepread KEY1 --force       强制重跑（旧版自动备份 .bak）
    python -m tools.deepread KEY1 KEY2 --si     批量补 SI 精读 + 合并 + 回写
    python -m tools.deepread KEY1 --upload      批量回写 summary 附件 + 打标签
    python -m tools.deepread KEY1 --refresh     只把新版铺进本地 storage
    python -m tools.deepread --file keys.txt    从文件读 key（每行一个）
    python -m tools.deepread --rerun-pro        列出可用 pro 重跑的文献
    python -m tools.deepread --rerun-pro 3      用 pro 重跑第 3 篇

金标评测（对着高分子学人的范文自动打分，产物在 data/state/golden_eval/<tag>/）：
    python -m tools.deepread --金标评测 --tag v3_local --篇数 10 --本地        本地模型跑 10 篇并打分
    python -m tools.deepread --金标评测 --tag v3_cloud --篇数 10               走路由表（花钱）
    python -m tools.deepread --金标评测 --tag v3_local --篇数 10 --对照         同一批老精读（v2）也打分做对照
    python -m tools.deepread --金标重算 v3_local                                改了评分口径只重算
    python -m tools.deepread --建术语表                                        从范文重建领域术语表（缩写→中文，零成本）
    --同批 v3_local 用上一轮那一批（候选池在长，同 seed 抽出来会变；跨轮对比必须同批）
    --seed 1 固定抽样；--model qwen3.5:4b 指定模型；--篇数 0 = 全部

审稿（精读写完由另一个模型对着原文逐句判：编造 / 曲解 / 漏重点；正常精读里自动跑，这两条是手动用）：
    python -m tools.deepread KEY1 --审稿                     审一篇已有的精读，报告写到 curated/<KEY>/review.json 并打印
    python -m tools.deepread --审稿校准 --篇数 10 --tag v1   拿范文校准审稿：干净范文的误报率 + 故意塞错的查全率
    --本地 走本机 Ollama（免费）；--seed 固定抽样

单元拆解研究（把人写的范文拆成七类最小信息单元，量「基本单元长什么样」，产物 data/state/unit_study/<tag>/）：
    python -m tools.deepread --单元拆解 --篇数 20 --本地 --tag u1
    python -m tools.deepread --原文单元 --篇数 10 --本地 --tag u1     第 2 步：从英文原文拆九类单元
    python -m tools.deepread --单元覆盖 u1                             范文单元有几成能在原文单元里找到（bge-m3 配对）

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
from tools.deepread.batch import (read_many, refresh_local_file, rerun_candidates,
                                  rerun_with_pro, si_many, upload_many)



def main():
    """用法见模块文档字符串（`python -m tools.deepread --help`）。"""
    if wants_help():
        print(__doc__)
        return 0
    force = flag('--force')
    fp = opt('--file')
    keys = ([l.strip() for l in open(fp, encoding='utf-8') if l.strip()]
            if fp else positionals())

    if flag('--建术语表'):
        from tools.deepread import glossary_build
        return glossary_build.main()

    if flag('--原文单元'):
        from shared.kernel import role
        from shared.adapters.llm_client import chat_json
        from tools.deepread.evals import units_src as US, golden as GE
        local = flag('--本地')
        if not local:
            role.require_prod('原文单元拆解（调用付费大模型拆十几篇原文）', force=force)
        n, seed = int(opt('--篇数') or 10), int(opt('--seed') or 1)
        keys = keys or (GE.candidates() if n == 0 else GE.sample(n, seed))
        done = US.run(keys, chat_json, tag=opt('--tag') or 'u1', local=local)
        print('\n拆完 %d 篇' % len(done))
        return 0

    if flag('--单元覆盖'):
        from tools.deepread.evals import units_src as US
        per_type, path = US.coverage(opt('--单元覆盖') or opt('--tag') or 'u1')
        print('\n' + '\n'.join('%s %s' % (t, b['rate']) for t, b in per_type.items() if b['n']) + '\n报告 → ' + path)
        return 0

    if flag('--单元重定位'):
        from tools.deepread.evals import units as U
        summary, path = U.relocate(opt('--单元重定位') or opt('--tag') or 'u1')
        print('报告 →', path)
        return 0

    if flag('--单元拆解'):
        from shared.kernel import role, paths
        from shared.adapters.llm_client import chat_json
        from tools.deepread.evals import units as U, golden as GE
        local = flag('--本地')
        if not local:
            role.require_prod('单元拆解研究（调用付费大模型拆二十篇范文）', force=force)
        n, seed = int(opt('--篇数') or 20), int(opt('--seed') or 1)
        keys = keys or (GE.candidates() if n == 0 else GE.sample(n, seed))
        tag = opt('--tag') or 'u1'
        summary, path = U.run(keys, chat_json, tag=tag, local=local)
        print('\n%d 篇 · 单元合计 %d\n报告 → %s' % (len(summary['per_paper']),
              sum(r['total'] for r in summary['per_paper']), path))
        return 0

    if flag('--审稿校准'):
        from shared.kernel import role, paths
        from shared.adapters.llm_client import chat_json
        from tools.deepread import review as RV
        from tools.deepread.evals import golden as GE
        local = flag('--本地')
        if not local:
            role.require_prod('审稿校准（调用付费大模型逐句判十几篇范文）', force=force)
        n, seed = int(opt('--篇数') or 10), int(opt('--seed') or 1)
        keys = keys or (GE.candidates() if n == 0 else GE.sample(n, seed))
        tag = opt('--tag') or ('v1_local' if local else 'v1')
        agg = RV.calibrate(keys, chat_json, tag=tag, local=local, out_dir=paths.review_calib_dir(tag))
        print('\n%d 篇 · 干净范文误报率 %.1f%% · 塞错查全率 %.0f%%\n报告 → %s' % (
            agg['n'], agg['fp_rate'] * 100, agg['recall'] * 100, os.path.join(paths.review_calib_dir(tag), 'report.md')))
        return 0

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

    if flag('--金标评测') or flag('--金标重算'):
        from shared.kernel import role
        from tools.deepread.evals import golden as GE
        if flag('--金标重算'):
            agg, path = GE.rescore(opt('--金标重算') or opt('--tag') or 'v3')
            print('重算完成 →', path, chr(10), agg)
            return 0
        local = flag('--本地')
        if not local:
            role.require_prod('金标评测（调用付费大模型跑十几篇精读）', force=force)
        n = int(opt('--篇数') or 10)
        seed = int(opt('--seed') or 1)
        same = opt('--同批')
        keys = keys or (GE.keys_of(same) if same else (GE.candidates() if n == 0 else GE.sample(n, seed)))
        if same and not keys:
            print('找不到上一轮', same, '的名单'); return 2
        tag = opt('--tag') or ('v3_local' if local else 'v3_cloud')
        if flag('--对照'):
            agg0, p0 = GE.baseline(keys)
            print('对照（老精读 v2）：', agg0, chr(10) + ' →', p0)
        agg, path = GE.run(tag, keys, local=local, model=opt('--model') or None)
        print(chr(10) + '本轮汇总：', agg, chr(10) + '报告 →', path)
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

    if flag('--refresh'):
        for key in keys:
            good, msg = refresh_local_file(key)
            print(f'  {key}: {"OK " if good else "跳过 "}{msg}')
        return
    if not keys:
        print(__doc__)
        raise SystemExit(2)
    if flag('--upload'):
        upload_many(keys, force=force)
    elif flag('--si'):
        si_many(keys, force=force)
    else:
        read_many(keys, force=force)


if __name__ == '__main__':
    main()
