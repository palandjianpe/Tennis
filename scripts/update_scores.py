#!/usr/bin/env python3
"""
Orchestrator: pull match results from every configured source, merge into
data/matches.json with deterministic conflict resolution, and report what
changed.

Source precedence (highest wins on score conflicts):
  1. manual         — data/manual_scores.csv (Petros's word is final)
  2. home_site      — the home team's own athletics page
  3. away_site      — the away team's site
  4. league_feed    — rSchoolToday widget / aggregator
  5. newspaper      — student paper recap (lowest, since prose is harder
                      to parse cleanly)

Usage:
  scripts/update_scores.py            # merge into matches.json, print summary
  scripts/update_scores.py --dry-run  # report what WOULD change, write nothing

Sources are configured below in SOURCES. To add a school, add a line.
Sources that fail (network error, parse error) are logged and skipped — a
single broken source never breaks the run.
"""

from __future__ import annotations

import csv
import json
import os
import sys
import traceback
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from fetch_rschooltoday import fetch_widget_matches  # noqa: E402
from fetch_sidearm import fetch_sidearm_matches  # noqa: E402

MATCHES_PATH = os.path.join(ROOT, "data", "matches.json")
SCHOOLS_PATH = os.path.join(ROOT, "data", "schools.json")
MANUAL_PATH = os.path.join(ROOT, "data", "manual_scores.csv")
LOG_PATH = os.path.join(ROOT, "data", "scrape_log.csv")

# Source precedence — lower number = higher trust.
PRECEDENCE = {
    "manual": 1,
    "home_site": 2,
    "away_site": 3,
    "league_feed": 4,
    "newspaper": 5,
    "scraped": 6,  # generic / unknown
}


# ---------------------------------------------------------------------------
# Sources — each entry produces a list of match dicts.
# Tier dictates conflict precedence; "tag" is what gets recorded in source.
# ---------------------------------------------------------------------------
SOURCES = [
    # Tier 1: league-level feeds
    {
        "name": "ISL boys tennis widget",
        "tier": "league_feed",
        "tag": "isl_feed",
        "fetcher": lambda: fetch_widget_matches(
            "fef0129c-6fc2-11f0-ba9f-064bb7083971", source="isl_feed"
        ),
    },
    # Tier 2: SIDEARM-standard schedule pages (one per school).
    # We could expand this list as more schools are confirmed working.
    {
        "name": "Phillips Exeter (SIDEARM)",
        "tier": "home_site",
        "tag": "exeter_site",
        "owner": "Phillips Exeter Academy",
        "fetcher": lambda: fetch_sidearm_matches(
            "Phillips Exeter Academy",
            "https://weareexeter.com/sports/mens-tennis/schedule/2026",
            season_year=2026,
            source="exeter_site",
        ),
    },
]


def load_aliases() -> tuple[set, dict]:
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
    # Common name variants seen in the wild
    aliases.setdefault("Loomis Chaffee School", "Loomis Chaffee")
    aliases.setdefault("Northfield Mount Hermon School", "Northfield Mt. Hermon")
    aliases.setdefault("Greenwich Country Day School", "Greenwich Country Day")
    aliases.setdefault("St. John's Prep School", "St. John's Preparatory School")
    aliases.setdefault("Phillips Academy", "Phillips Academy Andover")
    aliases.setdefault("The Groton School", "Groton")
    aliases.setdefault("Groton School", "Groton")
    aliases.setdefault("The Brooks School", "Brooks")
    aliases.setdefault("Brooks School", "Brooks")
    aliases.setdefault("Buckingham Browne & Nichols School", "Buckingham Browne & Nichols")
    aliases.setdefault("Noble and Greenough School", "Noble & Greenough")
    return canon, aliases


def canon(name: str, canonical: set, aliases: dict) -> str:
    if not name:
        return name
    n = name.strip()
    if n in canonical:
        return n
    if n in aliases:
        return aliases[n]
    for k, v in aliases.items():
        if k.lower() == n.lower():
            return v
    return n


