# -*- coding: utf-8 -*-
"""routing · 大模型的「通道」与「用途」两张表（2026-09-11，用户拍板的结构）。

## 为什么要有这两张表

在这之前，「用哪家」是**靠模型名前缀猜的**：`deepseek-` 开头 → 官方 DeepSeek，
`qwen` 开头 → 百炼。于是用户想「用阿里云的中转站跑 deepseek-v4-flash」
根本表达不出来 —— 名字一带 `deepseek-` 就被送去官方。
另外 13 处代码写死 `provider='deepseek'`、9 处各自 `key=get_key(...)`，
换一家要改十几处；账本只按模型记，说不出「精读花了多少」。

用户的话：「第一部分是填入对应的 API，第二部分是需要调用 API 的部分及选用的模型，
第三部分是日志记录哪些部分调用了哪些 API」。本文件是前两部分，第三部分在 `budget`。

## 两张表

**通道**（channel）= 一个能发请求的地方：名字 / 地址 / 密钥名 / 协议 / 能力。
官方几家是内置的（随代码走），用户加的中转站存在 `llm_routing.json` 里，
**同名时用户的覆盖内置的**（想把官方地址换成中转，改一条就行）。

**用途**（purpose）= 平台里一个要调大模型的环节：精读、抽取、问答……
每个用途指定 **走哪条通道 + 用哪个模型 + 备用通道**。
「哪家」不再猜 —— 每个用途明说。

## 兜底（用户拍板保留）

用途没指定通道时，仍按模型名前缀猜一家，**并标 `inferred=True`**，体检黄灯提醒。
这样老配置不改也能跑，但不会一直不知不觉地跑在猜出来的路上。

## 密钥不在这里

表里只写密钥的**名字**（如 `ALIYUN_RELAY_KEY`），值仍在系统凭据库。
本文件不进 git（每台机器各一份，和 `.env` 同级同待遇）。
"""
import io
import json
import os

from shared.kernel.paths import ROOT

ROUTING_FILE = os.path.join(ROOT, 'llm_routing.json')

# ── 内置通道 ──────────────────────────────────────────────────────────
# kind：'openai' = OpenAI 兼容的 /chat/completions；'ollama' = 本地 Ollama。
# caps：这条通道支持什么。用途配了通道不支持的能力，体检会报，而不是跑到一半炸。
#   text / json（response_format）/ thinking（能关推理链）/ vision（看图）
BUILTIN_CHANNELS = {
    'deepseek-官方': {
        'base': 'https://api.deepseek.com', 'key': 'DEEPSEEK_KEY', 'kind': 'openai',
        'caps': ['text', 'json', 'thinking', 'vision'],
        'note': 'V4.1 起 flash 的正式名是 deepseek-flash；旧名 deepseek-v4-flash 仍被转发'},
    'gemini-官方': {
        'base': 'https://generativelanguage.googleapis.com/v1beta/openai',
        'key': 'GEMINI_KEY', 'kind': 'openai',
        'caps': ['text', 'json', 'vision'],
        'note': 'Gemini 3 的思考关不掉，只能调到最低；免费档 429 = 额度用光'},
    'siliconflow': {
        'base': 'https://api.siliconflow.cn/v1', 'key': 'SILICONFLOW_KEY', 'kind': 'openai',
        'caps': ['text', 'json', 'vision']},
    'aliyun-百炼': {
        # 真实地址走本机设置 DASHSCOPE_BASE（每个用户的业务空间域名不同），这里是兜底
        'base': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        'key': 'DASHSCOPE_KEY', 'kind': 'openai',
        'caps': ['text', 'json', 'vision'],
        'note': '大陆版 key 打不通国际版，反之亦然'},
    'ollama-本地': {
        'base': 'http://localhost:11434', 'key': '', 'kind': 'ollama',
        'caps': ['text', 'json'],
        'note': '免费，但 7B 看图会编假数据，别拿它做图表数字化'},
}

# 模型名前缀 → 内置通道名。**只用于兜底**（用途没指定通道时）。
_PREFIX_GUESS = (('gemini-', 'gemini-官方'), ('deepseek-', 'deepseek-官方'),
                 ('Qwen/', 'siliconflow'), ('qwen', 'aliyun-百炼'))

# ── 用途 ──────────────────────────────────────────────────────────────
# id 是代码里用的名字（调用方写 purpose='DEEPREAD'），label 给人看。
# setting 是老的模型设置项名 —— 兼容：老配置里改过的模型名照样生效。
# needs 是这个用途要求的能力，通道不满足就报。
PURPOSES = {
    'DEEPREAD':       {'label': '精读',           'setting': 'DEEPREAD_MODEL',
                       'needs': ['text', 'thinking']},
    'EXTRACT':        {'label': '结构化抽取',     'setting': 'EXTRACT_MODEL',
                       'needs': ['text', 'json']},
    'ASK':            {'label': '问答',           'setting': 'ASK_MODEL',
                       'needs': ['text']},
    'AUTOTAG':        {'label': '自动打标签',     'setting': 'AUTOTAG_MODEL',
                       'needs': ['text', 'json']},
    'BRAINSTORM':     {'label': '研究构想',       'setting': 'BRAINSTORM_MODEL',
                       'needs': ['text']},
    'DIRECTION_QUAD': {'label': '方向层摘要抽取', 'setting': 'DIRECTION_QUAD_MODEL',
                       'needs': ['text', 'json']},
    'DIGITIZE':       {'label': '图表数字化',     'setting': 'DIGITIZE_MODEL',
                       'needs': ['vision']},
}


