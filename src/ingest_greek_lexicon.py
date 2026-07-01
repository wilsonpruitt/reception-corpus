#!/usr/bin/env python3.11
"""Ingest the Perseus classical lexica (Middle Liddell + full LSJ) for the words that actually
occur in the Greek NT, into data/greek.sqlite (table `greek_lexicon`), and export the app JSON.

This is the definition layer — the open, *classical* replacement for Logeion (not a Bible
dictionary). We scope storage to NT-occurring lemmas (read from greek_word), so the store stays
small and every entry is one a preacher will actually meet in the text. Lemmas with no classical
entry fall out as the unmatched report — expected and informative (proper nouns, Koine-only words).

Matching: MorphGNT lemmas are Unicode polytonic; Perseus headwords are betacode in the TEI `key`
attribute. We convert betacode→Unicode (greek.beta_to_uni), then join on greek.match_key (exact,
accent-sensitive) with a greek.fold_key fallback (accent-insensitive).

Sources (vendored, gitignored):
  cache/greek/perseus/middle-liddell.xml   — Middle Liddell, CC-BY-SA 3.0 US (Perseus/blinskey)
  cache/greek/perseus/lsj-eng*.xml         — LSJ, CC-BY-SA (PerseusDL/lexica)

Run AFTER ingest_greek_nt.py. Idempotent: rebuilds greek_lexicon and re-exports.
"""
from __future__ import annotations
import json, re, sqlite3, html, shutil
from pathlib import Path
import xml.etree.ElementTree as ET
import greek

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "greek.sqlite"
PERSEUS = ROOT / "cache" / "greek" / "perseus"
OUT_DIR = ROOT / "out" / "greek-lexicon"
ENTRY_DIR = OUT_DIR / "entries"

SOURCES = {
    "midliddell": {"label": "Middle Liddell", "prov": "Perseus (blinskey mirror), CC-BY-SA 3.0 US"},
    "lsj": {"label": "Liddell-Scott-Jones", "prov": "PerseusDL/lexica, CC-BY-SA"},
}

DDL = """
CREATE TABLE IF NOT EXISTS greek_lexicon (
  lexKey     TEXT NOT NULL,   -- greek.match_key of the headword (join to greek_word.lexKey)
  source     TEXT NOT NULL,   -- 'midliddell' | 'lsj'
  headword   TEXT NOT NULL,   -- Unicode polytonic citation form
  short_gloss TEXT NOT NULL,  -- concise gloss for inline display
  entry_html TEXT NOT NULL,   -- rendered entry
  PRIMARY KEY (lexKey, source)
);
"""

# ── betacode-aware TEI → HTML rendering ──────────────────────────────────────────────────────
_GREEK_LANGS = {"greek", "grc"}


def _beta(s: str) -> str:
    if not s:
        return ""
    try:
        return greek.beta_to_uni(s)
    except Exception:
        return s


def _render(el: ET.Element, lang: str, tr_out: list) -> str:
    """Recursively serialise a TEI element to lightweight HTML. `lang` is the inherited language
    context; text inside a greek-tagged element is betacode and gets converted. Translations
    (<tr>) are collected into tr_out so the caller can build a short gloss."""
    tag = el.tag
    my_lang = el.get("lang", lang)
    conv = _beta if my_lang in _GREEK_LANGS else (lambda s: s)

    open_html, close_html = "", ""
    if tag == "orth":
        open_html, close_html = "<b>", "</b>"
    elif tag == "tr":
        open_html, close_html = '<i class="tr">', "</i>"
    elif tag in ("foreign", "ref", "quote") and my_lang in _GREEK_LANGS:
        open_html, close_html = "<span class='grk'>", "</span>"
    elif tag == "sense":
        n = el.get("n") or ""
        lvl = el.get("level") or "0"
        open_html = f'<div class="sense lvl{html.escape(lvl)}">' + (f'<span class="sn">{html.escape(n)}.</span> ' if n else "")
        close_html = "</div>"

    parts = [open_html]
    if el.text and el.text.strip():
        parts.append(html.escape(conv(el.text)))
    for child in el:
        parts.append(_render(child, my_lang, tr_out))
        if child.tail and child.tail.strip():
            parts.append(html.escape(conv(child.tail)))
    parts.append(close_html)

    if tag == "tr" and el.text:
        tr_out.append(conv(el.text).strip())
    return "".join(parts)


