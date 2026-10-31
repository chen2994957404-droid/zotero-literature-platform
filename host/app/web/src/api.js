// 后台接口（host/app/server.py）。前台只通过这里取数据。
async function get(url) {
  const r = await fetch(url)
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText)
  return r.json()
}

export const api = {
  meta: () => get('/api/meta'),
  teams: () => get('/api/teams'),
  topics: () => get('/api/topics'),
  paper: (id) => get('/api/paper/' + encodeURIComponent(id)),
  search(f) {
    const p = new URLSearchParams()
    for (const k of ['q', 'corr', 'author', 'team', 'topic', 'year_from', 'year_to', 'journal']) if (f[k]) p.set(k, f[k])
    if (f.has.length) p.set('has', f.has.join(','))
    if (f.abstract) p.set('abstract', 'true')
    p.set('limit', f.limit || 100)
    return get('/api/search?' + p)
  },
  file: (id, kind) => `/files/${encodeURIComponent(id)}/${kind}`,
  importDois: (body) => post('/api/import', body),
  importStatus: () => get('/api/import/status'),
}

async function post(url, body) {
  const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText)
  return r.json()
}
