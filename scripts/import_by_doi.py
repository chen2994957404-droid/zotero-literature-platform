# -*- coding: utf-8 -*-
"""
按 DOI 批量导入 Zotero（Web API 写入，本地 API 只读见踩坑#8）。
流程：DOI -> Crossref 取元数据 -> 组装 Zotero item -> POST /users/<id>/items
可选打标签（如「待精读」）触发平台自动精读。
用法：python scripts/import_by_doi.py
"""
import io, json, os, sys, time, urllib.request, urllib.error

API_KEY = os.environ.get("ZOTERO_API_KEY", "")
UA = "n8n-literature-workflow/1.0 (mailto:research@example.com)"
BASE = "https://api.zotero.org"

# 要导入的文献：DOI -> 标签
TARGETS = [
    ("10.1016/j.polymer.2024.127377", ["待精读", "PBS机理"]),
    ("10.1016/j.polymer.2023.126005", ["待精读", "PBS机理"]),
    ("10.1021/acs.iecr.6b03823",      ["待精读", "PBS机理"]),
    ("10.1002/mame.202100360",        ["待精读", "PBS机理"]),
    ("10.1038/s41467-025-64000-1",    ["待精读", "PBS机理"]),
    ("10.1007/s10965-025-04419-8",    ["待精读", "PBS机理"]),
    ("10.3390/polym17030392",         ["待精读", "PBS共混相容性"]),
]


def _get(url, headers=None, timeout=45):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def get_user_id():
    uid = os.environ.get("ZOTERO_USER_ID", "").strip()
    if uid:
        return uid
    # 用 key 反查
    d = _get(BASE + "/keys/" + API_KEY, {"User-Agent": UA})
    return str(d.get("userID"))


def crossref(doi):
    d = _get("https://api.crossref.org/works/" + urllib.parse.quote(doi), {"User-Agent": UA})
    return d["message"]


def to_zotero_item(m):
    creators = []
    for a in m.get("author", [])[:40]:
        creators.append({
            "creatorType": "author",
            "firstName": a.get("given", ""),
            "lastName": a.get("family", a.get("name", "")),
        })
    date = ""
    for f in ("published-print", "published-online", "issued"):
        p = m.get(f, {}).get("date-parts", [[]])[0]
        if p:
            date = "-".join(str(x) for x in p)
            break
    title = (m.get("title") or [""])[0]
    return {
        "itemType": "journalArticle",
        "title": title,
        "creators": creators,
        "abstractNote": (m.get("abstract") or "").replace("<jats:p>", "").replace("</jats:p>", "").strip(),
        "publicationTitle": (m.get("container-title") or [""])[0],
        "volume": m.get("volume", ""),
        "issue": m.get("issue", ""),
        "pages": m.get("page", ""),
        "date": date,
        "DOI": m.get("DOI", ""),
        "url": m.get("URL", ""),
        "libraryCatalog": "Crossref",
        "tags": [],
    }


def post_items(uid, items):
    url = "%s/users/%s/items" % (BASE, uid)
    body = json.dumps(items, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Zotero-API-Key": API_KEY,
        "Zotero-API-Version": "3",
        "Content-Type": "application/json",
        "User-Agent": UA,
    })
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    if not API_KEY:
        print("NO_API_KEY"); return
    import urllib.parse  # noqa
    uid = get_user_id()
    print("USER_ID", uid)

    items, meta = [], []
    for doi, tags in TARGETS:
        try:
            m = crossref(doi)
            it = to_zotero_item(m)
            it["tags"] = [{"tag": t} for t in tags]
            items.append(it)
            meta.append((doi, it["title"]))
            print("OK  ", doi, "|", it["title"][:80])
        except Exception as e:
            print("FAIL", doi, e)
        time.sleep(0.4)

    if not items:
        print("NOTHING"); return

    res = post_items(uid, items)
    io.open(os.path.join(os.path.dirname(__file__), "..", "workflow_data", "_import_result.json"),
            "w", encoding="utf-8").write(json.dumps(res, ensure_ascii=False, indent=1))
    print("SUCCESS", len(res.get("success", {})), "FAILED", len(res.get("failed", {})))
    for k, v in res.get("successful", {}).items():
        print("  ->", v.get("key"), v.get("data", {}).get("title", "")[:70])
    for k, v in res.get("failed", {}).items():
        print("  XX", v)


if __name__ == "__main__":
    import urllib.parse
    main()
