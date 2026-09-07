# -*- coding: utf-8 -*-
"""宪法分级守卫 —— 让「每条规矩都要标可不可推翻」这件事不会随时间烂掉。

2026-09-07 立。起因是用户的疑问：
「那些旧宪法是不是相当于在你的思考之上，只要稍微合理你也不会推翻它，
我怕它反而会限制大模型的思维。」

这属实：写进宪法的话会作为用户指令进入每次会话，优先级高于模型自身判断。
解法是给每条规矩标【事实】/【硬约束】/【启发式】，只有前两档不许推翻。

但分级是一次性动作，**没有守卫的话过两个月新加的章节又会变回不带标记的祖训**。
这个文件就是那件事的执行者。它不测功能，只测宪法这份文件的形状。
"""
import os
import io
import re

from shared.kernel import paths

ROOT = paths.ROOT
宪法 = os.path.join(ROOT, 'docs', 'explain', '架构宪法_第一性原理.md')
存档 = os.path.join(ROOT, 'docs', 'explain', '架构宪法_v1_历史存档.md')

# 三档标记。改这里之前先想清楚：档位越多，「不许推翻」的边界就越糊。
标记 = ('【事实】', '【硬约束】', '【启发式】')

# 元章节：讲怎么用这份文件、列待办、给指令的，本身不是规矩，不需要标记。
# 刻意写成白名单而不是「含某关键词就跳过」——让豁免必须被显式添加。
元章节 = ('怎么用这份文件', '已知待推翻项', '给接手 LLM 的最高指令')

_NL = chr(10) + '  '

# 零号判据的唯一源在宪法里，被这对标记圈住；下面两份是抄过去的副本。
摘 = ('<!-- 摘:零号判据 开始', '<!-- 摘:零号判据 结束 -->')
抄 = ('<!-- AUTO:零号判据 开始', '<!-- AUTO:零号判据 结束 -->')
副本 = (os.path.join(ROOT, 'AGENTS.md'),
        os.path.join(ROOT, 'docs', 'howto', 'skills', 'research-first.md'),
        os.path.join(ROOT, '.claude', 'skills', 'research-first', 'SKILL.md'))


def _读(p):
    return io.open(p, encoding='utf-8').read()


def test_每个规矩章节都带分级标记():
    """一级章节（## 一、xxx）必须带三档标记之一，元章节除外。"""
    漏 = []
    for 行 in _读(宪法).splitlines():
        if not 行.startswith('## '):
            continue
        标题 = 行[3:].strip()
        if any(元 in 标题 for 元 in 元章节):
            continue
        if not any(t in 标题 for t in 标记):
            漏.append(标题)
    assert not 漏, (
        '宪法里这些章节没标【事实】/【硬约束】/【启发式】，'
        '读到它的模型会默认「不许推翻」：' + _NL + _NL.join(漏))


def test_三档标记的定义没被删掉():
    """标记的含义表是整套分级的地基，删了标记就变成没人懂的符号。"""
    正文 = _读(宪法)
    # 只要求「定义表里有」，不要求每档都被用上 ——
    # 【事实】那一档现在确实一次没用：项目事实都住在 AGENTS.md，宪法里只放判据。
    # 守卫在这里刻意留松，是因为「逼着凑一条事实进来」比空着更糟。
    缺 = [t for t in 标记 if t not in 正文]
    assert not 缺, '宪法里这几档标记没有定义：' + _NL + _NL.join(缺)


def test_启发式那一档写明了可以推翻():
    """这句话是整次改动的目的本身。它没了，分级就只剩装饰。"""
    正文 = _读(宪法)
    assert re.search(r'【启发式】.{0,80}可以推翻', 正文, re.S), (
        '宪法里找不到「【启发式】…可以推翻」的明文。'
        '没有这句，模型看到标记也只会照办。')


def test_旧宪法存档没有自称生效():
    """两份文件都自称最高纲领时，模型会照着更长的那份执行。"""
    正文 = _读(存档)
    assert '不再生效' in 正文.split('---')[0], (
        '架构宪法_v1_历史存档.md 的抬头没写明「不再生效」，'
        '它会被当成一份 300 行的现行纲领。')


def _抠(文, 起, 止):
    i = 文.find(起)
    if i < 0:
        return None
    i = 文.index('-->', i) + 3
    j = 文.find(止, i)
    return 文[i:j].strip() if j > 0 else None


def test_零号判据只有一个源():
    """三处副本必须与宪法里的源逐字一致 —— 漂移过一次就再也没人知道哪份对。

    2026-09-07 之前它在宪法 / AGENTS.md / research-first skill 各写一份。
    现在源在宪法，其余由 host/codegen/handover.py 抄过去。
    这个测试红了，多半是有人手改了副本 —— 改源，然后跑那个生成器。
    """
    源 = _抠(_读(宪法), *摘)
    assert 源, '宪法里找不到 <!-- 摘:零号判据 --> 圈起来的源'
    漂 = []
    for f in 副本:
        if not os.path.exists(f):
            continue
        本 = _抠(_读(f), *抄)
        if 本 is None:
            漂.append(os.path.relpath(f, ROOT) + '：没有 AUTO:零号判据 区块')
        elif 本 != 源:
            漂.append(os.path.relpath(f, ROOT) + '：内容与宪法里的源不一致')
    assert not 漂, ('零号判据的副本漂了。改源（宪法），再跑 '
                    'python host/codegen/handover.py：' + _NL + _NL.join(漂))
