#!/usr/bin/env python3
"""
Renders index.html (the dashboard) from data/matches.json + data/schools.json.

Usage: python3 scripts/render_dashboard.py

Outputs:
  - index.html                       (the dashboard, served by GitHub Pages at root)
  - ISL_Tennis_Report_2026.html      (legacy filename, redirects to index.html)

Edit data/matches.json by hand to add new scores. Each match looks like:
  {"date": "MM/DD/YYYY", "home": "...", "away": "...",
   "home_score": 4, "away_score": 3,
   "status": "completed" | "scheduled" | "cancelled" | "scrimmage",
   "source": "..."}

The renderer computes Elo ratings from completed matches (with margin weighting),
then displays win probabilities for every scheduled matchup in the H2H matrices
and in a top-of-page Predictions section.
"""
import json, os, sys, math
from datetime import datetime
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUTPUT = ROOT / "index.html"
LEGACY_OUTPUT = ROOT / "ISL_Tennis_Report_2026.html"

# Brand
CRIMSON = "#8E1838"
NAVY = "#222D65"

# Elo knobs
ELO_BASE = 1500.0
ELO_K = 32.0
ELO_MARGIN_FACTOR = 0.6  # margin 1->1.0x, 7->1.6x — bigger blowouts move more
LOW_CONFIDENCE_GAMES = 3

with open(DATA / "schools.json") as f:
    schools = json.load(f)
with open(DATA / "matches.json") as f:
    db = json.load(f)

ALIASES = schools["name_aliases"]
ISL_SCHOOLS = schools["isl"]
CLASS_A_ONLY = schools["class_a_only"]
ALL_CLASS_A = {**{k: v for k, v in ISL_SCHOOLS.items() if v.get("class_a")}, **CLASS_A_ONLY}

def canonicalize(name: str) -> str:
    return ALIASES.get(name.strip(), name.strip())

# Normalize all match names through aliases
matches = []
for m in db["matches"]:
    matches.append({
        **m,
        "home": canonicalize(m["home"]),
        "away": canonicalize(m["away"]),
    })

today = datetime.today().strftime("%B %-d, %Y") if sys.platform != "win32" else datetime.today().strftime("%B %#d, %Y")

# ============================
# Status helpers
# ============================
def is_completed(m):
    return m.get("status") == "completed" and m.get("home_score") is not None and m.get("away_score") is not None

# ============================
# Elo computation
# ============================
def compute_elo(matches):
    """Compute Elo rating for each team based on completed matches in chronological order.

    Tennis dual-meet matches are 7-point. Margin multiplier scales the rating
    swing: 1-point win is normal, a 7-0 sweep moves ratings ~1.6x as much.
    """
    ratings = defaultdict(lambda: ELO_BASE)
    games = defaultdict(int)
    sorted_completed = sorted(
        [m for m in matches if is_completed(m)],
        key=lambda m: datetime.strptime(m["date"], "%m/%d/%Y")
    )
    for m in sorted_completed:
        try:
            hs, as_ = int(m["home_score"]), int(m["away_score"])
        except (ValueError, TypeError):
            continue
        if hs == as_:
            continue
        h, a = m["home"], m["away"]
        margin = abs(hs - as_)
        # Margin multiplier: 1 -> 1.0, 7 -> 1.0 + 0.6 = 1.6
        margin_mult = 1.0 + ELO_MARGIN_FACTOR * (margin - 1) / 6.0
        # Expected probability
        E_h = 1.0 / (1.0 + 10 ** ((ratings[a] - ratings[h]) / 400.0))
        S_h = 1.0 if hs > as_ else 0.0
        delta = ELO_K * margin_mult * (S_h - E_h)
        ratings[h] += delta
        ratings[a] -= delta
        games[h] += 1
        games[a] += 1
    return dict(ratings), dict(games)

def win_probability(rating_a, rating_b):
    """Probability that team A beats team B (Elo formula)."""
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))

elo_ratings, elo_games = compute_elo(matches)

def elo_for(team):
    return elo_ratings.get(team, ELO_BASE)

def games_for(team):
    return elo_games.get(team, 0)

# ============================
# Compute records
# ============================
def compute_records(team_pool, h2h_pool):
    record = {full: {"w": 0, "l": 0, "t": 0} for full in team_pool}
    h2h = {full: {} for full in team_pool}
    scheduled = {full: {} for full in team_pool}
    for m in matches:
        h, a = m["home"], m["away"]
        if is_completed(m):
            try:
                hs, as_ = int(m["home_score"]), int(m["away_score"])
            except (ValueError, TypeError):
                continue
            if h in team_pool and a in h2h_pool:
                if hs > as_: record[h]["w"] += 1
                elif hs < as_: record[h]["l"] += 1
                else: record[h]["t"] += 1
            if a in team_pool and h in h2h_pool:
                if as_ > hs: record[a]["w"] += 1
                elif as_ < hs: record[a]["l"] += 1
                else: record[a]["t"] += 1
            if h in team_pool and a in team_pool:
                res_h = "W" if hs > as_ else ("L" if hs < as_ else "T")
                res_a = "L" if hs > as_ else ("W" if hs < as_ else "T")
                h2h[h][a] = (res_h, f"{hs}-{as_}", m["date"])
                h2h[a][h] = (res_a, f"{as_}-{hs}", m["date"])
        elif m.get("status") == "scheduled":
            if h in team_pool and a in team_pool:
                if a not in h2h.get(h, {}):
                    scheduled[h][a] = m["date"]
                if h not in h2h.get(a, {}):
                    scheduled[a][h] = m["date"]
    return record, h2h, scheduled

