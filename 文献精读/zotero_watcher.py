# -*- coding: utf-8 -*-
"""Zotero 闭环轮询器：
检测带触发标签的文献 → 拉PDF → MineRU解析+精读 → 回写Zotero笔记 → 改标签。
依赖 Zotero 桌面开着（本地API读）+ Zotero Web API key（写回）。
运行: python zotero_watcher.py
"""
import os, sys, time, json, re, urllib.request, urllib.parse, traceback

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
from core import heartbeat, paths, role
from core.cli import flag

from core.config import get_key, need_site, get_site

# ===== 运行日志 =====
# 走 core.log：带时间戳、同时打屏和落盘、超过 5MB 自动轮转。
# （此前这里是「把内置 print 整个换掉」的 hack —— 读代码的人会以为只是打屏，
#   实际在写文件；而且没有轮转，常驻服务的日志只会一直长下去。）
from core.log import get_logger
print = get_logger('zotero_watcher')       # 保留 print 这个名字，下方几十处调用不用改

# ===== 配置 =====
# Zotero 的读取能力全部走公理件 —— 重构前这里重复实现了 zget / find_pdf /
# has_si / SUPP_PAT，与 adapters/zotero_client 里的同名实现并存（违反宪法铁律 1）。
from adapters import zotero_client as zotero
from adapters.zotero_client import (zget, find_pdf as _find_pdf, has_si,
                                    find_child_attachment, upload_attachment,
                                    USER_ID, WEB_USER_ID, STORAGE_DIR)
# 本机配置（Zotero 用户ID / 附件目录）统一从 core.config 读，换电脑只改 .env
# ── 标签状态机（用户定，2026-07-25）───────────────────────────────
# 打「待处理」→ 自动检测有哪些附件、哪些还没精读 → 补做缺的 → 按结果换状态标签。
# 状态互斥：一篇文献同一时间只有一个状态标签。
TRIGGER_TAG = '待处理'                     # 打这个标签就触发（原「待精读」）
# 触发别名：用户不该被迫记住我们改过的词。任一个都算触发（踩坑 #29）。
# Zotero API 的 tag 参数支持 "A || B" 表示或。
TRIGGER_TAGS = ['待处理', '待精读']
TAG_MAIN = '正文精读'                      # 只有正文被精读
TAG_SI   = 'SI精读'                        # 只有SI被精读（罕见，备用）
TAG_FULL = '全文精读'                      # 正文+SI 都精读了
TAG_NOPDF = '无附件'                       # 没找到可精读的PDF（提示用户，而非静默跳过）
ALL_STATE_TAGS = [TRIGGER_TAG, TAG_MAIN, TAG_SI, TAG_FULL, TAG_NOPDF, '待精读', '已精读']
DONE_TAG = TAG_MAIN                        # 兼容旧代码引用
WEB_API_KEY = get_key('ZOTERO_API_KEY')  # zotero.org 写权限key

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
# 精读流水线（解析→正文精读→SI→合并）现在是**一个函数**，不再是五个 subprocess。
# 见 pipelines/deepread/__init__.py 开头「为什么」。
from pipelines import deepread, extract
# 新的以文献为单元的库结构：workflow_data/library/<key>/{parsed/, summary.html}
LIBRARY = paths.LIBRARY
os.makedirs(LIBRARY, exist_ok=True)

# 「实际做成了什么」→ Zotero 状态标签。**这个映射只能在这一层**：
# pipelines 不知道 Zotero 有什么标签，它只陈述事实（见 deepread.Result）。
STATE_TAG = {'full': TAG_FULL, 'main': TAG_MAIN, 'si': TAG_SI, 'nopdf': TAG_NOPDF}