def read_manual() -> list[dict]:
    rows: list[dict] = []
    if not os.path.exists(MANUAL_PATH):
        return rows
    with open(MANUAL_PATH) as f:
        for raw in f:
            if not raw.strip() or raw.lstrip().startswith("#"):
                continue
            try:
                parts = next(csv.reader([raw.rstrip("\n")]))
            except (StopIteration, ValueError):
                continue
            if not parts or parts[0] == "date":
                continue
            if len(parts) < 5:
                continue
            try:
                date, home, hs, away, as_ = parts[:5]
                rows.append(
                    {
                        "date": date.strip(),
                        "home": home.strip(),
                        "home_score": int(hs),
                        "away": away.strip(),
                        "away_score": int(as_),
                        "status": "completed",
                        "source": "manual",
                        "_tier": "manual",
                    }
                )
            except ValueError:
                continue
    return rows


def collect_all_sources() -> tuple[list[dict], list[dict]]:
    """Run every configured source. Returns (all_rows, scrape_log)."""
    all_rows: list[dict] = []
    log: list[dict] = []
    started = datetime.now()
    # Manual first (highest precedence)
    manual_rows = read_manual()
    log.append(
        {
            "timestamp": started.isoformat(timespec="seconds"),
            "source": "manual_scores.csv",
            "tier": "manual",
            "status": "ok",
            "rows": len(manual_rows),
            "note": "",
        }
    )
    all_rows.extend(manual_rows)
    # Then every configured fetcher
    for src in SOURCES:
        ts = datetime.now().isoformat(timespec="seconds")
        try:
            rows = src["fetcher"]() or []
            for r in rows:
                r["_tier"] = src["tier"]
                r["source"] = src.get("tag", r.get("source", src["tier"]))
            all_rows.extend(rows)
            log.append(
                {
                    "timestamp": ts,
                    "source": src["name"],
                    "tier": src["tier"],
                    "status": "ok",
                    "rows": len(rows),
                    "note": "",
                }
            )
            print(f"  [ok]  {src['name']}: {len(rows)} rows")
        except Exception as exc:  # pragma: no cover  — we want to keep going
            log.append(
                {
                    "timestamp": ts,
                    "source": src["name"],
                    "tier": src["tier"],
                    "status": "error",
                    "rows": 0,
                    "note": f"{type(exc).__name__}: {exc}",
                }
            )
            print(f"  [err] {src['name']}: {type(exc).__name__}: {exc}", file=sys.stderr)
    return all_rows, log


def merge(rows: list[dict], db: dict, canonical: set, aliases: dict) -> dict:
    """Merge incoming rows into the matches.json db. Returns a stats dict."""
    matches = db["matches"]

    def key(date, home, away):
        return f"{date}|{home}|{away}"

    by_key = {key(m["date"], m["home"], m["away"]): m for m in matches}

    stats = {
        "added_completed": 0,
        "added_scheduled": 0,
        "upgraded": 0,
        "verified": 0,
        "score_conflicts_overridden": 0,
        "skipped_low_precedence": 0,
        "details": {
            "added_completed": [],
            "upgraded": [],
            "score_conflicts_overridden": [],
            "skipped_low_precedence": [],
            "added_scheduled": [],
        },
    }

    for r in rows:
        h = canon(r["home"], canonical, aliases)
        a = canon(r["away"], canonical, aliases)
        date = r["date"]
        new_tier = PRECEDENCE.get(r.get("_tier", "scraped"), 6)
        k_direct = key(date, h, a)
        k_rev = key(date, a, h)
        target = by_key.get(k_direct)
        flipped = False
        if target is None and k_rev in by_key:
            target = by_key[k_rev]
            flipped = True

        if target is None:
            entry = {
                "date": date,
                "home": h,
                "away": a,
                "status": r["status"],
                "source": r["source"],
            }
            if r["status"] == "completed":
                entry["home_score"] = r["home_score"]
                entry["away_score"] = r["away_score"]
                stats["added_completed"] += 1
                stats["details"]["added_completed"].append(
                    f"{date}: {h} {entry['home_score']}-{entry['away_score']} {a} ({r['source']})"
                )
            else:
                stats["added_scheduled"] += 1
                stats["details"]["added_scheduled"].append(f"{date}: {h} vs {a}")
            matches.append(entry)
            by_key[k_direct] = entry
            continue

        # Existing target — possibly upgrade or verify or override
        prior_tier = PRECEDENCE.get(target.get("_tier", "scraped"), 9)
        prior_src = target.get("source", "")

        if r["status"] == "completed":
            new_h, new_a = (
                (r["away_score"], r["home_score"]) if flipped else (r["home_score"], r["away_score"])
            )
            if target.get("status") != "completed":
                # Upgrade scheduled → completed
                target["status"] = "completed"
                target["home_score"] = new_h
                target["away_score"] = new_a
                target["source"] = (
                    (prior_src + "," + r["source"]).strip(",") if prior_src else r["source"]
                )
                target["_tier"] = r.get("_tier")
                stats["upgraded"] += 1
                stats["details"]["upgraded"].append(
                    f"{date}: {target['home']} {new_h}-{new_a} {target['away']} ({r['source']})"
                )
            else:
                eh, ea = target.get("home_score"), target.get("away_score")
                if eh == new_h and ea == new_a:
                    # Verify — append source for provenance
                    if r["source"] not in prior_src:
                        target["source"] = (
                            (prior_src + "," + r["source"]).strip(",") if prior_src else r["source"]
                        )
                    stats["verified"] += 1
                else:
                    # Conflict — winner is the higher-precedence source
                    if new_tier <= prior_tier:
                        msg = (
                            f"{date}: {target['home']} v {target['away']}: "
                            f"was {eh}-{ea} ({prior_src}); now {new_h}-{new_a} ({r['source']})"
                        )
                        target["home_score"] = new_h
                        target["away_score"] = new_a
                        target["source"] = (
                            (prior_src + ",OVERRIDDEN_BY:" + r["source"]).strip(",")
                            if prior_src
                            else r["source"]
                        )
                        target["_tier"] = r.get("_tier")
                        stats["score_conflicts_overridden"] += 1
                        stats["details"]["score_conflicts_overridden"].append(msg)
                    else:
                        stats["skipped_low_precedence"] += 1
                        stats["details"]["skipped_low_precedence"].append(
                            f"{date}: {target['home']} v {target['away']}: "
                            f"keeping {eh}-{ea} ({prior_src}); ignoring {new_h}-{new_a} ({r['source']})"
                        )
        # If new row is just "scheduled" and we already have it, do nothing.

    # Strip internal _tier markers before write
    for m in matches:
        m.pop("_tier", None)

    matches.sort(key=lambda m: datetime.strptime(m["date"], "%m/%d/%Y"))
    db["matches"] = matches
    db["_last_updated"] = datetime.now().strftime("%Y-%m-%d")
    return stats


