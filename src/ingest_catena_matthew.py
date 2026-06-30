#!/usr/bin/env python3.11
"""Ingest the Catena Aurea (Gospel of Matthew) from CCEL ThML into the reception store.

Source: https://ccel.org/ccel/aquinas/catena1.xml  (Newman tr., public domain; clean UTF-8 ThML)
Conforms to reference_data-repository-standard: dual refKey(OSIS)/refDisplay, SQLite + JSON export,
verbatim text + provenanceUrl, controlled author vocab derived from the data (unmapped -> flagged).

Recognition discipline: a paragraph starts a NEW Father-comment only if its leading token matches a
KNOWN author alias (prefix + word-boundary). Everything else is a continuation of the prior comment.
This caps confabulation (no colon-guessing) and preserves multi-paragraph comments.
"""
from __future__ import annotations
import re, html, json, sqlite3, collections
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "cache" / "catena1.thml.xml"
DB = ROOT / "data" / "reception.sqlite"
JSON_OUT = ROOT / "out" / "catena-aurea" / "matthew.json"
SOURCE_ID = "catena-aurea"
SOURCE_URL = "https://ccel.org/ccel/aquinas/catena1.xml"
BOOK_OSIS, BOOK_NAME = "Matt", "Matthew"

# raw alias (lowercase) -> (canonical name, tradition). Enumerated from corpus token frequency.
AUTHORS = {
    "jerome": ("Jerome", "latin-patristic"),
    "chrys": ("John Chrysostom", "greek-patristic"), "chrysostom": ("John Chrysostom", "greek-patristic"),
    "chyrs": ("John Chrysostom", "greek-patristic"),
    "pseudo-chrys": ("Pseudo-Chrysostom", "pseudonymous"), "pseudo-chys": ("Pseudo-Chrysostom", "pseudonymous"),
    "pseudo-chyrs": ("Pseudo-Chrysostom", "pseudonymous"),
    "aug": ("Augustine", "latin-patristic"), "augustine": ("Augustine", "latin-patristic"),
    "pseudo-aug": ("Pseudo-Augustine", "pseudonymous"), "pseudo-augustine": ("Pseudo-Augustine", "pseudonymous"),
    "psuedo-aug": ("Pseudo-Augustine", "pseudonymous"),
    "remig": ("Remigius of Auxerre", "medieval"), "remigius": ("Remigius of Auxerre", "medieval"),
    "hilary": ("Hilary of Poitiers", "latin-patristic"), "hil": ("Hilary of Poitiers", "latin-patristic"),
    "origen": ("Origen", "greek-patristic"), "pseudo-origen": ("Pseudo-Origen", "pseudonymous"),
    "raban": ("Rabanus Maurus", "medieval"), "rabanus": ("Rabanus Maurus", "medieval"),
    "gregory nyss": ("Gregory of Nyssa", "greek-patristic"), "gregory nazianzen": ("Gregory Nazianzen", "greek-patristic"),
    "greg": ("Gregory the Great", "latin-patristic"), "gregory": ("Gregory the Great", "latin-patristic"),
    "ambrosiaster": ("Ambrosiaster", "latin-patristic"), "ambrose": ("Ambrose", "latin-patristic"),
    "leo": ("Leo the Great", "latin-patristic"), "pope leo": ("Leo the Great", "latin-patristic"),
    "bede": ("Bede", "medieval"),
    "cyprian": ("Cyprian", "latin-patristic"), "pseudo-cyprian": ("Pseudo-Cyprian", "pseudonymous"),
    "chrysologus": ("Peter Chrysologus", "latin-patristic"), "chrysol": ("Peter Chrysologus", "latin-patristic"),
    "cyril of alexandria": ("Cyril of Alexandria", "greek-patristic"), "cyril": ("Cyril of Alexandria", "greek-patristic"),
    "eusebius": ("Eusebius of Caesarea", "greek-patristic"), "euseb": ("Eusebius of Caesarea", "greek-patristic"),
    "pseudo-athan": ("Pseudo-Athanasius", "pseudonymous"), "athanasius": ("Athanasius", "greek-patristic"),
    "isidore": ("Isidore of Seville", "medieval"), "isid": ("Isidore of Seville", "medieval"),
    "gennadius": ("Gennadius", "patristic"), "theodotus": ("Theodotus", "patristic"),
    "pseudo-dionysius": ("Dionysius the Areopagite", "greek-patristic"),
    "dionysius": ("Dionysius the Areopagite", "greek-patristic"), "dionys": ("Dionysius the Areopagite", "greek-patristic"),
    "damascene": ("John Damascene", "greek-patristic"), "damascenus": ("John Damascene", "greek-patristic"),
    "damasc": ("John Damascene", "greek-patristic"), "damas": ("John Damascene", "greek-patristic"),
    "cassian": ("John Cassian", "latin-patristic"), "haymo": ("Haymo of Halberstadt", "medieval"),
    "maximus": ("Maximus", "greek-patristic"), "faustus": ("Faustus", "patristic"),
    "anselm": ("Anselm", "medieval"), "paschasius": ("Paschasius Radbertus", "medieval"),
    "lanfranc": ("Lanfranc", "medieval"), "josephus": ("Josephus", "jewish"),
    "nemesius": ("Nemesius of Emesa", "greek-patristic"), "petrus alfonsus": ("Petrus Alfonsus", "medieval"),
    "the council of ephesus": ("Council of Ephesus", "conciliar"),
    "second council of constantinople": ("Second Council of Constantinople", "conciliar"),
}
# longest-first so multiword/specific aliases win over short prefixes (e.g. "gregory nyss" before "greg")
ALIAS_KEYS = sorted(AUTHORS, key=len, reverse=True)

