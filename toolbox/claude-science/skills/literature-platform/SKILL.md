---
name: literature-platform
description: The user's own literature platform (evidence library of ~1100 polymer / materials papers with parsed full text, SI, tables, figures, plus institutional full-text download, plus read-only SciFinder / Reaxys searching through the user's logged-in browser). Use it FIRST whenever the task involves papers, literature, references, a DOI, full text, SI, or "what does the literature say" — 文献、论文、全文、SI、DOI、证据库、库里有没有、取全文、读原文、参考文献、SciFinder、Reaxys、专利、CAS. Reach it with the `litcall` command on the SSH host zotero-b.
---

# Literature platform (via `litcall` on SSH host `zotero-b`)

Run on the SSH host **zotero-b** (not locally):

```bash
~/bin/litcall --version                    # litcall + server version (expect server 0.4.x)
~/bin/litcall --list                       # tools + args (one JSON per line)
~/bin/litcall <tool> '<json args>'         # prints JSON result; exit 1 on tool error
~/bin/litcall --batch < calls.jsonl        # many calls, one session: {"tool":..,"args":{..}} per line
```

Typical path: `paper_status` / `library_db_search` / `library_retrieve` → `library_outline` → `library_section`
(→ `paper_files`, `figure_image`). Reference lists, data extraction and web search are yours to do (OpenAlex etc.). Not in the library → `paper_fulltext` with `allowFetch:true`,
then poll `fulltext_status` with `wait_s`.

What to expect (server 0.3):
- **Tiers.** A paper is readable seconds after its PDF lands (`tier: "text"`: local text extraction,
  sections and paragraphs addressable, no table structure). MineRU upgrades it in the background to
  `tier: "structured"` (tables, figure images). Tables as data: `library_section` with
  `sectionId: "t1", format: "csv"` (or `"json"`) — needs `structured`.
- **Status codes.** Every fetch result has `code` (`OK`, `CAPTCHA_REQUIRED`, `NOT_SUBSCRIBED`, `NOT_FOUND`,
  `NO_PDF_LINK`, `PARSE_PENDING`, `PARSE_FAILED`, `NETWORK_ERROR`, `NOT_FETCHED`) plus `retryable`, `stage`, `route`.
  Branch on `code`, not on the Chinese `why`.
- **CAPTCHA.** The server defers the rest of that publisher, keeps going with others, and pops a reminder on
  the user's desktop. Ask the user to click it in the "取全文用的浏览器", then call `fulltext_retry`.
- **Citing.** Section ids (`s8`, `s8.p2`) are per-version: they can shift when a paper goes text → structured.
  Record the section `title` (and ideally a short `quote`) with every citation; pass them back to `library_section`
  (`{"sectionId":"s8","title":"2.2 Mechanical Properties"}` or `{"quote":"…"}`) and it finds the current place,
  returning `remapped_from`. Every outline / section carries `rev` (tier + text hash) so you can see a change.
- **Figures.** `figure_image` (`{"itemKey":…, "fig":"Figure 2"}`) returns a small JPEG as base64 — no file transfer.
  `image_kind: "full"` = whole figure cropped from the PDF; `"panel"` = only one sub-panel (fallback).
- **Search.** `library_db_search` ignores dash variants and also matches by words; `library_retrieve` drops
  heading-only fragments and takes `per_paper` (e.g. 1) to spread hits across papers.
- **Size.** Any result over 50 KB comes back as `{"spilled": "<path>"}` — read that file (`cat`) instead.
  Long sections: `offset` / `next_offset`. In `--batch`, lines past ~48 KB total are spilled to `~/.cache/litcall/`.
- Invalid DOIs are rejected immediately (`NOT_FOUND` in `rejected`), they never enter the queue.

Check this platform before web search or other literature connectors: its full text and SI are
what the user actually has.

## SciFinder / Reaxys (server 0.4): `chemdb_search`, `chemdb_page`

The user's school subscribes to both; you can't log in, so these drive the browser on the user's main machine
(the user logs in there once) and return the **text of one results page**. Read-only: no export, no detail pages.

```bash
~/bin/litcall chemdb_search '{"db":"scifinder","query":"boron siloxane self-healing"}'
~/bin/litcall chemdb_search '{"db":"reaxys","query":"polyborosiloxane self-healing elastomer"}'
~/bin/litcall chemdb_page   '{"db":"scifinder","page":2}'     # next page of the last search in that db
```
`kind`: `references` (journal articles + patents, default) / `substances` / `reactions`. `maxChars` ≤ 45000.
Result: `code` (`OK`, `LOGIN_REQUIRED`, `NO_RESULTS`, `NO_SEARCH`, `NAVIGATE_FAILED`, `TIMEOUT`), `count`, `page`, `text`,
`quota` (`used_today`, `daily_limit`). Reaxys also returns `preview`: how it split your query into sub-queries, with counts.

**Human pace, enforced by the server**: ≥30 s between calls (the server waits for you; a call takes ~1 min),
and a small daily cap per database (search and page both count). CAS terms forbid scripting what is meant to be
manual; the user knowingly accepted light, human-paced use. So plan the query first; don't trial-and-error.
`LOGIN_REQUIRED` → ask the user to log in in the "取全文用的浏览器" on the main machine, then retry.

How the two behave (observed 2026-10-08, same query `polyborosiloxane self-healing elastomer`):

| | SciFinder | Reaxys |
|---|---|---|
| query parsing | ANDs every word ("Query Interpretation" in the text) | recognises substances as structures and splits the sentence into sub-queries, strictest first |
| hits | 26 (18 journal + 8 patents) | 134 documents |
| a results page shows | title, authors, journal/year, partial abstract, **filter facets with counts** (document type, year, language, patent office, patent status alive/dead, CPC/IPC codes, concepts), CAS Newton AI summary | title, authors, journal/year, **DOI**, times cited, hit snippets, AI summary, facet names |
| strengths | patents (incl. Chinese), CAS-indexed concepts, patent legal status | experimental property data per substance, reaction conditions |

Query tips for this user's field:
- **Go broad, filter later.** `polyborosiloxane self-healing elastomer` → 26 in SciFinder; `boron siloxane self-healing` → 317.
  Many papers say B–O–Si, borate / boronic ester cross-linked PDMS, borosiloxane, "silly putty", not "polyborosiloxane".
- Both are built for small molecules: polymer property numbers (tensile strength, healing efficiency) are mostly
  not indexed. Use them to find papers / patents and monomer or cross-linker chemistry; get the numbers from the
  full text via `paper_fulltext` → `library_section`.
- SciFinder lists usually lack DOIs: match by title (OpenAlex) before `paper_fulltext`. Reaxys lists include DOIs.
- Patents: full text is not fetched by `paper_fulltext`; use the patent number with a public patent source.
- For bulk screening, the user can also export a SciFinder result set to Excel (Result Details template, all fields:
  abstract, concepts, substances, Claim 1, patent status, family) and hand you the file — no quota used.
