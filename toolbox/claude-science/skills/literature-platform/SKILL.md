---
name: literature-platform
description: The user's own literature platform (evidence library of ~1100 polymer / materials papers with parsed full text, SI, tables, figures, plus institutional full-text download). Use it FIRST whenever the task involves papers, literature, references, a DOI, full text, SI, or "what does the literature say" — 文献、论文、全文、SI、DOI、证据库、库里有没有、取全文、读原文、参考文献. Reach it with the `litcall` command on the SSH host zotero-b.
---

# Literature platform (via `litcall` on SSH host `zotero-b`)

Run on the SSH host **zotero-b** (not locally):

```bash
~/bin/litcall --version                    # litcall + server version (expect server 0.3.x)
~/bin/litcall --list                       # tools + args (one JSON per line)
~/bin/litcall <tool> '<json args>'         # prints JSON result; exit 1 on tool error
~/bin/litcall --batch < calls.jsonl        # many calls, one session: {"tool":..,"args":{..}} per line
```

Typical path: `paper_status` / `library_db_search` / `library_retrieve` → `library_outline` → `library_section`
(→ `library_refs`, `paper_files`). Not in the library → `paper_fulltext` with `allowFetch:true`,
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
- **Size.** Any result over 50 KB comes back as `{"spilled": "<path>"}` — read that file (`cat`) instead.
  Long sections: `offset` / `next_offset`. In `--batch`, lines past ~48 KB total are spilled to `~/.cache/litcall/`.
- Invalid DOIs are rejected immediately (`NOT_FOUND` in `rejected`), they never enter the queue.

Check this platform before web search or other literature connectors: its full text and SI are
what the user actually has.
