# -*- coding: utf-8 -*-
"""shared.kernel.paths —— 数据契约的唯一实现。

**全系统只有这个文件知道 data/ 里的目录长什么样。**

为什么需要它（见 docs/explain/架构重构_v2总体设计.md 第三节 B）：
    `docs/reference/数据契约.md` 把目录约定写得很清楚，但那只是散文。重构前，
    数据路径曾在全项目 **53 处**被手工拼装 ——
    意味着契约随时可能被某个脚本悄悄违反，而没有任何东西会发现。

    收进这一个文件之后：
      · 想改目录布局 = 改这一个文件 + 写一个迁移脚本
      · 可以写契约测试：扫全库，验证每篇文献都满足约定（见 tests/）
      · 新写的代码不需要知道 'data' 这个字符串长什么样

用法：
    from shared.kernel import paths
    text = open(paths.fulltext(key), encoding='utf-8').read()
    paths.paper_dir(key, create=True)

设计约定：
    · 所有函数返回**绝对路径字符串**（不是 Path 对象）——
      与项目现有代码风格一致，且能直接喂给 subprocess / open。
    · 函数**不做 I/O**，除非显式传 create=True。
    · 只依赖标准库。
"""
import hashlib
import os
import re

from shared.kernel import errors

# ── 项目根 ────────────────────────────────────────────────────────────
# 本文件位于 <项目根>/shared/kernel/paths.py，往上**三级**即项目根。
# 靠 __file__ 定位，与「从哪个目录启动」无关 —— 这是它能取代
# 那 40 处「往上走查 modules/ 目录」补丁的原因。
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── 五层数据（R6 窗，2026-08-31）──────────────────────────────────────
# **数据单向流，每一层只从上一层构建。** 分层的判据是「重建它要付出什么」：
#
#   raw      解析器吐出来的东西 + 原始 PDF。重建 = 再花一次 MineRU 额度，
#            而且得先有 PDF。**最贵的一层，也是唯一必须备份的一层。**
#   curated  我们自己的流水线从 raw 造出来的：中文精读 HTML、元数据。
#            重建 = 再花一次大模型的钱。
#   serving  随时可重建：对比表、向量库、方向地图、**雷达库 radar.db**（0 级：盯着的刊
#            每篇的题目/摘要/参考文献，从 Crossref 重拉即可）。删了跑一条命令就有。
#            例外：journal_watch.json（盯哪些刊、分几档）是人定的，重建不了 —— 但它是配置不是数据。
#   state    索引与进度，**不是真相**：state.db / papers.db / 上次检索结果 /
#            journal_watch_seen.json（盯新刊见过哪些、回填到哪块）。
#            例外是 evalset.json（用户一条条打的人工评价，重建不了）。
#   logs     运行日志与心跳。
#   backup   快照（Zotero 标签、覆盖前的 structured）。
#
# ⚠ **偏离 REBUILD.md 第四节的映射表一处，理由如下**（同 R3/R4/R5 的
# 「规则优先于表」）：那张表把 `full.md` 归进 curated。但 `full.md` 是 MineRU
# 直接吐的，**没有经过我们任何一步加工**，按上面的判据它就是 raw；而且它与
# `images/`（Markdown 里的相对图片链接）、`layout.json` + `*_origin.pdf`
# （`figure_crop.crop_figures(parsed_dir)` 要求三者同目录）物理绑死。
# 把它单独拎出来会**逼着改工具逻辑**，而 R6 明令「只动目录组织」。
# 所以切口划在**目录边界**上：整个 `parsed/` 与 `si_parsed/` 进 raw，
# 我们自己产出的 `meta.json` / `summary*.html` 进 curated。
DATA = os.path.join(ROOT, 'data')

RAW = os.path.join(DATA, 'raw')            # 解析器原始产物 + 原始 PDF（最贵）
CURATED = os.path.join(DATA, 'curated')    # 我们的流水线产出（精读、元数据）
SERVING = os.path.join(DATA, 'serving')    # 随时可重建的服务层
STATE = os.path.join(DATA, 'state')        # 索引与进度，不是真相
LOGS = os.path.join(DATA, 'logs')          # 运行日志
BACKUP = os.path.join(DATA, 'backup')      # 快照（Zotero 标签、structured 覆盖前）

