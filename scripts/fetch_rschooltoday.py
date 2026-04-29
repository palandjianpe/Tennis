#!/usr/bin/env python3
"""
Fetch and parse rSchoolToday widget HTML to extract completed matches.

Why this exists:
  Most school athletics pages are JS-rendered and unparseable by plain HTTP.
  The rSchoolToday "Custom_widget" page, however, ships the full schedule
  inline in the initial HTML response (in `asc-perday-row` blocks). The
  ISL's league-level widget alone contains every Boys Tennis match for
  the season — making it the single highest-leverage source.

Usage:
  python3 scripts/fetch_rschooltoday.py [WIDGET_URL_OR_UUID]
  python3 scripts/fetch_rschooltoday.py            # defaults to ISL widget

Output:
  JSON list of dicts with keys: date, home, away, home_score, away_score,
  status, source. Status is "completed" iff both scores are present.

Importable:
  from fetch_rschooltoday import fetch_widget_matches
  matches = fetch_widget_matches(uuid_or_url)
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
import urllib.error
from typing import Iterable

ISL_BOYS_TENNIS_UUID = "fef0129c-6fc2-11f0-ba9f-064bb7083971"
WIDGET_BASE = "https://api.rschooltoday.com/widget/"

# Each match block looks like (whitespace-collapsed):
#   <div class="asc-perday-row">
#     <div class="asc-pc-day-title"> MM/DD/YYYY </div>
#     <div class="asc-perday-row-info show" data-date="MM/DD/YYYY" data-team="..." ...>
#       <div class="asc-col asc-col-start_time ...">...<div class="">TBD</div>...</div>
#       <div class="asc-col asc-col-type ...">          <div class="">Match</div></div>
#       <div class="asc-col asc-col-home_team ...">     <div class="">HOME</div></div>
#       <div class="asc-col asc-col-home_score ...">    <div class="">N</div></div>
#       <div class="asc-col asc-col-opponent ...">      <div class="">AWAY</div></div>
#       <div class="asc-col asc-col-visitor_score ...">  <div class="">N</div></div>
#       ...
#
# Some rows have empty score divs (= scheduled, not played).

ROW_OPEN_RE = re.compile(
    r'<div class="asc-perday-row-info[^"]*"[^>]*data-date="(?P<date>\d{2}/\d{2}/\d{4})"[^>]*>'
)
COL_RE = re.compile(
    r'<div class="asc-col asc-col-(?P<col>[a-z_]+)[^"]*"[^>]*>'
    r'\s*<div[^>]*>(?P<val>.*?)</div>',
    re.DOTALL,
)
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def _clean(s: str) -> str:
    s = TAG_RE.sub("", s)
    s = WS_RE.sub(" ", s)
    return s.strip()


def _to_int(s: str):
    s = _clean(s)
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def fetch_html(url_or_uuid: str, timeout: float = 20.0) -> str:
    """Fetch the widget HTML. Accepts a full URL or a bare UUID."""
    url = url_or_uuid
    if not url.startswith("http"):
        url = WIDGET_BASE + url_or_uuid
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (BHTennisBot)",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_widget(html: str, *, source: str = "rschooltoday") -> list[dict]:
    """Extract match dicts from a fetched widget HTML body.

    The widget never closes `asc-perday-row-info` divs cleanly enough for a
    pure regex slice, so we split the document by row openings and parse
    each chunk up to the next row opening (or end of document).
    """
    matches = []
    opens = list(ROW_OPEN_RE.finditer(html))
    boundaries = [m.start() for m in opens] + [len(html)]
    for i, m in enumerate(opens):
        date = m.group("date")
        chunk = html[m.end() : boundaries[i + 1]]
        cols = {c.group("col"): _clean(c.group("val")) for c in COL_RE.finditer(chunk)}
        home = cols.get("home_team") or ""
        away = cols.get("opponent") or ""
        if not home or not away:
            continue
        # Skip non-match rows defensively (some widgets list practices/scrimmages).
        type_ = (cols.get("type") or "").lower()
        if type_ and "match" not in type_ and "game" not in type_ and "meet" not in type_:
            # Keep anyway if scores are present — better to over-collect.
            pass
        hs = _to_int(cols.get("home_score") or "")
        as_ = _to_int(cols.get("visitor_score") or "")
        status = "completed" if hs is not None and as_ is not None else "scheduled"
        entry = {
            "date": date,
            "home": home,
            "away": away,
            "status": status,
            "source": source,
        }
        if status == "completed":
            entry["home_score"] = hs
            entry["away_score"] = as_
        matches.append(entry)
    return matches


def fetch_widget_matches(url_or_uuid: str, *, source: str | None = None) -> list[dict]:
    src = source or f"rschooltoday:{url_or_uuid[-12:]}"
    html = fetch_html(url_or_uuid)
    return parse_widget(html, source=src)


def main(argv: Iterable[str]) -> int:
    args = list(argv)
    target = args[0] if args else ISL_BOYS_TENNIS_UUID
    matches = fetch_widget_matches(target, source="isl_feed")
    print(json.dumps(matches, indent=2))
    print(
        f"\n# {len(matches)} rows · "
        f"completed={sum(1 for m in matches if m['status']=='completed')} · "
        f"scheduled={sum(1 for m in matches if m['status']=='scheduled')}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
