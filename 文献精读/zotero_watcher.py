# -*- coding: utf-8 -*-
"""Zotero 闭环轮询器：
检测带触发标签的文献 → 拉PDF → MineRU解析+精读 → 回写Zotero笔记 → 改标签。
依赖 Zotero 桌面开着（本地API读）+ Zotero Web API key（写回）。
运行: python zotero_watcher.py
"""
import os, sys, time, json, re, subprocess, urllib.request, urllib.parse, traceback

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
from core import paths

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
from adapters.zotero_client import (zget, find_pdf as _find_pdf, has_si,
                                    USER_ID, STORAGE_DIR)
# 本机配置（Zotero 用户ID / 附件目录）统一从 core.config 读，换电脑只改 .env
_NOWIN = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
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
DEEPREAD = os.path.join(SCRIPT_DIR, 'deepread_v4.py')
MINERU_SCRIPT = os.path.join(SCRIPT_DIR, 'mineru_parse.py')
EXTRACT_SCRIPT = os.path.join(ROOT, '数据抽取', 'extract_structured.py')  # 结构化抽取（粗层）
SI_DEEPREAD = os.path.join(SCRIPT_DIR, 'si_deepread.py')            # SI 实验细节精读
MERGE_SCRIPT = os.path.join(SCRIPT_DIR, 'merge_summary.py')         # 正文+SI 合并
# 新的以文献为单元的库结构：workflow_data/library/<key>/{parsed/, summary.html}
LIBRARY = paths.LIBRARY
os.makedirs(LIBRARY, exist_ok=True)