def clean(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s).replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip()

def osis_ref(ch, v0, v1):
    if v0 == v1:
        return f"{BOOK_OSIS}.{ch}.{v0}", f"{BOOK_NAME} {ch}:{v0}"
    return f"{BOOK_OSIS}.{ch}.{v0}-{BOOK_OSIS}.{ch}.{v1}", f"{BOOK_NAME} {ch}:{v0}–{v1}"

def match_author(txt: str):
    """Return (author, tradition, work, comment) if the paragraph opens with a known Father, else None."""
    m = re.match(r"\s*\[?\s*([^:]{1,90}?):\s*(.*)", txt, re.S)
    if not m:
        return None
    attribution, comment = m.group(1).strip(), m.group(2).strip()
    low = attribution.lower()
    if low.startswith("gloss"):
        return ("Glossa Ordinaria", "medieval", attribution, comment)
    for k in ALIAS_KEYS:
        if low.startswith(k):
            nxt = low[len(k):len(k)+1]
            if nxt == "" or not nxt.isalpha():        # word boundary
                author, tradition = AUTHORS[k]
                work = attribution[len(k):].lstrip(" .,").strip()
                return (author, tradition, work, comment)
    return None

def main():
    raw = SRC.read_bytes().decode("utf-8", "replace")
    records = []
    flags = {"orphans_attached": 0, "continuations": 0, "dangling_continuations": 0,
             "unrecognized_lead": collections.Counter()}

    chap_spans = [(m.group(1), m.start()) for m in re.finditer(r'<div2\b[^>]*\btitle="Chapter (\d+)"[^>]*>', raw)]
    bounds = [s for _, s in chap_spans] + [len(raw)]

    for idx, (chap, start) in enumerate(chap_spans):
        ch = int(chap)
        body = raw[start:bounds[idx + 1]]
        cur_v0 = cur_v1 = None
        block_has_comments = False
        last_idx = None              # index in records for continuation append
        pending = []                 # comments seen before the first lemma in this chapter

        def emit(author, tradition, work, comment):
            refKey, refDisplay = osis_ref(ch, cur_v0, cur_v1)
            records.append({"refKey": refKey, "refDisplay": refDisplay,
                "book": BOOK_OSIS, "chapter": ch, "v_start": cur_v0, "v_end": cur_v1,
                "source": SOURCE_ID, "author": author, "tradition": tradition,
                "work": work, "text": comment, "provenanceUrl": f"{SOURCE_URL}#ii.{chap}"})
            return len(records) - 1

        for m in re.finditer(r'<p\b([^>]*)>(.*?)</p>|<hr\b[^>]*/?>', body, re.S):
            if m.group(0).startswith("<hr"):
                continue
            attrs, inner = m.group(1), m.group(2)
            cls = (re.search(r'class="([^"]*)"', attrs) or [None, ""])[1] if 'class="' in attrs else ""
            txt = clean(inner)
            if not txt:
                continue

            if "scripture" in cls:
                vm = re.match(r"(\d+)\.", txt)
                if not vm:
                    continue                       # wrapped continuation of a verse line
                v = int(vm.group(1))
                if cur_v0 is None:                 # first lemma of the chapter
                    cur_v0 = cur_v1 = v
                    for a, t, w, c in pending:     # flush pre-lemma orphans onto first block
                        last_idx = emit(a, t, w, c); flags["orphans_attached"] += 1
                    pending = []
                elif block_has_comments:           # verses resume after commentary -> NEW lemma block
                    cur_v0 = cur_v1 = v; block_has_comments = False; last_idx = None
                else:                              # consecutive verses -> extend current lemma
                    cur_v1 = v

            elif "normal" in cls:
                ma = match_author(txt)
                if ma:
                    author, tradition, work, comment = ma
                    if cur_v0 is None:
                        pending.append((author, tradition, work, comment))
                    else:
                        last_idx = emit(author, tradition, work, comment)
                        block_has_comments = True
                else:                              # continuation of the previous comment
                    if last_idx is not None:
                        records[last_idx]["text"] += " " + txt
                        flags["continuations"] += 1
                    else:
                        flags["dangling_continuations"] += 1
                    head = txt.split(":", 1)[0][:40]
                    if ":" in txt[:60] and len(head.split()) <= 4:
                        flags["unrecognized_lead"][head] += 1

    write_db(records); write_json(records); report(records, flags)

