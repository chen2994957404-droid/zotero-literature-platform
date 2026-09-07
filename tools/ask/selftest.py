# -*- coding: utf-8 -*-
"""ask 自测：不调 LLM、不连 Ollama、不碰真实数据，验问答与向量化的编排骨架。"""
import io
import json
import os
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.kernel import paths
from tools import ask
from tools.ask import vectorize


class FakeStore(object):
    """够用的假向量库：只记住加进来的东西，query 按加入顺序返回。"""

    def __init__(self, hits=None):
        self.ids, self.docs, self.metas = [], [], []
        self._hits = hits or []

    def query(self, vec, n=5):
        return self._hits[:n]

    def add(self, ids, docs, metas, embs):
        self.ids += list(ids)
        self.docs += list(docs)
        self.metas += list(metas)

    def count(self):
        return len(self.ids)

    def existing_keys(self):
        return set(i.split('_')[0] for i in self.ids)

    def all_metadatas(self):
        # 真 Store 有这个方法，假的也必须有 —— SI 的判重就走它。
        # 假件跟真件接口漂移时，坏的不是自测而是「自测过了但真跑会崩」。
        return list(self.metas)


def main():
    ok = total = 0

    # ── 问答：检索到片段 → 片段进提示词 → 来源被带出来 ──────────────
    hits = [{'doc': 'PBS shows shear stiffening above 100 s-1.',
             'meta': {'title': 'Shear stiffening of polyborosiloxane', 'doi': '10.1/x'}},
            {'doc': 'B-O bonds are dynamic.',
             'meta': {'title': 'Dynamic boron chemistry', 'doi': ''}}]
    seen = {}

    def fake_llm(system, user):
        seen['user'] = user          # 记下提示词，下面要验「片段真的喂进去了」
        return '答案正文'

    real = (ask._store, ask.embed, ask.answer_with)
    ask._store = lambda: FakeStore(hits)
    ask.embed = lambda t: [0.1, 0.2]
    ask.answer_with = fake_llm
    try:
        total += 1
        r = ask.ask_answer('剪切增稠是怎么回事')
        if r['chunks'] == 2 and r['answer'] == '答案正文':
            print('  [PASS] 检索 2 块 → 作答'); ok += 1
        else:
            print(f'  [FAIL] 问答结果异常：{r}')

        total += 1
        if 'shear stiffening above' in seen.get('user', '') \
                and '剪切增稠是怎么回事' in seen.get('user', ''):
            print('  [PASS] 片段和问题都进了提示词（答案必须有据可依）'); ok += 1
        else:
            print('  [FAIL] 提示词里没带上检索到的片段')

        total += 1
        titles = [s['title'] for s in r['sources']]
        if titles == ['Shear stiffening of polyborosiloxane', 'Dynamic boron chemistry']:
            print('  [PASS] 来源随答案一起返回（可追溯）'); ok += 1
        else:
            print(f'  [FAIL] 来源不对：{titles}')

        total += 1
        ask._store = lambda: FakeStore([])
        r2 = ask.ask_answer('库里没有的东西')
        if r2['chunks'] == 0 and r2['answer'] == '':
            print('  [PASS] 检索不到时不硬答（chunks=0，交给调用方提示）'); ok += 1
        else:
            print(f'  [FAIL] 空库时的行为不对：{r2}')
    finally:
        ask._store, ask.embed, ask.answer_with = real

    # ── 向量化：精层读 full.md，已入库的跳过 ───────────────────────
    with tempfile.TemporaryDirectory() as d:
        real_cur, real_raw = paths.CURATED, paths.RAW
        real_emb, real_coll = vectorize.embed, vectorize.get_collection
        paths.CURATED = os.path.join(d, 'curated')
        paths.RAW = os.path.join(d, 'raw')
        store = FakeStore()
        vectorize.embed = lambda texts: [[0.0] for _ in texts]
        vectorize.get_collection = lambda rebuild=False: store
        try:
            key = 'ZZZZ0003'
            paths.parsed_dir(key, create=True)
            io.open(paths.fulltext(key), 'w', encoding='utf-8').write(
                '# Title\n\n' + ('polyborosiloxane elastomer. ' * 200))
            io.open(paths.meta(key), 'w', encoding='utf-8').write(
                json.dumps({'title': 'A PBS paper', 'DOI': '10.1/y'}))

            total += 1
            n_paper, n_chunk = vectorize.deep_all(log=lambda *a: None)
            if n_paper == 1 and n_chunk == store.count() > 0:
                print(f'  [PASS] 精层向量化一篇 → {n_chunk} 块入库'); ok += 1
            else:
                print(f'  [FAIL] 精层向量化异常：{n_paper} 篇 {n_chunk} 块')

            total += 1
            if store.metas and store.metas[0]['title'] == 'A PBS paper' \
                    and store.metas[0]['doi'] == '10.1/y':
                print('  [PASS] 元数据跟着块走（答完能说出来自哪篇）'); ok += 1
            else:
                print(f'  [FAIL] 块的元数据不对：{store.metas[:1]}')

            total += 1
            again, _ = vectorize.deep_all(log=lambda *a: None)
            if again == 0:
                print('  [PASS] 已入库的不重做（增量）'); ok += 1
            else:
                print(f'  [FAIL] 重复处理了 {again} 篇')

            # ── SI：必须能补进**已经有正文**的库 ──────────────────────
            # 这是本条最关键的设计点：库里绝大多数文献正文早就入过库了，
            # 若拿 existing_keys()（「这篇有没有块」）判重，SI 一篇都补不进去。
            paths.si_parsed_dir(key, create=True)
            io.open(paths.si_fulltext(key), 'w', encoding='utf-8').write(
                '# SI\n\n' + ('supplementary synthesis detail. ' * 200))

            total += 1
            before = store.count()
            n_si, c_si = vectorize.deep_all(log=lambda *a: None)
            si_metas = [m for m in store.metas if m.get('source') == 'si']
            if n_si == 1 and si_metas and store.count() > before:
                print(f'  [PASS] SI 补进了已有正文的库 → {len(si_metas)} 块'); ok += 1
            else:
                print(f'  [FAIL] SI 没补进去：新增 {n_si} 篇、SI 块 {len(si_metas)} 个'
                      f'（正文早已入库时最容易在这里被误判为「已处理」）')

            total += 1
            si_ids = [i for i in store.ids if '_SI' in i]
            main_metas = [m for m in store.metas if m.get('source') == 'main']
            if len(si_ids) == len(si_metas) > 0 and main_metas                     and not (set(si_ids) & set(i for i in store.ids if '_SI' not in i)):
                print('  [PASS] SI 的 id 与正文不撞、source 标记正确'); ok += 1
            else:
                print(f'  [FAIL] id/标记有问题：SI id {len(si_ids)} 个、'
                      f'SI 块 {len(si_metas)}、正文块 {len(main_metas)}')

            total += 1
            again_si, _ = vectorize.deep_all(log=lambda *a: None)
            if again_si == 0:
                print('  [PASS] SI 也不会重复入库'); ok += 1
            else:
                print(f'  [FAIL] SI 重复处理了 {again_si} 篇')

            total += 1
            n_off, _ = vectorize.deep_all(log=lambda *a: None, with_si=False)
            if n_off == 0:
                print('  [PASS] --no-si 时不碰 SI'); ok += 1
            else:
                print(f'  [FAIL] with_si=False 仍处理了 {n_off} 篇')
        finally:
            vectorize.embed, vectorize.get_collection = real_emb, real_coll
            paths.CURATED, paths.RAW = real_cur, real_raw

    print(f'\n{ok}/{total} 通过')
    sys.exit(0 if ok == total else 1)


if __name__ == '__main__':
    main()
