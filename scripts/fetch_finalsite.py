#!/usr/bin/env python3
"""
Fetch and parse FinalSite athletics schedule pages.

A surprising number of NEPSAC Class A schools (Loomis, NMH, Hotchkiss, Choate,
Kent, Brunswick, Deerfield) host their athletics CMS on FinalSite. The earlier
auto-discovery passes thought these pages were JavaScript-only because the
schedule isn't visible in a casual scan, but FinalSite actually renders the
full table server-side using a stable set of CSS classes:

    <tr class="fsResultWin">                    (or fsResultLoss / fsResultTie / fsAthleticsUpcoming)
      <td class="fsAthleticsOpponents">
        <span class="fsAthleticsOpponentName">Phillips Exeter Academy</span>
      </td>
      <td class="fsAthleticsDate">
        <time datetime="2026-04-04T13:00:00-04:00">…</time>
      </td>
      <td class="fsAthleticsAdvantage">Home</td>      (or Away)
      <td class="fsAthleticsResult">Win</td>          (or Loss / Tie / blank if upcoming)
      <td class="fsAthleticsScore">4-0</td>           (us-them, blank if upcoming)
    </tr>

Scores are recorded from the OWNING school's perspective, just like Veracross.

Usage:
  python3 scripts/fetch_finalsite.py SCHOOL_NAME PAGE_URL [--season-year YYYY]

Importable:
  from fetch_finalsite import fetch_finalsite_matches
  matches = fetch_finalsite_matches(school, url, season_year=2026)
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from datetime import datetime
from typing import Iterable

# Each match is a single block whose class starts with "fsResult" or
# "fsAthleticsUpcoming". FinalSite athletics composites use either:
#   - a <tr> wrapper (Loomis, Brunswick, Hotchkiss — table layout)
#   - an <article> wrapper (NMH, Choate, Kent — card layout)
# Both wrappers contain the same inner cell classes, so once we extract the
# block we can use the same opponent / date / score regexes on either.
ROW_RE = re.compile(
    r'<(?P<tag>tr|article)[^>]*class="[^"]*\b(?P<cls>fsResult\w+|fsAthleticsUpcoming\w*)\b[^"]*"[^>]*>(?P<body>.*?)</(?P=tag)>',
    re.DOTALL | re.IGNORECASE,
)

# When a school's page mixes Varsity / JV / Thirds, the team name is in a
# <fsTitle> link or <fsAthleticsTeamName> cell. We default to keeping only
# rows whose title matches "Varsity" (case-insensitive) — schools without
# these labels are unaffected because the regex is anchored to the row body.
VARSITY_RE = re.compile(r"varsity", re.IGNORECASE)
TEAM_TITLE_RE = re.compile(
    r'class="(?:fsTitle|fsAthleticsTeamName)[^"]*"[^>]*>(?:.*?<a[^>]*>)?(?P<title>[^<]+)',
    re.DOTALL | re.IGNORECASE,
)

OPP_RE = re.compile(
    r'class="fsAthleticsOpponentName"[^>]*>\s*(?P<name>[^<]+?)\s*</span>',
    re.DOTALL,
)

# Prefer the ISO datetime attribute — it's unambiguous.
DATETIME_RE = re.compile(
    r'<time[^>]*datetime="(?P<iso>\d{4}-\d{2}-\d{2})[^"]*"',
    re.DOTALL,
)

ADV_RE = re.compile(
    r'class="fsAthleticsAdvantage"[^>]*>\s*(?P<adv>[A-Za-z]+)',
    re.DOTALL,
)

SCORE_RE = re.compile(
    r'class="fsAthleticsScore"[^>]*>\s*(?P<us>\d+)\s*-\s*(?P<them>\d+)',
    re.DOTALL,
)

RESULT_RE = re.compile(
    r'class="fsAthleticsResult"[^>]*>\s*(?P<r>[A-Za-z]+)',
    re.DOTALL,
)


def fetch_html(url: str, timeout: float = 25.0) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (BHTennisBot)",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_finalsite(
    html: str,
    school: str,
    *,
    season_year: int,
    source: str,
    varsity_only: bool = True,
) -> list[dict]:
    """Extract match dicts from a FinalSite schedule page body."""
    matches: list[dict] = []
    for m in ROW_RE.finditer(html):
        body = m.group("body")

        # If this is a multi-team page (NMH, Choate, etc.), keep only Varsity rows.
        if varsity_only:
            title_m = TEAM_TITLE_RE.search(body)
            if title_m and not VARSITY_RE.search(title_m.group("title")):
                continue

        opp_m = OPP_RE.search(body)
        if not opp_m:
            continue
        opp = opp_m.group("name").strip()

        dt_m = DATETIME_RE.search(body)
        if not dt_m:
            continue
        iso = dt_m.group("iso")
        try:
            d = datetime.strptime(iso, "%Y-%m-%d")
        except ValueError:
            continue
        # If the page is a multi-season archive, snap stray years to the
        # requested season for downstream consistency. (Most FinalSite
        # pages return only the current season anyway.)
        date = d.strftime("%m/%d/%Y")

        adv_m = ADV_RE.search(body)
        adv = adv_m.group("adv").strip().lower() if adv_m else ""
        is_home = adv.startswith("home") or adv.startswith("h")

        # Score (only present if the match has been played)
        sc_m = SCORE_RE.search(body)
        completed = sc_m is not None
        if completed:
            us = int(sc_m.group("us"))
            them = int(sc_m.group("them"))
        else:
            us = them = None

        if is_home:
            home, away = school, opp
            hs, as_ = us, them
        else:
            home, away = opp, school
            hs, as_ = them, us

        entry = {
            "date": date,
            "home": home,
            "away": away,
            "status": "completed" if completed else "scheduled",
            "source": source,
        }
        if completed:
            entry["home_score"] = hs
            entry["away_score"] = as_
        matches.append(entry)

    return matches


def fetch_finalsite_matches(
    school: str,
    url: str,
    *,
    season_year: int | None = None,
    source: str | None = None,
) -> list[dict]:
    if season_year is None:
        season_year = datetime.now().year
    html = fetch_html(url)
    src = source or f"finalsite:{school.split()[0].lower()}"
    return parse_finalsite(html, school, season_year=season_year, source=src)


def main(argv: Iterable[str]) -> int:
    args = list(argv)
    if len(args) < 2:
        print("usage: fetch_finalsite.py SCHOOL_NAME URL [--season-year YYYY]", file=sys.stderr)
        return 2
    school, url = args[0], args[1]
    season_year = None
    if "--season-year" in args:
        i = args.index("--season-year")
        season_year = int(args[i + 1])
    matches = fetch_finalsite_matches(school, url, season_year=season_year)
    print(json.dumps(matches, indent=2))
    print(
        f"\n# {len(matches)} rows · "
        f"completed={sum(1 for x in matches if x['status']=='completed')} · "
        f"scheduled={sum(1 for x in matches if x['status']=='scheduled')}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
