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
#   serving  随时可重建：对比表、向量库、方向地图。删了跑一条命令就有。
#   state    索引与进度，**不是真相**：state.db / papers.db / 上次检索结果。
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

STRUCTURED = os.path.join(SERVING, 'structured')  # 结构化抽取产物
VECTOR_DB = os.path.join(SERVING, 'vector_db')    # Chroma 向量库（可重建）
DIRECTION = os.path.join(SERVING, 'direction')    # 方向地图：种子/引用网络/聚类
INCOMING = os.path.join(RAW, '_incoming')         # 临时处理区（可清空）

# ── 方向地图（领域全景，非单篇文献）────────────────────────────────
# 与 library/ 的区别：library 按「我读过的文献」组织，direction 按「领域长什么样」
# 组织。前者是资产，后者是**可重建的派生层** —— 删掉再跑一遍命令就有。
#
# ⚠ **按「窄带」分库，不是单例。** 用户会陆续做多条窄带（抗冲、别的方向……），
# 加一条窄带必须是「加一份配置」而不是「改代码」。所以 band 是必填参数，
# 没有默认值 —— 有默认值就会有人忘了传，然后两条窄带的数据混进同一个库。
BAND_RE = re.compile(r'^[a-z0-9][a-z0-9_-]{0,31}$')


class BadBandError(errors.BadInputError):
    """窄带 id 不合法。必须是小写字母数字下划线短横（做目录名要安全）。"""


def check_band(band):
    """校验窄带 id。不合法就抛 BadBandError。"""
    b = str(band or '').strip().lower()
    if not BAND_RE.match(b):
        raise BadBandError(
            f'不是合法的窄带 id: {band!r}（小写字母开头，只含 a-z 0-9 _ -，最长 32 位）')
    return b


def direction_dir(band, create=False):
    """<direction>/<band>/ —— 一条窄带的全部产物。"""
    d = os.path.join(DIRECTION, check_band(band))
    if create:
        os.makedirs(d, exist_ok=True)
    return d


def direction_db(band):
    """某条窄带的 SQLite 库：论文 / 引用边 / 种子 / 聚类都在这一个文件里。"""
    return os.path.join(direction_dir(band), 'map.db')


def direction_spec(band):
    """某条窄带的定义文件（检索式、关键词、边界判据）。加窄带就是加这个。"""
    return os.path.join(direction_dir(band), 'band.json')


def direction_file(name, band, create_dir=False):
    """某条窄带目录下的其它产物（导出的 json、网页版地图等）。"""
    return os.path.join(direction_dir(band, create=create_dir), name)


def direction_bands():
    """现有的窄带 id 列表（目录里有 map.db 或 band.json 的才算）。"""
    if not os.path.isdir(DIRECTION):
        return []
    out = []
    for n in sorted(os.listdir(DIRECTION)):
        d = os.path.join(DIRECTION, n)
        if os.path.isdir(d) and (os.path.isfile(os.path.join(d, 'map.db'))
                                 or os.path.isfile(os.path.join(d, 'band.json'))):
            out.append(n)
    return out


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
# 加一种来源 = 往 `_ID_PREFIXES` 里加一个前缀，不用改别的地方。
#
# **对账靠 DOI，不靠 id**：同一篇文献在不同来源下可能拿到不同 id，
# 谁跟谁是同一篇由 `papers.doi` 回答（见 tools/paperdb）。
ZOTERO_KEY_RE = re.compile(r'^[A-Z0-9]{8}$')
OA_ID_RE = re.compile(r'^W\d{4,12}$')
_ID_PREFIXES = ('doi',)
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
        f'或 doi_ 开头的 id —— 用 paths.paper_id_from_doi() 生成）')


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


