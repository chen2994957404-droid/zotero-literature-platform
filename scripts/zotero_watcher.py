# -*- coding: utf-8 -*-
"""Zotero 闭环轮询器：
检测带触发标签的文献 → 拉PDF → MineRU解析+精读 → 回写Zotero笔记 → 改标签。
依赖 Zotero 桌面开着（本地API读）+ Zotero Web API key（写回）。
运行: python zotero_watcher.py
"""
import os, time, json, re, subprocess, sys, urllib.request, traceback
try:
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))))
    from modules.config import get_key as _cfg_get
except Exception:
    _cfg_get = lambda n, **kw: _o.environ.get(n, '')

# ===== 运行日志 =====
_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'workflow_data', 'logs')
os.makedirs(_LOG_DIR, exist_ok=True)
_LOG_FILE = os.path.join(_LOG_DIR, 'zotero_watcher.log')
_print = print
def print(*args, **kwargs):
    msg = ' '.join(str(a) for a in args)
    line = f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] {msg}'
    _print(line, **kwargs)
    try:
        with open(_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass

# ===== 配置 =====
ZOTERO_LOCAL = 'http://localhost:23119/api'
ZOTERO_HEADERS = {'Zotero-Allowed-Request': 'true'}
# 本机配置（Zotero 用户ID / 附件目录）统一从 modules.config 读，换电脑只改 .env
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
try:
    from modules.config import need_site as _site
except Exception:
    _site = lambda n: _os.environ.get(n) or (_ for _ in ()).throw(RuntimeError(f'缺少本机设置 {n}，请在控制面板或 .env 中配置'))
_UID = _site('ZOTERO_USER_ID')
_STORAGE = _site('ZOTERO_STORAGE')
USER_ID = _UID                      # 本地API里的库id
STORAGE_DIR = _STORAGE
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
WEB_API_KEY = _cfg_get('ZOTERO_API_KEY')  # zotero.org 写权限key

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
DEEPREAD = os.path.join(SCRIPT_DIR, 'deepread_v4.py')
MINERU_SCRIPT = os.path.join(SCRIPT_DIR, 'mineru_parse.py')
EXTRACT_SCRIPT = os.path.join(SCRIPT_DIR, 'extract_structured.py')  # 结构化抽取（粗层）
SI_DEEPREAD = os.path.join(SCRIPT_DIR, 'si_deepread.py')            # SI 实验细节精读
MERGE_SCRIPT = os.path.join(SCRIPT_DIR, 'merge_summary.py')         # 正文+SI 合并
# 新的以文献为单元的库结构：workflow_data/library/<key>/{parsed/, summary.html}
LIBRARY = os.path.join(ROOT, 'workflow_data', 'library')
os.makedirs(LIBRARY, exist_ok=True)

# 引入附件上传能力
sys.path.insert(0, SCRIPT_DIR)
from zotero_upload_attachment import upload_attachment

DEEPSEEK_KEY = _cfg_get('DEEPSEEK_KEY')
PROVIDER = os.environ.get('DEEPREAD_PROVIDER', 'deepseek')
MODEL = os.environ.get('DEEPREAD_MODEL', 'deepseek-v4-flash')  # 默认flash省钱；重要文献用 重跑精读_pro.bat 切pro

def zget(path):
    req = urllib.request.Request(ZOTERO_LOCAL + path, headers=ZOTERO_HEADERS)
    return json.loads(urllib.request.urlopen(req, timeout=15).read())

def find_pdf(item_key):
    """查文献的正文PDF附件本地路径（智能排除补充材料，多个时选最大的）"""
    children = zget(f'/users/{USER_ID}/items/{item_key}/children')
    # 补充材料/附录 的常见特征：
    #  - suppmat/supporting/supplement/appendix 等通用词
    #  - -si-/_si_/si.pdf 及独立的 SI 命名
    #  - MOESM/ESM = Springer/Nature 系 Electronic Supplementary Material 的标准命名（踩坑15）
    SUPP_PAT = re.compile(
        r'suppmat|supp\b|supporting|supplement|-si-|_si_|\bsi\.pdf|appendix|'
        r'moesm|_esm\b|electronic.?supplementary', re.I)
    candidates = []  # (path, att_key, size, is_supp, is_fulltext)
    for c in children:
        if c['data'].get('itemType') == 'attachment' and c['data'].get('contentType') == 'application/pdf':
            att_key = c['key']
            # 附件的 Zotero 标题（规范命名是最可靠信号，工单·find_pdf 优先信任命名）
            att_title = (c['data'].get('title') or '').strip()
            title_is_supp = bool(SUPP_PAT.search(att_title)) or att_title.upper() == 'SI'
            is_fulltext = att_title.lower() == 'full text pdf'   # Zotero 规范化的正文命名
            d = os.path.join(STORAGE_DIR, att_key)
            if os.path.isdir(d):
                for f in os.listdir(d):
                    if f.lower().endswith('.pdf'):
                        fp = os.path.join(d, f)
                        try: size = os.path.getsize(fp)
                        except: size = 0
                        is_supp = bool(SUPP_PAT.search(f)) or title_is_supp
                        candidates.append((fp, att_key, size, is_supp, is_fulltext))
    if not candidates:
        return None, None
    # ① 最优先：title=="Full Text PDF" 的规范正文（不靠大小猜，最可靠）
    ft = [c for c in candidates if c[4] and not c[3]]
    if ft:
        ft.sort(key=lambda c: c[2], reverse=True)
        return ft[0][0], ft[0][1]
    # ② 兜底：非补充材料里选最大的（未规范化命名时的退路）
    main = [c for c in candidates if not c[3]]
    pool = main if main else candidates
    pool.sort(key=lambda c: c[2], reverse=True)
    return pool[0][0], pool[0][1]

_DOCX_CT = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'


def has_si(item_key):
    """该文献是否有 SI 附件。支持 PDF 和 .docx（Elsevier 的 SI 常是 docx）。"""
    try:
        children = zget(f'/users/{USER_ID}/items/{item_key}/children')
    except Exception:
        return False
    for c in children:
        d = c['data']
        if d.get('itemType') != 'attachment':
            continue
        if d.get('contentType') not in ('application/pdf', _DOCX_CT):
            continue
        t = (d.get('title') or '').strip(); fn = (d.get('filename') or '')
        SUPP = re.compile(r'suppmat|supp\b|supporting|supplement|-si-|_si_|\bsi\.pdf|'
                          r'appendix|moesm|_esm\b|electronic.?supplementary', re.I)
        if SUPP.search(t) or SUPP.search(fn) or t.upper() == 'SI':
            return True
    return False


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

    pdf_path, att_key = find_pdf(key)
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
                               errors='replace', timeout=600)
            if r.returncode != 0:
                print(f'  [正文解析失败] {r.stderr[-300:]}'); return
        r = subprocess.run([sys.executable, DEEPREAD, parsed_dir, out_html, PROVIDER, MODEL, DEEPSEEK_KEY],
                           capture_output=True, text=True, encoding='utf-8',
                           errors='replace', timeout=900, env=env)
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
                           errors='replace', timeout=900, env=env)
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
                           errors='replace', timeout=300, env=env)
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
                           errors='replace', timeout=300, env=env)
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


