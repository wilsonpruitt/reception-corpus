#!/usr/bin/env python3.11
"""OSIS reference handling — Python mirror of Catena's lib/osis.ts (the canonical impl of the
Wroot data-repository-standard). refKey forms must match exactly so reception-corpus joins to
Catena's published echo data and to Lectern by verse range. Versification: KJV/WEB.

refKey grammar (from lib/osis.ts):
  single verse        Ps.110.1
  whole chapter       Ps.110
  same-chapter range  Ps.45.6-Ps.45.7
  cross-chapter range Exod.2.8-Exod.3.3
  chapter range       Exod.12-Exod.14
"""
from __future__ import annotations

OSIS_NAME = {
 "Gen":"Genesis","Exod":"Exodus","Lev":"Leviticus","Num":"Numbers","Deut":"Deuteronomy",
 "Josh":"Joshua","Judg":"Judges","Ruth":"Ruth","1Sam":"1 Samuel","2Sam":"2 Samuel",
 "1Kgs":"1 Kings","2Kgs":"2 Kings","1Chr":"1 Chronicles","2Chr":"2 Chronicles","Ezra":"Ezra",
 "Neh":"Nehemiah","Esth":"Esther","Job":"Job","Ps":"Psalms","Prov":"Proverbs","Eccl":"Ecclesiastes",
 "Song":"Song of Solomon","Isa":"Isaiah","Jer":"Jeremiah","Lam":"Lamentations","Ezek":"Ezekiel",
 "Dan":"Daniel","Hos":"Hosea","Joel":"Joel","Amos":"Amos","Obad":"Obadiah","Jonah":"Jonah",
 "Mic":"Micah","Nah":"Nahum","Hab":"Habakkuk","Zeph":"Zephaniah","Hag":"Haggai","Zech":"Zechariah",
 "Mal":"Malachi","Matt":"Matthew","Mark":"Mark","Luke":"Luke","John":"John","Acts":"Acts",
 "Rom":"Romans","1Cor":"1 Corinthians","2Cor":"2 Corinthians","Gal":"Galatians","Eph":"Ephesians",
 "Phil":"Philippians","Col":"Colossians","1Thess":"1 Thessalonians","2Thess":"2 Thessalonians",
 "1Tim":"1 Timothy","2Tim":"2 Timothy","Titus":"Titus","Phlm":"Philemon","Heb":"Hebrews","Jas":"James",
 "1Pet":"1 Peter","2Pet":"2 Peter","1John":"1 John","2John":"2 John","3John":"3 John","Jude":"Jude",
 "Rev":"Revelation",
 # deuterocanon
 "Tob":"Tobit","Jdt":"Judith","Wis":"Wisdom of Solomon","Sir":"Sirach","Bar":"Baruch","Sus":"Susanna",
 "1Macc":"1 Maccabees","2Macc":"2 Maccabees","3Macc":"3 Maccabees","4Macc":"4 Maccabees","2Esd":"2 Esdras",
 # extended (pseudepigrapha — outside OSIS core, flagged)
 "1En":"1 Enoch","2Bar":"2 Baruch","4Ezra":"4 Ezra","TJob":"Testament of Job","TLevi":"Testament of Levi",
 "Jub":"Jubilees","JanJam":"Jannes and Jambres","MartIsa":"Martyrdom of Isaiah","AsMos":"Assumption of Moses",
 "LAE":"Life of Adam and Eve",
}
EXTENDED = {"1En","2Bar","4Ezra","TJob","TLevi","Jub","JanJam","MartIsa","AsMos","LAE"}

def name(code: str) -> str:
    return OSIS_NAME.get(code, code)

def build_refkey(code, c1, v1=None, ec=None, ev=None):
    """Mirror lib/osis.ts toOsis(). ec/ev = end chapter/verse for ranges. v1/ev None => chapter-level."""
    if ec is None:
        if v1 is None:
            return f"{code}.{c1}"
        return f"{code}.{c1}.{v1}"
    if ev is not None:                                   # verse range
        return f"{code}.{c1}.{v1 if v1 is not None else 1}-{code}.{ec}.{ev}"
    return f"{code}.{c1}-{code}.{ec}"                    # chapter range

def display(code, c1, v1=None, ec=None, ev=None):
    nm = name(code)
    if ec is None:
        if v1 is None:
            return f"{nm} {c1}"
        return f"{nm} {c1}:{v1}"
    if ev is not None:
        return f"{nm} {c1}:{v1 or 1}–{ev}" if ec == c1 else f"{nm} {c1}:{v1 or 1}–{ec}:{ev}"
    return f"{nm} {c1}–{ec}"

def normalize_osisref(s: str) -> str:
    """CCEL osisRef ('Bible:Gen.1.1-2', 'Bible:Gen.1') -> canonical refKey form with both ends qualified."""
    s = s.split(":", 1)[-1].strip()
    if "-" in s:
        a, b = s.split("-", 1)
        if "." not in b:                                 # compact '...-2' => same-chapter end verse
            ac = a.split(".")
            if len(ac) >= 2:
                b = f"{ac[0]}.{ac[1]}.{b}"
        s = f"{a}-{b}"
    return s

def refkey_to_display(refKey: str) -> str:
    p = parse_refkey(refKey)
    code, c0, v0, c1, v1 = p["book"], p["chapter"], p["v_start"], p["c_end"], p["v_end_true"]
    if p["cross_chapter"]:
        if v0 == 0 and v1 == 0:
            return display(code, c0, None, c1, None)      # chapter range (Exod.12-Exod.14)
        return display(code, c0, v0, c1, v1)              # cross-chapter verse range
    if v0 == 0:
        return display(code, c0)                          # whole chapter
    if v1 == v0 or v1 == 0:
        return display(code, c0, v0)                      # single verse
    return display(code, c0, v0, c0, v1)                  # same-chapter range


def parse_refkey(refKey: str):
    """Parse a canonical refKey -> dict with start/end + storage columns.
    v_start/v_end use 0 for whole-chapter. Cross-chapter sets cross=True; v_end clamps to a
    rest-of-chapter sentinel for the (book,chapter,v_start,v_end) overlap index, while refKey
    stays exact for joins."""
    if not refKey:
        return None
    start, _, end = refKey.partition("-")
    sp = start.split(".")
    if len(sp) < 2 or not sp[1].isdigit():               # book-level / unparseable
        return {"book": sp[0], "chapter": 0, "v_start": 0, "v_end": 0,
                "c_end": 0, "v_end_true": 0, "cross_chapter": False,
                "extended": sp[0] in EXTENDED}
    book, c0 = sp[0], int(sp[1])
    v0 = int(sp[2]) if len(sp) > 2 else 0
    if not end:
        c1, v1 = c0, v0
    else:
        ep = end.split(".")
        if len(ep) == 1:                                 # bare end verse (shouldn't occur post-normalize)
            c1, v1 = c0, int(ep[0])
        else:
            c1 = int(ep[1]); v1 = int(ep[2]) if len(ep) > 2 else 0
    cross = c1 != c0
    v_end_col = (999 if v0 else 0) if cross else v1      # approx rest-of-chapter for cross-chapter
    return {"book": book, "chapter": c0, "v_start": v0, "v_end": v_end_col,
            "c_end": c1, "v_end_true": v1, "cross_chapter": cross,
            "extended": book in EXTENDED}
