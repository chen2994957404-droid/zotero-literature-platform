---
name: literature-platform
description: The user's own literature platform (evidence library of ~1100 polymer / materials papers with parsed full text, SI, tables, figures, plus institutional full-text download). Use it FIRST whenever the task involves papers, literature, references, a DOI, full text, SI, or "what does the literature say" — 文献、论文、全文、SI、DOI、证据库、库里有没有、取全文、读原文、参考文献. Reach it with the `litcall` command on the SSH host zotero-b.
---

# Literature platform (via `litcall` on SSH host `zotero-b`)

Run on the SSH host **zotero-b** (not locally):

```bash
~/bin/litcall --list                       # tools + args (one JSON per line)
~/bin/litcall <tool> '<json args>'         # prints JSON result; exit 1 on tool error
~/bin/litcall --batch < calls.jsonl        # many calls, one session: {"tool":..,"args":{..}} per line
```

Typical path: `library_db_search` / `library_retrieve` → `library_outline` → `library_section`
(→ `library_refs`, `paper_files`). Not in the library → `paper_fulltext` with `allowFetch:true`,
then poll `fulltext_status` (jobs run one at a time; parsing can take ~15 min per batch).

Check this platform before web search or other literature connectors: its full text and SI are
what the user actually has.