# ── 读写 ──────────────────────────────────────────────────────────────
def _load():
    """读用户的路由文件。没有 / 坏了 → 空表（内置通道照常可用）。"""
    try:
        d = json.load(io.open(ROUTING_FILE, encoding='utf-8'))
        if not isinstance(d, dict):
            return {}
        return d
    except Exception:
        return {}


def save(channels=None, purposes=None):
    """整体写回（原子）。传 None 的那半边保持原样。"""
    d = _load()
    if channels is not None:
        d['channels'] = channels
    if purposes is not None:
        d['purposes'] = purposes
    tmp = ROUTING_FILE + '.tmp'
    with io.open(tmp, 'w', encoding='utf-8', newline='') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, ROUTING_FILE)


def channels():
    """全部通道：内置 + 用户加的，**同名时用户的覆盖内置的**。"""
    out = {k: dict(v, builtin=True) for k, v in BUILTIN_CHANNELS.items()}
    for name, c in (_load().get('channels') or {}).items():
        if isinstance(c, dict) and c.get('base'):
            merged = dict(out.get(name, {}), **c)
            merged['builtin'] = name in BUILTIN_CHANNELS
            merged.setdefault('kind', 'openai')
            merged.setdefault('caps', ['text', 'json'])
            merged.setdefault('key', '')
            out[name] = merged
    # 百炼的真实地址与 Ollama 地址走站点设置（老配置项，继续认）
    from shared.kernel.config import get_site
    base = (get_site('DASHSCOPE_BASE') or '').strip().rstrip('/')
    if base and 'aliyun-百炼' in out and out['aliyun-百炼'].get('builtin'):
        out['aliyun-百炼']['base'] = base
    host = (get_site('OLLAMA_HOST') or '').strip().rstrip('/')
    if host and out.get('ollama-本地', {}).get('builtin'):
        out['ollama-本地']['base'] = host
    return out


def guess_channel(model):
    """按模型名前缀猜通道 —— **兜底用**。带冒号的是本地 Ollama 的 tag 语法。"""
    m = str(model or '')
    if ':' in m:
        return 'ollama-本地'
    for prefix, ch in _PREFIX_GUESS:
        if m.startswith(prefix):
            return ch
    return 'deepseek-官方'


def purposes():
    """每个用途现在的路由：{id: {label, channel, model, fallback, inferred, needs}}。

    优先级：路由文件里明确指定的 > 老的模型设置项（`get_model`）+ 前缀猜通道（标 inferred）。
    """
    from shared.kernel.config import get_model
    user = _load().get('purposes') or {}
    out = {}
    for pid, meta in PURPOSES.items():
        u = user.get(pid) if isinstance(user.get(pid), dict) else {}
        model = (u.get('model') or '').strip() or get_model(meta['setting'])
        channel = (u.get('channel') or '').strip()
        inferred = not channel
        if inferred:
            channel = guess_channel(model)
        out[pid] = {'label': meta['label'], 'needs': list(meta['needs']),
                    'channel': channel, 'model': model,
                    'fallback': (u.get('fallback') or '').strip(),
                    'fallback_model': (u.get('fallback_model') or '').strip(),
                    'inferred': inferred}
    return out


def resolve(purpose):
    """一个用途 → 依次可尝试的 [(通道名, 通道dict, 模型名), ...]（主用在前，备用在后）。

    调用方（llm_client）按顺序试：主用失败且属于「换一条路可能有救」的那类错
    （额度用光、鉴权失败、连不上）就试备用。
    """
    if purpose not in PURPOSES:
        raise KeyError(f'未知的用途 {purpose!r}，可选：{list(PURPOSES)}')
    p = purposes()[purpose]
    chs = channels()
    order = []
    if p['channel'] in chs:
        order.append((p['channel'], chs[p['channel']], p['model']))
    if p['fallback'] and p['fallback'] in chs and p['fallback'] != p['channel']:
        order.append((p['fallback'], chs[p['fallback']],
                      p['fallback_model'] or p['model']))
    if not order:
        raise KeyError(f'用途「{p["label"]}」指定的通道 {p["channel"]!r} 不存在。'
                       f'现有通道：{list(chs)}')
    return order


def problems():
    """配置自洽吗 —— 给体检用。返回 (级别, 话) 列表，空 = 全对。"""
    from shared.kernel.config import get_key
    out = []
    chs = channels()
    ps = purposes()
    # 只查**有用途在用**的通道缺不缺密钥 —— 没人用的内置通道没填密钥不是问题，
    # 报出来只会让真警告被淹掉（体检分档的教训：噪音盖住真信号，就没人看了）
    used = {p['channel'] for p in ps.values()} | {p['fallback'] for p in ps.values() if p['fallback']}
    for name in sorted(used):
        c = chs.get(name)
        if c and c.get('key') and not get_key(c['key']):
            out.append(('warn', f'通道「{name}」要的密钥 {c["key"]} 没填'))
    for pid, p in ps.items():
        ch = chs.get(p['channel'])
        if not ch:
            out.append(('fail', f'用途「{p["label"]}」指定的通道 {p["channel"]!r} 不存在'))
            continue
        missing = [n for n in p['needs'] if n not in (ch.get('caps') or [])]
        if missing:
            out.append(('warn', f'用途「{p["label"]}」需要 {"/".join(missing)}，'
                                f'但通道「{p["channel"]}」没声明支持'))
        if p['inferred']:
            out.append(('warn', f'用途「{p["label"]}」没明确指定通道，'
                                f'现在是按模型名猜的「{p["channel"]}」—— 去面板指定'))
        if p['fallback'] and p['fallback'] not in chs:
            out.append(('warn', f'用途「{p["label"]}」的备用通道 {p["fallback"]!r} 不存在'))
    return out
