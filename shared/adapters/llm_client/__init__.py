# -*- coding: utf-8 -*-
"""llm_client · LLM 调用基础件（公理：文本 → LLM → 文本/JSON）

职责：统一封装对大模型的调用。此前散在 9 个脚本、6 个函数各写各的
（deepseek/ollama/call_llm/deepseek_json/ollama_json/llm_json），导致重复 +
密钥注入混乱（踩坑 #17）。收敛成单一公理件，一处正确、处处复用。

公理特征：只做「给 messages，返回模型输出」这一件不可再分的事。

对外接口：
  - chat(system, user, ...)      → 纯文本输出（对话/精读/问答）
  - chat_json(system, user, ...) → 强制 JSON 输出并解析成 dict（结构化抽取）
  两者都支持云端多家（deepseek / siliconflow / gemini）与本地 ollama。
  **选哪家由模型名决定**：`gemini-*` 自动走 Gemini，不必另设开关（见 PROVIDERS）。

配置（环境变量，可被函数参数覆盖）：
  - DEEPSEEK_KEY   : DeepSeek API key
  - GEMINI_KEY     : Google AI Studio 的 key（走 Gemini 的 OpenAI 兼容端点）
  - LLM_PROVIDER   : 认不出模型名时的默认 provider，默认 deepseek
  - DEEPSEEK_MODEL : 默认 deepseek-v4-pro
  - OLLAMA_MODEL   : 默认 qwen2.5:7b-instruct
  - OLLAMA_HOST    : 默认 http://localhost:11434

模型选择原则（宪法·两把尺子的沉淀）：输出少的活用 pro（抽取），输出多的用 flash（精读）。
"""
import os, json, re, urllib.request, urllib.error
try:
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.dirname(_o.path.dirname(_o.path.dirname(_o.path.abspath(__file__)))))
    from shared.kernel.config import get_key as _cfg_get, get_site as _cfg_site
except Exception:
    _cfg_get = lambda n, **kw: _o.environ.get(n, '')
    _cfg_site = lambda n: _o.environ.get(n, '')

_OLLAMA_DEFAULT = 'http://localhost:11434'      # 只在 config 取不到时兜底

DEEPSEEK_API = 'https://api.deepseek.com/chat/completions'

# ── 云端 provider 登记处 ──────────────────────────────────────────────
# (chat 端点, 密钥名, 默认文本模型, 默认视觉模型)
#
# **能并成一张表，是因为它们说的是同一种话**：三家都提供 OpenAI 兼容的
# `/chat/completions`（Gemini 的兼容层见 ai.google.dev/gemini-api/docs/openai）。
# 所以「换一家模型」在这里只是多一行，不是多一条代码路径 ——
# 这正是「联网只许在 adapters」那条铁律买来的东西。
PROVIDERS = {
    'deepseek': (DEEPSEEK_API, 'DEEPSEEK_KEY',
                 'deepseek-v4-pro', 'deepseek-vl2'),
    'siliconflow': ('https://api.siliconflow.cn/v1/chat/completions', 'SILICONFLOW_KEY',
                    'Qwen/Qwen2.5-72B-Instruct', 'Qwen/Qwen2.5-VL-72B-Instruct'),
    'gemini': ('https://generativelanguage.googleapis.com/v1beta/openai/chat/completions',
               'GEMINI_KEY', 'gemini-3.8-flash', 'gemini-3.8-flash'),
}

# 模型名前缀 → 是谁家的。
#
# **为什么靠模型名认人，而不是再加一个「选哪家」的开关**：控制面板里
# 每个环节本来就已经有一个「用哪个模型」的输入框。再加一个 provider 开关，
# 用户就有了两个必须彼此对上的设置项 —— 对不上时的症状是「模型不存在」，
# 而那看起来像模型名写错了，没人会想到是另一个框选错了家。
# 一个设置项推不出两种真相，那就只留一个。
_MODEL_OWNERS = (('gemini-', 'gemini'), ('deepseek-', 'deepseek'), ('Qwen/', 'siliconflow'))