VECTOR_DB = os.path.join(SERVING, 'vector_db')    # Chroma 向量库（可重建）
INCOMING = os.path.join(RAW, '_incoming')         # 临时处理区（可清空）
CHEMDB_EXPORTS = os.path.join(RAW, '_chemdb_exports')  # 人从 SciFinder / Reaxys 手动导出的表（Excel / RIS），原样放

# ── 方向地图（领域全景，非单篇文献）────────────────────────────────
# 与 library/ 的区别：library 按「我读过的文献」组织，direction 按「领域长什么样」
# 组织。前者是资产，后者是**可重建的派生层** —— 删掉再跑一遍命令就有。
#
# ⚠ **按「窄带」分库，不是单例。** 用户会陆续做多条窄带（抗冲、别的方向……），
# 加一条窄带必须是「加一份配置」而不是「改代码」。所以 band 是必填参数，
# 没有默认值 —— 有默认值就会有人忘了传，然后两条窄带的数据混进同一个库。


class BadBandError(errors.BadInputError):
    """窄带 id 不合法。必须是小写字母数字下划线短横（做目录名要安全）。"""

# ── 文献 id 的形状（2026-09-07 放宽，用户拍板）──────────────────────
# **原来这里写死 `^[A-Z0-9]{8}$` —— 即「文献的身份证 = Zotero 条目编号」。**
# 直接后果：一篇文献想在库里有位置，必须先是用户 Zotero 里的一条。
# 于是方向层那上万条公开文献只能另开一个目录、另起一套 id，
# 并在 paperdb / digitize / extract 里到处写「不是 8 位就跳过」的补丁。
#
# 用户的判断（2026-09-07）：
#   **数据库是这个领域的公共账本，Zotero 是他个人的阅读桌。**
#   账本不该被书架的编号限制住 —— Zotero 编号降级成「这篇我个人收藏了」这个属性。
#
# 所以身份证改成**来源无关的文献 id**，三种合法形状：
#   `2T6H4S3D`                  Zotero 条目编号（8 位大写字母数字）—— 老数据原样有效
#   `W2741809687`               OpenAlex 作品 id —— 方向层本来就在用
#   `doi_10.1021-acs.macro...`  由 DOI 生成（见 `paper_id_from_doi`）—— 两边都没有时用
#   `cnki_slgy202603021`        知网的文件名（见 `paper_id_from_cnki`）—— 没有 DOI 的中文文献（2026-10-15 加）
# 加一种来源 = 往 `_ID_PREFIXES` 里加一个前缀，不用改别的地方。
#
# **对账靠 DOI，不靠 id**：同一篇文献在不同来源下可能拿到不同 id，
# 谁跟谁是同一篇由 `papers.doi` 回答（见 tools/paperdb）。
ZOTERO_KEY_RE = re.compile(r'^[A-Z0-9]{8}$')
OA_ID_RE = re.compile(r'^W\d{4,12}$')
_ID_PREFIXES = ('doi', 'cnki')
SLUG_ID_RE = re.compile(r'^(?:%s)_[a-z0-9][a-z0-9._-]{0,79}$' % '|'.join(_ID_PREFIXES))

# 旧名字保留：既有代码里 `KEY_RE.match(x)` 问的都是「这是不是 Zotero 编号」，
# 那个含义没变，变的只是「文献 id 不再只有这一种」。新代码请用 is_zotero_key()。
KEY_RE = ZOTERO_KEY_RE


class BadKeyError(errors.BadInputError):
    """传进来的东西不是合法的文献 id。

    归入 `shared.kernel.errors.BadInputError`：调用方传错了，重试没有意义。
    （它同时仍是 ValueError，旧代码里 `except ValueError` 照样接得住。）
    """


def check_key(key):
    """校验并规范化一个文献 id。不合法就抛 BadKeyError。

    这是数据契约第 1 条（一篇文献一个目录，目录名 = 文献 id）的执行点。
    Zotero 编号与 OpenAlex id 归一成大写，前缀式 id 归一成小写 ——
    **同一篇永远只算出同一个目录名**，这是全系统不错位的前提。
    """
    s = str(key).strip() if key is not None else ''
    up = s.upper()
    if ZOTERO_KEY_RE.match(up) or OA_ID_RE.match(up):
        return up
    low = s.lower()
    if SLUG_ID_RE.match(low):
        return low
    raise BadKeyError(
        f'不是合法的文献 id: {key!r}'
        f'（应为 8 位 Zotero 编号如 2T6H4S3D、OpenAlex id 如 W2741809687，'
        f'或 doi_ / cnki_ 开头的 id —— 用 paths.paper_id_from_doi() / paper_id_from_cnki() 生成）')