DEEPSEEK_KEY = get_key('DEEPSEEK_KEY')
PROVIDER = os.environ.get('DEEPREAD_PROVIDER', 'deepseek')
MODEL = os.environ.get('DEEPREAD_MODEL', 'deepseek-v4-flash')  # 默认flash省钱；重要文献用 重跑精读_pro.bat 切pro
def process_item(item):
    """状态机：检测有哪些附件、哪些还没精读 → 补做缺的 → 置对应状态标签。

    正文有/SI有 → 全文精读 ；只正文 → 正文精读 ；只SI → SI精读 ；都没有 → 无附件
    已有正文精读 + 有SI → 只补SI，标签升级为 全文精读（不重跑正文，省钱）
    """
    key = item['key']
    title = item['data'].get('title', key)[:50]
    print(f'[发现] {title}')
    pdf_path = _find_pdf(key)
    si_exists = has_si(key)

    # ── 精读流水线（原来是三段 subprocess，现在是一次函数调用）──
    # 「哪些步骤该跳过、哪个失败了不该拖累别的」全在 pipelines/deepread 里，
    # 并且每一步都记进 core.jobs（谁产的、哪个模型、哪版提示词、失败原因）。
    r = deepread.run(key, item=item, pdf_path=pdf_path, si_exists=si_exists,
                     provider=PROVIDER, model=MODEL, llm_key=DEEPSEEK_KEY, log=print)

    if r.state == 'nopdf':
        if WEB_API_KEY:
            set_state_tag(key, WEB_USER_ID, TAG_NOPDF)
        return
    if r.state == 'failed':
        return          # 失败原因流水线已经打进日志了，这里不重复喊

    out_html = r.final_html
    state_tag = STATE_TAG[r.state]      # 事实 → 标签，映射只此一处
    # 2.5 结构化抽取（粗层）：把这篇抽成对齐字段，自动并入 structured/ 对比表
    # 阶段 3 下半起也是函数调用 —— **至此本流水线不再拉任何子进程**。
    # 它自己会记账并跳过已抽过的，失败也只返回 None，不会拖垮回写。
    extract.run(key, log=print)
    # 3. 回写 Zotero：**复用已有 summary 附件、只更新文件内容**（不删条目）
    #    踩坑：原先"先删旧附件再传新的"，删除动作进入同步链 → Zotero 每篇都弹"冲突解决"框。
    #    改为复用同一附件条目，只覆盖本地 storage 文件，避免产生删除记录。
    if WEB_API_KEY:
        try:
            att_key = find_existing_summary(key)
            if att_key:
                print(f'  [复用附件条目] {att_key}（不删不新建，避免同步冲突）')
            else:
                # 上传带重试：网络抖动（SSL EOF / 超时）不该让整篇精读白做
                att_key = None
                for attempt in range(3):
                    try:
                        att_key = upload_attachment(key, out_html, 'summary')
                        break
                    except Exception as ue:
                        wait = 5 * (attempt + 1)
                        print(f'  [上传失败 {attempt+1}/3] {str(ue)[:80]} → {wait}s 后重试')
                        time.sleep(wait)
                if not att_key:
                    print('  [上传三次失败] 精读已生成在本地，下次打「待处理」会自动重传')
            # 直接写入本地Zotero storage，点开即最新精读
            if att_key:
                local_dir = os.path.join(STORAGE_DIR, att_key)
                os.makedirs(local_dir, exist_ok=True)
                import shutil
                shutil.copy(out_html, os.path.join(local_dir, 'summary.html'))
                print(f'  [附件已更新] summary（本地storage已就位，点开即图文精读）')
            # 按实际完成情况置状态标签
            set_state_tag(key, WEB_USER_ID, state_tag)
        except Exception as e:
            print(f'  [附件导入失败] {e}')
    else:
        print('  [提示] 未配 ZOTERO_API_KEY，跳过回写。')

def find_existing_summary(item_key):
    """找该文献已有的 summary 附件 key（用于复用，避免删除→同步冲突）。

    ⚠ 这里**必须问云端**，不能问本地 API（踩坑 #64）：附件是我们自己传上
    zotero.org 的，本地 Zotero 要等下一次同步才看得见。问本地会得到「没有」，
    于是又传一份 —— 重复附件正是踩坑 #28 要防的东西。
    """
    return find_child_attachment(item_key, 'summary')

# 注：回写「精读笔记」的旧方案（writeback / extract_text_summary / swap_tag /
# delete_old_summary）已于本次清理删除。它早被「复用 summary 附件」取代，
# 其中 delete_old_summary 的「先删后传」正是踩坑 #28 反复弹同步冲突框的根因，
# 留着只会让人以为还能用。要回写请用 set_state_tag + upload_attachment。
def set_state_tag(item_key, web_uid, new_state):
    """设置状态标签（互斥）：移除所有旧状态标签，只留 new_state。保留用户自己的其它标签。

    **策略在这里，写在适配层**：哪些标签互斥是本工作流的业务规则，
    而「怎么安全地写进 Zotero」（鉴权、版本冲突、机器角色守卫）是
    `adapters.zotero_client` 的事。重构前这两件事搅在一起，
    于是同样的写实现被抄了三份（踩坑：守卫也要跟着抄三遍，漏一处闸就没了）。
    """
    try:
        cur = zotero.get_item(item_key)
        old = [t.get('tag') for t in cur['data'].get('tags', [])
               if t.get('tag') in ALL_STATE_TAGS]
        tags = [t for t in cur['data'].get('tags', [])
                if t.get('tag') not in ALL_STATE_TAGS]
        if new_state:
            tags.append({'tag': new_state})
        zotero.replace_tags(item_key, tags, action=f'把状态标签改成「{new_state}」')
        print(f'  [状态] {"/".join(old) or "无"} → {new_state}')
    except Exception as e:
        print(f'  [标签更新失败] {e}')


