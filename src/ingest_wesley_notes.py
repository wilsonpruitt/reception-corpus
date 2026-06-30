#!/usr/bin/env python3.11
"""Ingest John Wesley's *Explanatory Notes Upon the Old and New Testament* into the
reception store as source='wesley-notes' (mode='text') — the verse-keyed backbone of
the Wesley RCL companion.

Source: the in-house Wroot Press digital edition `~/kjv-wesley/data/notes/<slug>.json`
(verse-keyed; itself derived from the CCEL public-domain plain text). Each note already
carries {chapter, verse_start, verse_end, lemma, comment}, so this maps straight onto the
store's overlap columns — no parsing, just OSIS-key it via the shared osis.py.

Idempotent: deletes source='wesley-notes' then re-inserts. Run order vs other sources
doesn't matter; reception.sqlite accumulates.
"""
from __future__ import annotations
import json, sqlite3
from pathlib import Path
import osis

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "reception.sqlite"
NOTES_DIR = Path.home() / "kjv-wesley" / "data" / "notes"
REPO_BLOB = "https://github.com/wilsonpruitt/kjv-wesley/blob/main/web/data/notes"

SOURCE_ID = "wesley-notes"
AUTHOR = "John Wesley"
TRADITION = "Methodist"
WORK = {"NT": "Explanatory Notes Upon the New Testament",
        "OT": "Explanatory Notes Upon the Old Testament"}

NAME2CODE = {v: k for k, v in osis.OSIS_NAME.items()}
NAME2CODE.update({"Psalm": "Ps", "Song of Songs": "Song"})


def build_rows():
    rows = []
    skipped = []
    for f in sorted(NOTES_DIR.glob("*.json")):
        if f.name in ("_prefaces.json", "index.json"):
            continue
        d = json.loads(f.read_text(encoding="utf-8"))
        if not isinstance(d, dict) or not d.get("notes"):
            skipped.append(f.name)
            continue
        name, slug, testament = d.get("name"), d.get("slug"), d.get("testament", "NT")
        code = NAME2CODE.get(name)
        if not code:
            skipped.append(f"{f.name} (unmapped book {name!r})")
            continue
        work = WORK.get(testament, WORK["NT"])
        url = f"{REPO_BLOB}/{slug}.json"
        for n in d["notes"]:
            ch = int(n["chapter"])
            vs = int(n.get("verse_start") or 0)
            ve = int(n.get("verse_end") or vs)
            if ve < vs:
                ve = vs
            if vs == 0:                                   # whole-chapter (rare/none) -> chapter key
                refKey = osis.build_refkey(code, ch)
            elif ve == vs:
                refKey = osis.build_refkey(code, ch, vs)
            else:
                refKey = osis.build_refkey(code, ch, vs, ch, ve)
            lemma = (n.get("lemma") or "").strip()
            comment = (n.get("comment") or "").strip()
            text = f"{lemma} — {comment}" if lemma else comment
            if not text:
                continue
            rows.append((refKey, osis.refkey_to_display(refKey), code, ch, vs, ve,
                         SOURCE_ID, AUTHOR, TRADITION, work, text, url, "text", None))
    return rows, skipped


def main():
    rows, skipped = build_rows()
    con = sqlite3.connect(DB)
    con.execute("DELETE FROM reception WHERE source=?", (SOURCE_ID,))   # idempotent
    con.executemany("""INSERT INTO reception
        (refKey,refDisplay,book,chapter,v_start,v_end,source,author,tradition,work,text,provenanceUrl,mode,anchor)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM reception WHERE source=?", (SOURCE_ID,)).fetchone()[0]
    books = con.execute("SELECT COUNT(DISTINCT book) FROM reception WHERE source=?", (SOURCE_ID,)).fetchone()[0]
    print(f"wesley-notes: inserted {n} notes across {books} books"
          + (f"; skipped {skipped}" if skipped else ""))
    # spot-check a couple of RCL stations
    con.row_factory = sqlite3.Row
    for label, bk, ch, q0, q1 in [("Romans 1:16-17 (justification)", "Rom", 1, 16, 17),
                                  ("Matthew 20:1-16 (vineyard)", "Matt", 20, 1, 16)]:
        r = con.execute("""SELECT refDisplay,text FROM reception WHERE source=? AND book=? AND chapter=?
            AND v_start<=? AND v_end>=? ORDER BY v_start LIMIT 1""",
            (SOURCE_ID, bk, ch, q1, q0)).fetchone()
        print(f"  ▸ {label}: " + (f"[{r['refDisplay']}] {r['text'][:120]}" if r else "(no note)"))
    con.close()


if __name__ == "__main__":
    main()