# 引入附件上传能力
sys.path.insert(0, SCRIPT_DIR)
from zotero_upload_attachment import upload_attachment

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
    lib_dir = os.path.join(LIBRARY, key)
    parsed_dir = os.path.join(lib_dir, 'parsed')
    out_html = os.path.join(lib_dir, 'summary.html')
    si_html = os.path.join(lib_dir, 'si_summary.html')
    env = dict(os.environ, PYTHONIOENCODING='utf-8', DEEPSEEK_KEY=DEEPSEEK_KEY)

    pdf_path, att_key = _find_pdf(key, return_att_key=True)
    si_exists = has_si(key)
    main_done = os.path.exists(out_html)
    si_done = os.path.exists(si_html)
    print(f'  正文PDF:{"有" if pdf_path else "无"} SI:{"有" if si_exists else "无"} '
          f'| 已精读 正文:{"是" if main_done else "否"} SI:{"是" if si_done else "否"}')

    if not pdf_path and not si_exists:
        print('  [跳过] 无任何可精读的PDF附件')
        if WEB_API_KEY:
            set_state_tag(key, USER_ID, TAG_NOPDF)
        return

    # ── A. 正文：有PDF且没精读过才做 ──
    if pdf_path and not main_done:
        os.makedirs(parsed_dir, exist_ok=True)
        if os.path.exists(os.path.join(parsed_dir, 'layout.json')):
            print('  [复用] 已有解析结果')
        else:
            r = subprocess.run([sys.executable, MINERU_SCRIPT, pdf_path, parsed_dir],
                               capture_output=True, text=True, encoding='utf-8',
                               errors='replace', timeout=600, creationflags=_NOWIN)
            if r.returncode != 0:
                print(f'  [正文解析失败] {r.stderr[-300:]}'); return
        r = subprocess.run([sys.executable, DEEPREAD, parsed_dir, out_html, PROVIDER, MODEL, DEEPSEEK_KEY],
                           capture_output=True, text=True, encoding='utf-8',
                           errors='replace', timeout=900, env=env, creationflags=_NOWIN)
        if r.returncode != 0:
            print(f'  [正文精读失败] {r.stderr[-300:]}'); return
        main_done = True
        print(f'  [正文精读完成]')
    elif main_done:
        print('  [跳过正文] 已有精读，不重跑')

    # ── B. SI：有SI且没精读过才做 ──
    if si_exists and not si_done:
        r = subprocess.run([sys.executable, SI_DEEPREAD, key],
                           capture_output=True, text=True, encoding='utf-8',
                           errors='replace', timeout=900, env=env, creationflags=_NOWIN)
        print((r.stdout or '')[-300:])
        si_done = os.path.exists(si_html)
        print(f'  [SI精读{"完成" if si_done else "失败"}]')
    elif si_done:
        print('  [跳过SI] 已有精读，不重跑')

    # ── C. 合并（两者都有时）──
    final_html = out_html
    if main_done and si_done:
        r = subprocess.run([sys.executable, MERGE_SCRIPT, key, '--no-upload'],
                           capture_output=True, text=True, encoding='utf-8',
                           errors='replace', timeout=300, env=env, creationflags=_NOWIN)
        merged = os.path.join(lib_dir, 'summary_full.html')
        if os.path.exists(merged):
            final_html = merged
            print('  [已合并] 正文+SI')
    elif si_done and not main_done:
        final_html = si_html

    if not os.path.exists(final_html):
        print('  [失败] 没有产出任何精读'); return
    out_html = final_html   # 供后续回写使用
    # 存元数据供向量化用
    try:
        meta = {'key': key, 'title': item['data'].get('title', ''),
                'DOI': item['data'].get('DOI', ''), 'date': item['data'].get('date', ''),
                'model': MODEL, 'time': time.strftime('%Y-%m-%d %H:%M')}
        json.dump(meta, open(os.path.join(lib_dir, 'meta.json'), 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
    except Exception:
        pass
    # 2.5 结构化抽取（粗层）：把这篇抽成对齐字段，自动并入 structured/ 对比表
    try:
        r = subprocess.run([sys.executable, EXTRACT_SCRIPT, key],
                           capture_output=True, text=True, encoding='utf-8',
                           errors='replace', timeout=300, env=env, creationflags=_NOWIN)
        if r.returncode == 0:
            print(f'  [结构化抽取完成] 已并入 structured/compare.md')
        else:
            print(f'  [结构化抽取失败] {r.stderr[-200:]}')
    except Exception as e:
        print(f'  [结构化抽取异常] {e}')
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
            state = (TAG_FULL if (main_done and si_done)
                     else TAG_SI if si_done
                     else TAG_MAIN)
            set_state_tag(key, USER_ID, state)
        except Exception as e:
            print(f'  [附件导入失败] {e}')
    else:
        print('  [提示] 未配 ZOTERO_API_KEY，跳过回写。')

def find_existing_summary(item_key):
    """找该文献已有的 summary 附件 key（用于复用，避免删除→同步冲突）。"""
    try:
        children = zget(f'/users/{USER_ID}/items/{item_key}/children')
        for c in children:
            d = c['data']
            if d.get('itemType') == 'attachment' and (d.get('title') or '').strip() == 'summary':
                return c['key']
    except Exception:
        pass
    return None

# 注：回写「精读笔记」的旧方案（writeback / extract_text_summary / swap_tag /
# delete_old_summary）已于本次清理删除。它早被「复用 summary 附件」取代，
# 其中 delete_old_summary 的「先删后传」正是踩坑 #28 反复弹同步冲突框的根因，
# 留着只会让人以为还能用。要回写请用 set_state_tag + upload_attachment。
def set_state_tag(item_key, web_uid, new_state):
    """设置状态标签（互斥）：移除所有旧状态标签，只留 new_state。保留用户自己的其它标签。"""
    try:
        req = urllib.request.Request(f'https://api.zotero.org/users/{web_uid}/items/{item_key}',
            headers={'Zotero-API-Key': WEB_API_KEY, 'Zotero-API-Version':'3'})
        cur = json.loads(urllib.request.urlopen(req, timeout=15).read())
        ver = cur['version']
        old = [t.get('tag') for t in cur['data'].get('tags', []) if t.get('tag') in ALL_STATE_TAGS]
        tags = [t for t in cur['data'].get('tags', []) if t.get('tag') not in ALL_STATE_TAGS]
        if new_state:
            tags.append({'tag': new_state})
        patch = json.dumps({'tags': tags}).encode('utf-8')
        req2 = urllib.request.Request(f'https://api.zotero.org/users/{web_uid}/items/{item_key}',
            data=patch, method='PATCH',
            headers={'Zotero-API-Key': WEB_API_KEY, 'Zotero-API-Version':'3',
                     'If-Unmodified-Since-Version': str(ver), 'Content-Type':'application/json'})
        urllib.request.urlopen(req2, timeout=15)
        print(f'  [状态] {"/".join(old) or "无"} → {new_state}')
    except Exception as e:
        print(f'  [标签更新失败] {e}')

def main():
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
    seen = set()
    fail_streak = [0]      # 连续失败轮数，用于「持续异常」提醒与「已恢复」提示
    heartbeat = paths.runtime('watcher_heartbeat.txt')
    while True:
        # 心跳：每轮开始写时间戳，看门狗据此判断存活（工单·watcher 看门狗）
        try:
            with open(heartbeat, 'w', encoding='utf-8') as f:
                f.write(str(int(time.time())))
        except Exception:
            pass
        try:
            q = urllib.parse.quote(' || '.join(TRIGGER_TAGS))
            items = zget(f'/users/{USER_ID}/items?tag={q}&limit=25')
            print(f'[心跳] 轮询正常，待处理 {len(items)} 篇')
            for it in items:
                key = it['key']
                if key in seen:
                    continue
                seen.add(key)
                try:
                    process_item(it)
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
    main()
