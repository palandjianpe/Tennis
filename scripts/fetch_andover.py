#!/usr/bin/env python3
"""
Fetch and parse Phillips Academy Andover's athletics schedule.

Andover hosts a custom CMS at athletics.andover.edu (not SIDEARM, not FinalSite).
Each event is wrapped in a <section class="event__wrapper"> with predictable
inner structure:

    <section class="event__wrapper">
      <div class="event-head date-time">
        <div class="event-date">04.29</div>          <- MM.DD (no year)
      </div>
      <div class="event-body">
        <div class="team team-home">
          <a class="event-opponent">Tennis BV</a>    <- Andover's own team name
          <p class="event-result">7</p>              <- score (blank if upcoming)
        </div>
        <div class="team team-away">
          <span class="location-txt">A</span>        <- A=Andover-Away, H=Andover-Home
          <p class="event-opponent">Phillips Exeter Academy</p>
          <p class="event-result">0</p>
        </div>
      </div>
    </section>

The first team slot is always Andover; the second is the opponent. The "A"/"H"
location-txt tells us where Andover played. Scores live in the per-team
event-result <p> tags — empty <p> means the match hasn't been played yet.

Usage:
  python3 scripts/fetch_andover.py [--season-year YYYY]

Importable:
  from fetch_andover import fetch_andover_matches
  matches = fetch_andover_matches(season_year=2026)
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from datetime import datetime
from typing import Iterable

DEFAULT_URL = "https://athletics.andover.edu/teams/btev/schedule"

EVENT_RE = re.compile(
    r'<section[^>]*class="event__wrapper"[^>]*>(?P<body>.*?)</section>',
    re.DOTALL | re.IGNORECASE,
)
DATE_RE = re.compile(
    r'class="event-date"[^>]*>\s*(?P<m>\d{1,2})\.(?P<d>\d{1,2})',
    re.DOTALL,
)
HOME_BLOCK_RE = re.compile(
    r'class="team team-home[^"]*"[^>]*>(?P<inner>.*?)</div>\s*<div class="team team-away',
    re.DOTALL,
)
AWAY_BLOCK_RE = re.compile(
    r'class="team team-away[^"]*"[^>]*>(?P<inner>.*)',
    re.DOTALL,
)
LOCATION_RE = re.compile(r'class="location-txt"[^>]*>\s*(?P<loc>[A-Z])')
OPP_RE = re.compile(r'class="event-opponent"[^>]*>(?P<text>[^<]+)')
RESULT_RE = re.compile(r'class="event-result"[^>]*>(?P<r>\d+)\s*<')
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def _clean(s: str) -> str:
    return WS_RE.sub(" ", TAG_RE.sub("", s)).strip()


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


def parse_andover(html: str, *, season_year: int, source: str) -> list[dict]:
    matches: list[dict] = []
    for m in EVENT_RE.finditer(html):
        body = m.group("body")

        date_m = DATE_RE.search(body)
        if not date_m:
            continue
        try:
            month = int(date_m.group("m"))
            day = int(date_m.group("d"))
            date = datetime(season_year, month, day).strftime("%m/%d/%Y")
        except ValueError:
            continue

        home_b = HOME_BLOCK_RE.search(body)
        away_b = AWAY_BLOCK_RE.search(body)
        if not home_b or not away_b:
            continue

        # The OPPONENT name is in the AWAY block; HOME slot is always "Tennis BV".
        opp_m = OPP_RE.search(away_b.group("inner"))
        if not opp_m:
            continue
        opp = _clean(opp_m.group("text"))
        if not opp:
            continue

        # Location: "A" = Andover Away, "H" = Andover Home (or absent for Home)
        loc_m = LOCATION_RE.search(body)
        andover_is_home = not (loc_m and loc_m.group("loc").upper() == "A")

        # Scores — first event-result in HOME slot is Andover's, in AWAY is opponent's
        andover_score_m = RESULT_RE.search(home_b.group("inner"))
        opp_score_m = RESULT_RE.search(away_b.group("inner"))

        completed = andover_score_m is not None and opp_score_m is not None
        if completed:
            us = int(andover_score_m.group("r"))
            them = int(opp_score_m.group("r"))
        else:
            us = them = None

        if andover_is_home:
            home, away = "Phillips Academy Andover", opp
            hs, as_ = us, them
        else:
            home, away = opp, "Phillips Academy Andover"
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


def fetch_andover_matches(
    *,
    url: str = DEFAULT_URL,
    season_year: int | None = None,
    source: str = "andover_site",
) -> list[dict]:
    if season_year is None:
        # Andover's spring tennis season → use the year of "now" if we're in spring,
        # otherwise the next spring. Pragmatic default: current year.
        season_year = datetime.now().year
    html = fetch_html(url)
    return parse_andover(html, season_year=season_year, source=source)


def main(argv: Iterable[str]) -> int:
    args = list(argv)
    season_year = None
    if "--season-year" in args:
        i = args.index("--season-year")
        season_year = int(args[i + 1])
    matches = fetch_andover_matches(season_year=season_year)
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