def render_entry(el: ET.Element):
    """→ (headword_unicode, short_gloss, entry_html)."""
    orth = el.find(".//orth")
    hw = _beta(orth.text) if orth is not None and orth.text else _beta(el.get("key", ""))
    tr_out: list[str] = []
    body = _render(el, el.get("lang", ""), tr_out)
    # short gloss: first couple of distinct translations, capped
    seen, glosses = set(), []
    for t in tr_out:
        t = re.sub(r"\s+", " ", t).strip(" ,;")
        if t and t.lower() not in seen:
            seen.add(t.lower()); glosses.append(t)
        if len(glosses) >= 3:
            break
    gloss = "; ".join(glosses)[:140]
    return hw, gloss, body


# ── entry iteration per source ───────────────────────────────────────────────────────────────
def iter_entries(path: Path, tag: str):
    raw = path.read_text(encoding="utf-8")
    raw = re.sub(r"<!DOCTYPE.*?\]>", "", raw, flags=re.DOTALL)
    root = ET.fromstring(raw)
    for el in root.iter(tag):
        key = el.get("key")
        if key:
            yield el, key


def collect(want_exact: set, want_fold: dict):
    """Scan both lexica; return {(lexKey, source): (headword, gloss, html)} for NT lemmas.
    want_exact = set of match_keys; want_fold = {fold_key: match_key} for the fallback."""
    # (target_lexKey, source) -> {"quality": 0|1, "items": [(headword, gloss, html), ...]}
    # Homographs (o(do/s1 "threshold" / o(do/s2 "way") share a key — we MERGE all exact matches so
    # the panel shows every classical sense, rather than gambling on one. Fold matches are a
    # last-resort single fallback used only when no exact entry exists.
    found: dict[tuple, dict] = {}
    plan = [("midliddell", [PERSEUS / "middle-liddell.xml"], "entry")]
    plan.append(("lsj", sorted(PERSEUS.glob("lsj-eng*.xml"),
                               key=lambda p: int(re.search(r"eng(\d+)", p.name)[1])), "entryFree"))
    for source, files, tag in plan:
        for f in files:
            for el, key in iter_entries(f, tag):
                key = re.sub(r"\d+$", "", key)      # Perseus appends 1/2/3 for homographs (o(do/s1)
                hw_uni = _beta(key)
                mk = greek.match_key(hw_uni)
                if mk in want_exact:
                    target, quality = mk, 0
                else:
                    fk = greek.fold_key(hw_uni)
                    if fk not in want_fold:
                        continue
                    target, quality = want_fold[fk], 1
                slot = found.get((target, source))
                if slot is None:
                    slot = found[(target, source)] = {"quality": quality, "items": []}
                elif quality > slot["quality"]:
                    continue                         # exact already present; skip weaker fold
                elif quality < slot["quality"]:      # exact supersedes a provisional fold
                    slot["quality"], slot["items"] = quality, []
                if slot["quality"] == 1 and slot["items"]:
                    continue                         # only one fold entry ever
                slot["items"].append(render_entry(el))
        hits = sum(1 for (t, s) in found if s == source)
        print(f"  {source}: matched {hits} NT lemmas from {len(files)} file(s)")
    return {slot: _merge(rec["items"]) for slot, rec in found.items()}


