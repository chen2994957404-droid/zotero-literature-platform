# -*- coding: utf-8 -*-
"""控制面板 · 平台的仪表盘与开关（工作流件，不含任何业务逻辑）

设计原则（服从架构准则）：
  本文件**一行业务逻辑都不实现**。状态取自 health_check 的检查函数，配置取自
  shared.kernel.config，进程取自系统查询。它只是「现有模块的视图 + 遥控器」。
  任何新功能都应先做成模块，再由面板调用 —— 绝不在面板里写实现。

能做什么（都是可逆、零风险的事）：
  - 看：各服务是否正常、哪些进程在跑、数据资产统计、最近日志
  - 改：API 密钥、本机设置（写入凭据库 / .env，自动备份旧版）
  - 动：重启 watcher / Ollama 等后台服务

刻意**不做**的（不可逆或要花钱，继续走人工确认）：
  删除数据、全库重抽、改 Zotero 库、触发批量精读。

安全：只绑定 127.0.0.1（外部机器访问不到）；密钥默认脱敏显示。

用法: python host/panel/app.py     然后浏览器开 http://127.0.0.1:8777
      双击「控制面板.bat」会自动开好并打开浏览器。
"""
import os, sys, json, time, subprocess, threading, webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass
from shared.kernel import paths, role
from shared.kernel.paths import ROOT as _ROOT

from shared.kernel.cli import flag

ROOT = _ROOT

from shared.kernel.config import (SITE_SETTINGS, get_key, set_keys, mask,
                            ENV_FILE, get_site,
                            keyring_status, key_location,
                            migrate_secrets_to_keyring, env_shadow, clear_env_key)
from shared.kernel.subproc import run as _run, powershell   # 统一走静默子进程调用

PORT = int(os.environ.get('PANEL_PORT', '8777'))
_STARTED = time.strftime('%m-%d %H:%M:%S')   # 本面板进程的启动时刻
HOST = '127.0.0.1'          # 只监听本机，外部访问不到

KEY_NAMES = [
    ('MINERU_TOKEN',    'MineRU（PDF 解析）',         True),
    # OpenAlex 2026-02 起按量计费：无 key 只有 $0.10/天，免费 key 有 $1/天（10 倍）。
    ('OPENALEX_KEY',    'OpenAlex（作者 / 摘要索引，建议填）', False),
]

# 面板可重启的后台服务：任务计划名 → 显示名
SERVICES = {
    'ZoteroLiteratureWatcher': '看门狗（守文献库应用 / MCP 服务 / 取全文浏览器）',   # 任务名是历史遗留
    'OllamaService':           '本地 Ollama（向量化）',
}


# ───────────────────────── 数据采集（全部只读） ─────────────────────────

def collect_status():
    """服务健康状态。直接复用 health_check 的检查函数，不重写判断逻辑。"""
    from host.doctor import health_check as H
    checks = [
        ('配置密钥', H.c_config),
        ('Ollama 服务', H.c_ollama), ('数据资产', H.c_data),
        ('后台任务', H.c_services),
    ]
    def _run(item):
        name, fn = item
        try:
            status, msg = fn()
        except Exception as e:
            status, msg = H.FAIL, f'{type(e).__name__}: {e}'
        level = {H.OK: 'ok', H.WARN: 'warn'}.get(status, 'fail')
        return {'name': name, 'level': level, 'msg': msg}
    # Zotero / Ollama 没开时各要等 2 秒才被拒绝，串着就是 4 秒；并行只等最慢的一个
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=len(checks)) as pool:
        return list(pool.map(_run, checks))


