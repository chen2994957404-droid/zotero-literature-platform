# -*- coding: utf-8 -*-
"""extract 自测：不调 LLM、不碰真实数据，验编排骨架（幂等 / 出表 / 记账）。"""
import io, json, os, sys, tempfile
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
from shared.kernel import jobs, paths
from shared.domain import schema
from tools import extract
from tools.extract import audit

KEY = 'ZZZZ0002'


def main():
    ok = total = 0
    with tempfile.TemporaryDirectory() as d:
        real_cur, real_raw = paths.CURATED, paths.RAW
        real_struct, real_db = paths.STRUCTURED, jobs.db_path
        paths.CURATED = os.path.join(d, 'curated')
        paths.RAW = os.path.join(d, 'raw')
        paths.STRUCTURED = os.path.join(d, 'structured')
        jobs.db_path = lambda: os.path.join(d, 'state.db')
        jobs.close()
        try:
            paths.parsed_dir(KEY, create=True)
            io.open(paths.fulltext(KEY), 'w', encoding='utf-8').write('body text')
            io.open(paths.meta(KEY), 'w', encoding='utf-8').write(
                json.dumps({'title': 'A dynamic elastomer', 'DOI': '10.1/x'}))

            io.open(os.path.join(paths.si_parsed_dir(KEY, create=True), 'full.md'),
                    'w', encoding='utf-8').write('PDMS:boric acid = 10:1, 150 °C 2 h')

            calls, prompts = [], []
            real_llm = extract.llm_json
            extract.llm_json = lambda sysmsg, user: (
                calls.append(1) or prompts.append(user)
                or {'material_system': 'PBS', 'doc_type': 'research'})
            extract.EVAL_ENABLED = False

            total += 1
            rec = extract.run(KEY, log=lambda *a: None)
            if rec and rec['material_system'] == 'PBS' and rec['schema_ver'] == schema.SCHEMA_VER:
                print('  [PASS] 抽一篇 → 落盘带版本号'); ok += 1
            else:
                print(f'  [FAIL] 抽取结果异常：{rec}')

            total += 1
            if prompts and '10:1' in prompts[0] and rec and rec['si_used'] is True:
                print('  [PASS] SI 一起喂给模型（合成条件就在 SI 里）'); ok += 1
            else:
                print('  [FAIL] 抽取没读 SI')

            total += 1
            if extract.si_pending_keys() == []:
                print('  [PASS] 读过 SI 的不再进「该重抽」清单'); ok += 1
            else:
                print(f'  [FAIL] 待重抽清单不对：{extract.si_pending_keys()}')

            total += 1
            old = json.load(io.open(paths.structured(KEY), encoding='utf-8'))
            old.pop('si_used')
            json.dump(old, io.open(paths.structured(KEY), 'w', encoding='utf-8'))
            if extract.si_pending_keys() == [KEY]:
                print('  [PASS] 有 SI 却没读 SI 的自己冒出来（旧记录）'); ok += 1
            else:
                print(f'  [FAIL] 旧记录没被认出来：{extract.si_pending_keys()}')
            json.dump(rec, io.open(paths.structured(KEY), 'w', encoding='utf-8'))

            total += 1
            extract.run(KEY, log=lambda *a: None)
            if len(calls) == 1:
                print('  [PASS] 抽过的不重抽（省 API 费）'); ok += 1
            else:
                print(f'  [FAIL] 重复调用了 {len(calls)} 次')

            total += 1
            if os.path.exists(paths.compare()) and 'A dynamic elastomer' in io.open(
                    paths.compare(), encoding='utf-8').read():
                print('  [PASS] 自动并入横向对比表'); ok += 1
            else:
                print('  [FAIL] 对比表没生成')

            total += 1
            schema.SCHEMA_VER += 1                     # 假装加了字段
            try:
                if extract.stale_keys() == [KEY]:
                    print('  [PASS] schema 升版 → 该重抽的自己冒出来'); ok += 1
                else:
                    print(f'  [FAIL] 待重抽清单不对：{extract.stale_keys()}')
            finally:
                schema.SCHEMA_VER -= 1

            total += 1
            row = jobs.last(KEY, extract.STEP)
            if row and row['status'] == jobs.OK and row['producer'] == extract.PRODUCER:
                print('  [PASS] 记账完整（谁抽的、哪版 schema）'); ok += 1
            else:
                print(f'  [FAIL] 状态库记录不对：{row}')
        finally:
            extract.llm_json = real_llm
            jobs.close()
            paths.CURATED, paths.RAW = real_cur, real_raw
            paths.STRUCTURED, jobs.db_path = real_struct, real_db

    # ── 抽检：编出来的数字要能被挑出来（免费替代每篇都花钱的自检）──────
    total += 1
    rec = {'key': 'AAAA0001', 'title': '测试', 'schema_ver': 3,
           'samples': [{'sample_id': 'PBS-1'}],
           'measurements': [
               {'sample_id': 'PBS-1', 'name': 'tensile strength', 'value_text': '12.4 MPa'},
               {'sample_id': 'PBS-1', 'name': 'toughness', 'value_text': '999 kJ/m^2'},
               {'sample_id': '不存在的样品', 'name': 'modulus', 'value_text': '3.1 MPa'}]}
    real = audit._source_text
    audit._source_text = lambda key: ('The sample PBS-1 reached 12.4 MPa tensile '
                                      'strength and a modulus of 3.1 MPa. ' * 20)
    try:
        r = audit.audit_one(rec)
    finally:
        audit._source_text = real
    if r and r['hit'] == 2 and r['n'] == 3 and any('999' in m for m in r['miss']):
        print('  [PASS] 抽检把原文里找不到的那个数字（999）挑出来了'); ok += 1
    else:
        print(f'  [FAIL] 抽检结果不对：{r}')

    total += 1
    if r and r['orphan'] == ['不存在的样品']:
        print('  [PASS] 挂在不存在样品上的数值也被点名（等于没挂）'); ok += 1
    else:
        print(f'  [FAIL] 没查出孤儿样品：{r and r["orphan"]}')

    # ── 段落级比武的打分：编数字、编样品名，都要能当场判死 ──────────────
    total += 1
    from tools.extract import bench_chunk as B
    chunk = ('The hybrid gel reached a tensile strength of 12.4 MPa and an '
             'elongation at break of 320 %. Testing used a rate of 100 mm/min.')
    samples = ['hybrid gel', 'alginate gel']
    good = {'measurements': [
        {'sample_id': 'hybrid gel', 'name': 'tensile strength', 'value_text': '12.4 MPa'},
        {'sample_id': 'hybrid gel', 'name': 'elongation at break', 'value_text': '320 %'}]}
    s_good = B.score(good, chunk, samples)
    if (s_good['grounded'] == s_good['nums'] == 2 and s_good['sid_ok'] == 2
            and s_good['recall_hit'] >= 1):
        print('  [PASS] 老实作答：数字全接地、样品名合法、召回算得出'); ok += 1
    else:
        print(f'  [FAIL] 老实作答被误判：{s_good}')

    total += 1
    bad = {'measurements': [
        {'sample_id': 'PBS-9（编的）', 'name': 'tensile strength', 'value_text': '99.9 MPa'}]}
    s_bad = B.score(bad, chunk, samples)
    if s_bad['grounded'] == 0 and s_bad['sid_ok'] == 0:
        print('  [PASS] 编的数字与编的样品名，两样都当场判死'); ok += 1
    else:
        print(f'  [FAIL] 没抓住编造：{s_bad}')

    total += 1
    if B.score('不是 JSON', chunk, samples) is None and B.score({'x': 1}, chunk, samples) is None:
        print('  [PASS] 格式崩了就算这次没答（不给它蒙混过关）'); ok += 1
    else:
        print('  [FAIL] 坏格式没被判掉')

    # ── 拆段抽取的脚本校验层：小模型能用的全部前提 ──────────────────
    from tools.extract import chunk_pass as C

    passage = ('The PBS-1 sample showed a tensile strength of 12.4 MPa and an '
               'elongation at break of 480 %. PBS-2 reached 8.1 MPa.')
    names = ['PBS-1', 'PBS-2']

    total += 1
    rows = [{'sample_id': 'PBS-1', 'name': 'tensile strength', 'value_text': '12.4 MPa'},
            {'sample_id': 'PBS-1', 'name': 'tensile strength', 'value_text': '99.9 MPa'}]
    kept, drop = C.validate(rows, passage, names)
    if len(kept) == 1 and drop['编的数字'] == 1:
        print('  [PASS] 数字不在这一段里就丢掉（模型编的那个 99.9 被判了）'); ok += 1
    else:
        print(f'  [FAIL] 编的数字没判掉：留下 {len(kept)} 条，{drop}')

    total += 1
    rows = [{'sample_id': 'PBS-9', 'name': 'tensile strength', 'value_text': '12.4 MPa'}]
    kept, drop = C.validate(rows, passage, names)
    if not kept and drop['编的样品'] == 1:
        print('  [PASS] 样品不在名单里就丢掉（模型没有权力发明样品名）'); ok += 1
    else:
        print(f'  [FAIL] 编的样品没判掉：{kept}')

    total += 1
    rows = [{'sample_id': 'unknown', 'name': 'tensile strength', 'value_text': '12.4 MPa'}]
    kept, _ = C.validate(rows, passage, names)
    if len(kept) == 1 and kept[0]['sample_id'] == 'unknown':
        print('  [PASS] 说不清属于谁时 unknown 是合法答案（比硬猜一个强）'); ok += 1
    else:
        print(f'  [FAIL] unknown 被误判了：{kept}')

    total += 1
    tbl = [{'sample_id': 'PBS-1', 'name': 'tensile strength', 'value': 12.4}]
    rows = [{'sample_id': 'PBS-1', 'name': 'tensile strength', 'value_text': '12.4 MPa'}]
    kept, drop = C.validate(rows, passage, names, table_rows=tbl)
    if not kept and drop['跟表格重了'] == 1:
        print('  [PASS] 跟表格重的丢掉（表格那条带出处，更硬）'); ok += 1
    else:
        print(f'  [FAIL] 没跟表格判重：{kept}')

    total += 1
    rows = [{'sample_id': 'PBS-1', 'name': 'note', 'value_text': 'improved a lot'},
            {'sample_id': 'PBS-2', 'name': 'tensile strength', 'value_text': '8.1 MPa'},
            {'sample_id': 'PBS-2', 'name': 'tensile strength', 'value_text': '8.1 MPa'}]
    kept, drop = C.validate(rows, passage, names)
    if len(C._dedup(kept)) == 1 and drop['没有数值'] == 1:
        print('  [PASS] 没数值的丢掉；同一个数复述多遍只算一条'); ok += 1
    else:
        print(f'  [FAIL] 去重或空值判错：{kept} {drop}')

    total += 1
    # **失败分支也要真跑一遍**：模型调用抛异常时那行日志本身写错过
    # （`log.warning` 不存在，而 Log 只有 `warn`）—— import 能过、平时不走到，
    # 一到真跑就在「处理失败」的路上再炸一次（踩坑 #49 的原样重演）。
    import tempfile as _tf, os as _os, io as _io
    from shared.adapters import llm_client as _llm
    with _tf.TemporaryDirectory() as _d:
        _cur, _raw = paths.CURATED, paths.RAW
        _chat = _llm.chat_json
        paths.CURATED, paths.RAW = _os.path.join(_d, 'c'), _os.path.join(_d, 'r')
        try:
            paths.parsed_dir('YYYY0003', create=True)
            _io.open(paths.fulltext('YYYY0003'), 'w', encoding='utf-8').write(
                '# Results' + chr(10) + '' + chr(10) + '' + ('The sample reached 12.4 MPa and 480 % elongation at a rate of 50 mm/min, with a modulus of 3.2 MPa. ' * 8))
            _llm.chat_json = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('模型挂了'))
            _io.open(paths.chunk_measurements('YYYY0003'), 'w',
                     encoding='utf-8').write('{"measurements": [1]}')
            r = C.run_one('YYYY0003', model='x', verbose=False)
            still = _io.open(paths.chunk_measurements('YYYY0003'),
                             encoding='utf-8').read()
            if (r.get('n_failed_chunks') and not r.get('measurements')
                    and '[1]' in still):
                print('  [PASS] 模型全挂时不崩，也不把上一次的好结果覆盖成空'); ok += 1
            else:
                print(f'  [FAIL] 失败分支不对：{r} / 盘上还剩 {still[:40]!r}')
        except Exception as e:
            print(f'  [FAIL] 失败分支自己炸了：{type(e).__name__}: {e}')
        finally:
            _llm.chat_json = _chat
            paths.CURATED, paths.RAW = _cur, _raw



    print(f'\n{ok}/{total} 通过')
    sys.exit(0 if ok == total else 1)


if __name__ == '__main__':
    main()
