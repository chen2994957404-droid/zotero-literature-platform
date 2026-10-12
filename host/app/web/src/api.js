// 后台接口（host/app/server.py）。前台只通过这里取数据。
async function get(url) {
  const r = await fetch(url)
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText)
  return r.json()
}

export const api = {
  meta: () => get('/api/meta'),
  teams: () => get('/api/teams'),
  paper: (id) => get('/api/paper/' + encodeURIComponent(id)),
  search(f) {
    const p = new URLSearchParams()
    for (const k of ['q', 'corr', 'author', 'team', 'year_from', 'year_to', 'journal']) if (f[k]) p.set(k, f[k])
    if (f.has.length) p.set('has', f.has.join(','))
    if (f.abstract) p.set('abstract', 'true')
    p.set('limit', f.limit || 100)
    return get('/api/search?' + p)
  },
  file: (id, kind) => `/files/${encodeURIComponent(id)}/${kind}`,
  deepread: (id) => get('/api/deepread/' + encodeURIComponent(id)),
  async startDeepread(id) {
    // 会花钱的动作：带上自定义头，后台只认本页面发来的
    const r = await fetch('/api/deepread/' + encodeURIComponent(id), { method: 'POST', headers: { 'X-Literature-App': '1' } })
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText)
    return r.json()
  },
}