def collect_all():
    """面板一页要的全部数据。**各项并行取**（2026-09-17）。

    每 15 秒刷新一次，原来是十一项串着取：Zotero 探一次 2 秒、Ollama 探一次 2 秒、
    警报里再探一次 Zotero 2 秒、PowerShell 查进程 1 秒…… 服务没开的机器上一次刷新 7 秒，
    页面大半时间在转圈。这些项互不依赖，并行之后取决于最慢的一项（≈2 秒）。
    """
    from concurrent.futures import ThreadPoolExecutor
    parts = {
        'status': collect_status, 'processes': collect_processes,
        'progress': collect_progress,
        'alerts': collect_alerts, 'version': collect_version,
        'config': collect_config,
        'jobs': collect_jobs, 'structure': collect_blocks,
    }

    def _safe(fn):
        try:
            return fn()
        except Exception as e:
            return {'error': f'{type(e).__name__}: {e}'}
    with ThreadPoolExecutor(max_workers=len(parts)) as pool:
        got = dict(zip(parts, pool.map(_safe, parts.values())))
    got['services'] = SERVICES
    got['time'] = time.strftime('%H:%M:%S')
    return got


def collect_processes():
    """本平台相关的 python 进程。用 CIM 查，比 wmic 可靠。"""
    ps = ("Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | "
          "Where-Object {$_.CommandLine -match 'watchdog|ingest|vectorize|getpdf|host[.]mcp|host[.]app|panel'} | "
          "Select-Object ProcessId,CreationDate,CommandLine | ConvertTo-Json -Compress")
    # 走 subproc 模块：面板每 15 秒刷新一次，裸调 powershell 会不停闪窗口（踩坑 #31）
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
    p = paths.log('zotero_watcher')
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
    # 常驻服务 / 批量作业卡住了（2026-09-16 加：取件卡半小时、Edge 死三小时都没人知道）
    try:
        from shared.kernel import heartbeat
        for o in heartbeat.overview():
            if o['state'] in ('stuck', 'dead'):
                alerts.append({'level': 'fail', 'text': f"「{JOB_LABELS.get(o['name'], o['name'])}」{o['note']}"})
    except Exception:
        pass
    return alerts


JOB_LABELS = {'ingest': '落地流水线', 'getpdf': '取全文'}


def collect_progress():
    """每个常驻服务 / 批量作业最近一次进展 —— 「卡住了要有人知道」（逻辑在 heartbeat.overview）。"""
    try:
        from shared.kernel import heartbeat
        return [dict(o, label=JOB_LABELS.get(o['name'], o['name'])) for o in heartbeat.overview()]
    except Exception:
        return []


def collect_version():
    """面板进程正在跑的是哪一版代码。

    **为什么需要它**：面板是常驻进程，`git pull` 不会让它重新加载代码。
    更新完代码后如果没重启面板，你看到的还是旧界面 ——
    这个坑在 2026-08-26 真实发生过一次（新加的「机器角色」设置项不显示，
    因为旧面板进程占着 8777 端口，新进程绑不上直接死了）。

    把版本显示在页面上，这种「我看到的是不是最新的」就一眼可辨。
    """
    from shared.kernel import role
    out = {'role': role.current(), 'role_label': role.label(),
           'role_set': role.is_configured(), 'commit': '', 'dirty': None,
           'started': _STARTED}
    try:
        r = _run(['git', 'log', '-1', '--format=%h %s'], timeout=20, cwd=ROOT)
        out['commit'] = (r.stdout or '').strip()[:80]
        r2 = _run(['git', 'status', '--porcelain'], timeout=20, cwd=ROOT)
        out['dirty'] = bool((r2.stdout or '').strip())
    except Exception:
        pass
    return out


def action_clear_env_key(payload):
    """清掉某把密钥的用户级环境变量（它正盖着凭据库里的新值）。"""
    name = (payload or {}).get('name', '')
    if name not in [n for n, _l, _r in KEY_NAMES]:
        return False, '不认识这个密钥名'
    return clear_env_key(name)


