#!/usr/bin/env python3.11
"""RCL spine loader + resolver. Loads data/rcl.json and joins each reading to the reception store
by OSIS refKey — the proof that the shared spine lights up Fathers/commentary/echoes per Sunday.
Importable by Lectern and the Catena WS3 lectionary aid (the single shared spine).
"""
from __future__ import annotations
import json, sqlite3
from collections import Counter
from pathlib import Path
import osis

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "reception.sqlite"
SPINE = ROOT / "data" / "rcl.json"

def load():
    return json.loads(SPINE.read_text(encoding="utf-8"))

def reading_refkeys(reading):
    return reading.get("refKeys") or [reading["refKey"]]

def validate(spine):
    bad = []
    for occ in spine["occasions"]:
        for r in occ["readings"]:
            for rk in reading_refkeys(r):
                p = osis.parse_refkey(rk)
                if not p or p["chapter"] == 0 and "." in rk.split("-")[0][len(p["book"]):]:
                    bad.append((occ["id"], rk))
    return bad

def resolve_reading(con, reading):
    """All reception rows overlapping any span of a reading."""
    out = []
    for rk in reading_refkeys(reading):
        p = osis.parse_refkey(rk)
        if not p:
            continue
        rows = con.execute("""SELECT source,author,refDisplay,mode,text FROM reception
            WHERE book=? AND chapter=? AND ((v_start=0 AND v_end=0) OR (v_start<=? AND v_end>=?))""",
            (p["book"], p["chapter"], p["v_end"] or p["v_start"] or 999, p["v_start"] or 0)).fetchall()
        out.extend(rows)
    return out

def main():
    spine = load()
    bad = validate(spine)
    print(f"RCL spine: {len(spine['occasions'])} occasions; refKey validation: "
          f"{'all parse' if not bad else bad}")
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    for occ in spine["occasions"]:
        print(f"\n=== {occ['name']} ({occ['year']}) — {occ['season']} ===")
        for r in occ["readings"]:
            rows = resolve_reading(con, r)
            srcs = Counter(x["source"] for x in rows)
            tag = " [alt]" if r.get("alt") else ""
            print(f"  {r['role']:7} {r['refDisplay']:28}{tag}  {sum(srcs.values()):4} records  {dict(srcs)}")
    # deep example: the Emmanuel prophecy + its Gospel fulfilment, fully resolved
    print("\n" + "=" * 70)
    print("STATION DETAIL — Advent 4A, the Emmanuel pairing (what a preacher would see)")
    for label, rk in [("Isaiah 7:14 (Emmanuel)", "Isa.7.14"),
                      ("Matthew 1:18–25 (the nativity)", "Matt.1.18-Matt.1.25")]:
        p = osis.parse_refkey(rk)
        rows = con.execute("""SELECT source,author,refDisplay,mode,text FROM reception
            WHERE book=? AND chapter=? AND ((v_start=0 AND v_end=0) OR (v_start<=? AND v_end>=?))
            ORDER BY (mode='text') DESC, source""",
            (p["book"], p["chapter"], p["v_end"] or p["v_start"], p["v_start"])).fetchall()
        print(f"\n  ▸ {label} — {len(rows)} records, sources {dict(Counter(r['source'] for r in rows))}")
        for r in rows[:2]:
            kind = r["source"] if r["mode"] == "text" else f"{r['source']} (pointer)"
            print(f"      [{kind}] {r['author']}: {(r['text'] or '(pull on demand)')[:130]}")
    con.close()

if __name__ == "__main__":
    main()
