# -*- coding: utf-8 -*-
"""direction 自测：不联网，用假数据把 落库 → 聚类 → 报告 走一遍。
用法: python tools/direction/selftest.py

build() 要联网，所以自测不跑它 —— 它的两个组成部分（wechat_seed / openalex）
各有自己的 selftest。这里测的是**编排本身**：schema、聚类落库、报告生成。
测试会临时改写 shared.kernel.paths.DIRECTION 指向临时目录，**不碰真实数据**。
"""
import os
import shutil
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.kernel import paths

TMP = tempfile.mkdtemp(prefix='dirmap_')
_ORIG = paths.DIRECTION
paths.DIRECTION = TMP           # 关键：绝不写真实 data/

from tools import direction as dm

ok = True


def check(name, cond, detail=''):
    global ok
    print(('  [OK]   ' if cond else '  [FAIL] ') + name + (('  ' + detail) if detail else ''))
    if not cond:
        ok = False


try:
    print('== 1. 空库时的行为 ==')
    check('没建库时 stats 说 exists=False', dm.stats('t1').get('exists') is False)
    try:
        dm.cluster('t1')
        check('空库聚类应报错', False)
    except dm.DirectionMapError:
        check('空库聚类报 DirectionMapError', True)

    print('== 2. 灌假数据（3 组各 5 篇 + 共用工具论文）==')
    c = dm._conn('t1')
    works, edges = [], []
    for tag_i, tag in enumerate('abc'):
        for i in range(5):
            wid = 'W_%s%d' % (tag, i)
            # 推送日期：a 组集中在 2025，c 组集中在 2026（用来验趋势箭头）
            yr = '2025' if tag == 'a' else ('2026' if tag == 'c' else '2025')
            works.append((wid, '10.1/%s%d' % (tag, i), 'Paper %s%d' % (tag, i), 2024,
                          'Adv Mater', 10, 'Topic-' + tag, 1, '%s-0%d-01' % (yr, i + 1)))
            for j in range(4):
                edges.append((wid, 'R_%s%d' % (tag, j)))
            edges.append((wid, 'T_multiwfn'))
    for tag in 'abc':
        for j in range(4):
            works.append(('R_%s%d' % (tag, j), '', 'Foundation %s%d' % (tag, j),
                          2015, 'Science', 500, '', 0, ''))
    works.append(('T_multiwfn', '', 'Multiwfn: A multifunctional wavefunction analyzer',
                  2011, 'J Comput Chem', 44861, '', 0, ''))
    with c:
        c.executemany('INSERT OR REPLACE INTO works VALUES (?,?,?,?,?,?,?,?,?)', works)
        c.executemany('INSERT OR IGNORE INTO edges VALUES (?,?)', edges)
        c.execute("INSERT OR REPLACE INTO meta VALUES ('build','{\"seeds\":15}')")
    c.close()
    s = dm.stats('t1')
    check('种子 15 篇', s['seeds'] == 15, str(s['seeds']))
    check('参考文献 13 篇', s['refs'] == 13, str(s['refs']))

    print('== 2b. 种子与参考文献重叠时不许把种子降级（实测踩坑）==')
    # 真实数据里有 120 篇种子同时是别人的高频参考文献。按 id 主键覆盖的话，
    # 后写的 is_seed=0 会把它们踢出聚类 —— 而那恰恰是最重要的一批。
    fake_refs = {'W_a0': {'doi': '', 'title': 'Paper a0', 'publication_year': 2024},
                 'R_new': {'doi': '', 'title': 'A real reference', 'publication_year': 2010}}
    rows, overlap = dm.ref_rows_for(fake_refs, {'W_a0', 'W_a1'})
    check('重叠的那篇被跳过', overlap == 1, 'overlap=%d' % overlap)
    check('只留下真正的参考文献', [r[0] for r in rows] == ['R_new'], str([r[0] for r in rows]))
    check('留下的那行 is_seed=0', rows[0][7] == 0)
    rows2, ov2 = dm.ref_rows_for(fake_refs, set())
    check('没有重叠时两条都留', len(rows2) == 2 and ov2 == 0, '%d/%d' % (len(rows2), ov2))

    print('== 3. 聚类 ==')
    rep = dm.cluster('t1', resolutions=(1.0, 2.0), min_size=2, tries=3, progress=None)
    check('报告两档', len(rep) == 2, str([r[0] for r in rep]))
    s = dm.stats('t1')
    check('聚类结果已落库', s['clustered'] == 15, str(s['clustered']))

    print('== 4. 报告 ==')
    txt = dm.report('t1', min_size=2, top_refs=3)
    check('报告里有簇', '簇1' in txt)
    check('报告里有趋势行', '趋势' in txt)
    check('报告里有全域地基', '全域地基' in txt)
    check('工具论文被标出来', '[工具]' in txt, '（Multiwfn 应带 [工具] 标记）')
    check('报告提醒最后一段可能不满半年', '不满半年' in txt)

    print('== 4b. 窄带是必填参数、且 id 受校验 ==')
    try:
        dm.stats('Bad Band!')
        check('非法窄带 id 应报错', False)
    except paths.BadBandError:
        check('非法窄带 id 报 BadBandError', True)
    check('两条窄带分库', dm.paths.direction_db('t1') != dm.paths.direction_db('t2'))
    check('窄带目录能被列出', 't1' in paths.direction_bands(), str(paths.direction_bands()))

    print('== 4c. 没有 band.json 时报错清楚 ==')
    try:
        dm.load_spec('t2')
        check('缺定义文件应报错', False)
    except dm.DirectionMapError as e:
        check('缺定义文件报 DirectionMapError 且说清路径', 'band.json' in str(e))
    dm.save_spec('t2', {'id': 't2', 'name': 'x', 'queries': []})
    check('save_spec 后能读回', dm.load_spec('t2')['id'] == 't2')

    print('== 5. 写文件 ==')
    out = os.path.join(TMP, 'map.txt')
    dm.report('t1', min_size=2, out=out)
    check('文件写出来了', os.path.exists(out) and os.path.getsize(out) > 100)

    print('== 6. 没碰真实数据目录 ==')
    check('DIRECTION 指向临时目录', paths.DIRECTION == TMP)
    check('数据库在临时目录里', dm.paths.direction_db('t1').startswith(TMP))
finally:
    paths.DIRECTION = _ORIG
    shutil.rmtree(TMP, ignore_errors=True)

print('')
print('全部通过' if ok else '有失败项')
sys.exit(0 if ok else 1)
