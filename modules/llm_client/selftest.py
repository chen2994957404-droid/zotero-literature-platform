# -*- coding: utf-8 -*-
"""llm_client 自测：用本地 Ollama（零成本）验证 chat / chat_json；验证缺 key 报错。
用法: python modules/llm_client/selftest.py
需本地 Ollama 跑着 qwen2.5:7b-instruct。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from modules.llm_client import chat, chat_json, LLMError

def main():
    ok = 0; total = 3

    # 1. 本地 chat 纯文本
    try:
        out = chat('你是助手，只答一个字', '中国的首都是？简短回答',
                   provider='ollama', temperature=0)
        if out and len(out) > 0:
            print(f'  [PASS] ollama chat 返回: {out[:20]}'); ok += 1
        else:
            print('  [FAIL] ollama chat 空返回')
    except Exception as e:
        print(f'  [FAIL] ollama chat 异常: {e}')

    # 2. 本地 chat_json 强制 JSON
    try:
        d = chat_json('你是抽取引擎，只输出JSON',
                      '把这句话抽成JSON，字段city：中国首都是北京',
                      provider='ollama')
        if isinstance(d, dict):
            print(f'  [PASS] ollama chat_json 返回 dict: {d}'); ok += 1
        else:
            print('  [FAIL] chat_json 未返回 dict')
    except Exception as e:
        print(f'  [FAIL] ollama chat_json 异常: {e}')

    # 3. 缺 key 时 deepseek 正确报 LLMError
    old = os.environ.pop('DEEPSEEK_KEY', None)
    try:
        try:
            chat('x', 'y', provider='deepseek', key='')
            print('  [FAIL] 缺 key 应报 LLMError')
        except LLMError:
            print('  [PASS] 缺 key 正确报 LLMError'); ok += 1
        except Exception as e:
            print(f'  [FAIL] 报了非预期异常: {type(e).__name__}')
    finally:
        if old:
            os.environ['DEEPSEEK_KEY'] = old

    print(f'\n{ok}/{total} 通过')
    sys.exit(0 if ok == total else 1)

if __name__ == '__main__':
    main()
