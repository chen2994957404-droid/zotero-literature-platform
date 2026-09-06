# -*- coding: utf-8 -*-
"""getpdf 自测：纯离线，不碰浏览器、不碰网络。

**这个工具的主体在别人家的浏览器里跑**，本机验不了。所以这里只验
「不联网也必须成立」的那部分：文件名安全、落盘位置走 paths、
已有文件会跳过、撞验证码会停而不是接着跑。

浏览器那半只能在真机上验：`python -m tools.getpdf --probe`。
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import io
import tempfile

from shared.kernel import paths
from tools import getpdf


def main():
    ok = total = 0

    total += 1
    n = getpdf.safe_name('10.1016/j.cej.2025.164092')
    if '/' not in n and n.startswith('10.1016') and n.endswith('164092'):
        print(f'  [PASS] DOI → 文件名：{n}'); ok += 1
    else:
        print(f'  [FAIL] 文件名不对：{n}')

    total += 1
    # 红线 #4：路径必须从 paths 来，不许自己拼 data
    d = getpdf.out_dir()
    if d.startswith(paths.INCOMING):
        print('  [PASS] 落盘位置走 paths.INCOMING'); ok += 1
    else:
        print(f'  [FAIL] 落盘位置没走 paths：{d}')

    total += 1
    # 盘上已经有了就跳过 —— 重跑一批不该重敲出版商
    with tempfile.TemporaryDirectory() as tmp:
        doi = '10.1016/fake.test.1'
        p = os.path.join(tmp, getpdf.safe_name(doi) + '.pdf')
        with io.open(p, 'wb') as fh:
            fh.write(b'%PDF-1.7' + b'x' * 4096)
        r = getpdf.fetch_one(doi, tmp)
        if r['ok'] and r['reason'] == 'exists' and r['path'] == p:
            print('  [PASS] 盘上已有的会跳过，不重下'); ok += 1
        else:
            print(f'  [FAIL] 已有文件没跳过：{r}')

    total += 1
    # 撞上验证码要停整批 —— 硬跑只会把剩下的全废掉，还多敲出版商一堆次
    src = io.open(os.path.join(os.path.dirname(__file__), '__init__.py'),
                  encoding='utf-8').read()
    if "if r['reason'] == 'captcha':" in src and 'break' in src:
        print('  [PASS] 撞验证码是「停」不是「跳过」'); ok += 1
    else:
        print('  [FAIL] 找不到撞验证码就停的逻辑')

    total += 1
    if getpdf.GAP >= 10 and getpdf.LIMIT <= 50:
        print(f'  [PASS] 默认值保守：间隔 {getpdf.GAP} 秒、单次上限 {getpdf.LIMIT} 篇'); ok += 1
    else:
        print(f'  [FAIL] 默认值太激进：GAP={getpdf.GAP} LIMIT={getpdf.LIMIT}')

    total += 1
    # 用途 → 合集名的表，和它在别处被引用的名字，必须对得上
    if (set(getpdf.PURPOSES) == {'建库', '精读'}
            and all(len(v) == 2 and v[0] and v[1] for v in getpdf.PURPOSES.values())):
        print('  [PASS] 用途表完整（建库 / 精读，各带合集名与说明）'); ok += 1
    else:
        print(f'  [FAIL] 用途表不对：{getpdf.PURPOSES}')

    total += 1
    # 用途写错了要当场拦住，不能默默收到某个合集里去
    try:
        getpdf.ensure_tree('随便编一个')
        print('  [FAIL] 乱写的用途没被拦住')
    except ValueError:
        print('  [PASS] 用途写错了会当场拦住'); ok += 1
    except Exception as e:
        print(f'  [FAIL] 抛的不是 ValueError，是 {type(e).__name__}')

    total += 1
    # 查重必须走全库 DOI 索引，不能按篇去搜（2026-09-05 实测：按篇搜连建三个重复条目）。
    # ⚠ 这里查的是**正面行为**（有没有用索引），不是「某个字符串在不在」——
    # 头一版写成「源码里不许出现 qmode=everything」，结果匹配到了文档字符串里
    # 那句「别用 q 搜索」的警告，自己把自己判红了。
    # 判据要盯着行为，别盯着字面，否则连解释都不敢写在代码里。
    src = io.open(os.path.join(os.path.dirname(__file__), '__init__.py'),
                  encoding='utf-8').read()
    if 'def doi_index' in src and 'index.get(' in src:
        print('  [PASS] 查重走全库 DOI 索引，不是按篇去搜'); ok += 1
    else:
        print('  [FAIL] 查重没走索引 —— 按篇搜会漏掉刚写进去的，于是建重复条目')

    total += 1
    # 上传附件之后**必须**再铺一份到本地 storage。少了这一步，用户点开附件是
    # 「在此路径无法找到附件」—— 因为上传进的是 Zotero 官方存储，而他的文件同步
    # 走 WebDAV，桌面端只去 WebDAV 找。2026-09-05 真的这么坏过一次。
    src = io.open(os.path.join(os.path.dirname(__file__), '__init__.py'),
                  encoding='utf-8').read()
    i_up = src.find('upload_attachment(')
    i_put = src.find('put_local(')
    if i_up >= 0 and i_put > i_up:
        print('  [PASS] 上传之后有铺本地 storage 这一步'); ok += 1
    else:
        print('  [FAIL] 上传完没铺本地 —— 用户点开会「找不到附件」')

    total += 1
    c = getpdf.summarize([{'reason': 'ok'}, {'reason': 'ok'}, {'reason': 'no_access'}])
    if c == {'ok': 2, 'no_access': 1}:
        print('  [PASS] 结果汇总'); ok += 1
    else:
        print(f'  [FAIL] 汇总不对：{c}')

    print(f'\n{ok}/{total} 通过')
    sys.exit(0 if ok == total else 1)


if __name__ == '__main__':
    main()
