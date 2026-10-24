# -*- coding: utf-8 -*-
"""host.mcp.science · 给 Claude Science 的精简入口（HTTP 端点 `/science`）。

## 为什么单开一个（2026-09-29 用户定）

用户的判断：**Claude 这样的模型不需要一堆规矩，能拿到文献就够了。**
Claude Science 自己会检索（它有 OpenAlex），它缺的是：付费墙后面的全文（这台主力机的
校园网出口 + 过过人机验证的浏览器 + MineRU 解析）、以及用户这 1100 篇证据库的索引与向量库。

## 它怎么连进来（2026-09-29 实测出来的，别再猜）

Claude Science 的 Remote 连接器只收公网 https；本机命令连接器跑在它的沙箱里（读不到 D 盘、
**硬性禁止连回环地址**）。唯一可用的是它的 **SSH 算力**（B 机 WSL 的 science 账号）：
`~/bin/litplatform` 经一把受限钥匙登 B 的 Windows，只会跑 `bridge.py` → 本端点。
所以对它来说**每次调用 = 一次 SSH 命令**，它读的是**原始 JSON-RPC 回复**。

## v0.2（2026-09-30）：按它自己的实测评估改（桌面 litplatform_assessment.md）

它的原话要点：回复里的每个字都进它的上下文；排好版的中文它得用正则抠 id；
20 篇要拆 7 轮「提交 → 轮询」；轮询每次都带一整份菜单。于是：

- **每个工具都给 `structuredContent`**，文字只留一两行摘要。配套 `litcall.py` 只打印结构化那份。
- **itemKey 一律可给 DOI**（含 `https://doi.org/…`、`doi:` 前缀），服务端对账。
- `paper_fulltext` 一次最多 25 篇（原来 3 篇是接口层的限制，不是风控要求；风控靠的是
  串行 + 20 秒间隔 + 同时只一个作业，这三条一条没松）。
- `fulltext_status` 加 `wait_s`（等到有进展再回，最多 30 秒）与 `brief`（默认只回状态，不带菜单）。
- `library_section` 可批量：`requests=[{itemKey, sectionId, si}]`。
- 新增 `library_manifest`：全库清单写成 JSON 文件，回路径 —— 它在 B 上自己做集合运算。
- `paper_files` 多给图片目录与「图号 → 图片文件」对照。
- `library_refs` 加回来（09-29 我以为它用 OpenAlex 就够、删了，它明说要）。
- 借 `paperdb_sql` / `paperdb_measurements`：抽出来的数值库，只读。

## 唯一的规矩在服务端

取全文串行、每篇隔 20 秒、**同一时刻只许一个取全文作业**。出版商风控封的是整个学校的出口 IP。
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass

import io
import json
import re
import time

from host.mcp.stdio import MCPStdioServer

ENDPOINT = '/science'
NAME = 'literature-science'
VERSION = '0.15.2'
# v0.3（2026-10-04，桌面 literature_platform_spec_for_agent.md 的 P0 + 部分 P1/P2）：
#   解析分两层（PDF 到手几秒出快速文本层，MineRU 后台补表格）· 结果带 code/retryable/stage/tier/route ·
#   撞人机验证同家暂缓、别家照跑、主力机桌面弹提醒、fulltext_retry 续跑 · 任何返回超 50 KB 落文件只回路径 ·
#   library_section 加 offset 分页、表格出 CSV/JSON · 提交前问 Crossref，无效 DOI 当场 NOT_FOUND ·
#   新增 paper_status（一次看清一批的档位）· outline 带 tier 与图片路径
# v0.3.1（同日，它的实测报告 literature_platform_eval_2026-10-04.md）：
#   节号随 text→structured 升级会错位 → library_section 收 title / quote 找回现在的位置（remapped_from）、带 rev ·
#   图号对照改成整张图（版面坐标裁，image_kind=full）· 新增 figure_image（小 JPEG 直接回，不传文件）·
#   检索滤掉只有标题的碎片、per_paper · 表格 CSV 带图注 · 库内搜索不分横线写法 · ping 报自己的版本
# v0.4（2026-10-08 用户定）：chemdb_search / chemdb_page —— 借主力机浏览器搜 SciFinder / Reaxys、读结果页文字。
#   它进不去这两个库（学校订阅 + 个人登录），人一条条点开筛又太慢。按人的频率：两次至少隔 CHEMDB_GAP 秒、
#   每个库每天至多 CHEMDB_DAILY 次（服务端强制）。CAS 条款禁止脚本代替手工 —— 用户知情后决定小量用。
# v0.5（同日，Claude Science 用了两次后的建议）：结果解析成字段（items / facets / ai_summary / query_interpretation）·
#   Reaxys 每页调到最大 · 当天同一检索走缓存不扣次数 · chemdb_status（不碰网站）· SciFinder 筛选 / 排序 / 按原样搜 ·
#   SciFinder 按标题补 DOI、每条标 in_library / tier · Reaxys 预览拆成子检索列表 · AI 摘要没生成完标 complete=false
# v0.6（同日，用户：「最常用的是 CAS 号查精确结构、画大致结构查」）：structure（SMILES）+ match（exact / substructure /
#   similarity）走两个库的画图板；CAS 号 / 结构式回物质列表；CAS 号要文献时先落到物质再取它的文献
# v0.7（同日，Claude Science 用 0.6.2 跑了 6 次后的报告）：异步（等 25 秒，没好回 job_id，chemdb_result 取）·
#   SciFinder within（在结果内检索，CAS 号 + 主题词）· Reaxys CAS 号对应多个物质时挑文献最多的、候选全列 ·
#   结构式要文献直接开文献集 · 分面计数不再出 NaN · 界面字（Select Substance / Retrieve CAS RN / No title）不进字段 ·
#   Reaxys 老文献年份信出处 · 按标题补的 DOI 再对刊名与卷（德文版 / 国际版）·
#   Reaxys 的 CAS 号落到冷门条目（硼酸）时，经 PubChem 换成结构式按原样搜
# v0.8（2026-10-09 用户定）：polyinfo_* —— NIMS 聚合物数据库 PoLyInfo，同一个浏览器、同一套额度 / 缓存 / 作业。
#   用户原话「不是要批量抓取数据，只是省去我截图的过程，需要我点的时候我点一下」。条款禁止抓取、网站自带人机验证，
#   所以比 SciFinder 更保守：两次至少隔 POLYINFO_GAP 秒、每天 POLYINFO_DAILY 次；撞验证码回 CAPTCHA_REQUIRED +
#   主力机桌面弹提醒，人点完用 polyinfo_current 读那一页（不重查、不扣次数）。验证码永远是人填。
# v0.9（同日，用户「需要的都可以用起来」）：cnki_* —— 中国知网（学位论文 / 期刊 / 会议 / 中国专利），学校按 IP 授权。
#   同一套账本 / 缓存 / 作业；两次至少隔 CNKI_GAP 秒、每天 CNKI_DAILY 次；拼图验证码同 PoLyInfo 的处理（人拖、cnki_current 读）。
#   只读：检索、翻页、摘要页（含学位论文的章节目录）。不下载全文 —— 知网对批量下载封整个学校的出口 IP。
# v0.10（同日）：ccdc_* / jcr_journal / scopus_* —— CCDC Access Structures、JCR、Scopus。三家条款都禁程序访问或把数据交给 AI
#   （原文见 docs/变更记录.md 2026-10-09）；用户知情后定：「跟 SciFinder 一样省去截图……遇到人机验证我都会来点，也只做少量需要的检索」。
#   所以一次一页、只读、不下载、额度更低；JCR 结果不写进期刊分级表。
# v0.11（2026-10-11 用户定）：chemdb_search kind=suppliers —— SciFinder 的 CAS 商业来源（几百家试剂商目录）：
#   每家的规格与价格、纯度、库存、几周发货、国家、供应商商品页网址，另给 summary（各币种最便宜每克价、国家分布）。
#   设计实验时比药品价格、好不好买、找同类替代品，不再凭记忆。同一套额度 / 间隔 / 缓存（SciFinder 条款用户 10-08 已知情）。
# v0.12（同日，用户定）：tansoole_search / tansoole_page —— 探索平台（泰坦科技，他实际买药的地方）：品牌、规格、纯度、
#   货期（现货 / 几个工作日 / 期货）、能买还是要询价。价格是网站的防抓取字体，用户知情后定不读（价格走 kind=suppliers）。
# v0.13（2026-10-12，Claude Science 跑 BAPMA 扩链方案时报的三处）：chemdb_substance —— Reaxys 一个物质的物性表
#   （沸点 / 密度 / 折射率 / pKa……按 Reaxys 的分组，每行数值 + 条件 + 出处 / DOI），原来 kind=substances 只给「41 条物性」这个数。
#   Reaxys 关键词里的化学名被它的 AI 检索换成结构式时警告（structure_injected），能挑不带结构的组就挑；
#   取全文拿回来不是 PDF 时看页面分辨：验证页 → CAPTCHA_REQUIRED、付费墙 → NOT_SUBSCRIBED、分不清 → NOT_PDF（不再一律叫人去点验证码）。
# v0.13.1（同日实测）：物性表一组超过 7 行时点「Show all」（BAPMA 的 pKa 组 15 条只读到 7 行）；读不全的组标 group_partial、complete=false。
# v0.13.2（同日，58 篇批量取全文的报告）：页面打不开（断连 / 90 秒超时）改报 NETWORK_ERROR（可重试），不再是 NOT_FOUND；
#   连着 3 篇网络失败就先停手，整批跑完歇 3 分钟统一补试。World Scientific「No Access」、T&F「Purchase options」认成 NOT_SUBSCRIBED。
# v0.14（2026-10-12 用户定「放开」）：cnki_download —— 知网一篇的 PDF（摘要页点「PDF下载」），存进导出文件夹回路径。
#   一次一篇、两次至少隔 CNKI_PDF_GAP 秒、每天 CNKI_PDF_DAILY 篇（默认 5，控制面板可改），撞拼图就停等人拖。
# v0.14.1（同日，Claude Science 头一回用就 4 篇全挡）：知网整页「安全验证」认成 CAPTCHA_REQUIRED（原来报 NO_PDF_LINK、不弹提醒）；
#   下载额度只数真下到的（ONLY_OK_COUNTS），没下到的只占间隔、不扣篇数。
# v0.14.2（2026-10-13）：cnki_download 先找浏览器里已经开着的同一篇（人刚过完验证的那页），在它上面点下载，不再新开一页又被验证。
# v0.14.3（同日，用户实测「手动检索不弹」）：cnki_download 不给 n / url = 下人在浏览器里打开着的那篇（人打开、程序取）。
# v0.15.0（2026-10-15 用户提）：topic_add / topic_remove / topic_list / topic_items —— 专题：把写综述用到的一批文献放进一个有名字的组，用户在文献库应用里按专题筛。
# v0.15.1（2026-10-15）：cnki_download 下到的直接收进证据库（按页面 / PDF 里的 DOI 落正本 + 登记标题作者刊名年份），
#   回 library_id —— 原来只落在导出文件夹，专题里加不进去。没有 DOI 的仍只在文件夹（warnings 说明）。
# v0.15.2（同日）：没有 DOI 的按知网文件名起 id（cnki_slgy202603021）照样收进证据库；修知网「被挡」误报（屏幕外拼图弹层的字）。

# 原样借用的（输出本来就合适）
BORROW = ()     # 2026-10-04 用户定：只给它做不到的（取全文）。数值库它自己会抽，不借了；ping 自己挂

MAX_DOIS = 25          # 一次提交的上限；与 getpdf 单次最多 25 篇的老约定一致
MAX_WAIT = 30          # fulltext_status 最多等多久（HTTP 服务一次只跑一个调用，等太久会堵别人）
STALE_SECS = 600       # 进度文件多久没动就当那个作业已经死了
STALL_SECS = 300       # 同一篇处理超过这么久没进展 → 状态里标 stalled（下载各步自带超时，正常到不了这么久）
CHEMDB_GAP = 30        # SciFinder / Reaxys 两次操作至少隔几秒（人的速度；不够就等，最多等这么久）
CHEMDB_DAILY = 20      # 每个库每天最多几次（搜索和翻页都算）；控制面板 CHEMDB_DAILY 可改
POLYINFO_GAP = 45      # PoLyInfo 两次至少隔几秒：2026-10-09 隔 30 秒连查 5 次就弹了验证码
POLYINFO_DAILY = 15    # PoLyInfo 每天最多几次（检索 / 样品列表 / 样品详情各算一次）；控制面板 POLYINFO_DAILY 可改
CNKI_GAP = 30          # 知网两次至少隔几秒
CNKI_DAILY = 30        # 知网每天最多几次（检索 / 翻页 / 摘要页各算一次）；控制面板 CNKI_DAILY 可改
CNKI_PDF_GAP = 60      # 知网下载全文两次至少隔几秒（比检索慢：下载是知网最盯的动作）
CNKI_PDF_DAILY = 5     # 知网每天最多下几篇全文；控制面板 CNKI_PDF_DAILY 可改（2026-10-12 用户定放开，量小）
NO_CHARGE = ('NOT_FOUND', 'NO_SEARCH', 'LOGIN_REQUIRED')   # 这几种结果没真去网站查，不扣次数
ONLY_OK_COUNTS = ('cnki_pdf',)   # 额度数的是「下到了几篇」：没下到（验证页挡住、只有 CAJ……）只占间隔，不扣篇数
CCDC_GAP, CCDC_DAILY = 45, 15        # CCDC：条款明禁程序访问，用户知情后定小量用 —— 最保守
JCR_GAP, JCR_DAILY = 20, 30          # JCR：一次只查一本刊
SCOPUS_GAP, SCOPUS_DAILY = 30, 20    # Scopus：一次一页
TANSOOLE_GAP, TANSOOLE_DAILY = 30, 30   # 探索平台：一次一页、只读明文栏（价格不读）；控制面板 TANSOOLE_DAILY 可改
MAX_OUT = 50000        # 一次返回的结构化数据上限（字节）：调用方的远程命令输出过 64 KB 就被截断（2026-10 实测）

INSTRUCTIONS = """\
材料学研究者（聚硼硅氧烷 / 动态键弹性体）的文献证据库，约 1100 篇，跑在他校园网里的主力机上。
检索、读参考文献、抽数据你自己来；这里只给你做不到的：付费全文（学校订阅）取回并解析，以及他手上这些全文的查找、向量检索、按节读、看图。
每个工具都返回 structuredContent（JSON）；itemKey 可以给证据库 id，也可以直接给 DOI。
取全文：串行、每篇隔 20 秒、同时只跑一个作业（服务端强制，保护全校出口 IP），一篇约 1 分钟。
PDF 到手几秒内先出 tier=text（本地抽字，可按节读、无表格结构）；MineRU 后台补成 tier=structured（含表格）。
每篇结果带 code（OK / CAPTCHA_REQUIRED / NOT_SUBSCRIBED / NOT_FOUND / NO_PDF_LINK / NOT_PDF / PARSE_PENDING /
PARSE_FAILED / NETWORK_ERROR / NOT_FETCHED）与 retryable；CAPTCHA_REQUIRED 等人在主力机浏览器点完后用 fulltext_retry。
NOT_PDF = 拿回来的不是 PDF、页面上既不是验证页也看不到付费墙，分不清 —— 别叫人去点验证码。
任何返回超过 50 KB 会写成文件、只回 spilled 路径。
文件路径是 B 机 WSL 路径（/mnt/d/...），你的 SSH 算力能直接读。
SciFinder / Reaxys：先 `chemdb_status`（不扣次数），再 `chemdb_search` 回第 1 页的结构化列表，`chemdb_page` 翻页。
一个物质的物性数值（沸点、密度、pKa……带出处）：`chemdb_substance` query=CAS 号（只 Reaxys，一次算一次检索）。
药品价格 / 好不好买 / 替代品：`chemdb_search` db=scifinder kind=suppliers（CAS 号最准），回各家规格价格、纯度、库存、发货、国家。
用户实际在探索平台（泰坦）买药：`tansoole_search` 看那里有哪些品牌、规格、纯度、现货还是要等几个工作日（不含价格）。
按人的频率：两次至少隔 30 秒、每个库每天有上限（quota）；当天同一检索走缓存不扣次数 —— 先想好检索词，别试错式地连搜。
code=LOGIN_REQUIRED 时请人在主力机浏览器里登录。
PoLyInfo（聚合物实测性质）：`polyinfo_search` → `polyinfo_samples` → `polyinfo_sample`（组成、出处、原文的组成–性质表）。
更保守：两次至少隔 45 秒、每天 15 次。样品详情页网站每次要人机验证：回 CAPTCHA_REQUIRED 时等人在主力机浏览器点完，
再用 `polyinfo_current` 读那一页（不扣次数）。它的条款禁止批量获取 —— 只查回答眼前问题需要的那几条。
中国知网（中文硕博论文、中文期刊、中国专利）：`cnki_search`（kind=thesis/phd/master/journal/patent…）→ `cnki_page` 翻页 →
`cnki_detail`（摘要、关键词、导师、学位论文的整本目录、专利主权项）。两次至少隔 30 秒、每天 30 次；拼图验证码同上（cnki_current）。
全文：`cnki_download`（n 或 url）一次一篇，存成 PDF 回路径；两次至少隔 60 秒、每天 5 篇 —— 只下眼前真要读的。
CCDC（单个晶体结构）`ccdc_search` / `ccdc_detail`；JCR（一本刊的 JIF 与分区）`jcr_journal`；Scopus（检索、被引列表）`scopus_search` /
`scopus_citing` / `scopus_page`。这三家条款都不许程序批量取 —— 只查眼前问题需要的那一两条；额度见 `webdb_status`。
专题（给用户看的分组）：`topic_add` 把一批文献（DOI 或 id）放进一个有名字的专题，比如「综述：动态硼酸酯弹性体」，
每篇可带一句 note（如「第 3 节：自修复机理」）；用户在他的文献库应用里按专题一筛就能看到。`topic_list` / `topic_items` 看，
`topic_remove` 拿掉（文献本身不动）。只能放证据库里已有的，没有的回在 missing 里 —— 先 paper_fulltext 取进来再加。"""

_DOI_PREFIX = re.compile(r'(?i)^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)')


# ══════════════════════════════════════════════════════════════════════
# 小工具
# ══════════════════════════════════════════════════════════════════════

def _progress_path():
    from shared.kernel import paths
    return paths.runtime('fulltext_progress.json')


def _read_progress(path=None):
    path = path or _progress_path()
    if not os.path.exists(path):
        return None
    try:
        return json.load(io.open(path, encoding='utf-8'))
    except Exception:
        return {'total': 0, 'finished': 0, 'done': False, 'results': [], '_writing': True}


def running_job(path=None, now=None):
    """有没有一个取全文作业正在跑 → 给人看的一句话，或 ''。

    判据：进度文件存在、`done` 为假、而且最近 STALE_SECS 秒内还写过（死掉的作业不挡路）。
    """
    path = path or _progress_path()
    d = _read_progress(path)
    if d is None:
        return ''
    if d.get('_writing'):
        return '有一个取全文作业正在写进度'
    if d.get('done'):
        return ''
    if (now or time.time()) - os.path.getmtime(path) > STALE_SECS:
        return ''
    return '上一个取全文作业还在跑（%d/%d 篇）' % (d.get('finished', 0), d.get('total', 0))


def to_wsl(path):
    """Windows 路径 → WSL 里看到的路径（D:\\a\\b → /mnt/d/a/b）。不是盘符路径就原样返回。"""
    p = (path or '').replace('\\', '/')
    if len(p) >= 2 and p[1] == ':':
        return '/mnt/' + p[0].lower() + p[2:]
    return p


def norm_doi(k):
    """去掉 https://doi.org/ 与 doi: 前缀；不是 DOI 返回 ''。"""
    k = _DOI_PREFIX.sub('', (k or '').strip())
    return k if k.startswith('10.') and '/' in k else ''


