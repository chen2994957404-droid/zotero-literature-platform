# -*- coding: utf-8 -*-
"""一键健康检查：验证平台各环节是否正常。改动后跑这个，比逐个手测可靠。

覆盖：语法 → 配置 → 依赖服务 → 公理件自测 → 数据资产 → 后台服务
用法: python 平台管理/health_check.py
"""
import os, sys, ast, glob, json, urllib.request, subprocess
_NOWIN = getattr(__import__('subprocess'), 'CREATE_NO_WINDOW', 0) if __import__('os').name == 'nt' else 0

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

OK, WARN, FAIL = '[OK]  ', '[WARN]', '[FAIL]'
results = []

# 工作流文件夹 = 项目根下、含 .py 且不是积木层/数据/文档的目录。
# 自动发现而非写死清单：以后新增一条工作流线，体检自动纳入，不用改这里。
_SKIP_DIRS = {'modules', 'docs', 'workflow_data', 'n8n_data', 'wf_backup',
              '__pycache__', '.git', 'b'}


def workflow_dirs():
    return sorted(d for d in os.listdir('.')
                  if os.path.isdir(d) and d not in _SKIP_DIRS
                  and not d.startswith(('.', 'zotero_backup'))
                  and glob.glob(os.path.join(d, '*.py')))


def code_files():
    """所有需要检查的源码：各工作流文件夹 + 积木层。"""
    files = glob.glob('modules/**/*.py', recursive=True)
    for d in workflow_dirs():
        files += glob.glob(os.path.join(d, '**', '*.py'), recursive=True)
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
    正确做法：走 modules.subproc，或显式带 creationflags。
    **这一项是防复发的关键** —— 光修好现有的 17 处不够，得让以后写错立刻被发现。
    """
    import re
    call = re.compile(r'subprocess\.(run|Popen)\s*\(')
    bad = []
    for f in code_files():
        np = os.path.normpath(f)
        if np.startswith('modules' + os.sep + 'subproc'):
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
        return WARN, f'{len(bad)} 处子进程调用可能弹窗（改用 modules.subproc）: {bad[:6]}'
    return OK, '所有子进程调用都不会弹窗'


def c_secret_storage():
    """密钥存放方式：是否已进系统凭据库、硬盘上是否还有明文残留。

    体检的既有一项只查「源码里有没有密钥」，但密钥也可能明文躺在
    .env / .env.bak / 各种临时文件里 —— 那同样是泄露面。
    """
    from modules.config import keyring_status, key_location, SECRET_KEYS
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
    return OK, f'密钥已存入系统凭据库（{backend}），硬盘无明文残留'


def c_config():
    from modules.config import get_key
    missing = [k for k in ('DEEPSEEK_KEY', 'ZOTERO_API_KEY', 'MINERU_TOKEN') if not get_key(k)]
    return (OK, '三个密钥都能读到') if not missing else (FAIL, f'缺少: {missing}')


def c_zotero():
    try:
        from modules.config import get_site
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
    full = '--full' in sys.argv
    mods = [d for d in glob.glob('modules/*/') if os.path.exists(os.path.join(d, 'selftest.py'))]
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
    total = len(glob.glob('modules/*/__init__.py'))
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
    return (OK, f'{len(key_scripts)} 个关键脚本可正常加载') if not bad else (FAIL, f'加载失败: {bad}')


def c_no_selftest():
    """哪些公理件还缺自测（文档声称每个都有）。"""
    lack = [os.path.basename(os.path.dirname(f)) for f in glob.glob('modules/*/__init__.py')
            if not os.path.exists(os.path.join(os.path.dirname(f), 'selftest.py'))]
    return (OK, '所有公理件都有自测') if not lack else (WARN, f'缺自测: {lack}')


def c_data():
    n_lib = len([d for d in glob.glob('workflow_data/library/*/') if os.path.isdir(d)])
    n_struct = len(glob.glob('workflow_data/structured/*.json'))
    vdb = os.path.exists('workflow_data/vector_db')
    return OK, f'library {n_lib} 篇 / structured {n_struct} 条 / 向量库{"在" if vdb else "缺失"}'


def c_services():
    try:
        from modules.subproc import powershell
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


if __name__ == '__main__':
    print('=== 平台健康检查 ===\n', flush=True)
    check('语法', c_syntax)
    check('密钥安全', c_no_secrets)
    check('无弹窗', c_no_popup)
    check('密钥存放', c_secret_storage)
    check('配置加载', c_config)
    check('Zotero 服务', c_zotero)
    check('Ollama 服务', c_ollama)
    check('运行时导入', c_importable)
    check('公理件自测', c_modules)
    check('自测覆盖', c_no_selftest)
    check('数据资产', c_data)
    check('后台服务', c_services)

    nf = sum(1 for s, _, _ in results if s == FAIL)
    nw = sum(1 for s, _, _ in results if s == WARN)
    print(f'\n=== 结果：{len(results)-nf-nw} 通过，{nw} 警告，{nf} 失败 ===')
    sys.exit(1 if nf else 0)
