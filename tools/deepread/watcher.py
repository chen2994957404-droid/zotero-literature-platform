# -*- coding: utf-8 -*-
"""deepread 的常驻服务：Zotero 闭环轮询器。

检测带触发标签的文献 → 拉PDF → MineRU解析+精读 → 回写Zotero附件 → 改标签。
依赖 Zotero 桌面开着（本地API读）+ Zotero Web API key（写回）。

运行: python -m tools.deepread.watcher      （日常由任务计划 + 看门狗拉起）

**它是整条线里唯一知道 Zotero 有标签这回事的地方**：
`tools.deepread.run()` 只陈述「实际做成了什么」，翻译成标签在这里
（也是两台机器分工的闸门所在 —— 常驻服务只许在运行端跑）。
"""
import os, sys, time, urllib.parse, traceback

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
from shared.kernel import heartbeat, paths, role
from shared.kernel.cli import flag

from shared.kernel.config import get_key

# ===== 运行日志 =====
# 走 shared.kernel.log：带时间戳、同时打屏和落盘、超过 5MB 自动轮转。
# （此前这里是「把内置 print 整个换掉」的 hack —— 读代码的人会以为只是打屏，
#   实际在写文件；而且没有轮转，常驻服务的日志只会一直长下去。）
from shared.kernel.log import get_logger
print = get_logger('zotero_watcher')       # 保留 print 这个名字，下方几十处调用不用改

# ===== 配置 =====
# Zotero 的读取能力全部走公理件 —— 重构前这里重复实现了 zget / find_pdf /
# has_si / SUPP_PAT，与 shared/adapters/zotero_client 里的同名实现并存（违反宪法铁律 1）。
from shared.adapters.zotero_client import (zget, find_pdf as _find_pdf, has_si,
                                    find_child_attachment, upload_attachment,
                                    USER_ID)
# 标签状态机（哪些标签互斥、做成了什么打哪个标签）在 tags.py —— 它是纯规则，
# 不该藏在常驻服务里，否则「跑一批 SI」也得把心跳和单实例锁一起拖进来。
from tools import deepread
from tools.deepread import batch as _batch
from tools.deepread.tags import (TRIGGER_TAG, TRIGGER_TAGS, TAG_NOPDF,
                                 STATE_TAG, set_state_tag)

WEB_API_KEY = get_key('ZOTERO_API_KEY')    # zotero.org 写权限key

# 新的以文献为单元的库结构：library/<key>/{parsed/, summary.html}
LIBRARY = paths.LIBRARY
os.makedirs(LIBRARY, exist_ok=True)

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
    # 「哪些步骤该跳过、哪个失败了不该拖累别的」全在 tools/deepread 里，
    # 并且每一步都记进 shared.kernel.jobs（谁产的、哪个模型、哪版提示词、失败原因）。
    r = deepread.run(key, item=item, pdf_path=pdf_path, si_exists=si_exists,
                     provider=PROVIDER, model=MODEL, llm_key=DEEPSEEK_KEY, log=print)

    if r.state == 'nopdf':
        if WEB_API_KEY:
            set_state_tag(key, TAG_NOPDF, log=print)
        return
    if r.state == 'failed':
        return          # 失败原因流水线已经打进日志了，这里不重复喊

    out_html = r.final_html
    state_tag = STATE_TAG[r.state]      # 事实 → 标签，映射只此一处
    # 2.5 结构化抽取（粗层）：把这篇抽成对齐字段，自动并入 structured/ 对比表
    # 它自己会记账并跳过已抽过的，失败也只返回 None，不会拖垮回写。
    #
    # ⚠ 这是本仓库**唯一一处 tools 调 tools**（违反 REBUILD.md 第三节硬规则 2）。
    # 真正的原因是「打个标签就全自动」这条闭环横跨两个工具，而 REBUILD.md
    # 又明确要求 watcher 住在 tools/deepread/。R7 窗定夺：要么把 watcher 挪去
    # host/（它本来就是平台服务，不是能力），要么把这一步做成调用方传进来的回调。
    # 记在 docs/待办与需求.md，别在重构窗里顺手改掉行为。
    from tools import extract          # noqa: 见上
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
                _batch._put_local(att_key, out_html)
                print(f'  [附件已更新] summary（本地storage已就位，点开即图文精读）')
            # 按实际完成情况置状态标签
            set_state_tag(key, state_tag, log=print)
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


# 同一篇隔多久可以再试一次（回写失败那类，标签没换掉、条目也没变化）
RETRY_AFTER = 1800          # 30 分钟


