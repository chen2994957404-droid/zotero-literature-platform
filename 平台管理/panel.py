# -*- coding: utf-8 -*-
"""控制面板 · 平台的仪表盘与开关（定理件，不含任何业务逻辑）

设计原则（服从架构宪法）：
  本文件**一行业务逻辑都不实现**。状态取自 health_check 的检查函数，配置取自
  modules.config，进程取自系统查询。它只是「现有积木的视图 + 遥控器」。
  任何新功能都应先做成积木，再由面板调用 —— 绝不在面板里写实现。

能做什么（都是可逆、零风险的事）：
  - 看：各服务是否正常、哪些进程在跑、数据资产统计、最近日志
  - 改：API 密钥、各环节用哪个模型（写入 .env，自动备份旧版）
  - 动：重启 watcher / Ollama 等后台服务

刻意**不做**的（不可逆或要花钱，继续走人工确认）：
  删除数据、全库重抽、改 Zotero 库、触发批量精读。

安全：只绑定 127.0.0.1（外部机器访问不到）；密钥默认脱敏显示。

用法: python scripts/panel.py     然后浏览器开 http://127.0.0.1:8777
      双击「控制面板.bat」会自动开好并打开浏览器。
"""
import os, sys, json, time, subprocess, threading, webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

# 【标准开头】项目根加入 import 路径 + 强制 UTF-8 输出（详见 docs/代码规范_标准脚本模板.md）
_ROOT = os.path.dirname(os.path.abspath(__file__))
while True:
    if os.path.isdir(os.path.join(_ROOT, 'modules')):
        break                      # 项目根特征：modules/ 目录只在根存在
    parent = os.path.dirname(_ROOT)
    if parent == _ROOT:
        break                      # 到盘符根，兜底
    _ROOT = parent
sys.path.insert(0, _ROOT)
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from modules.cli import flag

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = _ROOT
sys.path.insert(0, SCRIPT_DIR)  # health_check 同在本文件夹

from modules.config import (get_key, set_keys, get_model, mask,
                            MODEL_SETTINGS, ENV_FILE, SITE_SETTINGS, get_site,
                            keyring_status, key_location,
                            migrate_secrets_to_keyring)
from modules.subproc import run as _run, powershell   # 统一走静默子进程调用

PORT = int(os.environ.get('PANEL_PORT', '8777'))
HOST = '127.0.0.1'          # 只监听本机，外部访问不到

KEY_NAMES = [
    ('DEEPSEEK_KEY',    'DeepSeek（精读/抽取/问答）', True),
    ('ZOTERO_API_KEY',  'Zotero（回写附件与标签）',   True),
    ('MINERU_TOKEN',    'MineRU（PDF 解析）',         True),
    ('SILICONFLOW_KEY', '硅基流动（图表数字化，可空）', False),
    ('SCIVERSE_KEY',    'Sciverse（全球文献检索，可空）', False),
]

# 面板可重启的后台服务：任务计划名 → 显示名
SERVICES = {
    'ZoteroLiteratureWatcher': '文献精读监听',
    'OllamaService':           '本地 Ollama（问答/向量化）',
    'ZoteroApp':               'Zotero 主程序',
    'LiteratureAutoSync':      '自动同步',
}


# ───────────────────────── 数据采集（全部只读） ─────────────────────────

def collect_status():
    """服务健康状态。直接复用 health_check 的检查函数，不重写判断逻辑。"""
    import health_check as H
    checks = [
        ('配置密钥', H.c_config), ('Zotero 服务', H.c_zotero),
        ('Ollama 服务', H.c_ollama), ('数据资产', H.c_data),
        ('后台任务', H.c_services),
    ]
    out = []
    for name, fn in checks:
        try:
            status, msg = fn()
        except Exception as e:
            status, msg = H.FAIL, f'{type(e).__name__}: {e}'
        level = {H.OK: 'ok', H.WARN: 'warn'}.get(status, 'fail')
        out.append({'name': name, 'level': level, 'msg': msg})
    return out


def collect_processes():
    """本平台相关的 python 进程。用 CIM 查，比 wmic 可靠。"""
    ps = ("Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | "
          "Where-Object {$_.CommandLine -match 'zotero_watcher|watchdog|deepread|"
          "extract_|vectorize|auto_sync|panel'} | "
          "Select-Object ProcessId,CreationDate,CommandLine | ConvertTo-Json -Compress")
    # 走 subproc 积木：面板每 15 秒刷新一次，裸调 powershell 会不停闪窗口（踩坑 #31）
    try:
        raw = powershell(ps, timeout=25).strip()
        data = json.loads(raw) if raw else []
        if isinstance(data, dict):
            data = [data]
    except Exception:
        return []
    rows = []
    for p in data:
        cmd = (p.get('CommandLine') or '')
        # 命令行里的路径可能带引号，先剥掉再找 .py（否则 "...\watchdog.py" 匹配不上）
        script = next((os.path.basename(t.strip('"\''))
                       for t in cmd.split() if t.strip('"\'').endswith('.py')), '(未知)')
        rows.append({'pid': p.get('ProcessId'), 'script': script})
    # 同一脚本跑了多份 = 重复实例，会互相抢任务，标出来提醒
    seen = {}
    for r in rows:
        seen[r['script']] = seen.get(r['script'], 0) + 1
    for r in rows:
        r['dup'] = seen[r['script']] > 1 and r['script'] != '(未知)'
    return rows


