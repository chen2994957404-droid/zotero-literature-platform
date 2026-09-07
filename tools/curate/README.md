# tools/curate · 库房维护

**一句话**：让 Zotero 库和平台产物保持干净、一致、能自愈。

## 怎么用

```
（定时增量同步搬去了 `python -m host.autosync`，每小时由任务计划自己跑）
python -m tools.curate junk                    列出没有正文 PDF 的垃圾条目（**只列，不删**）
python -m tools.curate junk --删除             按上一步的清单删
python -m tools.curate junk --删除 --只删A     只删确认是重复残留的那组
python -m tools.curate rename <全库json路径>    附件改名，不带 apply = 只预览
python -m tools.curate rename <全库json> apply  真改
python -m tools.curate backfill                给缺 meta.json 的补元数据
python -m tools.curate tags                    标签改嵌套写法（不带 apply = 预览）
```

## 五件事分别是什么

| 动作 | 干什么 | 为什么要 |
|---|---|---|
| ~~`sync`~~ | R7 窗搬去 `host/autosync/` | 新文献自动进问答库 |
| `junk` | 找出无正文 PDF 的条目并分组（重复残留 / 只有一份）| 库里塞满空壳会拖垮检索 |
| `rename` | 附件名统一成 Full Text PDF / SI / Snapshot | **精读线靠附件名认正文和 SI** |
| `backfill` | 给 library 里缺 meta.json 的补元数据 | 问答要知道这篇是什么 |
| `tags` | `dim:value` 标签改成 `dim/value` 嵌套写法 | Zotero 里能折叠成树 |

## 一条铁律：先预览，后执行

`junk` / `rename` / `tags` 都是**不带参数就只列清单**。
清单先给人看，确认了再执行。删条目走适配层的删除原语，
它只用于用户明确要删的条目，**绝不用于「更新产物」**（踩坑 #28）。

## 只在主力机上跑

每个写操作开头都有机器角色守卫，编程端会被拦住。

## 期刊分级（2026-09-07 加）

```
python -m tools.curate journals          # 全库刷一遍（走 OpenAlex，免费、不写 Zotero）
python -m tools.curate journals --list    # 只看上次结果，不联网
```

产出 `data/serving/journals.json`：每篇发在哪本刊、那本刊什么档次
（`顶刊 / 一流 / 常规 / 一般 / 慎用`，按近两年篇均被引分档）。
`tools/paperdb` 读它，于是 `--find X --journal 顶刊` 这类筛法成立。

**你的名单压过指标**：`data/serving/journal_overrides.json` 想写什么写什么
（按出版商或按刊名，大小写不敏感、包含匹配）。默认只有一条 ——
你说过的「不看不引 MDPI」。改完再跑一次 `journals` 就生效。

指标来自 OpenAlex（免费）。中科院分区和 JCR 都要订阅，SCImago 的下载口有
Cloudflare 挡着（实测 curl 只拿得到验证页），所以现成的免费源就这一个。
