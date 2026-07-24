# -*- coding: utf-8 -*-
"""llm_client · LLM 调用基础件（公理：文本 → LLM → 文本/JSON）

职责：统一封装对大模型的调用。此前散在 9 个脚本、6 个函数各写各的
（deepseek/ollama/call_llm/deepseek_json/ollama_json/llm_json），导致重复 +
密钥注入混乱（踩坑 #17）。收敛成单一公理件，一处正确、处处复用。

公理特征：只做「给 messages，返回模型输出」这一件不可再分的事。

对外接口：
  - chat(system, user, ...)      → 纯文本输出（对话/精读/问答）
  - chat_json(system, user, ...) → 强制 JSON 输出并解析成 dict（结构化抽取）
  两者都支持 provider='deepseek'(云) / 'ollama'(本地)，通过参数或环境变量切换。

配置（环境变量，可被函数参数覆盖）：
  - DEEPSEEK_KEY   : DeepSeek API key
  - LLM_PROVIDER   : 默认 provider（deepseek / ollama），默认 deepseek
  - DEEPSEEK_MODEL : 默认 deepseek-v4-pro
  - OLLAMA_MODEL   : 默认 qwen2.5:7b-instruct
  - OLLAMA_HOST    : 默认 http://localhost:11434

模型选择原则（宪法·两把尺子的沉淀）：输出少的活用 pro（抽取），输出多的用 flash（精读）。
"""
import os, json, re, urllib.request

DEEPSEEK_API = 'https://api.deepseek.com/chat/completions'


class LLMError(Exception):
    pass


def _cfg(provider, model, key):
    provider = provider or os.environ.get('LLM_PROVIDER', 'deepseek')
    key = key or os.environ.get('DEEPSEEK_KEY', '')
    if model is None:
        model = (os.environ.get('OLLAMA_MODEL', 'qwen2.5:7b-instruct') if provider == 'ollama'
                 else os.environ.get('DEEPSEEK_MODEL', 'deepseek-v4-pro'))
    return provider, model, key


def _deepseek(messages, model, key, temperature, json_mode, max_tokens):
    if not key:
        raise LLMError('未提供 DEEPSEEK_KEY')
    body = {'model': model, 'temperature': temperature, 'messages': messages}
    if json_mode:
        body['response_format'] = {'type': 'json_object'}
    if max_tokens:
        body['max_tokens'] = max_tokens
    req = urllib.request.Request(DEEPSEEK_API,
        data=json.dumps(body, ensure_ascii=False).encode(), method='POST',
        headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'})
    r = json.loads(urllib.request.urlopen(req, timeout=300).read())
    return r['choices'][0]['message']['content']


def _ollama(messages, model, temperature, json_mode, num_ctx):
    host = os.environ.get('OLLAMA_HOST', 'http://localhost:11434')
    body = {'model': model, 'stream': False,
            'options': {'temperature': temperature, 'num_ctx': num_ctx},
            'messages': messages}
    if json_mode:
        body['format'] = 'json'
    req = urllib.request.Request(host + '/api/chat',
        data=json.dumps(body, ensure_ascii=False).encode(), method='POST',
        headers={'Content-Type': 'application/json'})
    r = json.loads(urllib.request.urlopen(req, timeout=600).read())
    return r['message']['content']


def chat(system, user, provider=None, model=None, key=None,
         temperature=0.3, max_tokens=None, num_ctx=16384):
    """纯文本输出。用于对话/精读/问答。"""
    provider, model, key = _cfg(provider, model, key)
    messages = [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]
    if provider == 'ollama':
        out = _ollama(messages, model, temperature, False, num_ctx)
    else:
        out = _deepseek(messages, model, key, temperature, False, max_tokens)
    return re.sub(r'<think>[\s\S]*?</think>', '', out).strip()  # 去掉推理模型的 think 段


def _parse_json_lenient(txt):
    """容错解析：去代码围栏，失败则截第一个 {...}。"""
    txt = re.sub(r'^```(?:json)?|```$', '', txt.strip(), flags=re.M).strip()
    try:
        return json.loads(txt)
    except Exception:
        m = re.search(r'\{.*\}', txt, re.S)
        if m:
            return json.loads(m.group(0))
        raise LLMError('LLM 输出无法解析为 JSON')


def chat_json(system, user, provider=None, model=None, key=None,
              temperature=0.1, num_ctx=16384):
    """强制 JSON 输出并解析成 dict。用于结构化抽取。temperature 默认低求稳。"""
    provider, model, key = _cfg(provider, model, key)
    messages = [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]
    if provider == 'ollama':
        out = _ollama(messages, model, temperature, True, num_ctx)
    else:
        out = _deepseek(messages, model, key, temperature, True, None)
    return _parse_json_lenient(out)