def collect_alerts():
    """从日志里挑出「还没恢复」的故障，直接摆到面板上。

    为什么需要：心跳正常 ≠ 工作正常。曾出现 watcher 心跳照常写、
    实际每轮都连不上 Zotero、静默停摆 19 分钟的情况（踩坑 #33）。
    只看心跳会被骗，必须把失败本身暴露出来。
    """
    alerts = []
    p = os.path.join(ROOT, 'workflow_data', 'logs', 'zotero_watcher.log')
    try:
        with open(p, encoding='utf-8', errors='replace') as f:
            tail = f.readlines()[-200:]
    except Exception:
        tail = []
    i_fail = i_ok = -1
    for i, ln in enumerate(tail):
        if '[轮询失败]' in ln or '[持续异常]' in ln:
            i_fail = i
        elif '[已恢复]' in ln or '[心跳]' in ln:
            i_ok = i
    # 最后一条失败**出现在**最后一条正常之后 = 现在仍然是坏的
    if i_fail > i_ok:
        alerts.append({'level': 'fail', 'text': tail[i_fail].strip()[-160:]})
    # Zotero 没开是最常见的根因，单独探一次给出直白结论
    try:
        import urllib.request
        from modules.config import get_site
        uid = get_site('ZOTERO_USER_ID')
        urllib.request.urlopen(urllib.request.Request(
            f"{get_site('ZOTERO_API_HOST')}/api/users/{uid}/items/top?limit=1",
            headers={'Zotero-Allowed-Request': 'true'}), timeout=5)
    except Exception:
        alerts.append({'level': 'fail',
                       'text': 'Zotero 桌面程序没开 —— 精读功能现在无法工作。点下面「Zotero 主程序」的重启按钮即可。'})
    return alerts


def collect_heartbeat():
    """watcher 心跳距今多久（秒）。None 表示没有心跳文件。"""
    hb = os.path.join(ROOT, 'workflow_data', 'logs', 'watcher_heartbeat.txt')
    try:
        return int(time.time() - int(open(hb, encoding='utf-8').read().strip()))
    except Exception:
        return None


def collect_config():
    """密钥（脱敏）与模型设置。**绝不返回密钥明文**。"""
    kr_ok, kr_backend = keyring_status()
    keys = [{'name': n, 'label': lb, 'required': rq,
             'set': bool(get_key(n)), 'masked': mask(get_key(n)),
             'where': key_location(n)}
            for n, lb, rq in KEY_NAMES]
    return {
        'keys': keys,
        'plain_count': sum(1 for k in keys if k['where'] == '.env明文'),
        'keyring': {'ok': kr_ok, 'backend': kr_backend},
        'models': [{'name': n, 'label': MODEL_SETTINGS[n][0],
                    'value': get_model(n), 'default': MODEL_SETTINGS[n][1]}
                   for n in MODEL_SETTINGS],
        'sites': [{'name': n, 'label': lb, 'value': get_site(n), 'help': hp}
                  for n, lb, _d, hp in SITE_SETTINGS],
        'env_file': ENV_FILE,
    }


# ───────────────────── 找文献（后台任务 + 轮询） ─────────────────────
# 完整检索要 1~2 分钟（查询扩展 + 多式检索 + 雪球 + 向量对照），
# 不能让浏览器干等。做成「发起 → 轮询进度 → 取结果」，这也是本项目处理长任务的一贯做法。
_JOB = {'state': 'idle', 'log': [], 'result': None, 'query': '', 'started': 0}
_JOB_LOCK = threading.Lock()


def _job_log(msg):
    with _JOB_LOCK:
        _JOB['log'].append(msg)
        if len(_JOB['log']) > 60:
            del _JOB['log'][:-60]


def _run_search(params):
    try:
        sys.path.insert(0, os.path.join(ROOT, '找新文献'))
        from discover import run_discovery
        r = run_discovery(
            params['query'], limit=params.get('limit', 25),
            n_queries=params.get('n_queries', 5), mode=params.get('mode', 'survey'),
            year_from=params.get('year_from') or None,
            snowball_seeds=params.get('seeds', 3),
            topic_floor=params.get('floor', 0.45),
            log=_job_log)
        rows = []
        for i, (p, m, score) in enumerate(r['rows'], 1):
            rows.append({
                'n': i, 'title': p.get('title') or '', 'doi': p.get('doi') or '',
                'year': p.get('year'), 'venue': (p.get('venue') or '')[:40],
                'citations': p.get('citations') or 0, 'is_oa': bool(p.get('is_oa')),
                'status': m.get('status'), 'relevance': m.get('relevance'),
                'topic_sim': m.get('topic_sim'), 'lib_sim': m.get('lib_sim'),
                'from': p.get('from') or 'search',
                'nearest': (m.get('nearest') or {}).get('title', ''),
            })
        with _JOB_LOCK:
            _JOB['result'] = {
                'rows': rows, 'queries': r['queries'], 'seeds': r['seeds'],
                'snow_added': r['snow_added'], 'filtered': r['filtered'],
                'total_pool': r['total_pool'],
                'contrib': [{'q': c[0], 'got': c[1], 'new': c[2], 'err': c[3]}
                            for c in r['contrib']],
            }
            _JOB['state'] = 'done'
    except Exception as e:
        import traceback
        _job_log(f'检索失败：{type(e).__name__}: {str(e)[:200]}')
        _job_log(traceback.format_exc()[-400:])
        with _JOB_LOCK:
            _JOB['state'] = 'error'


def action_search(params):
    """发起检索。同一时间只允许一个任务，避免并发烧额度。"""
    q = (params.get('query') or '').strip()
    if not q:
        return False, '请输入要找什么'
    with _JOB_LOCK:
        if _JOB['state'] == 'running':
            return False, '已有一个检索在跑，请等它结束'
        _JOB.update({'state': 'running', 'log': [], 'result': None,
                     'query': q, 'started': time.time()})
    threading.Thread(target=_run_search, args=(params,), daemon=True).start()
    return True, '检索已开始'


def action_collect(payload):
    """把选中的文献收进 Zotero。deep=True 时打「待处理」标签触发精读。

    **两个决定分开**：收进库 与 是否精读。精读要花钱，不该被顺手触发。
    """
    dois = [d for d in (payload.get('dois') or []) if d]
    if not dois:
        return False, '没有选中任何文献'
    deep = bool(payload.get('deep'))
    try:
        sys.path.insert(0, os.path.join(ROOT, '找新文献'))
        from import_by_doi import import_dois
        from modules.lib_match import build_index
        _, have = build_index(force=True)
        skipped = [d for d in dois if d.lower() in have]
        todo = [d for d in dois if d.lower() not in have]
        if not todo:
            return True, f'选中的 {len(dois)} 篇库里都已经有了，没有导入'
        r = import_dois(todo, ['待处理'] if deep else [], verbose=False)
        msg = f'收下 {len(r["ok"])} 篇'
        if skipped:
            msg += f'（跳过 {len(skipped)} 篇库里已有的）'
        if r['failed']:
            msg += f'，{len(r["failed"])} 篇失败'
        if deep and r['ok']:
            msg += '；已打「待处理」标签，精读一分钟内自动开始'
        return True, msg
    except Exception as e:
        return False, f'{type(e).__name__}: {str(e)[:150]}'