def _resolve(k):
    """itemKey → 证据库 id。可以是 id，也可以是 DOI（带不带 doi.org 前缀都行）。"""
    from shared.kernel import catalog, paths
    k = (k or '').strip()
    doi = norm_doi(k)
    if doi:
        pid = catalog.find(doi)
        if not pid:
            raise ValueError(f'证据库里没有 DOI {doi}（用 paper_fulltext 把它拿进来）')
        return pid
    try:
        return catalog.resolve(k)          # 旧的 Zotero 编号也认（2026-10-12 起目录改成 doi_ 编号）
    except paths.BadKeyError:
        raise ValueError(f'「{k}」既不是证据库 id 也不是 DOI')


def _out(text, data):
    return {'text': text, 'structured': data}


# ══════════════════════════════════════════════════════════════════════
# 库：有没有 / 全库清单 / 按意思找
# ══════════════════════════════════════════════════════════════════════

# 不带 in_zotero：Claude Science 那条路不跟 Zotero 扯上关系（2026-09-30 用户定）
_CARD_KEYS = ('id', 'doi', 'title', 'year', 'journal', 'pdf', 'si',
              'fulltext', 'si_fulltext')


def _card(r):
    return {k: r.get(k) for k in _CARD_KEYS}


def _db_search(a):
    from tools import library
    q = (a.get('query') or '').strip()
    doi = norm_doi(q)
    rows = library.db_search(doi or q, limit=int(a.get('limit') or 25))
    return _out('%d 篇匹配「%s」' % (len(rows), q), {'papers': [_card(r) for r in rows]})


def _topic_add(a):
    from tools.library import topics
    refs = [x for x in (a.get('refs') or []) if str(x).strip()]
    r = topics.add(a.get('topic') or '', refs, note=(a.get('note') or '').strip(), by='Claude Science',
                   topic_note=a.get('topic_note'))
    return _out('专题「%s」：新加 %d 篇，原来就在 %d 篇，库里没有 %d 篇'
                % (r['topic'], len(r['added']), len(r['already']), len(r['missing'])), r)


def _topic_remove(a):
    from tools.library import topics
    r = topics.remove(a.get('topic') or '', [x for x in (a.get('refs') or []) if str(x).strip()])
    return _out('专题「%s」：拿掉 %d 篇' % (r['topic'], len(r['removed'])), r)


def _topic_list(a):
    from tools.library import topics
    ts = [{'name': t['name'], 'note': t['note'], 'n': t['n'], 'created_by': t['created_by']} for t in topics.list_topics()]
    return _out('%d 个专题' % len(ts), {'topics': ts})


def _topic_items(a):
    from tools.library import topics
    from shared.kernel import catalog
    t = topics.get(a.get('topic') or '')
    if t is None:
        raise ValueError('没有专题「%s」' % a.get('topic'))
    its = topics.items(t['name'])
    for x in its:
        rec = catalog.record(x['pid'])
        x.update(doi=rec.get('doi') or '', title=' '.join((rec.get('title') or '').split())[:200], year=rec.get('year'))
    return _out('专题「%s」%d 篇' % (t['name'], len(its)), {'topic': t['name'], 'note': t['note'], 'items': its})


def dedupe_hits(rows):
    """同一篇存了两份（Zotero 编号与 doi_ 各一份）时，同一段会出现两次 —— 按 DOI + 开头去重。"""
    seen, out = set(), []
    for r in rows:
        key = ((r.get('doi') or r.get('id') or '').lower(), (r.get('text') or '')[:200])
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


MIN_HIT_CHARS = 80     # 比这短的命中多半只是一行小标题（"Molecular dynamics simulation"），没有可读的内容


def filter_hits(rows, n, per_paper=0, min_chars=MIN_HIT_CHARS):
    """去重 → 去掉只有一行标题的碎片 → 每篇最多 per_paper 段（0 = 不限）→ 取前 n。"""
    out, per = [], {}
    for r in dedupe_hits(rows):
        if len((r.get('text') or '').strip()) < min_chars:
            continue
        k = (r.get('doi') or r.get('id') or '').lower()
        if per_paper and per.get(k, 0) >= per_paper:
            continue
        per[k] = per.get(k, 0) + 1
        out.append(r)
        if len(out) >= n:
            break
    return out


def _retrieve(a):
    from tools import library
    n = int(a.get('n') or 8)
    per_paper = int(a.get('per_paper') or 0)
    # 多取一些候选：碎片和同篇超额的要筛掉（2026-10-04 Claude Science：滑环查询 5 条里 3 条同一篇）
    rows = library.retrieve(a['query'], n=n * (4 if per_paper else 2) + 4, where=a.get('where') or 'all')
    rows = filter_hits(rows, n, per_paper)
    return _out('%d 段最相近「%s」' % (len(rows), a['query']), {'hits': rows})


# ══════════════════════════════════════════════════════════════════════
# 读：骨架 / 节（可批量）/ 参考文献 / 文件
# ══════════════════════════════════════════════════════════════════════

def _outline(a):
    from tools import library
    pid = _resolve(a.get('itemKey'))
    d = library.outline(pid)
    if not d.get('available'):
        return _out('%s：%s' % (pid, d.get('why', '没有骨架')), {'itemKey': pid, 'available': False})
    slim = lambda o: {
        'sections': [{k: s.get(k) for k in ('id', 'title', 'kind', 'chars', 'n_numbers', 'n_tables', 'n_figures')}
                     | ({'paras': [{k: p[k] for k in ('id', 'chars', 'head')} for p in s['paras']]}
                        if s.get('paras') else {})
                     for s in o.get('sections') or []],
        'tables': [{k: t.get(k) for k in ('id', 'ref', 'caption', 'section', 'n_rows', 'n_cols')}
                   for t in o.get('tables') or []],
        'figures': [{k: f.get(k) for k in ('id', 'ref', 'caption', 'section')} for f in o.get('figures') or []],
        'chars': (o.get('stats') or {}).get('chars', 0)}
    from tools.getpdf import fulltext as F
    data = {'itemKey': pid, 'available': True, 'main': slim(d), 'tier': F.tier_of(pid), 'rev': text_rev(pid),
            'cite_hint': '节号会随解析升级变（text → structured）；记出处请连 title 一起记，'
                         '取时传 title（或 quote 一句原文）就能找回，回复里有 remapped_from'}
    # 图注带上图片路径：整张图（full）优先，裁不出来的才给 MineRU 碎图（panel）；快速文本层没有图
    imgs = _figure_map(pid)
    for f in data['main']['figures']:
        f['image'], f['image_kind'] = imgs.get(_fig_key(f.get('ref')), ('', ''))
    if d.get('si'):
        data['si'] = slim(d['si'])         # SI 的地址与正文同形（s4.p1），取时传 si=true
        data['si_tier'] = F.tier_of(pid, si=True)
    return _out('%s：正文 %d 节%s' % (pid, len(data['main']['sections']),
                                   '，另有 SI（取 SI 的节传 si=true）' if d.get('si') else ''), data)


def _fig_key(ref):
    """'Figure 3' / 'Fig. 3b' / 'Scheme 1' → 'figure 3' / 'scheme 1'（对图号用）。"""
    r = re.sub(r'\s+', ' ', (ref or '').lower().replace('fig.', 'figure').replace('fig ', 'figure ')).strip()
    return re.sub(r'(\d)[a-z]$', r'\1', r.rstrip('.'))


def _figure_map(pid):
    """这篇「图号 → (图片 WSL 路径, 'full' | 'panel')」。

    先用按版面坐标裁好的**整张图**（`full_figures`）；裁不出来的号才退回 MineRU 的碎图（`panel`，
    多子图的 Figure 只指到其中一块 —— 2026-10-04 Claude Science 实测「图 1」只指到一个小图）。
    """
    from shared.kernel import paths
    out = {}
    md, img = paths.fulltext(pid), paths.images_dir(pid)
    if os.path.exists(md) and os.path.isdir(img):
        text = io.open(md, encoding='utf-8').read()
        out = {_fig_key(f['ref']): (to_wsl(f['image']), 'panel') for f in figure_images(text, img)}
    for f in full_figures(pid):
        if f.get('ref'):
            out[_fig_key(f['ref'])] = (to_wsl(f['image']), 'full')
    return out


_CAP_REF = re.compile(r'(?i)^\s*((?:fig(?:ure)?|scheme)\.?\s*S?\d+)')


def full_figures(pid, crop=None):
    """整张 Figure 的 PNG：[{num, page, ref, caption, image}]。裁一次存进 curated/<id>/figures/，之后直接读。

    要 MineRU 那一档（layout.json + 原 PDF）；快速文本层没有版面坐标，返回 []。
    layout.json 比索引新（重新解析过）就重裁。
    """
    import base64
    from shared.kernel import paths
    parsed = paths.parsed_dir(pid)
    lay = os.path.join(parsed, 'layout.json')
    if not os.path.exists(lay):
        return []
    d = paths.figures_dir(pid)
    idx = os.path.join(d, 'index.json')
    if os.path.exists(idx) and os.path.getmtime(idx) >= os.path.getmtime(lay):
        try:
            return json.load(io.open(idx, encoding='utf-8'))
        except ValueError:
            pass
    if crop is None:
        from host.mcp.figure_crop import crop_figures as crop
    try:
        figs = crop(parsed)
    except Exception:
        return []
    os.makedirs(d, exist_ok=True)
    out = []
    for f in figs:
        m = _CAP_REF.match(f.get('caption') or '')
        p = os.path.join(d, 'fig_%02d_p%d.png' % (f['num'], f['page'] + 1))
        io.open(p, 'wb').write(base64.b64decode(f['b64'].split(',', 1)[-1]))
        out.append({'num': f['num'], 'page': f['page'] + 1, 'ref': re.sub(r'\s+', ' ', m.group(1)) if m else '',
                    'caption': (f.get('caption') or '')[:200], 'image': p})
    io.open(idx, 'w', encoding='utf-8').write(json.dumps(out, ensure_ascii=False))
    return out


