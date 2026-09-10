#!/usr/bin/env python3.11
"""Ingest the Glossa ordinaria (Migne recension, PL 113-114) into the reception store as
source='glossa-ordinaria' (mode='text') -- one row per `VERS. n.--` address, modelled on
ingest_wesley_notes.py.

Source: ~/patrologia/src/english/<idno>/NNNN.md, the in-house English of Migne's abridged
19th-c. recension. 56 texts (idno set below), all fully Englished (866/866 chunks verified
2026-09-10). Excludes idno 9003 (a separate exposition on Ps 1-20, not the Glossa) and 9004
(the four-Gospel harmony, not verse-keyed to one book) -- see docs/PLAN-inline-sources.md
Phase 1.

Two things make this harder than the Wesley ingest:
  1. Chapter state must carry ACROSS chunk files in filename order -- a chunk can open
     mid-chapter, and only its own `## HEADING` lines are in that chunk.
  2. Migne's Psalms are VULGATE-numbered. We convert to Hebrew/OSIS numbering. The four
     merge/split points (Vulg 9=Heb9+10, Vulg113=Heb114+115, Vulg114-115=Heb116,
     Vulg146-147=Heb147) cannot be verse-split from the English text alone except where
     Migne prints an explicit "PSALM N.-- *According to the Hebrews.*" sub-heading (this
     occurs at the 9/10 boundary and gives the Hebrew number directly). Elsewhere at those
     four points we do NOT guess a verse-level split: the whole Vulgate psalm's `VERS.`
     entries are inserted under a SINGLE Hebrew anchor chapter (113->114, 114->116,
     115->116, 146->147, 147->147) and the row is tagged with anchor suffix "~approx" so a
     reader landing on (say) Heb Ps 115 via this route actually sees Vulg 113's full
     content starting at Heb 114. This is a known, disclosed imprecision, not a silent one.

Run `--report` first (per-book: chunks read, VERS entries found/mapped, ambiguous-heading
skips, and a lemma-match ratio against WEB/KJV text) before `--insert`. See Phase 1's gate.

Idempotent: deletes source='glossa-ordinaria' then re-inserts.
"""
from __future__ import annotations
import argparse, json, random, re, sqlite3, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import osis

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "reception.sqlite"
PATROLOGIA = Path.home() / "patrologia"
ENGLISH = PATROLOGIA / "src" / "english"
KJV_DIR = Path.home() / "kjv-wesley" / "data" / "kjv"
CATENA_DATA = Path.home() / "catena" / "data"
OT_CHAPTERS = CATENA_DATA / "ot-chapters.json"
OT_CHAPTERS_DEUTERO = CATENA_DATA / "ot-chapters-deutero.json"

SOURCE_ID = "glossa-ordinaria"
AUTHOR = "Glossa Ordinaria"
TRADITION = "medieval"
WORK = "Glossa ordinaria (Migne recension, PL 113\u2013114)"
SITE = "https://patrologia.wrootpress.com"

EXCLUDED_IDNOS = {"9003", "9004"}

# idno -> OSIS code. Built from ~/patrologia/data/works.json's 56 Glossa-set texts
# (author == "Anselmus Laudunensis et schola", minus EXCLUDED_IDNOS), matched by hand
# against scripts/build-glossa.mjs's ORDER table (the site's own biblical-order map).
IDNO_TO_CODE = {
    "8950": "Gen", "8949": "Exod", "8961": "Lev", "8963": "Num", "8945": "Deut",
    "8958": "Josh", "8959": "Judg", "8968": "Ruth",
    "8952": "1Sam", "8953": "2Sam", "8954": "1Kgs", "8955": "2Kgs",
    "8964": "1Chr", "8965": "2Chr", "8951": "Ezra", "8962": "Neh",
    "8970": "Tob", "8960": "Jdt", "8948": "Esth", "8957": "Job",
    "8967": "Ps",  # special-cased (Vulgate numbering)
    "8966": "Prov", "8946": "Eccl", "8944": "Song",
    "8969": "Wis", "8947": "Sir",
    "8956": "Isa", "9006": "Jer", "9005": "Bar",
    "9002": "Matt", "9001": "Mark", "9000": "Luke", "8999": "John",
    "8976": "Acts", "8996": "Rom", "8981": "1Cor", "8986": "2Cor",
    "8992": "Gal", "8991": "Eph", "8995": "Phil", "8990": "Col",
    "8982": "1Thess", "8987": "2Thess", "8983": "1Tim", "8988": "2Tim",
    "8997": "Titus", "8994": "Phlm", "8993": "Heb", "8998": "Jas",
    "8980": "1Pet", "8985": "2Pet", "8979": "1John", "8984": "2John",
    "8989": "3John", "8978": "Jude", "8977": "Rev",
}

