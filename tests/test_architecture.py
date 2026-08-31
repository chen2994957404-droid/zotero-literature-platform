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

from shared.kernel import paths

ROOT = paths.ROOT

# 不扫描的目录：数据、历史存档、构建产物
SKIP_DIRS = {'data', 'workflow_data', '.git', '__pycache__', '归档_旧版本',
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
# 允许直接写数据根目录字面量的文件（数据契约的实现处 + 它的测试 + 搬家脚本）
PATHS_OWNERS = {'shared/kernel/paths.py', 'tests/test_architecture.py',
                'tests/test_core_paths.py', 'host/deploy/migrate_data.py'}

# 「这一行在拼路径」的特征
_PATH_BUILDING = ('os.path.join', 'glob', 'open(', 'os.makedirs',
                  'os.path.exists', 'os.listdir', 'os.path.isdir', 'os.path.isfile')

# 数据根目录的字面量。R6 之前这里写死的是 'workflow_data' 那一个词；改名成
# `data/` 之后如果不跟着改，这条守卫会**一直空转**（踩坑 #83 就是这么来的：
# 两条联网守卫在 R1 改完路径后静静地什么都不守了）。
# 老名字一并留着：B 机切过来之前，任何还在拼老路径的代码照样要被揪出来。
_DATA_ROOT = re.compile(r"""['"](?:workflow_)?data['"/]""")


def test_数据目录路径只在core_paths里拼装():
    """除 shared/kernel/paths.py 外，谁都不许自己拼 data/ 的路径。

    为什么：路径散落各处 = 数据契约无法被保证。改一次目录布局要改几十处，
    漏一处就是一个只在运行时才暴露的 bug。R6 窗把 `workflow_data/` 换成五层
    `data/` 时，全系统**只改了 paths.py 一个文件**，靠的就是这条。
    """
    offenders = []
    for f in _py_files():
        rel = _rel(f)
        if rel in PATHS_OWNERS:
            continue
        for i, line in enumerate(open(f, encoding='utf-8', errors='replace'), 1):
            # 先把反斜杠归一成斜杠，正则里就不必处理 Windows 分隔符
            if EXEMPT in line or not _DATA_ROOT.search(line.replace(os.sep, '/')):
                continue
            # 只揪「真的在拼路径」的行。散文里提一句目录名（文档字符串、
            # 遍历时排除数据目录的集合字面量）不算违规，也没法在那儿加注释豁免。
            if any(t in line for t in _PATH_BUILDING):
                offenders.append(f'{rel}:{i}: {line.strip()[:90]}')
    assert not offenders, (
        '这些地方在自己拼数据目录路径，应改用 shared.kernel.paths：\n  '
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
    """shared.kernel 不许 import shared.domain/shared.adapters/tools/host，以此类推。"""
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

    如果工具层或 domain 也能直接发 HTTP 请求，那个承诺当场作废 ——
    换外部服务时就得满仓库找 urlopen。重构前 `pipelines/paper_discovery`
    正是这样：编排层里直接写着 OpenAlex 的 URL 和 urlopen。
    """
    offenders = []
    for ring in ('shared/kernel', 'shared/domain', 'tools'):
        for rel, f in _ring_files(ring):
            if rel.endswith('/selftest.py'):
                continue          # 自测里允许直接探活外部服务
            hit = _imports_of(f) & set(_NETWORK)
            if hit:
                offenders.append(f'{rel}: 「{ring}」环直接联网（{sorted(hit)}）')
    assert not offenders, (
        '只有 adapters 环可以联网，其余环必须通过适配器：' + _NL
        + _NL.join(sorted(offenders))
        + _NL + '做法：把这次外部调用包成 shared/adapters/<服务名>，本环只调它。')


def test_只有adapters环可以用外部服务客户端():
    """chromadb / keyring 这类第三方客户端同理，只许出现在 adapters。"""
    offenders = []
    for ring in ('shared/domain', 'tools'):
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
    ② **不许 import shared.kernel.paths** —— domain 永远不知道文件放在哪，
       路径一律由调用方传进来

    第二条是关键：一旦 domain 知道了 data/ 的布局，它就跟我们的
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
        if any(m == 'shared.kernel.paths' or m.startswith('shared.kernel.paths.') for m in mods):
            offenders.append(f'{rel}: import 了 shared.kernel.paths —— '
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
    known = set(paths.CODE_ROOTS)
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
# 所以每个写 Zotero 的地方都必须先过 shared.kernel.role.require_prod。

_ZOTERO_WRITE_HOST = 'api.zotero.org'      # Zotero 本地 API 只读，写只能走这个域名
_GUARD_CALL = 'role.require_prod'

# 允许出现该域名却不需要守卫的文件：适配层的只读封装、文档、守卫自己
_GUARD_EXEMPT = {
    'tests/test_architecture.py',
    'tests/test_core_role.py',
    'shared/kernel/role.py',
}

# 曾经有过一个「只读的云端封装」豁免名单（shared/adapters/zotero_client 只读云端时）。
# 2026-08-27 把三份 Zotero 写实现收进该适配层之后，它真的会写了，
# 也真的带上了守卫 —— 豁免与配套的「必须保持只读」检查一并撤销。
_READONLY_WEB = set()


def _code_text(path):
    """源码**抹掉注释与文档字符串之后**的样子 —— 守卫只该看代码，不该看散文。

    为什么需要（同一天踩了两次）：守卫是文本扫描，于是
    「在文档字符串里解释这些写操作收到哪儿去了」也会被判成「这个文件在写 Zotero」。
    人于是被逼着为了让守卫闭嘴而少写注释 —— **那是守卫在损害它本该保护的东西**。

    做法是把注释/文档字符串的字符**原地换成空格**，而不是重新拼源码：
    重拼会改变 `role.require_prod` 这种带点的写法（tokenize 会插空格），
    守卫反而全线误判。位置替换则保证除了被抹掉的部分，其余一个字符都没动。
    """
    import io as _io
    import tokenize
    src = open(path, encoding='utf-8', errors='replace').read()
    lines = src.splitlines(keepends=True)
    spans, prev = [], tokenize.INDENT
    try:
        for tok in tokenize.generate_tokens(_io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                spans.append((tok.start, tok.end))
                continue          # 注释不改变「上一个有意义的 token」
            drop = tok.type == tokenize.STRING and prev in (
                tokenize.INDENT, tokenize.DEDENT, tokenize.NEWLINE,
                tokenize.NL, tokenize.ENCODING)
            if tok.type not in (tokenize.NL, tokenize.NEWLINE):
                prev = tok.type
            if drop:
                spans.append((tok.start, tok.end))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return src          # 扫不动就退回原文（宁可误报，不可漏报）

    for (srow, scol), (erow, ecol) in spans:
        for row in range(srow, erow + 1):
            line = lines[row - 1]
            lo = scol if row == srow else 0
            hi = ecol if row == erow else len(line)
            lines[row - 1] = line[:lo] + ' ' * (hi - lo) + line[hi:]
    return ''.join(lines)


def test_守卫自己也要被守卫_散文不算代码(tmp_path):
    """给 `_code_text` 的元测试：**放过散文，但绝不能放过代码**。

    第二条比第一条重要得多 —— 一个「不会误报」但也不会真正报警的守卫，
    比没有守卫更糟：它给人一种「有东西在看着」的错觉。
    """
    nl = chr(10)
    prose = tmp_path / 'prose.py'
    prose.write_text(nl.join([
        '# 注释里提一句 api.zotero.org',
        chr(34) * 3 + '文档字符串里也提 api.zotero.org。' + chr(34) * 3,
        'x = 1', '']), encoding='utf-8')
    assert _ZOTERO_WRITE_HOST not in _code_text(str(prose))

    real = tmp_path / 'real.py'
    real.write_text(nl.join([
        chr(34) * 3 + '说明。' + chr(34) * 3,
        chr(87) + 'EB = ' + chr(34) + 'https://api.zotero.org/users/1' + chr(34),
        '']), encoding='utf-8')
    code = _code_text(str(real))
    assert _ZOTERO_WRITE_HOST in code, '真的在代码里写域名，必须还能被抓到'
    assert '说明' not in code

    guarded = tmp_path / 'guarded.py'
    guarded.write_text(nl.join([
        'def f():',
        '    role.require_prod(' + chr(34) + '写' + chr(34) + ')', '']), encoding='utf-8')
    assert _GUARD_CALL in _code_text(str(guarded)), (
        '守卫调用被抹掉的话，所有文件都会被误判成「没守卫」')


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
        if rel in _GUARD_EXEMPT or rel in _READONLY_WEB or rel.startswith('归档'):
            continue
        src = _code_text(f)          # 只看代码：文档里提一句域名不算「在写 Zotero」
        if _ZOTERO_WRITE_HOST in src and _GUARD_CALL not in src:
            offenders.append(rel)
    assert not offenders, (
        '这些文件会写 Zotero，但没有机器角色守卫：' + _NL
        + _NL.join(sorted(offenders))
        + _NL + '做法：在执行写操作的函数开头加一行'
        + _NL + "  role.require_prod('这是什么操作', force=flag('--force'))")


# HTTP 写方法的写法（够用即可：本项目一律用 urllib，method= 显式传）
_WRITE_METHODS = ("'POST'", '"POST"', "'PATCH'", '"PATCH"',
                  "'PUT'", '"PUT"', "'DELETE'", '"DELETE"')


def test_只读的云端封装必须保持只读():
    """上一条守卫给 `_READONLY_WEB` 里的文件开了免检，这条负责让免检名副其实。

    为什么需要这一对：适配层需要读云端（「我上次传的附件还在不在」，
    这个问题只有云端答得准，本地 API 滞后于同步 —— 踩坑 #64）。
    读不需要机器角色守卫，写需要。**开了口子就得有东西守着口子**，
    否则哪天有人在这个文件里加个 POST，免检会让它一路绿灯溜过去。
    """
    offenders = []
    for rel in sorted(_READONLY_WEB):
        f = os.path.join(ROOT, rel.replace('/', os.sep))
        if not os.path.isfile(f):
            continue
        src = open(f, encoding='utf-8', errors='replace').read()
        quotes = chr(39) + chr(34)
        hit = [m.strip(quotes) for m in _WRITE_METHODS if m in src]
        if hit:
            offenders.append(f'{rel}: 出现写方法 {sorted(set(hit))}')
    assert not offenders, (
        '这些文件被当成「只读的云端封装」而免了机器角色守卫，但它们在写：' + _NL
        + _NL.join(offenders)
        + _NL + '要么把写操作挪回调用方（那里有守卫），'
        + _NL + '要么给它加 role.require_prod 并从 _READONLY_WEB 里去掉。')


def test_常驻服务不许在编程端启动():
    """watcher / 看门狗两台都跑会重复精读、重复写回、重复烧钱，标签状态机还会打架。"""
    offenders = []
    for rel in ('tools/deepread/watcher.py', 'tools/deepread/watchdog.py'):
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


# ══════════════════════════════════════════════════════════════════════
# 守卫五：进版本库的文件必须只有一个生产者
# ══════════════════════════════════════════════════════════════════════
# 两台机器都会改写的生成物/缓存一旦进了版本库，每次 git pull 必冲突，
# 而运行端没有 Claude Code 来解冲突 —— 那是最难受的情形。
# 2026-08-26 真实发生过：主力机卡在 unmerged 状态，pull 不动。

# 这些文件由程序生成或运行时改写，必须保持「未跟踪」
_MUST_NOT_TRACK = [
    'HANDOVER.md',                       # handover.py 生成，面板上有按钮，两台都会点
    'data/state/_last_search.json',      # 每次「找新文献」都重写
]


def _tracked_files():
    import subprocess
    r = subprocess.run(['git', 'ls-files'], cwd=ROOT, capture_output=True,
                       text=True, encoding='utf-8', errors='replace', timeout=120)
    return set((r.stdout or '').split())


def test_生成物和运行时缓存不许进版本库():
    """判据：**进版本库的文件必须只有一个生产者。**

    多台机器都会改写同一个被跟踪的文件 = 每次拉取都冲突。
    这类文件都是可再生的，本地留着自己用就行。
    """
    tracked = _tracked_files()
    if not tracked:
        pytest.skip('拿不到 git 跟踪清单（不是 git 仓库？）')
    bad = [f for f in _MUST_NOT_TRACK if f in tracked]
    assert not bad, (
        '这些文件是生成物/运行时缓存，不该被 git 跟踪：' + _NL + _NL.join(bad)
        + _NL + '做法：git rm --cached <文件>，并加进 .gitignore')


def test_用户不可重建的数据仍在版本库里():
    """反向的闸：`evalset.json` 是用户一条条打出来的精读评价，**重建不了**。

    上面那条守卫说「生成物要移出版本库」，很容易顺手把这个也移出去 ——
    那就等于把唯一的备份删了。所以在这里钉死。
    """
    tracked = _tracked_files()
    if not tracked:
        pytest.skip('拿不到 git 跟踪清单')
    assert 'data/state/evalset.json' in tracked, (
        'evalset.json（用户人工精读评价）必须留在版本库里 —— 它不可重建，'
        '而且只有运行端会产生它，版本库是它唯一的备份。')


# ══════════════════════════════════════════════════════════════════════
# 守卫六：引导脚本不许依赖「还没装好的包」
# ══════════════════════════════════════════════════════════════════════
# 「用来修好环境的工具」自己被环境卡死，是最难受的一类故障 ——
# 用户拿不到任何有用信息，只有一行 ModuleNotFoundError。
# 2026-08-26 真实发生：主力机从没装过包，而 更新平台.py 顶上写着
# `from shared.kernel import paths, role`，于是那个「第 2 步就是装包」的脚本自己起不来。

# 这些脚本必须能在「包还没装好」的机器上跑起来
BOOTSTRAP_SCRIPTS = [
    'host/deploy/update.py',       # 它要做的事情之一就是装包
    'host/doctor/report.py',       # 出问题时才用，不能要求环境是好的
    'host/panel/open_panel.py',    # 面板起不来时要靠它定位，自己不能也起不来
    'host/panel/launcher.py',      # 同上：它存在的意义就是接住 import 期的异常
]

# 项目自己的顶层包
_PROJECT_PKGS = {'core', 'domain', 'adapters', 'pipelines'}


def test_引导脚本不许在模块顶层import项目包():
    """判据：**体温计不能要求你先退烧。**

    这两个脚本一个是「装包的」、一个是「坏了才用的」，
    它们必须在环境不完整时也能起来。项目包只能在函数里延迟 import，
    并且要为 import 失败准备好降级路径。
    """
    offenders = []
    for rel in BOOTSTRAP_SCRIPTS:
        f = os.path.join(ROOT, rel.replace('/', os.sep))
        if not os.path.isfile(f):
            continue
        tree = ast.parse(open(f, encoding='utf-8', errors='replace').read(), f)
        for node in tree.body:                      # 只看模块顶层
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module]
            for m in mods:
                if m.split('.')[0] in _PROJECT_PKGS:
                    offenders.append(f'{rel}:{node.lineno}: 顶层 import 了 {m}')
    assert not offenders, (
        '引导脚本在模块顶层 import 了项目包，包没装好时它自己就起不来：' + _NL
        + _NL.join(offenders)
        + _NL + '做法：放进函数里延迟 import，并写好 import 失败时的降级路径'
        + _NL + '（顶层写在 try/except 里也可以 —— 那不算模块顶层的裸 import）')