def text_rev(pid, si=False):
    """这篇正文（或 SI）当前版本的短指纹：档位 + 文本哈希前 8 位。变了就说明节号可能变了。"""
    import hashlib
    from shared.kernel import paths
    from tools.getpdf import fulltext as F
    p = paths.si_fulltext(pid) if si else paths.fulltext(pid)
    try:
        h = hashlib.sha1(io.open(p, 'rb').read()).hexdigest()[:8]
    except OSError:
        return ''
    return '%s-%s' % (F.tier_of(pid, si=si), h)


def _html_cells(html):
    """HTML 表格 → [[{text, colspan, rowspan}, …], …]（标准库 html.parser）。"""
    from html.parser import HTMLParser
    rows = []
    st: dict = {'row': None, 'cell': None}

    class P(HTMLParser):
        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            if tag == 'tr':
                st['row'] = []
            elif tag in ('td', 'th') and st['row'] is not None:
                st['cell'] = {'text': '', 'colspan': int(a.get('colspan') or 1),
                              'rowspan': int(a.get('rowspan') or 1)}
            elif tag == 'br' and st['cell'] is not None:
                st['cell']['text'] += ' '

        def handle_endtag(self, tag):
            if tag in ('td', 'th') and st['cell'] is not None and st['row'] is not None:
                st['row'].append(st['cell'])
                st['cell'] = None
            elif tag == 'tr' and st['row'] is not None:
                rows.append(st['row'])
                st['row'] = None

        def handle_data(self, data):
            if st['cell'] is not None:
                st['cell']['text'] += data

    P().feed(html or '')
    return rows


def html_table_rows(html):
    """HTML 表格 → 规整的行列表：colspan 展开成重复格，rowspan 往下面几行补同一格。"""
    grid, carry = [], {}                       # carry：列号 → (还要补几行, 文字)
    for cells in _html_cells(html):
        line, col, cells = [], 0, list(cells)
        while cells or carry.get(col):
            if carry.get(col):
                left, txt = carry[col]
                line.append(txt)
                carry[col] = (left - 1, txt) if left > 1 else None
                col += 1
                continue
            c = cells.pop(0)
            txt = ' '.join(c['text'].split())
            for _ in range(max(1, c['colspan'])):
                line.append(txt)
                if c['rowspan'] > 1:
                    carry[col] = (c['rowspan'] - 1, txt)
                col += 1
        grid.append(line)
    return grid


def table_rows(text):
    """一段含 <table> 的文字 → (表前的图注文字, 行列表)。没有表格返回 (text, [])。"""
    m = re.search(r'(?is)<table\b.*?</table>', text or '')
    if not m:
        return text, []
    return text[:m.start()].strip(), html_table_rows(m.group(0))


def _as_csv(rows):
    import csv
    buf = io.StringIO()
    csv.writer(buf, lineterminator='\n').writerows(rows)
    return buf.getvalue()


def _one_section(req, max_chars, offset=0, fmt='html'):
    from tools import library
    pid = _resolve(req.get('itemKey'))
    offset = max(0, int(req.get('offset') or offset or 0))
    fmt = (req.get('format') or fmt or 'html').lower()
    si = bool(req.get('si'))
    addr, anchor = reanchor(pid, req.get('sectionId') or '', req.get('title') or '', req.get('quote') or '', si)
    r = library.section(pid, addr, max_chars=offset + max_chars, si=si)
    full = r.get('text', '')
    out = {'itemKey': pid, 'sectionId': addr, 'si': si, 'why_empty': r.get('why_empty', ''),
           'title': anchor.get('title', ''), 'rev': text_rev(pid, si)}
    if anchor.get('remapped_from'):
        out['remapped_from'] = anchor['remapped_from']
        out['remap_by'] = anchor['by']
    if anchor.get('warning'):
        out['warning'] = anchor['warning']
    if fmt in ('csv', 'json') and full:
        caption, rows = table_rows(full)
        if not caption and addr.lower().startswith('t'):
            caption = _table_caption(pid, addr, si)          # 表的文字只含 <table>，图注在骨架里
        if rows:
            out.update(format=fmt, caption=caption, n_rows=len(rows), n_cols=max(len(x) for x in rows),
                       chars=len(full))
            out['csv' if fmt == 'csv' else 'rows'] = _as_csv(rows) if fmt == 'csv' else rows
            return out
        out['format_note'] = '这处没有 HTML 表格（快速文本层没有表格结构，等 tier=structured），按文字给'
    text = full[offset:offset + max_chars]
    more = bool(r.get('truncated')) or len(full) > offset + max_chars
    out.update(text=text, chars=len(text), offset=offset, truncated=more)
    if more:
        out['next_offset'] = offset + len(text)
    return out


def _table_caption(pid, tid, si=False):
    from tools import library
    o = library.outline(pid)
    src = (o.get('si') or {}) if si else o
    for t in src.get('tables') or []:
        if t.get('id') == tid.lower():
            return t.get('caption') or ''
    return ''


def reanchor(pid, addr, title='', quote='', si=False):
    """按 title / quote 把（可能是旧版本的）地址对到现在的版本 → (地址, {title, remapped_from, by, warning})。

    - 给了 quote：以原句为准，找它现在所在的段 / 节（最精确）。
    - 给了 title：sectionId 那一节的标题对不上 → 按标题找回那一节（原来是段地址的，退到整节）。
    - 都没给：照 sectionId 取，只把那节现在的标题带回去，让调用方自己核。
    """
    from shared.domain import outline as O
    from shared.kernel import paths
    from tools import library
    o = library.outline(pid)
    src = (o.get('si') or {}) if si else o
    titles = {x['id']: x.get('title', '') for x in src.get('sections') or []}
    sec = (addr or '').lower().partition('.')[0]
    info = {'title': titles.get(sec, '')}
    if not src.get('sections'):
        return addr, info
    if quote:
        p = paths.si_fulltext(pid) if si else paths.fulltext(pid)
        try:
            md = io.open(p, encoding='utf-8').read()
        except OSError:
            md = ''
        got = O.locate(md, src, quote)
        if got:
            if got.lower() != (addr or '').lower():
                info.update(remapped_from=addr, by='quote')
            info['title'] = titles.get(got.partition('.')[0], '')
            return got, info
        info['warning'] = '这句原文在当前版本里没找到（可能断行 / 公式写法不同）'
    if title and not addr:
        got = O.find_section(src, title)
        if got:
            info['title'] = titles.get(got, '')
            return got, info
        info['warning'] = '标题「%s」在当前版本里没找到' % title[:60]
    elif title and O.norm_text(titles.get(sec, '')) != O.norm_text(title):
        got = O.find_section(src, title)
        if got:
            info.update(remapped_from=addr, by='title', title=titles.get(got, ''))
            if '.' in (addr or ''):
                info['warning'] = '段号随版本变了，给的是整节'
            return got, info
        info['warning'] = '标题「%s」在当前版本里没找到，按 sectionId 照取' % title[:60]
    return addr, info


def _section(a):
    max_chars = int(a.get('maxChars') or 20000)
    reqs = a.get('requests') or ([{'itemKey': a.get('itemKey'), 'sectionId': a.get('sectionId'),
                                   'si': a.get('si'), 'title': a.get('title'), 'quote': a.get('quote')}]
                                 if a.get('itemKey') else [])
    if not reqs:
        raise ValueError('给 itemKey + sectionId，或 requests=[{itemKey, sectionId, si}]')
    out = []
    for q in reqs[:50]:
        try:
            out.append(_one_section(q, max_chars, a.get('offset') or 0, a.get('format') or 'html'))
        except ValueError as e:
            out.append({'itemKey': q.get('itemKey'), 'sectionId': q.get('sectionId'),
                        'text': '', 'chars': 0, 'why_empty': str(e)})
    got = sum(1 for r in out if r.get('chars'))
    return _out('取到 %d/%d 处' % (got, len(out)), {'results': out})


_IMG_LINE = re.compile(r'!\[[^\]]*\]\(([^)]+)\)')
_CAP_LINE = re.compile(r'(?im)^\s*(?:\*\*)?((?:Fig(?:ure)?|Scheme)\.?\s*S?\d+)')


def figure_images(md, img_dir):
    """全文 Markdown → [{ref, image}]：每条图注（Figure N / Fig. N / Scheme N）之前最近的那张图。

    MineRU 的写法是「图片行 → 图注」，所以按行走一遍、记住上一张图即可。纯文本处理，不看图。
    """
    out, last, seen = [], '', set()
    for line in (md or '').splitlines():
        m = _IMG_LINE.search(line)
        if m:
            last = m.group(1)
        c = _CAP_LINE.match(line)
        if c and last:
            ref = re.sub(r'\s+', ' ', c.group(1)).replace('Fig.', 'Figure').replace('Fig ', 'Figure ')
            if ref.lower() not in seen:
                seen.add(ref.lower())
                out.append({'ref': ref, 'image': os.path.join(img_dir, os.path.basename(last))})
            last = ''
    return out


def paper_files(key):
    """这篇手上有哪些文件 → {名字: Windows 路径}。只列真在盘上的。"""
    from shared.kernel import paths
    cands = {'main_pdf': paths.local_pdf(key), 'si_original': paths.find_local_si(key),
             'main_md': paths.fulltext(key), 'si_md': paths.si_fulltext(key),
             'images_dir': paths.images_dir(key)}
    return {k: p for k, p in cands.items() if p and os.path.exists(p)}


MAX_IMAGE_KB = 36      # base64 会大三分之一，36 KB 的图回出去约 48 KB，压在 50 KB 线内


def _figure_image(a):
    """一张图直接回成小 JPEG（base64）：不用传文件、不用等界面批准（2026-10-04 Claude Science：取一张图等了 20 多分钟）。"""
    import base64
    from host.mcp.figure_crop import shrink_jpeg
    pid = _resolve(a.get('itemKey'))
    want = str(a.get('fig') or '').strip()
    key = _fig_key('figure ' + want if want.isdigit() else want)
    imgs = _figure_map(pid)
    hit = imgs.get(key)
    if not hit:
        raise ValueError('「%s」没有对上的图片；有的是：%s' % (want, ', '.join(sorted(imgs)) or '（这篇还没有图片，tier 不是 structured）'))
    path, kind = hit
    win = path
    if win.startswith('/mnt/'):
        win = win[5].upper() + ':' + win[6:].replace('/', os.sep)
    max_kb = max(8, min(int(a.get('max_kb') or 30), MAX_IMAGE_KB))
    data = shrink_jpeg(win, max_kb * 1024)
    if not data:
        raise ValueError('这张图缩不到 %d KB 以内（或读不了）：%s' % (max_kb, path))
    return _out('%s %s：%d KB JPEG（%s）' % (pid, want, len(data) // 1024, '整张图' if kind == 'full' else '子图碎块'),
                {'itemKey': pid, 'fig': want, 'image_kind': kind, 'path': path, 'mime': 'image/jpeg',
                 'bytes': len(data), 'base64': base64.b64encode(data).decode()})


def _paper_files(a):
    pid = _resolve(a.get('itemKey'))
    got = paper_files(pid)
    data = {'itemKey': pid, 'files': {k: to_wsl(p) for k, p in got.items()}, 'figures': []}
    m = _figure_map(pid)
    data['figures'] = [{'ref': k.title(), 'image': v[0], 'image_kind': v[1]} for k, v in sorted(
        m.items(), key=lambda kv: (kv[0].split(' ')[0], int(re.sub(r'\D', '', kv[0]) or 0)))]
    return _out('%s：%d 个文件，%d 张图对上了图号' % (pid, len(got), len(data['figures'])), data)


# ══════════════════════════════════════════════════════════════════════
# 取全文：提交（后台串行）+ 看进度（可等）
# ══════════════════════════════════════════════════════════════════════

def precheck(dois, exists_fn=None):
    """库里没有的 DOI 先问 Crossref：查无此 DOI 的当场退回（NOT_FOUND，不占队列）。

    → (要交的, 退回的 [{doi, code, why}])。Crossref 连不上 / 别的错一律放行 —— 预检只拦「确定不存在」的，
    拿不准就交给出版商那边判（宁可多跑一篇，不能误杀）。并发问（5 路），25 篇约几秒。
    """
    from shared.kernel import catalog
    lookup = exists_fn
    if lookup is None:
        from shared.adapters import crossref

        def _exists(d):
            try:
                crossref.work(d)
                return True
            except crossref.DoiNotFound:
                return False
            except Exception:
                return True
        lookup = _exists
    todo = [d for d in dois if not catalog.find(d)]
    if not todo:
        return list(dois), []
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=5) as ex:
        exists = dict(zip(todo, ex.map(lookup, todo)))
    keep = [d for d in dois if exists.get(d, True)]
    gone = [{'doi': d, 'code': 'NOT_FOUND', 'retryable': False,
             'why': 'Crossref 查无此 DOI（多半抄错了），没排进队列'} for d in dois if not exists.get(d, True)]
    return keep, gone