VOLUME = {**{k: 113 for k in list(IDNO_TO_CODE)[:23]}}  # overwritten precisely below
VOLUME_BY_IDNO = {  # from works.json, needed for the site URL
    "8944": 113, "8945": 113, "8946": 113, "8947": 113, "8948": 113, "8949": 113,
    "8950": 113, "8951": 113, "8952": 113, "8953": 113, "8954": 113, "8955": 113,
    "8956": 113, "8957": 113, "8958": 113, "8959": 113, "8960": 113, "8961": 113,
    "8962": 113, "8963": 113, "8964": 113, "8965": 113, "8966": 113, "8967": 113,
    "8968": 113, "8969": 113, "8970": 113,
    "8976": 114, "8977": 114, "8978": 114, "8979": 114, "8980": 114, "8981": 114,
    "8982": 114, "8983": 114, "8984": 114, "8985": 114, "8986": 114, "8987": 114,
    "8988": 114, "8989": 114, "8990": 114, "8991": 114, "8992": 114, "8993": 114,
    "8994": 114, "8995": 114, "8996": 114, "8997": 114, "8998": 114, "8999": 114,
    "9000": 114, "9001": 114, "9002": 114, "9005": 114, "9006": 114,
}

TITLE_BY_IDNO = {
    "8944": "Canticum Canticorum", "8945": "Liber Deuteronomii", "8946": "Liber Ecclesiastes",
    "8947": "Liber Ecclesiasticus", "8948": "Liber Esther", "8949": "Liber Exodus",
    "8950": "Liber Genesis", "8951": "Liber I Esdrae", "8952": "Liber I Regum",
    "8953": "Liber II Regum", "8954": "Liber III Regum", "8955": "Liber IV Regum",
    "8956": "Liber Isaiae prophetae", "8957": "Liber Job", "8958": "Liber Josue Ben Nun",
    "8959": "Liber Judicum", "8960": "Liber Judith", "8961": "Liber Leviticus",
    "8962": "Liber Nehemiae", "8963": "Liber Numeri", "8964": "Liber Paralipomenon I",
    "8965": "Liber Paralipomenon II", "8966": "Liber Proverbiorum", "8967": "Liber Psalmorum",
    "8968": "Liber Ruth", "8969": "Liber Sapientiae", "8970": "Liber Tobiae",
    "8976": "Actus Apostolorum", "8977": "Apocalypsis B. Joannis",
    "8978": "Epistola Catholica Judae", "8979": "Epistola I B. Joannis",
    "8980": "Epistola I B. Petri", "8981": "Epistola I ad Corinthios",
    "8982": "Epistola I ad Thessalonicenses", "8983": "Epistola I ad Timotheum",
    "8984": "Epistola II B. Joannis", "8985": "Epistola II B. Petri",
    "8986": "Epistola II ad Corinthios", "8987": "Epistola II ad Thessalonicenses",
    "8988": "Epistola II ad Timotheum", "8989": "Epistola III B. Joannis",
    "8990": "Epistola ad Colossenses", "8991": "Epistola ad Ephesios",
    "8992": "Epistola ad Galatas", "8993": "Epistola ad Hebraeos",
    "8994": "Epistola ad Philemonem", "8995": "Epistola ad Philippenses",
    "8996": "Epistola ad Romanos", "8997": "Epistola ad Titum",
    "8998": "Epistola canonica B. Jacobi", "8999": "Evangelium secundum Joannem",
    "9000": "Evangelium secundum Lucam", "9001": "Evangelium secundum Marcum",
    "9002": "Evangelium secundum Matthaeum", "9005": "Prophetia Baruch",
    "9006": "Prophetia Jeremiae",
}

assert set(IDNO_TO_CODE) == set(VOLUME_BY_IDNO) == set(TITLE_BY_IDNO), \
    "IDNO_TO_CODE / VOLUME_BY_IDNO / TITLE_BY_IDNO must cover exactly the same 56 idnos"

