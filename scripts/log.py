#!/usr/bin/env python3
"""
One-line score entry for the BH tennis dashboard.

Manual scores are written to data/manual_scores.csv (append-only) and
always override scraped data on conflict. Run this from anywhere — it
finds its own data file.

Usage:
  log.py "5/2 BH 7-0 St. Mark's"
  log.py "5/6 Brunswick 6-1 Choate" --note "from coach"
  log.py "05/02/2026 Belmont Hill 5 Nobles 2"
  log.py --list                      # show last 10 manual entries
  log.py --check                     # list manual rows that conflict with scraped data

Accepted score notations:
  "5/2 BH 7-0 St. Mark's"       (slashed score)
  "5/2 BH 7 St. Mark's 0"       (space-separated)
  "5/2 BH 7-0 St Marks"         (no apostrophes — best-effort canonicalize)

Team names are matched against schools.json aliases so abbreviations
("BH", "Nobles", "RL") and short names work.
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CSV_PATH = os.path.join(ROOT, "data", "manual_scores.csv")
SCHOOLS_PATH = os.path.join(ROOT, "data", "schools.json")
MATCHES_PATH = os.path.join(ROOT, "data", "matches.json")

# Common abbreviations Petros uses in conversation.
EXTRA_ALIASES = {
    "BH": "Belmont Hill",
    "RL": "Roxbury Latin School",
    "Nobles": "Noble & Greenough",
    "MX": "Middlesex",
    "Govs": "Governor's Academy",
    "LA": "Lawrence Academy",
    "StSebs": "St. Sebastian's",
    "St Sebs": "St. Sebastian's",
    "Tabor": "Tabor Academy",
    "Thayer": "Thayer Academy",
    "Brooks": "Brooks",
    "Rivers": "Rivers School",
    "BB&N": "Buckingham Browne & Nichols",
    "Milton": "Milton Academy",
    "Brunswick": "Brunswick School",
    "Andover": "Phillips Academy Andover",
    "Exeter": "Phillips Exeter Academy",
    "SPS": "St. Paul's School",
    "Choate": "Choate Rosemary Hall",
    "Deerfield": "Deerfield Academy",
    "Hotchkiss": "Hotchkiss School",
    "Loomis": "Loomis Chaffee",
    "Hopkins": "Hopkins School",
}


def load_canonical():
    with open(SCHOOLS_PATH) as f:
        s = json.load(f)
    canon = set()
    aliases = dict(s.get("name_aliases", {}))
    for grp in ("isl", "class_a_only"):
        for full, meta in s[grp].items():
            canon.add(full)
            short = meta.get("short")
            if short and short != full:
                aliases.setdefault(short, full)
    for full in s.get("non_class_a_opponents", {}):
        canon.add(full)
    aliases.update(EXTRA_ALIASES)
    return canon, aliases


def canonicalize(name: str, canon: set, aliases: dict) -> str:
    n = name.strip().rstrip(",")
    if n in canon:
        return n
    if n in aliases:
        return aliases[n]
    # Case-insensitive fallback
    for k, v in aliases.items():
        if k.lower() == n.lower():
            return v
    for c in canon:
        if c.lower() == n.lower():
            return c
    # Partial match — last resort, biggest unique substring
    matches = [c for c in canon if n.lower() in c.lower() or c.lower() in n.lower()]
    if len(matches) == 1:
        return matches[0]
    return n  # give up — caller can decide


def parse_phrase(phrase: str, canon: set, aliases: dict) -> dict:
    """Parse 'M/D BH 7-0 St. Mark's' style into a dict."""
    s = phrase.strip()
    # Date
    date_match = re.match(r"^\s*(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\s+(.*)$", s)
    if not date_match:
        raise ValueError(f"can't find leading date in {s!r}")
    mo, da, yr, rest = date_match.groups()
    if not yr:
        yr = str(datetime.now().year)
    elif len(yr) == 2:
        yr = "20" + yr
    date = f"{int(mo):02d}/{int(da):02d}/{int(yr):04d}"
    # Score: try "X-Y" first, else "TEAM_A N TEAM_B M"
    rest = rest.strip()
    m = re.search(r"^(.+?)\s+(\d+)\s*[-–]\s*(\d+)\s+(.+)$", rest)
    if m:
        team_a, score_a, score_b, team_b = m.groups()
    else:
        m = re.search(r"^(.+?)\s+(\d+)\s+(.+?)\s+(\d+)\s*$", rest)
        if not m:
            raise ValueError(f"can't find score in {rest!r}")
        team_a, score_a, team_b, score_b = m.groups()
    return {
        "date": date,
        "home": canonicalize(team_a, canon, aliases),
        "home_score": int(score_a),
        "away": canonicalize(team_b, canon, aliases),
        "away_score": int(score_b),
    }


