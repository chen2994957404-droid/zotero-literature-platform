# -*- coding: utf-8 -*-
"""embed 自测：离线验 chunk / strip_references；加 --live 才真去问本机 Ollama 的 bge-m3。
用法: python shared/adapters/embed/selftest.py [--live]
自测必须离线、任何机器上都能全绿（编程端没装 Ollama），联网那条藏在 --live 后面。
"""
import sys, os
from shared.adapters.embed import embed, chunk, strip_references
from shared.kernel.cli import flag

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

    # 3. embed 返回向量（联网，只在 --live 时跑）
    if not flag('--live'):
        print('  [SKIP] embed 真调用（加 --live 才跑）'); ok += 1
    else:
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
