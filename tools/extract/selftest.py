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

KEY = 'ZZZZ0002'


def main():
    ok = total = 0
    with tempfile.TemporaryDirectory() as d:
        real_lib, real_struct, real_db = paths.LIBRARY, paths.STRUCTURED, jobs.db_path
        paths.LIBRARY = os.path.join(d, 'library')
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
            paths.LIBRARY, paths.STRUCTURED, jobs.db_path = real_lib, real_struct, real_db

    print(f'\n{ok}/{total} 通过')
    sys.exit(0 if ok == total else 1)


if __name__ == '__main__':
    main()
