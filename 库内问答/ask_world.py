# -*- coding: utf-8 -*-
"""问全世界：向全球文献提一个科学问题，拿到**带原文出处**的中文回答。

与同目录 ask.py 的分工（两者互补，不重叠）：
  ask.py       → 问**我读过的**文献（本地向量库，38 篇精读，答得深）
  ask_world.py → 问**全世界**的文献（Sciverse，3000 万篇全文，答得广）

流程：Sciverse 取回可引用的原文片段 → DeepSeek 结合片段用中文作答 → 附出处。
**答案只允许基于取回的片段**，不许模型自由发挥 —— 这是「可追溯」的前提。

用法:
  python 库内问答/ask_world.py "聚硼硅氧烷的剪切硬化机理是什么"
  python 库内问答/ask_world.py "B-N配位键如何提升自修复效率" --since 2020 --top 10
"""
import sys, os, io

# 用 reconfigure 而非替换 sys.stdout：后者会让原对象被回收、底层缓冲被关闭，
# 表现为程序跑到一半 print 抛「I/O operation on closed file」（踩坑 #37）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from modules.sciverse import ask_evidence, available, SciverseError
from modules.llm_client import chat
from modules.config import get_key, get_model

SYS = ('你是科研文献助手。请**只根据下面提供的文献片段**回答用户问题，用中文，准确专业。'
       '每个关键论断后面用 [1] [2] 这样的编号标出依据来自哪条片段。'
       '如果片段里没有足够信息，就直说「提供的文献片段中没有找到相关证据」，'
       '**不要用你自己的知识补充**——本工具的价值在于可追溯。'
       '回答末尾不用列来源，程序会另外附上。')


MIN_SCORE = 0.60      # 相关度低于此值的片段基本是噪声，实测 0.35~0.5 的全是跑题的


def to_english_query(q):
    """把中文问题转成英文检索式。

    **为什么必须转（实测教训）**：Sciverse 会按提问语言偏向同语言文献。
    中文提问「聚硼硅氧烷的剪切硬化机理」召回的是硼硅玻璃辐照、炉渣、LTCC 陶瓷 ——
    含「硼」但方向完全无关；同一问题用英文问，5 条全部命中、相关度 0.97。
    材料领域的高质量文献绝大多数是英文，检索必须用英文。
    这也符合项目语言约定：**机器用的中间数据用英文，给用户看的用中文。**
    """
    if not any('一' <= c <= '鿿' for c in q):
        return q          # 本来就是英文，不折腾
    try:
        en = chat('You translate scientific questions into concise English search queries. '
                  'Output ONLY the query, no quotes, no explanation.',
                  q, provider='deepseek', model=get_model('ASK_MODEL'),
                  key=get_key('DEEPSEEK_KEY'), temperature=0.1,
                  max_tokens=200, thinking=False).strip()
        return en or q
    except Exception:
        return q          # 翻译失败就用原文，不阻断主流程


def ask_world(question, top_k=8, year_from=None, min_score=MIN_SCORE):
    """返回 {'answer':str, 'evidence':list, 'query_used':str}。找不到证据时 answer 为空串。"""
    q_en = to_english_query(question)
    ev = ask_evidence(q_en, top_k=max(top_k, 12), year_from=year_from)
    # 按相关度过滤：宁可少给几条，也不要拿跑题片段污染答案
    ev = [e for e in ev if e['score'] >= min_score][:top_k]
    if not ev:
        return {'answer': '', 'evidence': [], 'query_used': q_en}
    ctx = ''
    for i, e in enumerate(ev, 1):
        page = f"，第{e['page']}页" if e.get('page') is not None else ''
        ctx += (f"\n【片段{i}·《{e['title'][:60]}》{e['year'] or ''}{page}】\n"
                f"{e['chunk'][:1200]}\n")
    answer = chat(SYS, f'文献片段：\n{ctx}\n\n用户问题：{question}',
                  provider='deepseek', model=get_model('ASK_MODEL'),
                  key=get_key('DEEPSEEK_KEY'), temperature=0.3,
                  max_tokens=8000, thinking=False)
    return {'answer': answer, 'evidence': ev, 'query_used': q_en}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not args:
        print(__doc__)
        return
    question = ' '.join(args)
    top_k = 8
    if '--top' in sys.argv:
        i = sys.argv.index('--top')
        if i + 1 < len(sys.argv) and sys.argv[i + 1].isdigit():
            top_k = int(sys.argv[i + 1])
    year_from = None
    if '--since' in sys.argv:
        i = sys.argv.index('--since')
        if i + 1 < len(sys.argv):
            year_from = sys.argv[i + 1]

    if not available():
        print('未配置 SCIVERSE_KEY。请双击「控制面板.bat」，在 Sciverse 一栏填写。')
        print('（想问自己库里的文献，用：python 库内问答/ask.py "问题"）')
        return

    print(f'正在向全球文献检索证据……（问题：{question}）\n')
    try:
        r = ask_world(question, top_k=top_k, year_from=year_from)
    except SciverseError as e:
        print(f'检索失败：{e}')
        return

    if r.get('query_used') and r['query_used'] != question:
        print(f'（检索用英文式：{r["query_used"]}）\n')
    if not r['evidence']:
        print('没有检索到足够相关的证据（已过滤掉低相关度的噪声片段）。')
        print('可以换个说法、放宽年份限制，或用 --top 调大候选数。')
        return

    print('=' * 78)
    print(r['answer'])
    print('=' * 78)
    print('\n📚 证据来源（可直接引用）：')
    for i, e in enumerate(r['evidence'], 1):
        page = f"  第{e['page']}页" if e.get('page') is not None else ''
        print(f"  [{i}] 《{e['title'][:64]}》")
        print(f"      {e['year'] or '????'} · {e['venue'][:34]} · 被引{e['citations']}"
              f"{page} · 相关度{e['score']}")
    print()


if __name__ == '__main__':
    main()
