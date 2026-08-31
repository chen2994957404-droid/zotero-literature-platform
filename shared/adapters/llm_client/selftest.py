# -*- coding: utf-8 -*-
"""llm_client 自测：用本地 Ollama（零成本）验证 chat / chat_json；验证缺 key 报错。
用法: python shared/adapters/llm_client/selftest.py
需本地 Ollama 跑着聊天模型（模型名配 OLLAMA_MODEL，默认 qwen2.5:7b-instruct）。
⚠ 自测的 system 消息用英文：实测 qwen3.5 对中文 system 消息要算 40~90 秒
（stream:false 下看起来像卡死），自测只验链路，不测翻译。
"""
import sys, os
from shared.adapters.llm_client import chat, chat_json, LLMError

def main():
    ok = 0; total = 3

    # 1. 本地 chat 纯文本（英文 system，避免 qwen3.5 中文 system 卡 40s+）
    try:
        out = chat('You are a concise assistant. Answer in one word.',
                   'What is the capital of China?', provider='ollama', temperature=0)
        if out and len(out) > 0:
            print(f'  [PASS] ollama chat 返回: {out[:20]}'); ok += 1
        else:
            print('  [FAIL] ollama chat 空返回')
    except Exception as e:
        print(f'  [FAIL] ollama chat 异常: {e}')

    # 2. 本地 chat_json 强制 JSON
    try:
        d = chat_json('You are an extraction engine. Output JSON only.',
                      'Extract the city from this sentence: The capital of China is Beijing. Fields: city',
                      provider='ollama')
        if isinstance(d, dict):
            print(f'  [PASS] ollama chat_json 返回 dict: {d}'); ok += 1
        else:
            print('  [FAIL] chat_json 未返回 dict')
    except Exception as e:
        print(f'  [FAIL] ollama chat_json 异常: {e}')

    # 3. 密钥获取链路正常（环境变量 或 .env 都能拿到；拿不到时报明确错误）
    #    注：安全改造后 key 从 shared.kernel.config 读，参数传空会自动回退到 .env——
    #    这是期望行为（更健壮），所以这里测"能拿到密钥"而非"传空必报错"。
    try:
        from shared.kernel.config import get_key
        if get_key('DEEPSEEK_KEY'):
            print('  [PASS] 密钥链路正常（config 能取到 DEEPSEEK_KEY）'); ok += 1
        else:
            # 真的没有密钥时，调用应报 LLMError 而非静默失败
            try:
                chat('x', 'y', provider='deepseek', key='')
                print('  [FAIL] 无密钥时应报 LLMError')
            except LLMError:
                print('  [PASS] 无密钥时正确报 LLMError'); ok += 1
    except Exception as e:
        print(f'  [FAIL] 密钥链路异常: {type(e).__name__}: {e}')

    print(f'\n{ok}/{total} 通过')
    sys.exit(0 if ok == total else 1)

if __name__ == '__main__':
    main()
