# -*- coding: utf-8 -*-
"""架构守卫 —— 把架构宪法里「说了但没人执行」的规则，变成会变红的测试。

宪法铁律 2 写着「严格单向依赖，永不循环」，但在此之前**没有任何机制阻止违反它**。
数据契约写着「路径稳定」，但路径在 53 处被手工拼装，随时可能被违反而无人发现。

这个文件就是那两条规则的执行者。它不测功能，只测**结构**。

见 docs/架构重构_v2总体设计.md 第一节、第三节 B。
"""
import os
import re
import pytest

from core import paths

ROOT = paths.ROOT

# 不扫描的目录：数据、历史存档、构建产物
SKIP_DIRS = {'workflow_data', '.git', '__pycache__', '归档_旧版本',
             '.venv', 'venv', 'build', 'dist', '.pytest_cache',
             'zotero_literature_platform.egg-info'}

# 单行豁免标记：确实需要写这个字符串（例如遍历时排除数据目录）的地方，
# 在行尾加 `# paths-exempt` 并说明理由。刻意做成显眼的，让豁免难以泛滥。
EXEMPT = '# paths-exempt'


def _py_files():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn.endswith('.py'):
                yield os.path.join(dirpath, fn)


def _rel(p):
    return os.path.relpath(p, ROOT).replace('\\', '/')


# ══════════════════════════════════════════════════════════════════════
# 守卫一：数据契约只有一个实现
# ══════════════════════════════════════════════════════════════════════
# 允许直接写 'workflow_data' 字面量的文件（数据契约的实现处 + 它的测试）
PATHS_OWNERS = {'core/paths.py', 'tests/test_architecture.py', 'tests/test_core_paths.py'}

# 「这一行在拼路径」的特征
_PATH_BUILDING = ('os.path.join', 'glob', 'open(', 'os.makedirs',
                  'os.path.exists', 'os.listdir', 'os.path.isdir', 'os.path.isfile')


def test_数据目录路径只在core_paths里拼装():
    """除 core/paths.py 外，谁都不许自己拼 workflow_data 的路径。

    为什么：路径散落各处 = 数据契约无法被保证。改一次目录布局要改几十处，
    漏一处就是一个只在运行时才暴露的 bug。
    """
    offenders = []
    for f in _py_files():
        rel = _rel(f)
        if rel in PATHS_OWNERS:
            continue
        for i, line in enumerate(open(f, encoding='utf-8', errors='replace'), 1):
            if 'workflow_data' not in line or EXEMPT in line:
                continue
            # 只揪「真的在拼路径」的行。散文里提一句目录名（文档字符串、
            # 遍历时排除数据目录的集合字面量）不算违规，也没法在那儿加注释豁免。
            if any(t in line for t in _PATH_BUILDING):
                offenders.append(f'{rel}:{i}: {line.strip()[:90]}')
    assert not offenders, (
        '这些地方在自己拼数据目录路径，应改用 core.paths：\n  '
        + '\n  '.join(offenders)
        + '\n（确有必要的，行尾加 "# paths-exempt" 并写明理由）')


# ══════════════════════════════════════════════════════════════════════
# 守卫二：依赖只能从上往下（宪法铁律 2）
# ══════════════════════════════════════════════════════════════════════
# 环的层级，数字越小越底层。上层可以 import 下层，反之绝对不行。
RINGS = {'core': 0, 'domain': 1, 'adapters': 1, 'pipelines': 2, 'apps': 3}

# domain 是「纯逻辑环」：只依赖 core，连同层的 adapters 也不许碰
# （因为 adapters 会联网，domain 一旦依赖它就没法离线测试了）
EXTRA_FORBIDDEN = {'domain': {'adapters'}}

_IMPORT_RE = re.compile(r'^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))', re.M)


def _ring_of(rel_path):
    top = rel_path.split('/')[0]
    return top if top in RINGS else None


def test_依赖方向不许反向():
    """core 不许 import domain/adapters/pipelines/apps，以此类推。"""
    violations = []
    for f in _py_files():
        rel = _rel(f)
        ring = _ring_of(rel)
        if ring is None:
            continue
        src = open(f, encoding='utf-8', errors='replace').read()
        for m in _IMPORT_RE.finditer(src):
            mod = (m.group(1) or m.group(2) or '').split('.')[0]
            if mod not in RINGS:
                continue
            bad = RINGS[mod] > RINGS[ring] or mod in EXTRA_FORBIDDEN.get(ring, ())
            if bad:
                violations.append(f'{rel}: 「{ring}」环 import 了「{mod}」环')
    assert not violations, (
        '依赖方向反了（违反架构宪法铁律 2）：\n  ' + '\n  '.join(sorted(set(violations))))


def test_纯逻辑环不许联网也不许碰硬盘():
    """domain/ 里出现网络或文件 I/O，就说明它放错环了，应该搬去 adapters。

    这条保证 domain 永远可以离线、毫秒级地测试 —— 那是整个安全网的地基。
    """
    FORBIDDEN = ['urllib.request', 'requests', 'httpx', 'socket',
                 'chromadb', 'subprocess']
    domain_dir = os.path.join(ROOT, 'domain')
    if not os.path.isdir(domain_dir):
        pytest.skip('domain 环尚未建立（重构阶段 2）')
    offenders = []
    for f in _py_files():
        rel = _rel(f)
        if not rel.startswith('domain/'):
            continue
        src = open(f, encoding='utf-8', errors='replace').read()
        for bad in FORBIDDEN:
            if re.search(r'^\s*(from|import)\s+' + re.escape(bad), src, re.M):
                offenders.append(f'{rel}: 用了 {bad}')
    assert not offenders, (
        'domain 是纯逻辑环，不许有 I/O：\n  ' + '\n  '.join(offenders))


# ══════════════════════════════════════════════════════════════════════
# 守卫三：项目已经是 Python 包，不该再有 sys.path 补丁
# ══════════════════════════════════════════════════════════════════════
# 允许保留的：为「同目录兄弟脚本 import」而做的插入（阶段 4 迁入 pipelines 后消失）
def test_不再有塞项目根到sys_path的补丁():
    """`pip install -e .` 之后，import 不需要任何补丁。

    残留的补丁会掩盖「其实没装好」的问题，让故障延后暴露、更难定位。
    """
    offenders = []
    pat = re.compile(r'sys\.path\.insert\([^)]*\)')
    for f in _py_files():
        rel = _rel(f)
        if rel.startswith('tests/'):
            continue
        for i, line in enumerate(open(f, encoding='utf-8', errors='replace'), 1):
            m = pat.search(line)
            if not m or EXEMPT in line:
                continue
            arg = m.group(0)
            # 指向项目根的写法：走查 _ROOT / 三层 dirname / ROOT 变量
            if ('_ROOT' in arg or re.search(r'dirname\(.*dirname\(.*dirname\(', arg)
                    or re.search(r'\bROOT\b', arg)):
                offenders.append(f'{rel}:{i}: {line.strip()[:90]}')
    assert not offenders, (
        '这些地方还在往 sys.path 塞项目根，装成包之后不需要了：\n  '
        + '\n  '.join(offenders))
