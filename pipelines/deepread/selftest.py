# -*- coding: utf-8 -*-
"""deepread 自测：不花一分钱、不联网，验证这条流水线的骨架是活的。

这里**故意不做**「真跑一篇」——那要 MineRU + DeepSeek，一次几块钱，
不适合体检反复跑。真跑一篇请用 `python 文献精读/deepread_batch.py <KEY> --force`。
"""
import os
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from shared.kernel import jobs
from pipelines import deepread
from pipelines.deepread import main_text, merge as merge_mod, si as si_mod


def main():
    ok = 0
    total = 5

    # 1. 提示词文件在不在（搬家最容易漏的就是数据文件）
    try:
        p = main_text.sys_prompt()
        if len(p) > 200 and '【图' in p:
            print(f'  [PASS] 精读提示词可读（{len(p)} 字，v{main_text.PROMPT_VER}）')
            ok += 1
        else:
            print(f'  [FAIL] 提示词内容不对：{len(p)} 字')
    except Exception as e:
        print(f'  [FAIL] 读不到提示词：{e}')

    # 2. 确定性插图：模型说「图放这儿」，图由脚本插
    figs = [{'b64': 'data:image/png;base64,AAA', 'caption': '', 'num': 1},
            {'b64': 'data:image/png;base64,BBB', 'caption': '', 'num': 2}]
    out = main_text.insert_figures('讲图一【图1】\n## 总结\n完', figs)
    if 'AAA' in out and 'BBB' in out and '【图1】' not in out:
        print('  [PASS] 确定性插图（漏掉的图自动补在总结前）')
        ok += 1
    else:
        print(f'  [FAIL] 插图结果异常：{out[:120]}')

    # 3. 渲染：栏目标题 / 加粗 / 图片直通
    html = main_text.render_html('## 导读\n**要点**\n<img src="x">')
    if 'h2 class="section"' in html and '<strong>要点</strong>' in html and '<img src="x">' in html:
        print('  [PASS] HTML 渲染')
        ok += 1
    else:
        print(f'  [FAIL] 渲染异常：{html[:150]}')

    # 4. 合并：正文在前、SI 在后，样式都在
    m = merge_mod.merge_html(
        '<html><head><style>BODYCSS</style></head><body><p>正文在此</p></body></html>',
        '<html><body><p>补充材料在此</p></body></html>')
    if ('BODYCSS' in m and m.index('正文在此') < m.index('补充材料在此')
            and 'si-divider' in m):
        print('  [PASS] 正文+SI 合并')
        ok += 1
    else:
        print('  [FAIL] 合并结果不对')

    # 5. 状态库：记账 → 查得到 → 「只补缺的部分」判得出
    with tempfile.TemporaryDirectory() as d:
        real = jobs.db_path
        jobs.db_path = lambda: os.path.join(d, 'state.db')
        jobs.close()
        try:
            with jobs.track('ZZZZ0001', deepread.STEP_MAIN, model='x', prompt_ver=2):
                pass
            row = jobs.last('ZZZZ0001', deepread.STEP_MAIN)
            stale = jobs.stale(deepread.STEP_MAIN, prompt_ver=3)
            if row and row['status'] == jobs.OK and stale == ['ZZZZ0001']:
                print('  [PASS] 任务状态库记账 + 「提示词升级即重跑清单」')
                ok += 1
            else:
                print(f'  [FAIL] 状态库异常：{row} / {stale}')
        finally:
            jobs.close()
            jobs.db_path = real

    print(f'\n{ok}/{total} 通过')
    sys.exit(0 if ok == total else 1)


if __name__ == '__main__':
    main()
