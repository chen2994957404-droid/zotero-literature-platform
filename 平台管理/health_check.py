# -*- coding: utf-8 -*-
"""一键健康检查：验证平台各环节是否正常。改动后跑这个，比逐个手测可靠。

覆盖分两档（见 docs/架构重构_v2总体设计.md 第五节）：
  离线档：包安装 → 离线测试 → 语法 → 静态检查        ← 必须永远全绿
  实测档：配置 → Zotero/Ollama → 公理件自测 → 数据 → 后台服务  ← 本机没配就会红，正常

用法: python 平台管理/health_check.py            两档都跑
      python 平台管理/health_check.py --offline  只跑离线档（改完代码先跑这个）
"""
import os, sys, ast, glob, json, urllib.request, subprocess

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
from core import paths
from core.paths import ROOT as _ROOT

from core.cli import flag

_NOWIN = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
ROOT = _ROOT
os.chdir(ROOT)

OK, WARN, FAIL = '[OK]  ', '[WARN]', '[FAIL]'
results = []

# 工作流文件夹 = 项目根下、含 .py 且不是积木层/数据/文档的目录。
# 自动发现而非写死清单：以后新增一条工作流线，体检自动纳入，不用改这里。
_SKIP_DIRS = paths.NON_WORKFLOW_DIRS


def workflow_dirs():
    return sorted(d for d in os.listdir('.')
                  if os.path.isdir(d) and d not in _SKIP_DIRS
                  and not d.startswith(('.', 'zotero_backup'))
                  and glob.glob(os.path.join(d, '*.py')))


def code_files():
    """所有需要检查的源码：各工作流文件夹 + 积木层。

    排除 `_tmp*` / `_t.py` 这类一次性临时脚本 —— 它们常由 PowerShell 生成（带 BOM），
    会让体检报语法错，制造与真实代码无关的噪声。
    **注意不能简单排除下划线开头**：`__init__.py` 正是积木的入口，必须检查。
    """
    def keep(f):
        b = os.path.basename(f)
        return not (b.startswith('_tmp') or b in ('_t.py', '_h.py', '_c.py', '_f.py'))

    files = []
    for _ring in paths.CODE_RINGS:                     # 四环的代码
        files += [f for f in glob.glob(_ring + '/**/*.py', recursive=True) if keep(f)]
    files = [f for f in files if keep(f)]
    for d in workflow_dirs():
        files += [f for f in glob.glob(os.path.join(d, '**', '*.py'), recursive=True)
                  if keep(f)]
    return files


def find_script(name):
    """按文件名在工作流各文件夹里找脚本，返回路径或 None。"""
    for d in workflow_dirs():
        p = os.path.join(d, name + '.py')
        if os.path.exists(p):
            return p
    return None


def check(name, fn):
    try:
        status, msg = fn()
    except Exception as e:
        status, msg = FAIL, f'{type(e).__name__}: {e}'
    results.append((status, name, msg))
    print(f'{status} {name}: {msg}', flush=True)


def c_syntax():
    files = code_files()
    bad = []
    for f in files:
        try:
            ast.parse(open(f, encoding='utf-8').read())
        except SyntaxError as e:
            bad.append(f'{os.path.basename(f)}:{e.lineno}')
    return (OK, f'{len(files)} 个文件语法通过') if not bad else (FAIL, f'语法错误 {bad}')