def delete_old_summary(item_key):
    """删除该文献下已有的 summary 附件，避免重复"""
    try:
        base = f'https://api.zotero.org/users/{USER_ID}'
        wh = {'Zotero-API-Key': WEB_API_KEY, 'Zotero-API-Version': '3'}
        req = urllib.request.Request(base + f'/items/{item_key}/children', headers=wh)
        children = json.loads(urllib.request.urlopen(req, timeout=15).read())
        for c in children:
            if c['data'].get('itemType') == 'attachment' and c['data'].get('title') == 'summary':
                dk = c['key']; dv = c['version']
                dreq = urllib.request.Request(base + f'/items/{dk}', method='DELETE',
                    headers={**wh, 'If-Unmodified-Since-Version': str(dv)})
                urllib.request.urlopen(dreq, timeout=15)
                time.sleep(0.3)
    except Exception:
        pass

def extract_text_summary(html_path):
    """从精读HTML里抽取纯文字部分（去图），作为笔记正文（图太大不塞进笔记）"""
    import re as _re
    html = open(html_path, encoding='utf-8').read()
    body = html.split('<body>')[-1].split('</body>')[0] if '<body>' in html else html
    # 去掉 img 标签（base64太大）
    body = _re.sub(r'<img[^>]*>', '<p>【图见本地完整版】</p>', body)
    return body

def writeback(item_key, html_path, web_uid):
    """通过 Zotero Web API 把精读作为笔记写回（纯文字版），并更新标签"""
    try:
        note_body = extract_text_summary(html_path)
        head = f'<h1>📖 图文精读（自动生成 {time.strftime("%Y-%m-%d %H:%M")}）</h1>' \
               f'<p><b>含图完整版</b>：workflow_data/summary/{os.path.basename(html_path)}</p><hr>'
        note_html = head + note_body
        base = f'https://api.zotero.org/users/{web_uid}/items'
        payload = json.dumps([{"itemType":"note","parentItem":item_key,
                               "note":note_html,"tags":[{"tag":"精读笔记"}]}]).encode('utf-8')
        req = urllib.request.Request(base, data=payload, method='POST',
            headers={'Zotero-API-Key': WEB_API_KEY, 'Content-Type':'application/json','Zotero-API-Version':'3'})
        json.loads(urllib.request.urlopen(req, timeout=25).read())
        print(f'  [回写成功] 精读笔记已写回 Zotero（同步后可见）')
        swap_tag(item_key, web_uid)
    except Exception as e:
        print(f'  [回写失败] {e}')

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

def swap_tag(item_key, web_uid):
    """兼容旧调用：默认置为「正文精读」。"""
    set_state_tag(item_key, web_uid, TAG_MAIN)

def main():
    # 单实例锁：任务计划自启一份、看门狗又启一份时，第二份直接退出（踩坑 #30）。
    # 两份同时轮询会抢同一篇文献，导致重复精读/重复上传。
    try:
        from modules.proc_lock import single_instance, holder
        if not single_instance('zotero_watcher'):
            print(f'已有一份 watcher 在跑（PID={holder("zotero_watcher")}），本次退出')
            return
    except Exception as e:
        print(f'[提醒] 单实例锁不可用（{e}），继续运行')
    print(f'Zotero闭环轮询器启动。触发标签: 「{TRIGGER_TAG}」')
    print(f'回写: {"已配置Web API" if WEB_API_KEY else "未配key(仅生成本地精读)"}')
    seen = set()
    heartbeat = os.path.join(_LOG_DIR, 'watcher_heartbeat.txt')
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
                except Exception:
                    traceback.print_exc()
        except Exception:
            traceback.print_exc()
        time.sleep(60)  # 每60秒检查一次，避免API限流

if __name__ == '__main__':
    import urllib.parse
    main()