READ_TAG = '读完'
READING_TAG = '在读'


def collect_review():
    """待评价队列：Zotero 里打了「读完」、但评测集里还没记录的。

    **评价不回写 Zotero** —— 用户的标签栏永远只有「在读/读完」两个，
    不会再堆积（他被 707 个自动标签坑过）。已评价与否记在本地评测集里。
    """
    from modules import evalset as E
    out = {'pending': [], 'stats': E.stats(), 'reasons': E.REASONS,
           'reading': 0, 'read': 0}
    try:
        from modules.zotero_client import zget, USER_ID
        import urllib.parse
        q = urllib.parse.quote(READ_TAG)
        items = zget(f'/users/{USER_ID}/items?tag={q}&limit=100')
        out['read'] = len(items)
        done = E.load()
        for it in items:
            k = it['key']
            if k in done:
                continue
            snap = E.snapshot(k)
            out['pending'].append({
                'key': k, 'title': (it['data'].get('title') or '')[:100],
                'has_summary': snap is not None, 'snapshot': snap,
            })
        r = zget(f'/users/{USER_ID}/items?tag={urllib.parse.quote(READING_TAG)}&limit=100')
        out['reading'] = len(r)
    except Exception as e:
        out['error'] = f'读不到 Zotero（是不是没开？）：{str(e)[:80]}'
    return out


def action_rate(payload):
    """保存一条精读评价。"""
    from modules import evalset as E
    key = (payload.get('key') or '').strip()
    verdict = payload.get('verdict')
    if not key or verdict not in ('good', 'bad'):
        return False, '参数不对'
    try:
        E.save(key, verdict, reasons=payload.get('reasons') or [],
               note=payload.get('note') or '', title=payload.get('title') or '')
        s = E.stats()
        tip = ''
        if s['ready']:
            tip = '（好/差样本各已≥3篇，可以做自动质量分校准了）'
        return True, f"已记录：{'好' if verdict == 'good' else '差'}。" \
                     f"评测集共 {s['total']} 条{tip}"
    except Exception as e:
        return False, str(e)[:150]


def collect_blocks():
    """积木与工作流一览。说明取自各文件夹的 CLAUDE.md 首段，不另写一份。

    这样面板上看到的介绍，永远等于 LLM 读到的介绍 —— 不会出现两套说法。
    """
    import glob, re, ast

    def first_line(md_path, fallback=''):
        if not os.path.exists(md_path):
            return fallback
        for ln in open(md_path, encoding='utf-8', errors='replace'):
            ln = ln.strip()
            if ln and not ln.startswith(('#', '>', '`', '|', '-')):
                return ln[:80]
        return fallback

    blocks = []
    for f in sorted(glob.glob(os.path.join(ROOT, 'modules', '*', '__init__.py'))):
        d = os.path.dirname(f)
        name = os.path.basename(d)
        try:
            tree = ast.parse(open(f, encoding='utf-8').read())
            doc = (ast.get_docstring(tree) or '').split('\n')[0]
            api = [n.name for n in tree.body
                   if isinstance(n, ast.FunctionDef) and not n.name.startswith('_')]
        except Exception:
            doc, api = '', []
        blocks.append({
            'name': name,
            'desc': doc.split('（')[0].replace(name + ' · ', '')[:40],
            'api': api[:6],
            'selftest': os.path.exists(os.path.join(d, 'selftest.py')),
            'doc': os.path.exists(os.path.join(d, 'CLAUDE.md')),
        })

    flows = []
    skip = {'modules', 'docs', 'workflow_data', 'n8n_data', 'wf_backup', 'b'}
    for d in sorted(os.listdir(ROOT)):
        p = os.path.join(ROOT, d)
        if (not os.path.isdir(p) or d in skip or d.startswith(('.', 'zotero_backup'))
                or not glob.glob(os.path.join(p, '*.py'))):
            continue
        flows.append({
            'name': d,
            'desc': first_line(os.path.join(p, 'CLAUDE.md'), '（还没写说明书）'),
            'files': len(glob.glob(os.path.join(p, '*.py'))),
            'doc': os.path.exists(os.path.join(p, 'CLAUDE.md')),
        })
    return {'blocks': blocks, 'flows': flows}


def action_selftest(name):
    """跑某块积木的自测。只读、可重复，是安全操作。"""
    p = os.path.join(ROOT, 'modules', name, 'selftest.py')
    if not os.path.exists(p) or os.path.sep + '..' in name or '/' in name:
        return False, '没有这块积木或它没有自测'
    try:
        r = _run([sys.executable, p], timeout=120, cwd=ROOT)
        tail = (r.stdout or r.stderr or '').strip().split('\n')[-1][:120]
        return r.returncode == 0, f'{name}：{tail}'
    except subprocess.TimeoutExpired:
        return False, f'{name}：自测超时（超过 120 秒）'
    except Exception as e:
        return False, f'{name}：{e}'


def collect_logs(name='zotero_watcher', lines=40):
    safe = {'zotero_watcher', 'watchdog', 'auto_sync'}      # 白名单，防路径穿越
    if name not in safe:
        return ['(不允许的日志名)']
    p = os.path.join(ROOT, 'workflow_data', 'logs', name + '.log')
    if not os.path.exists(p):
        return ['(日志文件还不存在)']
    try:
        with open(p, encoding='utf-8', errors='replace') as f:
            return [l.rstrip() for l in f.readlines()[-lines:]]
    except Exception as e:
        return [f'(读取失败: {e})']


