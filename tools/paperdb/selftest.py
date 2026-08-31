# -*- coding: utf-8 -*-
"""paperdb 自测：不碰真实数据、不调任何服务，验建库 / 筛选 / 只读约束。"""
import io, json, os, sys, tempfile
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
from shared.kernel import paths
from shared.domain import schema
from tools import paperdb

RECS = [
    {'key': 'AAAA0001', 'title': 'A boron elastomer', 'doc_type': 'research',
     'si_used': True, 'material_system': 'polyborosiloxane PBS',
     'dynamic_bond_type': 'boroxine B-O-B', 'synthesis_conditions': '150 °C, 2 h',
     'key_properties': ['tensile strength: 12 MPa', 'Mn: 3.2×10^4 g/mol']},
    {'key': 'BBBB0002', 'title': 'A weak gel', 'doc_type': 'research',
     'source': 'coarse', 'synthesis_conditions': 'N/A',
     'key_properties': ['tensile strength: 0.5 MPa']},
    {'key': 'CCCC0003', 'title': 'Recent advances in gels', 'doc_type': 'review'},
]


def main():
    ok = total = 0
    with tempfile.TemporaryDirectory() as d:
        real_struct, real_db = paths.STRUCTURED, paperdb.db_path
        paths.STRUCTURED = os.path.join(d, 'structured')
        os.makedirs(paths.STRUCTURED)
        paperdb.db_path = lambda: os.path.join(d, 'papers.db')
        paperdb.close()
        try:
            for r in RECS:
                json.dump(r, io.open(os.path.join(paths.STRUCTURED, r['key'] + '.json'),
                                     'w', encoding='utf-8'), ensure_ascii=False)

            total += 1
            n_paper, n_prop = paperdb.rebuild(log=lambda *a: None)
            if (n_paper, n_prop) == (3, 3):
                print('  [PASS] 建库：3 篇、3 条性能数值'); ok += 1
            else:
                print(f'  [FAIL] 建库计数不对：{n_paper} 篇 {n_prop} 条')

            total += 1
            hit = paperdb.find(prop='tensile', min_value=10)
            if [r['key'] for r in hit] == ['AAAA0001']:
                print('  [PASS] 性能能比大小（拉伸强度 > 10 MPa 只剩一篇）'); ok += 1
            else:
                print(f'  [FAIL] 数值筛选不对：{[r["key"] for r in hit]}')

            total += 1
            hit = paperdb.find(text='boron')
            if [r['key'] for r in hit] == ['AAAA0001']:
                print('  [PASS] 全字段关键词筛（含硼的）'); ok += 1
            else:
                print(f'  [FAIL] 关键词筛不对：{[r["key"] for r in hit]}')

            total += 1
            hit = paperdb.find(field='synthesis_conditions')
            if [r['key'] for r in hit] == ['AAAA0001']:
                print('  [PASS] 「这个字段真有值」把 N/A 挡在外面'); ok += 1
            else:
                print(f'  [FAIL] 有值筛不对：{[r["key"] for r in hit]}')

            total += 1
            rows = {r['key']: r for r in paperdb.query('SELECT key, tier, is_review FROM papers')}
            if (rows['AAAA0001']['tier'] == schema.TIER_FINE_SI
                    and rows['BBBB0002']['tier'] == schema.TIER_COARSE
                    and rows['CCCC0003']['is_review'] == 1):
                print('  [PASS] 来源档次与综述标记一起进库'); ok += 1
            else:
                print(f'  [FAIL] 档次/综述标记不对：{rows}')

            total += 1
            try:
                paperdb.query('DELETE FROM papers')
                print('  [FAIL] 居然让写语句跑了')
            except ValueError:
                print('  [PASS] 只读：写语句被拒（真相在 JSON，不在库里）'); ok += 1

            total += 1
            # 库是索引不是真相：删掉能原样重建
            paperdb.close()
            os.remove(os.path.join(d, 'papers.db'))
            again = paperdb.rebuild(log=lambda *a: None)
            if again == (3, 3):
                print('  [PASS] 删库可原样重建（真相是 structured/*.json）'); ok += 1
            else:
                print(f'  [FAIL] 重建结果不一致：{again}')
        finally:
            paperdb.close()
            paths.STRUCTURED, paperdb.db_path = real_struct, real_db

    print(f'\n{ok}/{total} 通过')
    sys.exit(0 if ok == total else 1)


if __name__ == '__main__':
    main()
