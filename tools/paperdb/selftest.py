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
    # v2 记录：一篇里两个配方，数字各自挂到样品上，并带条件与出处
    {'key': 'DDDD0004', 'title': 'A PBS series', 'doc_type': 'research',
     'schema_ver': 2, 'si_used': True, 'material_system': 'polyborosiloxane PBS',
     'samples': [
         {'sample_id': 'PBS-1', 'composition': 'PDMS:boric acid = 10:1',
          'preparation': '150 °C, 2 h', 'dynamic_bond': 'boroxine', 'role': 'best'},
         {'sample_id': 'PBS-2', 'composition': 'PDMS:boric acid = 20:1',
          'preparation': '150 °C, 2 h', 'dynamic_bond': 'boroxine', 'role': 'series'}],
     'measurements': [
         {'sample_id': 'PBS-1', 'name': 'ultimate tensile stress',
          'value_text': '18 MPa', 'condition': '100 mm/min, 25 °C',
          'location': 'Table 2', 'section': 'main'},
         {'sample_id': 'PBS-2', 'name': 'tensile strength', 'value_text': '4 MPa',
          'location': 'Fig. 3b', 'section': 'si'}]},
]


def main():
    ok = total = 0
    with tempfile.TemporaryDirectory() as d:
        real_struct, real_db = paths.STRUCTURED, paperdb.db_path
        real_curated, real_abs = paths.CURATED, paths.ABSTRACTS
        # 方向层目录也要隔离：`_records()` 现在两个目录都读，
        # 漏一个就会把真实数据算进来 —— 在编程端看不出来（那儿没数据），
        # 一到主力机就红。同 #127 的教训：**给读取加了新来源，先看测试隔离了什么。**
        paths.ABSTRACTS = os.path.join(d, 'abstracts')
        paths.STRUCTURED = os.path.join(d, 'structured')
        os.makedirs(paths.STRUCTURED)
        paperdb.db_path = lambda: os.path.join(d, 'papers.db')
        paperdb.close()
        try:
            for r in RECS:
                json.dump(r, io.open(os.path.join(paths.STRUCTURED, r['key'] + '.json'),
                                     'w', encoding='utf-8'), ensure_ascii=False)

            total += 1
            n_paper, n_samp, n_meas = paperdb.rebuild(log=lambda *a: None)
            if (n_paper, n_samp, n_meas) == (4, 5, 5):
                print('  [PASS] 三层一起建：4 篇、5 个样品、5 条数值'); ok += 1
            else:
                print(f'  [FAIL] 建库计数不对：{n_paper} 篇 {n_samp} 样品 {n_meas} 条')

            total += 1
            hit = paperdb.find(prop='tensile', min_value=10)
            if sorted(r['key'] for r in hit) == ['AAAA0001', 'DDDD0004']:
                print('  [PASS] 性能能比大小（拉伸强度 > 10 MPa 的两篇，弱的那篇被挡掉）'); ok += 1
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
            rows = paperdb.samples(key='DDDD0004')
            if ([r['sample_id'] for r in rows] == ['PBS-1', 'PBS-2']
                    and rows[0]['composition'].startswith('PDMS')):
                print('  [PASS] 样品层：一篇里的两个配方各占一行'); ok += 1
            else:
                print(f'  [FAIL] 样品层不对：{rows}')

            total += 1
            rows = paperdb.measurements(prop='tensile strength', min_value=10)
            keys = sorted({(r['key'], r['sample_id']) for r in rows})
            if keys == [('AAAA0001', 'main'), ('DDDD0004', 'PBS-1')]:
                print('  [PASS] 测量层：比大小时分得清是哪个样品的数'); ok += 1
            else:
                print(f'  [FAIL] 测量层筛选不对：{keys}')

            total += 1
            loc = paperdb.measurements(located=True)
            unloc = paperdb.measurements(located=False)
            if ({r['key'] for r in loc} == {'DDDD0004'}
                    and {r['key'] for r in unloc} == {'AAAA0001', 'BBBB0002'}):
                print('  [PASS] 有出处的和还没定位的分得开（待核清单能一句话拉出来）'); ok += 1
            else:
                print(f'  [FAIL] 出处筛选不对：{[r["key"] for r in loc]} / {[r["key"] for r in unloc]}')

            total += 1
            rows = paperdb.measurements(prop='ultimate tensile stress')
            if rows and rows[0]['name'] == 'tensile strength':
                print('  [PASS] 换个叫法也查得到（性能名字先归一再匹配）'); ok += 1
            else:
                print(f'  [FAIL] 名字归一没生效：{rows}')

            total += 1
            prov = {r['tier']: r for r in paperdb.provenance()}
            fine = prov.get(schema.TIER_FINE_SI, {})
            if fine.get('located') == 2 and fine.get('with_condition') == 1:
                print('  [PASS] 体温计：数得出有多少数字能追溯到原文'); ok += 1
            else:
                print(f'  [FAIL] 体温计不对：{prov}')

            total += 1
            n_view = paperdb.query('SELECT COUNT(*) n FROM properties')[0]['n']
            if n_view == 5:
                print('  [PASS] 老名字 properties 还在（视图），老查询照跑'); ok += 1
            else:
                print(f'  [FAIL] 兼容视图不对：{n_view}')

            # ── 曲线：抠下来的点要能进库、能比大小 ──────────────────────
            paths.CURATED = os.path.join(d, 'curated')
            os.makedirs(os.path.join(paths.CURATED, 'DDDD0004'), exist_ok=True)
            json.dump({'3': {'chart_type': 'line', 'confidence': 'medium',
                             'caption': 'Stress-strain curves',
                             'x_axis': {'label': 'Strain', 'unit': '%'},
                             'y_axis': {'label': 'Stress', 'unit': 'MPa'},
                             'series': [{'name': 'PBS-1',
                                         'points': [[0, 0], [100, 8.2], [300, 12.4], [400, 5.0]]}]}},
                      io.open(os.path.join(paths.CURATED, 'DDDD0004', 'curves.json'),
                              'w', encoding='utf-8'), ensure_ascii=False)

            total += 1
            paperdb.close()
            n_p, n_s, n_m = paperdb.rebuild(log=lambda *a: None)
            rows = paperdb.curves(key='DDDD0004')
            if len(rows) == 1 and rows[0]['n_points'] == 4 and rows[0]['y_unit'] == 'MPa':
                print('  [PASS] 曲线进库：一条 series 一行，轴与单位都留着'); ok += 1
            else:
                print(f'  [FAIL] 曲线没进库：{rows}')

            total += 1
            peak = [m for m in paperdb.measurements(key='DDDD0004')
                    if m['method'] == 'curve' and m['name'] == 'stress']
            if peak and peak[0]['value'] == 12.4 and peak[0]['location'] == 'Fig. 3':
                print('  [PASS] 曲线峰值变成能比大小的测量（method=curve，出处到图号）'); ok += 1
            else:
                print(f'  [FAIL] 曲线没派生出测量：{peak}')

            total += 1
            pts = paperdb.curve_points('DDDD0004', 3)
            if pts and pts[0]['points'][2] == [300, 12.4]:
                print('  [PASS] 原始点存住了（要画图或再分析随时取）'); ok += 1
            else:
                print(f'  [FAIL] 原始点取不回来：{pts}')

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
            # 5 条文字里抽的 + 2 条从曲线峰值派生的
            if again == (4, 5, 7):
                print('  [PASS] 删库可原样重建（真相是 JSON 文件，不是库）'); ok += 1
            else:
                print(f'  [FAIL] 重建结果不一致：{again}')
        finally:
            paperdb.close()
            paths.STRUCTURED, paperdb.db_path = real_struct, real_db
            paths.CURATED, paths.ABSTRACTS = real_curated, real_abs

    print(f'\n{ok}/{total} 通过')
    sys.exit(0 if ok == total else 1)


if __name__ == '__main__':
    main()