def collect_recent_reads(n=8):
    """最近处理过的文献：按 summary.html 修改时间排序，附正文字数用于识别废品。"""
    import glob, re
    rows = []
    for f in glob.glob(os.path.join(ROOT, 'workflow_data', 'library', '*', 'summary.html')):
        try:
            st = os.path.getmtime(f)
            h = open(f, encoding='utf-8', errors='replace').read()
            txt = re.sub(r'\s+', '', re.sub(r'<[^>]+>', '', re.sub(r'<img[^>]*>', '', h)))
            rows.append({'key': os.path.basename(os.path.dirname(f)),
                         'when': time.strftime('%m-%d %H:%M', time.localtime(st)),
                         'chars': len(txt), 'figs': h.count('<img'),
                         'bad': len(txt) < 3000})     # 低于底线 = 疑似废品
        except Exception:
            continue
    rows.sort(key=lambda r: r['when'], reverse=True)
    return rows[:n]


# ───────────────────────── 动作（可逆，低风险） ─────────────────────────

def action_restart(task_name):
    if task_name not in SERVICES:
        return False, '未知服务'
    try:
        r = _run(['powershell', '-NoProfile', '-NonInteractive', '-Command',
                  f'Restart-ScheduledTask -TaskName {task_name}'], timeout=40)
        if r.returncode == 0:
            return True, f'{SERVICES[task_name]} 已重启'
        return False, (r.stderr or '重启失败')[:200]
    except Exception as e:
        return False, str(e)[:200]


def action_save_config(payload):
    """保存密钥/模型。空值自动跳过（不会误清空），旧 .env 自动备份。"""
    updates = {k: v for k, v in (payload or {}).items()
               if k in dict((n, 1) for n, _, _ in KEY_NAMES) or k in MODEL_SETTINGS}
    written = set_keys(updates)
    if not written:
        return False, '没有需要保存的改动'
    return True, f'已保存 {len(written)} 项：{"、".join(written)}（旧配置已备份）'


# ───────────────────────────── HTTP 服务 ─────────────────────────────