def append_row(row: dict, note: str = "") -> None:
    new = not os.path.exists(CSV_PATH) or os.path.getsize(CSV_PATH) == 0
    with open(CSV_PATH, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["date", "home", "home_score", "away", "away_score", "note"])
        w.writerow(
            [row["date"], row["home"], row["home_score"], row["away"], row["away_score"], note]
        )


def read_manual_rows() -> list[dict]:
    rows = []
    if not os.path.exists(CSV_PATH):
        return rows
    with open(CSV_PATH) as f:
        for raw in f:
            if not raw.strip() or raw.lstrip().startswith("#"):
                continue
            line = raw.rstrip("\n")
            try:
                date, home, hs, away, as_, *rest = next(csv.reader([line]))
            except (StopIteration, ValueError):
                continue
            if date == "date":
                continue
            try:
                rows.append(
                    {
                        "date": date,
                        "home": home,
                        "home_score": int(hs),
                        "away": away,
                        "away_score": int(as_),
                        "note": rest[0] if rest else "",
                    }
                )
            except ValueError:
                continue
    return rows


def cmd_list() -> int:
    rows = read_manual_rows()
    if not rows:
        print("(no manual entries yet)")
        return 0
    for r in rows[-10:]:
        note = f"  // {r['note']}" if r["note"] else ""
        print(
            f"  {r['date']}: {r['home']} {r['home_score']}-{r['away_score']} {r['away']}{note}"
        )
    print(f"\n  ({len(rows)} total)")
    return 0


def cmd_check() -> int:
    """Compare manual rows against current matches.json — surface conflicts."""
    if not os.path.exists(MATCHES_PATH):
        print("matches.json not found", file=sys.stderr)
        return 1
    with open(MATCHES_PATH) as f:
        db = json.load(f)
    by_key = {f'{m["date"]}|{m["home"]}|{m["away"]}': m for m in db["matches"]}
    found = 0
    for r in read_manual_rows():
        k = f'{r["date"]}|{r["home"]}|{r["away"]}'
        kr = f'{r["date"]}|{r["away"]}|{r["home"]}'
        target = by_key.get(k) or by_key.get(kr)
        if not target:
            print(f"  + {r['date']}: {r['home']} {r['home_score']}-{r['away_score']} {r['away']}  (manual NEW)")
            found += 1
            continue
        eh, ea = target.get("home_score"), target.get("away_score")
        nh, na = r["home_score"], r["away_score"]
        if k not in by_key:
            nh, na = na, nh
        if eh != nh or ea != na:
            print(
                f"  ! {r['date']}: {r['home']} v {r['away']}: "
                f"DB has {eh}-{ea} ({target.get('source','?')}); manual says {nh}-{na}"
            )
            found += 1
    if not found:
        print("  no conflicts — all manual rows match the database.")
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] == "--list":
        return cmd_list()
    if argv[0] == "--check":
        return cmd_check()
    note = ""
    if "--note" in argv:
        i = argv.index("--note")
        note = argv[i + 1]
        argv = argv[:i] + argv[i + 2 :]
    phrase = " ".join(argv)
    canon, aliases = load_canonical()
    try:
        row = parse_phrase(phrase, canon, aliases)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        print("  expected something like:  log.py '5/2 BH 7-0 St. Mark's'", file=sys.stderr)
        return 2
    # Sanity check the canonicalization
    unrecognized = [t for t in (row["home"], row["away"]) if t not in canon]
    if unrecognized:
        print(
            f"  warning: didn't fully canonicalize {unrecognized}. Stored as written; edit data/manual_scores.csv to fix.",
            file=sys.stderr,
        )
    append_row(row, note=note)
    print(
        f"recorded: {row['date']}: {row['home']} {row['home_score']}-{row['away_score']} {row['away']}"
    )
    if note:
        print(f"  note: {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
