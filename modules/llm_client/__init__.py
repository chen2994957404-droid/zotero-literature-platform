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
import os, json, re, urllib.request, urllib.error
try:
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))))
    from modules.config import get_key as _cfg_get, get_site as _cfg_site
except Exception:
    _cfg_get = lambda n, **kw: _o.environ.get(n, '')
    _cfg_site = lambda n: _o.environ.get(n, '')

_OLLAMA_DEFAULT = 'http://localhost:11434'      # 只在 config 取不到时兜底

DEEPSEEK_API = 'https://api.deepseek.com/chat/completions'


class LLMError(Exception):
    pass


def _cfg(provider, model, key):
    provider = provider or os.environ.get('LLM_PROVIDER', 'deepseek')
    key = key or _cfg_get('DEEPSEEK_KEY')
    if model is None:
        # 走 config（环境变量→.env 三级），不能用裸 os.environ：
        # 否则 .env 里配的 OLLAMA_MODEL 对 llm_client 永远不生效（踩坑：404）
        model = (_cfg_get('OLLAMA_MODEL') or 'qwen2.5:7b-instruct' if provider == 'ollama'
                 else _cfg_get('DEEPSEEK_MODEL') or 'deepseek-v4-pro')
    return provider, model, key


def _deepseek(messages, model, key, temperature, json_mode, max_tokens, thinking=None):
    """thinking: True=开推理链, False=关, None=随 API 默认（V4 默认开）。

    ⚠ 踩坑：V4 思考模式默认开启，推理链 token **计入 max_tokens**。
    max_tokens 给小了（如 8000），推理吃光额度 → 正文被截断甚至空输出。
    长文生成（精读）应关掉 thinking 或把 max_tokens 放大。
    """
    if not key:
        raise LLMError('未提供 DEEPSEEK_KEY')
    body = {'model': model, 'temperature': temperature, 'messages': messages}
    if thinking is not None:
        body['thinking'] = {'type': 'enabled' if thinking else 'disabled'}
    if json_mode:
        body['response_format'] = {'type': 'json_object'}
    if max_tokens:
        body['max_tokens'] = max_tokens
    req = urllib.request.Request(DEEPSEEK_API,
        data=json.dumps(body, ensure_ascii=False).encode(), method='POST',
        headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'})
    # 5xx / 429 是服务端抖动，退避重试；4xx 是我们自己的错，立刻抛不浪费时间
    last = None
    for attempt in range(4):
        try:
            r = json.loads(urllib.request.urlopen(req, timeout=600).read())
            break
        except urllib.error.HTTPError as e:
            last = e
            if e.code not in (429, 500, 502, 503, 504):
                raise LLMError(f'HTTP {e.code}: {e.read()[:300].decode("utf8","replace")}')
            if attempt < 3:
                import time as _t; _t.sleep(5 * 2 ** attempt)   # 5s/10s/20s
    else:
        raise LLMError(f'DeepSeek 服务端异常，重试 4 次仍失败: {last}')
    ch = r['choices'][0]
    out = ch['message'].get('content') or ''
    # 输出被 max_tokens 截断时明确报错，避免静默产出半截/空结果
    if ch.get('finish_reason') == 'length' and len(out) < 200:
        raise LLMError(
            f'输出被 max_tokens={max_tokens} 截断且正文近乎为空'
            f'（V4 推理链计入额度）。请调大 max_tokens 或关闭 thinking。')
    return out


def _ollama(messages, model, temperature, json_mode, num_ctx):
    host = _cfg_site('OLLAMA_HOST') or _OLLAMA_DEFAULT
    body = {'model': model, 'stream': False,
            'options': {'temperature': temperature, 'num_ctx': num_ctx,
                        'think': False},   # 实测：qwen3.5 思考模式+中文会卡几分钟（stream:false 静默等待），本地调用一律关
            'messages': messages}
    if json_mode:
        body['format'] = 'json'
    req = urllib.request.Request(host + '/api/chat',
        data=json.dumps(body, ensure_ascii=False).encode(), method='POST',
        headers={'Content-Type': 'application/json'})
    r = json.loads(urllib.request.urlopen(req, timeout=600).read())
    return r['message']['content']


def chat(system, user, provider=None, model=None, key=None,
         temperature=0.3, max_tokens=None, num_ctx=16384, thinking=None):
    """纯文本输出。用于对话/精读/问答。

    thinking=False 建议用于长文生成（精读）：省 token、省钱、避免正文被推理链挤掉。
    """
    provider, model, key = _cfg(provider, model, key)
    messages = [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]
    if provider == 'ollama':
        out = _ollama(messages, model, temperature, False, num_ctx)
    else:
        out = _deepseek(messages, model, key, temperature, False, max_tokens, thinking)
    return re.sub(r'<think>[\s\S]*?</think>', '', out).strip()  # 去掉推理模型的 think 段


def chat_vision(system, user, image_b64, provider=None, model=None, key=None,
                temperature=0.1, json_mode=False):
    """看图输出。image_b64 是图片的 base64（可含或不含 data:image 前缀）。
    用于图表数字化等视觉任务。默认 provider 用支持视觉的模型。

    云端走 OpenAI 兼容的 image_url 格式；本地 Ollama 走其 images 字段。
    """
    provider = provider or os.environ.get('VISION_PROVIDER', 'deepseek')
    # 各 provider 的 endpoint / 默认视觉模型 / key 来源
    VISION_ENDPOINTS = {
        'deepseek':    (DEEPSEEK_API, 'deepseek-vl2', 'DEEPSEEK_KEY'),
        'siliconflow': ('https://api.siliconflow.cn/v1/chat/completions',
                        'Qwen/Qwen2.5-VL-72B-Instruct', 'SILICONFLOW_KEY'),
    }
    if model is None and provider == 'ollama':
        model = _cfg_get('OLLAMA_VISION_MODEL') or 'qwen2.5vl:7b'
    # 规范化 base64（去掉 data:image 前缀取纯数据；同时保留完整 data uri 供云端用）
    raw_b64 = re.sub(r'^data:image/\w+;base64,', '', image_b64)
    data_uri = image_b64 if image_b64.startswith('data:') else f'data:image/png;base64,{raw_b64}'

    if provider == 'ollama':
        host = _cfg_site('OLLAMA_HOST') or _OLLAMA_DEFAULT
        body = {'model': model, 'stream': False,
                'options': {'temperature': temperature},
                'messages': [{'role': 'system', 'content': system},
                             {'role': 'user', 'content': user, 'images': [raw_b64]}]}
        if json_mode:
            body['format'] = 'json'
        req = urllib.request.Request(host + '/api/chat',
            data=json.dumps(body).encode(), method='POST',
            headers={'Content-Type': 'application/json'})
        return json.loads(urllib.request.urlopen(req, timeout=600).read())['message']['content']
    else:
        # 云端 OpenAI 兼容（deepseek / siliconflow / 其他）
        endpoint, default_model, key_env = VISION_ENDPOINTS.get(
            provider, VISION_ENDPOINTS['deepseek'])
        model = model or default_model
        key = key or os.environ.get(key_env, '')
        if not key:
            raise LLMError(f'未提供 {key_env}')
        content = [{'type': 'text', 'text': user},
                   {'type': 'image_url', 'image_url': {'url': data_uri}}]
        body = {'model': model, 'temperature': temperature,
                'messages': [{'role': 'system', 'content': system},
                             {'role': 'user', 'content': content}]}
        if json_mode:
            body['response_format'] = {'type': 'json_object'}
        req = urllib.request.Request(endpoint,
            data=json.dumps(body, ensure_ascii=False).encode(), method='POST',
            headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'})
        return json.loads(urllib.request.urlopen(req, timeout=300).read())['choices'][0]['message']['content']


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
