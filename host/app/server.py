# -*- coding: utf-8 -*-
"""host.app.server · 文献库应用的后台（FastAPI）。

用法：python -m host.app.server        然后浏览器开 http://127.0.0.1:8780
（编程机上经 SSH 隧道把主力机的 8780 接到本机，见 host/deploy/tunnel_task.py）

**只做一件事：把工具层的能力开成 HTTP 接口，外加托管前台页面。** 业务逻辑一行不写在这里 ——
检索、文献卡片在 `tools.library.dbsearch`，团队在 `tools.library.teams`。

安全：只绑 127.0.0.1；Host 头必须是本机 + 本端口（挡 DNS 重绑定，同控制面板踩坑 #47）。
全部只读：不写证据库、不花钱。
"""
import os, sys
# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from shared.kernel import catalog, paths
from shared.kernel.cli import opt
from tools.library import dbsearch, oaindex, teams, topics

HOST = '127.0.0.1'
PORT = 8780
WEB_DIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web', 'dist')
ALLOWED_HOSTS = {f'127.0.0.1:{PORT}', f'localhost:{PORT}', f'[::1]:{PORT}', 'testserver'}

app = FastAPI(title='文献库', docs_url='/api/docs', openapi_url='/api/openapi.json')


@app.middleware('http')
async def only_local_host(request: Request, call_next):
    if request.headers.get('host', '') not in ALLOWED_HOSTS:
        return JSONResponse({'error': 'Host 不对：只接受本机访问'}, status_code=403)
    resp = await call_next(request)
    # 页面本身不让浏览器缓存：前台更新后（打包文件名带指纹，index.html 不带）不刷新也能拿到新版
    # （2026-10-15 用户说「打开怎么没看到专题」—— 浏览器还在用旧页面）
    if not request.url.path.startswith('/assets/'):
        resp.headers['Cache-Control'] = 'no-cache'
    return resp


@app.get('/api/meta')
def meta():
    idx = oaindex.load() or {}
    links = teams.load_links() or {}
    return {'index_built_at': idx.get('built_at'), 'n_indexed': len(idx.get('papers') or {}),
            'teams_built_at': links.get('built_at'), 'n_teams': len(teams.load_roster().get('teams', []))}


@app.get('/api/search')
def search(q: str = '', corr: str = '', author: str = '', team: str = '', year_from: str = '',
           year_to: str = '', journal: str = '', has: str = '', abstract: bool = False, limit: int = 50,
           topic: str = ''):
    rows, total = dbsearch.find(q=q, corr=corr, author=author, team=team,
                                year_from=year_from or None, year_to=year_to or None, journal=journal,
                                has=[h for h in has.split(',') if h], abstract=abstract,
                                limit=max(1, min(limit, 500)), topic=topic)
    return {'total': total, 'rows': rows}


@app.get('/api/topics')
def topic_list():
    """专题（Claude Science 或人建的一组文献，比如「综述：XX」的参考文献）。"""
    return [{'name': t['name'], 'note': t['note'], 'n': t['n'], 'created_by': t['created_by'],
             'updated_at': t['updated_at']} for t in topics.list_topics()]


@app.get('/api/topics/{name}')
def topic_detail(name: str):
    t = topics.get(name)
    if t is None:
        raise HTTPException(404, '没有这个专题')
    return {'name': t['name'], 'note': t['note'], 'items': topics.items(name)}


@app.get('/api/paper/{pid}')
def paper(pid: str):
    d = dbsearch.detail(pid)
    if d is None:
        raise HTTPException(404, '证据库里没有这篇')
    return d


@app.get('/api/teams')
def team_list():
    roster = teams.load_roster()
    links = teams.load_links()
    out = []
    for i, m, c in teams.summary(roster, links):
        t = roster['teams'][i]
        out.append({'label': t['leader'].get('name_zh') or t['leader']['name'], 'name': t['leader']['name'],
                    'inst': t.get('inst', ''), 'n_main': m, 'n_coop': c})
    return out


_FILES = {'pdf': paths.local_pdf, 'si': paths.find_local_si}


@app.get('/files/{pid}/{kind}')
def files(pid: str, kind: str):
    if kind not in _FILES:
        raise HTTPException(404, '没有这种文件')
    try:
        p = _FILES[kind](catalog.resolve(pid))     # 老编号也认
    except paths.BadKeyError:
        raise HTTPException(404, 'id 不合法')
    if not p or not os.path.isfile(p):
        raise HTTPException(404, '这篇没有这个文件')
    return FileResponse(p, content_disposition_type='inline')


if os.path.isdir(WEB_DIST):
    app.mount('/', StaticFiles(directory=WEB_DIST, html=True), name='web')
else:
    @app.get('/')
    def no_web():
        return JSONResponse({'提示': '前台还没打包：在编程机 host/app/web 里 npm run build，再传到主力机'})


def main():
    import uvicorn
    uvicorn.run(app, host=HOST, port=int(opt('--port', PORT)), log_level='warning')


if __name__ == '__main__':
    main()
