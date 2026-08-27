# -*- coding: utf-8 -*-
"""sciverse 自测：验证接口契约与清洗逻辑。

设计取舍：**纯逻辑测试不联网**（快、免费、随时可跑）；
只有配了密钥时才做一次最小真实调用验证连通性 —— 自测不该烧用户额度。
用法: python adapters/sciverse/selftest.py
"""
import sys, os, io

# 用 reconfigure 而非替换 sys.stdout：后者会让原对象被回收、底层缓冲被关闭，
# 表现为程序跑到一半 print 抛「I/O operation on closed file」（踩坑 #37）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from adapters.sciverse import clean_chunk, _year, available, paper_relations, SciverseError


def main():
    ok = 0
    total = 5

    # 1. 片段清洗：实测返回的 chunk 确实混着图片占位符
    dirty = '![](dt=2026-03-17/ht=00/abc123.jpg)\n\n# 机理\n\n\n\nB-O 键可逆断裂重组。  \n  '
    c = clean_chunk(dirty)
    if 'jpg' not in c and 'B-O' in c and '\n\n\n' not in c:
        print('  [PASS] 片段清洗：去图片占位符、压缩空白'); ok += 1
    else:
        print(f'  [FAIL] 清洗结果异常: {c!r}')

    # 2. 空输入不炸
    if clean_chunk(None) == '' and clean_chunk('') == '':
        print('  [PASS] 清洗空输入安全'); ok += 1
    else:
        print('  [FAIL] 空输入处理异常')

    # 3. 年份归一：实测 API 会返回 2022.0 这种浮点，也可能是 None
    if _year('2022.0') == 2022 and _year(2024) == 2024 and _year(None) is None and _year('') is None:
        print('  [PASS] 年份归一（浮点/整数/空 都能处理）'); ok += 1
    else:
        print('  [FAIL] 年份归一有问题')

    # 4. 非法 relation 应立刻报错，而不是发出无效请求浪费额度
    try:
        paper_relations('paper:10.1/x', relation='WRONG')
        print('  [FAIL] 非法 relation 未被拦截')
    except SciverseError:
        print('  [PASS] 非法 relation 在本地就被拦下（不浪费额度）'); ok += 1
    except Exception as e:
        print(f'  [FAIL] 抛了非预期异常: {type(e).__name__}')

    # 5. 连通性：配了密钥才测，且只发一次最小请求
    total_check = 5
    if not available():
        print('  [SKIP] 未配置 SCIVERSE_KEY，跳过联网测试'); ok += 1
    else:
        try:
            from adapters.sciverse import search_papers
            r = search_papers('polyborosiloxane', limit=1)
            if r['total'] > 0 and r['items']:
                print(f"  [PASS] 真实调用成功（命中 {r['total']} 篇）"); ok += 1
            else:
                print('  [FAIL] 真实调用返回空结果')
        except Exception as e:
            print(f'  [FAIL] 真实调用失败: {str(e)[:120]}')

    print(f'\n{ok}/{total} 通过')
    sys.exit(0 if ok == total else 1)


if __name__ == '__main__':
    main()
