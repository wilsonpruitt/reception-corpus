# Barth *Church Dogmatics* "Aids for the Preacher" — ingest status

**Source:** `~/Downloads/Church dogmatics. Index volume, with aids to the preacher … .pdf`
(CD Index Volume, T&T Clark 1977). Internet Archive scan, 573 pp.
**Entry section:** pdf pages **278–563** (= printed 264–549). pdf 564+ is the trailing German
cross-index, NOT ingested (we re-key by RCL, so the editors' order is not needed).

**Posture:** pointer-only (`mode='pointer'`, source `barth-cd`). Zero Barth prose stored. Facts only —
`vol/part/page` + CD section title — re-keyed by OSIS refKey, arranged by the RCL.
See `src/ingest_barth_aids.py` header for the copyright reasoning.

## Method (proven)
`pdftotext` corrupts the printed superscript verse numbers, so references MUST come from vision-OCR
of rendered pages, not the text layer. Pipeline:
1. `pdftoppm -r 150 -png -f 278 -l 563 <pdf> cache/barth/png/p`  → `cache/barth/png/p-<pdf>.png` (all 286 rendered, on disk)
2. vision subagents read 18-page batches → write `cache/barth/batches/batch_<pdfstart>.jsonl`
   (schema: `{occasion, ref, series, cd_refs:[{vol,part,page,section,cf?,page_ed1?}], src_pages}`;
    entries spanning a batch edge emit a leading `{"continues_prev":true,...}` orphan)
3. `python3.11 src/merge_barth_batches.py`  → folds orphans, gap-aware → `cache/barth/aids_pointers.jsonl`
4. `python3.11 src/ingest_barth_aids.py cache/barth/aids_pointers.jsonl`  → reception.sqlite

## DONE (2026-06-30) — 10 of 16 batches
Batches ingested (pdf pages): 278–439, 458–475.
→ **284 entries, 724 pointer rows** (42 header-only texts Barth never treats, dropped).
→ Covers **194/228 RCL occasions (85%)**, 363 reading-slots, via verse-overlap join.

## PENDING — 6 batches (re-run when tokens allow; PNGs already rendered)
Each: a `general-purpose` vision agent, 18 pages, prompt template = see the completed batch agents
(or the §"vision subagents" spec above). Write to the listed path, then `merge` + `ingest` again
(both are idempotent — merge re-reads all batch_*.jsonl; ingest DELETEs source='barth-cd' first).

| batch | pdf pages | printed | output file |
|------|-----------|---------|-------------|
| 440  | 440–457   | 426–443 | cache/barth/batches/batch_440.jsonl |
| 476  | 476–493   | 462–479 | cache/barth/batches/batch_476.jsonl |
| 494  | 494–511   | 480–497 | cache/barth/batches/batch_494.jsonl |
| 512  | 512–529   | 498–515 | cache/barth/batches/batch_512.jsonl |
| 530  | 530–547   | 516–533 | cache/barth/batches/batch_530.jsonl |
| 548  | 548–563   | 534–549 | cache/barth/batches/batch_548.jsonl (entries END ~p549; skip the trailing index after) |

Note: batch_422's last entry and batch_458's first entry may be missing a few CD refs that live in the
un-ingested 440–457 gap; they'll complete automatically once batch_440 is added (merge is gap-aware and
will fold batch_458's leading orphan once 440 is present).
