# reception-corpus

The shared **reception data layer** behind Lectern (the preacher's workbench) and the Catena WS3
lectionary aid. One OSIS-keyed store that answers, for any passage: *what has the church said here?*
— Fathers, Reformers, commentary, and Scripture-on-Scripture echoes, in a single query.

Built to the **Wroot data-repository standard** (see `~/.claude/.../memory/reference_data-repository-standard.md`):
dual `refKey` (OSIS, KJV/WEB versification) + `refDisplay`; SQLite source-of-truth; source-first ingest;
attributions come from retrieved text, never model recall.

## Store: `data/reception.sqlite` — table `reception` (101,353 rows as of 2026-06-30)

| column | meaning |
|---|---|
| `refKey` / `refDisplay` | OSIS join key (`Matt.20.1-Matt.20.16`) / human (`Matthew 20:1–16`) |
| `book, chapter, v_start, v_end` | overlap-index columns (v_start=v_end=0 ⇒ whole chapter) |
| `source, author, tradition, work` | provenance + attribution |
| `text` | verbatim prose (mode=text) or NULL (mode=index, pull on demand) |
| `mode` | `text` = prose stored · `index` = PD pointer, lazy text · `pointer` = citation-only (copyright, e.g. Barth — reserved, unused) |
| `anchor` | ThML id for `pull_text()` (index rows) |
| `provenanceUrl` | source URL — attribution stays auditable |

### Sources ingested
| source | mode | rows | coverage |
|---|---|---|---|
| `catena-aurea` | text | 4,829 | **Matthew only** (CCEL ThML; the patristic chains) |
| `jfb` (Jamieson-Fausset-Brown) | index | 32,281 | 66 books |
| `matthew-henry` | index | 5,569 | 66 books |
| `barnes` (Albert Barnes) | index | 8,207 | NT (27) |
| `calvin` | index | 14,052 | Calvin's canon subset |
| `catena` (intertextual echoes) | text | 18,495 | both directions, from `catena-echoes.jsonl` |
| `wesley-notes` (John Wesley, *Explanatory Notes*) | text | 17,920 | 66 books (OT Notes abridged) — the Wesley RCL companion backbone |

## Scripts (`src/`)
- **`osis.py`** — shared OSIS module; Python mirror of Catena's `lib/osis.ts` (refKey grammar, cross-chapter, parse/display). Import this; don't reinvent reference handling.
- **`ingest_catena_matthew.py`** — Catena Aurea (Matthew) full-text, from `cache/catena1.thml.xml`. Bounded author alias table; continuations merged; validated vs source.
- **`ingest_commentary_index.py`** — generic CCEL-ThML index ingester (JFB/Henry/Barnes/Calvin) via `<scripCom osisRef=…>`; + lazy `pull_text(source, anchor)`. Idempotent (deletes mode=index then re-inserts).
- **`ingest_catena_echoes.py`** — Catena open-data echoes → both-direction reception rows.
- **`ingest_wesley_notes.py`** — John Wesley's *Explanatory Notes* (verse-keyed, mode=text) from in-house `~/kjv-wesley/data/notes/*.json` (PD; CCEL upstream). The **Wesley RCL companion** backbone: 96% of RCL readings (1,150/1,188) resolve a Wesley note; gaps = 19 Apocrypha + 7 OT/NT passages Wesley left unannotated (honest, not silent). Idempotent on `source='wesley-notes'`.
- **`rcl.py`** — RCL spine loader/validator/resolver. Importable by Lectern + Catena-WS3. `resolve_reading` is **cross-chapter aware** (`chapter_query_spans` expands e.g. `Jonah.3.10-Jonah.4.11` across every spanned chapter — the single-chapter overlap index would otherwise drop the later chapter).
- **`build_rcl.py`** — rebuilds `data/rcl.json` from the cached Vanderbilt xlsx (full A/B/C). **`validate_rcl.py`** — fidelity gate (run after any rebuild).

## Spine: `data/rcl.json` — the shared lectionary calendar
Per occasion: `{id, year(A|B|C), season, name, readings:[{role, track?, refKey, refDisplay, refKeys?, multi?, alt?, note?}]}`.
Every reading carries an OSIS refKey → the universal join. **COMPLETE: Years A, B, C — 228 occasions, 1,188 readings.**
Built from the Vanderbilt Divinity Library per-year Excel downloads (`cache/rcl_year_{A,B,C}.xlsx`,
lectionary.library.vanderbilt.edu — the canonical machine-readable RCL; citation lists are facts, not
copyrightable). **`refDisplay` is verbatim from Vanderbilt** (authoritative, never recalled); **refKeys are
derived and validated**. Every non-Apocrypha reading resolves to reception rows (0 dead); 25 Apocrypha refKeys
(Wis/Sir/Bar) carry no reception text but keep authoritative refDisplay.

- `role` ∈ first | psalm | second | gospel. `track` = semicontinuous | complementary (Season after Pentecost
  OT only; second + Gospel are shared). `refKeys[]` + `multi` for split verse-spans (`Ps.72.1-Ps.72.7`,
  `Ps.72.18-Ps.72.19`). `alt:true` = an "or" alternative to the preceding same-role reading. `note` = Easter
  Vigil reading index.
- **`src/build_rcl.py`** rebuilds the spine from the cached xlsx (citation→OSIS parser: tracks, or-alternatives,
  parentheticals/optional verses, partial-verse letters, cross-chapter & semicolon multi-spans, Apocrypha,
  the 9-reading Easter Vigil, the Liturgy-of-the-Palms gospel-column quirk). **`src/validate_rcl.py`** is the
  fidelity gate: every refKey parses; every integer in a refKey appears in its verbatim refDisplay (anti-
  fabrication); generated Year-A Advent == the original hand-verified data; reception resolution lights up.

## How to extend
- **More Catena Aurea Gospels:** fetch CCEL `catena2/3/4.xml` (Mark/Luke/John) into `cache/`, generalize `ingest_catena_matthew.py` (currently Matthew-hardcoded: `BOOK_OSIS`, the `<div2 title="Chapter N">` walk).
- **More commentaries:** add `(source_id, author, tradition, [files])` to `SOURCES` in `ingest_commentary_index.py`, fetch the CCEL ThML to `cache/`, re-run. `remote_url()` maps filenames→provenance.
- **Lectionary:** the RCL spine is complete (A/B/C). To regenerate, re-run `src/build_rcl.py` then `src/validate_rcl.py`. Daily-office / RC daily-Mass calendars would be separate spines (different source).
- **Run order doesn't matter** across sources (each idempotent for its source); `reception.sqlite` accumulates.

## Conventions / caveats
- Python 3.11 (`/usr/local/bin/python3.11`); stdlib only (no bs4 needed — regex over cached ThML).
- Raw sources cached in `cache/` — never re-hammer hosts; re-parse is free.
- RCL cites **NRSV** versification; refKeys normalized to KJV/WEB to join our texts — flag divergences (Psalm headings etc.).
- Cross-chapter refKeys (`Exod.2.8-Exod.3.3`) store an approximate rest-of-chapter `v_end` for the integer overlap index; the refKey string stays exact for joins.
