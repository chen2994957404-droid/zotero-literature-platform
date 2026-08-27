# -*- coding: utf-8 -*-
"""架构守卫 —— 把架构宪法里「说了但没人执行」的规则，变成会变红的测试。

宪法铁律 2 写着「严格单向依赖，永不循环」，但在此之前**没有任何机制阻止违反它**。
数据契约写着「路径稳定」，但路径在 53 处被手工拼装，随时可能被违反而无人发现。

这个文件就是那两条规则的执行者。它不测功能，只测**结构**。

见 docs/架构重构_v2总体设计.md 第一节、第三节 B。
"""
import ast
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

# 报错信息里的换行 + 缩进（写成常量，避免转义在各种工具链里被吃掉）
_NL = chr(10) + '  '


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


# 联网 / 外部服务客户端：只有 adapters 环可以碰
_NETWORK = ['urllib.request', 'urllib.error', 'requests', 'httpx', 'socket',
            'http.client', 'aiohttp']
_EXTERNAL = ['chromadb', 'keyring']


def _imports_of(path):
    """这个文件顶层 import 了哪些模块（含 from X import 的 X）。"""
    src = open(path, encoding='utf-8', errors='replace').read()
    try:
        tree = ast.parse(src, path)
    except SyntaxError:
        return set()
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods.update(a.name for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module:
            mods.add(n.module)
    return mods


def _ring_files(ring):
    for f in _py_files():
        rel = _rel(f)
        if rel.startswith(ring + '/'):
            yield rel, f


def test_只有adapters环可以联网():
    """这条是「换掉 MineRU 只需改一个文件」的**全部保证**。

    如果 pipelines 或 domain 也能直接发 HTTP 请求，那个承诺当场作废 ——
    换外部服务时就得满仓库找 urlopen。重构前 `pipelines/paper_discovery`
    正是这样：编排层里直接写着 OpenAlex 的 URL 和 urlopen。
    """
    offenders = []
    for ring in ('core', 'domain', 'pipelines'):
        for rel, f in _ring_files(ring):
            if rel.endswith('/selftest.py'):
                continue          # 自测里允许直接探活外部服务
            hit = _imports_of(f) & set(_NETWORK)
            if hit:
                offenders.append(f'{rel}: 「{ring}」环直接联网（{sorted(hit)}）')
    assert not offenders, (
        '只有 adapters 环可以联网，其余环必须通过适配器：' + _NL
        + _NL.join(sorted(offenders))
        + _NL + '做法：把这次外部调用包成 adapters/<服务名>，本环只调它。')


def test_只有adapters环可以用外部服务客户端():
    """chromadb / keyring 这类第三方客户端同理，只许出现在 adapters。"""
    offenders = []
    for ring in ('domain', 'pipelines'):
        for rel, f in _ring_files(ring):
            if rel.endswith('/selftest.py'):
                continue
            hit = _imports_of(f) & set(_EXTERNAL)
            if hit:
                offenders.append(f'{rel}: {sorted(hit)}')
    assert not offenders, (
        '第三方服务客户端只许出现在 adapters 环：' + _NL + _NL.join(sorted(offenders)))


def test_纯逻辑环不许有IO也不许知道数据放在哪():
    """domain 的两条禁令，第二条最容易被忽略但最关键。

    ① 不许联网、不许起子进程 —— 保证它能离线、毫秒级地被测试
    ② **不许 import core.paths** —— domain 永远不知道文件放在哪，
       路径一律由调用方传进来

    第二条是关键：一旦 domain 知道了 workflow_data 的布局，它就跟我们的
    数据组织方式绑死了，既不能独立测试，也不能被别的项目复用，
    而且改一次目录布局就会波及本该最稳定的一层。
    """
    if not os.path.isdir(os.path.join(ROOT, 'domain')):
        pytest.skip('domain 环尚未建立')
    offenders = []
    for rel, f in _ring_files('domain'):
        if rel.endswith('/selftest.py'):
            continue
        mods = _imports_of(f)
        for bad in _NETWORK + _EXTERNAL + ['subprocess']:
            if bad in mods:
                offenders.append(f'{rel}: 用了 {bad}（domain 不许有 I/O）')
        if any(m == 'core.paths' or m.startswith('core.paths.') for m in mods):
            offenders.append(f'{rel}: import 了 core.paths —— '
                             f'domain 不该知道文件放在哪，路径请由调用方传进来')
    assert not offenders, 'domain 是纯逻辑环：' + _NL + _NL.join(sorted(offenders))


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


def test_项目内的import都能解析到真实存在的包():
    """搬家/改名之后，不许留下指向已经不存在的包的 import。

    这条是被真事逼出来的：阶段 2 把 `modules/` 拆成四环时，
    `panel.py` 里有两处**缩进在函数体内**的 `from modules import evalset`，
    批量改写的正则只匹配了行首，于是漏掉了。
    模块能 import 成功（因为那行在函数里），语法检查也过 ——
    只有用户点开控制面板的「精读评价」那一栏时才会炸。

    这里连**函数体内的 import** 一起扫，就是为了堵住这种「只在特定操作下才发作」的洞。
    """
    known = set(paths.CODE_RINGS)
    stale = {'modules'}          # 已经不存在的历史包名
    offenders = []
    for f in _py_files():
        rel = _rel(f)
        if rel.startswith('归档'):
            continue
        try:
            tree = ast.parse(open(f, encoding='utf-8', errors='replace').read(), f)
        except SyntaxError:
            continue
        for n in ast.walk(tree):
            mods = []
            if isinstance(n, ast.Import):
                mods = [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom) and n.module:
                mods = [n.module]
            for m in mods:
                top = m.split('.')[0]
                if top in stale:
                    offenders.append(f'{rel}:{n.lineno}: import 了已不存在的包「{top}」')
                elif top in known:
                    # 环存在，再看子包/子模块在不在
                    parts = m.split('.')
                    d = os.path.join(ROOT, *parts)
                    if not (os.path.isdir(d) or os.path.isfile(d + '.py')):
                        offenders.append(f'{rel}:{n.lineno}: 找不到 {m}')
    assert not offenders, (
        '这些 import 指向不存在的东西（改名/搬家后漏改）：' + _NL
        + _NL.join(sorted(set(offenders))))


# ══════════════════════════════════════════════════════════════════════
# 守卫四：两台机器的分工（见 docs/两台机器的分工.md）
# ══════════════════════════════════════════════════════════════════════
# 编程端（A 机）和运行端（B 机）**共用同一个 Zotero 账号**。
# 编程端一旦回写，污染的是真实文献库，而且立刻同步到主力机。
# 所以每个写 Zotero 的地方都必须先过 core.role.require_prod。

_ZOTERO_WRITE_HOST = 'api.zotero.org'      # Zotero 本地 API 只读，写只能走这个域名
_GUARD_CALL = 'role.require_prod'

# 允许出现该域名却不需要守卫的文件：适配层的只读封装、文档、守卫自己
_GUARD_EXEMPT = {
    'tests/test_architecture.py',
    'tests/test_core_role.py',
    'core/role.py',
}


def test_每个写Zotero的地方都有机器角色守卫():
    """漏掉一处，就等于这道闸不存在。

    为什么用「扫域名」而不是「信任大家记得加」：写 Zotero 的脚本有 9 个，
    分散在 4 个文件夹里。靠人记住「在编程端别跑这些」是不可靠的 ——
    一次手滑就把真实文献库的标签改掉，而且会同步到主力机，
    事后极难看出是什么时候被改的。
    """
    offenders = []
    for f in _py_files():
        rel = _rel(f)
        if rel in _GUARD_EXEMPT or rel.startswith('归档'):
            continue
        src = open(f, encoding='utf-8', errors='replace').read()
        if _ZOTERO_WRITE_HOST in src and _GUARD_CALL not in src:
            offenders.append(rel)
    assert not offenders, (
        '这些文件会写 Zotero，但没有机器角色守卫：' + _NL
        + _NL.join(sorted(offenders))
        + _NL + '做法：在执行写操作的函数开头加一行'
        + _NL + "  role.require_prod('这是什么操作', force=flag('--force'))")


def test_常驻服务不许在编程端启动():
    """watcher / 看门狗两台都跑会重复精读、重复写回、重复烧钱，标签状态机还会打架。"""
    offenders = []
    for rel in ('文献精读/zotero_watcher.py', '文献精读/watchdog.py'):
        f = os.path.join(ROOT, rel.replace('/', os.sep))
        if not os.path.isfile(f):
            continue
        if _GUARD_CALL not in open(f, encoding='utf-8', errors='replace').read():
            offenders.append(rel)
    assert not offenders, '常驻服务缺少机器角色守卫：' + _NL + _NL.join(offenders)


def test_守卫必须在函数体里而不是模块顶层():
    """守卫写在模块顶层会让 import 就抛错 —— 体检的「运行时导入」检查、
    pytest 的收集、面板借用这些模块的逻辑，全都会连带失败。

    守卫要挡的是「执行」，不是「加载」。
    """
    offenders = []
    for f in _py_files():
        rel = _rel(f)
        if rel in _GUARD_EXEMPT:
            continue
        try:
            tree = ast.parse(open(f, encoding='utf-8', errors='replace').read(), f)
        except SyntaxError:
            continue
        for node in tree.body:          # 只看模块顶层
            for sub in ast.walk(node):
                if (isinstance(sub, ast.Call)
                        and getattr(sub.func, 'attr', '') == 'require_prod'
                        and isinstance(node, (ast.Expr, ast.Assign, ast.If))):
                    offenders.append(f'{rel}:{sub.lineno}')
    assert not offenders, (
        '守卫被写在了模块顶层（import 时就会抛错）：' + _NL + _NL.join(sorted(offenders)))