def is_zotero_key(key):
    """这个 id 是不是 Zotero 条目编号（即：这篇在用户自己的库里）？

    取代此前散在各处的 `KEY_RE.match(k)` —— 那个写法问的是形状，
    真正想知道的是**这篇在不在他的阅读桌上**。名字写对了，读代码的人才不会误解。
    """
    try:
        return bool(ZOTERO_KEY_RE.match(check_key(key)))
    except BadKeyError:
        return False


_DOI_PREFIX_RE = re.compile(r'^(?:https?://(?:dx\.)?doi\.org/|doi:)', re.I)


CNKI_FILENAME_RE = re.compile(r'^[A-Za-z]{0,8}\d{4,}[A-Za-z0-9]*$')   # 期刊 SLGY202603021；学位论文全是数字


def paper_id_from_cnki(filename):
    """知网的文件名（每篇固定的编号，如期刊 `SLGY202603021`、学位论文 `1024012345.nh` 去掉后缀）→ `cnki_slgy202603021`。

    给**没有 DOI 的中文文献**用（2026-10-15：王海平《塑料工业》2026 在知网页和 PDF 里都没有 DOI，证据库收不进）。
    有 DOI 的一律按 DOI 起（`paper_id_from_doi`）—— 跨来源认同一篇靠 DOI。
    """
    f = re.sub(r'\.(nh|caj|pdf)$', '', str(filename or '').strip(), flags=re.I)
    if not CNKI_FILENAME_RE.match(f):
        raise BadKeyError(f'不像知网文件名: {filename!r}（应形如 SLGY202603021）')
    return check_key('cnki_' + f.lower())


def paper_id_from_doi(doi):
    """DOI → 文献 id（`10.1021/acs.x` → `doi_10.1021-acs.x`）。

    为什么不直接拿 DOI 当目录名：DOI 里的 `/` 是路径分隔符，Windows 上根本建不出来。
    所以做一次**只进不出的**净化：非 `a-z0-9._-` 的字符一律换成 `-`。
    净化不可逆是故意的 —— 目录名只需要「唯一且稳定」，
    **规范的 DOI 原文另存在 `meta.json` 与 `papers.doi` 里**，要引用时取那份。
    太长的截断后缀一段哈希，保证仍然唯一。
    """
    d = _DOI_PREFIX_RE.sub('', str(doi or '').strip()).strip().lower()
    if not d.startswith('10.') or len(d) < 8:
        raise BadKeyError(f'不像是 DOI: {doi!r}（应形如 10.1021/acs.macromol.1c00123）')
    slug = re.sub(r'-{2,}', '-', re.sub(r'[^a-z0-9._-]+', '-', d)).strip('-.')
    if len(slug) > 72:
        slug = slug[:64] + '-' + hashlib.sha1(d.encode('utf-8')).hexdigest()[:8]
    return check_key('doi_' + slug)


# ── 单篇文献的产物（★ 标记的是下游可以依赖的稳定文件）────────────────
def paper_dir(key, create=False):
    """★ curated/<key>/ —— 这篇文献里**我们自己造的**东西（精读、元数据）。

    R6 之前它是 `library/<key>/`，解析产物也在里面。现在解析产物搬去了
    `raw/<key>/`（见 `paper_raw_dir`）—— 一篇文献占两个目录，因为它跨两层。
    """
    p = os.path.join(CURATED, check_key(key))
    if create:
        os.makedirs(p, exist_ok=True)
    return p


def paper_raw_dir(key, create=False):
    """raw/<key>/ —— 这篇文献**解析器吐出来的**那一半（parsed/ 与 si_parsed/）。

    要算「这篇一共占多大」得把它和 `paper_dir` 一起算（见 host/doctor/artifact_gaps）。
    """
    p = os.path.join(RAW, check_key(key))
    if create:
        os.makedirs(p, exist_ok=True)
    return p