def write_log(log_rows: list[dict]) -> None:
    new = not os.path.exists(LOG_PATH)
    with open(LOG_PATH, "a", newline="") as f:
        w = csv.DictWriter(
            f, fieldnames=["timestamp", "source", "tier", "status", "rows", "note"]
        )
        if new:
            w.writeheader()
        for r in log_rows:
            w.writerow(r)


def print_summary(stats: dict, log: list[dict], dry_run: bool) -> None:
    mode = "DRY RUN" if dry_run else "LIVE"
    print(f"\n=== Update summary ({mode}) ===")
    print(f"  sources run    : {len(log)}")
    print(f"  total rows in  : {sum(r['rows'] for r in log)}")
    print(f"  new completed  : {stats['added_completed']}")
    for d in stats["details"]["added_completed"][:8]:
        print(f"    + {d}")
    if len(stats["details"]["added_completed"]) > 8:
        print(f"    ... and {len(stats['details']['added_completed']) - 8} more")
    print(f"  upgraded       : {stats['upgraded']}")
    for d in stats["details"]["upgraded"][:5]:
        print(f"    ↑ {d}")
    print(f"  verified       : {stats['verified']}")
    print(f"  conflicts won  : {stats['score_conflicts_overridden']}")
    for d in stats["details"]["score_conflicts_overridden"]:
        print(f"    ! {d}")
    print(f"  conflicts lost : {stats['skipped_low_precedence']}")
    for d in stats["details"]["skipped_low_precedence"]:
        print(f"    · {d}")
    print(f"  new scheduled  : {stats['added_scheduled']}")


def main(argv: list[str]) -> int:
    dry_run = "--dry-run" in argv
    print(f"=== update_scores.py — {datetime.now().isoformat(timespec='seconds')} ===")
    rows, log = collect_all_sources()
    canonical, aliases = load_aliases()
    with open(MATCHES_PATH) as f:
        db = json.load(f)
    stats = merge(rows, db, canonical, aliases)
    print_summary(stats, log, dry_run)
    if dry_run:
        print("\n(dry run — no files modified)")
        return 0
    with open(MATCHES_PATH, "w") as f:
        json.dump(db, f, indent=2)
    write_log(log)
    print(f"\nwrote {MATCHES_PATH}")
    print(f"appended {len(log)} log rows to {LOG_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