def provider_of(model):
    """从模型名认出该找哪家。认不出来返回 ''（由调用方决定默认）。"""
    for prefix, name in _MODEL_OWNERS:
        if model and str(model).startswith(prefix):
            return name
    return ''


class LLMError(Exception):
    pass


def _cfg(provider, model, key):
    """把 (provider, model, key) 补全。**模型名是权威**：给了 `gemini-*`
    就去 Gemini，哪怕调用方同时说了 provider='deepseek'。

    ⚠ 为什么模型名要能**推翻**显式传进来的 provider（2026-09-03 实测撞出来）：
      `tools/deepread/batch.py` 里写着 `provider='deepseek'` 和
      `key=get_key('DEEPSEEK_KEY')` —— 那是写死在下游的默认值。
      于是用户在面板把精读模型改成 `gemini-3.8-flash` 之后，请求照样发去
      DeepSeek，得到一句 `The supported API model names are deepseek-...`。
      **上游加了新能力，下游的写死默认值让它静默失效** —— 而且症状出现在
      离改动最远的地方。

      挡住这类问题的办法不是去改每一个调用方（漏一个就复发），
      而是让唯一知道「谁家是谁家」的这一层说了算。
    """
    owner = provider_of(model)
    if owner and provider != 'ollama' and owner != provider:
        # 连 key 一起丢掉：调用方递来的是**另一家的钥匙**，
        # 拿去开这扇门只会换来一句莫名其妙的 401/400。
        provider, key = owner, ''
    elif not provider:
        provider = os.environ.get('LLM_PROVIDER', 'deepseek')
    if model is None:
        # 走 config（环境变量→.env 三级），不能用裸 os.environ：
        # 否则 .env 里配的 OLLAMA_MODEL 对 llm_client 永远不生效（踩坑：404）
        if provider == 'ollama':
            model = _cfg_get('OLLAMA_MODEL') or 'qwen2.5:7b-instruct'
        elif provider == 'deepseek':
            model = _cfg_get('DEEPSEEK_MODEL') or PROVIDERS['deepseek'][2]
        else:
            model = PROVIDERS[provider][2]
    if not key and provider in PROVIDERS:
        key = _cfg_get(PROVIDERS[provider][1])
    return provider, model, key


# ── 花了多少 token（记账）────────────────────────────────────────────
# 为什么要记（2026-08-28）：用户跑了 7 篇就发现「花了不少钱」，而我们当时
# **谁也说不出一篇要多少钱** —— 只能猜。看不见的开销没法优化，也没法让人放心。
USAGE = {'calls': 0, 'prompt': 0, 'completion': 0, 'reasoning': 0, 'model': ''}


def _note_usage(u, model=''):
    if not u:
        return
    USAGE['calls'] += 1
    USAGE['prompt'] += int(u.get('prompt_tokens') or 0)
    USAGE['completion'] += int(u.get('completion_tokens') or 0)
    det = u.get('completion_tokens_details') or {}
    USAGE['reasoning'] += int(det.get('reasoning_tokens') or 0)
    USAGE['model'] = model or USAGE['model']


def usage_snapshot():
    """到目前为止这个进程花掉的 token。调用方自己算差值就是「这一篇花了多少」。"""
    return dict(USAGE)


