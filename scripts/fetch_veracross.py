#!/usr/bin/env python3
"""
Fetch and parse Veracross team ICS calendar feeds.

A lot of Founders League / NEPSAC Class A schools host their athletics
schedules on Veracross. They expose each team's calendar as an .ics feed
at api.veracross.com/{org}/teams/{team_id}.ics?t={token}&uid={uid}, and
the schedule rows on the public site are just "Add to Calendar" buttons
linking to that same URL.

The ICS DESCRIPTION often looks like:
  "Varsity Tennis vs. Loomis Chaffee School -- (score: 4 - 3)"
or:
  "Varsity Tennis at Choate Rosemary Hall"  (no score yet → scheduled)

We parse the SUMMARY/DESCRIPTION to extract:
  - opponent name
  - is_home  ("vs." = home, "at" = away)
  - score (when present), recorded from the OWNING school's perspective

Usage:
  python3 scripts/fetch_veracross.py SCHOOL_NAME ICS_URL [--source TAG]

Importable:
  from fetch_veracross import fetch_veracross_matches
  matches = fetch_veracross_matches(school, ics_url)
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from datetime import datetime
from typing import Iterable

# Match the ICS event blocks (very permissive — Veracross is well-formed)
EVENT_RE = re.compile(r"BEGIN:VEVENT(.*?)END:VEVENT", re.DOTALL)
DTSTART_RE = re.compile(r"DTSTART(?:;[^:]*)?:(\d{8})", re.MULTILINE)
SUMMARY_RE = re.compile(r"^SUMMARY:(.*)$", re.MULTILINE)
DESC_RE = re.compile(r"^DESCRIPTION:(.*)$", re.MULTILINE)

# "Varsity Tennis vs. Loomis Chaffee School -- (score: 4 - 3)"
# or just "Varsity Tennis vs. Loomis Chaffee School"
EVENT_BODY_RE = re.compile(
    r"^(?P<sport>.+?)\s+(?P<rel>vs\.?|at)\s+(?P<opp>.+?)(?:\s*--\s*\(score:\s*(?P<us>\d+)\s*-\s*(?P<them>\d+)\))?\s*$",
    re.IGNORECASE,
)


def fetch_html(url: str, timeout: float = 20.0) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (BHTennisBot)",
            "Accept": "text/calendar, text/plain, */*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _unescape_ics(s: str) -> str:
    # ICS line continuations sometimes happen — fold soft-wrapped lines
    s = re.sub(r"\r?\n[ \t]", "", s)
    return s.replace(r"\,", ",").replace(r"\;", ";").replace(r"\\n", " ").replace(r"\n", " ").replace(r"\\", "\\")


def _parse_date(yyyymmdd: str) -> str | None:
    try:
        return datetime.strptime(yyyymmdd, "%Y%m%d").strftime("%m/%d/%Y")
    except ValueError:
        return None


def parse_veracross_ics(text: str, school: str, *, source: str) -> list[dict]:
    """Extract match dicts from a Veracross ICS body."""
    matches: list[dict] = []
    # Fold continuation lines first (RFC 5545 — line begins with space/tab)
    text = re.sub(r"\r?\n[ \t]", "", text)
    for raw_event in EVENT_RE.findall(text):
        dts = DTSTART_RE.search(raw_event)
        if not dts:
            continue
        date = _parse_date(dts.group(1))
        if not date:
            continue
        sm = SUMMARY_RE.search(raw_event)
        ds = DESC_RE.search(raw_event)
        # Prefer DESCRIPTION (it has the score) — fall back to SUMMARY if missing
        body = _unescape_ics((ds.group(1) if ds else (sm.group(1) if sm else "")).strip())
        if not body:
            continue
        m = EVENT_BODY_RE.match(body)
        if not m:
            continue
        opp = m.group("opp").strip()
        # Trim a trailing " - (score:..." if our regex didn't catch a weird format
        opp = re.sub(r"\s*--?\s*\(.*?\).*$", "", opp).strip()
        is_home = m.group("rel").lower().startswith("vs")
        us = m.group("us")
        them = m.group("them")
        completed = us is not None and them is not None
        if is_home:
            home, away = school, opp
            hs = int(us) if completed else None
            as_ = int(them) if completed else None
        else:
            home, away = opp, school
            hs = int(them) if completed else None
            as_ = int(us) if completed else None
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


def fetch_veracross_matches(
    school: str,
    ics_url: str,
    *,
    source: str | None = None,
) -> list[dict]:
    text = fetch_html(ics_url)
    src = source or f"veracross:{school.split()[0].lower()}"
    return parse_veracross_ics(text, school, source=src)


def main(argv: Iterable[str]) -> int:
    args = list(argv)
    if len(args) < 2:
        print("usage: fetch_veracross.py SCHOOL_NAME ICS_URL [--source TAG]", file=sys.stderr)
        return 2
    school, url = args[0], args[1]
    source = None
    if "--source" in args:
        i = args.index("--source")
        source = args[i + 1]
    matches = fetch_veracross_matches(school, url, source=source)
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