def write_db(records):
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.execute("DROP TABLE IF EXISTS reception")
    con.execute("""CREATE TABLE reception(
        id INTEGER PRIMARY KEY, refKey TEXT, refDisplay TEXT,
        book TEXT, chapter INT, v_start INT, v_end INT,
        source TEXT, author TEXT, tradition TEXT, work TEXT, text TEXT, provenanceUrl TEXT)""")
    con.executemany("""INSERT INTO reception
        (refKey,refDisplay,book,chapter,v_start,v_end,source,author,tradition,work,text,provenanceUrl)
        VALUES (:refKey,:refDisplay,:book,:chapter,:v_start,:v_end,:source,:author,:tradition,:work,:text,:provenanceUrl)""", records)
    con.execute("CREATE INDEX idx_overlap ON reception(book, chapter, v_start, v_end)")
    con.commit(); con.close()

def write_json(records):
    JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    JSON_OUT.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")

def resolve(book, ch, q0, q1):
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    rows = con.execute("""SELECT * FROM reception WHERE book=? AND chapter=? AND v_start<=? AND v_end>=?
                          ORDER BY v_start, id""", (book, ch, q1, q0)).fetchall()
    con.close(); return rows

def report(records, flags):
    by_ch = collections.Counter(r["chapter"] for r in records)
    by_auth = collections.Counter(r["author"] for r in records)
    unmapped = collections.Counter(r["author"] for r in records if r["tradition"] == "unmapped")
    print(f"\n=== Catena Aurea — Matthew: {len(records)} comment records across {len(by_ch)} chapters ===")
    print(f"distinct authors: {len(by_auth)} | continuations merged: {flags['continuations']} | "
          f"orphans attached: {flags['orphans_attached']} | dangling: {flags['dangling_continuations']}")
    print("top authors:", ", ".join(f"{a} {n}" for a, n in by_auth.most_common(10)))
    print("unmapped authors:", dict(unmapped) or "(none)")
    ul = flags["unrecognized_lead"]
    print(f"unrecognized name-like leads (review): {sum(ul.values())}", dict(ul.most_common(8)))
    # lemma-block sanity: chapter 20 distinct blocks
    blocks = sorted({(r["chapter"], r["v_start"], r["v_end"]) for r in records if r["chapter"] == 20})
    print("ch20 lemma blocks:", [f"{a}-{b}" for _, a, b in blocks])
    print("\n=== resolver demo: Matt 20:1-16 (laborers in the vineyard) ===")
    rows = resolve("Matt", 20, 1, 16)
    print(f"{len(rows)} comments resolve; authors:",
          ", ".join(f"{a}×{n}" for a, n in collections.Counter(r["author"] for r in rows).most_common()))
    print("\n--- first 3 verbatim (eyeball vs https://ccel.org/ccel/aquinas/catena1.ii.xx.html) ---")
    for r in rows[:3]:
        print(f"  [{r['refDisplay']}] {r['author']} ({r['work'] or 'no work'}) [{r['tradition']}]")
        print(f"    {r['text'][:230]}...")

if __name__ == "__main__":
    main()