ISL_FULL = set(ISL_SCHOOLS.keys())
CLASS_A_FULL = set(ALL_CLASS_A.keys())
ANY_TEAM = set([m["home"] for m in matches] + [m["away"] for m in matches])

isl_record, isl_h2h, isl_scheduled = compute_records(ISL_FULL, ISL_FULL)
ca_record, ca_h2h, ca_scheduled = compute_records(CLASS_A_FULL, CLASS_A_FULL)
total_record, _, _ = compute_records(ISL_FULL, ANY_TEAM)
ca_overall_record, _, _ = compute_records(CLASS_A_FULL, ANY_TEAM)

# Apply known external Class A records
ca_known_overall = {
    "Phillips Academy Andover": (2, 6),
    "Brunswick School": (1, 0),
    "Deerfield Academy": (1, 1),
}
for full, (w, l) in ca_known_overall.items():
    cur = ca_overall_record[full]
    if cur["w"] + cur["l"] < w + l:
        ca_overall_record[full] = {"w": w, "l": l, "t": 0}

def build_standings(record, pool_meta):
    out = []
    for full, meta in pool_meta.items():
        r = record.get(full, {"w": 0, "l": 0, "t": 0})
        total = r["w"] + r["l"] + r["t"]
        pct = r["w"] / total if total else 0
        out.append({
            "full": full,
            "short": meta["short"],
            "abbr": meta.get("abbr", meta["short"]),
            "w": r["w"], "l": r["l"], "t": r["t"], "pct": pct, "total": total,
            "elo": elo_for(full),
            "elo_games": games_for(full),
        })
    out.sort(key=lambda d: (-d["pct"], -d["w"], d["l"], d["short"]))
    return out

isl_standings = build_standings(isl_record, ISL_SCHOOLS)
ca_standings_only = build_standings(ca_record, ALL_CLASS_A)
total_standings = build_standings(total_record, ISL_SCHOOLS)

# Class A combined standings
ca_combined = []
for full, meta in ALL_CLASS_A.items():
    ca_only = ca_record[full]
    overall = ca_overall_record.get(full, {"w": 0, "l": 0, "t": 0})
    ca_combined.append({
        "full": full,
        "short": meta["short"],
        "abbr": meta.get("abbr", meta["short"]),
        "in_isl": full in ISL_FULL,
        "a_w": ca_only["w"], "a_l": ca_only["l"],
        "a_pct": ca_only["w"] / (ca_only["w"] + ca_only["l"]) if (ca_only["w"] + ca_only["l"]) else 0,
        "ovr_w": overall["w"], "ovr_l": overall["l"],
        "elo": elo_for(full),
        "elo_games": games_for(full),
    })
ca_combined.sort(key=lambda x: (-x["a_pct"], -x["a_w"], x["a_l"], -x["ovr_w"], x["ovr_l"], x["short"]))

# ============================
# Helpers
# ============================
def short_date(date_str):
    try:
        d = datetime.strptime(date_str, "%m/%d/%Y")
        return f"{d.month}/{d.day}"
    except ValueError:
        return date_str

