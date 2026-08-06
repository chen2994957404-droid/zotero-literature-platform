# -*- coding: utf-8 -*-
"""config · 配置/密钥加载基础件（公理：统一、可靠地拿到密钥）

解决的真实问题（踩坑 #17/#19 反复出现三次）：
密钥只放环境变量时，setx 设的值**只对之后新建的进程生效**，长驻进程/子进程常拿不到，
导致 401、"未设置 MINERU_TOKEN" 等静默失败。

加载顺序（后者不覆盖前者）：
  1. 进程环境变量（os.environ）—— 优先，便于临时覆盖
  2. 项目根目录的 .env 文件 —— 兜底，保证任何启动方式都能拿到

用法：
    from modules.config import get_key
    key = get_key('DEEPSEEK_KEY')            # 拿不到返回 ''
    key = get_key('DEEPSEEK_KEY', required=True)   # 拿不到直接报错，避免静默失败

.env 格式（该文件已在 .gitignore，不进版本库）：
    DEEPSEEK_KEY=sk-xxx
    ZOTERO_API_KEY=xxx
    MINERU_TOKEN=sk-xxx
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENV_FILE = os.path.join(ROOT, '.env')

_cache = None


def _load_env_file():
    """读 .env（KEY=value，支持 # 注释、去引号）。文件不存在返回空 dict。"""
    data = {}
    if not os.path.exists(ENV_FILE):
        return data
    try:
        with open(ENV_FILE, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k, v = line.split('=', 1)
                data[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    return data


def get_key(name, required=False, default=''):
    """取配置：先环境变量，再 .env 文件。required=True 时拿不到直接报错。"""
    global _cache
    v = os.environ.get(name, '')
    if not v:
        if _cache is None:
            _cache = _load_env_file()
        v = _cache.get(name, '')
    if not v:
        if required:
            raise RuntimeError(
                f'缺少配置 {name}。请任选其一：\n'
                f'  1) 设环境变量：setx {name} "你的密钥"（需重开终端/重启进程）\n'
                f'  2) 在项目根目录 .env 里写：{name}=你的密钥（推荐，任何启动方式都生效）')
        return default
    return v


def all_keys():
    """当前可用的配置键（用于自检，不返回值本身）。"""
    global _cache
    if _cache is None:
        _cache = _load_env_file()
    names = set(_cache.keys())
    for n in ('DEEPSEEK_KEY', 'ZOTERO_API_KEY', 'MINERU_TOKEN', 'SILICONFLOW_KEY'):
        if os.environ.get(n):
            names.add(n)
    return sorted(names)


# ---------------------------------------------------------------------------
# 本机设置：所有「换台电脑就得改」的东西集中在这里
# ---------------------------------------------------------------------------
# 原来这些散落在 19 个文件里 hardcode（Zotero 用户ID）、4 个文件里写死绝对路径，
# 后果有二：① 换电脑/换人就全废；② 用户想改只能来找我改代码。
# 收敛到此处后，既能一键换机，也能在控制面板上自助修改。
# (键名, 显示名, 默认值, 说明)
SITE_SETTINGS = [
    ('ZOTERO_USER_ID', 'Zotero 用户 ID', '',
     'Zotero 设置→账户里的 userID，纯数字'),
    ('ZOTERO_STORAGE', 'Zotero 附件目录', '',
     '形如 D:\\...\\Zotero\\storage，精读结果要写进去'),
    ('ZOTERO_API_HOST', 'Zotero 本地服务地址', 'http://localhost:23119',
     '一般不用改'),
    ('OLLAMA_HOST', 'Ollama 地址', 'http://localhost:11434',
     '一般不用改'),
    ('OLLAMA_MODELS', 'Ollama 模型目录', '',
     '形如 D:\\...\\Ollama\\models；留空则用 Ollama 默认位置'),
]


def get_site(name):
    """取本机设置。环境变量 → .env → 内置默认。

    未配置且无默认值时返回 ''，由调用方决定是报错还是降级 ——
    本函数不替调用方做这个判断（公理件只负责取值）。
    """
    for k, _label, default, _help in SITE_SETTINGS:
        if k == name:
            return get_key(name, default=default)
    raise KeyError(f'未知的本机设置项 {name}，可选：{[s[0] for s in SITE_SETTINGS]}')


def need_site(name):
    """取必填的本机设置，没配就**明确报错**并给出怎么配。

    为什么不留「读不到就用默认值」的兜底：
    那会把开发者本人的 Zotero 用户ID 留在源码里（传到 GitHub 就是泄露），
    而且别人装上后会静默连到陌生人的库 —— 静默用错值比直接报错危险得多。
    """
    v = get_site(name)
    if not v:
        label = next((s[1] for s in SITE_SETTINGS if s[0] == name), name)
        tip = next((s[3] for s in SITE_SETTINGS if s[0] == name), '')
        raise RuntimeError(
            f'缺少本机设置「{label}」（{name}）。{tip}\n'
            f'  配置方法：双击「控制面板.bat」→ 在「本机设置」里填写；\n'
            f'  或直接在项目根目录 .env 里写一行：{name}=你的值')
    return v


def site_missing():
    """哪些必填的本机设置还没配（装到新电脑时用来提示）。返回键名列表。"""
    must = ('ZOTERO_USER_ID', 'ZOTERO_STORAGE')
    return [k for k in must if not get_site(k)]


# ---------------------------------------------------------------------------
# 模型设置：把散在各脚本里的模型名收敛到这里，控制面板才能统一切换
# ---------------------------------------------------------------------------
# 默认值即项目宪法的「两把尺子」：输出少的活上 pro（准），输出多的上 flash（省）
MODEL_SETTINGS = {
    'DEEPREAD_MODEL':   ('精读',       'deepseek-v4-flash'),
    'EXTRACT_MODEL':    ('结构化抽取', 'deepseek-v4-pro'),
    'ASK_MODEL':        ('问答',       'deepseek-v4-flash'),
    'AUTOTAG_MODEL':    ('自动打标签', 'deepseek-v4-flash'),
    'BRAINSTORM_MODEL': ('研究构想',   'deepseek-v4-pro'),
}


def get_model(name):
    """取某个环节该用的模型名。环境变量 → .env → 内置默认，三级兜底。

    这样任何脚本都写 get_model('DEEPREAD_MODEL')，不再各自 hardcode，
    控制面板改一处即全局生效（原来 .env 的值进不了 os.environ，
    用 os.environ.get 读模型的脚本改了也不生效 —— 本函数消除该陷阱）。
    """
    if name not in MODEL_SETTINGS:
        raise KeyError(f'未知的模型设置项 {name}，可选：{list(MODEL_SETTINGS)}')
    return get_key(name, default=MODEL_SETTINGS[name][1])


def set_keys(updates):
    """把 {键: 值} 写回 .env（原子替换 + 自动备份）。返回实际写入的键名列表。

    值为 None 或 '' 的键会被跳过（避免面板留空时误清空已有密钥）。
    **只写 .env，不动源码** —— 源码内不含明文密钥这条底线不能破。
    """
    global _cache
    existing = _load_env_file()
    written = []
    for k, v in (updates or {}).items():
        if v is None or str(v).strip() == '':
            continue
        existing[k] = str(v).strip()
        written.append(k)
    if not written:
        return []
    # 备份旧文件（可逆是修改配置的前提）
    if os.path.exists(ENV_FILE):
        import shutil, time
        shutil.copy2(ENV_FILE, ENV_FILE + f'.bak{time.strftime("%m%d%H%M%S")}')
    tmp = ENV_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write('# 由控制面板/程序写入。本文件已在 .gitignore，不进版本库。\n')
        for k in sorted(existing):
            f.write(f'{k}={existing[k]}\n')
    os.replace(tmp, ENV_FILE)   # 原子替换，避免写一半断电留下坏文件
    _cache = None               # 让下次 get_key 重新读盘
    return written


def mask(value):
    """脱敏显示密钥：只留后 4 位。面板展示用，避免密钥出现在截图/录屏里。"""
    if not value:
        return ''
    return ('*' * max(4, len(value) - 4)) + value[-4:]