def curves(key):
    """★ curated/<key>/curves.json —— 从图上抠下来的曲线数值（tools.digitize 的产物）。

    为什么要落盘（2026-09-06）：此前 `digitize_paper()` 读完图就把结果返回给调用方，
    **谁也没存** —— 每问一次同一张图就要再花一次云端视觉模型的钱，
    而且抠出来的数据进不了查询库。图只需读一次，数值应该跟精读产物一样长期留着。
    """
    return os.path.join(paper_dir(key), 'curves.json')


def outline(key):
    """★ curated/<key>/outline.json —— 这篇的**骨架**（章节地址 + 类别 + 密度）。

    2026-09-08 加。它是「给模型点菜的菜单」：全文平均 5 万字符（约 1.3 万 token），
    而一个问题真正要看的往往是两三节。先给菜单再按地址取原文，
    读菜单的成本大约是读全文的三十分之一。

    **纯派生**：由 `full.md` 用 `schema.outline` 现算，删了跑一次就有，
    所以它住 curated 而不是 raw（跟 curves.json / chunk_measurements.json 同待遇）。
    """
    return os.path.join(paper_dir(key), 'outline.json')


def chunk_measurements(key):
    """★ curated/<key>/chunk_measurements.json —— 拆段扫正文抽到的数值。

    为什么单独一份、而不是并进 `structured/<key>.json`（2026-09-07）：
    那份是「整篇过一次大模型」的产物，重抽一次就整个覆盖。
    拆段扫正文是**另一条流水线、另一种代价**（几百次小请求），
    混在一起会出现「重抽一次，几百次小请求的成果没了」——
    而且没人看得出来它没了。分开放，两条线各自可重跑。

    跟 `curves()` 是同一个道理：都是花过钱才拿到的派生数据，都由 paperdb 编进索引。
    """
    return os.path.join(paper_dir(key), 'chunk_measurements.json')


# ── 结构化抽取产物 ────────────────────────────────────────────────────
def structured(key):
    """★ structured/<key>.json —— 单篇的结构化字段。"""
    return os.path.join(STRUCTURED, check_key(key) + '.json')


def structured_backup(stamp):
    """backup/structured_<stamp>/ —— 覆盖已有抽取结果之前的备份落点。

    为什么要有（踩坑 #16）：曾经拿低档结果覆盖了高档结果，丢了真数据。
    重抽前先把旧的挪进这里，出事能原样搬回来。
    """
    return os.path.join(BACKUP, 'structured_' + str(stamp))


def journals():
    """★ serving/journals.json —— 期刊分级（tools.curate.journals 的产物）。

    为什么单独一份而不是塞进每篇记录：刊是**共享的**，188 篇可能只涉及 60 本刊；
    分级还会随指标更新而变，塞进每篇就得改 188 个文件。
    """
    return os.path.join(SERVING, 'journals.json')


# ── 方向层：摘要抽出来的记录 ──────────────────────────────────────────
# 为什么另起一个目录而不是塞进 structured/：两边的**代价与可信度**不同 ——
# structured/ 是读全文（+SI）抽的，abstracts/ 只读得到摘要。
# 分目录 = 分档，`tier` 才有据可依。
# （2026-09-07 前这里的理由是「方向层没有 Zotero key，不该伪造一个」；
#  身份证放宽之后那个理由已经不成立了，但**分目录这件事仍然对**，理由换成上面这条。）
# 两个目录、同一种记录格式（schema 的 samples/measurements），
# `tools/paperdb` 两边都读 —— 于是方向层与细节层住进同一张表，靠 tier 分辨。
ABSTRACTS = os.path.join(SERVING, 'abstracts')
_OA_RE = OA_ID_RE


def check_work_id(work_id):
    """校验 OpenAlex 作品 id（`W2741809807`）。允许整条 URL，返回短 id。"""
    w = str(work_id).strip().rsplit('/', 1)[-1].upper()
    if not _OA_RE.match(w):
        raise BadKeyError('不是合法的 OpenAlex 作品 id: %r（应形如 W2741809807）' % (work_id,))
    return w


