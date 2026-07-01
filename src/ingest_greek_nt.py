#!/usr/bin/env python3.11
"""Ingest the MorphGNT SBLGNT tab files into the word-level Greek store (data/greek.sqlite,
table `greek_word`) and export a per-book JSON for the Lectern app.

This is the parsing layer — the open replacement for BibleHub's text page. Each MorphGNT row is
seven space-separated columns:

    bcv     pos parse     text        word       normalized  lemma
    030304  N-  ----NSF-  Φωνὴ        Φωνὴ       φωνή        φωνή

bcv is BBCCVV (book 01=Matthew … 27=Revelation, then 2-digit chapter + 2-digit verse). We key each
word on the shared OSIS single-verse refKey (Luke.3.4) via osis.build_refkey, expand the codes with
greek.py, and carry a `lexKey` (the lemma match key) so the lexicon layer can join.

Source (vendored, gitignored): cache/greek/morphgnt/*.txt
  MorphGNT SBLGNT — morphology/lemmas CC-BY-SA 3.0 (J. K. Tauber, ed.); SBLGNT text under its EULA.

Idempotent: rebuilds table + re-exports from whatever book tab files are present in cache
(pilot = Luke only). Run before ingest_greek_lexicon.py — it reads the lemma set this produces.
"""
from __future__ import annotations
import json, sqlite3
from pathlib import Path
import osis, greek

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "greek.sqlite"
SRC_DIR = ROOT / "cache" / "greek" / "morphgnt"
OUT_DIR = ROOT / "out" / "greek-nt"
PROVENANCE = "https://github.com/morphgnt/sblgnt (v6.12, CC-BY-SA morphology; SBLGNT text EULA)"

DDL = """
CREATE TABLE IF NOT EXISTS greek_word (
  refKey       TEXT NOT NULL,   -- OSIS single-verse key, e.g. Luke.3.4
  pos_in_verse INTEGER NOT NULL,
  book         TEXT NOT NULL,   -- OSIS book code
  chapter      INTEGER NOT NULL,
  verse        INTEGER NOT NULL,
  text         TEXT NOT NULL,   -- surface form with editorial marks/punctuation
  word         TEXT NOT NULL,   -- surface form, marks stripped
  normalized   TEXT NOT NULL,   -- accents normalised, lowercased
  lemma        TEXT NOT NULL,   -- dictionary citation form (Unicode polytonic)
  lexKey       TEXT NOT NULL,   -- greek.match_key(lemma) — join to greek_lexicon
  foldKey      TEXT NOT NULL,   -- greek.fold_key(lemma)  — accent-insensitive fallback
  pos          TEXT NOT NULL,   -- raw MorphGNT POS code
  parse        TEXT NOT NULL,   -- raw 8-slot parse code
  parseLabel   TEXT NOT NULL,   -- human morphology, e.g. 'noun · nominative singular feminine'
  PRIMARY KEY (refKey, pos_in_verse)
);
CREATE INDEX IF NOT EXISTS idx_word_lexkey ON greek_word(lexKey);
CREATE INDEX IF NOT EXISTS idx_word_book   ON greek_word(book);
"""


def parse_file(path: Path):
    """Yield word dicts from one MorphGNT book tab file, in document order per verse."""
    last_ref, pos_in_verse = None, 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        cols = line.split(" ")
        if len(cols) != 7:
            raise ValueError(f"{path.name}: expected 7 cols, got {len(cols)}: {line!r}")
        bcv, pos, parse, text, word, norm, lemma = cols
        bnum, chap, verse = int(bcv[0:2]), int(bcv[2:4]), int(bcv[4:6])
        code = greek.NT_BOOK_OSIS[bnum]
        refKey = osis.build_refkey(code, chap, verse)
        pos_in_verse = pos_in_verse + 1 if refKey == last_ref else 0
        last_ref = refKey
        yield {
            "refKey": refKey, "pos_in_verse": pos_in_verse,
            "book": code, "chapter": chap, "verse": verse,
            "text": text, "word": word, "normalized": norm, "lemma": lemma,
            "lexKey": greek.match_key(lemma), "foldKey": greek.fold_key(lemma),
            "pos": pos, "parse": parse, "parseLabel": greek.morph_label(pos, parse),
        }


def export_book(con: sqlite3.Connection, code: str):
    """Write out/greek-nt/<code>.json — verses in order, each an ordered word list (no gloss;
    the lexicon layer supplies inline glosses separately so the two ingests stay independent)."""
    rows = con.execute(
        "SELECT refKey, chapter, verse, pos_in_verse, text, word, lemma, lexKey, foldKey, "
        "pos, parse, parseLabel FROM greek_word WHERE book=? "
        "ORDER BY chapter, verse, pos_in_verse", (code,)).fetchall()
    verses: dict[str, dict] = {}
    for r in rows:
        (refKey, chapter, verse, piv, text, word, lemma, lexKey, foldKey, pos, parse, label) = r
        v = verses.setdefault(refKey, {"refKey": refKey, "refDisplay": osis.refkey_to_display(refKey),
                                       "chapter": chapter, "verse": verse, "words": []})
        v["words"].append({"i": piv, "text": text, "word": word, "lemma": lemma,
                           "lexKey": lexKey, "foldKey": foldKey, "pos": pos, "parse": parse,
                           "morph": label})
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = {"book": code, "bookName": osis.name(code), "source": PROVENANCE,
           "verses": list(verses.values())}
    (OUT_DIR / f"{code}.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(verses), len(rows)


def main():
    files = sorted(SRC_DIR.glob("*-morphgnt.txt"))
    if not files:
        raise SystemExit(f"no MorphGNT files in {SRC_DIR}")
    con = sqlite3.connect(DB)
    con.executescript(DDL)
    con.execute("DELETE FROM greek_word")
    books = []
    for f in files:
        rows = list(parse_file(f))
        code = rows[0]["book"]
        con.executemany(
            "INSERT INTO greek_word (refKey,pos_in_verse,book,chapter,verse,text,word,"
            "normalized,lemma,lexKey,foldKey,pos,parse,parseLabel) VALUES "
            "(:refKey,:pos_in_verse,:book,:chapter,:verse,:text,:word,:normalized,:lemma,"
            ":lexKey,:foldKey,:pos,:parse,:parseLabel)", rows)
        con.commit()
        books.append(code)
        print(f"  {f.name}: {len(rows):>6} words  ({code})")
    for code in books:
        nv, nw = export_book(con, code)
        print(f"  export {code}.json: {nv} verses, {nw} words")
    total = con.execute("SELECT COUNT(*) FROM greek_word").fetchone()[0]
    lemmas = con.execute("SELECT COUNT(DISTINCT lexKey) FROM greek_word").fetchone()[0]
    con.close()
    print(f"greek_word: {total} words, {lemmas} distinct lemmas across {len(books)} book(s)")


if __name__ == "__main__":
    main()
