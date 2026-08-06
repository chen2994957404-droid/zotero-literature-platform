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

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, ROOT)
sys.path.insert(0, SCRIPT_DIR)  # health_check 同在本文件夹

from modules.config import (get_key, set_keys, get_model, mask,
                            MODEL_SETTINGS, ENV_FILE)

PORT = int(os.environ.get('PANEL_PORT', '8777'))
HOST = '127.0.0.1'          # 只监听本机，外部访问不到

KEY_NAMES = [
    ('DEEPSEEK_KEY',    'DeepSeek（精读/抽取/问答）', True),
    ('ZOTERO_API_KEY',  'Zotero（回写附件与标签）',   True),
    ('MINERU_TOKEN',    'MineRU（PDF 解析）',         True),
    ('SILICONFLOW_KEY', '硅基流动（图表数字化，可空）', False),
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
    try:
        out = subprocess.run(['powershell', '-NoProfile', '-Command', ps],
                             capture_output=True, text=True, timeout=25).stdout.strip()
        data = json.loads(out) if out else []
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


def collect_heartbeat():
    """watcher 心跳距今多久（秒）。None 表示没有心跳文件。"""
    hb = os.path.join(ROOT, 'workflow_data', 'logs', 'watcher_heartbeat.txt')
    try:
        return int(time.time() - int(open(hb, encoding='utf-8').read().strip()))
    except Exception:
        return None


def collect_config():
    """密钥（脱敏）与模型设置。**绝不返回密钥明文**。"""
    return {
        'keys': [{'name': n, 'label': lb, 'required': rq,
                  'set': bool(get_key(n)), 'masked': mask(get_key(n))}
                 for n, lb, rq in KEY_NAMES],
        'models': [{'name': n, 'label': MODEL_SETTINGS[n][0],
                    'value': get_model(n), 'default': MODEL_SETTINGS[n][1]}
                   for n in MODEL_SETTINGS],
        'env_file': ENV_FILE,
    }


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
        r = subprocess.run([sys.executable, p], capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=120,
                           cwd=ROOT)
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
        r = subprocess.run(['powershell', '-NoProfile', '-Command',
                            f'Restart-ScheduledTask -TaskName {task_name}'],
                           capture_output=True, text=True, timeout=40)
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

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass    # 不往 stdout 刷日志

    def _send(self, obj, code=200, ctype='application/json'):
        body = (obj if isinstance(obj, bytes)
                else json.dumps(obj, ensure_ascii=False).encode('utf-8'))
        self.send_response(code)
        self.send_header('Content-Type', ctype + '; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = self.path.split('?')[0]
        if p == '/':
            return self._send(PAGE.encode('utf-8'), ctype='text/html')
        if p == '/api/all':
            return self._send({
                'status': collect_status(),
                'processes': collect_processes(),
                'heartbeat': collect_heartbeat(),
                'config': collect_config(),
                'services': SERVICES,
                'recent': collect_recent_reads(),
                'structure': collect_blocks(),
                'time': time.strftime('%H:%M:%S'),
            })
        if p == '/api/logs':
            import urllib.parse
            q = urllib.parse.parse_qs(self.path.partition('?')[2])
            return self._send({'lines': collect_logs(q.get('name', ['zotero_watcher'])[0])})
        return self._send({'error': 'not found'}, 404)

    def do_POST(self):
        try:
            n = int(self.headers.get('Content-Length', 0))
            payload = json.loads(self.rfile.read(n) or b'{}')
        except Exception:
            return self._send({'ok': False, 'msg': '请求格式错误'}, 400)
        if self.path == '/api/restart':
            ok, msg = action_restart(payload.get('task', ''))
        elif self.path == '/api/selftest':
            ok, msg = action_selftest(payload.get('name', ''))
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

<div class="card"><h2>运行状态</h2><div id="status"></div></div>

<div class="card"><h2>正在运行的进程</h2><div id="procs"></div></div>

<div class="card"><h2>后台服务（卡住了点重启）</h2><div id="svcs"></div></div>

<div class="card"><h2>密钥与模型</h2>
  <div class="hint" style="margin-bottom:10px">
    密钥只显示后 4 位。留空表示不改动，不会清空已有配置。保存前自动备份旧配置。</div>
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

  $('#cfg').innerHTML =
    d.config.keys.map(k=>
      `<div class="row"><span class="lbl">${esc(k.label)}</span>
       <input id="k_${k.name}" placeholder="${k.set?'已配置 '+esc(k.masked)+'，留空即不改':(k.required?'⚠ 未配置，必填':'未配置（可选）')}">
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

load(); loadLog(); setInterval(load,15000);
</script></html>"""


def main():
    srv = HTTPServer((HOST, PORT), Handler)
    url = f'http://{HOST}:{PORT}/'
    print(f'控制面板已启动：{url}（按 Ctrl+C 关闭）')
    if '--no-browser' not in sys.argv:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print('\n面板已关闭')


if __name__ == '__main__':
    main()
