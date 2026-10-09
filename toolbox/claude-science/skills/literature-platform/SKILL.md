---
name: literature-platform
description: The user's own literature platform (evidence library of ~1100 polymer / materials papers with parsed full text, SI, tables, figures, plus institutional full-text download, plus read-only SciFinder / Reaxys / PoLyInfo / CNKI (中国知网) / CCDC / JCR / Scopus look-ups through the user's logged-in browser). Use it FIRST whenever the task involves papers, literature, references, a DOI, full text, SI, or "what does the literature say" — 文献、论文、全文、SI、DOI、证据库、库里有没有、取全文、读原文、参考文献、SciFinder、Reaxys、专利、CAS、PoLyInfo、聚合物性质、Tg、密度、知网、学位论文、硕博论文、中国专利、晶体结构、CCDC、CSD、影响因子、JCR、分区、Scopus、被引. Reach it with the `litcall` command on the SSH host zotero-b.
---

# Literature platform (via `litcall` on SSH host `zotero-b`)

Run on the SSH host **zotero-b** (not locally):

```bash
~/bin/litcall --version                    # litcall + server version (expect server 0.10.x)
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

## SciFinder / Reaxys (server 0.7): `chemdb_status`, `chemdb_search`, `chemdb_page`

The user's school subscribes to both; you can't log in, so these drive the browser on the user's main machine
(the user logs in there once) and return **one results page as structured fields**. Read-only: no export, no detail pages.

```bash
~/bin/litcall chemdb_status '{}'      # free: quota left, reset time, last searches, login state of the tabs, export folder
~/bin/litcall chemdb_search '{"db":"scifinder","query":"boron siloxane self-healing","sort":"cited","filters":{"Document Type":["Journal"],"yearFrom":2018}}'
~/bin/litcall chemdb_search '{"db":"reaxys","query":"polyborosiloxane self-healing elastomer","sort":"cited"}'
~/bin/litcall chemdb_page   '{"db":"reaxys","page":2}'     # page n of the last search in that db
```

Result fields: `code` (`OK`, `LOGIN_REQUIRED`, `NO_RESULTS`, `NO_SEARCH`, `NAVIGATE_FAILED`, `TIMEOUT`), `complete`, `warnings`,
`count`, `page`, `page_size`, `pages`, `query_interpretation` (what the database actually ran), `ai_summary`, `facets`,
`cached`, `quota`, and `items[]`:
`rank, type (journal|review|patent|conference paper|…), title, authors (≤8, n_authors if more), source, year, doi,
cited (Reaxys) / citing (SciFinder), snippet (≤400 chars), index_terms (Reaxys), in_library, id, tier`; for patents also
`patent_no, assignee, office, status (SciFinder: alive/dead), family_ranks / family_members (Reaxys)`.
- SciFinder lists carry no DOI: the server matches titles on Crossref (`doi_source: crossref_title_match`,
  `doi_match_score`; `doi_uncertain: true` below 0.9), asking with the journal and preferring the candidate whose volume
  matches; if journal/volume still disagree it leaves `doi` empty and gives `doi_candidate` + `doi_rejected_because`
  (e.g. Angewandte German edition vs International Edition).
  Titles Crossref can't match (or when it's rate-limited) are retried on OpenAlex (`doi_source: openalex_title_match`);
  anything still empty says why in `doi_lookup` (`not_found` / `failed` / `skipped`). `in_library` / `tier` tell you what `paper_fulltext` would add.
- A full page is often > 50 KB (Reaxys ~100 items/page, SciFinder ~80): you get `{"spilled": path}` — read that file.
- `raw: true` adds the whole page text (debugging only).

Options:
- `sort`: `relevance` (default) / `cited` / `date` (newest first). Both databases.
- `filters` (**SciFinder only**): `{facet name: [values]}` exactly as they appear in `facets` (e.g. `"Document Type": ["Journal"]`,
  `"Patent Status": ["Alive"]`, `"Language": ["English"]`), plus `yearFrom` / `yearTo`. Only values shown on the page
  (top 5 per facet) can be ticked; misses go to `warnings`. Reaxys returns only facet names (`facets.available`).
- `mode: "original"` (SciFinder): when `query_modified` is true, search the original string instead of SciFinder's rewrite.
- Reaxys splits a sentence into sub-queries, strictest first; `preview` lists them with counts and the server opens the
  first `documents` one. If that set is too narrow or too wide, rephrase.
- `kind: reactions` returns only `raw` text for now.

**Async (0.7).** A real search takes 40–150 s. Each call waits up to `wait_s` (default 25, ≤50); if the search
isn't done you get `{"code": "PENDING", "job_id": …}` — poll `chemdb_result {"job_id": …, "wait_s": 45}` (free).
Repeating the identical `chemdb_search` while it runs also just waits on the same job (no second charge).
Only one SciFinder/Reaxys search runs at a time.

**Human pace, enforced by the server**: ≥30 s between site calls (the server waits; a call takes ~1–2 min), and a daily cap
per database (search and page both count; `chemdb_status` shows what's left). **The same search/page on the same day is
served from cache (`cached: true`) and costs nothing** — re-run freely after context compression.
CAS terms forbid scripting what is meant to be manual; the user knowingly accepted light, human-paced use. So plan first.
`LOGIN_REQUIRED` (or `chemdb_status` showing `login: login_page`) → ask the user to log in in the "取全文用的浏览器" on the
main machine, then retry.

### CAS numbers and structures (server 0.6) — the user's most common use

```bash
~/bin/litcall chemdb_search '{"db":"scifinder","query":"98-80-6","kind":"substances"}'              # the substance record
~/bin/litcall chemdb_search '{"db":"scifinder","query":"98-80-6","kind":"references","sort":"cited"}' # papers/patents using it
~/bin/litcall chemdb_search '{"db":"scifinder","structure":"OB(O)c1ccccc1","match":"substructure","kind":"substances"}'
~/bin/litcall chemdb_search '{"db":"reaxys","structure":"OB(O)c1ccccc1","match":"similarity","kind":"substances","subset":1}'
```
- `structure`: SMILES (Reaxys also takes a molfile). Neither search box understands SMILES (SciFinder's treats it as an
  exact-structure query, Reaxys's searches the literal string in titles), so the server pastes it into each site's drawing
  editor (CAS Draw / MarvinJS). `structure_formula` (SciFinder) or `structure_smiles` (Reaxys) echoes what the editor
  understood — check it. `query` + `structure` together = both must match.
- `match`: `exact` (as drawn; includes isotope / salt variants), `substructure` (contains this skeleton), `similarity`.
  SciFinder returns `structure_match` with the count for all three (e.g. As Drawn 274 / Substructure 307K / Similarity 101
  for phenylboronic acid) — use it to decide whether to switch.
- Reaxys similarity comes in five tiers in `preview` (tight 1 / near 17 / average 375 / wide 18,288 / widest 76,958 for
  phenylboronic acid). The server opens the strictest non-empty one; pass `subset` (index into `preview`) to open another.
  `subset` also picks among the sub-queries Reaxys splits a keyword sentence into.
- `kind: "substances"` items: `cas_rn, formula (SciFinder) / formula_linear + mw + reaxys_rn (Reaxys), name,
  n_references | n_documents, n_reactions, n_suppliers` (+ Reaxys `n_preparations, n_physical_data, n_spectra,
  n_bioactivity`). SciFinder writes big counts as 51K (`counts_rounded: true`).
  Multi-component substances (salts, 1:1 complexes, copolymers) also give `n_components` and `component_cas_rns`
  (for a copolymer: its monomers). Long formulas are cut by SciFinder's list page: `formula_truncated: true`
  (the full one is only on the substance detail page).
  SciFinder's list page gives **no name** for many multi-component entries (only "Images of a multi component structure
  including CAS RNs …"), so `name` is null there — identify them by `component_cas_rns`. SciFinder lists only components
  that have a CAS number (e.g. HCl in a salt is not listed): `components_unlisted` says how many are missing.
- **CAS number + topic** (the most common question, e.g. "boric acid in self-healing materials"), SciFinder:
  `{"query":"10043-35-3","kind":"references","within":["self-healing"],"filters":{"Concept":["Self-healing materials"]}}`.
  `within` alone (133,484 → 3,035) still lets in electrocatalysis papers ("self-healing catalyst"); the CAS-indexed
  `Concept` facet makes it exact (→ 247, all on topic: boronate dynamic networks, vitrimers, PBS elastomers). Concept values
  only appear once they're in the top 5 of `facets.Concept` — so run `within` first, read `facets`, then add the Concept.
- **Structure → documents** directly: `{"structure": SMILES, "match": "substructure", "kind": "references"}` — SciFinder
  1,4-benzenediboronic acid 6,578 refs; Reaxys 5,852 documents (sorted by `cited`, DOIs for all).
- Reaxys's CAS index is incomplete: boric acid 10043-35-3 is registered only on 7 mineral/hydrate records (max 9 docs);
  the main record carries 11113-50-1. When a CAS number lands only on thin records, the server converts it to a structure
  via PubChem and searches the structure as drawn (`warnings: cas_fallback_to_structure`; → 22,536 docs).
  Candidates are listed in `substance_candidates` / `cas_candidates_reaxys`.
- CAS number alone, sorted by `cited`, mostly surfaces reviews that merely mention the substance (boric acid: Nobel-level
  catalysis and toxicology reviews). Always pair a CAS number with a topic (`within` + `Concept`).
- CAS number + `kind: "references"`: the server lands on that substance first, then opens its references
  (`warnings` contains `via_substance`). In SciFinder, narrow with `filters: {"Substance Role": ["Preparation"]}` etc. —
  the role names are in `facets`. Polymers are poorly indexed by structure: for the user's materials, search the
  monomers / cross-linkers (boric acid 10043-35-3, phenylboronic acid 98-80-6, a specific diol or siloxane) by CAS number.

How the two behave (observed 2026-10-08):

| | SciFinder | Reaxys |
|---|---|---|
| query parsing | ANDs every word (`query_interpretation`), flags it in `query_modified` | recognises substances as structures; splits into sub-queries (`preview`) |
| same query `polyborosiloxane self-healing elastomer` | 26 hits | 134 documents |
| page size | ~80 per page | ~100 per page (server sets the maximum) |
| strengths | patents (incl. Chinese), CAS concepts, patent legal status, facet counts | DOIs in list, times cited, index terms, experimental property data, reaction conditions |

Query tips for this user's field:
- **Go broad, filter later.** `polyborosiloxane self-healing elastomer` → 26 in SciFinder; `boron siloxane self-healing` → 317
  (79 journal articles). Many papers say B–O–Si, borate / boronic ester cross-linked PDMS, borosiloxane, "silly putty".
- `sort: "cited"` first to find the foundational papers, then `date` for the newest.
- Both are built for small molecules: polymer property numbers (tensile strength, healing efficiency) are mostly not indexed.
  Use them to find papers / patents and monomer or cross-linker chemistry; get numbers from full text via
  `paper_fulltext` → `library_section`.
- Patents: `paper_fulltext` doesn't fetch patents; use the patent number with a public patent source.
- For bulk screening, ask the user to export a result set (SciFinder: Excel, "Result Details" template, all fields —
  abstract, concepts, substances, Claim 1, patent status, family) into the export folder shown by `chemdb_status`
  (`exports.dir`). Read it yourself — no quota used.

## PoLyInfo (server 0.8): `polyinfo_status`, `polyinfo_search`, `polyinfo_samples`, `polyinfo_sample`, `polyinfo_current`

NIMS's polymer property database (measured Tg, density, moduli, gas permeability, solubility parameters …, each value
with its sample, composition, conditions and source paper). The user has a DICE account approved for MatNavi and is
logged in in the same browser. Same machinery as chemdb (cache, PENDING + `chemdb_result`, one browser job at a time).

```bash
~/bin/litcall polyinfo_status '{}'     # free: quota, wait, whether a login page / CAPTCHA is blocking the tab
~/bin/litcall polyinfo_search '{"name":"poly(methyl methacrylate)","prop":"Glass transition temperature"}'
~/bin/litcall polyinfo_search '{"formula":"C16H38O5Si4","prop":"Glass transition temperature"}'   # by repeat unit (TRIS)
~/bin/litcall polyinfo_samples '{"pid":"P905362"}'       # every sample of that polymer with its values
~/bin/litcall polyinfo_sample  '{"pid":"P905362","n":1}' # one sample: composition, conditions, reference/DOI, source tables
~/bin/litcall polyinfo_current '{}'    # free: read whatever page the PoLyInfo tab shows now (after the user solved a CAPTCHA)
```

Three levels (observed 2026-10-09):
1. `polyinfo_search` → polymers matching name / PID / repeat-unit formula, with the chosen property's **median, mode,
   variance and number of points** (e.g. PMMA P040048: Tg median 108 °C over 1124 samples; density 1.190 g/cm³ over 208).
   Names are IUPAC-ish English; if a name finds nothing, search by `formula` (one repeat unit, ≤6 elements, only
   C H B Br Cl D F Fe Si Ge I N Na O P S Sn). IDs: `P0xxxxx` homopolymer, `P9xxxxx` copolymer (COID), `BDxxxxxx` blend.
   A wrong `prop` returns `NOT_FOUND` listing every valid property name.
2. `polyinfo_samples` → each sample's property values (no composition yet).
3. `polyinfo_sample` → the full sample record: `info` (polymerization: monomers + feed ratio, initiator, solvent,
   conditions; Mn/Mw), `reference` + `doi`, `components`, `composition` (mol%), `properties` with measurement method /
   conditions, and **`related_tables`: the source paper's composition-vs-property table** (feed vs copolymer composition,
   Mn, Tg, permeability …). Feed vs copolymer composition across a series is what you need to estimate reactivity ratios.
   Example: P905362 (MMA-ran-TRIS methacrylate, Inoue & Matsukawa, J. Macromol. Sci. A 1992, 29(6), 415) lists feed /
   copolymer MTTS mol% 7.4/7.4, 19/19.7, 28/28.4, 41.5/42.6, 62.4/63.8 and Tg 101 → 27 °C, PTRIS homopolymer −7 °C.
   Check the DOI it gives against Crossref before citing (that record printed 10.1080/10101329208052172).

**Rules (server-enforced, stricter than chemdb):** at least 45 s between calls, 15 calls per day (search, samples and
sample each count; cached repeats are free). PoLyInfo's terms forbid bulk acquisition and scraping, manual or
mechanical, and it suspends accounts — so query only what the question in front of you needs; never loop over many
PIDs or samples. For a systematic survey, tell the user what to look at instead.

**CAPTCHA:** the sample-detail page (level 3) asks for a CAPTCHA every time, and searches can too when used often. You get
`code: "CAPTCHA_REQUIRED"`; the server has popped a reminder on the user's desktop. Tell the user, wait for them to say it's
done, then call `polyinfo_current` (free) to read the page — do **not** call `polyinfo_sample` again.
`LOGIN_REQUIRED` → ask the user to log in to PoLyInfo with the DICE account in the "取全文用的浏览器".

## CNKI 中国知网 (server 0.9): `cnki_status`, `cnki_search`, `cnki_page`, `cnki_detail`, `cnki_current`

Chinese master's / PhD theses, Chinese journals, conferences and **Chinese patents**. The school's IP licence covers it
(no login). Chinese theses on polyborosiloxanes are numerous and much more detailed than the journal papers
(full synthesis, raw data, every characterisation) — check here when English literature is thin.

```bash
~/bin/litcall cnki_search '{"query":"聚硼硅氧烷","kind":"thesis"}'       # thesis = PhD + master; phd / master / journal / conference / patent / all
~/bin/litcall cnki_search '{"query":"硼酸酯 动态共价 自修复 弹性体","kind":"patent","sort":"date"}'
~/bin/litcall cnki_page   '{"page":2}'                                     # 20 per page
~/bin/litcall cnki_detail '{"n":2}'                                        # rank on the current results page (or {"url": ...})
```

- `cnki_search` → `items[]`: rank, title, authors, source (journal, or degree-granting university), date, type (期刊 / 硕士 /
  博士 / 中国专利 …), cited, downloads, url; patents: inventors, applicants, date_applied, date_published, patent_no.
  Plus `count`, `pages`, and `counts` per database for that query (e.g. `{学术期刊: 47, 学位论文: 36, 博士: 4, 硕士: 32}`).
- `cnki_detail` → `detail.fields` (摘要 abstract, 关键词, DOI, 分类号, 导师 supervisor, 学科专业, 基金; patents: 申请号, 申请人,
  主权项 main claim, 法律状态) and `detail.outline`: **the thesis's whole table of contents** (e.g. 77 lines) — use it to
  decide which thesis is worth the user downloading.
- Search is by topic (主题). Chinese terms work best (聚硼硅氧烷, 硼硅氧烷, 硼酸酯键, 动态共价键, 自修复, 剪切增稠); English
  terms hit the English abstracts of Chinese papers.
- **Rules:** ≥30 s between calls, 30 calls/day; same search/page/detail on the same day is cached (free).
  CNKI shows a slider CAPTCHA when used a lot → `CAPTCHA_REQUIRED` + desktop reminder; tell the user, then `cnki_current`.
- **No downloading.** CNKI bans the whole university IP for bulk downloads. If a thesis is worth reading in full, tell the
  user which one; they click "PDF下载" themselves.

## CCDC, JCR, Scopus (server 0.10): `ccdc_search`, `ccdc_detail`, `ccdc_current`, `jcr_journal`, `scopus_search`, `scopus_citing`, `scopus_page`, `webdb_status`

All three forbid programmatic access or feeding their data to AI in their terms; the user decided, knowing that, to use
them at a human pace in place of taking screenshots for you. **So: one look-up for the question in front of you, never a
loop.** Quotas are low and server-enforced (`webdb_status`, free): CCDC 15/day ≥45 s apart, JCR 30/day ≥20 s, Scopus 20/day ≥30 s.
A call that isn't finished within `wait_s` returns `PENDING` + `job_id` → `chemdb_result`.

```bash
~/bin/litcall ccdc_search '{"compound":"phenylboronic acid"}'      # or ident (CCDC number / refcode), doi, author
~/bin/litcall ccdc_detail '{"n":3}'                                  # n = rank in the current list
~/bin/litcall jcr_journal '{"journal":"Macromolecules"}'             # name, JCR abbreviation or ISSN; optional year
~/bin/litcall scopus_search '{"query":"polyborosiloxane","sort":"cited"}'
~/bin/litcall scopus_citing '{"n":1}'                                # who cites item 1 of the current page
~/bin/litcall scopus_page   '{"page":2}'
```

- **CCDC** (Access Structures, CSD + ICSD published entries): list ≤30 per search (`truncated: true` if more —
  be more specific): refcode, deposition (CCDC number), space_group, cell, name. `ccdc_detail` adds data_doi
  (10.5517/…), deposited_on and the associated paper(s) with DOI. **No CIF / geometry** — if bond lengths are needed,
  ask the user to download that one CIF; the platform's COD statistics on organic B–O structures live in
  `data/serving/cod_boron/结论.md`. CCDC sometimes shows a validation page → `CAPTCHA_REQUIRED`; the user fills it,
  then `ccdc_current`.
- **JCR**: `journal` = title, issn, eissn, publisher, edition, year, jif, jif_no_self, jci, oa_pct and
  `ranks[{category, year, rank, quartile, percentile}]`. Example: Macromolecules 2025 JIF 5.7 (4.9 w/o self-cites),
  POLYMER SCIENCE 19/96 Q1. A journal "On Hold" at release has `status: "On Hold"` and no JIF. Results are not written
  into the platform's journal tiers (those use open OpenAlex data only).
- **Scopus**: items with eid, title, authors, source + citation, year, cited, type, open_access; DOIs are matched on
  Crossref by title (`doi_match_score`) and each item says `in_library` / `tier`. `query` may be plain words (searched in
  title/abstract/keywords) or a Scopus query (`TITLE-ABS-KEY(borosiloxane) AND PUBYEAR > 2019`, `DOI(...)`).
  For bulk citation work prefer OpenAlex (open data, no limits on use).