def should_process(key, version, seen, now):
    """这一篇现在该不该处理？—— watcher 轮询的唯一判据。

    **原来这里是一个 `seen` 集合：处理过一次就永远跳过。**
    它想防的是「回写失败 → 标签没换掉 → 每 60 秒重跑一次烧钱」，
    但它同时挡掉了**用户重新打标签**这个明确请求 ——
    而「先精读正文，后来补了 SI，再打一次待处理」正是文档里写明的核心用法。
    真实后果：用户打了标签，watcher 每分钟都看得见它，却一小时一动不动，
    日志里连一行「发现」都没有（2026-08-28 用户实测撞上，见踩坑 #67）。

    现在的判据两条，满足其一就处理：
      1. **条目变了**（`version` 变化）—— 用户改了标签/元数据，是明确请求
      2. **距上次尝试超过 30 分钟** —— 给「上次没做完」一个自愈机会，
         而不是等到 watcher 重启

    为什么不怕重跑烧钱：每一步都是幂等的（`shared.kernel.jobs` + 产物检查），
    重跑一篇已完成的只花几百毫秒、零 API 调用。
    """
    last = seen.get(key)
    if last is None:
        return True
    last_ver, last_at = last
    if last_ver != version:
        return True
    return (now - last_at) >= RETRY_AFTER


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
        from shared.adapters.llm_client import check_key as _ds
        from shared.adapters.pdf_parse import check_token as _mineru
        from shared.adapters.zotero_client import check_key as _zot
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
        from shared.kernel.proc_lock import single_instance, holder
        if not single_instance('zotero_watcher'):
            print(f'已有一份 watcher 在跑（PID={holder("zotero_watcher")}），本次退出')
            return
    except Exception as e:
        print(f'[提醒] 单实例锁不可用（{e}），继续运行')
    print(f'Zotero闭环轮询器启动。触发标签: 「{TRIGGER_TAG}」')
    print(f'回写: {"已配置Web API" if WEB_API_KEY else "未配key(仅生成本地精读)"}')
    log_key_status()
    seen = {}          # key -> (上次处理时的条目 version, 上次处理时刻)
    fail_streak = [0]      # 连续失败轮数，用于「持续异常」提醒与「已恢复」提示
    # 后台线程固定节奏报活：精读一篇要几分钟到几十分钟，期间主线程根本回不到
    # 循环顶部。原来把心跳写在循环开头，于是**正在干活的 watcher 会被看门狗当成
    # 卡死杀掉**（主力机一个月被误杀约 20 次，每次都白花一份 MineRU + DeepSeek）。
    # 见 shared/kernel/heartbeat.py 与踩坑记录。
    heartbeat.start('watcher')
    while True:
        # 「还活着」由后台线程报；这里只记「有进展」——
        # 两个信号回答的是不同问题，见 shared/kernel/heartbeat.py 开头的说明。
        try:
            q = urllib.parse.quote(' || '.join(TRIGGER_TAGS))
            items = zget(f'/users/{USER_ID}/items?tag={q}&limit=25')
            heartbeat.progress('watcher')      # 轮询成功 = 有进展
            print(f'[心跳] 轮询正常，待处理 {len(items)} 篇')
            for it in items:
                key = it['key']
                if not should_process(key, it.get('version'), seen, time.time()):
                    continue
                seen[key] = (it.get('version'), time.time())
                try:
                    process_item(it)
                    heartbeat.progress('watcher')   # 一篇做完 = 有进展
                except Exception as e:
                    # 单篇失败不能拖垮整个轮询；但必须记进日志，否则是静默失败
                    print(f'  [处理失败] {key}: {type(e).__name__}: {e}')
                    print('  ' + traceback.format_exc().replace('\n', '\n  ').rstrip())
                    seen.pop(key, None)    # 允许下一轮重试（可能只是网络抖动）
        except Exception as e:
            # ⚠ 踩坑 #33：原来这里是 traceback.print_exc()，打到标准输出。
            # 但服务是 pythonw 无窗口运行的，标准输出直接被丢弃 ——
            # 于是 watcher 每轮都在失败，日志却一片空白，看起来「心跳正常」。
            # 曾出现 Zotero 挂了 19 分钟、用户毫不知情的情况。**必须写进日志文件。**
            hint = ''
            if isinstance(e, OSError) or 'refused' in str(e).lower():
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
    from shared.kernel import errors as _err
    try:
        main()
    except _err.WrongMachineError as _e:
        print(str(_e))
        sys.exit(2)
