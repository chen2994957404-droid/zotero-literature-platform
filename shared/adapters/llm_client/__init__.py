# -*- coding: utf-8 -*-
"""llm_client · LLM 调用基础件（原子能力：文本 → LLM → 文本/JSON）

职责：统一封装对大模型的调用。此前散在 9 个脚本、6 个函数各写各的
（deepseek/ollama/call_llm/deepseek_json/ollama_json/llm_json），导致重复 +
密钥注入混乱（踩坑 #17）。收敛成单一原子模块，一处正确、处处复用。

原子模块的特征：只做「给 messages，返回模型输出」这一件不可再分的事。

对外接口：
  - chat(system, user, ...)      → 纯文本输出（对话/精读/问答）
  - chat_json(system, user, ...) → 强制 JSON 输出并解析成 dict（结构化抽取）
  两者都支持云端多家（deepseek / siliconflow / gemini / dashscope）与本地 ollama。
  **选哪家由模型名决定**：`gemini-*` 自动走 Gemini，不必另设开关（见 PROVIDERS）。

配置（环境变量，可被函数参数覆盖）：
  - DEEPSEEK_KEY   : DeepSeek API key
  - GEMINI_KEY     : Google AI Studio 的 key（走 Gemini 的 OpenAI 兼容端点）
  - DASHSCOPE_KEY  : 阿里云百炼的 key（走百炼的 OpenAI 兼容端点，模型名 qwen*）
  - LLM_PROVIDER   : 认不出模型名时的默认 provider，默认 deepseek
  - DEEPSEEK_MODEL : 默认 deepseek-v4-pro
  - OLLAMA_MODEL   : 默认 qwen2.5:7b-instruct
  - OLLAMA_HOST    : 默认 http://localhost:11434

模型选择原则（架构准则·两把尺子的沉淀）：输出少的活用 pro（抽取），输出多的用 flash（精读）。
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
# 阿里云百炼（DashScope）的 OpenAI 兼容端点。
#
# ⚠ 这条**不能写死**：百炼有两种地址，老的通用域名（这里的默认值）和每个用户
#   各不相同的业务空间专属域名（ws-<你的空间id>.cn-beijing.maas.aliyuncs.com，
#   官方推荐、吞吐更高）。后者带着用户自己的 ID，源码里放什么都是错的。
#   所以真实地址走本机设置 DASHSCOPE_BASE，这里只是留个能跑的兜底。
#
# ⚠ 地域绑死密钥：大陆版 key 打不通国际版（dashscope-intl），反之亦然。
DASHSCOPE_API = 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions'


def _chat_endpoint(provider):
    """该往哪个 URL 发。除百炼外都用 PROVIDERS 里登记的固定端点。

    百炼要拼：用户从控制台粘过来的是 base（`.../compatible-mode/v1`），
    不带 `/chat/completions`。要求用户手工补那一截，等于给一个必错项 ——
    他照着控制台粘完，看到的会是 404，而 404 不会告诉他少了什么。
    """
    endpoint = PROVIDERS.get(provider, PROVIDERS['deepseek'])[0]
    if provider != 'dashscope':
        return endpoint
    base = (_cfg_site('DASHSCOPE_BASE') or '').strip().rstrip('/')
    if not base:
        return DASHSCOPE_API
    return base if base.endswith('/chat/completions') else base + '/chat/completions'

# ── 云端 provider 登记处 ──────────────────────────────────────────────
# (chat 端点, 密钥名, 默认文本模型, 默认视觉模型)
#
# **能并成一张表，是因为它们说的是同一种话**：三家都提供 OpenAI 兼容的
# `/chat/completions`（Gemini 的兼容层见 ai.google.dev/gemini-api/docs/openai）。
# 所以「换一家模型」在这里只是多一行，不是多一条代码路径 ——
# 这正是「联网只许在 adapters」那条铁律买来的东西。
PROVIDERS = {
    # ⚠ 第 4 位是**看图**用的默认模型。`deepseek-vl2` 已被下线（2026-09-07 实测，
    # 服务端原话：「supported API model names are deepseek-v4-pro, deepseek-v4-flash,
    # and deepseek-v4-flash-vision-exp」）—— 这一位过期的症状是 HTTP 400，
    # 而 400 不会告诉不懂编程的人「换个模型名就好了」。踩坑 #139。
    'deepseek': (DEEPSEEK_API, 'DEEPSEEK_KEY',
                 'deepseek-v4-pro', 'deepseek-v4-flash-vision-exp'),
    'siliconflow': ('https://api.siliconflow.cn/v1/chat/completions', 'SILICONFLOW_KEY',
                    'Qwen/Qwen2.5-72B-Instruct', 'Qwen/Qwen2.5-VL-72B-Instruct'),
    'gemini': ('https://generativelanguage.googleapis.com/v1beta/openai/chat/completions',
               'GEMINI_KEY', 'gemini-3.8-flash', 'gemini-3.8-flash'),
    'dashscope': (DASHSCOPE_API, 'DASHSCOPE_KEY',
                  'qwen3.7-plus', 'qwen3-vl-plus'),
}

# 模型名前缀 → 是谁家的。
#
# **为什么靠模型名认人，而不是再加一个「选哪家」的开关**：控制面板里
# 每个环节本来就已经有一个「用哪个模型」的输入框。再加一个 provider 开关，
# 用户就有了两个必须彼此对上的设置项 —— 对不上时的症状是「模型不存在」，
# 而那看起来像模型名写错了，没人会想到是另一个框选错了家。
# 一个设置项推不出两种真相，那就只留一个。
_MODEL_OWNERS = (('gemini-', 'gemini'), ('deepseek-', 'deepseek'), ('Qwen/', 'siliconflow'),
                 ('qwen', 'dashscope'))

# 本地 ollama 的模型名长得跟百炼的很像（`qwen2.5:7b-instruct` vs `qwen3.7-plus`），
# 但 ollama 的名字**一定带冒号**（那是它的 tag 语法），云端的一定不带。
# 不区分的话，本地免费模型会被静默发去云端花钱 —— 症状还只是「跑得有点慢」。
_OLLAMA_TAG = ':'


def provider_of(model):
    """从模型名认出该找哪家。认不出来返回 ''（由调用方决定默认）。"""
    if model and _OLLAMA_TAG in str(model):
        return ''            # 带 tag 的是本地 ollama 模型，云端认不出这种名字
    for prefix, name in _MODEL_OWNERS:
        if model and str(model).startswith(prefix):
            return name
    return ''


class LLMError(Exception):
    """大模型调用失败。

    `failover=True` 表示**换一条通道可能有救**（额度用光、鉴权失败、连不上、
    服务端持续 5xx）；False 表示换了也一样（请求本身有问题、输出被截断……）。
    路由执行器只在前一种情况下试备用通道 —— 否则会把配置错误藏起来。
    """
    def __init__(self, msg, failover=False):
        super().__init__(msg)
        self.failover = failover


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
    if not owner and model and _OLLAMA_TAG in str(model):
        # 带 tag 的名字（`qwen3.5:latest`）只有本地 ollama 认。
        # 不认这条的后果是**把本地模型名发去云端**，换回一句「模型不存在」——
        # 而那看起来像模型名写错了，没人会想到是发错了家（2026-09-07 撞到）。
        provider, key = 'ollama', ''
    owner = owner if owner else provider_of(model)
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


def _ollama_usage(r):
    """Ollama 的回话 → OpenAI 那套 usage 字段名。**两家的字段名不同，一处翻译。**"""
    if not isinstance(r, dict) or 'prompt_eval_count' not in r and 'eval_count' not in r:
        return None
    return {'prompt_tokens': r.get('prompt_eval_count') or 0,
            'completion_tokens': r.get('eval_count') or 0}


def _note_usage(u, model='', paid=False, purpose='', channel=''):
    """记这次调用的用量。`paid=True` 时**同时记进跨进程的当日账本**。

    进程内的 `USAGE` 只活到进程结束，调用方拿它算「这一篇花了多少」；
    而 `shared.kernel.budget` 是落盘的当日账本，watcher / 面板 / MCP 三个进程
    各花各的，只有落盘才加得到一起。本地 Ollama 不计（免费），所以要 `paid` 这个参数。
    """
    if not u:
        return
    USAGE['calls'] += 1
    USAGE['prompt'] += int(u.get('prompt_tokens') or 0)
    USAGE['completion'] += int(u.get('completion_tokens') or 0)
    det = u.get('completion_tokens_details') or {}
    USAGE['reasoning'] += int(det.get('reasoning_tokens') or 0)
    USAGE['model'] = model or USAGE['model']
    if paid:
        from shared.kernel import budget
        budget.record(prompt=u.get('prompt_tokens') or 0,
                      completion=u.get('completion_tokens') or 0, model=model,
                      purpose=purpose, channel=channel)


def usage_snapshot():
    """到目前为止这个进程花掉的 token。调用方自己算差值就是「这一篇花了多少」。"""
    return dict(USAGE)


def apply_thinking(body, provider, thinking):
    """把「少想一点」翻译成这家听得懂的话。**三家三种说法，一处翻译。**

    | 家 | 说法 |
    |---|---|
    | deepseek | `thinking={'type': 'enabled'/'disabled'}` |
    | dashscope（百炼 qwen3.x）| `enable_thinking=True/False` |
    | gemini | 关不掉，只能 `reasoning_effort='low'` |

    ⚠ **漏翻译不会报错，只会安静地一直开着**：百炼这一家漏了将近一天 ——
    方向层抽摘要因此慢了一个数量级（实测同一个提问：开着 45 tok / 1.2s，
    关掉 5 tok / 0.6s），还白付了推理链的输出费（踩坑 #130）。

    ⚠ Gemini 3 之后思考**真的关不掉**（官方原话：不支持 `reasoning_effort="none"`），
    只能调到最低。所以这里的 `thinking=False` 对它是「尽量少想」——
    名字骗人，但行为是调用方要的那个：别让推理链吃掉正文额度。
    实测撞过：max_tokens=300 时思考把额度吃光，正文一个字没剩（2026-09-03）。
    """
    if thinking is None:
        return body
    if provider == 'deepseek':
        body['thinking'] = {'type': 'enabled' if thinking else 'disabled'}
    elif provider == 'dashscope':
        body['enable_thinking'] = bool(thinking)
    elif provider == 'gemini' and not thinking:
        # ⚠ 用 `low`，**别用文档里列的 `minimal`**：文档把它列成合法值，
        #   但 gemini-3.8-flash 实测回 400
        #   `Thinking level MINIMAL is not supported for this model`。
        body['reasoning_effort'] = 'low'
    return body


def _cloud_chat(messages, model, key, temperature, json_mode, max_tokens,
                thinking=None, provider='deepseek', endpoint=None,
                purpose='', channel=''):
    """打一家 OpenAI 兼容的云端模型。thinking 三家三种说法，本函数负责翻译。

    thinking: True=开推理链, False=关, None=随 API 默认（V4 默认开）。

    ⚠ 踩坑：V4 思考模式默认开启，推理链 token **计入 max_tokens**。
    max_tokens 给小了（如 8000），推理吃光额度 → 正文被截断甚至空输出。
    长文生成（精读）应关掉 thinking 或把 max_tokens 放大。
    """
    _e, key_env, _m, _v = PROVIDERS.get(provider, PROVIDERS['deepseek'])
    # endpoint 显式给了就用（走通道表那条路）；没给才按 provider 查老表（兜底）
    endpoint = endpoint or _chat_endpoint(provider)
    if not key:
        raise LLMError(f'未提供 {key_env}', failover=True)
    # ⚠ 当日额度闸。**装在发请求之前** —— 一次调用要么完整发生要么不发生，
    #   半截的精读比不精读更难收拾。没设限额时它永远放行（只记账）。
    #   这道闸不依赖客户端：MCP 的 confirm 是 Claude Code 专有标记，
    #   换个客户端（Antigravity）会被直接忽略（2026-09-10 实际发生过）。
    from shared.kernel import budget
    budget.check(f'调用 {model}')
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
    apply_thinking(body, provider, thinking)
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
                # 401/402/403 = 钥匙不对 / 没钱 / 没权限 —— 换条通道可能有救；
                # 其余 4xx 是请求本身的问题，换了也一样，别把配置错误藏起来
                raise LLMError(f'HTTP {e.code}: {e.read()[:300].decode("utf8","replace")}',
                               failover=(e.code in (401, 402, 403)))
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
        raise LLMError(f'{channel or provider} 服务端异常，重试 4 次仍失败: {last}{hint}',
                       failover=True)
    _note_usage(r.get('usage'), model, paid=True, purpose=purpose, channel=channel)
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


def _ollama(messages, model, temperature, json_mode, num_ctx, host=None):
    host = host or _cfg_site('OLLAMA_HOST') or _OLLAMA_DEFAULT
    # ⚠ `think` 是 Ollama 请求的**顶层**参数，不是 options 里的（踩坑 #155，2026-09-11）。
    #   原来写在 options 里，Ollama 静默忽略 —— 于是 qwen3.5 每次都先偷偷推理几千字再答：
    #   主力机 A/B 实测同一条打标签请求，options 里 53 秒（隐藏推理 8104 字），
    #   顶层 2.8 秒（0 字）。**20 倍**。此前注释记的「思考模式+中文会卡几分钟」
    #   症状看对了、修在了错的地方 —— 症状消失过是因为换了模型，不是因为这一行。
    body = {'model': model, 'stream': False, 'think': False,
            'options': {'temperature': temperature, 'num_ctx': num_ctx},
            'messages': messages}
    if json_mode:
        body['format'] = 'json'
    req = urllib.request.Request(host + '/api/chat',
        data=json.dumps(body, ensure_ascii=False).encode(), method='POST',
        headers={'Content-Type': 'application/json'})
    r = json.loads(urllib.request.urlopen(req, timeout=600).read())
    return r['message']['content']


# ── 按「用途」走「通道」（2026-09-11，用户拍板的三段式：通道 / 用途 / 账本）────
# 调用方只说「我是精读」：`chat(..., purpose='DEEPREAD')`。
# 走哪条通道、用哪个模型、备用是谁，由 `shared.kernel.config.routing` 查表决定；
# 主用失败且**换条路可能有救**（额度用光 / 鉴权失败 / 连不上）时自动试备用。
# 老的 provider/model/key 三件套仍然能用 —— 那是兜底，不是主路。

def _attempts(purpose, provider, model, key):
    """→ 依次可尝试的 [(通道名, 通道dict, 模型)]。给了 purpose 就查路由表，否则走老路。"""
    if purpose:
        from shared.kernel.config import routing
        order = routing.resolve(purpose)
        if model:
            # 同时给了 purpose 和 model = 「走这个用途的通道，但用我指定的模型」
            # （精读线「用 pro 重跑」就是这种用法）。备用通道若自己配了模型则不动。
            p = routing.purposes()[purpose]
            order = [(n, ch, (model if i == 0 or not p['fallback_model'] else m))
                     for i, (n, ch, m) in enumerate(order)]
        return order
    provider, model, key = _cfg(provider, model, key)
    if provider == 'ollama':
        return [('ollama-本地', {'kind': 'ollama', 'base': _cfg_site('OLLAMA_HOST')
                                 or _OLLAMA_DEFAULT, 'key': ''}, model)]
    ep = _chat_endpoint(provider)
    base = ep[:-len('/chat/completions')] if ep.endswith('/chat/completions') else ep
    return [(provider, {'kind': 'openai', 'base': base,
                        'key': PROVIDERS.get(provider, PROVIDERS['deepseek'])[1],
                        '_key_value': key, '_provider': provider}, model)]


def _run(purpose, attempts, call):
    """按顺序试每条通道。`call(通道名, 通道dict, 模型)` 抛 LLMError(failover=True) 就换下一条。

    只在「换条路可能有救」的错上切换 —— 请求本身的错（400、截断、JSON 解析失败）
    换了也一样，切换只会把配置错误藏起来。
    """
    from shared.kernel.log import get_logger
    log = get_logger('llm_client')
    errs = []
    for i, (name, ch, model) in enumerate(attempts):
        last = (i == len(attempts) - 1)
        try:
            return call(name, ch, model)
        except LLMError as e:
            errs.append(f'{name}/{model}: {e}')
            if not e.failover or last:
                raise
            log.warn(f'{purpose or "调用"} 走「{name}」失败（{str(e)[:80]}），'
                     f'切到备用「{attempts[i + 1][0]}」')
        except (urllib.error.URLError, OSError) as e:
            errs.append(f'{name}/{model}: {e}')
            if last:
                raise LLMError('；'.join(errs), failover=True)
            log.warn(f'{purpose or "调用"} 连不上「{name}」（{e}），'
                     f'切到备用「{attempts[i + 1][0]}」')
    raise LLMError('；'.join(errs))


def _channel_key(ch):
    """通道的密钥值。老路（_attempts 的兜底分支）会把值直接塞在 _key_value 里。"""
    if ch.get('_key_value'):
        return ch['_key_value']
    return _cfg_get(ch['key']) if ch.get('key') else ''


def _text_call(messages, temperature, json_mode, max_tokens, num_ctx, thinking, purpose):
    """造一个「在某条通道上发这组 messages」的调用，给 _run 用。"""
    def call(name, ch, model):
        if ch.get('kind') == 'ollama':
            return _ollama(messages, model, temperature, json_mode, num_ctx,
                           host=ch.get('base'))
        base = (ch.get('base') or '').rstrip('/')
        ep = base if base.endswith('/chat/completions') else base + '/chat/completions'
        return _cloud_chat(messages, model, _channel_key(ch), temperature, json_mode,
                           max_tokens, thinking, ch.get('_provider') or name,
                           endpoint=ep, purpose=purpose, channel=name)
    return call


def chat(system, user, provider=None, model=None, key=None,
         temperature=0.3, max_tokens=None, num_ctx=16384, thinking=None, purpose=None):
    """纯文本输出。用于对话/精读/问答。

    **推荐只传 `purpose`**（如 'DEEPREAD'），通道与模型由路由表决定、主用失败自动切备用。
    provider/model/key 三件套是老路，仍可用。
    thinking=False 建议用于长文生成（精读）：省 token、省钱、避免正文被推理链挤掉。
    """
    messages = [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]
    out = _run(purpose, _attempts(purpose, provider, model, key),
               _text_call(messages, temperature, False, max_tokens, num_ctx, thinking, purpose))
    return re.sub(r'<think>[\s\S]*?</think>', '', out).strip()  # 去掉推理模型的 think 段


def chat_messages(messages, provider=None, model=None, key=None,
                  temperature=0.3, max_tokens=None, num_ctx=16384, thinking=None,
                  purpose=None):
    """多轮对话：直接给完整 messages 列表（含 system / 历史 user+assistant）。

    R3 窗（2026-08-30）加的：创意讨论（tools/direction/brainstorm）要带上下文连续追问，
    而它原本自己 urlopen 打 DeepSeek —— 那是「联网只在 adapters」的破口（强制规范 #5）。
    `chat()` 是它的单轮特例。
    """
    out = _run(purpose, _attempts(purpose, provider, model, key),
               _text_call(messages, temperature, False, max_tokens, num_ctx, thinking, purpose))
    return re.sub(r'<think>[\s\S]*?</think>', '', out).strip()


def chat_vision(system, user, image_b64, provider=None, model=None, key=None,
                temperature=0.1, json_mode=False, purpose=None):
    """看图输出。image_b64 是图片的 base64（可含或不含 data:image 前缀）。
    用于图表数字化等视觉任务。

    **推荐只传 `purpose='DIGITIZE'`**，通道与模型由路由表决定、主用失败自动切备用。
    云端走 OpenAI 兼容的 image_url 格式；本地 Ollama 走其 images 字段。
    """
    # 规范化 base64（去掉 data:image 前缀取纯数据；同时保留完整 data uri 供云端用）
    raw_b64 = re.sub(r'^data:image/\w+;base64,', '', image_b64)
    data_uri = image_b64 if image_b64.startswith('data:') else f'data:image/png;base64,{raw_b64}'

    if purpose:
        from shared.kernel.config import routing
        attempts = routing.resolve(purpose)
    else:
        # 老路：同 _cfg，模型名能推翻调用方说的家，并把另一家的钥匙一起丢掉。
        _owner = provider_of(model)
        if _owner and provider != 'ollama' and _owner != provider:
            provider, key = _owner, ''
        elif not provider:
            # 走三级加载（环境变量 → 凭据库 → .env），不只读环境变量 ——
            # 面板把设置写进 .env，而 .env 的值进不了 os.environ（强制规范 #3 的老坑）。
            provider = _cfg_get('VISION_PROVIDER') or 'deepseek'
        if provider == 'ollama':
            model = model or _cfg_get('OLLAMA_VISION_MODEL') or 'qwen2.5vl:7b'
            attempts = [('ollama-本地', {'kind': 'ollama',
                                         'base': _cfg_site('OLLAMA_HOST') or _OLLAMA_DEFAULT,
                                         'key': ''}, model)]
        else:
            _e, key_env, _t, default_model = PROVIDERS.get(provider, PROVIDERS['deepseek'])
            ep = _chat_endpoint(provider)
            base = ep[:-len('/chat/completions')] if ep.endswith('/chat/completions') else ep
            # ⚠ 密钥走 _cfg_get 三级加载（凭据库里的才读得到），不是裸 os.environ
            attempts = [(provider, {'kind': 'openai', 'base': base, 'key': key_env,
                                    '_key_value': key or _cfg_get(key_env),
                                    '_provider': provider}, model or default_model)]

    def call(name, ch, model):
        if ch.get('kind') == 'ollama':
            body = {'model': model, 'stream': False, 'think': False,   # 顶层，同 _ollama（踩坑 #155）
                    'options': {'temperature': temperature},
                    'messages': [{'role': 'system', 'content': system},
                                 {'role': 'user', 'content': user, 'images': [raw_b64]}]}
            if json_mode:
                body['format'] = 'json'
            req = urllib.request.Request((ch.get('base') or _OLLAMA_DEFAULT).rstrip('/') + '/api/chat',
                data=json.dumps(body).encode(), method='POST',
                headers={'Content-Type': 'application/json'})
            r = json.loads(urllib.request.urlopen(req, timeout=600).read())
            _note_usage(_ollama_usage(r), model)
            return r['message']['content']

        k = _channel_key(ch)
        if not k:
            raise LLMError(f'通道「{name}」没有密钥（{ch.get("key") or "未指定"}）', failover=True)
        # ⚠ 看图这条路**自己发请求，不经过 `_cloud_chat`**，所以闸门要单独装一份。
        #   2026-09-07 记账那次栽过同样的形状：只有 `_cloud_chat` 记账，于是
        #   **最贵的那类调用反而是唯一没被管住的**。加闸时别重蹈覆辙。
        from shared.kernel import budget
        budget.check(f'看图（{model}）')
        base = (ch.get('base') or '').rstrip('/')
        ep = base if base.endswith('/chat/completions') else base + '/chat/completions'
        content = [{'type': 'text', 'text': user},
                   {'type': 'image_url', 'image_url': {'url': data_uri}}]
        body = {'model': model, 'temperature': temperature,
                'messages': [{'role': 'system', 'content': system},
                             {'role': 'user', 'content': content}]}
        if json_mode:
            body['response_format'] = {'type': 'json_object'}
        req = urllib.request.Request(ep,
            data=json.dumps(body, ensure_ascii=False).encode(), method='POST',
            headers={'Authorization': f'Bearer {k}', 'Content-Type': 'application/json'})
        try:
            r = json.loads(urllib.request.urlopen(req, timeout=300).read())
        except urllib.error.HTTPError as e:
            raise LLMError(f'HTTP {e.code}: {e.read()[:300].decode("utf8","replace")}',
                           failover=(e.code in (401, 402, 403, 429, 500, 502, 503, 504)))
        # 看图也要记账（2026-09-07 补）。此前只有 `_cloud_chat` 记，于是
        # **最贵的那类调用反而是唯一不记账的** —— 试跑两张图后问「花了多少」，
        # 得到的是「调用 0 次、0 token」，正是 USAGE 当初要消灭的那种回答。
        _note_usage(r.get('usage'), model, paid=True, purpose=purpose, channel=name)
        return r['choices'][0]['message']['content']

    return _run(purpose, attempts, call)


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
              temperature=0.1, num_ctx=16384, thinking=False, purpose=None):
    """强制 JSON 输出并解析成 dict。用于结构化抽取。temperature 默认低求稳。

    **`thinking` 默认关**（2026-08-28 改）：V4 的推理链默认开启，而推理 token
    **按输出价计费（约为输入价的 3 倍）**。结构化抽取要的是「照着原文填表格」，
    不是解数学题 —— 那条推理链既没用上，又是这件事最大的一笔开销。
    确实需要模型多想一步时，显式传 `thinking=True`。
    """
    messages = [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]
    out = _run(purpose, _attempts(purpose, provider, model, key),
               _text_call(messages, temperature, True, None, num_ctx, thinking, purpose))
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