def _open_paper(key):
    """开工处理一篇文献 = 它在**两层里的目录都建好**。

    R6 之前 `parsed/` 是 `library/<key>/` 的子目录，所以建解析目录顺手就把
    这篇的目录建出来了，后面写 `meta.json` / `summary.html` 直接就能写。
    分层之后这个隐含保证断了 —— 精读写 summary 时 `curated/<key>/` 还不存在，
    只会在真跑一篇的时候炸（离线测试全绿也照样炸）。
    与其让每个写产物的地方各自补一句 makedirs，不如把这个不变量钉在这里：
    **这是唯一知道「一篇文献长什么样」的地方。**
    """
    os.makedirs(paper_dir(key), exist_ok=True)
    os.makedirs(paper_raw_dir(key), exist_ok=True)


def parsed_dir(key, create=False):
    """raw/<key>/parsed/ —— PDF 解析器（现为 MineRU）的原始产物。

    这一整个目录是**一个不可拆的单元**：`full.md` 用相对路径引 `images/`，
    `crop_figures()` 要求 `layout.json` 与 `*_origin.pdf` 同目录。别只搬其中一个。
    """
    p = os.path.join(paper_raw_dir(key), 'parsed')
    if create:
        os.makedirs(p, exist_ok=True)
        _open_paper(key)
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


def si_parsed_dir(key, create=False):
    """raw/<key>/si_parsed/ —— 补充材料（SI）的解析产物。"""
    p = os.path.join(paper_raw_dir(key), 'si_parsed')
    if create:
        os.makedirs(p, exist_ok=True)
        _open_paper(key)
    return p


def si_fulltext(key):
    """★ si_parsed/full.md —— SI 的全文 Markdown。

    **合成条件（投料量、配比、温度时间）大多只写在 SI 里**，正文只给结论。
    结构化抽取要读它，不然 `synthesis_conditions` 只能是 N/A（2026-08-28）。
    """
    return os.path.join(si_parsed_dir(key), 'full.md')


def local_pdf(key):
    """★ raw/<key>/main.pdf —— 正文 PDF 的**本地正本**。

    2026-09-06 加。在它之前，正文 PDF 的唯一存放处是 Zotero 的 storage ——
    于是「取一批文献」必须同时「传一批附件」，而附件传不上去（体积、配额）
    就整条线卡住。用户的判断：**建库本来就不需要 Zotero**，
    先把文献落到本地，需要哪篇再传。所以正本在这里，Zotero 是它的一份拷贝。
    """
    return os.path.join(paper_raw_dir(key), 'main.pdf')


def local_si(key, ext='pdf'):
    """★ raw/<key>/si.<ext> —— 补充材料原件的本地正本（pdf 或 docx）。"""
    return os.path.join(paper_raw_dir(key), 'si.' + ext.lstrip('.').lower())


def find_local_si(key):
    """本地有没有 SI 原件？有就返回路径，没有返回 ''。

    扩展名不定（Wiley 常给 .docx，RSC 给 .pdf），所以只能去看一眼。
    """
    for ext in ('pdf', 'docx'):
        p = local_si(key, ext)
        if os.path.exists(p):
            return p
    return ''

def meta(key):
    """★ meta.json —— 元数据（标题/DOI/日期/由谁何时生成）。"""
    return os.path.join(paper_dir(key), 'meta.json')

def figures_dir(key, create=False):
    """curated/<key>/figures/ —— 按版面坐标裁好的**整张** Figure（PNG + index.json），给调用方看图用。

    2026-10-04 加：MineRU 的 images/ 是一块块碎图（子图各一张），按图号对照只能指到其中一块
    （Claude Science 实测：「图 1」指到的只是储能模量那一个小图）。整图由 `figure_crop` 裁，派生物，删了可重裁。
    """
    p = os.path.join(paper_dir(key), 'figures')
    if create:
        os.makedirs(p, exist_ok=True)
    return p


def outline(key):
    """★ curated/<key>/outline.json —— 这篇的**骨架**（章节地址 + 类别 + 密度）。

    2026-09-08 加。它是「给模型点菜的菜单」：全文平均 5 万字符（约 1.3 万 token），
    而一个问题真正要看的往往是两三节。先给菜单再按地址取原文，
    读菜单的成本大约是读全文的三十分之一。

    **纯派生**：由 `full.md` 用 `schema.outline` 现算，删了跑一次就有，
    所以它住 curated 而不是 raw（跟 curves.json / chunk_measurements.json 同待遇）。
    """
    return os.path.join(paper_dir(key), 'outline.json')

