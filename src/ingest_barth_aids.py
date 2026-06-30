#!/usr/bin/env python3.11
"""Ingest Barth's *Church Dogmatics* pointer index from the "Aids for the Preacher"
(CD Index Volume, T&T Clark 1977) into the reception store as mode='pointer' rows.

COPYRIGHT POSTURE (Wilson, 2026-06-30) — FACTS ONLY, RE-ARRANGED BY RCL:
  * We store ONLY the bare FACT "Barth treats <scripture> at CD <vol>/<part> p.<page>"
    (+ the short CD section title as a human anchor). Barth's PROSE is never stored.
  * We do NOT replicate the editors' compilation arrangement, nor the 1958 German
    Lutheran lectionary the Aids are keyed to. We re-key every entry by OSIS refKey and
    let the RCL spine arrange it (verse-range overlap). This keeps clear of BOTH the
    Barth/Bromiley prose copyright AND the editors' thin compilation copyright (Feist):
    individual location facts are uncopyrightable; our selection/arrangement is our own.
  * mode='pointer'  -> text column is ALWAYS NULL.

INPUT  cache/barth/aids_pointers*.jsonl  — one JSON object per scripture entry, produced by a
       vision-OCR pass over the rendered Aids pages (the printed verse superscripts are lost by
       pdftotext, so the references MUST come from vision, not the text layer). Schema:
         {"occasion": str, "ref": "Luke 1:67-79", "series": "III"|null,
          "cd_refs": [{"vol":"IV","part":2,"page":183,"section":"The Royal Man",
                       "cf": true?, "page_ed1": 447?}], "src_pages": "264-265"}
OUTPUT reception.sqlite rows: one per (scripture refKey-span x cd_ref).

Usage: python3.11 src/ingest_barth_aids.py [jsonl ...]   (default: the proof file)
"""
from __future__ import annotations
import json, sqlite3, sys, glob
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from build_rcl import parse_citation          # citation string -> {refKey, refDisplay, refKeys?}
import osis

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "reception.sqlite"
SOURCE = "barth-cd"

COLS = ("refKey", "refDisplay", "book", "chapter", "v_start", "v_end",
        "source", "author", "tradition", "work", "text", "provenanceUrl", "mode", "anchor")


def rows_for_entry(e: dict):
    """Yield reception rows (dicts) for one Aids entry. text is always None (pointer-only)."""
    cit = parse_citation(e["ref"])                       # may raise; caller collects
    spans = cit.get("refKeys", [cit["refKey"]])          # multi-span -> each span keyed
    disp = cit["refDisplay"]
    for span in spans:
        p = osis.parse_refkey(span)
        for cd in e["cd_refs"]:
            anchor = f"CD {cd['vol']}/{cd['part']}:{cd['page']}"
            if cd.get("cf"):                             # editors' "Cf. also" = related, not direct
                anchor = "cf. " + anchor
            yield {
                "refKey": span, "refDisplay": disp,
                "book": p["book"], "chapter": p["chapter"],
                "v_start": p["v_start"], "v_end": p["v_end"],
                "source": SOURCE, "author": "Karl Barth", "tradition": "dialectical",
                "work": cd.get("section"),               # CD section title = human anchor (a fact)
                "text": None,                            # NEVER store Barth's prose
                "provenanceUrl": None,
                "mode": "pointer",
                "anchor": anchor,
            }


def main(argv):
    files = argv or [str(ROOT / "cache/barth/aids_pointers_proof.jsonl")]
    paths = [p for f in files for p in glob.glob(f)]
    con = sqlite3.connect(DB)
    con.execute("DELETE FROM reception WHERE source=?", (SOURCE,))   # idempotent re-ingest
    entries = errs = rows = empty = 0
    ph = ",".join("?" * len(COLS))
    for path in paths:
        for ln, line in enumerate(open(path, encoding="utf-8"), 1):
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            if e.get("continues_prev"):
                continue                                 # merge step already folded these
            entries += 1
            if not e.get("cd_refs"):                      # header-only text Barth never treats -> no pointer
                empty += 1
                continue
            try:
                batch = list(rows_for_entry(e))
            except Exception as ex:                      # collect, never silently drop
                errs += 1
                print(f"  ! parse fail {path}:{ln}  {e.get('ref')!r}: {ex}", file=sys.stderr)
                continue
            con.executemany(
                f"INSERT INTO reception ({','.join(COLS)}) VALUES ({ph})",
                [tuple(r[c] for c in COLS) for r in batch])
            rows += len(batch)
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM reception WHERE source=?", (SOURCE,)).fetchone()[0]
    con.close()
    print(f"Barth Aids ingest: {entries} entries ({empty} header-only/no-CD skipped), "
          f"{rows} pointer rows written, {errs} parse errors.")
    print(f"  reception rows now source='{SOURCE}': {n}")


if __name__ == "__main__":
    main(sys.argv[1:])
