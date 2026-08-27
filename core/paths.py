# -*- coding: utf-8 -*-
"""core.paths —— 数据契约的唯一实现。

**全系统只有这个文件知道 workflow_data 里的目录长什么样。**

为什么需要它（见 docs/架构重构_v2总体设计.md 第三节 B）：
    `docs/数据契约.md` 把目录约定写得很清楚，但那只是散文。重构前，
    `workflow_data/...` 的路径在全项目 **53 处**被手工拼装 ——
    意味着契约随时可能被某个脚本悄悄违反，而没有任何东西会发现。

    收进这一个文件之后：
      · 想改目录布局 = 改这一个文件 + 写一个迁移脚本
      · 可以写契约测试：扫全库，验证每篇文献都满足约定（见 tests/）
      · 新写的代码不需要知道 'workflow_data' 这个字符串长什么样

用法：
    from core import paths
    text = open(paths.fulltext(key), encoding='utf-8').read()
    paths.paper_dir(key, create=True)

设计约定：
    · 所有函数返回**绝对路径字符串**（不是 Path 对象）——
      与项目现有代码风格一致，且能直接喂给 subprocess / open。
    · 函数**不做 I/O**，除非显式传 create=True。
    · 只依赖标准库。
"""
import os
import re

from core import errors

# ── 项目根 ────────────────────────────────────────────────────────────
# 本文件位于 <项目根>/core/paths.py，往上两级即项目根。
# 靠 __file__ 定位，与「从哪个目录启动」无关 —— 这是它能取代
# 那 40 处「往上走查 modules/ 目录」补丁的原因。
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── 一级目录 ──────────────────────────────────────────────────────────
DATA = os.path.join(ROOT, 'workflow_data')

LIBRARY = os.path.join(DATA, 'library')        # 核心数据区：按文献归档
STRUCTURED = os.path.join(DATA, 'structured')  # 结构化抽取产物
VECTOR_DB = os.path.join(DATA, 'vector_db')    # Chroma 向量库（可重建）
LOGS = os.path.join(DATA, 'logs')              # 运行日志
BACKUP = os.path.join(DATA, 'backup')          # 备份（如 Zotero 标签快照）
INCOMING = os.path.join(DATA, '_incoming')     # 临时处理区（可清空）

# ── Zotero item key 的形状 ────────────────────────────────────────────
# 数据契约保证「文件夹名 = Zotero item key，8 位字母数字」。
# 这里把它变成可执行的校验，防止有人拿标题、路径当 key 传进来。
KEY_RE = re.compile(r'^[A-Z0-9]{8}$')


class BadKeyError(errors.BadInputError):
    """传进来的东西不是合法的 Zotero item key。

    归入 `core.errors.BadInputError`：调用方传错了，重试没有意义。
    （它同时仍是 ValueError，旧代码里 `except ValueError` 照样接得住。）
    """


def check_key(key):
    """校验并规范化一个 item key，返回大写形式。不合法就抛 BadKeyError。

    这是数据契约第 1 条（文件夹名 = 8 位字母数字 item key）的执行点。
    """
    k = str(key).strip().upper()
    if not KEY_RE.match(k):
        raise BadKeyError(
            f'不是合法的 Zotero item key: {key!r}（应为 8 位字母数字，如 2T6H4S3D）')
    return k


# ── 单篇文献的产物（★ 标记的是下游可以依赖的稳定文件）────────────────
def paper_dir(key, create=False):
    """<library>/<key>/ —— 一篇文献的全部数据都在这里。"""
    p = os.path.join(LIBRARY, check_key(key))
    if create:
        os.makedirs(p, exist_ok=True)
    return p


def parsed_dir(key, create=False):
    """<library>/<key>/parsed/ —— PDF 解析器（现为 MineRU）的原始产物。"""
    p = os.path.join(paper_dir(key), 'parsed')
    if create:
        os.makedirs(p, exist_ok=True)
    return p


def fulltext(key):
    """★ parsed/full.md —— 解析出的全文 Markdown。

    这是整个平台**不可再生的核心资产**：向量化、结构化抽取、重新精读
    都从它出发。换解析器时，新解析器也必须产出这个文件（数据契约）。
    """
    return os.path.join(parsed_dir(key), 'full.md')


def layout(key):
    """★ parsed/layout.json —— 页面布局与图坐标，精读裁完整 Figure 靠它。"""
    return os.path.join(parsed_dir(key), 'layout.json')


def images_dir(key):
    """parsed/images/ —— 解析器抽出的碎图（精读不用它，见踩坑 #7）。"""
    return os.path.join(parsed_dir(key), 'images')


def summary(key):
    """★ summary.html —— 正文的中文图文精读（图已内嵌 base64，可独立打开）。"""
    return os.path.join(paper_dir(key), 'summary.html')


def si_summary(key):
    """si_summary.html —— 补充材料（SI）的实验细节精读。"""
    return os.path.join(paper_dir(key), 'si_summary.html')


def summary_full(key):
    """summary_full.html —— 正文 + SI 合并后的全文精读。"""
    return os.path.join(paper_dir(key), 'summary_full.html')


