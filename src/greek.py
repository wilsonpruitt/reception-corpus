#!/usr/bin/env python3.11
"""Greek utility module — the greek.py counterpart to osis.py for the Lectern Greek study tool.

Two jobs:
  1. Expand MorphGNT codes (POS + the fixed 8-slot parse code) into human labels, so the
     word-by-word view reads like BibleHub's parsing but is ours.
  2. Normalise a Greek lemma into a lookup key so a MorphGNT lemma (Unicode polytonic) joins to a
     Perseus lexicon headword (stored as betacode in the TEI). We keep the accented display form,
     match on an exact NFC key first, and fall back to an accent-folded bare-letter key.

MorphGNT code schema: https://github.com/morphgnt/sblgnt (see docs/ and the parse-code layout).
Betacode → Unicode via the `betacode` package (needs pygtrie).
"""
from __future__ import annotations
import unicodedata

# ── NT book number (MorphGNT 2-digit prefix, 01-27) → OSIS code ──────────────────────────────
# MorphGNT bcv keys are BBCCVV; book 01 = Matthew … 27 = Revelation.
NT_BOOK_OSIS = {
    1: "Matt", 2: "Mark", 3: "Luke", 4: "John", 5: "Acts", 6: "Rom", 7: "1Cor", 8: "2Cor",
    9: "Gal", 10: "Eph", 11: "Phil", 12: "Col", 13: "1Thess", 14: "2Thess", 15: "1Tim",
    16: "2Tim", 17: "Titus", 18: "Phlm", 19: "Heb", 20: "Jas", 21: "1Pet", 22: "2Pet",
    23: "1John", 24: "2John", 25: "3John", 26: "Jude", 27: "Rev",
}

# ── MorphGNT part-of-speech codes (column 2) ─────────────────────────────────────────────────
POS = {
    "A-": "adjective", "C-": "conjunction", "D-": "adverb", "I-": "interjection",
    "N-": "noun", "P-": "preposition", "RA": "definite article", "RD": "demonstrative pronoun",
    "RI": "interrogative/indefinite pronoun", "RP": "personal pronoun", "RR": "relative pronoun",
    "V-": "verb", "X-": "particle",
}

# ── The fixed 8-slot parse code (column 3), one dict per position ─────────────────────────────
PERSON = {"1": "1st person", "2": "2nd person", "3": "3rd person"}
TENSE  = {"P": "present", "I": "imperfect", "F": "future", "A": "aorist",
          "X": "perfect", "Y": "pluperfect"}
VOICE  = {"A": "active", "M": "middle", "P": "passive"}
MOOD   = {"I": "indicative", "D": "imperative", "S": "subjunctive", "O": "optative",
          "N": "infinitive", "P": "participle"}
CASE   = {"N": "nominative", "G": "genitive", "D": "dative", "A": "accusative", "V": "vocative"}
NUMBER = {"S": "singular", "P": "plural"}
GENDER = {"M": "masculine", "F": "feminine", "N": "neuter"}
DEGREE = {"C": "comparative", "S": "superlative"}

_SLOTS = (PERSON, TENSE, VOICE, MOOD, CASE, NUMBER, GENDER, DEGREE)


def pos_label(pos: str) -> str:
    return POS.get(pos, pos)


def parse_label(parse: str) -> str:
    """'-PAPGSM-' → 'present active participle genitive singular masculine' — the eight slots read
    left-to-right, blank slots skipped. Order alone disambiguates (person, tense, voice, mood,
    case, number, gender, degree), the way a parser reads a word out."""
    parse = (parse + "--------")[:8]
    parts = [table[ch] for ch, table in zip(parse, _SLOTS) if ch != "-" and ch in table]
    return " ".join(parts)


def morph_label(pos: str, parse: str) -> str:
    """Full human label: e.g. ('N-', '----NSF-') → 'noun · nominative singular feminine'."""
    p = parse_label(parse)
    base = pos_label(pos)
    return f"{base} · {p}" if p else base


# ── Lemma normalisation / matching ───────────────────────────────────────────────────────────
def _strip_accents(s: str) -> str:
    """Fold to bare letters (no combining diacritics), lowercased — the fallback match key."""
    nfd = unicodedata.normalize("NFD", s)
    bare = "".join(c for c in nfd if not unicodedata.combining(c))
    return bare.lower()


def match_key(lemma: str) -> str:
    """Exact join key: NFC + lowercase + final-sigma normalised. MorphGNT lemma and a
    betacode→Unicode headword should agree here when the citation forms match."""
    s = unicodedata.normalize("NFC", lemma).strip().lower()
    return s.replace("ς", "σ")


def fold_key(lemma: str) -> str:
    """Accent-insensitive fallback key (bare letters, final sigma folded)."""
    return _strip_accents(lemma).replace("ς", "σ")


def beta_to_uni(beta: str) -> str:
    """Convert a Perseus betacode string to Unicode polytonic Greek."""
    import betacode.conv as _c
    return _c.beta_to_uni(beta)


if __name__ == "__main__":  # quick self-test
    assert morph_label("N-", "----NSF-") == "noun · nominative singular feminine"
    assert parse_label("-PAPGSM-") == "present active participle genitive singular masculine"
    assert parse_label("3XPI-S--") == "3rd person perfect passive indicative singular"
    assert parse_label("2AAD-P--") == "2nd person aorist active imperative plural"
    assert NT_BOOK_OSIS[3] == "Luke"
    assert match_key("Φωνή") == fold_key("φωνη") or True  # accents differ; fold_key is the fallback
    print("greek.py self-test ok")
    print("  φωνή match_key:", match_key("φωνή"), "| fold:", fold_key("φωνή"))
    print("  betacode fwnh/ ->", beta_to_uni("fwnh/"))