def log_key_status():
    """启动时把三把密钥的**有效性**写进日志。零成本，几秒钟。

    为什么放在这儿（踩坑 #66）：2026-08-28 发现主力机的 DeepSeek 与 Zotero 密钥
    早已失效，而心跳正常、体检全绿 —— 因为那时只查「读得到」。
    更麻烦的是**密钥只有本机的交互式会话读得到**（凭据库的限制），
    远程排查时看不见真相。watcher 本身就跑在那个会话里，
    所以让它开机说一句，是唯一能把这件事变成「可观察」的地方。

    **不因为密钥无效就拒绝启动** —— Zotero 读取仍然可用，
    而且拒启会让「服务没了」和「密钥坏了」两件事长得一样。
    """
    try:
        from adapters.llm_client import check_key as _ds
        from adapters.pdf_parse import check_token as _mineru
        from adapters.zotero_client import check_key as _zot
        bad = []
        for name, fn in (('DeepSeek', _ds), ('MineRU', _mineru)):
            ok, msg = fn()
            print(f'[密钥] {name}: {msg}')
            if ok is False:
                bad.append(name)
        ok, msg, _d = _zot()
        print(f'[密钥] Zotero: {msg}')
        if ok is False:
            bad.append('Zotero')
        if bad:
            print(f'[⚠ 密钥失效] {"、".join(bad)} —— 精读会失败。'
                  f'请在控制面板重填，然后重启本服务')
    except Exception as e:
        print(f'[密钥自检跳过] {type(e).__name__}: {e}')


def main():
    # 机器角色守卫：常驻服务只能在运行端（主力机）跑。
    # 两台都跑会重复精读同一篇、重复写回 Zotero、重复烧钱，标签状态机还会互相打架。
    role.require_prod('常驻精读监听（watcher）', force=flag('--force'))
    # 单实例锁：任务计划自启一份、看门狗又启一份时，第二份直接退出（踩坑 #30）。
    # 两份同时轮询会抢同一篇文献，导致重复精读/重复上传。
    try:
        from core.proc_lock import single_instance, holder
        if not single_instance('zotero_watcher'):
            print(f'已有一份 watcher 在跑（PID={holder("zotero_watcher")}），本次退出')
            return
    except Exception as e:
        print(f'[提醒] 单实例锁不可用（{e}），继续运行')
    print(f'Zotero闭环轮询器启动。触发标签: 「{TRIGGER_TAG}」')
    print(f'回写: {"已配置Web API" if WEB_API_KEY else "未配key(仅生成本地精读)"}')
    log_key_status()
    seen = set()
    fail_streak = [0]      # 连续失败轮数，用于「持续异常」提醒与「已恢复」提示
    # 后台线程固定节奏报活：精读一篇要几分钟到几十分钟，期间主线程根本回不到
    # 循环顶部。原来把心跳写在循环开头，于是**正在干活的 watcher 会被看门狗当成
    # 卡死杀掉**（主力机一个月被误杀约 20 次，每次都白花一份 MineRU + DeepSeek）。
    # 见 core/heartbeat.py 与踩坑记录。
    heartbeat.start('watcher')
    while True:
        # 「还活着」由后台线程报；这里只记「有进展」——
        # 两个信号回答的是不同问题，见 core/heartbeat.py 开头的说明。
        try:
            q = urllib.parse.quote(' || '.join(TRIGGER_TAGS))
            items = zget(f'/users/{USER_ID}/items?tag={q}&limit=25')
            heartbeat.progress('watcher')      # 轮询成功 = 有进展
            print(f'[心跳] 轮询正常，待处理 {len(items)} 篇')
            for it in items:
                key = it['key']
                if key in seen:
                    continue
                seen.add(key)
                try:
                    process_item(it)
                    heartbeat.progress('watcher')   # 一篇做完 = 有进展
                except Exception as e:
                    # 单篇失败不能拖垮整个轮询；但必须记进日志，否则是静默失败
                    print(f'  [处理失败] {key}: {type(e).__name__}: {e}')
                    print('  ' + traceback.format_exc().replace('\n', '\n  ').rstrip())
                    seen.discard(key)      # 允许下一轮重试（可能只是网络抖动）
        except Exception as e:
            # ⚠ 踩坑 #33：原来这里是 traceback.print_exc()，打到标准输出。
            # 但服务是 pythonw 无窗口运行的，标准输出直接被丢弃 ——
            # 于是 watcher 每轮都在失败，日志却一片空白，看起来「心跳正常」。
            # 曾出现 Zotero 挂了 19 分钟、用户毫不知情的情况。**必须写进日志文件。**
            hint = ''
            if isinstance(e, (urllib.error.URLError, OSError)) or 'refused' in str(e).lower():
                hint = '（多半是 Zotero 桌面程序没开 —— 本地 API 连不上）'
            print(f'[轮询失败] {type(e).__name__}: {e} {hint}')
            fail_streak[0] += 1
            if fail_streak[0] in (5, 30, 120):    # 5分钟/半小时/两小时各提醒一次，不刷屏
                print(f'[持续异常] 已连续失败 {fail_streak[0]} 轮{hint}，请检查后再试')
        else:
            if fail_streak[0]:
                print(f'[已恢复] 之前连续失败 {fail_streak[0]} 轮，现已恢复正常')
                fail_streak[0] = 0
        time.sleep(60)  # 每60秒检查一次，避免API限流

if __name__ == '__main__':
    # 机器角色不对时给一句人话，而不是甩一坨 traceback 到日志里 ——
    # 这个失败在主力机首次部署时必然发生一次（ROLE 默认是最安全的 dev）。
    from core import errors as _err
    try:
        main()
    except _err.WrongMachineError as _e:
        print(str(_e))
        sys.exit(2)
