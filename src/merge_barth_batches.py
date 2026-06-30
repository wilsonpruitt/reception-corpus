#!/usr/bin/env python3.11
"""Merge the per-batch vision-OCR JSONL files for Barth's Aids into one clean pointer file.

Each vision subagent writes cache/barth/batches/batch_<startpage>.jsonl. An Aids entry can span a
batch boundary (scripture header + first CD ref in batch A, more CD refs at the top of batch B), so
an agent whose first page opens mid-entry emits a leading record  {"continues_prev": true,
"cd_refs":[...], "src_pages": "<p>"}  carrying the orphan CD refs above its first scripture header.
Merge folds those into the preceding real entry. Also coalesces two adjacent real entries that share
(occasion, ref) — the case where the same header is captured at both sides of a boundary.

Out: cache/barth/aids_pointers.jsonl  (consumed by ingest_barth_aids.py)
"""
from __future__ import annotations
import json, glob, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BATCH_DIR = ROOT / "cache/barth/batches"
OUT = ROOT / "cache/barth/aids_pointers.jsonl"


def start_page(path):
    m = re.search(r"batch_(\d+)", Path(path).name)
    return int(m.group(1)) if m else 0


def main():
    files = sorted(glob.glob(str(BATCH_DIR / "batch_*.jsonl")), key=start_page)
    if not files:
        sys.exit("no batch files in " + str(BATCH_DIR))
    BATCH_PAGES = 18     # every batch is 18 pdf pages (the final one is shorter but never precedes a gap)
    merged = []          # list of real entry dicts, in page order
    orphans = folds = coalesced = dropped = 0
    prev_start = None
    for f in files:
        sp = start_page(f)
        contiguous = prev_start is not None and sp == prev_start + BATCH_PAGES
        prev_start = sp
        first_line = True
        for line in open(f, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if r.get("continues_prev"):
                orphans += 1
                if first_line and not contiguous:
                    # the entry this orphan continues lives in a MISSING/not-yet-ingested batch.
                    # Folding it into the previous file's last entry would mis-attribute it. Drop + flag.
                    dropped += 1
                    print(f"  ~ dropped orphan at gap before {Path(f).name} "
                          f"(belongs to un-ingested pages {prev_start-BATCH_PAGES+BATCH_PAGES}..{sp-1})",
                          file=sys.stderr)
                    first_line = False
                    continue
                if merged and r.get("cd_refs"):
                    merged[-1]["cd_refs"].extend(r["cd_refs"]); folds += 1
                first_line = False
                continue
            first_line = False
            if not r.get("ref"):                     # malformed / headerless non-orphan — skip, flag
                print(f"  ! skip headerless record in {Path(f).name}: {r}", file=sys.stderr)
                continue
            if merged and merged[-1].get("ref") == r["ref"] \
               and merged[-1].get("occasion") == r.get("occasion"):
                merged[-1]["cd_refs"].extend(r.get("cd_refs", [])); coalesced += 1
                continue
            r.setdefault("cd_refs", [])
            merged.append(r)
    # de-dup identical cd_refs within each entry (anchor+section+cf)
    for e in merged:
        seen, uniq = set(), []
        for cd in e["cd_refs"]:
            k = (cd.get("vol"), cd.get("part"), cd.get("page"), bool(cd.get("cf")))
            if k in seen:
                continue
            seen.add(k); uniq.append(cd)
        e["cd_refs"] = uniq
    with open(OUT, "w", encoding="utf-8") as w:
        for e in merged:
            w.write(json.dumps(e, ensure_ascii=False) + "\n")
    nrefs = sum(len(e["cd_refs"]) for e in merged)
    print(f"merged {len(files)} batches -> {len(merged)} entries, {nrefs} CD pointers")
    print(f"  orphan records: {orphans} ({folds} folded, {dropped} dropped at page gaps), "
          f"coalesced dup headers: {coalesced}")
    print(f"  wrote {OUT}")


if __name__ == "__main__":
    main()
