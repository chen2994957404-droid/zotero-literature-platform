---
name: curate
description: 库房维护：自动打标签、附件改名、清重复、定时同步。什么时候用：用户说「库里好像有重复的」「附件名乱了」「标签太乱」「同步一下」；体检报告说缺 meta.json、或精读线找不到正文 PDF
---

<!-- 本文件由 host/codegen/skills.py 生成，**别手改**。改源：tools/curate/SKILL.md + tools/curate/tool.toml -->

> **动手之前先看这三行**（取自 `tools/curate/tool.toml`）：
> **会花钱** · **有副作用**：写Zotero（标签/改名/删除条目）、写 data/curated/<key>/meta.json · **只能在运行端（主力机）跑**
> MCP 暴露方式：`prompt`（**由人在客户端点，模型不能自己发起**）
> 命令行：`python -m tools.curate`

# curate —— 库房维护

## 什么时候用我

- 用户说「库里好像有重复的」「附件名乱了」「标签太乱」「同步一下」
- 体检报告说缺 meta.json、或精读线找不到正文 PDF

## 怎么用

我是 **prompt**，而且是**最危险的一个**：会改用户真实的 Zotero 库。

```
python -m tools.curate junk        # 先列清单
python -m tools.curate junk --删除  # 用户看过清单、明确说删，才跑这条
```

**永远先跑预览、把清单原样给用户看、等他说删哪些改哪些。**
`junk` / `rename` / `tags` 不带参数就是预览，用这个性质。

## 什么时候**别**用我

- **只是想看看库里有什么** → `library_search` / `library_tags`（只读，免费）
- **用户没提出要清理** → 别主动跑。发现问题就报告给他，让他决定
- **要删的是「产物」不是「条目」**（比如想更新精读附件）→ 走 `deepread` 的回写，
  **绝不要用删除**：删除动作会进 Zotero 同步链，导致反复弹冲突框（踩坑 #28）
- **在编程端** → 跑不通，机器角色守卫会拦

## 边界

- `sync` 会顺带跑全库作业（向量化 + 粗层抽取），耗时长
- `autotag`（自动打标签）**已于 2026-07-25 弃用**（用户认为多余），别推荐它
- `rename` 要一份全库 JSON 作数据源，不是随手就能跑的
