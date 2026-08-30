# -*- coding: utf-8 -*-
"""config · 配置/密钥加载基础件（公理：统一、可靠地拿到密钥）

解决的真实问题（踩坑 #17/#19 反复出现三次）：
密钥只放环境变量时，setx 设的值**只对之后新建的进程生效**，长驻进程/子进程常拿不到，
导致 401、"未设置 MINERU_TOKEN" 等静默失败。

加载顺序（后者不覆盖前者）：
  1. 进程环境变量（os.environ）—— 优先，便于临时覆盖
  2. 项目根目录的 .env 文件 —— 兜底，保证任何启动方式都能拿到

用法：
    from core.config import get_key
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

# ---------------------------------------------------------------------------
# 密钥存储：优先用操作系统凭据库（Windows 凭据管理器 / macOS 钥匙串）
# ---------------------------------------------------------------------------
# 桌面应用的行业标准做法。密钥用当前系统账户加密，不再以明文躺在硬盘上：
#   - 拷走项目文件夹也解不开
#   - 不可能被误提交到 Git
#   - 别的系统账户读不到
# 防不住的是「以你的身份运行的恶意程序」—— 单机环境下没有方案能防住这点，
# 包括企业级的密钥管理服务。不夸大它的作用。
KEYRING_SERVICE = 'literature-platform'

# 哪些是「密钥」（存凭据库），哪些是普通配置（留在 .env，需要可读可移植）
SECRET_KEYS = ('DEEPSEEK_KEY', 'ZOTERO_API_KEY', 'MINERU_TOKEN', 'SILICONFLOW_KEY',
               'SCIVERSE_KEY', 'OPENALEX_KEY')


def _keyring():
    """拿到可用的 keyring 模块；不可用返回 None（降级到 .env，不影响功能）。"""
    try:
        import keyring
        from keyring.backends.fail import Keyring as _Fail
        if isinstance(keyring.get_keyring(), _Fail):
            return None          # 没有可用后端（某些 Linux 环境）
        return keyring
    except Exception:
        return None


def keyring_status():
    """凭据库是否可用 + 后端名。面板用它告诉用户当前密钥存在哪。"""
    kr = _keyring()
    if not kr:
        return False, '不可用（将回退到 .env 明文文件）'
    try:
        return True, str(kr.get_keyring()).split(' ')[0].split('.')[-1]
    except Exception:
        return True, '可用'


def _kr_get(name):
    kr = _keyring()
    if not kr:
        return ''
    try:
        return kr.get_password(KEYRING_SERVICE, name) or ''
    except Exception:
        return ''


def _kr_set(name, value):
    kr = _keyring()
    if not kr:
        return False
    try:
        kr.set_password(KEYRING_SERVICE, name, value)
        return True
    except Exception:
        return False


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
    """取配置。加载顺序（后者兜底前者）：

      1. 进程环境变量 —— 便于临时覆盖、CI 注入
      2. **系统凭据库**（密钥类才查）—— 安全的正式存放处
      3. 项目根 `.env` 文件 —— 兼容旧配置 / 凭据库不可用时的退路

    凭据库排在 .env 之前：迁移之后 .env 里的明文可以安全删掉。
    required=True 时拿不到直接报错，避免静默失败。
    """
    global _cache
    v = os.environ.get(name, '')
    if not v and name in SECRET_KEYS:
        v = _kr_get(name)
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
    for n in ('DEEPSEEK_KEY', 'ZOTERO_API_KEY', 'MINERU_TOKEN', 'SILICONFLOW_KEY',
              'OPENALEX_KEY'):
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
    # ⚠ 角色放第一位：它决定这台机器**允许做什么**，是安全项不是偏好项。
    #   见 docs/两台机器的分工.md 与 core/role.py。默认 dev 是刻意的（fail safe）。
    ('ROLE', '机器角色', 'dev',
     'dev=编程端（不许写 Zotero、不许跑 watcher、不许跑全库作业）；'
     'prod=运行端（主力机，允许全部操作）；'
     'test=编程端但接的是**测试 Zotero 账号**（允许写，但只许写测试库）'),
    ('ZOTERO_USER_ID', 'Zotero 用户 ID（本地 API）', '',
     'Zotero 本地 API 用；本机开着 Zotero 时填 0 也行'),
    ('ZOTERO_WEB_USER_ID', 'Zotero 用户 ID（写回用）', '',
     '写 zotero.org 用的**真实数字 id**（设置→账户里能看到）。'
     '留空则沿用上面那个 —— 但上面填 0 时写回必然失败'),
    ('ZOTERO_TEST_USER_ID', '测试账号的用户 ID', '',
     '只有机器角色=test 时才用：写回的目标必须是这个 id，否则直接拒绝。'
     '这条是「别把测试改动写进真实文献库」的执行点'),
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


def web_user_id():
    """写 zotero.org 时该用哪个用户 id。

    **本地 API 和 Web API 要的不是同一个东西**：本地 API 认 `0`，
    Web API 必须是真实数字 id。此前两者共用一个配置项 `ZOTERO_USER_ID`，
    于是编程端填 0 时「读得动、写必失败」，而失败原因看起来像鉴权问题
    —— 这个坑记了很久（见 docs/待办与需求.md）。现在拆开：
    没单独配就沿用旧值，行为与从前一致；配了就以它为准。
    """
    return get_site('ZOTERO_WEB_USER_ID') or get_site('ZOTERO_USER_ID')


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
    """保存配置。返回实际写入的键名列表。

    **密钥进系统凭据库，普通配置进 .env** —— 两者要求不同：
      - 密钥要保密，且不需要人去读 → 凭据库（加密、不落明文）
      - 模型/路径等要能被人看懂、跟着项目走 → .env（明文反而是优点）

    值为 None 或 '' 的键会被跳过（避免面板留空时误清空已有配置）。
    **永远不写源码** —— 源码内不含明文密钥这条底线不能破。
    """
    global _cache
    existing = _load_env_file()
    written = []
    plain = []            # 需要落 .env 的普通配置
    for k, v in (updates or {}).items():
        if v is None or str(v).strip() == '':
            continue
        v = str(v).strip()
        if k in SECRET_KEYS and _kr_set(k, v):
            written.append(k)
            existing.pop(k, None)      # 已进凭据库，把 .env 里的明文残留清掉
            continue
        existing[k] = v
        written.append(k)
        plain.append(k)
    if not written:
        return []
    _write_env(existing)
    return written


def _write_env(data):
    """把配置字典原子写回 .env（先备份，再临时文件替换）。

    原子替换的意义：写到一半断电/崩溃，也不会留下半截坏文件把配置搞丢。
    """
    global _cache
    if os.path.exists(ENV_FILE):
        import time
        # 备份要脱敏：直接 copy 会留下一份含明文密钥的文件在硬盘上，
        # 那正好抵消了「把密钥搬进凭据库」的意义（迁移那一刻反而多一份明文）。
        # 备份的目的是「改错了能还原配置」，密钥本身在凭据库里，不需要备份。
        try:
            old = _load_env_file()
            with open(ENV_FILE + f'.bak{time.strftime("%m%d%H%M%S")}', 'w',
                      encoding='utf-8') as bf:
                bf.write('# 配置备份（密钥已脱敏，仅用于还原非密配置）\n')
                for k in sorted(old):
                    bf.write(f'{k}=' + ('<已脱敏>' if k in SECRET_KEYS else old[k]) + '\n')
        except Exception:
            pass
    tmp = ENV_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write('# 由控制面板/程序写入。本文件已在 .gitignore，不进版本库。\n')
        f.write('# 密钥不在这里 —— 已存入系统凭据库（Windows 凭据管理器）。\n')
        for k in sorted(data):
            f.write(f'{k}={data[k]}\n')
    os.replace(tmp, ENV_FILE)
    _cache = None               # 让下次 get_key 重新读盘


def key_location(name):
    """某个密钥当前存在哪。面板据此提示用户是否还有明文残留。

    返回 '环境变量' / '系统凭据库' / '.env明文' / '未配置'
    """
    if os.environ.get(name):
        return '环境变量'
    if name in SECRET_KEYS and _kr_get(name):
        return '系统凭据库'
    global _cache
    if _cache is None:
        _cache = _load_env_file()
    return '.env明文' if _cache.get(name) else '未配置'


def _tail(v, n=4):
    """只露末 4 位 —— 够人分辨是不是同一把，又不泄露密钥。"""
    v = str(v or '')
    return v[-n:] if len(v) > n else '?' * len(v)


def env_shadow(name):
    """环境变量里是不是有一把**旧密钥，正盖着**你新填进凭据库的那把？

    这是 2026-08-28 咬人的那件事：加载顺序是「环境变量 → 凭据库 → .env」，
    用户在面板里填了新密钥（进了凭据库），可环境变量里还躺着一把作废的旧的，
    于是**新值被静默盖住**，跑什么都是 401，而面板一片正常。

    返回 None（没有环境变量）或 dict：
        env_tail    环境变量里那把的末 4 位（真正在生效的）
        stored_tail 凭据库里那把的末 4 位（''=凭据库里没有）
        differs     两者不是同一把 —— 这就是「新值被盖住」
    """
    env_v = os.environ.get(name)
    if not env_v:
        return None
    stored = _kr_get(name) if name in SECRET_KEYS else ''
    return {'env_tail': _tail(env_v), 'stored_tail': _tail(stored) if stored else '',
            'differs': bool(stored) and stored.strip() != env_v.strip()}


def _broadcast_env_change():
    """告诉全系统「环境变量变了」（WM_SETTINGCHANGE）。

    **少了这一步，删注册表等于没删**：`explorer.exe` 是所有双击出来的程序的父进程，
    它的环境是自己启动时拷贝的。不广播，它就一直用旧值，
    于是用户双击任何东西，拿到的都还是那把作废的密钥（2026-08-28 踩坑 #73）。
    注意广播只让**愿意重读的**进程更新（explorer 会），已经在跑的普通进程不受影响。
    """
    if os.name != 'nt':
        return
    try:
        import ctypes
        HWND_BROADCAST, WM_SETTINGCHANGE, SMTO_ABORTIFHUNG = 0xFFFF, 0x001A, 0x0002
        ctypes.windll.user32.SendMessageTimeoutW(
            HWND_BROADCAST, WM_SETTINGCHANGE, 0,
            ctypes.c_wchar_p('Environment'), SMTO_ABORTIFHUNG, 3000, None)
    except Exception:
        pass          # 广播失败不影响删除本身，只是要重登录才生效


def drop_stale_env(names=None, log=None):
    """**本进程内**丢掉那些「和凭据库对不上」的密钥环境变量。返回被丢掉的键名。

    为什么需要（2026-08-28 连栽两次）：加载顺序是「环境变量 → 凭据库 → .env」。
    用户在面板里填了新密钥（进凭据库）、也删了注册表里的旧环境变量，
    **但 explorer.exe 还揣着旧的**，于是他双击出来的每个程序都继承那份旧值 ——
    看起来一切正常，一调 API 就 401。

    这里只在**两边都有值且不一样**时丢弃环境变量那份：
    「临时用环境变量覆盖」这个正当用法（CI、调试）依然有效 ——
    只要凭据库里没存过那把密钥，就不会被动到。
    """
    dropped = []
    for name in (names or SECRET_KEYS):
        env_v = os.environ.get(name)
        if not env_v:
            continue
        stored = _kr_get(name)
        if stored and stored.strip() != env_v.strip():
            os.environ.pop(name, None)
            dropped.append(name)
            if log:
                log(f'  [用凭据库里的密钥] {name}：环境变量里那把（末位 {_tail(env_v)}）'
                    f'已作废，改用凭据库里的（末位 {_tail(stored)}）')
    return dropped


def clear_env_key(name):
    """删掉**用户级**环境变量 `name`，让凭据库里的新密钥重新生效。返回 (ok, 人话)。

    只删用户级（HKCU）。系统级（HKLM）要管理员且影响全机，只报告不擅自动。
    删完还要重启用到它的进程 —— 进程的环境变量是启动时拷贝的，删注册表不会追过去。
    """
    if os.name != 'nt':
        return False, '只在 Windows 上支持'
    import winreg
    removed = False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment', 0,
                            winreg.KEY_SET_VALUE | winreg.KEY_READ) as k:
            try:
                winreg.QueryValueEx(k, name)
            except FileNotFoundError:
                pass
            else:
                winreg.DeleteValue(k, name)
                removed = True
    except OSError as e:
        return False, f'删用户级环境变量失败：{e}'
    machine = False
    try:
        with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment') as k:
            try:
                winreg.QueryValueEx(k, name)
                machine = True
            except FileNotFoundError:
                pass
    except OSError:
        pass
    os.environ.pop(name, None)         # 当前进程立刻不再受它影响
    _broadcast_env_change()            # 让 explorer 等长驻进程重新读环境（否则双击出来的程序还是旧值）
    if not removed and not machine:
        return True, f'{name}：用户级环境变量本来就没有（可能只在某个窗口里临时设过）'
    msg = f'{name}：已删掉用户级环境变量' if removed else f'{name}：用户级没有'
    if machine:
        msg += '；⚠ 系统级（HKLM）还有一份，要用管理员权限删'
    return True, msg + '。用到它的服务要重启才会拿到新值'


def migrate_secrets_to_keyring():
    """把 .env 里的明文密钥搬进系统凭据库，并从 .env 中删除。

    返回 (搬走的键名列表, 说明)。凭据库不可用时不动任何东西 ——
    宁可保持现状，也不能把密钥搬到一个存不住的地方然后删掉原件。
    """
    ok, backend = keyring_status()
    if not ok:
        return [], f'系统凭据库{backend}，未做任何改动'
    env = _load_env_file()
    moved = []
    for k in SECRET_KEYS:
        v = (env.get(k) or '').strip()
        if not v:
            continue
        if not _kr_set(k, v):
            continue
        # 先确认真的能读出来，再删明文（顺序不能反）
        if _kr_get(k) == v:
            moved.append(k)
    if not moved:
        return [], '.env 里没有需要迁移的明文密钥'
    for k in moved:
        env.pop(k, None)
    _write_env(env)
    return moved, f'已迁移 {len(moved)} 个密钥到系统凭据库，并清除 .env 中的明文'


def mask(value):
    """脱敏显示密钥：只留后 4 位。面板展示用，避免密钥出现在截图/录屏里。"""
    if not value:
        return ''
    return ('*' * max(4, len(value) - 4)) + value[-4:]