def tier_for(rank, total):
    if rank <= 2: return "Championship"
    if rank <= 4: return "Contender"
    if rank <= max(total // 2, 6): return "Competitive"
    return "Developing"

def format_pct(p):
    return f"{round(p*100)}%"

def low_confidence(team):
    return games_for(team) < LOW_CONFIDENCE_GAMES

def h2h_cell(team_full, opp_full, h2h, scheduled):
    if team_full == opp_full:
        return '<td class="diag">—</td>'
    if team_full in h2h and opp_full in h2h[team_full]:
        res, score, date = h2h[team_full][opp_full]
        cls = "win" if res == "W" else ("loss" if res == "L" else "tie")
        return f'<td class="{cls}" title="{date}: {res} {score}"><strong>{res}</strong> {score}</td>'
    if team_full in scheduled and opp_full in scheduled[team_full]:
        date = scheduled[team_full][opp_full]
        # Win probability from team_full's perspective
        p = win_probability(elo_for(team_full), elo_for(opp_full))
        lc = low_confidence(team_full) or low_confidence(opp_full)
        pct_str = format_pct(p)
        if lc:
            return f'<td class="upcoming low-conf" title="Scheduled: {date}. Win probability {pct_str} (low confidence — limited data)">{short_date(date)} · {pct_str}*</td>'
        return f'<td class="upcoming" title="Scheduled: {date}. Win probability {pct_str}">{short_date(date)} · {pct_str}</td>'
    return '<td class="empty"></td>'

def standings_table(standings, show_elo=True):
    rows = ""
    total = len(standings)
    for i, s in enumerate(standings, 1):
        is_bh = s["short"] == "Belmont Hill"
        cls = "bh-row" if is_bh else ("tier-champ" if i <= 2 else "")
        pct = format_pct(s['pct']) if (s["w"] + s["l"]) else "—"
        rec = f"{s['w']}-{s['l']}" if (s["w"] + s["l"]) else "—"
        tier = tier_for(i, total)
        elo_cell = ""
        if show_elo:
            elo = round(s["elo"])
            lc = '*' if low_confidence(s["full"]) else ''
            elo_cell = f'<td><strong>{elo}{lc}</strong></td>'
        rows += f'<tr class="{cls}"><td>{i}</td><td>{s["short"]}</td><td>{rec}</td><td>{pct}</td>{elo_cell}<td><span class="tier tier-{tier}">{tier}</span></td></tr>\n'
    return rows

def h2h_matrix(standings, h2h, scheduled, label_col_name="Record"):
    full_to_short = {s["full"]: s.get("abbr", s["short"]) for s in standings}
    ordered = [s["full"] for s in standings]
    head = '<tr><th class="row-head">Team</th>'
    for f in ordered:
        head += f'<th><div class="col-label">{full_to_short[f]}</div></th>'
    head += f'<th>{label_col_name}</th></tr>'
    body = ""
    for i, full in enumerate(ordered):
        s = standings[i]
        cls = "bh-row" if s["short"] == "Belmont Hill" else ""
        body += f'<tr class="{cls}"><td>{s["short"]}</td>'
        for opp_full in ordered:
            body += h2h_cell(full, opp_full, h2h, scheduled)
        rec = f"{s['w']}-{s['l']}" if (s.get("w", 0) + s.get("l", 0)) else "—"
        body += f'<td><strong>{rec}</strong></td></tr>'
    return f'<table class="matrix"><thead>{head}</thead><tbody>{body}</tbody></table>'

# Class A standings table rows (combined)
ca_table_rows = ""
for i, s in enumerate(ca_combined, 1):
    is_bh = s["short"] == "Belmont Hill"
    cls = "bh-row" if is_bh else ""
    a_rec = f"{s['a_w']}-{s['a_l']}" if (s["a_w"] + s["a_l"]) else "—"
    a_pct = format_pct(s['a_pct']) if (s["a_w"] + s["a_l"]) else "—"
    ovr = f"{s['ovr_w']}-{s['ovr_l']}" if (s["ovr_w"] + s["ovr_l"]) else "TBD"
    isl_badge = ' <span class="badge isl-badge">ISL</span>' if s["in_isl"] else ''
    elo = round(s["elo"])
    lc = '*' if low_confidence(s["full"]) else ''
    ca_table_rows += f'<tr class="{cls}"><td>{i}</td><td>{s["short"]}{isl_badge}</td><td>{a_rec}</td><td>{a_pct}</td><td>{ovr}</td><td><strong>{elo}{lc}</strong></td></tr>\n'

ca_matrix_standings = []
for s in ca_combined:
    ca_matrix_standings.append({
        "full": s["full"], "short": s["short"], "abbr": s["abbr"],
        "w": s["a_w"], "l": s["a_l"], "t": 0, "pct": s["a_pct"],
        "elo": s["elo"], "elo_games": s["elo_games"],
    })

# ============================
# BH match list (with predicted result for upcoming)
# ============================
bh_matches_raw = []
for m in matches:
    if m["home"] == "Belmont Hill" or m["away"] == "Belmont Hill":
        is_home = m["home"] == "Belmont Hill"
        opp = m["away"] if is_home else m["home"]
        if is_completed(m):
            try:
                bh_score = int(m["home_score"] if is_home else m["away_score"])
                opp_score = int(m["away_score"] if is_home else m["home_score"])
                result = "W" if bh_score > opp_score else ("L" if bh_score < opp_score else "T")
                score = f"{bh_score}-{opp_score}"
            except (ValueError, TypeError):
                result = ""; score = "—"
            bh_matches_raw.append({
                "date": m["date"], "home_away": "Home" if is_home else "Away",
                "opp": opp, "score": score, "result": result, "status": "completed",
                "predicted": ""
            })
        elif m.get("status") == "scheduled":
            p = win_probability(elo_for("Belmont Hill"), elo_for(opp))
            lc = low_confidence(opp) or low_confidence("Belmont Hill")
            predicted = format_pct(p) + ("*" if lc else "")
            bh_matches_raw.append({
                "date": m["date"], "home_away": "Home" if is_home else "Away",
                "opp": opp, "score": "—", "result": "", "status": "scheduled",
                "predicted": predicted
            })

bh_matches_raw.sort(key=lambda x: datetime.strptime(x["date"], "%m/%d/%Y"))

# Dedupe by (date, opp) — prefer completed
seen = {}
for m in bh_matches_raw:
    key = (m["date"], m["opp"])
    if key not in seen or m["result"]:
        seen[key] = m
bh_matches = sorted(seen.values(), key=lambda x: datetime.strptime(x["date"], "%m/%d/%Y"))

bh_match_rows = ""
for m in bh_matches:
    if m["result"] == "W": rstyle = ' style="color:var(--win-fg);font-weight:700;"'
    elif m["result"] == "L": rstyle = ' style="color:var(--loss-fg);font-weight:700;"'
    else: rstyle = ''
    pred_cell = f'<td>{m["predicted"]}</td>' if m["predicted"] else '<td></td>'
    bh_match_rows += f'<tr><td>{m["date"]}</td><td>{m["home_away"]}</td><td>{m["opp"]}</td><td>{m["score"]}</td><td{rstyle}>{m["result"]}</td>{pred_cell}</tr>\n'

# ============================
# Recent results
# ============================
completed_matches = [m for m in matches if is_completed(m)]
completed_matches.sort(key=lambda m: datetime.strptime(m["date"], "%m/%d/%Y"), reverse=True)
recent_rows = ""
for m in completed_matches[:18]:
    try:
        hs, as_ = int(m["home_score"]), int(m["away_score"])
    except (ValueError, TypeError):
        continue
    winner = m["home"] if hs > as_ else m["away"]
    loser = m["away"] if hs > as_ else m["home"]
    hi, lo = max(hs, as_), min(hs, as_)
    is_bh = winner == "Belmont Hill" or loser == "Belmont Hill"
    bh_class = ' style="color:var(--crimson);font-weight:700;"' if is_bh else ''
    recent_rows += f'<tr><td>{m["date"]}</td><td{bh_class}><strong>{winner}</strong></td><td>def.</td><td{bh_class}>{loser}</td><td><strong>{hi}-{lo}</strong></td></tr>\n'

# ============================
# Class A vs Class A — played + upcoming
# ============================
ca_match_li = ""
ca_played = sorted([m for m in matches if is_completed(m) and m["home"] in CLASS_A_FULL and m["away"] in CLASS_A_FULL],
                   key=lambda x: datetime.strptime(x["date"], "%m/%d/%Y"))
for m in ca_played:
    try:
        hs, as_ = int(m["home_score"]), int(m["away_score"])
    except (ValueError, TypeError):
        continue
    winner = m["home"] if hs > as_ else m["away"]
    loser = m["away"] if hs > as_ else m["home"]
    hi, lo = max(hs, as_), min(hs, as_)
    src_str = f' <span class="note">— per {m.get("source", "ISL feed")}</span>' if m.get("source") else ""
    ca_match_li += f'<li><strong>{m["date"]}</strong> &nbsp; <strong>{winner}</strong> def. {loser} &nbsp; {hi}-{lo}{src_str}</li>\n'

ca_upcoming = sorted([m for m in matches if m.get("status") == "scheduled"
                      and m["home"] in CLASS_A_FULL and m["away"] in CLASS_A_FULL],
                     key=lambda x: datetime.strptime(x["date"], "%m/%d/%Y"))
ca_upcoming_li = ""
for m in ca_upcoming:
    p = win_probability(elo_for(m["home"]), elo_for(m["away"]))
    favored = m["home"] if p >= 0.5 else m["away"]
    fav_p = max(p, 1 - p)
    lc = low_confidence(m["home"]) or low_confidence(m["away"])
    star = '*' if lc else ''
    ca_upcoming_li += f'<li><strong>{m["date"]}</strong> &nbsp; {m["home"]} <em>vs</em> {m["away"]} &nbsp; <span class="note">{favored} {format_pct(fav_p)}{star}</span></li>\n'

# ============================
# Predictions: top upcoming matches by closeness
# ============================
def get_predictions(team_pool=None):
    """Get all upcoming matches with win probabilities, sorted by closeness."""
    preds = []
    seen_keys = set()
    for m in matches:
        if m.get("status") != "scheduled": continue
        h, a = m["home"], m["away"]
        if team_pool is not None and (h not in team_pool or a not in team_pool): continue
        # Skip duplicates
        key = (m["date"], min(h, a), max(h, a))
        if key in seen_keys: continue
        seen_keys.add(key)
        # Skip if either team has 0 games (truly unknown)
        if games_for(h) == 0 and games_for(a) == 0: continue
        p_home = win_probability(elo_for(h), elo_for(a))
        favored = h if p_home >= 0.5 else a
        underdog = a if p_home >= 0.5 else h
        fav_p = max(p_home, 1 - p_home)
        closeness = abs(p_home - 0.5)
        lc = low_confidence(h) or low_confidence(a)
        preds.append({
            "date": m["date"],
            "home": h, "away": a,
            "favored": favored, "underdog": underdog,
            "fav_p": fav_p,
            "closeness": closeness,
            "lc": lc,
        })
    return preds

# All upcoming matches involving any ISL team (most relevant to BH)
all_preds = get_predictions(ISL_FULL | CLASS_A_FULL)

# Closest upcoming matches (most uncertain — most interesting)
closest_preds = sorted(all_preds, key=lambda p: (p["closeness"], datetime.strptime(p["date"], "%m/%d/%Y")))[:8]
# Upcoming BH-specific
bh_preds = sorted([p for p in all_preds if p["home"] == "Belmont Hill" or p["away"] == "Belmont Hill"],
                  key=lambda p: datetime.strptime(p["date"], "%m/%d/%Y"))

def render_predictions_list(preds, show_bh_perspective=False):
    rows = ""
    for p in preds:
        star = '*' if p["lc"] else ''
        if show_bh_perspective and (p["home"] == "Belmont Hill" or p["away"] == "Belmont Hill"):
            opp = p["away"] if p["home"] == "Belmont Hill" else p["home"]
            bh_p = win_probability(elo_for("Belmont Hill"), elo_for(opp))
            bh_pct = format_pct(bh_p)
            verdict = "favored" if bh_p >= 0.5 else "underdog"
            color = 'var(--win-fg)' if bh_p >= 0.5 else 'var(--loss-fg)'
            rows += f'<tr><td>{p["date"]}</td><td>vs {opp}</td><td style="color:{color};font-weight:700;">BH {bh_pct}{star} ({verdict})</td></tr>'
        else:
            close_label = ""
            if p["closeness"] < 0.10:
                close_label = ' <span class="badge close-badge">PICKEM</span>'
            rows += f'<tr><td>{p["date"]}</td><td>{p["home"]} vs {p["away"]}</td><td><strong>{p["favored"]}</strong> {format_pct(p["fav_p"])}{star}{close_label}</td></tr>'
    return rows

# ============================
# Season snapshot for cards
# ============================
co_leaders = [s for s in isl_standings if s["w"] > 0 and s["l"] == 0]
co_leader_names = ", ".join([s["short"] for s in co_leaders[:2]]) or "TBD"
total_completed = len(completed_matches)
total_scheduled = sum(1 for m in matches if m.get("status") == "scheduled")

# Top Elo (for context)
top_elo = sorted([s for s in isl_standings if s["elo_games"] >= LOW_CONFIDENCE_GAMES],
                 key=lambda s: -s["elo"])[:3]
top_elo_names = " · ".join(f"{s['short']} ({round(s['elo'])})" for s in top_elo) or "TBD"

# ============================
# HTML
# ============================
html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>2026 ISL & NEPSAC Class A Tennis — Belmont Hill</title>
<style>
:root {{ --crimson: {CRIMSON}; --navy: {NAVY}; --black: #201E1E; --offwhite: #FAFAFA;
  --parchment: #EEECE1; --win-bg: #DCEFD8; --win-fg: #2D6B2A;
  --loss-bg: #FCE0E0; --loss-fg: #A02525; --upcoming-bg: #F4F4F4; --upcoming-fg: #888;
  --close-bg: #FFF2CC; --close-fg: #8E6A00; }}
* {{ box-sizing: border-box; }}
body {{ font-family: 'Open Sans', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', sans-serif;
  background: var(--offwhite); color: var(--black); margin: 0; padding: 0; line-height: 1.55; }}
.container {{ max-width: 1320px; margin: 0 auto; padding: 48px 56px 96px; }}
.eyebrow {{ font-size: 12px; font-weight: 700; letter-spacing: 0.16em; text-transform: uppercase; color: var(--crimson); margin: 0 0 8px; }}
.crimson-rule {{ width: 64px; height: 3px; background: var(--crimson); margin: 0 0 24px; }}
h1 {{ font-family: 'Inter', sans-serif; font-size: 44px; font-weight: 800; color: var(--navy); margin: 0 0 8px; letter-spacing: -0.02em; }}
h2 {{ font-family: 'Inter', sans-serif; font-size: 24px; font-weight: 700; color: var(--navy); margin: 48px 0 12px; letter-spacing: -0.01em; }}
h3 {{ font-family: 'Inter', sans-serif; font-size: 16px; color: var(--navy); margin: 24px 0 12px; }}
.subtitle {{ color: #555; font-size: 14px; margin: 0 0 8px; }}
.dateline {{ font-size: 12px; letter-spacing: 0.16em; text-transform: uppercase; color: #888; margin: 0 0 32px; }}
.cards {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; margin: 24px 0 8px; }}
.card {{ background: white; border: 1px solid #E5E5E5; border-left: 3px solid var(--crimson); padding: 18px 20px; border-radius: 4px; }}
.card .label {{ font-size: 11px; font-weight: 700; letter-spacing: 0.16em; text-transform: uppercase; color: #888; margin-bottom: 8px; }}
.card .value {{ font-family: 'Inter', sans-serif; font-size: 26px; font-weight: 800; color: var(--navy); }}
.card .meta {{ font-size: 12.5px; color: #666; margin-top: 4px; }}
.tabs {{ display: flex; gap: 0; border-bottom: 2px solid #E5E5E5; margin: 40px 0 0; flex-wrap: wrap; }}
.tab {{ padding: 14px 24px; cursor: pointer; font-family: 'Inter', sans-serif; font-weight: 700; font-size: 14px; color: #888; letter-spacing: 0.04em; text-transform: uppercase; border-bottom: 3px solid transparent; margin-bottom: -2px; transition: all 0.2s; }}
.tab:hover {{ color: var(--navy); }}
.tab.active {{ color: var(--crimson); border-bottom-color: var(--crimson); }}
.tab-pane {{ display: none; padding-top: 12px; }}
.tab-pane.active {{ display: block; }}
.tab .count {{ background: #E5E5E5; color: #555; padding: 2px 8px; border-radius: 12px; font-size: 11px; margin-left: 8px; }}
.tab.active .count {{ background: var(--crimson); color: white; }}
table {{ width: 100%; border-collapse: collapse; font-size: 14px; background: white; margin: 16px 0 8px; }}
th {{ background: var(--crimson); color: white; padding: 12px 10px; text-align: left; font-size: 11px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; }}
td {{ padding: 11px 10px; border-bottom: 1px solid #EEE; vertical-align: middle; }}
tr.bh-row td {{ background: #FFF5F7; color: var(--crimson); font-weight: 700; }}
tr.tier-champ td:first-child {{ color: var(--crimson); font-weight: 700; }}
.tier {{ display: inline-block; padding: 3px 10px; border-radius: 3px; font-size: 11px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; }}
.tier-Championship {{ background: var(--crimson); color: white; }}
.tier-Contender {{ background: var(--navy); color: white; }}
.tier-Competitive {{ background: #E5E5E5; color: var(--black); }}
.tier-Developing {{ background: #F4F4F4; color: #888; }}
.badge {{ display: inline-block; padding: 2px 7px; border-radius: 3px; font-size: 10px; font-weight: 700; letter-spacing: 0.05em; }}
.badge.isl-badge {{ background: var(--navy); color: white; margin-left: 6px; }}
.badge.close-badge {{ background: var(--close-bg); color: var(--close-fg); margin-left: 6px; }}
.matrix-wrap {{ overflow-x: auto; }}
table.matrix {{ font-size: 11px; table-layout: fixed; min-width: 900px; }}
table.matrix th {{ font-size: 10px; padding: 4px 4px; vertical-align: bottom; height: 110px; white-space: nowrap; text-align: center; background: var(--crimson); }}
table.matrix th.row-head {{ vertical-align: middle; height: auto; padding: 8px 10px; text-align: left; }}
.col-label {{ writing-mode: vertical-rl; transform: rotate(180deg); display: inline-block; padding: 6px 0; }}
table.matrix td {{ text-align: center; padding: 6px 3px; border: 1px solid #EEE; font-weight: 600; }}
table.matrix td.diag {{ background: #F0F0F0; color: #BBB; }}
table.matrix td.empty {{ background: white; color: #DDD; }}
table.matrix td.win {{ background: var(--win-bg); color: var(--win-fg); }}
table.matrix td.loss {{ background: var(--loss-bg); color: var(--loss-fg); }}
table.matrix td.upcoming {{ background: var(--upcoming-bg); color: var(--upcoming-fg); font-weight: 500; font-size: 10.5px; }}
table.matrix td.upcoming.low-conf {{ font-style: italic; opacity: 0.85; }}
table.matrix td:first-child {{ text-align: left; font-weight: 700; color: var(--navy); background: var(--offwhite); }}
table.matrix tr.bh-row td:first-child {{ color: var(--crimson); }}
table.matrix tr.bh-row td {{ background: #FFF8FA; }}
.legend {{ font-size: 12px; color: #666; margin: 8px 0 24px; }}
.dot {{ display: inline-block; width: 12px; height: 12px; border-radius: 2px; margin-right: 4px; vertical-align: middle; }}
.note {{ font-size: 12px; color: #888; font-style: italic; }}
.match-list li {{ margin: 6px 0; }}
.footer {{ margin-top: 64px; padding-top: 24px; border-top: 1px solid #E5E5E5; font-size: 12px; color: #888; }}
.footer a {{ color: var(--navy); text-decoration: underline; }}
ul.match-list {{ list-style: none; padding-left: 0; }}
.split {{ display: grid; grid-template-columns: 1fr 1fr; gap: 32px; }}
.predictions table {{ font-size: 13px; }}
@media (max-width: 800px) {{ .cards {{ grid-template-columns: 1fr; }} .split {{ grid-template-columns: 1fr; }} }}
</style>
</head>
<body>
<div class="container">

<div class="eyebrow">Belmont Hill Tennis · Scouting Report</div>
<h1>2026 ISL & NEPSAC Class A Tennis</h1>
<div class="crimson-rule"></div>
<p class="dateline">As of {today} · {total_completed} matches played · {total_scheduled} remaining</p>

<div class="cards">
  <div class="card">
    <div class="label">ISL Co-Leaders</div>
    <div class="value" style="font-size:22px;">{co_leader_names}</div>
    <div class="meta">Both undefeated; meet in regular-season finale</div>
  </div>
  <div class="card">
    <div class="label">Top Elo Ratings</div>
    <div class="value" style="font-size:14px;line-height:1.4;">{top_elo_names}</div>
    <div class="meta">Margin-weighted Elo from completed matches</div>
  </div>
</div>

<div class="tabs" role="tablist">
  <div class="tab active" data-tab="isl" role="tab">ISL Only <span class="count">16</span></div>
  <div class="tab" data-tab="classa" role="tab">NEPSAC Class A <span class="count">18</span></div>
  <div class="tab" data-tab="total" role="tab">Total Record <span class="count">16</span></div>
  <div class="tab" data-tab="predictions" role="tab">Predictions</div>
</div>

<div class="tab-pane active" id="pane-isl">
  <h2>ISL Conference Standings</h2>
  <p class="subtitle">Ranked by ISL conference winning percentage. Only ISL-vs-ISL matches count toward this record. Elo is margin-weighted across all completed matches (any opponent). <code>*</code> = limited match data, low confidence.</p>
  <table>
    <thead><tr><th style="width:50px;">#</th><th>School</th><th style="width:90px;">ISL Record</th><th style="width:90px;">Win %</th><th style="width:80px;">Elo</th><th style="width:130px;">Tier</th></tr></thead>
    <tbody>{standings_table(isl_standings)}</tbody>
  </table>

  <h2>ISL Head-to-Head Matrix</h2>
  <p class="subtitle">Read across: row team's result vs column team. Empty cells with a date show when that match is scheduled, plus the row team's predicted win probability.</p>
  <div class="legend">
    <span class="dot" style="background:var(--win-bg);"></span> Win &nbsp;
    <span class="dot" style="background:var(--loss-bg);"></span> Loss &nbsp;
    <span class="dot" style="background:var(--upcoming-bg);"></span> Scheduled (date · win prob) &nbsp;
    <span class="dot" style="background:white; border:1px solid #DDD;"></span> No match this season
  </div>
  <div class="matrix-wrap">{h2h_matrix(isl_standings, isl_h2h, isl_scheduled, label_col_name="ISL")}</div>

  <h2>Belmont Hill Match Schedule</h2>
  <table>
    <thead><tr><th style="width:120px;">Date</th><th style="width:90px;">Home/Away</th><th>Opponent</th><th style="width:120px;">Score</th><th style="width:80px;">Result</th><th style="width:110px;">BH Win Prob</th></tr></thead>
    <tbody>{bh_match_rows}</tbody>
  </table>
</div>

<div class="tab-pane" id="pane-classa">
  <h2>NEPSAC Class A Standings (2025-26)</h2>
  <p class="subtitle">Official Class A roster (18 schools) per <a href="https://nepsac.org/coaches-associations/boys-sports/boys-tennis-nepsbta/">NEPSBTA</a>. "Class A Record" counts only matches against other Class A teams. Elo is computed across all matches.</p>
  <table>
    <thead><tr><th style="width:50px;">#</th><th>School</th><th style="width:130px;">Class A Record</th><th style="width:90px;">A Win %</th><th style="width:130px;">Overall Record</th><th style="width:80px;">Elo</th></tr></thead>
    <tbody>{ca_table_rows}</tbody>
  </table>

  <h2>Class A vs Class A Head-to-Head Matrix</h2>
  <p class="subtitle">Played matches are colored; empty cells with a date show when those teams are scheduled to meet (often at the May 16 NEPSAC tournament).</p>
  <div class="legend">
    <span class="dot" style="background:var(--win-bg);"></span> Win &nbsp;
    <span class="dot" style="background:var(--loss-bg);"></span> Loss &nbsp;
    <span class="dot" style="background:var(--upcoming-bg);"></span> Scheduled (date · win prob)
  </div>
  <div class="matrix-wrap">{h2h_matrix(ca_matrix_standings, ca_h2h, ca_scheduled, label_col_name="A Record")}</div>

  <div class="split">
    <div>
      <h2>Class A — Played</h2>
      <ul class="match-list">{ca_match_li}</ul>
    </div>
    <div>
      <h2>Class A — Upcoming</h2>
      <ul class="match-list">{ca_upcoming_li}</ul>
    </div>
  </div>
</div>

<div class="tab-pane" id="pane-total">
  <h2>Total / Overall Records</h2>
  <p class="subtitle">Every ISL school's full record vs ANY opponent (includes ISL matches plus non-ISL games).</p>
  <table>
    <thead><tr><th style="width:50px;">#</th><th>School</th><th style="width:130px;">Overall Record</th><th style="width:90px;">Win %</th><th style="width:80px;">Elo</th><th style="width:140px;">Tier</th></tr></thead>
    <tbody>{standings_table(total_standings)}</tbody>
  </table>

  <h2>Recent Results Across the League</h2>
  <table>
    <thead><tr><th style="width:120px;">Date</th><th>Winner</th><th></th><th>Loser</th><th style="width:90px;">Score</th></tr></thead>
    <tbody>{recent_rows}</tbody>
  </table>
</div>

<div class="tab-pane predictions" id="pane-predictions">
  <h2>How predictions work</h2>
  <p class="subtitle">Each completed match updates a margin-weighted <strong>Elo rating</strong> for both teams. A 7-0 sweep moves ratings ~1.6× as much as a 4-3 squeaker. The predicted win probability for any future match is computed from the rating gap: a 100-point gap implies ~64%, 200 points ~76%, 400 points ~91%. Teams with fewer than {LOW_CONFIDENCE_GAMES} completed games are flagged with <code>*</code> — predictions involving them carry low confidence.</p>

  <h2>Belmont Hill — Upcoming Matches</h2>
  <table>
    <thead><tr><th style="width:120px;">Date</th><th>Matchup</th><th>BH Win Probability</th></tr></thead>
    <tbody>{render_predictions_list(bh_preds, show_bh_perspective=True)}</tbody>
  </table>

  <h2>Closest Upcoming Matches Across the League</h2>
  <p class="subtitle">Sorted by closeness — these are the most uncertain (and most interesting) games on the schedule.</p>
  <table>
    <thead><tr><th style="width:120px;">Date</th><th>Matchup</th><th style="width:240px;">Predicted Outcome</th></tr></thead>
    <tbody>{render_predictions_list(closest_preds)}</tbody>
  </table>

  <p class="note">Caveat: Elo doesn't know about graduating seniors, injuries, or specific lineup matchups. It only sees results. Class A schools that play primarily in the Founders League / Eight Schools have less ISL data — so cross-conference matchups (e.g., Brunswick vs Nobles in the NEPSAC final) are noisier than intra-ISL predictions.</p>
</div>

<div class="footer">
  <p><strong>Data sources:</strong> <a href="https://www.islsports.org/boys-tennis/">islsports.org</a> ISL feed; <a href="https://www.belmonthill.org/athletics/our-teams/athletic-teams-page/~athletics-team-id/181">BH Athletics</a>; <a href="https://nobilis.nobles.edu/Athletics/team_detail.php?team_id=51441">Nobles Athletics</a>; <a href="https://athletics.mxschool.edu/sports/mens-tennis/schedule">MX Athletics</a>; <a href="https://athletics.andover.edu/teams/btev">Phillips Andover Athletics</a>; <a href="https://my.brunswickschool.org/athletics/team/~athletics-team-id/231">Brunswick Athletics</a>; <a href="https://www.loomischaffee.org/athletics/teams/spring/tennis/boys">Loomis Athletics</a>; <a href="https://nepsac.org/coaches-associations/boys-sports/boys-tennis-nepsbta/">NEPSBTA Class A roster</a>; <a href="https://phillipian.net/">The Phillipian</a>.</p>
  <p>Belmont Hill School · Computer Science Dept. · Generated {today} · Edit <code>data/matches.json</code> and rerun <code>python3 scripts/render_dashboard.py</code> to update.</p>
</div>
</div>

<script>
document.querySelectorAll('.tab').forEach(t => {{
  t.addEventListener('click', () => {{
    const target = t.dataset.tab;
    document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
    document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
    t.classList.add('active');
    document.getElementById('pane-' + target).classList.add('active');
  }});
}});
</script>
</body>
</html>"""

# Write index.html (primary)
with open(OUTPUT, "w") as f:
    f.write(html)

# Write legacy ISL_Tennis_Report_2026.html as a redirect to index.html
legacy_redirect = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="0; url=index.html">
<link rel="canonical" href="index.html">
<title>Redirecting…</title>
</head>
<body>
<p>This report has moved to <a href="index.html">index.html</a>. Redirecting…</p>
</body>
</html>
"""
with open(LEGACY_OUTPUT, "w") as f:
    f.write(legacy_redirect)

print(f"Wrote {OUTPUT} ({len(html):,} chars)")
print(f"Wrote {LEGACY_OUTPUT} (redirect to index.html)")
print(f"  Matches: {total_completed} completed, {total_scheduled} scheduled")
print(f"  ISL leader(s): {co_leader_names}")
print(f"  Top Elo (3+ games): {top_elo_names}")
if bh_preds:
    print(f"  BH next match: {bh_preds[0]['date']} vs {bh_preds[0]['away'] if bh_preds[0]['home']=='Belmont Hill' else bh_preds[0]['home']}")