def c_undefined_names():
    """揪出「用了但没导入」的模块（踩坑 #39）。

    语法检查和运行时导入检查都发现不了这类问题：
    `re.sub(...)` 写在函数体里，语法完全合法，模块也能正常 import，
    **只有那个函数被真正调用时才炸** —— 用户在面板上点了检索才发现。

    做法：用 ast 收集每个文件里「导入了什么」和「用了哪些 模块.属性」，
    对常见标准库名做交叉核对。简单但足以覆盖这一整类事故。
    """
    COMMON = {'re', 'os', 'sys', 'json', 'io', 'time', 'math', 'glob', 'shutil',
              'random', 'hashlib', 'base64', 'zipfile', 'sqlite3', 'threading',
              'subprocess', 'datetime', 'itertools', 'collections', 'traceback',
              'urllib', 'csv', 'tempfile', 'pathlib', 'textwrap'}
    bad = []
    for f in code_files():
        try:
            tree = ast.parse(open(f, encoding='utf-8').read())
        except SyntaxError:
            continue
        imported, used = set(), {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    imported.add((a.asname or a.name).split('.')[0])
            elif isinstance(node, ast.ImportFrom):
                for a in node.names:
                    imported.add(a.asname or a.name)
                if node.module:
                    imported.add(node.module.split('.')[0])
            elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                used.setdefault(node.value.id, node.lineno)
        for name, line in used.items():
            if name in COMMON and name not in imported:
                bad.append(f'{os.path.basename(f)}:{line} 用了 {name} 但没导入')
    return (OK, '没有「用了但没导入」的模块') if not bad else (FAIL, f'{bad[:5]}')


def c_no_secrets():
    """确保源码里没有明文密钥（安全底线）。"""
    import re
    pat = re.compile(r"(sk-[a-zA-Z0-9]{24,}|['\"][A-Za-z0-9]{24}['\"]\s*#?\s*zotero)", re.I)
    hits = []
    for f in code_files() + glob.glob('*.bat') + glob.glob('wf_backup/*.json'):
        try:
            s = open(f, encoding='utf-8', errors='replace').read()
        except Exception:
            continue
        if pat.search(s):
            hits.append(os.path.basename(f))
    return (OK, '源码无明文密钥') if not hits else (FAIL, f'发现明文密钥: {hits}')


def c_no_popup():
    """揪出会弹控制台窗口的子进程调用（踩坑 #31）。

    Windows 上 subprocess 默认会弹窗。面板每 15 秒、看门狗每 60 秒各查一次进程，
    没加静默标志就会不停闪蓝色窗口打扰用户。
    正确做法：走 core.subproc，或显式带 creationflags。
    **这一项是防复发的关键** —— 光修好现有的 17 处不够，得让以后写错立刻被发现。
    """
    import re
    call = re.compile(r'subprocess\.(run|Popen)\s*\(')
    bad = []
    for f in code_files():
        np = os.path.normpath(f)
        if np.startswith('core' + os.sep + 'subproc'):
            continue                       # 积木自己就是正确实现，豁免
        if np.startswith('归档'):
            continue                       # 归档的旧代码不再运行，不必整改
        try:
            src = open(f, encoding='utf-8', errors='replace').read()
        except Exception:
            continue
        for m in call.finditer(src):
            # 取该调用之后的一小段，看有没有静默标志
            seg = src[m.start():m.start() + 600]
            if 'creationflags' not in seg:
                line = src[:m.start()].count('\n') + 1
                bad.append(f'{os.path.basename(f)}:{line}')
    if bad:
        return WARN, f'{len(bad)} 处子进程调用可能弹窗（改用 core.subproc）: {bad[:6]}'
    return OK, '所有子进程调用都不会弹窗'


def c_secret_storage():
    """密钥存放方式：是否已进系统凭据库、硬盘上是否还有明文残留。

    体检的既有一项只查「源码里有没有密钥」，但密钥也可能明文躺在
    .env / .env.bak / 各种临时文件里 —— 那同样是泄露面。
    """
    from core.config import keyring_status, key_location, SECRET_KEYS
    ok, backend = keyring_status()
    plain = [k for k in SECRET_KEYS if key_location(k) == '.env明文']
    # 含明文密钥的残留文件（备份、临时文件）
    import re
    pat = re.compile(r'^(DEEPSEEK_KEY|ZOTERO_API_KEY|MINERU_TOKEN|SILICONFLOW_KEY)=(.{8,})$', re.M)
    leftovers = []
    for f in glob.glob('.env.bak*') + glob.glob('.env.tmp') + glob.glob('*.env'):
        try:
            if pat.search(open(f, encoding='utf-8', errors='replace').read()):
                leftovers.append(os.path.basename(f))
        except Exception:
            continue
    if not ok:
        return WARN, f'系统凭据库{backend}；密钥只能明文存放'
    if plain:
        return WARN, f'{len(plain)} 个密钥仍是明文（控制面板可一键迁移）: {plain}'
    if leftovers:
        return WARN, f'有含明文密钥的残留文件，建议删除: {leftovers[:5]}'
    # ⚠ 这里必须查「到底存进去了几个」（踩坑 #45）。
    # 原来只查了「凭据库可用」+「硬盘无明文」，一个密钥都没配时两条也都成立，
    # 于是空仓库被报成「密钥已存入系统凭据库」——换机器时看到绿灯以为配好了。
    # 没有密钥当然没有明文残留：这种「因为空所以合格」的结论必须挡掉。
    stored = [k for k in SECRET_KEYS if key_location(k) == '系统凭据库']
    unset = [k for k in SECRET_KEYS if key_location(k) == '未配置']
    if not stored:
        return WARN, (f'凭据库可用（{backend}），但一个密钥都没存 —— '
                      f'{len(unset)} 个待填，请在控制面板里配置')
    tail = f'；另有 {len(unset)} 个未配置 {unset}' if unset else ''
    return OK, f'{len(stored)} 个密钥在系统凭据库（{backend}），硬盘无明文残留{tail}'


def c_hardcoded():
    """守住红线 #3：配置与地址一律走 core/config，不许 hardcode。

    为什么要有这一项：2026-08-23 的「36 个脚本框架化」漏了 5 个文件，
    但体检全绿 —— 因为当时根本没有任何一项在查硬编码。
    红线写在文档里而没有检查项守着，等于没写。
    """
    import re
    # 这些值都已经在 core/config 的 SITE_SETTINGS 里可配，源码里不该再出现
    PATS = [(re.compile(r'localhost:23119'), 'ZOTERO_API_HOST'),
            (re.compile(r'localhost:11434'), 'OLLAMA_HOST')]
    bad = []
    for f in code_files():
        n = os.path.normpath(f)
        # config 自己要写默认值；归档是废弃代码；本文件里就写着要查的模式串本身（自匹配）
        if ('modules' + os.sep + 'config' in n or '归档_旧版本' in n
                or os.path.basename(n) == 'health_check.py'):
            continue
        try:
            src = open(f, encoding='utf-8', errors='replace').read()
        except Exception:
            continue
        # 已经在向 config 要这个设置的文件就放过：它里面的字面量是
        # 「config 取不到时的兜底默认值」或文档示例，那是积木能被单独拷走用的前提，
        # 不是漏掉的硬编码。判据放在文件粒度 —— 宁可漏报也不要天天误报到没人看。
        consults_config = ('get_site' in src or '_cfg_site' in src or '_gsite' in src)
        if consults_config:
            continue
        for pat, setting in PATS:
            if pat.search(src):
                bad.append(f'{f} → 应走 get_site({setting!r})')
    return (OK, '没有硬编码的地址，配置都走 core/config') if not bad         else (FAIL, f'{len(bad)} 处硬编码: {bad[:4]}')


def c_config():
    from core.config import get_key
    missing = [k for k in ('DEEPSEEK_KEY', 'ZOTERO_API_KEY', 'MINERU_TOKEN') if not get_key(k)]
    return (OK, '三个密钥都能读到') if not missing else (FAIL, f'缺少: {missing}')


def c_zotero():
    try:
        from core.config import get_site
        uid = get_site('ZOTERO_USER_ID')
        host = get_site('ZOTERO_API_HOST')
        if not uid:
            return WARN, '未配置 ZOTERO_USER_ID（控制面板里可填）'
        urllib.request.urlopen(urllib.request.Request(
            f'{host}/api/users/{uid}/items/top?limit=1',
            headers={'Zotero-Allowed-Request': 'true'}), timeout=6)
        return OK, 'Zotero 本地 API 通'
    except Exception:
        return WARN, 'Zotero 未开（精读/抽取/找文献会失败）'


def c_ollama():
    try:
        r = json.loads(urllib.request.urlopen('http://localhost:11434/api/tags', timeout=6).read())
        n = len(r.get('models', []))
        return (OK, f'Ollama 通，{n} 个模型') if n else (WARN, 'Ollama 通但模型列表为空（OLLAMA_MODELS 路径问题）')
    except Exception:
        return WARN, 'Ollama 未跑（问答/向量化会失败）'


# 慢自测（调大模型/网络）默认跳过，加 --full 才跑
SLOW_TESTS = {'chart_digitize'}


def c_modules():
    """跑各公理件的 selftest（每个限时 60s，避免单个卡死整个检查）。"""
    full = flag('--full')
    mods = [d for _r, _n, d in paths.block_dirs()
            if os.path.exists(os.path.join(d, 'selftest.py'))]
    passed, failed, skipped = [], [], []
    for m in mods:
        name = os.path.basename(m.rstrip('/\\'))
        if name in SLOW_TESTS and not full:
            skipped.append(name); continue
        try:
            r = subprocess.run([sys.executable, os.path.join(m, 'selftest.py')],
                               capture_output=True, text=True, encoding='utf-8',
                               errors='replace', timeout=60, creationflags=_NOWIN)
            (passed if r.returncode == 0 else failed).append(name)
        except subprocess.TimeoutExpired:
            failed.append(f'{name}(超时)')
    total = len(paths.block_dirs())
    msg = f'{len(passed)}/{len(mods)-len(skipped)} 自测通过（共 {total} 个公理件）'
    if skipped:
        msg += f'；跳过慢测试 {skipped}（--full 可跑）'
    if failed:
        return WARN, msg + f'；失败: {failed}'
    return OK, msg


def c_importable():
    """运行时导入检查——语法检查发现不了 NameError/ImportError（踩坑 #24）。"""
    import importlib.util
    key_scripts = ['zotero_watcher', 'si_deepread', 'extract_structured', 'ask',
                   'mineru_parse', 'deepread_batch', 'merge_summary']
    bad = []
    missing = []
    for name in key_scripts:
        p = find_script(name)
        if not p:
            missing.append(name)      # 关键脚本找不到 = 重组时漏搬了，必须报出来
            continue
        # 用子进程 import，避免脚本执行副作用影响本进程
        r = subprocess.run(
            [sys.executable, '-c',
             f"import sys; sys.path.insert(0, r'{os.path.dirname(p)}'); sys.path.insert(0,'.'); "
             f"import importlib.util as u; "
             f"spec=u.spec_from_file_location('_m', r'{p}'); m=u.module_from_spec(spec); "
             f"sys.argv=['x','a','b']; "
             f"exec(compile(open(r'{p}',encoding='utf-8').read().split('if __name__')[0], r'{p}', 'exec'), m.__dict__)"],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=60, creationflags=_NOWIN)
        err = r.stderr or ''
        if 'NameError' in err or 'ImportError' in err or 'ModuleNotFoundError' in err:
            first = [l for l in err.splitlines() if 'Error' in l]
            bad.append(f'{name}({first[-1][:60] if first else "err"})')
    if missing:
        return FAIL, f'关键脚本找不到（可能重组时漏搬）: {missing}'
    # 检查工具不该有副作用：加载脚本时若在项目根凭空造出目录，说明该脚本
    # 把有副作用的代码写在了模块顶层（踩坑 #34：曾每跑一次体检就生成一个 'b' 文件夹）
    junk = [d for d in ('a', 'b', 'x') if os.path.isdir(d)]
    for d in junk:
        try:
            os.rmdir(d)          # 只删空目录，非空不动
        except OSError:
            pass
    if junk:
        return WARN, (f'加载脚本时产生了垃圾目录 {junk}（已清理）。'
                      f'说明有脚本把副作用写在模块顶层，应移进 main()')
    return (OK, f'{len(key_scripts)} 个关键脚本可正常加载') if not bad else (FAIL, f'加载失败: {bad}')


def c_no_selftest():
    """哪些公理件还缺自测（文档声称每个都有）。"""
    lack = [n for _r, n, d in paths.block_dirs()
            if not os.path.exists(os.path.join(d, 'selftest.py'))]
    return (OK, '所有公理件都有自测') if not lack else (WARN, f'缺自测: {lack}')


def c_data():
    n_lib = len([d for d in glob.glob(os.path.join(paths.LIBRARY, '*') + os.sep) if os.path.isdir(d)])
    n_struct = len(glob.glob(os.path.join(paths.STRUCTURED, '*.json')))
    vdb = os.path.exists(paths.VECTOR_DB)
    msg = f'library {n_lib} 篇 / structured {n_struct} 条 / 向量库{"在" if vdb else "缺失"}'
    from core import role
    if role.is_test():
        # 测试端有自己的 Zotero 账号，数据是它自己跑出来的 —— 不用从主力机拷
        if n_lib == 0:
            return WARN, msg + ' —— 测试端还没有产物；在测试 Zotero 库里打「待处理」跑一篇即可'
        return OK, msg + f'（测试端，自产 {n_lib} 篇；与主力机的权威数据互不相干）'
    if role.is_dev():
        # 编程端的权威数据在主力机，这里只需要够做回归测试的金样本（2~3 篇）
        if n_lib == 0:
            return WARN, msg + ' —— 编程端没有金样本，纯逻辑改动无法做回归验证；'                                '建议从主力机拷 2~3 篇的 parsed/ 过来'
        return OK, msg + f'（编程端，金样本 {n_lib} 篇；权威数据在主力机）'
    return OK, msg


def c_services():
    """四个自启任务在不在。**只对运行端有意义** —— 编程端/测试端都不该注册它们。

    测试端可以**手动**起 watcher 做端到端验证（`精读监听.bat`），
    但不注册自启任务：那会让它跟着开机长跑，白烧 API 额度。
    """
    from core import role
    if not role.is_prod():
        return OK, f'{role.label()}不注册自启任务（常驻服务只在主力机跑），跳过检查'
    try:
        from core.subproc import powershell
        out = powershell(
            "Get-ScheduledTask | Where-Object {$_.TaskName -in "
            "@('ZoteroLiteratureWatcher','OllamaService','ZoteroApp','LiteratureAutoSync')} "
            "| Select-Object -ExpandProperty TaskName", timeout=30)
        tasks = [t.strip() for t in out.splitlines() if t.strip()]
        want = {'ZoteroLiteratureWatcher', 'OllamaService', 'ZoteroApp', 'LiteratureAutoSync'}
        miss = want - set(tasks)
        return (OK, f'{len(tasks)} 个自启任务在') if not miss else (WARN, f'缺任务: {miss}')
    except Exception as e:
        return WARN, f'无法查询任务计划: {e}'



# ══════════════════════════════════════════════════════════════════════
# 离线档：不依赖任何外部服务，永远应该全绿（见 docs/架构重构_v2总体设计.md 第五节）
# ══════════════════════════════════════════════════════════════════════
def c_role():
    """本机角色配没配、配的是什么。见 docs/两台机器的分工.md。

    这一项排在很前面，因为它决定了后面几项该不该报警：
    编程端本来就不该有自启任务、不该有全库数据，那些黄灯是噪音不是问题。
    """
    from core import role
    r, lab = role.current(), role.label()
    if not role.is_configured():
        return WARN, (f'没设置机器角色，按最安全的 {r}（{lab}）处理。'
                      f'请在控制面板「本机设置」里选「机器角色」：'
                      f'dev（编程端）/ prod（运行端·主力机）/ test（编程端接测试 Zotero 账号）')
    if r == role.PROD:
        return OK, f'{lab} —— 允许写 Zotero、跑常驻服务、跑全库作业'
    if r == role.TEST:
        # 对测试端来说，「指着哪个库」比「角色写着什么」重要得多，所以直接体检它
        if role.test_library_ok():
            return OK, f'{lab} —— 允许写，且已确认写回目标是测试库'
        return FAIL, (f'{lab}，但**写回目标不是测试库** —— 现在任何写操作都会被拒绝。'
                      f'请在控制面板把「Zotero 用户 ID（写回用）」和'
                      f'「测试账号的用户 ID」填成同一个值（测试账号的数字 id）')
    return OK, f'{lab} —— 已禁止写 Zotero / 跑 watcher / 跑全库作业（保护真实文献库）'


def c_installed():
    """项目是否已装成 Python 包 —— 现在所有 import 都依赖这一步。"""
    try:
        import importlib.metadata as md
        ver = md.version('zotero-literature-platform')
    except Exception:
        return FAIL, ('项目没装成包！所有脚本的 import 都会失败。'
                      '修复：在项目根目录跑  pip install -e . --no-deps')
    # 装了，但可能指向别的目录（换过盘符/复制过项目）
    import core.paths as _cp
    if os.path.normcase(_cp.ROOT) != os.path.normcase(ROOT):
        return FAIL, f'装的是另一份代码：{_cp.ROOT}，当前在 {ROOT}。重跑 pip install -e . --no-deps'
    return OK, f'已装成包 v{ver}，import 无需 sys.path 补丁'


def c_offline_tests():
    """离线测试必须全绿 —— 这是整个安全网的核心指标。"""
    try:
        import pytest  # noqa: F401
    except ImportError:
        return WARN, '没装 pytest，离线测试跑不了：pip install "pytest>=8.0"'
    r = subprocess.run([sys.executable, '-m', 'pytest', '-q', '--no-header'],
                       capture_output=True, text=True, encoding='utf-8',
                       errors='replace', cwd=ROOT, timeout=300,
                       creationflags=_NOWIN)
    tail = [ln for ln in (r.stdout or '').strip().splitlines() if ln.strip()]
    summary = tail[-1][:120] if tail else '(无输出)'
    if r.returncode == 0:
        return OK, f'离线测试全绿：{summary}'
    return FAIL, f'离线测试有红的（结构被改坏了）：{summary}'


if __name__ == '__main__':
    offline = flag('--offline')     # 只跑不依赖外部服务的检查
    print('=== 平台健康检查%s ===\n' % ('（离线档）' if offline else ''), flush=True)
    check('机器角色', c_role)
    check('包安装', c_installed)
    check('离线测试', c_offline_tests)
    check('语法', c_syntax)
    check('未导入的模块', c_undefined_names)
    check('密钥安全', c_no_secrets)
    check('无弹窗', c_no_popup)
    if not offline:
        check('密钥存放', c_secret_storage)
    check('配置硬编码', c_hardcoded)
    check('自测覆盖', c_no_selftest)
    check('运行时导入', c_importable)

    # ── 实测档：需要真实服务/密钥/数据，本机没配就会红，属正常 ──
    if not offline:
        check('配置加载', c_config)
        check('Zotero 服务', c_zotero)
        check('Ollama 服务', c_ollama)
        check('公理件自测', c_modules)
        check('数据资产', c_data)
        check('后台服务', c_services)

    nf = sum(1 for s, _, _ in results if s == FAIL)
    nw = sum(1 for s, _, _ in results if s == WARN)
    print(f'\n=== 结果：{len(results)-nf-nw} 通过，{nw} 警告，{nf} 失败 ===')
    sys.exit(1 if nf else 0)