# --- Roman numerals -----------------------------------------------------------------
_ROMAN = [("M", 1000), ("CM", 900), ("D", 500), ("CD", 400), ("C", 100), ("XC", 90),
          ("L", 50), ("XL", 40), ("X", 10), ("IX", 9), ("V", 5), ("IV", 4), ("I", 1)]


def roman_to_int(s: str) -> int | None:
    s = s.upper().strip().rstrip(".")
    if not s or not re.fullmatch(r"[IVXLCDM]+", s):
        return None
    n, i = 0, 0
    for sym, val in _ROMAN:
        while s[i:i + len(sym)] == sym:
            n += val
            i += len(sym)
    return n if i == len(s) else None


# --- Vulgate -> Hebrew psalm numbering -----------------------------------------------
# Standard concordance. The four books at the merge/split seams (9, 113, 114, 115, 146,
# 147) get a single anchor chapter and an "~approx" anchor tag -- see module docstring.
APPROX_PSALM_SEAMS = {113, 114, 115, 146, 147}


def vulg_psalm_to_heb(n: int) -> int:
    if n <= 8:
        return n
    if n == 9:
        return 9          # the Heb-10 portion is separately headed "secundum Hebraeos"
    if n <= 112:
        return n + 1       # 10..112 -> 11..113
    if n == 113:
        return 114          # approx: covers Heb 114 AND the start of Heb 115
    if n in (114, 115):
        return 116          # approx: both halves of the Heb 116 merge
    if n <= 145:
        return n + 1        # 116..145 -> 117..146
    if n in (146, 147):
        return 147          # approx: both halves of the Heb 147 merge
    return n                # 148..150 unchanged


# --- Heading parsing ------------------------------------------------------------------
HEAD_RE = re.compile(r"^##\s+(.+?)\s*$", re.M)

# "CHAPTER II." / "CHAP. XLIV." / "CHAPTER ONE." / "THE ONLY CHAPTER."  (+ "(cont.)")
CHAPTER_RE = re.compile(
    r"^(?:CHAPTER|CHAP\.)\s+([IVXLCDM]+|ONE)\.?(?:\s*\(cont\.\))?$"
    r"|^THE ONLY CHAPTER\.?(?:\s*\(cont\.\))?$", re.I)
# "PSALM C." / "PSAL. LXXVIII." / "PSALMUS X." / "PSALM ONE."  (+ Hebrews suffix / cont.)
PSALM_RE = re.compile(
    r"^PSAL(?:M|MUS|\.)?\s+([IVXLCDM]+|ONE)\.?"
    r"(?:\s*--\s*\*(?:According to the Hebrews|Secundum Hebraeos)\.\*)?"
    r"(?:\s*\(cont\.\))?$", re.I)
HEBREWS_SUFFIX_RE = re.compile(r"according to the hebrews|secundum hebraeos", re.I)
COMBINED_CHAPTERS_RE = re.compile(r"^CHAPTERS\b", re.I)  # e.g. "CHAPTERS XLII, XLIII."

VERS_RE = re.compile(
    r"VERS\.\s*((?:[0-9]+(?:\s*[,\-]\s*[0-9]+)*)?)\.?\s*--", re.I)

NOTE_N_RE = re.compile(r"\[n:\s*(.*?)\]", re.S)
NOTE_VAR_RE = re.compile(r"\[var:\s*.*?\]", re.S)
NOTE_OTHER_RE = re.compile(r"\[(?:cj|d|ed|nt|sic):\s*(.*?)\]", re.S)
COLUMN_RE = re.compile(r"\[(\d{4}[A-D])\]")