def _merge(items: list):
    """Merge one-or-more homograph entries into a single (headword, gloss, html)."""
    headword = items[0][0]
    # combine glosses across homographs, dedup, cap
    seen, glosses = set(), []
    for _, g, _ in items:
        for piece in g.split("; "):
            p = piece.strip()
            if p and p.lower() not in seen:
                seen.add(p.lower()); glosses.append(p)
    gloss = "; ".join(glosses)[:160]
    if len(items) == 1:
        html_out = items[0][2]
    else:
        html_out = "".join(f'<div class="homograph"><span class="hn">{i}.</span>{h}</div>'
                           for i, (_, _, h) in enumerate(items, 1))
    return headword, gloss, html_out


def main():
    con = sqlite3.connect(DB)
    con.executescript(DDL)
    con.execute("DELETE FROM greek_lexicon")

    lemmas = con.execute(
        "SELECT DISTINCT lexKey, foldKey, lemma FROM greek_word").fetchall()
    want_exact = {lk for lk, fk, lm in lemmas}
    want_fold = {fk: lk for lk, fk, lm in lemmas}   # fold→exact (last wins; fine for fallback)
    lemma_display = {lk: lm for lk, fk, lm in lemmas}
    print(f"NT lemmas to look up: {len(want_exact)}")

    found = collect(want_exact, want_fold)
    for (lexKey, source), (hw, gloss, body) in found.items():
        con.execute("INSERT INTO greek_lexicon (lexKey,source,headword,short_gloss,entry_html) "
                    "VALUES (?,?,?,?,?)", (lexKey, source, hw, gloss, body))
    con.commit()

    # ── exports ──
    if ENTRY_DIR.exists():
        shutil.rmtree(ENTRY_DIR)                     # drop stale entries (renames, dropped lemmas)
    ENTRY_DIR.mkdir(parents=True, exist_ok=True)
    short = {}
    matched_keys = set()
    for lexKey in sorted(want_exact):
        ml = con.execute("SELECT headword,short_gloss,entry_html FROM greek_lexicon WHERE lexKey=? AND source='midliddell'", (lexKey,)).fetchone()
        lsj = con.execute("SELECT headword,short_gloss,entry_html FROM greek_lexicon WHERE lexKey=? AND source='lsj'", (lexKey,)).fetchone()
        if not ml and not lsj:
            continue
        matched_keys.add(lexKey)
        headword = (ml or lsj)[0]
        gloss = (ml[1] if ml and ml[1] else (lsj[1] if lsj else "")) or ""
        if gloss:
            short[lexKey] = gloss
        entry = {
            "lexKey": lexKey, "headword": headword, "lemma": lemma_display.get(lexKey),
            "midliddell": {"gloss": ml[1], "html": ml[2]} if ml else None,
            "lsj": {"gloss": lsj[1], "html": lsj[2]} if lsj else None,
        }
        # Filename is an ASCII slug (hex of NFC-UTF8 bytes) — Greek filenames don't survive
        # Vercel static routing. The client computes the same slug to fetch. See greek.lex_slug.
        (ENTRY_DIR / f"{greek.lex_slug(lexKey)}.json").write_text(
            json.dumps(entry, ensure_ascii=False), encoding="utf-8")

    (OUT_DIR / "short-glosses.json").write_text(
        json.dumps(short, ensure_ascii=False, indent=0), encoding="utf-8")

    unmatched = sorted((lemma_display[lk], lk) for lk in want_exact if lk not in matched_keys)
    (OUT_DIR / "_unmatched.json").write_text(
        json.dumps([{"lemma": lm, "lexKey": lk} for lm, lk in unmatched],
                   ensure_ascii=False, indent=1), encoding="utf-8")

    con.close()
    n = len(want_exact)
    print(f"matched {len(matched_keys)}/{n} lemmas ({100*len(matched_keys)//n}%), "
          f"{len(unmatched)} unmatched → _unmatched.json")
    print(f"exports: {len(list(ENTRY_DIR.glob('*.json')))} entry files, "
          f"{len(short)} short glosses")


if __name__ == "__main__":
    main()
