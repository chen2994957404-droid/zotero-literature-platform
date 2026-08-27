# -*- coding: utf-8 -*-
"""query_expand · 检索式扩展基础件（公理：一个研究问题 → 多个互补的英文检索式）

**为什么需要这块**：单一查询是「检索不全面」的根本原因，跟检索引擎好不好无关。
材料领域同一个东西有太多叫法 ——
polyborosiloxane / PBS / boron-siloxane / borosiloxane elastomer /
silly putty / shear stiffening gel / dilatant compound …
只搜其中一个词，就必然漏掉用别的词写的那批文献。

前沿的文献检索 Agent（PaperPilot、PaSa、SPAR 等）都把「查询分解与扩展」
作为第一步：先把研究问题拆成领域概念、术语变体、时间约束，
再生成适配各数据库的查询串 —— **而不是拿用户原话直接去搜**。

两种模式（对应两类真实需求，策略不同）：
  survey  系统调研 → 求**全**：术语变体、同义词、上位/下位概念、相关体系
  problem 解决问题 → 求**准**：机理角度、方法角度、性能指标角度、应用场景角度

对外接口：
  - to_english(q)          → 单个英文检索式（中文问题转英文）
  - expand(q, mode, n)     → n 个互补的英文检索式（含原式）

依赖：modules.llm_client、modules.config。LLM 不可用时降级为只返回原式。
"""
import os, sys, re

from modules.llm_client import chat
from modules.config import get_key, get_model


def looks_chinese(text):
    return any('一' <= c <= '鿿' for c in (text or ''))


_SYS_EN = ('You translate scientific questions into concise English search queries. '
           'Output ONLY the query itself: no quotes, no punctuation at the end, '
           'no explanation, no numbering.')

_SYS_SURVEY = (
    'You are a research librarian helping a materials scientist do an EXHAUSTIVE literature survey.\n'
    'Given a research topic, produce {n} DIFFERENT English search queries that together '
    'MAXIMISE COVERAGE of the topic. Cover:\n'
    '  - the standard term AND its common synonyms/abbreviations/alternative spellings\n'
    '  - broader (parent) and narrower (child) concepts\n'
    '  - the same material/phenomenon as named in adjacent communities\n'
    '  - the underlying mechanism, if it has its own name\n'
    'Each query should be 3-8 words, suitable for an academic search engine.\n'
    'Output ONLY the queries, one per line, no numbering, no explanation.')

_SYS_PROBLEM = (
    'You are a research librarian helping a materials scientist SOLVE A CONCRETE PROBLEM.\n'
    'Given the problem, produce {n} DIFFERENT English search queries that approach it '
    'from COMPLEMENTARY ANGLES:\n'
    '  - the phenomenon / failure mode itself\n'
    '  - the underlying mechanism that causes it\n'
    '  - known strategies or methods used to fix it\n'
    '  - the measurable property or metric involved\n'
    '  - the material system where it is most studied\n'
    'Each query should be 3-8 words, suitable for an academic search engine.\n'
    'Output ONLY the queries, one per line, no numbering, no explanation.')


def _llm(system, user, max_tokens=400):
    return chat(system, user, provider='deepseek', model=get_model('ASK_MODEL'),
                key=get_key('DEEPSEEK_KEY'), temperature=0.4,
                max_tokens=max_tokens, thinking=False)


def to_english(q, context=None):
    """中文问题 → 英文检索式。已经是英文就原样返回。

    为什么必须转：Sciverse 等按 query 语言做亲和加权，中文问会召回中文文献，
    而材料领域的高质量文献绝大多数是英文（踩坑 #35 实测）。

    context 同 expand()：给出领域，避免缩写被翻错。
    """
    if not looks_chinese(q):
        return q
    try:
        user = q
        if context:
            sample = '\n'.join(f'- {t}' for t in list(context)[:5])
            user = (f"Field context (papers from this researcher's library):\n{sample}\n\n"
                    f"Translate this query into an English search query IN THAT FIELD:\n{q}")
        return _llm(_SYS_EN, user, 200).replace('"', '').strip() or q
    except Exception:
        return q          # 翻译失败不阻断主流程


def _clean_lines(text, n):
    out = []
    for ln in (text or '').split('\n'):
        ln = ln.strip()
        ln = re.sub(r'^[\-\*\d\.\)\s]+', '', ln)
        # 引号可能出现在任意位置（LLM 偶尔吐出 `PBS" lead-free solder` 这种），
        # 只 strip 两端不够，直接全删
        ln = ln.replace('"', '').replace('“', '').replace('”', '').strip()
        if not ln or len(ln) < 4 or looks_chinese(ln):
            continue
        if ln.lower() not in (x.lower() for x in out):
            out.append(ln)
        if len(out) >= n:
            break
    return out


def expand(query, mode='survey', n=5, context=None):
    """把一个研究问题扩展成 n 个互补的英文检索式。

    context: 用户领域的样例文献标题列表。**缩写歧义必须靠它消解**（踩坑 #39）。

    返回 list[str]，**第一个永远是原式（转英文后）** —— 保证不会因为扩展跑偏
    而丢掉用户本来想搜的东西。LLM 不可用时只返回这一个，功能降级但不失效。
    """
    base = to_english(query, context=context)
    queries = [base]
    if n <= 1:
        return queries
    sysmsg = (_SYS_SURVEY if mode == 'survey' else _SYS_PROBLEM).format(n=n - 1)
    user = query
    if context:
        # 把用户库里的真实文献标题作为领域上下文 ——
        # 这是本平台独有的信息，API 层和通用工具都拿不到
        sample = '\n'.join(f'- {t}' for t in list(context)[:6])
        user = (f"This researcher works in the field represented by these papers "
                f"from their own library:\n{sample}\n\n"
                f"Interpret the query IN THAT FIELD (abbreviations must be resolved "
                f"according to this field, not other disciplines).\n\nQuery: {query}")
    try:
        extra = _clean_lines(_llm(sysmsg, user), n - 1)
    except Exception:
        extra = []
    for e in extra:
        if e.lower() != base.lower():
            queries.append(e)
    return queries[:n]