def action_check_keys(_payload=None):
    """当场验一验密钥到底**能不能用**（不花钱，只查余额/有效性接口）。

    为什么面板必须有这一条（2026-08-28 真事）：面板此前只显示密钥「存在哪」
    （🔒 凭据库 / ⚠ 明文），不显示「有没有用」。于是 DeepSeek 密钥已经 401 了，
    用户看着满屏绿色的「已存入系统凭据库」，**看不出任何问题** ——
    直到一批重抽全军覆没才发现。

    踩坑 #66 已经把体检升级成「查有效性」，却漏了用户天天看的这一屏。
    密钥只有本机交互式会话读得到，所以这个按钮只能在本机点，也只该在本机点。
    """
    try:
        from shared.adapters.pdf_parse import check_token as _mineru
    except Exception as e:
        return False, f'适配层加载失败：{e}'
    lines, all_ok = [], True
    for name, fn_ in (('MineRU（PDF 解析）', _mineru),):
        try:
            ok, msg = fn_()
        except Exception as e:
            ok, msg = False, str(e)[:140]
        all_ok = all_ok and (ok is not False)
        lines.append(('✅ ' if ok else '❌ ') + name + '：' + str(msg)[:160])
    if not all_ok:
        lines.append('失效的那把请在上面重填并保存。')
    return all_ok, '\n'.join(lines)


def collect_config():
    """密钥（脱敏）与本机设置。**绝不返回密钥明文**。"""
    kr_ok, kr_backend = keyring_status()
    keys = [{'name': n, 'label': lb, 'required': rq,
             'set': bool(get_key(n)), 'masked': mask(get_key(n)),
             'where': key_location(n), 'shadow': env_shadow(n)}
            for n, lb, rq in KEY_NAMES]
    return {
        'keys': keys,
        'plain_count': sum(1 for k in keys if k['where'] == '.env明文'),
        'keyring': {'ok': kr_ok, 'backend': kr_backend},
        # options 由后端给：前端写死过一次选项，结果 shared.kernel.role 加了第三档
        # 面板却选不到，而且保存时会把 test 悄悄退回 dev（同踩坑 #58 一族）。
        'sites': [{'name': n, 'label': lb, 'value': get_site(n), 'help': hp,
                   'options': SITE_OPTIONS.get(n, [])}
                  for n, lb, _d, hp in SITE_SETTINGS],
        'env_file': ENV_FILE,
    }


# 哪些本机设置是「选一个」而不是「填一段」。**选项从 shared.kernel.role 取，不在前端写死**。
SITE_OPTIONS = {
    'ROLE': [
        {'value': role.DEV,  'text': '编程端 dev —— 不许跑常驻服务 / 全库作业 / 花钱的批量'},
        {'value': role.PROD, 'text': '运行端 prod —— 主力机，允许全部操作'},
        {'value': role.TEST, 'text': '编程端·测试档 test —— 允许跑，产物只在本机'},
    ],
}