def _fulltext(a):
    from shared.kernel import paths, subproc
    dois, bad = [], []
    for d in a.get('dois') or []:
        n = norm_doi(str(d))
        (dois if n else bad).append(n or str(d))
    dois = list(dict.fromkeys(dois))          # 队列内去重
    rejected = [{'doi': d, 'code': 'NOT_FOUND', 'retryable': False, 'why': '不像一个 DOI'} for d in bad]
    if not dois:
        raise ValueError('没有像样的 DOI：%s' % ', '.join(bad) if bad else '没给 DOI')
    if len(dois) > MAX_DOIS:
        raise ValueError(f'一次最多 {MAX_DOIS} 篇（给了 {len(dois)}）；分批提交，上一批跑完再交下一批')
    allow = a.get('allowFetch', True)
    if allow:
        busy = running_job()
        if busy:
            raise ValueError(busy + '；等它跑完再提交（fulltext_status 可以 wait_s 等）')
    else:
        # 只查不取：前三层零成本，同步答
        from tools.getpdf import fulltext as F
        rs = F.many(dois, allow_fetch=False, limit=len(dois))
        return _out('只查不取：%d/%d 篇手上有全文' % (sum(1 for r in rs if r['ok']), len(rs)),
                    {'results': [_slim_result(r) for r in rs], 'rejected': rejected})
    dois, gone = precheck(dois)
    rejected += gone
    if not dois:
        return _out('全部退回：%d 篇 DOI 无效' % len(rejected), {'submitted': [], 'rejected': rejected, 'eta_s': 0})
    path = _progress_path()
    try:
        io.open(path, 'w', encoding='utf-8').write(json.dumps(
            {'total': len(dois), 'finished': 0, 'done': False, 'elapsed': 0, 'results': []}))
    except OSError:
        pass
    subproc.spawn([sys.executable, '-m', 'tools.getpdf'] + dois
                  + ['--fulltext', '--limit', str(len(dois))], cwd=paths.ROOT)
    eta = len(dois) * 60
    return _out('已提交 %d 篇，后台串行，预计约 %d 分钟%s' % (
        len(dois), max(1, eta // 60), '；退回 %d 篇' % len(rejected) if rejected else ''),
                {'submitted': dois, 'rejected': rejected, 'eta_s': eta})


_RESULT_KEYS = ('doi', 'id', 'ok', 'code', 'retryable', 'stage', 'tier', 'route', 'source',
                'secs', 'chars', 'si', 'why', 'deferred')


def _slim_result(r):
    out = {k: r.get(k) for k in _RESULT_KEYS if k in r}
    if out.get('id'):
        # 档位看盘、现算：MineRU 在后台把 text 升成 structured，进度文件里那份是提交时的
        from tools.getpdf import fulltext as F
        try:
            out['tier'] = F.tier_of(out['id'])
            out['si_tier'] = F.tier_of(out['id'], si=True)
        except Exception:
            pass
        if out.get('code') == 'PARSE_PENDING' and out.get('tier') in ('text', 'structured'):
            out.update(ok=True, code='OK', retryable=False, why='')
    return out


def _status(a):
    wait = max(0, min(int(a.get('wait_s') or 0), MAX_WAIT))
    d = _read_progress()
    if d is None:
        return _out('还没有提交过取全文', {'total': 0, 'finished': 0, 'done': True, 'results': []})
    t_end, seen = time.time() + wait, d.get('finished', 0)
    while wait and not d.get('done') and time.time() < t_end:
        time.sleep(2)
        d = _read_progress() or d
        if d.get('finished', 0) != seen:
            break
    results = [_slim_result(r) for r in d.get('results') or []]
    data = {'total': d.get('total', 0), 'finished': d.get('finished', 0), 'done': bool(d.get('done')),
            'elapsed_s': d.get('elapsed', 0), 'results': results,
            'retryable': [r['doi'] for r in results if r.get('retryable') and not r.get('ok')]}
    if d.get('upgrading'):
        data['upgrading'] = True               # 下载完了，MineRU 还在后台补表格；结果里的 tier 会自己变
    if d.get('current') and not d.get('done'):
        # 正在处理哪篇、已经多久（每 15 秒更新）—— 解析一篇大文献要好几分钟，这个数在涨就说明没卡死
        data['current'] = d['current']
        if (d['current'].get('for_s') or 0) > STALL_SECS:
            data['stalled'] = True
            data['stalled_hint'] = '同一篇处理了 %d 秒还没完：多半是浏览器那边卡在验证页，看主力机桌面提醒' % d['current']['for_s']
    if a.get('brief') is False:
        from tools.getpdf import fulltext as F
        data['menus'] = {r['id']: F._menu_of(r['id']) for r in results if r.get('ok')}
    return _out('%d/%d 篇%s' % (data['finished'], data['total'], '，完成' if data['done'] else '，还在跑'), data)


def _retry(a):
    """上一个作业里可重试的（撞验证 / 暂缓 / 网络错）再交一次。也可以自己给 dois。"""
    dois = a.get('dois')
    if not dois:
        d = _read_progress() or {}
        dois = [r['doi'] for r in d.get('results') or []
                if not r.get('ok') and (r.get('retryable') or r.get('code') in ('CAPTCHA_REQUIRED', 'NETWORK_ERROR'))]
    if not dois:
        return _out('上一个作业里没有可重试的', {'submitted': [], 'rejected': [], 'eta_s': 0})
    return _fulltext({'dois': dois})


def _paper_status(a):
    """一批 DOI / id → 每篇的档位、SI、表图数、最近一次错误。不取、不解析、零成本。"""
    from shared.kernel import catalog, paths
    from tools import library
    from tools.getpdf import fulltext as F
    keys = list(a.get('dois') or []) + list(a.get('itemKeys') or [])
    if not keys:
        raise ValueError('给 dois=[…] 或 itemKeys=[…]')
    last = {r.get('doi'): r for r in ((_read_progress() or {}).get('results') or [])}
    out = []
    for k in keys[:200]:
        doi = norm_doi(str(k))
        try:
            pid = _resolve(k)
        except ValueError:
            row = {'key': k, 'doi': doi, 'in_db': False, 'tier': 'none'}
            if doi in last:
                row.update(last_code=last[doi].get('code'), last_why=last[doi].get('why'))
            out.append(row)
            continue
        row = {'key': k, 'id': pid, 'doi': doi or catalog.doi_of(catalog.read_meta(pid)), 'in_db': True,
               'pdf': os.path.exists(paths.local_pdf(pid)), 'si_original': bool(paths.find_local_si(pid)),
               'tier': F.tier_of(pid), 'si_tier': F.tier_of(pid, si=True)}
        if row['tier'] != 'none':
            try:
                o = library.outline(pid)
                row.update(sections=len(o.get('sections') or []), tables=len(o.get('tables') or []),
                           figures=len(o.get('figures') or []))
            except Exception:
                pass
        if row['doi'] in last:
            r = last[row['doi']]
            row.update(route=r.get('route') or r.get('source'), last_code=r.get('code'))
            if not r.get('ok'):
                row['last_why'] = r.get('why')
        out.append(row)
    n = lambda t: sum(1 for r in out if r.get('tier') == t)
    return _out('%d 篇：structured %d、text %d、没有可读全文 %d' % (len(out), n('structured'), n('text'), n('none')),
                {'papers': out})



# ══════════════════════════════════════════════════════════════════════
# SciFinder / Reaxys：按人的频率搜、读结果页（2026-10-08）
# ══════════════════════════════════════════════════════════════════════

def _chemdb_usage_path():
    from shared.kernel import paths
    return paths.runtime('chemdb_usage.json')


def _load(path):
    try:
        return json.load(io.open(path, encoding='utf-8'))
    except Exception:
        return {}


def _day(now):
    return time.strftime('%Y-%m-%d', time.localtime(now))


WEB_DBS = ('scifinder', 'reaxys', 'polyinfo', 'cnki', 'cnki_pdf', 'ccdc', 'jcr', 'scopus', 'tansoole')   # 借浏览器查的库；共用一份账本、一把锁


def check_web_db(db):
    db = (db or '').strip().lower()
    if db not in WEB_DBS:
        raise ValueError(f'db 只能是 {" / ".join(WEB_DBS)}（给了「{db}」）')
    return db


def gap_of(db):
    return {'polyinfo': POLYINFO_GAP, 'cnki': CNKI_GAP, 'cnki_pdf': CNKI_PDF_GAP, 'ccdc': CCDC_GAP, 'jcr': JCR_GAP, 'scopus': SCOPUS_GAP,
            'tansoole': TANSOOLE_GAP}.get(db, CHEMDB_GAP)


_DAILY = {'polyinfo': ('POLYINFO_DAILY', POLYINFO_DAILY), 'cnki': ('CNKI_DAILY', CNKI_DAILY),
          'cnki_pdf': ('CNKI_PDF_DAILY', CNKI_PDF_DAILY),
          'ccdc': ('CCDC_DAILY', CCDC_DAILY), 'jcr': ('JCR_DAILY', JCR_DAILY), 'scopus': ('SCOPUS_DAILY', SCOPUS_DAILY),
          'tansoole': ('TANSOOLE_DAILY', TANSOOLE_DAILY)}


def chemdb_daily(db='scifinder'):
    from shared.kernel import config
    name, default = _DAILY.get(db, ('CHEMDB_DAILY', CHEMDB_DAILY))
    try:
        return int(config.get_key(name, default='') or default)
    except ValueError:
        return default


def chemdb_quota(db, path=None, now=None, daily=None):
    """→ (今天已用, 上限, 还要等几秒)。账本按天记，跨天自动清零。间隔按库（PoLyInfo 更长），从上一次碰任何库算起。"""
    now = now or time.time()
    d = _load(path or _chemdb_usage_path())
    daily = chemdb_daily(db) if daily is None else daily
    used = d.get('days', {}).get(_day(now), {}).get(db, 0)
    wait = max(0.0, gap_of(db) - (now - float(d.get('last', 0))))
    return used, daily, wait


def chemdb_charge(db, path=None, now=None, last_search=None, count=True):
    """记一次（搜索或翻页）。只留最近 7 天。last_search = 这个库最近一次搜索的参数 + 列表网址（翻页要用）。
    count=False：只记时间（下一次照样要隔够），不算进当天次数。"""
    now = now or time.time()
    path = path or _chemdb_usage_path()
    d = _load(path)
    today = _day(now)
    days = d.get('days', {})
    days.setdefault(today, {})[db] = days.get(today, {}).get(db, 0) + (1 if count else 0)
    out = {'last': now, 'days': {k: days[k] for k in sorted(days)[-7:]}, 'searches': d.get('searches', {})}
    if last_search is not None:
        out['searches'][db] = last_search
    io.open(path, 'w', encoding='utf-8').write(json.dumps(out, ensure_ascii=False))


def _remember_search(db, search, path=None):
    """缓存命中时也要记住「这个库现在的检索是哪次」，翻页才翻得对。不扣次数。"""
    path = path or _chemdb_usage_path()
    d = _load(path)
    d.setdefault('searches', {})[db] = search
    io.open(path, 'w', encoding='utf-8').write(json.dumps(d, ensure_ascii=False))


def chemdb_key(db, params, page):
    """同一库、同一检索（词 + 类 + 排序 + 筛选 + 模式）、同一页 → 同一个缓存键。"""
    import hashlib
    sig = json.dumps({'db': db, 'p': {k: params.get(k) for k in ('query', 'kind', 'sort', 'filters', 'mode', 'structure', 'match', 'subset', 'within',
                                                                  'op', 'name', 'pid', 'formula', 'prop', 'atoms_only', 'n', 'url',
                                                                  'compound', 'ident', 'doi', 'author', 'database', 'journal', 'year',
                                                                  'eid')},
                      'page': int(page), 'v': VERSION}, sort_keys=True, ensure_ascii=False)   # 升版本 = 解析变了，旧缓存作废
    return hashlib.sha1(sig.encode('utf-8')).hexdigest()[:16]


def _cache_path(key, now=None, root=None):
    from shared.kernel import paths
    root = root or paths.runtime('chemdb_cache')
    return os.path.join(root, _day(now or time.time()), key + '.json')


def cache_get(key, now=None, root=None):
    p = _cache_path(key, now, root)
    return (_load(p) or None) if os.path.exists(p) else None


def cache_put(key, r, now=None, root=None):
    import shutil
    p = _cache_path(key, now, root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    io.open(p, 'w', encoding='utf-8').write(json.dumps(r, ensure_ascii=False))
    base = os.path.dirname(os.path.dirname(p))
    for old in sorted(os.listdir(base))[:-3]:          # 缓存只留最近 3 天
        shutil.rmtree(os.path.join(base, old), ignore_errors=True)


DOI_SURE = 0.9          # 标题相似度到这个数，就当是它
DOI_MAYBE = 0.75        # 到这个数，给 DOI 但标 doi_uncertain，让调用方自己判


def _volume_of(it):
    """SciFinder 出处「Angewandte Chemie, International Edition (2019), 58(12), 3800-3804」→ '58'。"""
    import re as _re
    m = _re.search(r'\(\d{4}\),\s*(\d+)', it.get('citation') or '')
    return m.group(1) if m else None


def doi_mismatch(it, got):
    """按标题配到的 DOI 要再对一遍刊名和卷：对不上 → 说明原因；对得上 → ''。"""
    from shared.adapters import crossref
    vol, cvol = _volume_of(it), str(got.get('volume') or '').strip()
    if vol and cvol and vol != cvol:
        return f'卷号对不上（出处 {vol}，候选 {cvol}「{got.get("journal")}」）'
    src, cj = (it.get('source') or '').lower(), (got.get('journal') or '').lower()
    if src and cj:
        intl = lambda j: 'international' in j or 'int. ed' in j or 'int ed' in j
        if intl(src) != intl(cj):
            return f'刊名的版本对不上（出处「{it.get("source")}」，候选「{got.get("journal")}」）'
        if crossref.title_similarity(src.split('(')[0], cj) < 0.5 and src.split()[0] not in cj:
            return f'刊名对不上（出处「{it.get("source")}」，候选「{got.get("journal")}」）'
    return ''


OPENALEX_FALLBACK = 10


def openalex_match(it):
    """按标题问 OpenAlex → {doi, score, venue} / None（没配上）/ False（没查成）。标题相似度 ≥0.9、年份差 ≤1 才算。"""
    from shared.adapters import crossref, openalex
    try:
        found, _ = openalex.search(it['title'], limit=3)
    except Exception:
        return False
    best = None
    for w in found:
        sc = crossref.title_similarity(it['title'], w.get('title'))
        if it.get('year') and w.get('year') and abs(int(w['year']) - int(it['year'])) > 1:
            continue
        if w.get('doi') and sc >= DOI_SURE and (not best or sc > best['score']):
            best = {'doi': w['doi'].lower(), 'score': round(sc, 3), 'venue': w.get('venue')}
    return best


def enrich(items, match=None, find=None, tier=None, warnings=None):
    """补 DOI（SciFinder 列表没有，按标题去 Crossref 找）+ 标出证据库里有没有、能读到哪一档。"""
    warnings = [] if warnings is None else warnings
    if match is None:
        from shared.adapters import crossref

        def _crossref(it):
            first = ((it.get('authors') or [''])[0] or '').split(',')[0]
            src = (it.get('source') or '').split('(')[0].strip()
            return crossref.match_title(it['title'], it.get('year'), first, journal=src, volume=_volume_of(it) or '')
        match = _crossref
    if find is None or tier is None:
        from shared.kernel import catalog
        from tools.getpdf import fulltext as F
        find, tier = find or catalog.find, tier or F.tier_of
    todo = [it for it in items if not it.get('doi') and it.get('type') not in ('patent', 'substance') and it.get('title')]
    if todo:
        from concurrent.futures import ThreadPoolExecutor

        def _m(it):
            for attempt in range(3):          # 2026-10-08：5 路并发被 Crossref 限流，42 条只配上 16 条
                try:
                    return True, match(it)
                except Exception:
                    time.sleep(1.5 * (attempt + 1))
            return False, None
        with ThreadPoolExecutor(max_workers=2) as ex:
            got_all = list(ex.map(_m, todo))
        for it, (ok, got) in zip(todo, got_all):
            if not ok or not (got and got.get('doi') and got['score'] >= DOI_MAYBE):
                it['_retry'] = True
            if not (got and got.get('doi') and got['score'] >= DOI_MAYBE):
                continue
            why = doi_mismatch(it, got)
            if why:
                # 标题像、但刊 / 卷对不上：多半是同一篇的另一个版本（德文版 / 会议版），不填，只给候选
                it['doi_candidate'] = got['doi']
                it['doi_rejected_because'] = why
                continue
            it['doi'] = got['doi']
            it['doi_source'] = 'crossref_title_match'
            it['doi_match_score'] = got['score']
            if got['score'] < DOI_SURE:
                it['doi_uncertain'] = True
        # Crossref 限流没查成、或没配上的（2026-10-09 Claude Science 报：Science 2005 COF、2017 vitrimer 两篇空着、也没原因）
        # → 改按标题问 OpenAlex（每页最多 OPENALEX_FALLBACK 条，$0.001/次量级）；还不行逐条标 doi_lookup
        retry = [it for it in todo if it.pop('_retry', False) and not it.get('doi_candidate')]
        for it in retry[:OPENALEX_FALLBACK]:
            got = openalex_match(it)
            if got and not doi_mismatch(it, {'journal': got.get('venue')}):
                it.update(doi=got['doi'], doi_source='openalex_title_match', doi_match_score=got['score'])
            else:
                it['doi_lookup'] = 'not_found' if got is not False else 'failed'
        for it in retry[OPENALEX_FALLBACK:]:
            it['doi_lookup'] = 'skipped'
        n_left = sum(1 for it in retry if not it.get('doi'))
        if n_left:
            warnings.append(f'doi_not_found: {n_left} 条 Crossref 与 OpenAlex 都没配上 DOI（条目上 doi_lookup 写了原因），可以自己按标题再找')
    for it in items:
        if it.get('doi'):
            pid = find(it['doi'])
            it['in_library'] = bool(pid)
            if pid:
                it['id'] = pid
                try:
                    it['tier'] = tier(pid)
                except Exception:
                    it['tier'] = None
        elif it.get('type') not in ('patent', 'substance', 'supplier'):
            it['in_library'] = None
    return items


def _no_nan(x):
    """JSON 里不许有 NaN / Infinity（严格的解析器直接报错，2026-10-08 Claude Science 报）。"""
    import math
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return None
    if isinstance(x, dict):
        return {k: _no_nan(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_no_nan(v) for v in x]
    return x


CHEMDB_WAIT = 25       # 一次调用最多陪着等几秒（调用方远程命令 60 秒就断，2026-10-08）；没好就回 job_id
_chemdb_lock = __import__('threading').Lock()      # 同一时刻只跑一个库检索（共用一个浏览器、一份账本）


def _job_path(job_id):
    from shared.kernel import paths
    d = paths.runtime('chemdb_jobs')
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, job_id + '.json')


def _job_write(job_id, data):
    io.open(_job_path(job_id), 'w', encoding='utf-8').write(json.dumps(_no_nan(data), ensure_ascii=False))


def _job_wait(job_id, wait_s):
    """等这个作业最多 wait_s 秒 → 作业记录（state = running / done / failed）。"""
    end = time.time() + max(0, wait_s)
    while True:
        d = _load(_job_path(job_id))
        if d.get('state') in ('done', 'failed') or time.time() >= end:
            return d
        time.sleep(1)


def _clean(r):
    c = _no_nan(dict(r))
    return c if isinstance(c, dict) else dict(r)


def _deliver(r, db, params, cached):
    r = _clean(r)
    used, daily, _ = chemdb_quota(db)
    r['cached'] = cached
    r['quota'] = {'used_today': used, 'daily_limit': daily, 'remaining': max(0, daily - used),
                  'min_gap_s': gap_of(db)}
    if not params.get('raw'):
        r.pop('text', None)
    n = len(r.get('items') or [])
    summary = '共 %s 条，第 %s 页 %d 条' % (r.get('count'), r.get('page'), n)
    if r.get('kind') == 'substance_facts':
        sub: dict = r.get('substance') or {}           # type: ignore[assignment]
        gs: list = r.get('groups') or []               # type: ignore[assignment]
        summary = '%s（%s）：%s 组、%s 行数据' % (sub.get('name'), sub.get('cas_rn'), len(gs),
                                          sum(len(g.get('rows') or []) for g in gs))
    head = '%s %s%s：%s' % (db, r.get('code'), '（缓存）' if cached else '', r.get('why') or summary)
    return _out(head, r)


def _chemdb_work(db, params, page, fetch, key):
    """后台线程里真去网站：间隔 → 检索 → 记账 → 补 DOI 与库内标记 → 存缓存。结果写进作业文件。"""
    try:
        wait = chemdb_quota(db)[2]
        if wait:
            time.sleep(wait)                  # 不到 30 秒就等够再做（人的节奏）
        r = fetch(db)
        keep = {k: v for k, v in params.items() if k != 'raw'}
        is_search = page == 1 and r.get('url') and params.get('op') in (None, 'search', 'citing')   # 看详情不算「最近一次检索」；被引列表算（翻页翻的是它）
        if r.get('code') not in NO_CHARGE:     # 标签不在、列表里没有第 n 条…… 没碰网站的失败不扣次数
            chemdb_charge(db, last_search=dict(keep, url=r.get('url')) if is_search else None,
                          count=db not in ONLY_OK_COUNTS or r.get('code') == 'OK')
        if r.get('code') in ('CAPTCHA_REQUIRED', 'LOGIN_REQUIRED'):
            _call_human(db, r)
        if r.get('items') and db not in ('polyinfo', 'cnki', 'ccdc', 'jcr', 'tansoole'):   # 聚合物 / 中文文献 / 晶体结构：不去 Crossref 补 DOI
            try:
                enrich(r['items'], warnings=r.setdefault('warnings', []))
            except Exception as e:
                r.setdefault('warnings', []).append(f'enrich_failed: {type(e).__name__}: {str(e)[:80]}')
        r = _clean(r)
        if r.get('code') in ('OK', 'NO_RESULTS') and r.get('complete', True):
            cache_put(key, r)
        _job_write(key, {'state': 'done', 'db': db, 'params': params, 'page': page, 'result': r, 'finished': time.time()})
    except Exception as e:
        _job_write(key, {'state': 'failed', 'db': db, 'params': params, 'page': page,
                         'error': f'{type(e).__name__}: {str(e)[:300]}', 'finished': time.time()})
    finally:
        _chemdb_lock.release()


def _call_human(db, r):
    """要人去浏览器点（验证码 / 登录）：主力机桌面弹一条提醒。弹不出来就算了，不许让检索本身失败。"""
    try:
        from tools.getpdf import notify
        what = '输入验证码' if r.get('code') == 'CAPTCHA_REQUIRED' else '重新登录'
        notify.desktop(f'{db} 要你{what}', f'在「取全文用的浏览器」的 {db} 标签里{what}；Claude Science 在等。')
    except Exception:
        pass


def _pending(job_id, db, d):
    started = d.get('started') or time.time()
    return _out('%s 还在查（已 %d 秒），用 chemdb_result 取：job_id=%s' % (db, time.time() - started, job_id),
                {'code': 'PENDING', 'job_id': job_id, 'db': db, 'elapsed_s': round(time.time() - started),
                 'hint': 'chemdb_result {"job_id": "%s", "wait_s": 25}；一次真实检索约 40–120 秒' % job_id})


def _from_job(job_id, d, params=None):
    if d.get('state') == 'done':
        return _deliver(d['result'], d.get('db'), params or d.get('params') or {}, False)
    if d.get('state') == 'failed':
        raise ValueError('这次检索出错了：%s' % d.get('error'))
    if _stale(d):
        raise ValueError('这次检索被打断了（服务中途重启过，作业记录停在「运行中」超过 10 分钟）；同样的参数重交一次即可')
    return _pending(job_id, d.get('db'), d)


def _stale(d, now=None):
    """作业记录停在 running 却超过 STALE_SECS 没完：线程已经随服务重启没了（2026-10-09 实测留下过一条）。"""
    return d.get('state') == 'running' and (now or time.time()) - float(d.get('started') or 0) > STALE_SECS


def _chemdb_run(db, params, page, fetch, wait_s=CHEMDB_WAIT):
    """缓存 → 额度 → 放到后台线程去网站 → 陪着等最多 wait_s 秒；没好回 PENDING + job_id（chemdb_result 取）。"""
    db = check_web_db(db)
    key = chemdb_key(db, params, page)
    hit = cache_get(key)
    if hit:
        if page == 1 and params.get('op') in (None, 'search'):
            _remember_search(db, dict(params, url=hit.get('url')))
        return _deliver(hit, db, params, True)
    d = _load(_job_path(key))
    if d.get('state') == 'running' and time.time() - (d.get('started') or 0) < 600:
        return _from_job(key, _job_wait(key, wait_s), params)      # 同一个检索已经在跑：不再扣一次
    used, daily, _ = chemdb_quota(db)
    if used >= daily:
        raise ValueError(f'{db} 今天已经用了 {used} 次（上限 {daily}，按人的频率）；明天再来，'
                         f'或请用户在控制面板调 {_DAILY.get(db, ("CHEMDB_DAILY",))[0]}。'
                         f'当天查过的检索照样能从缓存拿（不扣次数）')
    if not _chemdb_lock.acquire(blocking=False):
        busy = [f for f in os.listdir(os.path.dirname(_job_path('x')))
                if _load(os.path.join(os.path.dirname(_job_path('x')), f)).get('state') == 'running'
                and not _stale(_load(os.path.join(os.path.dirname(_job_path('x')), f)))]
        raise ValueError('另一个借浏览器的检索正在跑（%s）；等它跑完（chemdb_result）再交' %
                         ', '.join(b[:-5] for b in busy) or '?')
    _job_write(key, {'state': 'running', 'db': db, 'params': params, 'page': page, 'started': time.time()})
    import threading
    threading.Thread(target=_chemdb_work, args=(db, params, page, fetch, key), daemon=True).start()
    return _from_job(key, _job_wait(key, wait_s), params)


def _chemdb_result(a):
    """取一个检索作业的结果（chemdb_search / chemdb_page 回了 PENDING 时用）。不扣次数。"""
    job_id = (a.get('job_id') or '').strip()
    if not job_id or not os.path.exists(_job_path(job_id)):
        raise ValueError('没有这个 job_id（作业记录只留当天）')
    wait_s = max(0, min(int(a.get('wait_s') or CHEMDB_WAIT), 50))
    return _from_job(job_id, _job_wait(job_id, wait_s))


def _chemdb_params(a):
    return {'query': (a.get('query') or '').strip(), 'kind': a.get('kind') or 'references',
            'sort': a.get('sort') or None, 'filters': a.get('filters') or None,
            'mode': a.get('mode') or 'auto', 'raw': bool(a.get('raw')),
            'structure': (a.get('structure') or '').strip() or None,
            'match': (a.get('match') or 'exact') if a.get('structure') else None,
            'subset': a.get('subset') if a.get('subset') is not None else None,
            'within': [t for t in (a.get('within') if isinstance(a.get('within'), list) else [a.get('within')]) if t] or None}


def _cas_smiles(db, p):
    """Reaxys 按 CAS 号查文献时备一个结构式（PubChem），Reaxys 的 CAS 号落到冷门条目时改按结构搜。查不到就算了。"""
    from shared.adapters import chemdb
    if db != 'reaxys' or p['structure'] or p['kind'] != 'references' or not chemdb.is_cas_rn(p['query']):
        return ''
    try:
        from shared.adapters import pubchem
        got = pubchem.cas_to_structure(p['query'])
        return (got or {}).get('smiles') or ''
    except Exception:
        return ''


def _chemdb_search(a):
    from shared.adapters import chemdb
    p = _chemdb_params(a)
    mc = int(a.get('maxChars') or 30000)
    return _chemdb_run(a.get('db'), p, 1, lambda db: chemdb.search(
        db, p['query'], p['kind'], structure=p['structure'] or '', match=p['match'] or 'exact', sort=p['sort'],
        filters=p['filters'], mode=p['mode'], raw=p['raw'], max_chars=mc, subset=p['subset'], within=p['within'],
        cas_smiles=_cas_smiles(db, p)),
        wait_s=max(0, min(int(a.get('wait_s') if a.get('wait_s') is not None else CHEMDB_WAIT), 50)))


def _chemdb_page(a):
    from shared.adapters import chemdb
    db = chemdb.check_db(a.get('db'))
    n = int(a.get('page') or 2)
    last = (_load(_chemdb_usage_path()).get('searches') or {}).get(db)
    if not last:
        raise ValueError(f'{db} 还没有搜过（或账本被清了），先 chemdb_search')
    p = dict(last, raw=bool(a.get('raw')))
    mc = int(a.get('maxChars') or 30000)
    return _chemdb_run(db, p, n, lambda db: chemdb.page(db, n, base_url=last.get('url') or '', raw=p['raw'],
                                                       max_chars=mc),
                       wait_s=max(0, min(int(a.get('wait_s') if a.get('wait_s') is not None else CHEMDB_WAIT), 50)))


def _chemdb_substance(a):
    from shared.adapters import chemdb
    groups = a.get('groups')
    groups = [g for g in (groups if isinstance(groups, list) else [groups]) if g] or None
    p = {'op': 'substance', 'query': (a.get('query') or '').strip() or None, 'n': int(a.get('n') or 1),
         'section': a.get('section') or 'physical', 'groups': groups,
         'max_rows': max(1, min(int(a.get('max_rows') or 20), 100))}
    if p['section'] not in chemdb.RX_SECTIONS:
        raise ValueError(f'section 只能是 {" / ".join(chemdb.RX_SECTIONS)}')
    base = ''
    if not p['query']:
        last = (_load(_chemdb_usage_path()).get('searches') or {}).get('reaxys') or {}
        if last.get('kind') != 'substances' or not last.get('url'):
            raise ValueError('不给 query 时读 Reaxys 最近一次 kind=substances 的列表，可最近一次不是物质检索；给 query（CAS 号最准）')
        base, p['list'] = last['url'], last.get('query')
    return _chemdb_run('reaxys', p, 1, lambda db: chemdb.substance_facts(
        p['query'] or '', n=p['n'], section=p['section'], groups=p['groups'], max_rows=p['max_rows'], base_url=base),
        wait_s=max(0, min(int(a.get('wait_s') if a.get('wait_s') is not None else CHEMDB_WAIT), 50)))


def _chemdb_status(a):
    """不碰网站：额度、几点重置、两个库最近一次检索、标签停在哪（登录页 = 要人去登录）、导出文件夹里有什么。"""
    from shared.adapters import chemdb
    from shared.kernel import paths
    now = time.time()
    d = _load(_chemdb_usage_path())
    t = time.localtime(now)
    reset = time.mktime((t.tm_year, t.tm_mon, t.tm_mday + 1, 0, 0, 0, 0, 0, -1))
    out = {'quota': {}, 'reset_at': time.strftime('%Y-%m-%d %H:%M', time.localtime(reset)),
           'min_gap_s': CHEMDB_GAP, 'last_searches': d.get('searches') or {}}
    for db in chemdb.DBS:
        used, daily, _ = chemdb_quota(db, now=now)
        out['quota'][db] = {'used_today': used, 'daily_limit': daily, 'remaining': max(0, daily - used)}
    out['wait_s'] = round(chemdb_quota('scifinder', now=now)[2], 1)
    try:
        tabs = chemdb.tabs()
        for st in tabs.values():
            st['login'] = 'login_page' if st['login_page'] else ('likely_ok' if st['tab_open'] else 'unknown')
        out['tabs'] = tabs
    except Exception as e:
        out['tabs'] = {'error': f'{type(e).__name__}: {str(e)[:160]}'}
    ex = paths.CHEMDB_EXPORTS
    files = sorted(os.listdir(ex)) if os.path.isdir(ex) else []
    out['exports'] = {'dir': to_wsl(ex), 'files': files[-50:],
                      'hint': '用户手动从 SciFinder / Reaxys 导出的 Excel / RIS 放这里；你直接读（不扣次数）'}
    q = out['quota']
    return _out('SciFinder 今天还剩 %d 次、Reaxys 还剩 %d 次；%s 重置' % (
        q['scifinder']['remaining'], q['reaxys']['remaining'], out['reset_at']), out)


def _pi_wait(a):
    return max(0, min(int(a.get('wait_s') if a.get('wait_s') is not None else CHEMDB_WAIT), 50))


def _polyinfo_search(a):
    from shared.adapters import polyinfo
    p = {'op': 'search', 'name': (a.get('name') or '').strip() or None, 'pid': (a.get('pid') or '').strip().upper() or None,
         'formula': a.get('formula') or None, 'prop': (a.get('prop') or '').strip() or None,
         'atoms_only': bool(a.get('atoms_only'))}
    if p['pid']:
        polyinfo.check_id(p['pid'])
    if not (p['name'] or p['pid'] or p['formula']):
        raise ValueError('name / pid / formula 至少给一个')
    polyinfo.formula_counts(p['formula'])            # 不合法当场报，不扣次数
    return _chemdb_run('polyinfo', p, 1, lambda db: polyinfo.search(
        name=p['name'] or '', pid=p['pid'] or '', formula=p['formula'], prop=p['prop'] or '',
        atoms_only=p['atoms_only']), wait_s=_pi_wait(a))


def _polyinfo_samples(a):
    from shared.adapters import polyinfo
    pid = polyinfo.check_id(a.get('pid'))
    return _chemdb_run('polyinfo', {'op': 'samples', 'pid': pid}, 1, lambda db: polyinfo.samples(pid), wait_s=_pi_wait(a))


def _polyinfo_sample(a):
    from shared.adapters import polyinfo
    pid = polyinfo.check_id(a.get('pid'))
    n = int(a.get('n') or 1)
    return _chemdb_run('polyinfo', {'op': 'sample', 'pid': pid, 'n': n}, 1, lambda db: polyinfo.sample(pid, n),
                       wait_s=_pi_wait(a))


def _polyinfo_current(a):
    """不导航：读 PoLyInfo 标签上现在那一页（人点完验证码后用）。不扣次数；有检索在跑就别碰浏览器。"""
    from shared.adapters import polyinfo
    if not _chemdb_lock.acquire(blocking=False):
        raise ValueError('有一个检索正在用浏览器；等它跑完（chemdb_result）再读')
    try:
        r = _clean(polyinfo.current())
    finally:
        _chemdb_lock.release()
    return _out('polyinfo %s（%s）：%s' % (r.get('code'), r.get('page_kind'), r.get('why') or 'OK'), r)


def _polyinfo_status(a):
    """不碰网站：额度、要等几秒、标签停在哪（登录页 / 验证码挡着）。"""
    from shared.adapters import polyinfo
    used, daily, wait = chemdb_quota('polyinfo')
    out = {'quota': {'used_today': used, 'daily_limit': daily, 'remaining': max(0, daily - used)},
           'min_gap_s': POLYINFO_GAP, 'wait_s': round(wait, 1)}
    try:
        out['tab'] = polyinfo.status()
    except Exception as e:
        out['tab'] = {'error': f'{type(e).__name__}: {str(e)[:160]}'}
    t = out['tab']
    state = ('要人登录' if t.get('login_page') else '验证码挡着，等人点' if t.get('captcha')
             else '标签没开（第一次查会自己开，但要人先登录过）' if not t.get('tab_open') else '可以查')
    return _out('PoLyInfo 今天还剩 %d 次；%s' % (out['quota']['remaining'], state), out)


def _cnki_search(a):
    from shared.adapters import cnki
    p = {'op': 'search', 'query': (a.get('query') or '').strip(), 'kind': cnki.check_kind(a.get('kind')),
         'sort': cnki.check_sort(a.get('sort')) or None}
    if not p['query']:
        raise ValueError('query 不能空')
    return _chemdb_run('cnki', p, 1, lambda db: cnki.search(p['query'], p['kind'], p['sort']), wait_s=_pi_wait(a))


def _cnki_page(a):
    from shared.adapters import cnki
    n = int(a.get('page') or 2)
    last = (_load(_chemdb_usage_path()).get('searches') or {}).get('cnki')
    if not last:
        raise ValueError('知网还没有搜过（或账本被清了），先 cnki_search')
    p = {k: last.get(k) for k in ('query', 'kind', 'sort')}
    p['op'] = 'page'
    return _chemdb_run('cnki', p, n, lambda db: cnki.page(n), wait_s=_pi_wait(a))


def _cnki_detail(a):
    from shared.adapters import cnki
    url = (a.get('url') or '').strip()
    if not url:
        if not a.get('n'):
            raise ValueError('给 n（结果页上的序号 rank）或 url')
        if not _chemdb_lock.acquire(blocking=False):
            raise ValueError('有一个检索正在用浏览器；等它跑完（chemdb_result）再交')
        try:
            url = cnki.row_url(int(a['n'])) or ''
        finally:
            _chemdb_lock.release()
        if not url:
            raise ValueError(f'知网结果页上没有第 {a["n"]} 条（先 cnki_search / cnki_page 到那一页）')
    return _chemdb_run('cnki', {'op': 'detail', 'url': url}, 1, lambda db: cnki.detail(url=url), wait_s=_pi_wait(a))


def _cnki_download(a):
    from shared.adapters import cnki
    from shared.kernel import paths
    url, fname = (a.get('url') or '').strip(), ''
    if not url and a.get('n'):
        if not _chemdb_lock.acquire(blocking=False):
            raise ValueError('有一个检索正在用浏览器；等它跑完（chemdb_result）再交')
        try:
            row = cnki.row_info(int(a['n']))
            url, fname = row.get('url') or '', row.get('filename') or ''
        finally:
            _chemdb_lock.release()
        if not url:
            raise ValueError(f'知网结果页上没有第 {a["n"]} 条（先 cnki_search / cnki_page 到那一页）')
    if not url:
        # 人打开、程序取：浏览器里人打开着的那篇。缓存键要按那一页算，不能都叫「当前页」
        if not _chemdb_lock.acquire(blocking=False):
            raise ValueError('有一个检索正在用浏览器；等它跑完再交')
        try:
            with cnki._session() as (_b, ctx):
                opened = [p for p in ctx.pages if '/kcms' in (p.url or '')]
                url = opened[-1].url if opened else ''
        finally:
            _chemdb_lock.release()
        if not url:
            raise ValueError('浏览器里没有打开着的知网摘要页：请用户在主力机「取全文用的浏览器」里搜到这篇、点开，再交一次（不带参数）')

    def fetch(db):
        r = cnki.download(url, filename=fname)
        raw = r.pop('pdf', None)
        if raw:
            d = os.path.join(paths.CHEMDB_EXPORTS, 'cnki')
            os.makedirs(d, exist_ok=True)
            path = os.path.join(d, r['filename'])
            io.open(path, 'wb').write(raw)
            r['path'], r['path_local'] = to_wsl(path), path
            _cnki_to_library(r, path)
        return r
    return _chemdb_run('cnki_pdf', {'op': 'download', 'url': url}, 1, fetch, wait_s=_pi_wait(a))


def cnki_meta_fields(meta):
    """知网页上读到的 → 证据库目录卡的字段（只补不覆盖由 catalog.register 保证）。"""
    m = meta or {}
    return {k: v for k, v in {'title': m.get('title'), 'journal': m.get('journal'), 'year': m.get('year'),
                              'authors': m.get('authors'), 'abstract': m.get('abstract'),
                              'keywords': m.get('keywords'), 'language': 'zh', 'origin': 'cnki'}.items() if v}


def _cnki_to_library(r, path):
    """下到的知网 PDF 收进证据库：有 DOI 就落正本 + 登记；没有就只留在导出文件夹并说明。"""
    meta = r.get('meta') or {}
    doi = (meta.get('doi') or '').strip()
    try:
        from tools import getpdf
        from shared.kernel import catalog, paths
        if not doi:
            # 没有 DOI：按知网文件名起 id（2026-10-15，王海平《塑料工业》2026 两边都没 DOI）
            try:
                pid = paths.paper_id_from_cnki(meta.get('cnki_filename'))
            except paths.BadKeyError:
                r.setdefault('warnings', []).append('not_in_library: 没有 DOI，也没读到知网文件名，只放在导出文件夹')
                return
            lr = getpdf.land_file(pid, path, cnki_filename=meta.get('cnki_filename'), **cnki_meta_fields(meta))
            if lr.get('ok'):
                r['library_id'], r['in_library'] = lr['id'], True
            return
        lr = getpdf.land(doi, with_si=False, allow_fetch=False, pdf_path=path)
        if lr.get('ok'):
            catalog.register(lr['id'], **cnki_meta_fields(r.get('meta')))
            r['library_id'], r['in_library'] = lr['id'], True
        else:
            r.setdefault('warnings', []).append(f'not_in_library: 收进证据库没成（{lr.get("note")}）')
    except Exception as e:
        r.setdefault('warnings', []).append(f'not_in_library: {type(e).__name__}: {str(e)[:120]}')


def _cnki_current(a):
    """不导航：读知网标签上现在那一页（人拖完拼图后用）。不扣次数。"""
    from shared.adapters import cnki
    if not _chemdb_lock.acquire(blocking=False):
        raise ValueError('有一个检索正在用浏览器；等它跑完（chemdb_result）再读')
    try:
        r = _clean(cnki.current())
    finally:
        _chemdb_lock.release()
    return _out('cnki %s：%s' % (r.get('code'), r.get('why') or 'OK'), r)


def _cnki_status(a):
    from shared.adapters import cnki
    used, daily, wait = chemdb_quota('cnki')
    pu, pd_, pw = chemdb_quota('cnki_pdf')
    out = {'quota': {'used_today': used, 'daily_limit': daily, 'remaining': max(0, daily - used)},
           'min_gap_s': CNKI_GAP, 'wait_s': round(wait, 1),
           'pdf_quota': {'used_today': pu, 'daily_limit': pd_, 'remaining': max(0, pd_ - pu),
                         'min_gap_s': CNKI_PDF_GAP, 'wait_s': round(pw, 1)},
           'last_search': (_load(_chemdb_usage_path()).get('searches') or {}).get('cnki')}
    try:
        out['tab'] = cnki.status()
    except Exception as e:
        out['tab'] = {'error': f'{type(e).__name__}: {str(e)[:160]}'}
    state = '拼图验证码挡着，等人拖' if out['tab'].get('captcha') else '可以查'
    return _out('知网今天还剩 %d 次检索、%d 篇下载；%s' % (out['quota']['remaining'], out['pdf_quota']['remaining'], state), out)


def _ccdc_search(a):
    from shared.adapters import ccdc
    p = {'op': 'search', **{k: (a.get(k) or '').strip() or None for k in ('compound', 'ident', 'doi', 'author')},
         'database': a.get('database') or 'Published'}
    ccdc.search_url(p['compound'] or '', p['ident'] or '', p['doi'] or '', p['author'] or '', p['database'])  # 参数不对当场报
    return _chemdb_run('ccdc', p, 1, lambda db: ccdc.search(p['compound'] or '', p['ident'] or '', p['doi'] or '',
                                                            p['author'] or '', p['database']), wait_s=_pi_wait(a))


def _ccdc_detail(a):
    from shared.adapters import ccdc
    n = int(a.get('n') or 0)
    if n < 1:
        raise ValueError('给 n（当前结果列表上的序号，从 1 数）')
    last = (_load(_chemdb_usage_path()).get('searches') or {}).get('ccdc') or {}
    p = {'op': 'detail', 'n': n, **{k: last.get(k) for k in ('compound', 'ident', 'doi', 'author', 'database')}}
    return _chemdb_run('ccdc', p, 1, lambda db: ccdc.detail(n), wait_s=_pi_wait(a))


def _ccdc_current(a):
    from shared.adapters import ccdc
    if not _chemdb_lock.acquire(blocking=False):
        raise ValueError('有一个检索正在用浏览器；等它跑完（chemdb_result）再读')
    try:
        r = _clean(ccdc.current())
    finally:
        _chemdb_lock.release()
    return _out('ccdc %s：%s' % (r.get('code'), r.get('why') or 'OK'), r)


def _jcr_journal(a):
    from shared.adapters import jcr
    q = (a.get('journal') or '').strip()
    if not q:
        raise ValueError('给 journal（刊名 / JCR 缩写 / ISSN）')
    p = {'op': 'journal', 'journal': q.upper(), 'year': int(a['year']) if a.get('year') else None}
    return _chemdb_run('jcr', p, 1, lambda db: jcr.journal(q, p['year']), wait_s=_pi_wait(a))


def _scopus_search(a):
    from shared.adapters import scopus
    p = {'op': 'search', 'query': scopus.build_query(a.get('query')), 'sort': (a.get('sort') or 'relevance').lower()}
    scopus.results_url(p['query'], p['sort'])
    return _chemdb_run('scopus', p, 1, lambda db: scopus.search(p['query'], p['sort']), wait_s=_pi_wait(a))


def _scopus_citing(a):
    from shared.adapters import scopus
    n = int(a.get('n') or 0)
    if n < 1:
        raise ValueError('给 n（当前 Scopus 结果页上的序号）')
    last = (_load(_chemdb_usage_path()).get('searches') or {}).get('scopus') or {}
    p = {'op': 'citing', 'n': n, 'query': last.get('query'), 'sort': last.get('sort')}
    return _chemdb_run('scopus', p, 1, lambda db: scopus.citing(n), wait_s=_pi_wait(a))


def _scopus_page(a):
    from shared.adapters import scopus
    n = int(a.get('page') or 2)
    last = (_load(_chemdb_usage_path()).get('searches') or {}).get('scopus')
    if not last:
        raise ValueError('Scopus 还没有搜过，先 scopus_search')
    p = {'op': 'page', 'query': last.get('query'), 'sort': last.get('sort'),
         'n': last.get('n') if last.get('op') == 'citing' else None}   # 被引列表的翻页和原检索的翻页分开缓存
    return _chemdb_run('scopus', p, n, lambda db: scopus.page(n), wait_s=_pi_wait(a))


def _tansoole_search(a):
    from shared.adapters import tansoole
    q = (a.get('query') or '').strip()
    if not q:
        raise ValueError('query 不能空')
    return _chemdb_run('tansoole', {'op': 'search', 'query': q}, 1, lambda db: tansoole.search(q), wait_s=_pi_wait(a))


def _tansoole_page(a):
    from shared.adapters import tansoole
    n = int(a.get('page') or 2)
    last = (_load(_chemdb_usage_path()).get('searches') or {}).get('tansoole')
    if not last:
        raise ValueError('探索平台还没有搜过（或账本被清了），先 tansoole_search')
    return _chemdb_run('tansoole', {'op': 'page', 'query': last.get('query')}, n, lambda db: tansoole.page(n), wait_s=_pi_wait(a))


def _webdb_status(a):
    """不碰网站：CCDC / JCR / Scopus / 探索平台 今天各剩几次、要等几秒、标签状态（登录页 / 验证页）。"""
    from shared.adapters import ccdc, jcr, scopus, tansoole
    out = {}
    for db, mod in (('ccdc', ccdc), ('jcr', jcr), ('scopus', scopus), ('tansoole', tansoole)):
        used, daily, wait = chemdb_quota(db)
        st = {'quota': {'used_today': used, 'daily_limit': daily, 'remaining': max(0, daily - used)},
              'min_gap_s': gap_of(db), 'wait_s': round(wait, 1)}
        try:
            st['tab'] = mod.status()
        except Exception as e:
            st['tab'] = {'error': f'{type(e).__name__}: {str(e)[:120]}'}
        out[db] = st
    return _out('CCDC 剩 %d、JCR 剩 %d、Scopus 剩 %d、探索平台剩 %d 次' % tuple(
        out[d]['quota']['remaining'] for d in ('ccdc', 'jcr', 'scopus', 'tansoole')), out)


def cap(name, handler, limit=None, spill_dir=None):
    """包一层：结构化结果超过 MAX_OUT 字节就写成文件、只回路径（2026-10：6 篇 outline 合一次 batch，
    JSON 在 64 KB 处被截成半截）。文件在 logs/science_out/，B 机 WSL 读得到。"""
    limit = limit or MAX_OUT

    def h(a):
        r = handler(a)
        data = r.get('structured') if isinstance(r, dict) else None
        if data is None:
            return r
        raw = json.dumps(data, ensure_ascii=False)
        size = len(raw.encode('utf-8'))
        if size <= limit:
            return r
        from shared.kernel import paths
        d = spill_dir or paths.runtime('science_out')
        os.makedirs(d, exist_ok=True)
        _sweep(d)
        p = os.path.join(d, '%s-%s-%d.json' % (name, time.strftime('%Y%m%d-%H%M%S'), int(time.time() * 1000) % 1000))
        io.open(p, 'w', encoding='utf-8').write(raw)
        summary = {k: (len(v) if isinstance(v, (list, dict)) else v) for k, v in data.items()
                   if not isinstance(v, str) or len(v) < 200}
        return _out('%s：结果 %d 字节，超过 %d，已写到 %s' % (r.get('text', ''), size, limit, to_wsl(p)),
                    {'spilled': to_wsl(p), 'bytes': size, 'summary': summary,
                     'hint': '整份结果在 spilled 文件里（JSON）；或者缩小请求（少几处 / maxChars / offset 分页）'})
    return h


def _sweep(d, keep_s=3 * 86400):
    """落出来的大结果留三天。"""
    now = time.time()
    try:
        for f in os.listdir(d):
            p = os.path.join(d, f)
            if now - os.path.getmtime(p) > keep_s:
                os.remove(p)
    except OSError:
        pass


# ══════════════════════════════════════════════════════════════════════
# 装配
# ══════════════════════════════════════════════════════════════════════

_KEY = {'type': 'string', 'description': '证据库 id 或 DOI'}

TOOLS = [
    ('topic_add', '把一批文献放进一个专题（给用户看的分组，比如「综述：XX」用到的参考文献）；专题不存在就新建。'
     'refs 给 DOI 或证据库 id；note 是这批每篇的备注（可空）；topic_note 是专题本身的说明（可空，给了就覆盖）。'
     '只收证据库里已有的，没有的回在 missing。重复加不报错。',
     {'topic': {'type': 'string'}, 'refs': {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 200},
      'note': {'type': 'string'}, 'topic_note': {'type': 'string'}}, ['topic', 'refs'], _topic_add),
    ('topic_remove', '从专题里拿掉几篇（文献本身不动）。', {'topic': {'type': 'string'},
     'refs': {'type': 'array', 'items': {'type': 'string'}}}, ['topic', 'refs'], _topic_remove),
    ('topic_list', '全部专题：名字、说明、篇数、谁建的。', {}, [], _topic_list),
    ('topic_items', '一个专题里的文献：id、DOI、标题、年份、每篇的备注。', {'topic': {'type': 'string'}}, ['topic'], _topic_items),
    ('library_db_search', '证据库里有没有：按标题 / DOI / 期刊子串搜，回目录卡（有无正文、SI、已解析）。',
     {'query': {'type': 'string'}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 200}}, ['query'], _db_search),
    ('library_retrieve', '向量检索证据库：最相近的段落 + 文献 id + 节地址（拿去 library_section 读上下文）。'
     '只有一行标题的碎片已滤掉；per_paper=1 每篇最多一段。',
     {'query': {'type': 'string'}, 'n': {'type': 'integer', 'minimum': 1, 'maximum': 30},
      'per_paper': {'type': 'integer', 'minimum': 0, 'maximum': 10},
      'where': {'type': 'string', 'enum': ['all', 'main', 'si']}}, ['query'], _retrieve),
    ('library_outline', '一篇的骨架：节 / 长节的段 / 表 / 图注，各自的地址、类别、字数。有 SI 的另给 si 一份。',
     {'itemKey': _KEY}, ['itemKey'], _outline),
    ('library_section', '按地址取原文：s5 一节（含子节）/ s5.p3 一段 / t1 一张表 / f2 一条图注；SI 的传 si=true。'
     '表格 format=csv|json（默认 html）。长的用 offset 分页（回 next_offset）。'
     '节号会随解析升级变：传 title（节标题）或 quote（一句原文）找回现在的位置，回复带 remapped_from。'
     '可批量：requests=[{itemKey, sectionId, title, quote, si, offset, format}]（最多 50 处）。',
     {'itemKey': _KEY, 'sectionId': {'type': 'string'}, 'si': {'type': 'boolean'},
      'requests': {'type': 'array', 'items': {'type': 'object'}},
      'offset': {'type': 'integer', 'minimum': 0},
      'title': {'type': 'string'}, 'quote': {'type': 'string'},
      'format': {'type': 'string', 'enum': ['html', 'csv', 'json']},
      'maxChars': {'type': 'integer', 'minimum': 100, 'maximum': 200000}}, [], _section),
    ('paper_files', '一篇手上的文件（正文 PDF / SI 原件 / 解析 Markdown / 图片目录），B 机 WSL 路径；'
     '另给「图号 → 图片文件」对照。',
     {'itemKey': _KEY}, ['itemKey'], _paper_files),
    ('paper_fulltext', '给 DOI 取全文（学校订阅）→ 正本 + SI 落地并解析。后台串行跑，一次最多 25 篇，'
     '同一时刻只跑一个作业。allowFetch=false 只查手上有没有（同步、零成本）。',
     {'dois': {'type': 'array', 'items': {'type': 'string'}}, 'allowFetch': {'type': 'boolean'}},
     ['dois'], _fulltext),
    ('fulltext_status', '取全文作业的进度。每篇带 code / retryable / tier（现算）；retryable 列出可续跑的 DOI；'
     'stalled=true 表示同一篇卡太久。wait_s（≤30）= 等到有新一篇完成再回；brief=false 附每篇的骨架菜单。',
     {'wait_s': {'type': 'integer', 'minimum': 0, 'maximum': MAX_WAIT}, 'brief': {'type': 'boolean'}},
     [], _status),
    ('figure_image', '一张图直接回成小 JPEG（base64，默认 ≤30 KB，最多 36 KB）：fig 给 "Figure 2" / "Scheme 1" / "2"。'
     '不用传文件。整张图（image_kind=full）要 tier=structured。',
     {'itemKey': _KEY, 'fig': {'type': 'string'}, 'max_kb': {'type': 'integer', 'minimum': 8, 'maximum': MAX_IMAGE_KB}},
     ['itemKey', 'fig'], _figure_image),
    ('fulltext_retry', '续跑：把上一个作业里撞人机验证 / 暂缓 / 网络错的再交一次（人在主力机浏览器点完验证后用）。'
     '也可以自己给 dois。规矩同 paper_fulltext。',
     {'dois': {'type': 'array', 'items': {'type': 'string'}}}, [], _retry),
    ('paper_status', '一批 DOI 或 id 的现状：在不在库、tier（none/text/structured）、SI、节 / 表 / 图数、'
     '上次取全文的 route 与错误码。零成本，不取不解析。',
     {'dois': {'type': 'array', 'items': {'type': 'string'}},
      'itemKeys': {'type': 'array', 'items': {'type': 'string'}}}, [], _paper_status),
    ('chemdb_search', '在 SciFinder 或 Reaxys 里搜一次（借主力机上已登录的浏览器），回第 1 页的结构化列表。'
     '三种入口：关键词（query）、CAS 号（query="98-80-6"）、结构式（structure=SMILES + match=exact|substructure|similarity）。'
     'CAS 号或结构式 + kind=substances → 物质列表（cas_rn / formula / name / 被多少文献、反应用到）；'
     'CAS 号 + kind=references → 先落到这个物质再取用了它的文献 / 专利（warnings 里有 via_substance）。文献列表：'
     'items[]（rank / type=journal|review|patent / title / authors / source / year / doi / patent_no / assignee / status / '
     'cited|citing / snippet / index_terms / in_library / tier）、count、page_size、pages、facets（SciFinder 带计数）、'
     'query_interpretation（库实际执行的检索式）、ai_summary、Reaxys 的 preview（整句拆成的子检索及各自条数）、complete、warnings。'
     'SciFinder 列表没有 DOI，服务端按标题去 Crossref 补（doi_match_score；<0.9 标 doi_uncertain）。'
     '当天同一检索同一页走缓存（cached=true，不扣次数）。不在缓存时：两次至少隔 30 秒（服务端会等），每库每天有上限（quota）。',
     {'db': {'type': 'string', 'enum': ['scifinder', 'reaxys'], 'description': '哪个库'},
      'query': {'type': 'string', 'description': '检索词（英文）或 CAS 号。SciFinder 会把词用 and 连起来，看 query_interpretation。'
                '和 structure 一起给 = 结构 + 关键词同时满足'},
      'structure': {'type': 'string', 'description': '结构式：SMILES（Reaxys 也收 molfile）。两个库的搜索框都不认 SMILES，服务端走它们的画图板'},
      'match': {'type': 'string', 'enum': ['exact', 'substructure', 'similarity'],
                'description': '结构怎么比：exact = 按原样（含同位素、盐等变体）/ substructure = 含这个骨架 / similarity = 相似；默认 exact'},
      'kind': {'type': 'string', 'enum': ['references', 'substances', 'reactions', 'suppliers'],
               'description': 'references = 文献 + 专利（默认）；substances = 物质列表；reactions 目前只回原样文字（用 raw=true）；'
                              'suppliers = 只 SciFinder：这个物质（CAS 号 / 名字 / 结构式，取物质列表第一个）在哪些试剂商有卖：'
                              'items[]（supplier / purity / prices[{qty, unit, currency, price, per_g}] / stock / ships_within / '
                              'country / order_number / url / orderable）+ summary（各币种最便宜每克价、国家分布）。'
                              '每页 100 家；只要国内的给 filters={"Country/Region": ["China"]}'},
      'sort': {'type': 'string', 'enum': ['relevance', 'date', 'cited'], 'description': '排序，默认 relevance'},
      'filters': {'type': 'object', 'description': '只 SciFinder：{facet 名: [值]}，名与值照 facets 里写（如 '
                  '{"Document Type": ["Journal"], "Patent Status": ["Alive"]}），另认 yearFrom / yearTo（整数年）。'
                  '只有页面左侧显示出来的值能选（每个 facet 前 5 个），选不到会进 warnings'},
      'mode': {'type': 'string', 'enum': ['auto', 'original'],
               'description': 'original = SciFinder 改写了检索式时按原样搜（点 Search Original Query）'},
      'within': {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 3,
                 'description': '只 SciFinder：「在结果内检索」，最多 3 个词，和当前结果取交集。CAS 号 / 结构 + 主题词就用它'
                                '（如 query="10043-35-3", kind="references", within=["self-healing"]）。'
                                '要更准就用 filters 的 Concept（CAS 人工标引，如 "Self-healing materials"）'},
      'wait_s': {'type': 'integer', 'minimum': 0, 'maximum': 50,
                 'description': '最多陪着等几秒（默认 25）。没查完回 code=PENDING + job_id，再用 chemdb_result 取'},
      'subset': {'type': 'integer', 'minimum': 0, 'description': '只 Reaxys：开预览（preview）里的第几组，从 0 数。'
                 '相似检索分 tight / near / average / wide / widest 五档（默认开第一个有结果的、最严的那档）；'
                 '关键词会被拆成几组子检索。先不给看 preview，再按需要给 subset 重搜'},
      'raw': {'type': 'boolean', 'description': '另附整页原文 text（排查用，平时别开）'},
      'maxChars': {'type': 'integer', 'minimum': 1000, 'maximum': 45000, 'description': 'raw 原文的上限'}},
     ['db'], _chemdb_search),
    ('chemdb_page', '这个库最近一次 chemdb_search 的第 page 页（同样的结构化字段；同一页当天走缓存）。额度与间隔规矩同上。',
     {'db': {'type': 'string', 'enum': ['scifinder', 'reaxys']},
      'page': {'type': 'integer', 'minimum': 1, 'description': '页码；pages 告诉你一共几页'},
      'wait_s': {'type': 'integer', 'minimum': 0, 'maximum': 50},
      'raw': {'type': 'boolean'}, 'maxChars': {'type': 'integer', 'minimum': 1000, 'maximum': 45000}},
     ['db', 'page'], _chemdb_page),
    ('chemdb_substance', '只 Reaxys：一个物质的物性数值表 —— 把人点开物质条目上「Physical Data - 41」看到的表读回来。'
     '回 substance（cas_rn / name / formula / n_physical_data……）+ groups[]（group = Reaxys 的分组名，如 Boiling Point / Density / '
     'Refractive Index / Dissociation Exponent（pKa 在这组）/ Association (MCS)；n = 这组共几条；rows[] 每行是 {列名（带单位）: 值} '
     '+ reference{citation, type, authors, doi, cited}；truncated 表示只回了前 max_rows 行）。'
     'query 给 CAS 号最准（先搜物质列表，再读第 n 个）；不给就读 Reaxys 最近一次 kind=substances 的列表。'
     '算一次检索（扣 Reaxys 当天额度），当天同参数走缓存。只要几项就给 groups，省得把 Bioactivity 那种大组也点开。',
     {'query': {'type': 'string', 'description': 'CAS 号（最准，如 "105-83-9"）或物质名'},
      'n': {'type': 'integer', 'minimum': 1, 'description': '物质列表里第几个（一个 CAS 号偶尔对应几个条目；默认 1）'},
      'section': {'type': 'string', 'enum': ['physical', 'other'],
                  'description': 'physical = Physical Data（默认）；other = Other Data'},
      'groups': {'type': 'array', 'items': {'type': 'string'},
                 'description': '只点开名字含这些词的组（不分大小写），如 ["Boiling", "Density", "Dissociation"]；不给就全点开'},
      'max_rows': {'type': 'integer', 'minimum': 1, 'maximum': 100, 'description': '每组最多回几行（默认 20）'},
      'wait_s': {'type': 'integer', 'minimum': 0, 'maximum': 50}},
     [], _chemdb_substance),
    ('chemdb_result', '取 chemdb_search / chemdb_page 回了 PENDING 的那次检索：给 job_id，最多等 wait_s 秒（默认 25，≤50）。'
     '查完回完整结果，没完再回 PENDING。不扣次数。',
     {'job_id': {'type': 'string'}, 'wait_s': {'type': 'integer', 'minimum': 0, 'maximum': 50}},
     ['job_id'], _chemdb_result),
    ('chemdb_status', '不碰网站、不扣次数：两个库今天各剩几次、几点重置、要等几秒、最近一次检索（词 + 网址）、'
     '浏览器标签停在哪（login=login_page 就是要人去登录）、人手动导出文件的文件夹和里面的文件。做一组检索之前先看它。',
     {}, [], _chemdb_status),
    ('polyinfo_search', '在 NIMS 聚合物数据库 PoLyInfo 里检索一次（借主力机上已登录的浏览器），回结果列表第 1 页：'
     'items[]（rank / name / id_type=PID|COID|BDID / id / cu_formula / n_samples / properties[{name, unit, median, mode, '
     'variance, points}]）、count、n_homopolymer / n_copolymer / n_blend。三种入口可组合：name（聚合物名子串，英文，'
     '如 "poly(methyl methacrylate)"）、pid（P040048 / P905362 / BD000088）、formula（一个重复单元的分子式，如 "C16H38O5Si4"，'
     '查含这种单元的均聚物与共聚物）。prop 选一种性质只回它的统计（写法照网站下拉框，如 "Glass transition temperature"、'
     '"Density"、"Tensile modulus"；写错会回 NOT_FOUND 并列出全部可选值）。'
     '当天同一检索走缓存（不扣次数）。两次至少隔 45 秒、每天 15 次（服务端强制）。网站条款禁止批量获取：只查眼前问题需要的。',
     {'name': {'type': 'string'}, 'pid': {'type': 'string'},
      'formula': {'type': 'string', 'description': '重复单元分子式；只认 C H B Br Cl D F Fe Si Ge I N Na O P S Sn，最多 6 种元素'},
      'prop': {'type': 'string'},
      'atoms_only': {'type': 'boolean', 'description': '只要「只由这些元素组成」的（配合 formula）'},
      'wait_s': {'type': 'integer', 'minimum': 0, 'maximum': 50}}, [], _polyinfo_search),
    ('polyinfo_samples', 'PoLyInfo 一种聚合物（pid）的样品列表：samples[]（no / sample_id / material_type / additives / '
     'polymer_type / properties[{name, value, unit}]）。没有组成与出处 —— 那在 polyinfo_sample。额度规矩同上。',
     {'pid': {'type': 'string'}, 'wait_s': {'type': 'integer', 'minimum': 0, 'maximum': 50}}, ['pid'], _polyinfo_samples),
    ('polyinfo_sample', 'PoLyInfo 第 n 个样品（照 polyinfo_samples 的 no）的详情：sample.info（聚合信息、分子量…）、'
     'reference / doi、components、composition（mol% 等）、properties（值 + 测量条件 / 方法）、'
     'related_tables（原文的「组成 vs 性质」整张表：title / header / rows —— 常含进料与聚合物组成，可估竞聚率）。'
     '这一页网站每次要人机验证：回 code=CAPTCHA_REQUIRED（主力机已弹提醒），等人点完再调 polyinfo_current，别重调这个。',
     {'pid': {'type': 'string'}, 'n': {'type': 'integer', 'minimum': 1},
      'wait_s': {'type': 'integer', 'minimum': 0, 'maximum': 50}}, ['pid'], _polyinfo_sample),
    ('polyinfo_current', '不导航、不扣次数：读 PoLyInfo 标签上现在那一页（结果列表 / 样品列表 / 样品详情各按各的字段）。'
     '人在浏览器里点完验证码之后用；还挡着会再回 CAPTCHA_REQUIRED。',
     {}, [], _polyinfo_current),
    ('polyinfo_status', '不碰网站、不扣次数：PoLyInfo 今天还剩几次、要等几秒、标签停在哪（login_page / captcha）。',
     {}, [], _polyinfo_status),
    ('cnki_search', '在中国知网检索一次（学校按 IP 授权，借主力机浏览器），回第 1 页：items[]（rank / title / authors / '
     'source（刊名或学位授予单位）/ date / type（期刊 / 硕士 / 博士 / 中国专利…）/ cited / downloads / url；专利是 inventors / '
     'applicants / date_applied / date_published / patent_no）、count、pages、counts（各库条数，如 {学术期刊: 47, 学位论文: 34, 博士: 4}）。'
     '按「主题」检索，中文词最好（如「聚硼硅氧烷」「硼酸酯 动态共价 弹性体」）。当天同一检索走缓存。两次至少隔 30 秒、每天 30 次。',
     {'query': {'type': 'string'},
      'kind': {'type': 'string', 'enum': ['all', 'journal', 'thesis', 'phd', 'master', 'conference', 'patent'],
               'description': 'thesis = 博硕都要；patent = 中国专利；默认 all'},
      'sort': {'type': 'string', 'enum': ['relevance', 'date', 'cited', 'downloads']},
      'wait_s': {'type': 'integer', 'minimum': 0, 'maximum': 50}}, ['query'], _cnki_search),
    ('cnki_page', '知网最近一次 cnki_search 的第 page 页（每页 20 条；同一页当天走缓存）。规矩同上。',
     {'page': {'type': 'integer', 'minimum': 1}, 'wait_s': {'type': 'integer', 'minimum': 0, 'maximum': 50}},
     ['page'], _cnki_page),
    ('cnki_detail', '知网一篇的摘要页：detail.fields（摘要、关键词、DOI、分类号、导师、学科专业、基金；专利：申请号、申请人、'
     '主权项、法律状态…）、detail.outline（学位论文的整本章节目录）、title / authors_line / institution。'
     'n = 当前结果页上的序号（rank），或直接给 url。同一篇当天走缓存。撞拼图验证码回 CAPTCHA_REQUIRED，人拖完用 cnki_current。',
     {'n': {'type': 'integer', 'minimum': 1}, 'url': {'type': 'string'},
      'wait_s': {'type': 'integer', 'minimum': 0, 'maximum': 50}}, [], _cnki_detail),
    ('cnki_download', '知网一篇的全文 PDF：在摘要页点「PDF下载」，存进主力机的导出文件夹，回 path（WSL 路径，直接读）/ filename / '
     'title / bytes，**并直接收进证据库**（library_id；有 DOI 按 DOI，没有按知网文件名 cnki_…；标题作者刊名年份取自知网页，可加进专题）。'
     '常用：先 cnki_search，再给 n（当前结果页序号）。也可给摘要页 url；都不给 = 下用户在主力机浏览器里打开着的那篇'
     '（真撞上安全验证、人拖完之后用）。一次一篇；两次至少隔 60 秒、每天 5 篇（单独的额度，见 cnki_status 的 '
     'pdf_quota）—— 只下眼前真要读的。code：OK / CAPTCHA_REQUIRED（拼图，人拖完再交一次）/ NO_PDF_LINK（只有 CAJ）/ '
     'NOT_PDF（点了没拿到文件）。同一篇当天走缓存，不重复下。',
     {'n': {'type': 'integer', 'minimum': 1}, 'url': {'type': 'string'},
      'wait_s': {'type': 'integer', 'minimum': 0, 'maximum': 50}}, [], _cnki_download),
    ('cnki_current', '不导航、不扣次数：读知网最新那个标签现在的页面（结果页 / 摘要页）。人拖完拼图验证码之后用。',
     {}, [], _cnki_current),
    ('cnki_status', '不碰网站、不扣次数：知网今天还剩几次、要等几秒、最近一次检索、验证码挡没挡着。', {}, [], _cnki_status),
    ('ccdc_search', '在 CCDC Access Structures 检索晶体结构（CSD + ICSD 已发表的），回列表（最多 30 条）：items[]（rank / refcode / '
     'deposition（CCDC 号）/ icsd / space_group / cell / name / synonyms），超过 30 条标 truncated。按 compound（英文化合物名）、'
     'ident（CCDC 号或结构代码，可多个空格隔开）、doi（一篇论文的 DOI → 它的全部结构）、author 检索。'
     '条款不许程序批量取：两次至少隔 45 秒、每天 15 次。只读、不下载 CIF（要 CIF 请用户自己点 Download）。',
     {'compound': {'type': 'string'}, 'ident': {'type': 'string'}, 'doi': {'type': 'string'}, 'author': {'type': 'string'},
      'database': {'type': 'string', 'enum': ['Published', 'CSD', 'ICSD']},
      'wait_s': {'type': 'integer', 'minimum': 0, 'maximum': 50}}, [], _ccdc_search),
    ('ccdc_detail', 'CCDC 当前结果列表第 n 条的详情：detail（refcode / name / space_group / cell / deposition / data_doi（10.5517/…）/ '
     'deposited_on / synonyms / publications[{citation, doi}]）。键长等几何数据只在 CIF 里，这里没有。规矩同上。'
     '撞验证页回 CAPTCHA_REQUIRED（主力机已弹提醒），人填完用 ccdc_current。',
     {'n': {'type': 'integer', 'minimum': 1}, 'wait_s': {'type': 'integer', 'minimum': 0, 'maximum': 50}}, ['n'], _ccdc_detail),
    ('ccdc_current', '不导航、不扣次数：读 CCDC 标签上现在那一页（列表 / 详情）。人填完验证页之后用。', {}, [], _ccdc_current),
    ('jcr_journal', '查一本刊在 JCR（Clarivate）的期刊页：journal（title / issn / eissn / publisher / edition / year / jif / jif_no_self / '
     'jci / oa_pct / ranks[{category, year, rank, quartile, percentile}] / categories）。journal 参数给刊名、JCR 缩写或 ISSN；'
     '没有完全同名的会取下拉第一个并写进 warnings（核对 title）。year 不给 = 最新一年。同一本当天走缓存。'
     '两次至少隔 20 秒、每天 30 次；一次一本，别批量查一串刊。',
     {'journal': {'type': 'string'}, 'year': {'type': 'integer', 'minimum': 1997},
      'wait_s': {'type': 'integer', 'minimum': 0, 'maximum': 50}}, ['journal'], _jcr_journal),
    ('scopus_search', '在 Scopus 检索一次，回第 1 页：items[]（rank / eid / title / authors / source / citation（卷期页）/ year / cited / '
     'type / open_access / doi（按标题去 Crossref 补，doi_match_score）/ in_library / tier）、count、pages。query：普通词（按题名 / 摘要 / '
     '关键词）或 Scopus 检索式（TITLE-ABS-KEY(…) AND PUBYEAR > 2019、DOI(…)、AUTH(…)…）。sort：relevance / cited / date。'
     '两次至少隔 30 秒、每天 20 次；同一检索同一页当天走缓存。',
     {'query': {'type': 'string'}, 'sort': {'type': 'string', 'enum': ['relevance', 'cited', 'date']},
      'wait_s': {'type': 'integer', 'minimum': 0, 'maximum': 50}}, ['query'], _scopus_search),
    ('scopus_citing', 'Scopus 当前结果页第 n 条「谁引用了它」的列表第 1 页（字段同 scopus_search，另有 citing_of）。规矩同上。',
     {'n': {'type': 'integer', 'minimum': 1}, 'wait_s': {'type': 'integer', 'minimum': 0, 'maximum': 50}}, ['n'], _scopus_citing),
    ('scopus_page', 'Scopus 当前列表（最近一次 scopus_search 或 scopus_citing）的第 page 页。规矩同上。',
     {'page': {'type': 'integer', 'minimum': 1}, 'wait_s': {'type': 'integer', 'minimum': 0, 'maximum': 50}}, ['page'], _scopus_page),
    ('webdb_status', '不碰网站、不扣次数：CCDC / JCR / Scopus / 探索平台 今天各剩几次、要等几秒、标签停在哪（登录页 / 验证页）。', {}, [], _webdb_status),
    ('tansoole_search', '在探索平台（泰坦科技，用户实际买药品的地方，借主力机上已登录的浏览器）搜一个药品，回第 1 页（每页 100 条）：'
     'compounds[]（name_cn / name_en / cas_rn / mdl / formula / mw）、items[]（rank / brand / catalog_no / product_no / spec / qty / unit / '
     'grams / purity / grade / lead_time / in_stock / lead_days[min,max]（工作日）/ futures（期货）/ on_sale / action（购买 | 询价）/ '
     'compound / url）、summary（各品牌条数、现货条数、现货里最大包装克数、纯度、最快的非现货要几天）、other_categories、count、pages。'
     '**不含价格**（网站用防抓取字体，用户定不读）—— 价格用 chemdb_search db=scifinder kind=suppliers。'
     '设计实验时用它判断：哪些品牌有货、要不要等几周、有没有现货的替代规格 / 纯度。CAS 号最准，中文名、英文名也行。'
     '当天同一检索走缓存。两次至少隔 30 秒、每天 30 次。',
     {'query': {'type': 'string', 'description': 'CAS 号（如 98-80-6）、中文名、英文名或货号'},
      'wait_s': {'type': 'integer', 'minimum': 0, 'maximum': 50}}, ['query'], _tansoole_search),
    ('tansoole_page', '探索平台最近一次 tansoole_search 的第 page 页（同一页当天走缓存）。规矩同上。',
     {'page': {'type': 'integer', 'minimum': 1}, 'wait_s': {'type': 'integer', 'minimum': 0, 'maximum': 50}},
     ['page'], _tansoole_page),
]


def _ping(a):
    return _out(f'{NAME} {VERSION} 在跑', {'ok': True, 'server': NAME, 'version': VERSION})


def build(full):
    """装成给 Claude Science 的服务：只挂它做不到的那几样（取全文 + 读取回来的全文）。每个都套 50 KB 上限。"""
    s = MCPStdioServer(NAME, VERSION, instructions=INSTRUCTIONS)
    s.register_tool('ping', '存活检查：服务在跑、是哪一版。', {'type': 'object', 'properties': {}}, _ping)
    for name, desc, props, req, fn in TOOLS:
        s.register_tool(name, desc, {'type': 'object', 'properties': props, 'required': req}, cap(name, fn))
    have = {t['name']: t for t in full._tools}
    missing = [n for n in BORROW if n not in have]
    if missing:
        # 借不到 = 某个工具包没挂上；喊出来，别让它悄悄少一个工具（踩坑 #173 同类）
        print(f'⚠ /science 少了这些工具（完整服务里没有）：{", ".join(missing)}', file=sys.stderr)
    for n in BORROW:
        t = have.get(n)
        if t:
            s.register_tool(n, t['description'], t['inputSchema'], cap(n, t['handler']))  # 不打 confirm
    return s