# 面板允许的访问来源：只有本机、且只有本面板自己的端口。
# 「只绑 127.0.0.1」挡得住别的机器，挡不住**你自己浏览器里打开的任何网页** ——
# 那些页面同样跑在你本机，照样能往 127.0.0.1:8777 发请求（踩坑 #47）。
_ALLOWED_HOSTS = {f'127.0.0.1:{PORT}', f'localhost:{PORT}', f'[::1]:{PORT}'}
_ALLOWED_ORIGINS = {f'http://{h}' for h in _ALLOWED_HOSTS}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass    # 不往 stdout 刷日志

    def _guard(self, need_json):
        """挡住来自其它网页的跨站请求（CSRF）与 DNS 重绑定。

        面板能改密钥、重启服务、发起烧钱的检索 —— 这些都不该被一个
        你随手打开的网页悄悄触发。三道判据，任一不过就拒绝：

        1. Host 必须是本机+本端口 —— 挡 DNS 重绑定（把恶意域名解析到 127.0.0.1）。
        2. 有 Origin 时必须是面板自己 —— 挡跨站脚本发起的请求。
        3. 写操作必须是 application/json —— HTML 表单发不出这个 Content-Type，
           跨站 fetch 想发它会先触发 CORS 预检，而本服务不应答预检。
           面板自己的 JS 本来就带着它，所以这条对正常使用零影响。

        返回 None 表示放行，否则返回要回给对方的 (码, 说明)。
        """
        if (self.headers.get('Host') or '').lower() not in _ALLOWED_HOSTS:
            return 403, '只允许本机访问'
        origin = self.headers.get('Origin')
        if origin and origin.lower() not in _ALLOWED_ORIGINS:
            return 403, '拒绝跨站请求'
        if need_json:
            ctype = (self.headers.get('Content-Type') or '').split(';')[0].strip().lower()
            if ctype != 'application/json':
                return 415, '写操作必须用 application/json'
        return None

    def _send(self, obj, code=200, ctype='application/json'):
        body = (obj if isinstance(obj, bytes)
                else json.dumps(obj, ensure_ascii=False).encode('utf-8'))
        self.send_response(code)
        self.send_header('Content-Type', ctype + '; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        bad = self._guard(need_json=False)
        if bad:
            return self._send({'error': bad[1]}, bad[0])
        p = self.path.split('?')[0]
        if p == '/':
            return self._send(PAGE.encode('utf-8'), ctype='text/html')
        if p == '/api/all':
            return self._send({
                'status': collect_status(),
                'processes': collect_processes(),
                'heartbeat': collect_heartbeat(),
                'alerts': collect_alerts(),
                'config': collect_config(),
                'services': SERVICES,
                'recent': collect_recent_reads(),
                'structure': collect_blocks(),
                'time': time.strftime('%H:%M:%S'),
            })
        if p == '/summary':
            # 直接在面板里打开精读，省得切到 Zotero 去找 —— 看完就地评价
            import urllib.parse as _up
            q = _up.parse_qs(self.path.partition('?')[2])
            key = (q.get('key') or [''])[0]
            # 只允许字母数字的 Zotero key，杜绝路径穿越
            if not key or not key.isalnum():
                # 中文不能写在 b'' 字节串里，要显式编码
                return self._send('<h3>无效的文献编号</h3>'.encode('utf-8'),
                                  400, 'text/html')
            fp = os.path.join(ROOT, 'workflow_data', 'library', key, 'summary.html')
            if not os.path.exists(fp):
                return self._send('<h3>这篇还没有精读结果</h3>'.encode('utf-8'),
                                  404, 'text/html')
            with open(fp, 'rb') as f:
                return self._send(f.read(), ctype='text/html')
        if p == '/api/review':
            return self._send(collect_review())
        if p == '/api/search_status':
            with _JOB_LOCK:
                return self._send({
                    'state': _JOB['state'], 'query': _JOB['query'],
                    'log': list(_JOB['log']),
                    'elapsed': int(time.time() - _JOB['started']) if _JOB['started'] else 0,
                    'result': _JOB['result'],
                })
        if p == '/api/logs':
            import urllib.parse
            q = urllib.parse.parse_qs(self.path.partition('?')[2])
            return self._send({'lines': collect_logs(q.get('name', ['zotero_watcher'])[0])})
        return self._send({'error': 'not found'}, 404)

    def do_POST(self):
        bad = self._guard(need_json=True)
        if bad:
            return self._send({'ok': False, 'msg': bad[1]}, bad[0])
        try:
            n = int(self.headers.get('Content-Length', 0))
            payload = json.loads(self.rfile.read(n) or b'{}')
        except Exception:
            return self._send({'ok': False, 'msg': '请求格式错误'}, 400)
        if self.path == '/api/restart':
            ok, msg = action_restart(payload.get('task', ''))
        elif self.path == '/api/selftest':
            ok, msg = action_selftest(payload.get('name', ''))
        elif self.path == '/api/search':
            ok, msg = action_search(payload)
        elif self.path == '/api/collect':
            ok, msg = action_collect(payload)
        elif self.path == '/api/rate':
            ok, msg = action_rate(payload)
        elif self.path == '/api/handover':
            # 生成交接文件：换新对话时让 AI 知道「我们停在哪」
            r = _run([sys.executable, os.path.join(SCRIPT_DIR, '交接.py')],
                     timeout=400, cwd=ROOT)
            ok = r.returncode == 0
            msg = (r.stdout or r.stderr or '').strip().split('\n')[-1][:160] or '已生成'
        elif self.path == '/api/migrate_secrets':
            moved, msg = migrate_secrets_to_keyring()
            ok = bool(moved) or '没有需要迁移' in msg
        elif self.path == '/api/config':
            ok, msg = action_save_config(payload)
        else:
            ok, msg = False, '未知操作'
        return self._send({'ok': ok, 'msg': msg})


PAGE = r"""<!doctype html><html lang="zh"><meta charset="utf-8">
<title>文献平台 · 控制面板</title>
<style>
*{box-sizing:border-box}
body{margin:0;padding:26px;background:#f5f6fa;color:#222;
 font:14.5px/1.7 -apple-system,"Microsoft YaHei",sans-serif}
.wrap{max-width:1000px;margin:0 auto}
h1{font-size:21px;margin:0 0 4px}
.sub{color:#888;font-size:13px;margin-bottom:20px}
.card{background:#fff;border-radius:12px;padding:18px 20px;margin-bottom:16px;
 box-shadow:0 1px 4px rgba(0,0,0,.06)}
.card h2{font-size:15px;margin:0 0 14px;color:#4a5aa8}
.row{display:flex;align-items:center;gap:10px;padding:7px 0;border-bottom:1px solid #f2f2f2}
.row:last-child{border:0}
.dot{width:9px;height:9px;border-radius:50%;flex:none}
.ok{background:#35c15f}.warn{background:#f0ad2e}.fail{background:#e2504a}
.nm{width:120px;flex:none;color:#555}
.msg{color:#777;font-size:13px;flex:1}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid #f2f2f2}
th{color:#999;font-weight:500}
input,select{padding:6px 9px;border:1px solid #dcdfe6;border-radius:6px;font-size:13px;
 font-family:inherit}
input{width:290px}
button{padding:6px 14px;border:0;border-radius:6px;background:#5a6ec0;color:#fff;
 cursor:pointer;font-size:13px;font-family:inherit}
button:hover{background:#4a5aa8}
button.ghost{background:#eef0f7;color:#4a5aa8}
.lbl{width:210px;flex:none;color:#555;font-size:13px}
.hint{color:#aaa;font-size:12px}
.bad{color:#e2504a;font-weight:600}
pre{background:#20232a;color:#c8d0dc;padding:12px;border-radius:8px;font-size:12px;
 max-height:280px;overflow:auto;margin:0;white-space:pre-wrap}
#toast{position:fixed;right:22px;bottom:22px;background:#2f3542;color:#fff;padding:11px 17px;
 border-radius:8px;opacity:0;transition:.25s;font-size:13px;max-width:380px}
#toast.on{opacity:1}
</style>
<div class="wrap">
<h1>文献平台 · 控制面板</h1>
<div class="sub">每 15 秒自动刷新 · 上次刷新 <span id="t">—</span></div>

<div id="alertbox"></div>

<div class="card">
  <h2>找文献</h2>
  <div class="hint" style="margin-bottom:12px">
    会自动拆成多个检索式 + 沿引用网络扩展 + 排除你库里已有的，按「跟你多相关」排序。
    <b>英文关键词效果好很多</b>（材料领域好文献几乎都是英文）。</div>
  <div class="row" style="border:0;padding-bottom:4px">
    <input id="q" style="width:420px" placeholder="例：polyborosiloxane shear stiffening mechanism"
           onkeydown="if(event.key==='Enter')doSearch()">
    <select id="mode">
      <option value="survey">系统调研（求全）</option>
      <option value="problem">解决问题（求准）</option>
    </select>
    <select id="seeds">
      <option value="3">雪球种子 3 篇</option>
      <option value="5">雪球种子 5 篇</option>
      <option value="0">不用雪球（快）</option>
    </select>
    <button onclick="doSearch()" id="btnSearch">开始找</button>
  </div>
  <pre id="searchlog" style="display:none;max-height:150px"></pre>
  <div id="searchsum" class="hint" style="margin-top:8px"></div>
  <div id="results"></div>
  <div id="collectbar" style="display:none;margin-top:12px">
    <button onclick="doCollect(false)">收下选中的（不精读）</button>
    <button onclick="doCollect(true)" style="background:#c0392b">收下并立刻精读</button>
    <span class="hint" style="margin-left:10px">精读会消耗解析与大模型额度</span>
  </div>
</div>

<div class="card">
  <h2>精读评价</h2>
  <div class="hint" style="margin-bottom:10px">
    在 Zotero 给看完的文献打「<b>读完</b>」标签，就会出现在这里。
    评价只存在本平台，<b>不回写 Zotero</b>，你的标签栏永远只有「在读 / 读完」两个。<br>
    目的：把你的判断变成系统能自动算的标准 —— 以后精读质量退化，系统能自己发现。</div>
  <div id="reviewsum" class="hint"></div>
  <div id="review"></div>
  <div style="margin-top:14px;padding-top:12px;border-top:1px solid #f0f0f0">
    <button class="ghost" onclick="genHandover(this)">生成交接文件</button>
    <span class="hint" style="margin-left:8px">
      换新对话前点一下，新对话读 <code>HANDOVER.md</code> 就知道我们停在哪（约 40 秒）</span>
  </div>
</div>

<div class="card"><h2>运行状态</h2><div id="status"></div></div>

<div class="card"><h2>正在运行的进程</h2><div id="procs"></div></div>

<div class="card"><h2>后台服务（卡住了点重启）</h2><div id="svcs"></div></div>

<div class="card"><h2>密钥与模型</h2>
  <div class="hint" style="margin-bottom:10px">
    密钥只显示后 4 位。留空表示不改动，不会清空已有配置。保存前自动备份旧配置。</div>
  <div id="krbar"></div>
  <div id="cfg"></div>
  <div style="margin-top:14px"><button onclick="saveCfg()">保存设置</button></div>
</div>

<div class="card"><h2>项目组成（想改哪块，就在新对话里单独选中那个文件夹）</h2>
  <div class="hint" style="margin-bottom:10px">
    每个文件夹里都有一份说明书（CLAUDE.md），单独选中时 AI 也能看懂那一块。</div>
  <div id="flows"></div>
</div>

<div class="card"><h2>积木（底层能力，上面所有功能由它们搭成）</h2>
  <div class="hint" style="margin-bottom:10px">
    点「自测」可单独检验某块是否正常。只读操作，随便点。</div>
  <div id="blocks"></div>
</div>

<div class="card"><h2>最近处理的文献</h2><div id="recent"></div></div>

<div class="card"><h2>日志</h2>
  <div style="margin-bottom:10px">
    <select id="logname" onchange="loadLog()">
      <option value="zotero_watcher">精读监听</option>
      <option value="watchdog">看门狗</option>
      <option value="auto_sync">自动同步</option>
    </select>
    <button class="ghost" onclick="loadLog()">刷新日志</button>
  </div>
  <pre id="log">加载中…</pre>
</div>
</div>
<div id="toast"></div>
<script>
const $=s=>document.querySelector(s);
function toast(m){const e=$('#toast');e.textContent=m;e.className='on';
  setTimeout(()=>e.className='',3600);}
function esc(s){return String(s).replace(/[<>&]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;'}[c]));}

async function load(){
  let d; try{ d=await (await fetch('/api/all')).json(); }
  catch(e){ toast('面板连不上后台，可能已关闭'); return; }
  $('#t').textContent=d.time;

  const al=d.alerts||[];
  $('#alertbox').innerHTML = al.length
    ? `<div class="card" style="border-left:4px solid #e2504a">
         <h2 style="color:#e2504a">⚠ 需要处理</h2>`
      + al.map(a=>`<div class="row"><span class="msg" style="color:#c0392b">${esc(a.text)}</span></div>`).join('')
      + `</div>`
    : '';

  $('#status').innerHTML=d.status.map(s=>
    `<div class="row"><span class="dot ${s.level}"></span>
     <span class="nm">${esc(s.name)}</span><span class="msg">${esc(s.msg)}</span></div>`).join('');

  const hb=d.heartbeat;
  let hbTxt = hb===null ? '<span class="bad">无心跳文件</span>'
      : hb>300 ? `<span class="bad">${hb} 秒未更新（疑似卡死）</span>`
      : `${hb} 秒前（正常）`;
  $('#procs').innerHTML =
    `<div class="row"><span class="nm">精读监听心跳</span><span class="msg">${hbTxt}</span></div>`
    + (d.processes.length
        ? `<table><tr><th>PID</th><th>脚本</th></tr>` +
          d.processes.map(p=>`<tr><td>${p.pid}</td><td class="${p.dup?'bad':''}">${esc(p.script)}${p.dup?' ⚠重复实例':''}</td></tr>`).join('')
          + `</table>`
        : '<div class="hint" style="padding-top:8px">当前没有相关进程在跑</div>');

  $('#svcs').innerHTML=Object.entries(d.services).map(([k,v])=>
    `<div class="row"><span class="nm" style="width:230px">${esc(v)}</span>
     <span class="msg"><button class="ghost" onclick="restart('${k}')">重启</button></span></div>`).join('');

  const kr=d.config.keyring||{};
  $('#krbar').innerHTML =
    `<div class="hint" style="margin-bottom:8px">密钥存放：${kr.ok?'系统凭据库可用（'+esc(kr.backend)+'）':'<span class="bad">系统凭据库不可用，只能用明文文件</span>'}</div>`
    + (d.config.plain_count>0
        ? `<div class="row" style="background:#fff6f5;border-radius:8px;padding:10px">
             <span class="msg bad">还有 ${d.config.plain_count} 个密钥以明文存在 .env 文件里</span>
             <button onclick="migrate()">迁移到系统凭据库</button></div>`
        : `<div class="row"><span class="msg" style="color:#35c15f">✓ 密钥都已存入系统凭据库，硬盘上没有明文</span></div>`);

  $('#cfg').innerHTML =
    d.config.keys.map(k=>{
      const w = k.where==='系统凭据库' ? '<span style="color:#35c15f">🔒 凭据库</span>'
              : k.where==='.env明文'  ? '<span class="bad">⚠ 明文</span>'
              : k.where==='环境变量'   ? '<span class="hint">环境变量</span>'
              : '<span class="hint">未配置</span>';
      return `<div class="row"><span class="lbl">${esc(k.label)}</span>
       <input id="k_${k.name}" placeholder="${k.set?'已配置 '+esc(k.masked)+'，留空即不改':(k.required?'⚠ 未配置，必填':'未配置（可选）')}">
       <span class="hint" style="margin-left:8px">${w}</span></div>`;}).join('')
  + d.config.sites.map(s=>
      `<div class="row"><span class="lbl">${esc(s.label)}</span>
       <input id="k_${s.name}" value="${esc(s.value||'')}" placeholder="${esc(s.help)}">
       </div>`).join('')
  + d.config.models.map(m=>
      `<div class="row"><span class="lbl">${esc(m.label)} 用的模型</span>
       <select id="k_${m.name}">
         <option value="deepseek-v4-flash"${m.value==='deepseek-v4-flash'?' selected':''}>flash（快·便宜，适合长输出）</option>
         <option value="deepseek-v4-pro"${m.value==='deepseek-v4-pro'?' selected':''}>pro（准·贵3倍，适合短输出）</option>
       </select>
       <span class="hint">默认 ${esc(m.default)}</span></div>`).join('');

  const st = d.structure || {flows:[],blocks:[]};
  $('#flows').innerHTML = `<table><tr><th>文件夹</th><th>是什么</th><th>脚本数</th><th>说明书</th></tr>`
    + st.flows.map(f=>`<tr><td><b>${esc(f.name)}</b></td><td>${esc(f.desc)}</td>
        <td>${f.files}</td><td>${f.doc?'✓':'<span class="bad">缺</span>'}</td></tr>`).join('')
    + `</table>`;

  $('#blocks').innerHTML = `<table><tr><th>积木</th><th>能力</th><th>说明书</th><th></th></tr>`
    + st.blocks.map(b=>`<tr><td><b>${esc(b.name)}</b></td><td>${esc(b.desc)}</td>
        <td>${b.doc?'✓':'<span class="bad">缺</span>'}</td>
        <td>${b.selftest?`<button class="ghost" onclick="selftest('${b.name}')">自测</button>`
             :'<span class="hint">无自测</span>'}</td></tr>`).join('')
    + `</table>`;

  $('#recent').innerHTML = d.recent.length
    ? `<table><tr><th>时间</th><th>文献</th><th>正文字数</th><th>图</th></tr>`
      + d.recent.map(r=>`<tr><td>${esc(r.when)}</td><td>${esc(r.key)}</td>
        <td class="${r.bad?'bad':''}">${r.chars}${r.bad?' ⚠偏短':''}</td>
        <td>${r.figs}</td></tr>`).join('') + `</table>`
    : '<div class="hint">还没有精读记录</div>';
}

async function restart(task){
  toast('正在重启…');
  const r=await (await fetch('/api/restart',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({task})})).json();
  toast(r.msg); setTimeout(load,2500);
}

let REASONS=[];
async function loadReview(){
  let d; try{ d=await (await fetch('/api/review')).json(); }catch(e){ return; }
  REASONS=d.reasons||[];
  const s=d.stats||{};
  let sum=`已评价 ${s.total||0} 篇（好 ${s.good||0} / 差 ${s.bad||0}）`;
  if(d.reading!==undefined) sum+=` · Zotero 里在读 ${d.reading} 篇、读完 ${d.read} 篇`;
  if(s.ready) sum+=' · <b style="color:#35c15f">样本已够，可做自动质量分校准</b>';
  else if((s.total||0)>0) sum+=' · 好/差各满 3 篇后可做自动校准';
  if(s.compare && (s.good||0)+(s.bad||0)>0){
    const c=s.compare;
    sum+=`<br><span class="hint">你说好的 vs 差的：字数 ${c.chars.good}/${c.chars.bad} ·
      图 ${c.figures.good}/${c.figures.bad} · 数值 ${c.numbers.good}/${c.numbers.bad} ·
      章节 ${c.sections.good}/${c.sections.bad}</span>`;
  }
  $('#reviewsum').innerHTML=sum;

  if(d.error){ $('#review').innerHTML=`<div class="row"><span class="msg bad">${esc(d.error)}</span></div>`; return; }
  const p=d.pending||[];
  if(!p.length){
    $('#review').innerHTML='<div class="hint" style="padding-top:8px">'
      +'没有待评价的。去 Zotero 给看完的文献打「读完」标签即可。</div>';
    return;
  }
  $('#review').innerHTML=p.map(x=>{
    const sn=x.snapshot;
    const meta=sn?`${sn.chars} 字 · ${sn.figures} 图 · ${sn.numbers} 处数值 · ${sn.sections} 个章节 · ${sn.mtime}`
                 :'<span class="bad">没有精读结果</span>';
    return `<div class="row" style="display:block;padding:12px 0">
      <div><b>${esc(x.title)}</b></div>
      <div class="hint" style="margin:4px 0 8px">${meta}</div>
      <div style="margin-bottom:8px">
        ${x.has_summary?`<a href="/summary?key=${x.key}" target="_blank"><button class="ghost">打开精读看看</button></a>`:''}
        <button onclick="rate('${x.key}','good',this)">这篇精读得好</button>
        <button onclick="showBad('${x.key}')" style="background:#c0392b">精读得差</button>
      </div>
      <div id="bad_${x.key}" style="display:none;padding:10px;background:#fff6f5;border-radius:8px">
        <div class="hint" style="margin-bottom:6px">差在哪？（可多选，也可以不选直接提交）</div>
        ${REASONS.map(r=>`<label style="margin-right:14px;font-size:13px">
          <input type="checkbox" class="rs_${x.key}" value="${r[0]}"> ${esc(r[1])}</label>`).join('')}
        <div style="margin-top:8px">
          <input id="note_${x.key}" style="width:400px" placeholder="补充说明（可不填）">
          <button onclick="rate('${x.key}','bad',this)">提交</button>
        </div>
      </div></div>`;}).join('');
}

async function genHandover(btn){
  btn.disabled=true; const t=btn.textContent; btn.textContent='生成中（约40秒）…';
  const r=await (await fetch('/api/handover',{method:'POST',
    headers:{'Content-Type':'application/json'},body:'{}'})).json();
  toast(r.msg); btn.disabled=false; btn.textContent=t;
}

function showBad(key){
  const el=document.getElementById('bad_'+key);
  el.style.display = el.style.display==='none' ? 'block' : 'none';
}

async function rate(key, verdict, btn){
  btn.disabled=true;
  const reasons=[...document.querySelectorAll('.rs_'+key+':checked')].map(e=>e.value);
  const noteEl=document.getElementById('note_'+key);
  const title=btn.closest('.row').querySelector('b').textContent;
  const r=await (await fetch('/api/rate',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({key,verdict,reasons,note:noteEl?noteEl.value:'',title})})).json();
  toast(r.msg);
  if(r.ok) loadReview(); else btn.disabled=false;
}

let searchTimer=null;
async function doSearch(){
  const q=$('#q').value.trim();
  if(!q){toast('请输入要找什么');return;}
  $('#btnSearch').disabled=true; $('#btnSearch').textContent='检索中…';
  $('#searchlog').style.display='block'; $('#searchlog').textContent='正在开始…';
  $('#results').innerHTML=''; $('#collectbar').style.display='none'; $('#searchsum').textContent='';
  const r=await (await fetch('/api/search',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({query:q, mode:$('#mode').value,
      seeds:parseInt($('#seeds').value), limit:25, n_queries:5})})).json();
  if(!r.ok){toast(r.msg); $('#btnSearch').disabled=false; $('#btnSearch').textContent='开始找'; return;}
  clearInterval(searchTimer);
  searchTimer=setInterval(pollSearch,2000);
}

async function pollSearch(){
  const s=await (await fetch('/api/search_status')).json();
  $('#searchlog').textContent=(s.log||[]).join('\n')+`\n（已用 ${s.elapsed} 秒）`;
  $('#searchlog').scrollTop=$('#searchlog').scrollHeight;
  if(s.state==='running') return;
  clearInterval(searchTimer);
  $('#btnSearch').disabled=false; $('#btnSearch').textContent='开始找';
  if(s.state==='error'){toast('检索失败，详情见上面日志');return;}
  renderResults(s.result);
}

function renderResults(res){
  if(!res||!res.rows||!res.rows.length){$('#results').innerHTML='<div class="hint">没找到结果，换个说法试试</div>';return;}
  const newOnes=res.rows.filter(r=>r.status==='new');
  $('#searchsum').innerHTML=
    `检索式 ${res.queries.length} 个 · 候选池 ${res.total_pool} 篇`
    + (res.snow_added?` （其中雪球贡献 <b>${res.snow_added}</b> 篇关键词搜不到的）`:'')
    + (res.filtered?` · 滤掉 ${res.filtered} 篇跨方向的`:'')
    + ` · <b>新文献 ${newOnes.length} 篇</b>，库里已有 ${res.rows.length-newOnes.length} 篇`;
  $('#results').innerHTML=
    `<table><tr><th style="width:28px"></th><th>文献</th><th style="width:150px">相关度</th>
     <th style="width:60px">被引</th></tr>`
    + res.rows.map(r=>{
        const have=r.status!=='new';
        const bar='█'.repeat(Math.round((r.relevance||0)*10));
        const src={backward:'引用源头',forward:'跟进工作'}[r.from]||'';
        return `<tr style="${have?'opacity:.45':''}">
          <td>${have?'':`<input type="checkbox" class="pick" data-doi="${esc(r.doi)}">`}</td>
          <td><b>${esc(r.title.slice(0,88))}</b><br>
            <span class="hint">${r.year||'????'} · ${esc(r.venue)}
            ${r.is_oa?' · 开放获取':''}${src?' · '+src:''}
            ${have?' · <b>库里已有</b>':''}
            ${r.nearest&&!have?'<br>↳ 与你库中《'+esc(r.nearest.slice(0,54))+'》最接近':''}</span></td>
          <td>${r.relevance} ${bar}<br><span class="hint">贴题${r.topic_sim} 近库${r.lib_sim}</span></td>
          <td>${r.citations}</td></tr>`;}).join('')
    + `</table>`;
  $('#collectbar').style.display=newOnes.length?'block':'none';
}

async function doCollect(deep){
  const dois=[...document.querySelectorAll('.pick:checked')].map(e=>e.dataset.doi).filter(Boolean);
  if(!dois.length){toast('先勾选要收的文献');return;}
  if(deep && !confirm(`确认收下 ${dois.length} 篇并立刻精读？\n精读会消耗解析与大模型额度。`))return;
  toast('正在收下…');
  const r=await (await fetch('/api/collect',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({dois,deep})})).json();
  toast(r.msg);
  if(r.ok) document.querySelectorAll('.pick:checked').forEach(e=>{
    e.checked=false; e.closest('tr').style.opacity=.45;});
}

async function migrate(){
  toast('正在迁移密钥到系统凭据库…');
  const r=await (await fetch('/api/migrate_secrets',{method:'POST',
    headers:{'Content-Type':'application/json'},body:'{}'})).json();
  toast(r.msg); load();
}

async function selftest(name){
  toast(name+' 自测中…');
  const r=await (await fetch('/api/selftest',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({name})})).json();
  toast((r.ok?'✓ ':'✗ ')+r.msg);
}

async function saveCfg(){
  const body={};
  document.querySelectorAll('[id^=k_]').forEach(el=>{
    if(el.value && el.value.trim()) body[el.id.slice(2)]=el.value.trim();});
  const r=await (await fetch('/api/config',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})).json();
  toast(r.msg);
  document.querySelectorAll('input[id^=k_]').forEach(el=>el.value='');
  load();
}

async function loadLog(){
  const n=$('#logname').value;
  const r=await (await fetch('/api/logs?name='+encodeURIComponent(n))).json();
  $('#log').textContent=r.lines.join('\n');
  $('#log').scrollTop=$('#log').scrollHeight;
}

load(); loadLog(); loadReview(); setInterval(load,15000);
</script></html>"""


def main():
    srv = HTTPServer((HOST, PORT), Handler)
    url = f'http://{HOST}:{PORT}/'
    print(f'控制面板已启动：{url}（按 Ctrl+C 关闭）')
    if not flag('--no-browser'):
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print('\n面板已关闭')


if __name__ == '__main__':
    main()