def meta(key):
    """★ meta.json —— 元数据（标题/DOI/日期/由谁何时生成）。"""
    return os.path.join(paper_dir(key), 'meta.json')


# ── 结构化抽取产物 ────────────────────────────────────────────────────
def structured(key):
    """★ structured/<key>.json —— 单篇的结构化字段。"""
    return os.path.join(STRUCTURED, check_key(key) + '.json')


def compare(name='compare'):
    """★ structured/<name>.md —— 横向对比表（找 idea 的载体）。

    name 取值：'compare'（研究论文总表）、'compare_reviews'（综述）、
    'compare_PBS'（聚硼硅氧烷精层子表）、'compare_domain' 等。
    """
    return os.path.join(STRUCTURED, name + '.md')


# ── 日志与杂项 ────────────────────────────────────────────────────────
def log(name, create_dir=True):
    """logs/<name>.log —— 统一的日志落点。"""
    if create_dir:
        os.makedirs(LOGS, exist_ok=True)
    return os.path.join(LOGS, name + '.log')


def runtime(name):
    """logs/<name> —— 心跳、锁等运行期小文件（与日志同目录，便于一并清理）。"""
    os.makedirs(LOGS, exist_ok=True)
    return os.path.join(LOGS, name)


def evalset():
    """workflow_data/evalset.json —— 精读质量评测集（用户的人工评价，不可重建）。"""
    return os.path.join(DATA, 'evalset.json')


def last_search():
    """workflow_data/_last_search.json —— 上一次「找新文献」的结果暂存。"""
    return os.path.join(DATA, '_last_search.json')


def junk_list(ext='json'):
    """workflow_data/待删条目清单.<ext> —— 库房维护的待删清单。"""
    return os.path.join(DATA, '待删条目清单.' + ext)


# ── 遍历 ──────────────────────────────────────────────────────────────
def all_keys():
    """列出 library/ 下所有已归档文献的 key（已按契约过滤掉非法目录名）。"""
    if not os.path.isdir(LIBRARY):
        return []
    keys = []
    for name in os.listdir(LIBRARY):
        if KEY_RE.match(name.upper()) and os.path.isdir(os.path.join(LIBRARY, name)):
            keys.append(name.upper())
    return sorted(keys)


def has(key, what='fulltext'):
    """这篇文献的某个产物存在吗？what ∈ 本模块的产物函数名。

    例：paths.has(key, 'summary') → summary.html 在不在。
    给「只补缺的部分，不重跑已有的」这类判断一个统一入口，
    避免各处自己拼路径再 os.path.exists。
    """
    fn = globals().get(what)
    if not callable(fn):
        raise ValueError(f'未知的产物名: {what!r}')
    try:
        return os.path.exists(fn(key))
    except BadKeyError:
        return False


# ── 仓库形状 ──────────────────────────────────────────────────────────
# 「哪些顶层目录不是工作流」这份清单，此前在 交接.py / panel.py / health_check.py
# 里各写了一遍（三份，且已经互相不一致）。收在这里，改一次全都生效。
# ① 噪音目录：数据、缓存、构建产物。画目录树、扫源码时一律跳过，
#    但它们**不是**「代码结构」的一部分。
NOISE_DIRS = {
    'workflow_data', 'n8n_data', 'wf_backup', 'b',
    '__pycache__', '.git', '.venv', 'venv', 'build', 'dist', '.pytest_cache',
    'zotero_literature_platform.egg-info',
}

# ② 非工作流目录 = 噪音 + 代码环 + 积木/文档/测试。
#    用于「自动发现有哪几条工作流线」（体检、面板、交接文件都要这个判断）。
NON_WORKFLOW_DIRS = NOISE_DIRS | {
    'core', 'domain', 'adapters', 'apps',   # 四环里的非编排环
    'modules', 'docs', 'tests', '归档_旧版本',
}


# ③ 代码四环（重构 v2）。依赖只能从上往下：apps → pipelines → domain/adapters → core
CODE_RINGS = ('core', 'domain', 'adapters', 'pipelines')


def block_dirs():
    """列出四环里所有「积木」（带 __init__.py 的子包），返回 [(环, 名字, 目录)]。

    体检、控制面板、交接文件都要枚举积木。重构前它们各自 glob `modules/*/`，
    积木一搬家三处全瞎 —— 所以这个枚举也收在契约层。
    """
    out = []
    for ring in CODE_RINGS:
        rd = os.path.join(ROOT, ring)
        if not os.path.isdir(rd):
            continue
        for name in sorted(os.listdir(rd)):
            d = os.path.join(rd, name)
            if os.path.isdir(d) and os.path.isfile(os.path.join(d, '__init__.py')):
                out.append((ring, name, d))
    return out


def block_dir(name):
    """按名字找一块积木在哪个环，返回目录；找不到返回 None。"""
    for _ring, n, d in block_dirs():
        if n == name:
            return d
    return None


def is_workflow_dir(name):
    """这个顶层目录名算不算一条「工作流线」（用于体检、面板、交接文件的自动发现）。"""
    return (name not in NON_WORKFLOW_DIRS
            and not name.startswith(('.', 'zotero_backup'))
            and not name.endswith('.egg-info'))