def _cloud_chat(messages, model, key, temperature, json_mode, max_tokens,
                thinking=None, provider='deepseek'):
    """打一家 OpenAI 兼容的云端模型。thinking 只对 DeepSeek 有意义。

    thinking: True=开推理链, False=关, None=随 API 默认（V4 默认开）。

    ⚠ 踩坑：V4 思考模式默认开启，推理链 token **计入 max_tokens**。
    max_tokens 给小了（如 8000），推理吃光额度 → 正文被截断甚至空输出。
    长文生成（精读）应关掉 thinking 或把 max_tokens 放大。
    """
    endpoint, key_env, _m, _v = PROVIDERS.get(provider, PROVIDERS['deepseek'])
    if not key:
        raise LLMError(f'未提供 {key_env}')
    body = {'model': model, 'temperature': temperature, 'messages': messages}
    # 「少想一点」这件事，两家的说法不一样，得各说各的话。
    #
    # ⚠ 而且 **Gemini 3 的思考关不掉**（官方原话：2.5 之后的模型不支持
    #   `reasoning_effort="none"`），只能调到最低。所以 `thinking=False` 在这里
    #   不是「关掉」而是「尽量少想」—— 名字骗人，但行为是对的：
    #   调用方要的本来就是「别让推理链吃掉正文额度」。
    #
    # 这条是实测撞出来的（2026-09-03）：max_tokens=300 的一次试探直接
    # 「输出被截断且正文近乎为空」—— 300 全被思考吃光了，一个字没留给答案。
    if thinking is not None:
        if provider == 'deepseek':
            body['thinking'] = {'type': 'enabled' if thinking else 'disabled'}
        elif provider == 'gemini' and not thinking:
            # ⚠ 用 `low`，**别用文档里列的 `minimal`**：文档把 minimal 列成合法值，
            #   但 gemini-3.8-flash 实测回 400
            #   `Thinking level MINIMAL is not supported for this model`。
            #   又一次「文档说的和它实际接受的不一样」—— 以实测为准。
            body['reasoning_effort'] = 'low'
    if json_mode:
        body['response_format'] = {'type': 'json_object'}
    if max_tokens:
        body['max_tokens'] = max_tokens
    req = urllib.request.Request(endpoint,
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
        # 429 在两家的含义**不一样**：DeepSeek 那边多半是并发抖动，退避重试就好；
        # Gemini 免费档的 429 是**额度用光了**（每分钟或每天），
        # 再退避也没用，等下一个窗口才行。把这句说清楚，省得对着日志猜。
        hint = ''
        if getattr(last, 'code', None) == 429 and provider != 'deepseek':
            hint = ('\n  429 在免费档一般是**额度用光**（每分钟或每天的上限），'
                    '不是服务器忙 —— 重试帮不上，要等下一个额度窗口。')
        raise LLMError(f'{provider} 服务端异常，重试 4 次仍失败: {last}{hint}')
    _note_usage(r.get('usage'), model)
    ch = r['choices'][0]
    out = ch['message'].get('content') or ''
    # 输出被 max_tokens 截断时明确报错，避免静默产出半截/空结果
    if ch.get('finish_reason') == 'length' and len(out) < 200:
        raise LLMError(
            f'输出被 max_tokens={max_tokens} 截断且正文近乎为空 —— '
            f'{model} 的推理链计入这个额度，被它吃光了。\n'
            f'  DeepSeek：thinking=False 可以真的关掉。\n'
            f'  Gemini 3：**关不掉**，只能 reasoning_effort=minimal 调到最低，'
            f'所以额度要给得比 DeepSeek 更宽。')
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
        out = _cloud_chat(messages, model, key, temperature, False, max_tokens,
                          thinking, provider)
    return re.sub(r'<think>[\s\S]*?</think>', '', out).strip()  # 去掉推理模型的 think 段


def chat_messages(messages, provider=None, model=None, key=None,
                  temperature=0.3, max_tokens=None, num_ctx=16384, thinking=None):
    """多轮对话：直接给完整 messages 列表（含 system / 历史 user+assistant）。

    R3 窗（2026-08-30）加的：创意讨论（tools/direction/brainstorm）要带上下文连续追问，
    而它原本自己 urlopen 打 DeepSeek —— 那是「联网只在 adapters」的破口（红线 #5）。
    `chat()` 是它的单轮特例。
    """
    provider, model, key = _cfg(provider, model, key)
    if provider == 'ollama':
        out = _ollama(messages, model, temperature, False, num_ctx)
    else:
        out = _cloud_chat(messages, model, key, temperature, False, max_tokens,
                          thinking, provider)
    return re.sub(r'<think>[\s\S]*?</think>', '', out).strip()


def chat_vision(system, user, image_b64, provider=None, model=None, key=None,
                temperature=0.1, json_mode=False):
    """看图输出。image_b64 是图片的 base64（可含或不含 data:image 前缀）。
    用于图表数字化等视觉任务。默认 provider 用支持视觉的模型。

    云端走 OpenAI 兼容的 image_url 格式；本地 Ollama 走其 images 字段。
    """
    # 同 _cfg：模型名能推翻调用方说的家，并把另一家的钥匙一起丢掉。
    _owner = provider_of(model)
    if _owner and provider != 'ollama' and _owner != provider:
        provider, key = _owner, ''
    elif not provider:
        provider = os.environ.get('VISION_PROVIDER', 'deepseek')
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
        # 云端 OpenAI 兼容（deepseek / siliconflow / gemini）
        endpoint, key_env, _t, default_model = PROVIDERS.get(
            provider, PROVIDERS['deepseek'])
        model = model or default_model
        # ⚠ 这里原来写的是 `os.environ.get(key_env)` —— **凭据库里的密钥读不到**。
        #   密钥搬进系统凭据库之后，看图这条路就只在「密钥恰好也在环境变量里」时能用，
        #   而那正是开发机的样子，主力机上不是。走 _cfg_get 才是三级加载。
        key = key or _cfg_get(key_env)
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
              temperature=0.1, num_ctx=16384, thinking=False):
    """强制 JSON 输出并解析成 dict。用于结构化抽取。temperature 默认低求稳。

    **`thinking` 默认关**（2026-08-28 改）：V4 的推理链默认开启，而推理 token
    **按输出价计费（约为输入价的 3 倍）**。结构化抽取要的是「照着原文填表格」，
    不是解数学题 —— 那条推理链既没用上，又是这件事最大的一笔开销。
    确实需要模型多想一步时，显式传 `thinking=True`。
    """
    provider, model, key = _cfg(provider, model, key)
    messages = [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]
    if provider == 'ollama':
        out = _ollama(messages, model, temperature, True, num_ctx)
    else:
        out = _cloud_chat(messages, model, key, temperature, True, None,
                          thinking, provider)
    return _parse_json_lenient(out)


