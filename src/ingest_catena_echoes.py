#!/usr/bin/env python3.11
"""Ingest Catena's published open data (catena-echoes.jsonl, CC BY-SA 4.0) as a reception source.

Each echo edge (NT 'citing' -> OT/earlier 'source') becomes TWO keyed reception records so the
resolver surfaces the link from either side:
  - backward, keyed to the NT 'citing' passage:  "quotes/alludes to <source> …"  (what a NT text reaches for)
  - forward,  keyed to the OT 'source' passage:   "taken up at <citing> …"        (the typological afterlife)
refKeys are already canonical (Catena's lib/osis.ts), parsed via the shared osis module.
"""
from __future__ import annotations
import json, sqlite3
from pathlib import Path
import osis

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "reception.sqlite"
ECHOES = Path.home() / "catena" / "public" / "data" / "catena-echoes.jsonl"
SOURCE_ID = "catena"
AUTHOR = "Catena — intertextual"

def row(refKey, refDisplay, text, etype, conf, extended, provenance):
    c = osis.parse_refkey(refKey)
    if not c or c["chapter"] == 0:           # skip book-level / unparseable (can't verse-resolve)
        return None
    return (refKey, refDisplay, c["book"], c["chapter"], c["v_start"], c["v_end"],
            SOURCE_ID, AUTHOR, "intertext-extended" if extended else "intertext",
            f"{etype}, {conf}", text, provenance, "text", None)

def main():
    con = sqlite3.connect(DB)
    con.execute("DELETE FROM reception WHERE source=?", (SOURCE_ID,))
    rows = []
    n = 0
    for line in ECHOES.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        e = json.loads(line); n += 1
        cit, src = e["citing"], e["source"]
        typ, conf = e["type"], e["confidence"]
        contested = " (contested)" if e.get("contested") else ""
        note = (" — " + e["note"]) if e.get("note") else ""
        stext = (": " + e["sourceText"]) if e.get("sourceText") else ""
        ext = bool(src.get("extended"))
        # backward: keyed to the NT citing passage
        b = row(cit["refKey"], cit["refDisplay"],
                f"{typ.capitalize()} of {src['refDisplay']}{contested}{stext}{note}",
                typ, conf, False, e.get("provenance", ""))
        # forward: keyed to the OT/earlier source passage
        f = row(src["refKey"], src["refDisplay"],
                f"Taken up at {cit['refDisplay']} ({typ}, {conf}){contested}{note}",
                typ, conf, ext, e.get("provenance", ""))
        rows += [r for r in (b, f) if r]
    con.executemany("""INSERT INTO reception
        (refKey,refDisplay,book,chapter,v_start,v_end,source,author,tradition,work,text,provenanceUrl,mode,anchor)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
    con.commit()
    print(f"ingested {n} echoes -> {len(rows)} reception records (both directions), source='{SOURCE_ID}'")
    bym = dict(con.execute("SELECT mode,count(*) FROM reception GROUP BY mode"))
    tot = con.execute("SELECT count(*) FROM reception").fetchone()[0]
    print(f"store total: {tot}  by mode: {bym}")
    con.row_factory = sqlite3.Row
    def show(label, book, ch, v0, v1):
        rows = con.execute("""SELECT source,author,refDisplay,text FROM reception
            WHERE book=? AND chapter=? AND ((v_start=0 AND v_end=0) OR (v_start<=? AND v_end>=?))
            ORDER BY (source='catena') DESC, source LIMIT 60""", (book, ch, v1, v0)).fetchall()
        from collections import Counter
        print(f"\n=== {label} — sources: {dict(Counter(r['source'] for r in rows))} ===")
        for r in [x for x in rows if x["source"] == "catena"][:4]:
            print(f"  · {r['text'][:150]}")
    show("Isaiah 53:5 (OT — forward echoes: its NT afterlife)", "Isa", 53, 5, 5)
    show("Hebrews 1:5 (NT — backward echoes: what it quotes)", "Heb", 1, 5, 5)
    con.close()

if __name__ == "__main__":
    main()
