#!/usr/bin/env python3.11
"""Validate the built RCL spine. Fidelity gate before the data is trusted.

Checks:
  1. Every refKey parses (osis.parse_refkey) and the book code is real.
  2. Number-subset: every chapter/verse integer in a derived refKey appears in its
     VERBATIM refDisplay — catches any parser fabrication or drift (refDisplay is the
     authoritative source string; refKey is derived).
  3. Generated Year A Advent == hand-verified backup (refKey sets per occasion).
  4. Structural: unique ids; roles valid; track only in Season after Pentecost;
     every Sunday/principal occasion resolves a gospel.
  5. Reception resolution lights up (non-Apocrypha readings join the store).
"""
from __future__ import annotations
import json, re, sqlite3, sys
from collections import Counter, defaultdict
from pathlib import Path
import osis

ROOT = Path(__file__).resolve().parent.parent
SPINE = ROOT / "data" / "rcl.json"
HAND = ROOT / "cache" / "rcl.json.hand-advent-a.bak"
DB = ROOT / "data" / "reception.sqlite"
ROLES = {"first", "psalm", "second", "gospel"}
APOC = {"Tob", "Jdt", "Wis", "Sir", "Bar", "Sus", "1Macc", "2Macc", "Bel", "PrAzar", "EpJer", "1Esd", "2Esd"}

fail = []


def nums(s):
    return [int(n) for n in re.findall(r"\d+", s)]


def all_refkeys(r):
    return r.get("refKeys") or ([r["refKey"]] if r.get("refKey") else [])


def check_parse_and_numbers(spine):
    bad_parse, bad_nums = [], []
    for occ in spine["occasions"]:
        for r in occ["readings"]:
            if r.get("refKey") is None:
                bad_parse.append((occ["id"], r.get("refDisplay"), "null refKey"))
                continue
            disp_nums = set(nums(r["refDisplay"]))
            for rk in all_refkeys(r):
                p = osis.parse_refkey(rk)
                if not p or p["book"] not in osis.OSIS_NAME:
                    bad_parse.append((occ["id"], rk, "unparseable/unknown book"))
                    continue
                # every integer in the refKey must be present in the verbatim display
                rk_nums = set(nums(rk.split(".", 1)[1])) if "." in rk else set()
                missing = rk_nums - disp_nums
                if missing:
                    bad_nums.append((occ["id"], r["refDisplay"], rk, sorted(missing)))
    return bad_parse, bad_nums


def check_advent_a(spine):
    hand = json.loads(HAND.read_text())
    hand_by_name = {o["name"]: o for o in hand["occasions"]}
    diffs = []
    for occ in spine["occasions"]:
        if occ["year"] != "A" or occ["name"] not in hand_by_name:
            continue
        h = hand_by_name[occ["name"]]
        # compare the multiset of refKeys per role (join keys are what must match;
        # refDisplay dash-style differs: source uses '-', hand used en-dash).
        def sig(o):
            acc = []
            for r in o["readings"]:
                for rk in all_refkeys(r):
                    acc.append((r["role"], rk))
            return Counter(acc)
        if sig(occ) != sig(h):
            diffs.append((occ["name"], "GEN", sig(occ), "HAND", sig(h)))
    return diffs


def check_structure(spine):
    ids = [o["id"] for o in spine["occasions"]]
    dup = [i for i, c in Counter(ids).items() if c > 1]
    if dup:
        fail.append(f"duplicate ids: {dup}")
    for occ in spine["occasions"]:
        for r in occ["readings"]:
            if r["role"] not in ROLES:
                fail.append(f"{occ['id']}: bad role {r['role']}")
            if r.get("track") and occ["season"] != "Season after Pentecost":
                fail.append(f"{occ['id']}: track outside Pentecost season ({occ['season']})")
        # principal Sundays/feasts should resolve a gospel (data sanity)
        roles = {r["role"] for r in occ["readings"]}
        if "gospel" not in roles:
            fail.append(f"{occ['id']} ({occ['name']}): no gospel reading")


def check_reception(spine):
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    lit = dead = apoc = 0
    for occ in spine["occasions"]:
        for r in occ["readings"]:
            for rk in all_refkeys(r):
                p = osis.parse_refkey(rk)
                if not p:
                    continue
                if p["book"] in APOC:
                    apoc += 1
                    continue
                n = con.execute(
                    """SELECT COUNT(*) FROM reception WHERE book=? AND chapter=? AND
                       ((v_start=0 AND v_end=0) OR (v_start<=? AND v_end>=?))""",
                    (p["book"], p["chapter"], p["v_end"] or p["v_start"] or 999, p["v_start"] or 0),
                ).fetchone()[0]
                lit += 1 if n else 0
                dead += 0 if n else 1
    con.close()
    return lit, dead, apoc


def main():
    spine = json.loads(SPINE.read_text())
    occ = spine["occasions"]
    print(f"Occasions: {len(occ)}  Readings: {sum(len(o['readings']) for o in occ)}")
    by_year = Counter(o["year"] for o in occ)
    print("By year:", dict(by_year))
    print("Seasons:", dict(Counter(o["season"] for o in occ)))
    print("Tracks:", dict(Counter(r.get("track", "—") for o in occ for r in o["readings"])))

    bad_parse, bad_nums = check_parse_and_numbers(spine)
    if bad_parse:
        fail.append(f"{len(bad_parse)} parse failures: {bad_parse[:8]}")
    if bad_nums:
        fail.append(f"{len(bad_nums)} number-subset mismatches: {bad_nums[:8]}")

    diffs = check_advent_a(spine)
    if diffs:
        fail.append(f"Advent-A mismatch vs hand-verified: {diffs}")
    else:
        print("Advent-A: generated refKeys == hand-verified backup ✓")

    check_structure(spine)
    lit, dead, apoc = check_reception(spine)
    print(f"Reception resolution: {lit} readings light up, {dead} dead (no rows), {apoc} Apocrypha (no text expected)")

    if fail:
        print("\n!! VALIDATION FAILURES:")
        for f in fail:
            print("  -", f)
        sys.exit(1)
    print("\nALL CHECKS PASSED.")


if __name__ == "__main__":
    main()