def collect_blocks():
    """模块与工作流一览。说明取自各文件夹的 CLAUDE.md 首段，不另写一份。

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
    for ring, name, d in paths.block_dirs():
        f = os.path.join(d, '__init__.py')
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
    skip = paths.NON_WORKFLOW_DIRS
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
    """跑某块模块的自测。只读、可重复，是安全操作。"""
    d = paths.block_dir(name) if name and '/' not in name and '..' not in name else None
    p = os.path.join(d, 'selftest.py') if d else ''
    if not p or not os.path.exists(p):
        return False, '没有这个模块或它没有自测'
    try:
        r = _run([sys.executable, p], timeout=120, cwd=ROOT)
        tail = (r.stdout or r.stderr or '').strip().split('\n')[-1][:120]
        return r.returncode == 0, f'{name}：{tail}'
    except subprocess.TimeoutExpired:
        return False, f'{name}：自测超时（超过 120 秒）'
    except Exception as e:
        return False, f'{name}：{e}'


def collect_logs(name='watchdog', lines=40):
    safe = {'watchdog', 'ingest', 'getpdf', 'mcp_http'}      # 白名单，防路径穿越
    if name not in safe:
        return ['(不允许的日志名)']
    p = paths.log(name)
    if not os.path.exists(p):
        return ['(日志文件还不存在)']
    try:
        with open(p, encoding='utf-8', errors='replace') as f:
            return [l.rstrip() for l in f.readlines()[-lines:]]
    except Exception as e:
        return [f'(读取失败: {e})']


def collect_jobs(recent=8):
    """从任务状态库读**真进度**：哪一步在跑、谁失败了、谁该重跑。

    在此之前，面板只能看日志尾巴 —— 日志回答不了「现在做到第几篇」，
    更回答不了「上次是哪一步失败的」。状态库（shared/kernel/jobs）建好之后这些都是一句查询。

    刻意只读不写：面板是观察窗，不是执行者。
    """
    try:
        from shared.kernel import jobs
    except Exception as e:
        return {'ok': False, 'msg': f'状态库读不到：{e}'}

    zh = {'parse': '解析正文', 'parse_si': '解析 SI', 'outline': '骨架', 'vectorize': '向量化'}
    try:
        summary = jobs.summary()
        steps = [{'step': k, 'label': zh.get(k, k),
                  'ok': v.get(jobs.OK, 0), 'failed': v.get(jobs.FAILED, 0),
                  'running': v.get(jobs.RUNNING, 0)}
                 for k, v in sorted(summary.items(), key=lambda kv: list(zh).index(kv[0])) if k in zh]   # 精读 / 抽取那些旧步骤的历史记录不再显示
        # 卡了超过 30 分钟还挂着 running 的，多半是进程被杀/断电留下的
        stuck = [{'key': r['item_key'], 'step': zh.get(r['step'], r['step'])}
                 for r in jobs.running(older_than=1800) if r['step'] in zh]
        rows = [r for r in jobs.recent(200) if r['step'] in zh][:recent]
        recent_rows = [{
            'key': r['item_key'], 'step': zh.get(r['step'], r['step']),
            'status': r['status'], 'model': r['model'] or '',
            'when': time.strftime('%m-%d %H:%M', time.localtime(r['started_at'])),
            'secs': round((r['finished_at'] or r['started_at']) - r['started_at']),
            'error': (r['error'] or '')[:120]} for r in rows]
        return {'ok': True, 'steps': steps, 'stuck': stuck, 'recent': recent_rows}
    except Exception as e:
        return {'ok': False, 'msg': f'读状态库出错：{e}'}


# ───────────────────────── 动作（可逆，低风险） ─────────────────────────

# 任务 → 它真正干活的那个进程持有的锁名（`host.ingest.proc_lock`）。
# 重启任务时要连这个进程一起停，否则新配置进不去（见 action_restart）。
# 2026-09-17 起看门狗管三个进程：精读监听、落地流水线常驻、每日作业 —— 重启任务要把它们全停掉，
# 锁名收在 host.watcher.watchdog.CHILD_LOCKS（部署脚本也用它），别在这里另抄一份
_TASK_CHILDREN = {'ZoteroLiteratureWatcher': True}

def action_restart(task_name):
    """重启一个自启任务。

    ⚠ **不要用 `Restart-ScheduledTask`** —— Windows PowerShell 5.1 里根本没有这个
    cmdlet（2026-08-28 在主力机上实测：面板的「重启」按钮一直报
    「无法将 Restart-ScheduledTask 项识别为 cmdlet」，也就是说这个按钮从来没生效过）。
    只有 `Stop-ScheduledTask` / `Start-ScheduledTask` 是真存在的。

    停一下再起：Stop 对没在跑的任务会报错，所以吞掉它的失败，只认 Start 的结果。
    """
    if task_name not in SERVICES:
        return False, '未知服务'
    try:
        _run(['powershell', '-NoProfile', '-NonInteractive', '-Command',
              f'Stop-ScheduledTask -TaskName {task_name} -ErrorAction SilentlyContinue'],
             timeout=40)
        # ⚠ 计划任务启动的是**看门狗**，watcher 是看门狗 spawn 出去的独立进程 ——
        #   停任务不会停 watcher。于是「重启」之后 watcher 还揣着启动那一刻的配置。
        #   2026-08-28 就栽在这儿：密钥换新了、任务也重启了，watcher 照用旧密钥。
        #   所以这里要按锁文件把真正干活的那个进程也停掉，让它带着新配置重新起。
        if _TASK_CHILDREN.get(task_name):
            from host.watcher.watchdog import kill_children
            kill_children()
        r = _run(['powershell', '-NoProfile', '-NonInteractive', '-Command',
                  f'Start-ScheduledTask -TaskName {task_name}'], timeout=40)
        if r.returncode == 0:
            return True, f'{SERVICES[task_name]} 已重启'
        return False, (r.stderr or '重启失败')[:200]
    except Exception as e:
        return False, str(e)[:200]


def action_save_config(payload):
    """保存密钥 / 本机设置。空值自动跳过（不会误清空），旧 .env 自动备份。

    ⚠ 白名单里**必须包含 SITE_SETTINGS**。原来只写了密钥和模型，于是
    「本机设置」在页面上显示得出来、也改得动，**一保存就被静默丢弃** ——
    用户把机器角色从 dev 改成 prod、点保存、刷新后又变回 dev，
    而且没有任何错误提示（2026-08-26 主力机实测）。
    「界面看着能改，其实存不进去」是最难自查的一类 bug，所以在这里钉死。
    """
    allowed = ({n for n, _, _ in KEY_NAMES}
               | {s[0] for s in SITE_SETTINGS})     # 漏掉过一次
    updates = {k: v for k, v in (payload or {}).items() if k in allowed}
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
        if p in ('/', '/settings', '/logs'):
            # 同一份页面，前端按路径只显示日常卡片或管理卡片
            return self._send(PAGE.encode('utf-8'), ctype='text/html')
        if p == '/api/all':
            return self._send(collect_all())
        if p == '/api/logs':
            import urllib.parse
            q = urllib.parse.parse_qs(self.path.partition('?')[2])
            return self._send({'lines': collect_logs(q.get('name', ['watchdog'])[0])})
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
        elif self.path == '/api/handover':
            # 生成交接文件：换新对话时让 AI 知道「我们停在哪」
            r = _run([sys.executable,
                      os.path.join(ROOT, 'host', 'codegen', 'handover.py')],
                     timeout=400, cwd=ROOT)
            ok = r.returncode == 0
            msg = (r.stdout or r.stderr or '').strip().split('\n')[-1][:160] or '已生成'
        elif self.path == '/api/clear_env_key':
            ok, msg = action_clear_env_key(payload)
        elif self.path == '/api/check_keys':
            ok, msg = action_check_keys(payload)
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
.card[data-page]{display:none}
body[data-page="daily"] .card[data-page="daily"],body[data-page="settings"] .card[data-page="settings"],body[data-page="logs"] .card[data-page="logs"]{display:block}
</style>
<div class="wrap">
<h1 id="title">文献平台 · 控制面板</h1>
<div class="sub" id="nav"></div>
<div class="sub">每 15 秒自动刷新 · 上次刷新 <span id="t">—</span></div>
<div class="sub" id="ver">—</div>

<div id="alertbox"></div>

<div class="card" data-page="logs"><h2>运行状态</h2><div id="status"></div></div>

<div class="card" data-page="logs"><h2>正在运行的进程</h2><div id="procs"></div></div>

<div class="card" data-page="logs"><h2>后台服务（卡住了点重启）</h2><div id="svcs"></div></div>

<div class="card" data-page="settings"><h2>密钥 · 本机设置</h2>
  <div class="hint" style="margin-bottom:10px">
    密钥只显示后 4 位。留空表示不改动，不会清空已有配置。保存前自动备份旧配置。</div>
  <div id="krbar"></div>
  <div id="cfg"></div>
  <div style="margin-top:14px"><button onclick="saveCfg()">保存设置</button></div>
</div>

<div class="card" data-page="settings"><h2>项目组成（想改哪块，就在新对话里单独选中那个文件夹）</h2>
  <div class="hint" style="margin-bottom:10px">
    每个文件夹里都有一份说明书（CLAUDE.md），单独选中时 AI 也能看懂那一块。</div>
  <div id="flows"></div>
</div>

<div class="card" data-page="settings"><h2>模块（底层能力，上面所有功能由它们搭成）</h2>
  <div class="hint" style="margin-bottom:10px">
    点「自测」可单独检验某块是否正常。只读操作，随便点。</div>
  <div id="blocks"></div>
</div>

<div class="card" data-page="daily"><h2>落地处理进度（解析 → 骨架 → 向量化）</h2><div id="jobs"></div></div>
<div class="card" data-page="daily"><h2>交接</h2>
  <button class="ghost" onclick="genHandover(this)">生成交接文件</button>
  <span class="hint" style="margin-left:8px">
    换新对话前点一下，新对话读 <code>HANDOVER.md</code> 就知道我们停在哪（约 40 秒）</span>
</div>

<div class="card" data-page="logs"><h2>日志</h2>
  <div style="margin-bottom:10px">
    <select id="logname" onchange="loadLog()">
      <option value="watchdog">看门狗</option>
      <option value="ingest">落地流水线</option>
      <option value="getpdf">取全文</option>
      <option value="mcp_http">MCP 服务</option>
    </select>
    <button class="ghost" onclick="loadLog()">刷新日志</button>
  </div>
  <pre id="log">加载中…</pre>
</div>
</div>
<div id="toast"></div>
<script>
const $=s=>document.querySelector(s);
// 三个页面、一个后台：`/` 日常（找文献 / 评价 / 进度），`/settings` 设置（密钥 / 本机设置 / 项目组成 / 模块），
// `/logs` 运行与日志（运行状态 / 进程 / 后台服务 / 日志）。
// 拆开的原因：用户只会主动点日常那几样，管理项堆在一起太杂（2026-09-17）。
const PATH = location.pathname.replace(/\/+$/,'');
const PAGE_KIND = PATH === '/settings' ? 'settings' : PATH === '/logs' ? 'logs' : 'daily';
document.body.dataset.page = PAGE_KIND;
const TITLES = {daily:'文献平台 · 控制面板', settings:'文献平台 · 设置与密钥', logs:'文献平台 · 运行与日志'};
$('#title').textContent = TITLES[PAGE_KIND];
$('#nav').innerHTML = [['daily','日常面板','/'],['settings','设置与密钥','/settings'],['logs','运行与日志','/logs']]
  .map(([k,n,u]) => k === PAGE_KIND ? `<b>${n}</b>` : `<a href="${u}">${n}</a>`).join(' · ')
  + ' <span class="hint">（launch/ 里各有一个同名 .bat）</span>';
function toast(m){const e=$('#toast');e.textContent=m;e.className='on';
  setTimeout(()=>e.className='',3600);}
function esc(s){return String(s).replace(/[<>&]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;'}[c]));}

// ⚠ 配置区只在首次和保存后重画。**它每 15 秒被自动刷新重画一次时，
// 用户正在改的下拉/输入框会被悄悄改回已存的值** —— 选了 test，还没点保存
// 就被刷回 dev，看起来像「改不动」。别把它挪回自动刷新里（踩坑 #63）。
let cfgReady=false;

async function load(force){
  let d; try{ d=await (await fetch('/api/all')).json(); }
  catch(e){ toast('面板连不上后台，可能已关闭'); return; }
  $('#t').textContent=d.time;

  const al=d.alerts||[];
  const v = d.version || {};
  // 角色名由后端给（shared.kernel.role.label），前端写死过一次就漏了 test 档
  const roleColor = v.role === 'prod' ? '#35c15f' : v.role === 'test' ? '#4a9de0' : '#e6a23c';
  const roleTag = `<b style="color:${roleColor}">${esc(v.role_label || v.role)}</b>`
      + (v.role_set ? '' : ' <span class="bad">·未设置，按最安全的 dev 处理</span>');
  $('#ver').innerHTML =
      `本机角色 ${roleTag}`
    + ` · 代码 <code>${esc(v.commit || '未知')}</code>`
    + (v.dirty ? ' <span class="bad">·工作区有未提交改动</span>' : '')
    + ` · 面板进程启动于 ${esc(v.started || '?')}`
    + ` <span class="hint">（更新代码后必须重启面板，否则你看到的还是旧界面）</span>`;

  $('#alertbox').innerHTML = al.length
    ? `<div class="card" style="border-left:4px solid #e2504a">
         <h2 style="color:#e2504a">⚠ 需要处理</h2>`
      + al.map(a=>`<div class="row"><span class="msg" style="color:#c0392b">${esc(a.text)}</span></div>`).join('')
      + `</div>`
    : '';

  $('#status').innerHTML=d.status.map(s=>
    `<div class="row"><span class="dot ${s.level}"></span>
     <span class="nm">${esc(s.name)}</span><span class="msg">${esc(s.msg)}</span></div>`).join('');

  const stateTxt = {running:'在跑', stuck:'<b>卡住</b>', dead:'<b>没报活</b>', done:'做完', idle:'空闲'};
  const progRows = (d.progress||[]).map(o=>
    `<div class="row"><span class="dot ${o.state==='running'||o.state==='done'?'ok':'fail'}"></span>
     <span class="nm">${esc(o.label)}</span><span class="msg ${o.state==='stuck'||o.state==='dead'?'bad':''}">${stateTxt[o.state]||o.state} · ${esc(o.note)}</span></div>`).join('');
  $('#procs').innerHTML = progRows
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
        : `<div class="row"><span class="msg" style="color:#35c15f">✓ 密钥都已存入系统凭据库，硬盘上没有明文</span></div>`)
    + `<div class="row"><span class="msg hint">「存进去了」不等于「还能用」—— 密钥会被吊销、会过期</span>
         <button onclick="checkKeys()">测一测密钥（不花钱）</button></div>
       <div id="keychk" class="hint" style="white-space:pre-line;padding:2px 0 0"></div>`;

  if(force || !cfgReady){
  $('#cfg').innerHTML =
      `<h3 style="margin:4px 0 6px;font-size:15px">密钥</h3>`
  + d.config.keys.map(k=>{
      const w = k.where==='系统凭据库' ? '<span style="color:#35c15f">🔒 凭据库</span>'
              : k.where==='.env明文'  ? '<span class="bad">⚠ 明文</span>'
              : k.where==='环境变量'   ? '<span class="bad">⚠ 环境变量</span>'
              : '<span class="hint">未配置</span>';
      const sh = k.shadow;
      // 环境变量优先级最高：它一旦有值，你在这里填的新密钥**永远用不上**。
      // 这条必须喊出来 —— 2026-08-28 就是它让三把新密钥全程失灵，而面板一片正常。
      const warn = sh ? `<div class="row" style="background:#fff6f5;border-radius:8px;padding:8px 10px">
          <span class="msg bad">⚠ 这把密钥正由**环境变量**提供（末位 ${esc(sh.env_tail)}）${
            sh.differs ? '，而凭据库里另有一把（末位 '+esc(sh.stored_tail)+'）—— <b>你在这里填的新密钥被它盖住了</b>'
                       : '；在这里填新值也不会生效'}</span>
          <button onclick="clearEnv('${k.name}')">清除这个环境变量</button></div>` : '';
      return `<div class="row"><span class="lbl">${esc(k.label)}</span>
       <input id="k_${k.name}" placeholder="${k.set?'已配置 '+esc(k.masked)+'，留空即不改':(k.required?'⚠ 未配置，必填':'未配置（可选）')}">
       <span class="hint" style="margin-left:8px">${w}</span></div>` + warn;}).join('')
  + `<h3 style="margin:18px 0 6px;font-size:15px">本机设置<span class="hint" style="font-weight:normal">（每台机器各填各的，不进版本库）</span></h3>`
  + d.config.sites.map(s=> (s.options && s.options.length)
      ? `<div class="row"><span class="lbl">${esc(s.label)}</span>
         <select id="k_${s.name}">${s.options.map(o=>
           `<option value="${esc(o.value)}"${s.value===o.value?` selected`:``}>${esc(o.text)}</option>`).join('')}
         </select></div>`
      : `<div class="row"><span class="lbl">${esc(s.label)}</span>
         <input id="k_${s.name}" value="${esc(s.value||'')}" placeholder="${esc(s.help)}">
         </div>`).join('');
  cfgReady=true; }

  const st = d.structure || {flows:[],blocks:[]};
  $('#flows').innerHTML = `<table><tr><th>文件夹</th><th>是什么</th><th>脚本数</th><th>说明书</th></tr>`
    + st.flows.map(f=>`<tr><td><b>${esc(f.name)}</b></td><td>${esc(f.desc)}</td>
        <td>${f.files}</td><td>${f.doc?'✓':'<span class="bad">缺</span>'}</td></tr>`).join('')
    + `</table>`;

  $('#blocks').innerHTML = `<table><tr><th>模块</th><th>能力</th><th>说明书</th><th></th></tr>`
    + st.blocks.map(b=>`<tr><td><b>${esc(b.name)}</b></td><td>${esc(b.desc)}</td>
        <td>${b.doc?'✓':'<span class="bad">缺</span>'}</td>
        <td>${b.selftest?`<button class="ghost" onclick="selftest('${b.name}')">自测</button>`
             :'<span class="hint">无自测</span>'}</td></tr>`).join('')
    + `</table>`;

  const jb = d.jobs || {ok:false, msg:'没有数据'};
  if(!jb.ok){
    $('#jobs').innerHTML = `<div class="hint">${esc(jb.msg||'读不到状态库')}</div>`;
  } else if(!(jb.steps||[]).length){
    $('#jobs').innerHTML = '<div class="hint">状态库还是空的 —— 有文献落地解析后就有了</div>';
  } else {
    const stuck = (jb.stuck||[]).length
      ? `<div class="bad">⚠ 卡住超过 30 分钟：`
        + jb.stuck.map(x=>`${esc(x.key)}（${esc(x.step)}）`).join('、')
        + `（多半是进程被杀或断电，落地流水线会自己重试）</div>` : '';
    $('#jobs').innerHTML = stuck
      + `<table><tr><th>步骤</th><th>成功</th><th>失败</th><th>在跑</th></tr>`
      + jb.steps.map(s=>`<tr><td>${esc(s.label)}</td><td>${s.ok}</td>
          <td class="${s.failed?'bad':''}">${s.failed||''}</td>
          <td>${s.running||''}</td></tr>`).join('')
      + `</table>`
      + `<table style="margin-top:10px"><tr><th>时间</th><th>文献</th><th>步骤</th><th>结果</th><th>用时</th></tr>`
      + (jb.recent||[]).map(r=>`<tr><td>${esc(r.when)}</td><td>${esc(r.key)}</td>
          <td>${esc(r.step)}</td>
          <td class="${r.status==='failed'?'bad':''}">${r.status==='ok'?'成功'
             :r.status==='failed'?'失败':'在跑'}${r.error?`<br><span class="hint">${esc(r.error)}</span>`:''}</td>
          <td>${r.secs?r.secs+'s':''}</td></tr>`).join('')
      + `</table>`;
  }

}


async function restart(task){
  toast('正在重启…');
  const r=await (await fetch('/api/restart',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({task})})).json();
  toast(r.msg); setTimeout(load,2500);
}

async function genHandover(btn){
  btn.disabled=true; const t=btn.textContent; btn.textContent='生成中（约40秒）…';
  const r=await (await fetch('/api/handover',{method:'POST',
    headers:{'Content-Type':'application/json'},body:'{}'})).json();
  toast(r.msg); btn.disabled=false; btn.textContent=t;
}

async function clearEnv(name){
  if(!confirm(name+'：删掉用户级环境变量里的这把旧密钥？\n凭据库里的新密钥会重新生效，服务需重启。'))return;
  const r=await (await fetch('/api/clear_env_key',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({name})})).json();
  toast(r.msg); load(true);
}

async function checkKeys(){
  $('#keychk').textContent='正在验（几秒）…';
  const r=await (await fetch('/api/check_keys',{method:'POST',
    headers:{'Content-Type':'application/json'},body:'{}'})).json();
  $('#keychk').innerHTML=esc(r.msg||'').replace(/\n/g,'<br>');
  toast(r.ok?'密钥有效':'有密钥失效，看下面');
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
  load(true);          // 保存后才重画配置区，让页面显示真正存进去的值
}

async function loadLog(){
  const n=$('#logname').value;
  const r=await (await fetch('/api/logs?name='+encodeURIComponent(n))).json();
  $('#log').textContent=r.lines.join('\n');
  $('#log').scrollTop=$('#log').scrollHeight;
}

load(); loadLog(); setInterval(load,15000);
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