# ── 方向层：摘要抽出来的记录 ──────────────────────────────────────────
# 为什么另起一个目录而不是塞进 structured/：两边的**代价与可信度**不同 ——
# structured/ 是读全文（+SI）抽的，abstracts/ 只读得到摘要。
# 分目录 = 分档，`tier` 才有据可依。
# （2026-09-07 前这里的理由是「方向层没有 Zotero key，不该伪造一个」；
#  身份证放宽之后那个理由已经不成立了，但**分目录这件事仍然对**，理由换成上面这条。）
# 两个目录、同一种记录格式（schema 的 samples/measurements），
# `tools/paperdb` 两边都读 —— 于是方向层与细节层住进同一张表，靠 tier 分辨。

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

def state_db():
    """state/state.db —— 任务状态库（谁做到哪一步，见 shared/kernel/jobs.py）。

    **可重建**：删掉只丢历史与溯源，产物文件才是真相。
    """
    return os.path.join(STATE, 'state.db')

def teams():
    """state/teams.json —— 研究团队名单（大导 / 小导 / 已独立，每条带依据，**不可重建**）。

    跟 evalset 同类：人工查证 + 用户纠正得来的真相，必须进版本库（2026-10-11 用户定：
    不做自动化流程，由 Claude 查证定名单、用户发现错的再改）。人看的版本在
    docs/reference/团队名单_2026-10-11.md。
    """
    return os.path.join(STATE, 'teams.json')


def topics_db():
    """state/topics.db —— 专题（一个名字 + 一批文献，比如「综述：XX」用到的参考文献）。

    人和 agent（Claude Science）整理出来的，**不可重建**；SQLite 是因为应用、MCP 服务、命令行会同时读写。
    """
    return os.path.join(STATE, 'topics.db')

def oa_index():
    """serving/oa_index.json —— 证据库每篇的作者（含通讯标记、单位）+ 摘要，从 OpenAlex 取一次。

    **可重建**（tools.library.oaindex）。目录卡里没有作者，按通讯作者检索、挂团队都读它。
    """
    return os.path.join(SERVING, 'oa_index.json')


def team_links():
    """serving/team_links.json —— 文章 → 研究团队的对照（tools.library.teams 生成）。

    **可重建**：名单（teams.json）× 每篇的 OpenAlex 作者，重跑一次就有；页面与命令行读它、零网络。
    """
    return os.path.join(SERVING, 'team_links.json')

def last_search():
    """state/_last_search.json —— 上一次「找新文献」的结果暂存。"""
    return os.path.join(STATE, '_last_search.json')

# ── 遍历 ──────────────────────────────────────────────────────────────
def all_keys():
    """列出所有已归档文献的 id（已按契约过滤掉非法目录名）。

    **id 不一定是 Zotero 编号**（2026-09-07 起）：库里可能有他没收藏的文献。
    要挑出「他自己库里那些」，用 `is_zotero_key()` 过滤。

    以 **curated/** 为准：只解析了没精读的半成品不算「已归档」，
    要查那种半成品用 host/doctor/artifact_gaps。
    """
    if not os.path.isdir(CURATED):
        return []
    keys = []
    for name in os.listdir(CURATED):
        if not os.path.isdir(os.path.join(CURATED, name)):
            continue
        try:                       # 认所有合法文献 id，不再只认 Zotero 编号
            keys.append(check_key(name))
        except BadKeyError:
            continue               # 不合契约的目录名（临时文件、手工建的）一律不算
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
# 「哪些顶层目录不是工作流」这份清单，此前在 handover / panel / health_check
# 里各写了一遍（三份，且已经互相不一致）。收在这里，改一次全都生效。
# ① 噪音目录：数据、缓存、构建产物。画目录树、扫源码时一律跳过，
#    但它们**不是**「代码结构」的一部分。
NOISE_DIRS = {
    'data', 'workflow_data', 'n8n_data', 'wf_backup', 'b',
    '__pycache__', '.git', '.venv', 'venv', 'build', 'dist', '.pytest_cache',
    # 两个 egg-info 都要留着：2026-09-08 项目改名 zotero-literature-platform →
    # literature-platform，旧的构建产物在换过的机器上还躺着，只写新名字会漏掉它。
    'zotero_literature_platform.egg-info', 'literature_platform.egg-info',
    # toolbox/toolforge/template/ 里是**带 {{占位符}} 的骨架文件，不是能运行的
    # Python** —— 扫源码的检查（语法、未定义名字）碰到就报语法错误。
    # 2026-09-08 toolbox 并进主仓库后才暴露出来。
    # ⚠ 这是按**名字**跳过的：以后真要在别处放一个正经的 template/ 目录，
    #    得改成按路径跳过，不能直接沿用这一行。
    'template',
}