def check_key(key=None, timeout=15):
    """这把 DeepSeek 密钥现在还有效吗？返回 (ok, 人话说明)。**不花钱**。

    为什么需要（2026-08-28 真事）：主力机的密钥早就失效了，
    但体检只查「读得到」，于是心跳正常、体检全绿，**精读其实一次都跑不了** ——
    等用户下次打标签才会发现，而那时他只会看到「怎么没反应」。
    **「配置存在」不等于「配置有用」，安全网必须查后者。**
    """
    import json as _json
    import urllib.error as _ue
    import urllib.request as _ur
    k = key
    if k is None:
        from shared.kernel.config import get_key
        k = get_key('DEEPSEEK_KEY')
    if not k:
        return False, '没配 DEEPSEEK_KEY'
    try:
        r = _ur.urlopen(_ur.Request('https://api.deepseek.com/user/balance',
                                    headers={'Authorization': 'Bearer ' + k}), timeout=timeout)
        d = _json.loads(r.read())
        # ⚠ balance_infos 是**按币种一条**的列表。只取 [0] 会报出
        # 「0.00 USD」而实际人民币账户里还有钱 —— 一个把好消息说成坏消息的显示 bug。
        infos = d.get('balance_infos') or []
        parts = [f'{i.get("total_balance", "?")} {i.get("currency", "")}'.strip()
                 for i in infos if str(i.get('total_balance', '0')) not in ('0', '0.00')]
        bal = '、'.join(parts) if parts else '0（各币种都是 0）'
        if not d.get('is_available', True):
            return False, f'密钥有效但账户不可用（余额 {bal}）'
        return True, f'有效，余额 {bal}'
    except _ue.HTTPError as e:
        return False, ('密钥无效或已撤销（HTTP 401）' if e.code == 401
                       else f'查不了：HTTP {e.code}')
    except Exception as e:
        return None, f'连不上 DeepSeek：{type(e).__name__}'
