# -*- coding: utf-8 -*-
"""一键健康检查：验证平台各环节是否正常。改动后跑这个，比逐个手测可靠。

覆盖：语法 → 配置 → 依赖服务 → 公理件自测 → 数据资产 → 后台服务
用法: python scripts/health_check.py
"""
import os, sys, ast, glob, json, urllib.request, subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

OK, WARN, FAIL = '[OK]  ', '[WARN]', '[FAIL]'
results = []


def check(name, fn):
    try:
        status, msg = fn()
    except Exception as e:
        status, msg = FAIL, f'{type(e).__name__}: {e}'
    results.append((status, name, msg))
    print(f'{status} {name}: {msg}', flush=True)


def c_syntax():
    files = glob.glob('scripts/**/*.py', recursive=True) + glob.glob('modules/**/*.py', recursive=True)
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
    for f in glob.glob('scripts/**/*.py', recursive=True) + glob.glob('modules/**/*.py', recursive=True) \
            + glob.glob('*.bat') + glob.glob('wf_backup/*.json'):
        try:
            s = open(f, encoding='utf-8', errors='replace').read()
        except Exception:
            continue
        if pat.search(s):
            hits.append(os.path.basename(f))
    return (OK, '源码无明文密钥') if not hits else (FAIL, f'发现明文密钥: {hits}')


def c_config():
    from modules.config import get_key
    missing = [k for k in ('DEEPSEEK_KEY', 'ZOTERO_API_KEY', 'MINERU_TOKEN') if not get_key(k)]
    return (OK, '三个密钥都能读到') if not missing else (FAIL, f'缺少: {missing}')


def c_zotero():
    try:
        urllib.request.urlopen(urllib.request.Request(
            'http://localhost:23119/api/users/16078117/items/top?limit=1',
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
                               errors='replace', timeout=60)
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
        out = subprocess.run(['powershell', '-Command',
                              "Get-ScheduledTask | Where-Object {$_.TaskName -in @('ZoteroLiteratureWatcher','OllamaService','ZoteroApp','LiteratureAutoSync')} | Select-Object -ExpandProperty TaskName"],
                             capture_output=True, text=True, timeout=30).stdout
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
    check('配置加载', c_config)
    check('Zotero 服务', c_zotero)
    check('Ollama 服务', c_ollama)
    check('公理件自测', c_modules)
    check('自测覆盖', c_no_selftest)
    check('数据资产', c_data)
    check('后台服务', c_services)

    nf = sum(1 for s, _, _ in results if s == FAIL)
    nw = sum(1 for s, _, _ in results if s == WARN)
    print(f'\n=== 结果：{len(results)-nf-nw} 通过，{nw} 警告，{nf} 失败 ===')
    sys.exit(1 if nf else 0)
