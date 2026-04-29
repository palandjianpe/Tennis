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
from fetch_veracross import fetch_veracross_matches  # noqa: E402
from fetch_finalsite import fetch_finalsite_matches  # noqa: E402
from fetch_andover import fetch_andover_matches  # noqa: E402

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
    # Tier 2: Veracross ICS calendar feeds (Founders League / Class A schools).
    # Each entry needs the school's public Veracross ICS URL, found on the
    # school's varsity-tennis page as the "Add to Calendar" button. Token in
    # the URL is required and read-only — Veracross rotates them rarely.
    {
        "name": "Avon Old Farms (Veracross)",
        "tier": "home_site",
        "tag": "avon_site",
        "owner": "Avon Old Farms",
        "fetcher": lambda: fetch_veracross_matches(
            "Avon Old Farms",
            "https://api.veracross.com/aof/teams/53213.ics?t=f9670b44377f86c7036573244cd939a5&uid=2C49F278-5AF8-46FE-8032-1D347AA25245",
            source="avon_site",
        ),
    },
    # Tier 2: SIDEARM-standard schedule pages (continued).
    {
        "name": "St. Paul's School (SIDEARM)",
        "tier": "home_site",
        "tag": "sps_site",
        "owner": "St. Paul's School",
        "fetcher": lambda: fetch_sidearm_matches(
            "St. Paul's School",
            "https://athletics.sps.edu/sports/boys-tennis/schedule",
            season_year=2026,
            source="sps_site",
        ),
    },
    # Tier 2: FinalSite athletics composites. The same parser handles every
    # school that hosts on FinalSite's athletics CMS. Adding a new school is
    # one line: just give it a name, owner, URL, and source tag. Some FinalSite
    # pages cap the initial render at 5-6 events (Choate, NMH) — their pages
    # have a "Load More" button that requires JS, so we get a partial schedule.
    # If you need the full set, write down the missing matches in manual_scores.csv.
    {
        "name": "Loomis Chaffee (FinalSite)",
        "tier": "home_site",
        "tag": "loomis_site",
        "owner": "Loomis Chaffee",
        "fetcher": lambda: fetch_finalsite_matches(
            "Loomis Chaffee",
            "https://www.loomischaffee.org/athletics/teams/spring/tennis/boys",
            season_year=2026, source="loomis_site",
        ),
    },
    {
        "name": "Northfield Mt. Hermon (FinalSite)",
        "tier": "home_site",
        "tag": "nmh_site",
        "owner": "Northfield Mt. Hermon",
        "fetcher": lambda: fetch_finalsite_matches(
            "Northfield Mt. Hermon",
            "https://www.nmhschool.org/athletics-home/programs/boys/tennis",
            season_year=2026, source="nmh_site",
        ),
    },
    {
        "name": "Hotchkiss School (FinalSite)",
        "tier": "home_site",
        "tag": "hotchkiss_site",
        "owner": "Hotchkiss School",
        "fetcher": lambda: fetch_finalsite_matches(
            "Hotchkiss School",
            "https://www.hotchkiss.org/athletics/our-teams/boys-tennis/varsity",
            season_year=2026, source="hotchkiss_site",
        ),
    },
    {
        "name": "Choate Rosemary Hall (FinalSite, partial)",
        "tier": "home_site",
        "tag": "choate_site",
        "owner": "Choate Rosemary Hall",
        "fetcher": lambda: fetch_finalsite_matches(
            "Choate Rosemary Hall",
            "https://www.choate.edu/athletics/teams-programs/spring/tennis/~athletics-team-id/276",
            season_year=2026, source="choate_site",
        ),
    },
    {
        "name": "Kent School (FinalSite)",
        "tier": "home_site",
        "tag": "kent_site",
        "owner": "Kent School",
        "fetcher": lambda: fetch_finalsite_matches(
            "Kent School",
            "https://www.kent-school.edu/athletics/teams-schedules/boys-tennis",
            season_year=2026, source="kent_site",
        ),
    },
    {
        "name": "Brunswick School (FinalSite)",
        "tier": "home_site",
        "tag": "brunswick_site",
        "owner": "Brunswick School",
        "fetcher": lambda: fetch_finalsite_matches(
            "Brunswick School",
            "https://my.brunswickschool.org/athletics/team/~athletics-team-id/231",
            season_year=2026, source="brunswick_site",
        ),
    },
    # Custom: Phillips Academy Andover. Their CMS only renders UPCOMING events
    # in static HTML — past results require JS to populate. So this fetcher
    # contributes the schedule only; scores need manual entry.
    {
        "name": "Phillips Academy Andover (custom; schedule only)",
        "tier": "home_site",
        "tag": "andover_site",
        "owner": "Phillips Academy Andover",
        "fetcher": lambda: fetch_andover_matches(season_year=2026),
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
    aliases.setdefault("Kingswood Oxford School", "Kingswood-Oxford")
    aliases.setdefault("Kingswood-Oxford School", "Kingswood-Oxford")
    aliases.setdefault("Hotchkiss", "Hotchkiss School")
    aliases.setdefault("The Hotchkiss School", "Hotchkiss School")
    aliases.setdefault("Trinity-Pawling School", "Trinity-Pawling")
    aliases.setdefault("Avon Old Farms School", "Avon Old Farms")
    aliases.setdefault("Choate", "Choate Rosemary Hall")
    aliases.setdefault("Choate Rosemary Hall School", "Choate Rosemary Hall")
    aliases.setdefault("Hopkins", "Hopkins School")
    aliases.setdefault("The Hopkins School", "Hopkins School")
    aliases.setdefault("Taft", "Taft School")
    aliases.setdefault("The Taft School", "Taft School")
    aliases.setdefault("Westminster", "Westminster School")
    aliases.setdefault("Berkshire", "Berkshire School")
    aliases.setdefault("Salisbury", "Salisbury School")
    aliases.setdefault("Suffield", "Suffield Academy")
    aliases.setdefault("Pomfret", "Pomfret School")
    aliases.setdefault("Frederick Gunn", "Frederick Gunn School")
    aliases.setdefault("Williston Northampton", "Williston Northampton School")
    aliases.setdefault("Cheshire", "Cheshire Academy")
    aliases.setdefault("Canterbury", "Canterbury School")
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

    # Post-merge cleanup: drop scheduled entries that duplicate a completed
    # match between the same two teams within a 7-day window. This handles
    # the common case where a league feed lists a match on its OFFICIAL date
    # but the team's home site reports the actual played date a day off.
    completed_index = {}
    for m in matches:
        if m.get("status") != "completed":
            continue
        teams = frozenset((m["home"], m["away"]))
        d = datetime.strptime(m["date"], "%m/%d/%Y").date()
        completed_index.setdefault(teams, []).append(d)

    def _is_phantom(m):
        if m.get("status") == "completed":
            return False
        teams = frozenset((m["home"], m["away"]))
        if teams not in completed_index:
            return False
        d = datetime.strptime(m["date"], "%m/%d/%Y").date()
        return any(abs((d - cd).days) <= 7 for cd in completed_index[teams])

    before = len(matches)
    dropped = [m for m in matches if _is_phantom(m)]
    matches = [m for m in matches if not _is_phantom(m)]
    if dropped:
        stats.setdefault("details", {}).setdefault("dropped_phantoms", [])
        for m in dropped:
            stats["details"]["dropped_phantoms"].append(
                f"{m['date']}: {m['home']} vs {m['away']} (already completed within 7d)"
            )
        stats["dropped_phantoms"] = len(dropped)

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
    if stats.get("dropped_phantoms"):
        print(f"  dropped phantoms: {stats['dropped_phantoms']}")
        for d in stats["details"].get("dropped_phantoms", [])[:5]:
            print(f"    × {d}")


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