def abstract_record(work_id):
    """★ serving/abstracts/<Wxxx>.json —— 一篇公开文献从摘要抽出来的记录。"""
    return os.path.join(ABSTRACTS, check_work_id(work_id) + '.json')


def all_work_ids():
    """列出所有已抽过摘要的作品 id。"""
    if not os.path.isdir(ABSTRACTS):
        return []
    out = []
    for name in os.listdir(ABSTRACTS):
        if name.endswith('.json') and _OA_RE.match(name[:-5].upper()):
            out.append(name[:-5].upper())
    return sorted(out)


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


def state_db():
    """state/state.db —— 任务状态库（谁做到哪一步，见 shared/kernel/jobs.py）。

    **可重建**：删掉只丢历史与溯源，产物文件才是真相。
    """
    return os.path.join(STATE, 'state.db')


def papers_db():
    """state/papers.db —— 文献查询库（结构化字段 + 能比大小的性能数值）。

    **可重建**：由 `structured/*.json` 整库生成（见 tools/paperdb），
    删掉零代价。真相永远是那些 JSON。
    """
    return os.path.join(STATE, 'papers.db')


def evalset():
    """state/evalset.json —— 精读质量评测集（用户的人工评价，**不可重建**）。

    住在 state 层但**必须进版本库** —— 这一层别的东西都是索引，只有它是真相。
    """
    return os.path.join(STATE, 'evalset.json')


def last_search():
    """state/_last_search.json —— 上一次「找新文献」的结果暂存。"""
    return os.path.join(STATE, '_last_search.json')


def junk_list(ext='json'):
    """state/待删条目清单.<ext> —— 库房维护的待删清单。"""
    return os.path.join(STATE, '待删条目清单.' + ext)


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

# ② 非工作流目录 = 噪音 + 代码环 + 积木/文档/测试。
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

# ④ 积木住的环。**带斜杠的相对路径**，因为 kernel/domain/adapters 现在住在 shared/ 底下。
#    依赖只能从上往下：host → tools → shared.domain / shared.adapters → shared.kernel
#    'tools' 也在里面：工具切片一样是「有 __init__ + 自测」的块，体检要枚举到它们
#    （R2 窗漏掉这一行的话，搬进 tools/ 的工具会静悄悄地不再被自测覆盖）。
CODE_RINGS = ('shared/kernel', 'shared/domain', 'shared/adapters', 'tools')


def block_dirs():
    """列出四环里所有「积木」（带 __init__.py 的子包），返回 [(环, 名字, 目录)]。

    体检、控制面板、交接文件都要枚举积木。重构前它们各自 glob `modules/*/`，
    积木一搬家三处全瞎 —— 所以这个枚举也收在契约层。
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
    """按名字找一块积木在哪个环，返回目录；找不到返回 None。"""
    for _ring, n, d in block_dirs():
        if n == name:
            return d
    return None


# 精读一篇会依次产出这些东西。**顺序就是流水线的顺序** ——
# 看「从哪一个开始缺」，就知道它死在哪一步。这份清单即数据契约的一部分。
PAPER_ARTIFACTS = ('fulltext', 'layout', 'meta', 'summary')


def missing_artifacts(key, kinds=PAPER_ARTIFACTS):
    """这篇文献缺哪些核心产物。返回 (缺的, 有的)。

    半成品最常见的来源是精读中途被打断（踩坑 #61）。
    契约在这里定义，「该怎么办」的建议属于工具层，不放这儿。
    """
    missing, present = [], []
    for kind in kinds:
        try:
            (present if has(key, kind) else missing).append(kind)
        except Exception:
            missing.append(kind)
    return missing, present


def is_workflow_dir(name):
    """这个顶层目录名算不算一条「工作流线」（用于体检、面板、交接文件的自动发现）。"""
    return (name not in NON_WORKFLOW_DIRS
            and not name.startswith(('.', 'zotero_backup'))
            and not name.endswith('.egg-info'))