# ② 非工作流目录 = 噪音 + 代码环 + 模块/文档/测试。
#    用于「自动发现有哪几条工作流线」（体检、面板、交接文件都要这个判断）。
NON_WORKFLOW_DIRS = NOISE_DIRS | {
    'shared', 'host', 'tools',              # 重构后的三个顶层代码包
    'docs', 'tests', 'specs', 'launch',
}


# ③ 顶层代码目录（= 可以 import 的顶层包名）。守卫用它判断「这个 import 是不是自家的」。
CODE_ROOTS = ('shared', 'host', 'tools')

# ③b 要做静态检查（语法 / 未定义名字 / 弹窗 / 硬编码）的顶层目录。
#    **比 CODE_ROOTS 多一个 toolbox** —— 2026-09-08 toolbox 并进主仓库，
#    它是真代码、会被人改，当然要检查。但它**不能进 CODE_ROOTS**：
#    那个常量的含义是「可以 import 的顶层包名」，守卫拿它判断依赖环，
#    而 `toolbox/remote-machine` 带连字符根本不能 import。
#    混为一谈会让架构守卫开始检查一片它管不着的地方。
#    toolbox 也**刻意不受五层规矩约束**（比如 remote.py 要开 SSH 连接，
#    放在 tools/ 里会违反「联网只在 adapters」）—— 它不是平台的能力层。
SCANNED_ROOTS = CODE_ROOTS + ('toolbox',)

# ④ 模块住的环。**带斜杠的相对路径**，因为 kernel/domain/adapters 现在住在 shared/ 底下。
#    依赖只能从上往下：host → tools → shared.domain / shared.adapters → shared.kernel
#    'tools' 也在里面：工具包一样是「有 __init__ + 自测」的块，体检要枚举到它们
#    （R2 窗漏掉这一行的话，搬进 tools/ 的工具会静悄悄地不再被自测覆盖）。
CODE_RINGS = ('shared/kernel', 'shared/domain', 'shared/adapters', 'tools')


def block_dirs():
    """列出四环里所有「模块」（带 __init__.py 的子包），返回 [(环, 名字, 目录)]。

    体检、控制面板、交接文件都要枚举模块。重构前它们各自 glob `modules/*/`，
    模块一搬家三处全瞎 —— 所以这个枚举也收在契约层。
    """
    out = []
    for ring in CODE_RINGS:
        rd = os.path.join(ROOT, *ring.split('/'))
        if not os.path.isdir(rd):
            continue
        for name in sorted(os.listdir(rd)):
            d = os.path.join(rd, name)
            if os.path.isdir(d) and os.path.isfile(os.path.join(d, '__init__.py')):
                out.append((ring, name, d))
    return out


def block_dir(name):
    """按名字找一个模块在哪个环，返回目录；找不到返回 None。"""
    for _ring, n, d in block_dirs():
        if n == name:
            return d
    return None


# 一篇落地后会依次有这些东西（2026-10-23 起不再有精读）。**顺序就是流水线的顺序** ——
# 看「从哪一个开始缺」，就知道它停在哪一步。这份清单即数据契约的一部分。
PAPER_ARTIFACTS = ('fulltext', 'layout', 'meta')


def missing_artifacts(key, kinds=PAPER_ARTIFACTS):
    """这篇文献缺哪些核心产物。返回 (缺的, 有的)。

    契约在这里定义，「该怎么办」的建议属于工具层，不放这儿。
    """
    missing, present = [], []
    for kind in kinds:
        try:
            (present if has(key, kind) else missing).append(kind)
        except Exception:
            missing.append(kind)
    return missing, present
