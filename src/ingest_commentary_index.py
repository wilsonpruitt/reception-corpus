#!/usr/bin/env python3.11
"""Index-first ingest of single-author PD commentaries from CCEL ThML.

Two-tier model (reference_data-repository-standard): store a lightweight POINTER index
(refKey -> source + anchor) and pull prose from the cached raw file on demand. CCEL pre-tags
every commentary section with <scripCom osisRef=... id=... passage=.../>, so the index is
extracted directly — no prose parsing to build the spine.

mode='index'  -> PD commentary; pointer stored, full text lazily available via pull_text(source, anchor)
mode='text'   -> full prose stored inline (the Catena Aurea rows)
mode='pointer' -> citation only, source words NEVER stored (reserved for in-copyright works, e.g. Barth)
"""
from __future__ import annotations
import re, sqlite3, html
from pathlib import Path
import osis   # shared OSIS module — mirrors Catena's lib/osis.ts (refKey grammar, cross-chapter)

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "reception.sqlite"
CACHE = ROOT / "cache"

SOURCES = [
    # source_id, author label, tradition, [cache files]
    ("jfb", "Jamieson, Fausset & Brown", "protestant-19c", ["jfb.thml.xml"]),
    ("matthew-henry", "Matthew Henry", "puritan", [f"mhc{v}.thml.xml" for v in range(1, 7)]),
    ("barnes", "Albert Barnes", "protestant-19c", ["barnes_nt.thml.xml"]),
    ("calvin", "John Calvin", "reformed", [f"calcom{v:02d}.thml.xml" for v in range(1, 46)]),
]

def remote_url(fn):
    """Map a local cache filename to its canonical CCEL work URL (for provenance)."""
    base = fn.replace(".thml.xml", "")
    if base.startswith("calcom"):  return f"https://ccel.org/ccel/calvin/{base}.xml"
    if base.startswith("mhc"):     return f"https://ccel.org/ccel/henry/{base}.xml"
    if base == "jfb":              return "https://ccel.org/ccel/jamieson/jfb.xml"
    if base == "barnes_nt":        return "https://ccel.org/ccel/barnes/ntnotes.xml"
    return f"https://ccel.org/ccel/{base}.xml"

SCRIPCOM = re.compile(r'<scripCom\b([^>]*?)/?>', re.I)
ATTR = lambda a, s: (re.search(rf'{a}="([^"]*)"', s) or [None, None])[1]

def migrate():
    con = sqlite3.connect(DB)
    cols = {r[1] for r in con.execute("PRAGMA table_info(reception)")}
    if "mode" not in cols:
        con.execute("ALTER TABLE reception ADD COLUMN mode TEXT")
        con.execute("UPDATE reception SET mode='text' WHERE mode IS NULL")
    if "anchor" not in cols:
        con.execute("ALTER TABLE reception ADD COLUMN anchor TEXT")
    con.execute("DELETE FROM reception WHERE mode='index'")   # idempotent re-ingest
    con.commit(); con.close()

def ingest():
    con = sqlite3.connect(DB)
    total = {}
    for source_id, author, tradition, files in SOURCES:
        rows, skipped = [], 0
        for fn in files:
            raw = (CACHE / fn).read_bytes().decode("utf-8", "replace")
            for m in SCRIPCOM.finditer(raw):
                attrs = m.group(1)
                if (ATTR("type", attrs) or "").lower() not in ("commentary", ""):
                    continue
                osisref = ATTR("osisRef", attrs)
                if not osisref:
                    skipped += 1; continue
                rk = osis.normalize_osisref(osisref)
                c = osis.parse_refkey(rk)
                if c["book"] not in osis.OSIS_NAME:
                    skipped += 1; continue
                anchor = ATTR("id", attrs)
                rows.append((rk, osis.refkey_to_display(rk), c["book"], c["chapter"],
                             c["v_start"], c["v_end"], source_id, author,
                             tradition, ATTR("passage", attrs) or "", None,
                             f"{remote_url(fn)}#{anchor}", "index", anchor))
        con.executemany("""INSERT INTO reception
            (refKey,refDisplay,book,chapter,v_start,v_end,source,author,tradition,work,text,provenanceUrl,mode,anchor)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
        total[source_id] = (len(rows), skipped)
    con.commit(); con.close()
    return total

def _clean(seg):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", seg)).replace(" ", " ")).strip()

def pull_text(source, anchor):
    """Lazily extract a commentary's prose from cache. CCEL clusters scripCom markers
    (chapter + verse back-to-back), so hop over heading-only segments to the first real prose,
    without crossing a section (</div>) boundary."""
    files = next(s[3] for s in SOURCES if s[0] == source)
    for fn in files:
        raw = (CACHE / fn).read_bytes().decode("utf-8", "replace")
        m = re.search(rf'<scripCom\b[^>]*\bid="{re.escape(anchor)}"[^>]*?/?>', raw)
        if not m:
            continue
        pos = m.end()
        for _ in range(6):                      # hop at most a few clustered markers
            nxt = SCRIPCOM.search(raw, pos)
            seg = raw[pos: nxt.start() if nxt else pos + 6000]
            text = _clean(seg)
            text = re.sub(r"^(?:MATTHEW |MARK |LUKE |JOHN )?CHAPTER\s+[IVXLC0-9]+\.?\s*", "", text, flags=re.I)
            if len(text) > 40:                  # real prose, not a bare heading
                return text[:4000]
            if "</div" in seg or not nxt:        # don't cross into the next section
                break
            pos = nxt.end()
        return None
    return None

def resolve(book, ch, q0, q1):
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    rows = con.execute("""SELECT * FROM reception WHERE book=? AND chapter=?
        AND ((v_start=0 AND v_end=0) OR (v_start<=? AND v_end>=?))
        ORDER BY mode DESC, source, v_start, id""", (book, ch, q1, q0)).fetchall()
    con.close(); return rows

def main():
    migrate()
    total = ingest()
    con = sqlite3.connect(DB)
    print("=== commentary index ingested (mode='index') ===")
    for sid, (n, sk) in total.items():
        print(f"  {sid:16} {n:7} pointers  ({sk} scripCom skipped: no/odd osisRef)")
    grand = con.execute("SELECT count(*) FROM reception").fetchone()[0]
    bym = dict(con.execute("SELECT mode,count(*) FROM reception GROUP BY mode"))
    byb = con.execute("SELECT count(distinct book) FROM reception WHERE mode='index'").fetchone()[0]
    print(f"\nstore total rows: {grand}  by mode: {bym}  | index spans {byb} books")
    con.close()
    print("\n=== resolver demo: Matt 20:1-16 across ALL sources ===")
    rows = resolve("Matt", 20, 1, 16)
    from collections import Counter
    print("sources:", dict(Counter(r["source"] for r in rows)))
    # show one pointer per PD commentary + lazily pull its text
    for src in ("jfb", "matthew-henry", "barnes"):
        r = next((x for x in rows if x["source"] == src), None)
        if r:
            txt = pull_text(src, r["anchor"])
            print(f"\n  {r['author']} @ {r['refDisplay']} (anchor {r['anchor']}, mode={r['mode']})")
            print(f"    pulled: {txt[:200] if txt else '(none)'}...")
    # show an OT verse to prove whole-canon coverage the Catena lacks
    print("\n=== resolver demo: Isaiah 53:5 (OT — Catena has nothing here) ===")
    for r in resolve("Isa", 53, 5, 5):
        print(f"  {r['source']:14} {r['author']:26} {r['refDisplay']}")

if __name__ == "__main__":
    main()
