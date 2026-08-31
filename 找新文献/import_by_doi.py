# -*- coding: utf-8 -*-
"""按 DOI 导入文献到 Zotero（走 Web API 写入；本地 API 只读，见踩坑 #8）。

流程：DOI → Crossref 取元数据 → 组装 Zotero item → POST /users/<id>/items

**注意这是有副作用的操作**（会改用户的 Zotero 库并同步到所有设备），
所以默认不打任何标签 —— 是否触发精读由用户单独决定（精读要花钱）。

用法:
  python 找新文献/import_by_doi.py 10.1021/acsami.2c04994
  python 找新文献/import_by_doi.py <DOI1> <DOI2> ... --tag 待处理
  参数: --tag <标签>  可重复；打「待处理」会触发自动精读
"""
import os, sys, json, time, urllib.request, urllib.parse, urllib.error

# 【标准开头】强制 UTF-8 输出（项目已装成 Python 包，import 无需再塞 sys.path）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from shared.kernel import role
from shared.kernel.cli import opts, positionals, flag
from shared.kernel.config import get_key, get_site
from shared.adapters import zotero_client as zotero

UA = 'zotero-literature-platform/1.0'


def _get(url, headers=None, timeout=45):
    req = urllib.request.Request(url, headers=headers or {'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


def crossref(doi):
    """按 DOI 取元数据。DOI 不存在会抛 HTTPError 404。"""
    return _get('https://api.crossref.org/works/' + urllib.parse.quote(doi),
                {'User-Agent': UA})['message']


def to_zotero_item(m, tags=None):
    creators = [{'creatorType': 'author',
                 'firstName': a.get('given', ''),
                 'lastName': a.get('family', a.get('name', ''))}
                for a in m.get('author', [])[:40]]
    date = ''
    for f in ('published-print', 'published-online', 'issued'):
        p = (m.get(f) or {}).get('date-parts', [[]])[0]
        if p:
            date = '-'.join(str(x) for x in p)
            break
    abstract = (m.get('abstract') or '')
    for junk in ('<jats:p>', '</jats:p>', '<jats:title>', '</jats:title>'):
        abstract = abstract.replace(junk, '')
    return {
        'itemType': 'journalArticle',
        'title': (m.get('title') or [''])[0],
        'creators': creators,
        'abstractNote': abstract.strip(),
        'publicationTitle': (m.get('container-title') or [''])[0],
        'volume': m.get('volume', ''), 'issue': m.get('issue', ''),
        'pages': m.get('page', ''), 'date': date,
        'DOI': m.get('DOI', ''), 'url': m.get('URL', ''),
        'libraryCatalog': 'Crossref',
        'tags': [{'tag': t} for t in (tags or [])],
    }


def post_items(items, forced=False):
    """新建条目走适配层（鉴权、用户 id、机器角色守卫都在那里）。"""
    return zotero.create_items(items, action='按 DOI 导入文献', force=forced)


def import_dois(dois, tags=None, verbose=True, forced=False):
    """导入一批 DOI。返回 {'ok':[(doi,title,key)], 'failed':[(doi,原因)]}。"""
    if not get_key('ZOTERO_API_KEY'):
        raise RuntimeError('缺少 ZOTERO_API_KEY，请在控制面板填写')

    items, meta, failed = [], [], []
    for doi in dois:
        doi = (doi or '').strip().replace('https://doi.org/', '')
        if not doi:
            continue
        try:
            it = to_zotero_item(crossref(doi), tags)
            if not it['title']:
                raise ValueError('Crossref 没有返回标题')
            items.append(it)
            meta.append((doi, it['title']))
            if verbose:
                print(f'  取到元数据: {it["title"][:66]}')
        except urllib.error.HTTPError as e:
            failed.append((doi, 'Crossref 查不到这个 DOI' if e.code == 404 else f'HTTP {e.code}'))
        except Exception as e:
            failed.append((doi, f'{type(e).__name__}: {str(e)[:60]}'))
        time.sleep(0.35)          # 对 Crossref 友好，避免被限流

    ok = []
    if items:
        res = post_items(items, forced=forced)
        for idx, v in (res.get('successful') or {}).items():
            i = int(idx)
            ok.append((meta[i][0], meta[i][1], v.get('key')))
        for idx, v in (res.get('failed') or {}).items():
            i = int(idx)
            failed.append((meta[i][0], str(v)[:80]))
    return {'ok': ok, 'failed': failed}


def main():
    # 机器角色守卫：这件事只允许在运行端（主力机）做，见 docs/两台机器的分工.md
    role.require_prod('按 DOI 导入 Zotero', force=flag('--force'))
    args = positionals()
    tags = opts('--tag')
    if not args:
        print(__doc__)
        return
    print(f'准备导入 {len(args)} 篇' + (f'，标签：{tags}' if tags else '（不打标签）'))
    r = import_dois(args, tags)
    print(f'\n成功 {len(r["ok"])} 篇：')
    for doi, title, key in r['ok']:
        print(f'  ✓ [{key}] {title[:66]}')
    if r['failed']:
        print(f'\n失败 {len(r["failed"])} 篇：')
        for doi, why in r['failed']:
            print(f'  ✗ {doi} — {why}')
    if tags and any(t in ('待处理', '待精读') for t in tags):
        print('\n已打「待处理」标签，精读服务会在 1 分钟内自动开始。')


if __name__ == '__main__':
    main()