def clean_text(s: str) -> tuple[str, str | None]:
    """-> (cleaned text, first column anchor seen or None)."""
    m = COLUMN_RE.search(s)
    anchor = m.group(1) if m else None
    s = NOTE_VAR_RE.sub("", s)
    s = NOTE_N_RE.sub(lambda m: f"({m.group(1).strip()})", s)
    s = NOTE_OTHER_RE.sub(lambda m: m.group(1).strip(), s)
    s = COLUMN_RE.sub("", s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip(), anchor


def parse_vers_list(numlist: str) -> tuple[int, int] | None:
    if not numlist.strip():
        return None
    nums = [int(x) for x in re.split(r"[,\-]", numlist) if x.strip()]
    if not nums:
        return None
    return min(nums), max(nums)


# --- Per-work parsing -------------------------------------------------------------------
class Skip:
    def __init__(self):
        self.counts: dict[str, int] = {}

    def add(self, reason: str, n: int = 1):
        self.counts[reason] = self.counts.get(reason, 0) + n


def parse_work(idno: str, code: str, skip: Skip):
    """-> list of dicts {chapter, v_start, v_end, text, anchor}"""
    d = ENGLISH / idno
    files = sorted(d.glob("[0-9][0-9][0-9][0-9].md"))
    entries: list[dict] = []
    chapter = None           # current OSIS chapter (already Heb-converted for Psalms)
    approx = False            # current chapter is an approx psalm-seam anchor
    cur_key = None            # (chapter,) key of the entry currently being appended to
    n_vers = 0

    for f in files:
        raw = f.read_text(encoding="utf-8")
        body = raw.split("---", 2)[-1] if raw.startswith("---") else raw
        # split into (heading, block) segments; text before the first heading in a
        # chunk continues whatever heading was open at the end of the PREVIOUS chunk.
        pieces = HEAD_RE.split(body)
        # pieces = [pre, head1, block1, head2, block2, ...]
        segs = [(None, pieces[0])] + list(zip(pieces[1::2], pieces[2::2]))
        for head, block in segs:
            if head is not None:
                is_cont = bool(re.search(r"\(cont\.\)\s*$", head, re.I))
                if COMBINED_CHAPTERS_RE.match(head):
                    skip.add("combined-chapters-heading")
                    chapter, cur_key = None, None
                    continue
                new_chapter = new_approx = None
                m = CHAPTER_RE.match(head)
                if m and code != "Ps":
                    g = m.group(1)
                    new_chapter = 1 if (g and g.upper() == "ONE") else roman_to_int(g or "")
                    if new_chapter is None and "ONLY CHAPTER" in head.upper():
                        new_chapter = 1
                    new_approx = False
                if new_chapter is None:
                    m2 = PSALM_RE.match(head)
                    if m2 and code == "Ps":
                        g = m2.group(1)
                        num = 1 if (g and g.upper() == "ONE") else roman_to_int(g or "")
                        if num is None:
                            skip.add("unparsed-psalm-heading")
                            chapter, cur_key = None, None
                            continue
                        if HEBREWS_SUFFIX_RE.search(head):
                            new_chapter, new_approx = num, False   # heading gives the Hebrew number directly
                        else:
                            new_chapter, new_approx = vulg_psalm_to_heb(num), num in APPROX_PSALM_SEAMS
                if new_chapter is None:
                    # ARGUMENT / PROLOGUE / PREFACE / PROTHEMATA / LETTER / etc: front matter
                    chapter, cur_key = None, None
                    if re.search(r"VERS\.", block):
                        skip.add("vers-inside-frontmatter-section")
                    continue
                # a fresh (non-"(cont.)") heading, or a "(cont.)" landing on a DIFFERENT
                # chapter than currently open (Migne sometimes reprints "(cont.)" loosely),
                # starts a new address; a true continuation keeps cur_key so stray text
                # before the next VERS still appends to the last entry.
                if not is_cont or new_chapter != chapter:
                    cur_key = None
                chapter, approx = new_chapter, new_approx
                # fall through: process this heading's own block below, same as head=None
            # continuation text of whatever chapter is currently open (head classified
            # above, or head is None and we're inside an already-open chapter/psalm)
            if chapter is None or not block.strip():
                continue
            parts = VERS_RE.split(block)
            # parts = [pre-text, num1, text1, num2, text2, ...] where pre-text (before the
            # first VERS in this block) continues the previous address, if any.
            pre = parts[0]
            if pre.strip() and cur_key is not None:
                entries[-1]["text"] += "\n\n" + pre
            elif pre.strip():
                skip.add("orphan-text-before-first-vers")
            for numlist, text in zip(parts[1::2], parts[2::2]):
                rng = parse_vers_list(numlist)
                if rng is None:
                    if cur_key is None:
                        skip.add("empty-vers-no-prior-address")
                        continue
                    entries[-1]["text"] += "\n\n" + text
                    continue
                vs, ve = rng
                cleaned, anch = clean_text(text)
                entries.append({"chapter": chapter, "v_start": vs, "v_end": ve,
                                 "text": cleaned, "anchor": (anch + "~approx" if approx and anch
                                                              else ("~approx" if approx else anch)),
                                 "approx": approx})
                cur_key = (chapter, vs, ve)
                n_vers += 1
    return entries, n_vers


# --- Reference text for the match-ratio gate --------------------------------------------
_kjv_cache: dict[str, dict] = {}
_deutero_cache: dict | None = None
_web_cache: dict | None = None

KJV_SLUG = {  # OSIS code -> kjv-wesley filename stem (spot-checked pattern: lowercase, no spaces)
    "Gen": "genesis", "Exod": "exodus", "Lev": "leviticus", "Num": "numbers", "Deut": "deuteronomy",
    "Josh": "joshua", "Judg": "judges", "Ruth": "ruth", "1Sam": "1samuel", "2Sam": "2samuel",
    "1Kgs": "1kings", "2Kgs": "2kings", "1Chr": "1chronicles", "2Chr": "2chronicles",
    "Ezra": "ezra", "Neh": "nehemiah", "Esth": "esther", "Job": "job", "Ps": "psalms",
    "Prov": "proverbs", "Eccl": "ecclesiastes", "Song": "songofsolomon", "Isa": "isaiah",
    "Jer": "jeremiah", "Matt": "matthew", "Mark": "mark", "Luke": "luke", "John": "john",
    "Acts": "acts", "Rom": "romans", "1Cor": "1corinthians", "2Cor": "2corinthians",
    "Gal": "galatians", "Eph": "ephesians", "Phil": "philippians", "Col": "colossians",
    "1Thess": "1thessalonians", "2Thess": "2thessalonians", "1Tim": "1timothy",
    "2Tim": "2timothy", "Titus": "titus", "Phlm": "philemon", "Heb": "hebrews", "Jas": "james",
    "1Pet": "1peter", "2Pet": "2peter", "1John": "1john", "2John": "2john", "3John": "3john",
    "Jude": "jude", "Rev": "revelation",
}
DEUTERO_SLUG = {"Wis": "wisdom-of-solomon", "Sir": "sirach", "Bar": "baruch",
                "Tob": "tobit", "Jdt": "judith"}


def _kjv_book(code: str) -> dict | None:
    slug = KJV_SLUG.get(code)
    if not slug:
        return None
    if slug not in _kjv_cache:
        f = KJV_DIR / f"{slug}.json"
        _kjv_cache[slug] = json.loads(f.read_text()) if f.exists() else {}
    return _kjv_cache[slug] or None


def reference_verses(code: str, chapter: int) -> dict[int, str]:
    """-> {verse: text} for a chapter, from KJV or (for deutero) WEB."""
    global _deutero_cache
    b = _kjv_book(code)
    if b:
        for ch in b.get("chapters", []):
            if ch.get("chapter") == chapter:
                return {v["verse"]: v["text"] for v in ch.get("verses", [])}
    dslug = DEUTERO_SLUG.get(code)
    if dslug:
        if _deutero_cache is None:
            _deutero_cache = json.loads(OT_CHAPTERS_DEUTERO.read_text()) if OT_CHAPTERS_DEUTERO.exists() else {}
        ch = _deutero_cache.get(f"{dslug}-{chapter}")
        if ch:
            return {v: t for v, t in ch["verses"]}
    return {}


def extract_lemma(text: str) -> str:
    """The printed Latin-gloss lemma, Englished -- some chunks mark it with *asterisks*,
    others with <<guillemets>> (a real formatting inconsistency across translation stints,
    not a data error -- see report's per-book match ratios). One combined pattern so the
    earliest-occurring form wins, not whichever alternative happens to match first."""
    m = re.search(r"\*(.+?)\*|«\s*(.+?)\s*»", text)
    return (m.group(1) or m.group(2)) if m else text.split(".", 1)[0][:80]


def lemma_match(lemma: str, ref_text: str) -> bool:
    """Loose word-overlap check: does the lemma share content words with the reference
    verse(s)? Only a gross-misalignment detector, not a translation check."""
    stop = {"the", "a", "an", "and", "of", "to", "in", "is", "he", "his", "that", "for",
            "was", "it", "they", "with", "not", "be", "shall", "you", "i", "we", "as"}
    lw = {w for w in re.findall(r"[a-z']+", lemma.lower()) if w not in stop and len(w) > 2}
    rw = {w for w in re.findall(r"[a-z']+", ref_text.lower()) if w not in stop and len(w) > 2}
    if not lw or not rw:
        return True  # can't judge -- don't penalize
    return len(lw & rw) > 0


# --- Psalms only: per-chapter verse-numbering offset --------------------------------------
# Many Vulgate psalms count the superscription ("A Psalm of David...") as verse 1, so every
# verse after it prints one number higher than the Hebrew/KJV verse it actually glosses.
# This does NOT apply uniformly (psalms without a superscription need no shift), and the
# plan explicitly forbids guessing it by hand -- so it's resolved per chapter using the same
# lemma/reference-text oracle as the report gate: try offset 0 and offset 1, keep whichever
# gets a clearly better match on that chapter's own entries. Logged, not silent.
def resolve_psalm_offset(code: str, heb_chapter: int, chapter_entries: list[dict]) -> tuple[int, str]:
    scores = {0: [0, 0], 1: [0, 0]}  # offset -> [matched, judged]
    ref = reference_verses(code, heb_chapter)
    if not ref:
        return 0, "no-reference-text"
    for e in chapter_entries:
        lemma = extract_lemma(e["text"])
        for off in (0, 1):
            vs, ve = e["v_start"] - off, e["v_end"] - off
            if vs < 1:
                continue
            rt = " ".join(ref.get(v, "") for v in range(vs, ve + 1))
            if not rt.strip():
                continue
            scores[off][1] += 1
            if lemma_match(lemma, rt):
                scores[off][0] += 1
    r0 = scores[0][0] / scores[0][1] if scores[0][1] else 0.0
    r1 = scores[1][0] / scores[1][1] if scores[1][1] else 0.0
    if scores[1][1] >= 3 and r1 > r0 + 0.15:
        return 1, f"shifted (offset-0 {r0:.0%}/{scores[0][1]} vs offset-1 {r1:.0%}/{scores[1][1]})"
    return 0, f"kept (offset-0 {r0:.0%}/{scores[0][1]} vs offset-1 {r1:.0%}/{scores[1][1]})"


def apply_psalm_offsets(entries: list[dict], code: str, verbose: bool = False) -> list[dict]:
    if code != "Ps":
        return entries
    by_chapter: dict[int, list[dict]] = {}
    for e in entries:
        by_chapter.setdefault(e["chapter"], []).append(e)
    out = []
    for ch, ch_entries in sorted(by_chapter.items()):
        off, why = resolve_psalm_offset(code, ch, ch_entries)
        if verbose:
            print(f"    Ps {ch:>3}: offset={off}  {why}")
        for e in ch_entries:
            vs, ve = e["v_start"] - off, e["v_end"] - off
            if vs < 1:
                continue  # pure-superscription entry under a shifted chapter -- no Hebrew verse to anchor it to
            out.append({**e, "v_start": vs, "v_end": ve,
                        "anchor": (e["anchor"] or "") + ("~voffset1" if off else "")})
    return out


def report():
    total_vers = total_mapped = total_matched = total_judged = 0
    print(f"{'idno':>6} {'code':>6} {'chunks':>7} {'VERS':>6} {'mapped':>7} {'match%':>7}  skips")
    for idno, code in sorted(IDNO_TO_CODE.items(), key=lambda kv: kv[0]):
        skip = Skip()
        entries, n_vers = parse_work(idno, code, skip)
        entries = apply_psalm_offsets(entries, code, verbose=(code == "Ps"))
        n_files = len(list((ENGLISH / idno).glob("[0-9][0-9][0-9][0-9].md")))
        matched = judged = 0
        for e in entries:
            refv = reference_verses(code, e["chapter"])
            if not refv:
                continue
            # union of the verse range's reference text
            rt = " ".join(refv.get(v, "") for v in range(e["v_start"], e["v_end"] + 1))
            if not rt.strip():
                continue
            lemma = extract_lemma(e["text"])
            judged += 1
            if lemma_match(lemma, rt):
                matched += 1
        ratio = f"{100*matched/judged:.0f}%" if judged else "n/a"
        skips = ", ".join(f"{k}={v}" for k, v in skip.counts.items()) or "-"
        print(f"{idno:>6} {code:>6} {n_files:>7} {n_vers:>6} {len(entries):>7} {ratio:>7}  {skips}")
        total_vers += n_vers
        total_mapped += len(entries)
        total_matched += matched
        total_judged += judged
    overall = f"{100*total_matched/total_judged:.1f}%" if total_judged else "n/a"
    print(f"\nTOTAL: {total_vers} VERS entries, {total_mapped} rows mapped, "
          f"overall lemma-match {overall} ({total_matched}/{total_judged} judged; "
          f"{total_mapped - total_judged} had no reference text to check, e.g. no KJV/WEB coverage)")


def build_rows():
    rows = []
    for idno, code in IDNO_TO_CODE.items():
        skip = Skip()
        entries, _ = parse_work(idno, code, skip)
        entries = apply_psalm_offsets(entries, code)
        title = TITLE_BY_IDNO[idno]
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        url = f"{SITE}/pl/{VOLUME_BY_IDNO[idno]}/{slug}/"
        for e in entries:
            ch, vs, ve = e["chapter"], e["v_start"], e["v_end"]
            refKey = osis.build_refkey(code, ch) if vs == 0 else (
                osis.build_refkey(code, ch, vs) if ve == vs else
                osis.build_refkey(code, ch, vs, ch, ve))
            if not e["text"].strip():
                continue
            rows.append((refKey, osis.refkey_to_display(refKey), code, ch, vs, ve,
                         SOURCE_ID, AUTHOR, TRADITION, WORK, e["text"], url, "text",
                         e["anchor"]))
    return rows


def insert(rows):
    con = sqlite3.connect(DB)
    con.execute("DELETE FROM reception WHERE source=?", (SOURCE_ID,))
    con.executemany("""INSERT INTO reception
        (refKey,refDisplay,book,chapter,v_start,v_end,source,author,tradition,work,text,provenanceUrl,mode,anchor)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM reception WHERE source=?", (SOURCE_ID,)).fetchone()[0]
    books = con.execute("SELECT COUNT(DISTINCT book) FROM reception WHERE source=?", (SOURCE_ID,)).fetchone()[0]
    approx = con.execute("SELECT COUNT(*) FROM reception WHERE source=? AND anchor LIKE '%~approx%'",
                          (SOURCE_ID,)).fetchone()[0]
    print(f"glossa-ordinaria: inserted {n} rows across {books} books ({approx} at approx psalm seams)")
    con.row_factory = sqlite3.Row
    for label, bk, ch, q0, q1 in [("Matt 13:1-9,18-23 (Sower)", "Matt", 13, 1, 23),
                                  ("Ruth 2 (gleaning)", "Ruth", 2, 1, 23),
                                  ("Psalm 23 (Heb numbering)", "Ps", 23, 1, 6)]:
        rs = con.execute("""SELECT refDisplay,text FROM reception WHERE source=? AND book=? AND chapter=?
            AND v_start<=? AND v_end>=? ORDER BY v_start LIMIT 2""",
            (SOURCE_ID, bk, ch, q1, q0)).fetchall()
        print(f"  \u25b8 {label}: " + (f"[{rs[0]['refDisplay']}] {rs[0]['text'][:100]}" if rs else "(no note)"))
    con.close()


def spot_sample(n: int = 10):
    """Print n random rows per testament for hand-verification against the Latin."""
    random.seed(2026)
    rows = build_rows()
    ot = [r for r in rows if r[2] not in ("Matt", "Mark", "Luke", "John", "Acts") and not r[2].startswith(
        ("Rom", "1Cor", "2Cor", "Gal", "Eph", "Phil", "Col", "1Thess", "2Thess", "1Tim", "2Tim",
         "Titus", "Phlm", "Heb", "Jas", "1Pet", "2Pet", "1John", "2John", "3John", "Jude", "Rev"))]
    nt = [r for r in rows if r not in ot]
    for label, pool in [("OT", ot), ("NT", nt)]:
        print(f"\n== {label} sample ({len(pool)} rows) ==")
        for r in random.sample(pool, min(n, len(pool))):
            print(f"  {r[1]}  {r[10][:140]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["report", "insert", "sample"], nargs="?", default="report")
    args = ap.parse_args()
    if args.mode == "report":
        report()
    elif args.mode == "sample":
        spot_sample()
    else:
        insert(build_rows())
