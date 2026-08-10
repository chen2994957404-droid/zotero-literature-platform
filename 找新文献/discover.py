# -*- coding: utf-8 -*-
"""找文献（闭环版）：搜全球 → 对照我的库 → 按「跟我多相关」排序 → 一键入库触发精读。

**和普通文献搜索的区别**：外部检索谁都能调；本工具的价值在于它知道
**你已经有什么、读过什么、在做什么方向**，所以能回答那个真正要紧的问题 ——
不是「有哪些文献」，而是「哪几篇值得我现在就读」。

排序刻意让「与我的方向相关」压过「被引数」：
一篇 300 次引用的通用综述，往往不如一篇 5 次引用但正好做你那个体系的论文。

**默认会把你的问题拆成 5 个互补的检索式再搜**，因为单一检索式是「搜不全」的
根本原因 —— 材料领域同一个东西有太多叫法（polyborosiloxane / PBS /
borosiloxane elastomer / shear stiffening gel / silly putty…），
只搜一个词必然漏掉用别的词写的那批。

用法:
  python 找新文献/discover.py "polyborosiloxane dynamic bond"
  python 找新文献/discover.py "我的材料回弹太差怎么解决" --解决问题
  python 找新文献/discover.py "shear stiffening gel" 30 --since 2020
  python 找新文献/discover.py "..." --扩展 8      拆更多检索式（更全，更慢更费）
  python 找新文献/discover.py "..." --单查询      只用原话搜（快，但会漏）
  python 找新文献/discover.py "..." --all         同时显示库里已有的
  python 找新文献/discover.py "..." --openalex    改用免费的 OpenAlex（不需要密钥）

两种模式：
  默认（系统调研）求**全** —— 术语变体、同义词、上位/下位概念
  --解决问题        求**准** —— 机理、方法、性能指标、应用场景等不同角度

看完想收哪篇：python 找新文献/import_by_doi.py <DOI>
入库后在 Zotero 打「待处理」标签即自动精读。
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
from modules.lib_match import match_many, rank
from modules import sciverse


def fetch_one(query, limit, year_from, use_openalex, prefer):
    """单个检索式取候选。优先 Sciverse（覆盖广），没密钥或指定时走 OpenAlex（免费）。"""
    if not use_openalex and sciverse.available():
        r = sciverse.search_papers(query, limit=limit, year_from=year_from, prefer=prefer)
        return r['items'], r['total'], 'Sciverse（4.55 亿条）'
    from modules.paper_discovery import search as oa_search
    out = []
    for it in oa_search(query, limit=limit):
        out.append({'title': it.get('title') or '', 'doi': it.get('doi') or '',
                    'year': it.get('year'), 'venue': it.get('venue') or '',
                    'citations': it.get('cited') or 0, 'abstract': it.get('abstract') or '',
                    'is_oa': it.get('is_oa'), 'oa_url': ''})
    return out, len(out), 'OpenAlex（免费）'


def _key(it):
    """合并去重用的标识：优先 DOI，没有就用归一标题。"""
    doi = (it.get('doi') or '').lower().strip()
    if doi:
        return 'doi:' + doi
    return 'ti:' + re.sub(r'[^a-z0-9]', '', (it.get('title') or '').lower())[:110]


def fetch_multi(queries, limit, year_from, use_openalex, prefer):
    """多个检索式分别检索后合并去重，并统计每一式的**新增贡献**。

    「新增贡献」是判断检索是否饱和的直接依据：
    如果最后几个检索式都只带来一两篇新的，说明这个方向基本被覆盖到了；
    如果每一式都带来大量新文献，说明还远没搜够 —— 这正面回答「全不全面」。
    """
    merged, seen, contrib, source, total_hint = [], set(), [], '', 0
    per = max(8, limit // max(1, len(queries)) + 6)   # 每式多取一些，合并后再截断
    for q in queries:
        try:
            items, total, source = fetch_one(q, per, year_from, use_openalex, prefer)
        except Exception as e:
            contrib.append((q, 0, 0, f'失败: {str(e)[:40]}'))
            continue
        total_hint = max(total_hint, total)
        new = 0
        for it in items:
            k = _key(it)
            if k in seen:
                continue
            seen.add(k)
            merged.append(it)
            new += 1
        contrib.append((q, len(items), new, ''))
    return merged, total_hint, source, contrib


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    flags = [a for a in sys.argv[1:] if a.startswith('--')]
    if not args:
        print(__doc__)
        return
    query = args[0]
    limit = int(args[1]) if len(args) > 1 and args[1].isdigit() else 25
    year_from = None
    if '--since' in sys.argv:
        i = sys.argv.index('--since')
        if i + 1 < len(sys.argv):
            year_from = sys.argv[i + 1]
    prefer = ('citations' if '--cited' in flags else
              'fresh' if '--fresh' in flags else
              'impact' if '--impact' in flags else 'relevance')
    show_all = '--all' in flags

    # 查询扩展：单一检索式是「搜不全」的根本原因（材料领域同一个东西有多种叫法）
    n_q = 1 if '--单查询' in flags else int(
        next((sys.argv[i + 1] for i, a in enumerate(sys.argv)
              if a == '--扩展' and i + 1 < len(sys.argv) and sys.argv[i + 1].isdigit()), 5))
    mode = 'problem' if '--解决问题' in flags else 'survey'
    queries = [query]
    if n_q > 1:
        print(f'正在把问题拆成 {n_q} 个互补的检索式（{"解决问题" if mode == "problem" else "系统调研"}模式）…')
        try:
            from modules.query_expand import expand
            queries = expand(query, mode=mode, n=n_q)
        except Exception as e:
            print(f'（扩展失败，退回单查询：{str(e)[:50]}）')
            queries = [query]
        for i, q in enumerate(queries, 1):
            print(f'  {i}. {q}')
        print()

    try:
        items, total, source, contrib = fetch_multi(
            queries, limit, year_from, '--openalex' in flags, prefer)
    except Exception as e:
        print(f'检索失败：{e}')
        return
    if not items:
        print('没有检索到结果，换个说法试试。')
        return

    print(f'来源 {source}，合并去重后 {len(items)} 篇')
    if len(queries) > 1:
        print('\n各检索式的新增贡献（判断搜得够不够）：')
        for q, got, new, err in contrib:
            if err:
                print(f'  {q[:52]:<54} {err}')
            else:
                print(f'  {q[:52]:<54} 取{got:3d} 新增{new:3d}')
        tail = [c[2] for c in contrib[-2:] if not c[3]]
        if tail and sum(tail) <= 2:
            print('  ↳ 最后两式几乎没带来新文献，**这个方向基本搜到底了**')
        elif tail and sum(tail) >= len(items) * 0.4:
            print('  ↳ 后面的检索式还在大量带新文献，**可能还没搜全**，可加 --扩展 8 再试')
    print('\n正在与你的库对照…（首次会稍慢，要把摘要向量化）')

    ms = match_many(items)
    rows = rank(items, ms)

    n_have = sum(1 for m in ms if m['status'] in ('have', 'likely'))
    shown = [r for r in rows if show_all or r[1]['status'] == 'new']

    print('\n' + '=' * 84)
    print(f'库里已有 {n_have} 篇 · 新文献 {len(items) - n_have} 篇'
          + ('' if show_all else '（下面只列新的，加 --all 可看全部）'))
    print('=' * 84)

    for i, (p, m, score) in enumerate(shown, 1):
        tag = {'have': '【已有】', 'likely': '【疑似已有】', 'new': ''}[m['status']]
        rel = m['relevance']
        bar = '█' * int((rel or 0) * 10) if rel is not None else '?'
        yr = p.get('year') or '????'
        print(f'{i:2d}. {tag}[{yr}] 相关度 {rel if rel is not None else "?"} {bar:<10} '
              f'被引{p.get("citations", 0)}')
        print(f'    {(p.get("title") or "")[:76]}')
        meta = []
        if p.get('venue'):
            meta.append(p['venue'][:38])
        if p.get('doi'):
            meta.append(f'DOI:{p["doi"]}')
        if p.get('is_oa'):
            meta.append('开放获取')
        if meta:
            print(f'    {" · ".join(meta)}')
        if m.get('nearest') and m['status'] == 'new' and (rel or 0) >= 0.7:
            print(f'    ↳ 与你库中《{m["nearest"]["title"]}》最接近')
        print()

    # 把这次结果存下来，供 collect.py 按编号挑选 —— 用户不必手抄 DOI
    import json
    stash = os.path.join(ROOT, 'workflow_data', '_last_search.json')
    try:
        with open(stash, 'w', encoding='utf-8') as f:
            json.dump({'query': query, 'time': __import__('time').strftime('%Y-%m-%d %H:%M'),
                       'items': [{'n': i, 'title': p.get('title'), 'doi': p.get('doi'),
                                  'year': p.get('year'), 'citations': p.get('citations'),
                                  'relevance': m.get('relevance'), 'status': m.get('status')}
                                 for i, (p, m, s) in enumerate(shown, 1)]},
                      f, ensure_ascii=False, indent=1)
    except Exception:
        pass

    print('=' * 84)
    print('相关度 = 这篇跟你库里已有内容的接近程度（不是质量分，是"离你多近"）。')
    print()
    print('决定收哪几篇（按上面的编号，不用抄 DOI）：')
    print('  python 找新文献/collect.py 1,3,5-7          只收进库，先不精读')
    print('  python 找新文献/collect.py 1,3 --精读        收进库并立刻精读')
    print('  python 找新文献/collect.py --看              再看一遍刚才的列表')


if __name__ == '__main__':
    main()
