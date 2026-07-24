# -*- coding: utf-8 -*-
"""embed 自测：用本地 bge-m3（零成本）验证 embed / chunk / strip_references。
用法: python modules/embed/selftest.py
需本地 Ollama 跑着 bge-m3。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from modules.embed import embed, chunk, strip_references

def main():
    ok = 0; total = 3

    # 1. strip_references 截掉参考文献（正文占比要够，否则触发防误截保护）
    text = ("这是一段较长的正文内容，描述了实验方法和结果。" * 20 +
            "\n\n# References\n1. Foo et al.\n2. Bar et al.")
    stripped = strip_references(text)
    if 'References' not in stripped and '正文' in stripped:
        print('  [PASS] strip_references 正确截断'); ok += 1
    else:
        print(f'  [FAIL] strip_references: ...{stripped[-40:]}')

    # 2. chunk 切块
    long_text = ('段落。' * 100 + '\n\n') * 5
    chunks = chunk(long_text, max_chars=200)
    if isinstance(chunks, list) and len(chunks) > 1:
        print(f'  [PASS] chunk 切出 {len(chunks)} 块'); ok += 1
    else:
        print(f'  [FAIL] chunk: {len(chunks) if isinstance(chunks,list) else chunks}')

    # 3. embed 返回向量
    try:
        vecs = embed(["测试文本一", "测试文本二"])
        if isinstance(vecs, list) and len(vecs) == 2 and len(vecs[0]) > 100:
            print(f'  [PASS] embed 返回 2 个 {len(vecs[0])} 维向量'); ok += 1
        else:
            print(f'  [FAIL] embed 返回异常')
    except Exception as e:
        print(f'  [FAIL] embed 异常（本地 bge-m3 没跑？）: {e}')

    print(f'\n{ok}/{total} 通过')
    sys.exit(0 if ok == total else 1)

if __name__ == '__main__':
    main()
