#!/usr/bin/env python3
"""
Fetch and parse SIDEARM Sports / PrestoSports schedule pages.

SIDEARM is the platform behind athletics.andover.edu, weareexeter.com,
athletics.sps.edu, and many other prep / college athletic departments.
Their schedule pages serve all match data inline as HTML — every game is
a `<div class="sidearm-schedule-game ...">` block with data attributes
and well-named child divs.

Each block tells us, from the OWNING school's perspective:
  * home or away (`sidearm-schedule-home-game` / `sidearm-schedule-away-game`)
  * completed or upcoming (`sidearm-schedule-game-completed` / `upcoming-game`)
  * a result string like "W, 7-0" or "L, 3-4" (us first, them second)
  * the opponent's name
  * the calendar date as "Mon D" (no year — we infer from the season)

Usage:
  python3 scripts/fetch_sidearm.py SCHOOL_NAME SCHEDULE_URL [--season-year YYYY]

  python3 scripts/fetch_sidearm.py "Phillips Exeter Academy" \
    https://weareexeter.com/sports/mens-tennis/schedule/2026

Importable:
  from fetch_sidearm import fetch_sidearm_matches
  matches = fetch_sidearm_matches(school, url, season_year=2026)
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from datetime import datetime
from typing import Iterable

GAME_RE = re.compile(
    # SIDEARM wraps each game in either <li> or <div>; we don't care which.
    r'class="sidearm-schedule-game (?P<classes>[^"]+)"[^>]*data-game-id="(?P<gid>\d+)"',
    re.DOTALL,
)
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
DATE_RE = re.compile(
    r'class="sidearm-schedule-game-opponent-date[^"]*"[^>]*>\s*<span>([^<]+)</span>',
    re.DOTALL,
)
# Opponent name lives inside `sidearm-schedule-game-opponent-name`. Some sites
# (Phillips Exeter) put the name as plain text right after the div; others
# (St. Paul's) wrap it in an <a aria-label="..."> tag. We capture the entire
# inner div then strip tags, which handles both shapes.
OPP_RE = re.compile(
    r'class="sidearm-schedule-game-opponent-name"\s*>(?P<inner>.*?)</div>',
    re.DOTALL,
)
RESULT_RE = re.compile(
    r'class="sidearm-schedule-game-result[^"]*"[^>]*>(?P<inner>.*?)</div>',
    re.DOTALL,
)
SCORE_RE = re.compile(r'(\d+)\s*-\s*(\d+)')


def _clean(s: str) -> str:
    return WS_RE.sub(" ", TAG_RE.sub("", s)).strip()


def _slice_block(html: str, start: int, end: int) -> str:
    return html[start:end]


def _parse_date(raw: str, season_year: int) -> str | None:
    """Parse 'Apr 1 (Wed)' style date strings into MM/DD/YYYY."""
    if not raw:
        return None
    raw = raw.strip()
    # Strip trailing parenthetical ("(Wed)") and any extra junk.
    raw = re.sub(r"\s*\([^)]*\)\s*$", "", raw).strip()
    # Try common SIDEARM formats.
    for fmt in ("%b %d", "%B %d", "%m/%d", "%b %d, %Y"):
        try:
            dt = datetime.strptime(raw, fmt)
            year = dt.year if dt.year != 1900 else season_year
            return dt.replace(year=year).strftime("%m/%d/%Y")
        except ValueError:
            continue
    return None


def fetch_html(url: str, timeout: float = 20.0) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (BHTennisBot)",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_sidearm(
    html: str,
    school: str,
    *,
    season_year: int,
    source: str = "sidearm",
) -> list[dict]:
    """Extract match dicts from a SIDEARM schedule HTML body."""
    matches: list[dict] = []
    starts = [m.start() for m in GAME_RE.finditer(html)]
    starts.append(len(html))
    for i in range(len(starts) - 1):
        block = html[starts[i] : starts[i + 1]]
        m = GAME_RE.search(block)
        if not m:
            continue
        classes = m.group("classes")
        is_home = "sidearm-schedule-home-game" in classes
        is_away = "sidearm-schedule-away-game" in classes
        if not (is_home or is_away):
            # Neutral-site games we'll still record as "home" for the owning school.
            is_home = True
        completed = "sidearm-schedule-game-completed" in classes
        # Date
        date_match = DATE_RE.search(block)
        date = _parse_date(date_match.group(1) if date_match else "", season_year)
        if not date:
            continue
        # Opponent — strip any wrapping <a>/<span> tags then collapse whitespace.
        opp_match = OPP_RE.search(block)
        opponent = _clean(opp_match.group("inner")) if opp_match else ""
        if not opponent:
            continue
        # Result
        score_us = score_them = None
        if completed:
            result_match = RESULT_RE.search(block)
            if result_match:
                inner = _clean(result_match.group("inner"))
                score = SCORE_RE.search(inner)
                if score:
                    score_us = int(score.group(1))
                    score_them = int(score.group(2))
        # Map perspective into canonical home/away.
        if is_home:
            home, away = school, opponent
            hs, as_ = score_us, score_them
        else:
            home, away = opponent, school
            hs, as_ = score_them, score_us
        entry = {
            "date": date,
            "home": home,
            "away": away,
            "status": "completed" if (hs is not None and as_ is not None) else "scheduled",
            "source": source,
        }
        if entry["status"] == "completed":
            entry["home_score"] = hs
            entry["away_score"] = as_
        matches.append(entry)
    return matches


def fetch_sidearm_matches(
    school: str,
    url: str,
    *,
    season_year: int | None = None,
    source: str | None = None,
) -> list[dict]:
    if season_year is None:
        # Try to guess the season year from the URL (e.g. /schedule/2026 → 2026).
        m = re.search(r"/(\d{4})(?:/|$|\?)", url)
        season_year = int(m.group(1)) if m else datetime.now().year
    html = fetch_html(url)
    src = source or f"sidearm:{school.split()[0].lower()}"
    return parse_sidearm(html, school, season_year=season_year, source=src)


def main(argv: Iterable[str]) -> int:
    args = list(argv)
    if len(args) < 2:
        print("usage: fetch_sidearm.py SCHOOL_NAME URL [--season-year YYYY]", file=sys.stderr)
        return 2
    school, url = args[0], args[1]
    season_year = None
    if "--season-year" in args:
        i = args.index("--season-year")
        season_year = int(args[i + 1])
    matches = fetch_sidearm_matches(school, url, season_year=season_year)
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
