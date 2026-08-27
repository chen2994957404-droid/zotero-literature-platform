# -*- coding: utf-8 -*-
"""vectordb 自测：向量库适配层能不能存、能不能检索、返回的形状对不对。
用法: python adapters/vectordb/selftest.py

**全程用临时目录里的假向量**，不碰用户真实的向量库，也不联网。
重点验「返回形状」—— 这一层存在的理由就是把 Chroma 那套
「每个字段套一层 list」的返回拆平，换库时只有这里要重写。
"""
import os
import shutil
import sys
import tempfile

from adapters import vectordb
from core import errors


def _vec(*xs):
    return list(xs) + [0.0] * (4 - len(xs))


def main():
    ok = total = 0
    tmp = tempfile.mkdtemp(prefix='vdb_selftest_')
    try:
        try:
            store = vectordb.open_store(path=os.path.join(tmp, 'db'), name='selftest_coll')
        except errors.ServiceUnavailable as e:
            print(f'  [SKIP] 打不开向量库（chromadb 没装？）: {e}')
            return 0

        total += 1
        if store.count() == 0:
            print('  [PASS] 新建的库是空的'); ok += 1
        else:
            print(f'  [FAIL] 新建的库不空: {store.count()}')

        total += 1
        n = store.add(['a', 'b'], ['聚硼硅氧烷', '完全无关'],
                      [{'key': 'AAAAAAAA', 'title': '论文A'},
                       {'key': 'BBBBBBBB', 'title': '论文B'}],
                      [_vec(1, 0, 0), _vec(0, 0, 1)])
        if n == 2 and store.count() == 2:
            print('  [PASS] 入库 2 条'); ok += 1
        else:
            print(f'  [FAIL] 入库异常: 返回{n}、count={store.count()}')

        total += 1
        try:
            store.add(['x', 'y'], ['只有一条'], [{}], [_vec(1)])
            print('  [FAIL] 四个列表不等长竟然没报错（会静默入错数据）')
        except errors.BadInputError:
            print('  [PASS] 四个列表不等长被挡住'); ok += 1

        total += 1
        hits = store.query(_vec(1, 0, 0), n=2)
        shape_ok = (hits and isinstance(hits, list)
                    and set(hits[0]) == {'id', 'doc', 'meta', 'distance', 'sim'})
        if shape_ok:
            print('  [PASS] 检索返回拆平的结果（没有 Chroma 那层 [0]）'); ok += 1
        else:
            print(f'  [FAIL] 返回形状不对: {hits[:1]}')

        total += 1
        if hits and hits[0]['id'] == 'a' and hits[0]['meta'].get('key') == 'AAAAAAAA':
            print('  [PASS] 最像的排在最前，元数据带回来了'); ok += 1
        else:
            print(f'  [FAIL] 排序或元数据不对: {hits[:1]}')

        total += 1
        sims = [h['sim'] for h in hits]
        if sims and sims == sorted(sims, reverse=True) and 0.0 <= sims[-1] <= 1.0:
            print(f'  [PASS] sim 是「越大越像」且落在 0~1: {sims}'); ok += 1
        else:
            print(f'  [FAIL] sim 语义不对: {sims}')

        total += 1
        if store.existing_keys() == {'AAAAAAAA', 'BBBBBBBB'}:
            print('  [PASS] 能列出已入库的 key（增量向量化靠它）'); ok += 1
        else:
            print(f'  [FAIL] existing_keys 不对: {store.existing_keys()}')

        total += 1
        again = vectordb.open_store(path=os.path.join(tmp, 'db'),
                                    name='selftest_coll', rebuild=True)
        if again.count() == 0:
            print('  [PASS] rebuild 清空了旧数据'); ok += 1
        else:
            print(f'  [FAIL] rebuild 没清空: {again.count()}')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f'  {ok}/{total} 通过')
    return 0 if ok == total else 1


if __name__ == '__main__':
    sys.exit(main())
