# -*- coding: utf-8 -*-
"""标签维护。两条线，**其中一条已弃用**。

## 线一：`to_nested()` —— 把 `dim:value` 改成 Zotero 风格的嵌套 `dim/value`

支持中断续跑（已转的会跳过）。
用法: `python -m tools.curate.tags [apply]`；不带 apply = 预览。

## 线二：`autotag()` —— 【已弃用 · 2026-07-25，不要再运行】

用户明确表示自动标签「没什么用还很多余」，已清理全部 690 种分类标签
（`type/ mechanism/ topic/ method/ material/` 前缀，共 1500 次标记）。
Zotero 现在只保留「待处理」「已精读」这类工作流标签。

**如需重新启用，先与用户确认。** 备份见 `data/backup/zotero_tags_backup.json`。
留着它不是为了跑，是因为「怎么给材料文献分维度」这套提示词还有参考价值。
"""
import sys
import time

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.adapters import zotero_client as zotero
from shared.adapters.llm_client import chat_json as _chat_json
from shared.kernel import role
from shared.kernel.cli import flag, opt, pos
from shared.kernel import prompts
from shared.kernel.config import get_key, get_model

DIMS = ('topic', 'material', 'mechanism', 'method', 'type')
ARTICLE_TYPES = ('journalArticle', 'conferencePaper', 'thesis', 'bookSection')

AUTOTAG_SYS = prompts.load('curate', 'autotag@v1')


def fetch_tops():
    """取全部顶层条目（分页）。走适配层，红线 #5。"""
    tops = []
    start = 0
    while True:
        d = zotero.search_items(limit=100, start=start)
        if not d:
            break
        tops += d
        start += 100
        if len(d) < 100:
            break
    return tops


# ── 线一：dim:value → dim/value ──────────────────────────────────────
def nested_of(tags):
    """一条文献的标签列表 → 改造后的标签列表；没有可改的返回 None。"""
    out, need = [], False
    for t in tags:
        tag = t.get('tag', '')
        for dim in DIMS:
            if tag.startswith(dim + ':'):
                out.append({'tag': dim + '/' + tag[len(dim) + 1:]})
                need = True
                break
        else:
            out.append(t)
    return out if need else None


def to_nested(apply=False, forced=False):
    """把库里所有 `dim:value` 标签改成 `dim/value`。apply=False 时只预览。"""
    todo = []
    for x in fetch_tops():
        newtags = nested_of(x['data'].get('tags', []))
        if newtags:
            todo.append((x['key'], newtags))

    print(f'需要转换的文献: {len(todo)} 篇')
    if not apply:
        for k, tags in todo[:3]:
            print(k, '->', [t['tag'] for t in tags if '/' in t['tag']][:5])
        print('\n(预览。加 apply 执行)')
        return todo

    ok = fail = 0
    for i, (key, newtags) in enumerate(todo):
        try:
            zotero.replace_tags(key, newtags, action='标签改成嵌套写法',
                                force=forced, log=print)
            ok += 1
        except Exception as e:
            print(f'  [写回失败] {key}: {e}')
            fail += 1      # 单篇失败不中断整批
        if (i + 1) % 20 == 0:
            print(f'  {i+1}/{len(todo)} 成功{ok} 失败{fail}')
        time.sleep(0.3)
    print(f'\n完成：成功 {ok}，失败 {fail}')
    return todo


# ── 线二：自动打标签（已弃用）────────────────────────────────────────
def tag_llm(title, abstract):
    """标题+摘要 → 各维度标签（JSON）。打标签用 flash：快、便宜、JSON 稳。"""
    return _chat_json(AUTOTAG_SYS, f'标题：{title}\n\n摘要：{abstract[:2000]}',
                      provider='deepseek', model=get_model('AUTOTAG_MODEL'),
                      key=get_key('DEEPSEEK_KEY'))


def to_tags(result):
    """LLM 的 JSON 结果 → `dim:value` 标签列表。"""
    tags = []
    for dim in ('topic', 'material', 'mechanism', 'method'):
        for v in result.get(dim, []):
            if v and isinstance(v, str):
                tags.append(f'{dim}:{v.strip().lower()}')
    t = result.get('type')
    if t:
        tags.append(f'type:{t.strip().lower()}')
    return tags


def autotag(apply=False, limit=None, forced=False):
    """【已弃用】给有摘要的文献自动打分类标签。**跑之前先和用户确认。**"""
    arts = [x for x in fetch_tops()
            if x['data'].get('itemType') in ARTICLE_TYPES and x['data'].get('abstractNote')]
    if apply:
        # 增量：跳过已有维度标签的（避免重复处理，支持中断续跑）
        arts = [x for x in arts if not any(':' in t.get('tag', '') for t in x['data'].get('tags', []))]
    if limit:
        arts = arts[:limit]

    print(f'处理 {len(arts)} 篇（{"写入" if apply else "试打"}）\n')
    for x in arts:
        d = x['data']
        title, abstract = d.get('title', ''), d.get('abstractNote', '')
        try:
            tags = to_tags(tag_llm(title, abstract))
        except Exception as e:
            print(f'✗ {title[:35]} — 解析失败: {e}')
            continue
        print(f'《{title[:45]}》')
        print('  ' + '  '.join(tags))
        print()
        if not apply:
            continue
        # 保留原有非维度标签，加上新标签（去重）
        old = [t for t in d.get('tags', []) if ':' not in t.get('tag', '')]
        seen, uniq = set(), []
        for t in old + [{'tag': t} for t in tags]:
            if t['tag'] not in seen:
                seen.add(t['tag'])
                uniq.append(t)
        try:
            zotero.replace_tags(x['key'], uniq, action='自动打标签', force=forced, log=print)
        except Exception as e:
            print(f'  [写回失败] {x["key"]}: {e}')
        time.sleep(0.3)
    print('完成')


def main():
    """命令行入口：默认走「标签改嵌套写法」；`--autotag` 才碰那条已弃用的线。"""
    # 机器角色守卫：这件事只允许在运行端（主力机）做，见 docs/两台机器的分工.md
    forced = flag('--force')
    if flag('--autotag'):
        print('⚠ 自动打标签已于 2026-07-25 弃用（用户认为多余）。'
              '确要执行请加 --我确认；先读本文件顶部说明。')
        if not flag('--我确认'):
            return
        role.require_prod('自动打标签（写回 Zotero）', force=forced)
        _limit = opt('--limit')
        autotag(apply=flag('--apply'), limit=int(_limit) if _limit else None, forced=forced)
        return
    apply = pos(0) == 'apply'
    if apply:
        role.require_prod('标签改造（写回 Zotero）', force=forced)
    to_nested(apply=apply, forced=forced)


if __name__ == '__main__':
    main()
