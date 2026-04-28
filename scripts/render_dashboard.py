#!/usr/bin/env python3
"""
Renders ISL_Tennis_Report_2026.html from data/matches.json + data/schools.json.

Usage: python3 scripts/render_dashboard.py

Edit data/matches.json by hand to add new scores. Each match looks like:
  {"date": "MM/DD/YYYY", "home": "...", "away": "...",
   "home_score": 4, "away_score": 3,
   "status": "completed" | "scheduled" | "cancelled" | "scrimmage",
   "source": "..."}

Then re-run this script and the dashboard updates.
"""
import json, os, sys
from datetime import datetime
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUTPUT = ROOT / "ISL_Tennis_Report_2026.html"

# Brand
CRIMSON = "#8E1838"
NAVY = "#222D65"

with open(DATA / "schools.json") as f:
    schools = json.load(f)
with open(DATA / "matches.json") as f:
    db = json.load(f)

ALIASES = schools["name_aliases"]
ISL_SCHOOLS = schools["isl"]
CLASS_A_ONLY = schools["class_a_only"]
ALL_CLASS_A = {**{k: v for k, v in ISL_SCHOOLS.items() if v.get("class_a")}, **CLASS_A_ONLY}
ALL_SCHOOLS = {**ISL_SCHOOLS, **CLASS_A_ONLY}
SCHOOL_URLS = {full: meta.get("url") for full, meta in ALL_SCHOOLS.items() if meta.get("url")}

def canonicalize(name: str) -> str:
    return ALIASES.get(name.strip(), name.strip())

def school_link(full_name: str, label: str = None):
    """Wrap a school's display label in an <a> if we have a URL for it."""
    label = label if label is not None else full_name
    url = SCHOOL_URLS.get(full_name)
    if url:
        return f'<a class="school-link" href="{url}" target="_blank" rel="noopener">{label}</a>'
    return label

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
# Compute records
# ============================
def is_completed(m):
    return m.get("status") == "completed" and m.get("home_score") is not None and m.get("away_score") is not None

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
                # Track scheduled — don't overwrite existing completed
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

# Apply known external Class A records (where we don't have full match data)
ca_known_overall = {
    "Phillips Academy Andover": (2, 6),  # 2-6 per Phillipian 4/24
    "Brunswick School": (1, 0),  # only known: 7-0 vs Andover
    "Deerfield Academy": (1, 1),  # 4-3 vs Andover, 3-4 vs BH
    "Loomis Chaffee": (4, 2),  # 4-2 per loomischaffee.org team page snippet (4/22)
    "St. Paul's School": (1, 1),  # W vs New Hampton 4/13 + L vs Exeter 4/8
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
            "w": r["w"], "l": r["l"], "t": r["t"], "pct": pct, "total": total
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
    })
ca_combined.sort(key=lambda x: (-x["a_pct"], -x["a_w"], x["a_l"], -x["ovr_w"], x["ovr_l"], x["short"]))

# ============================
# Helpers
# ============================
def short_date(date_str):
    """Convert MM/DD/YYYY to M/D"""
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

def h2h_cell(team_full, opp_full, h2h, scheduled):
    if team_full == opp_full:
        return '<td class="diag">—</td>'
    if team_full in h2h and opp_full in h2h[team_full]:
        res, score, date = h2h[team_full][opp_full]
        cls = "win" if res == "W" else ("loss" if res == "L" else "tie")
        return f'<td class="{cls}" title="{date}: {res} {score}"><strong>{res}</strong> {score}</td>'
    if team_full in scheduled and opp_full in scheduled[team_full]:
        date = scheduled[team_full][opp_full]
        return f'<td class="upcoming" title="Scheduled: {date}">{short_date(date)}</td>'
    return '<td class="empty"></td>'

def standings_table(standings):
    rows = ""
    total = len(standings)
    for i, s in enumerate(standings, 1):
        is_bh = s["short"] == "Belmont Hill"
        cls = "bh-row" if is_bh else ("tier-champ" if i <= 2 else "")
        pct = f"{s['pct']*100:.0f}%" if (s["w"] + s["l"]) else "—"
        rec = f"{s['w']}-{s['l']}" if (s["w"] + s["l"]) else "—"
        tier = tier_for(i, total)
        name_html = school_link(s["full"], s["short"])
        rows += f'<tr class="{cls}"><td>{i}</td><td>{name_html}</td><td>{rec}</td><td>{pct}</td><td><span class="tier tier-{tier}">{tier}</span></td></tr>\n'
    return rows

def h2h_matrix(standings, h2h, scheduled, label_col_name="Record"):
    full_to_short = {s["full"]: s.get("abbr", s["short"]) for s in standings}
    ordered = [s["full"] for s in standings]
    head = '<tr><th class="row-head">Team</th>'
    for f in ordered:
        head += f'<th><div class="col-label">{school_link(f, full_to_short[f])}</div></th>'
    head += f'<th>{label_col_name}</th></tr>'
    body = ""
    for i, full in enumerate(ordered):
        s = standings[i]
        cls = "bh-row" if s["short"] == "Belmont Hill" else ""
        body += f'<tr class="{cls}"><td>{school_link(full, s["short"])}</td>'
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
    a_pct = f"{s['a_pct']*100:.0f}%" if (s["a_w"] + s["a_l"]) else "—"
    ovr = f"{s['ovr_w']}-{s['ovr_l']}" if (s["ovr_w"] + s["ovr_l"]) else "TBD"
    isl_badge = ' <span class="badge isl-badge">ISL</span>' if s["in_isl"] else ''
    name_html = school_link(s["full"], s["short"])
    ca_table_rows += f'<tr class="{cls}"><td>{i}</td><td>{name_html}{isl_badge}</td><td>{a_rec}</td><td>{a_pct}</td><td>{ovr}</td></tr>\n'

# Class A matrix needs short names that include all 18 schools
ca_matrix_standings = []
for s in ca_combined:
    ca_matrix_standings.append({
        "full": s["full"], "short": s["short"], "abbr": s["abbr"],
        "w": s["a_w"], "l": s["a_l"], "t": 0, "pct": s["a_pct"],
    })

# BH match list
bh_matches = []
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
        else:
            result = ""; score = "—"
        bh_matches.append({
            "date": m["date"], "home_away": "Home" if is_home else "Away",
            "opp": opp, "score": score, "result": result, "status": m.get("status", "scheduled")
        })
bh_matches.sort(key=lambda x: datetime.strptime(x["date"], "%m/%d/%Y"))

# Dedupe by (date, opp) — prefer completed
seen = {}
for m in bh_matches:
    key = (m["date"], m["opp"])
    if key not in seen or m["result"]:
        seen[key] = m
bh_matches = sorted(seen.values(), key=lambda x: datetime.strptime(x["date"], "%m/%d/%Y"))

bh_match_rows = ""
for m in bh_matches:
    if m["result"] == "W": rstyle = ' style="color:var(--win-fg);font-weight:700;"'
    elif m["result"] == "L": rstyle = ' style="color:var(--loss-fg);font-weight:700;"'
    else: rstyle = ''
    opp_short = ALL_SCHOOLS.get(m["opp"], {}).get("short", m["opp"])
    opp_html = school_link(m["opp"], opp_short)
    bh_match_rows += f'<tr><td>{m["date"]}</td><td>{m["home_away"]}</td><td>{opp_html}</td><td>{m["score"]}</td><td{rstyle}>{m["result"]}</td></tr>\n'

# Recent results
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
    winner_short = ALL_SCHOOLS.get(winner, {}).get("short", winner)
    loser_short = ALL_SCHOOLS.get(loser, {}).get("short", loser)
    winner_html = school_link(winner, winner_short)
    loser_html = school_link(loser, loser_short)
    recent_rows += f'<tr><td>{m["date"]}</td><td{bh_class}><strong>{winner_html}</strong></td><td>def.</td><td{bh_class}>{loser_html}</td><td><strong>{hi}-{lo}</strong></td></tr>\n'

# Class A vs Class A matches
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
    winner_html = school_link(winner)
    loser_html = school_link(loser)
    ca_match_li += f'<li><strong>{m["date"]}</strong> &nbsp; <strong>{winner_html}</strong> def. {loser_html} &nbsp; {hi}-{lo}{src_str}</li>\n'

# Upcoming Class A vs Class A
ca_upcoming = sorted([m for m in matches if m.get("status") == "scheduled"
                      and m["home"] in CLASS_A_FULL and m["away"] in CLASS_A_FULL],
                     key=lambda x: datetime.strptime(x["date"], "%m/%d/%Y"))
ca_upcoming_li = ""
for m in ca_upcoming:
    home_html = school_link(m["home"])
    away_html = school_link(m["away"])
    ca_upcoming_li += f'<li><strong>{m["date"]}</strong> &nbsp; {home_html} <em>vs</em> {away_html}</li>\n'

# Compute season snapshot for top stat cards (no BH-specific cards now)
co_leaders = [s for s in isl_standings if s["w"] > 0 and s["l"] == 0]
co_leader_names = ", ".join([s["short"] for s in co_leaders[:2]]) or "TBD"
total_completed = len(completed_matches)
total_scheduled = sum(1 for m in matches if m.get("status") == "scheduled")

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>2026 ISL & NEPSAC Class A Tennis — Belmont Hill</title>
<style>
:root {{ --crimson: {CRIMSON}; --navy: {NAVY}; --black: #201E1E; --offwhite: #FAFAFA;
  --parchment: #EEECE1; --win-bg: #DCEFD8; --win-fg: #2D6B2A;
  --loss-bg: #FCE0E0; --loss-fg: #A02525; --upcoming-bg: #F4F4F4; --upcoming-fg: #888; }}
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
.tabs {{ display: flex; gap: 0; border-bottom: 2px solid #E5E5E5; margin: 40px 0 0; }}
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
.badge.isl-badge {{ background: var(--navy); color: white; padding: 2px 7px; border-radius: 3px; font-size: 10px; font-weight: 700; letter-spacing: 0.05em; margin-left: 6px; }}
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
table.matrix td.upcoming {{ background: var(--upcoming-bg); color: var(--upcoming-fg); font-weight: 500; font-size: 10.5px; font-style: italic; }}
table.matrix td:first-child {{ text-align: left; font-weight: 700; color: var(--navy); background: var(--offwhite); }}
table.matrix tr.bh-row td:first-child {{ color: var(--crimson); }}
table.matrix tr.bh-row td {{ background: #FFF8FA; }}
.legend {{ font-size: 12px; color: #666; margin: 8px 0 24px; }}
.dot {{ display: inline-block; width: 12px; height: 12px; border-radius: 2px; margin-right: 4px; vertical-align: middle; }}
.note {{ font-size: 12px; color: #888; font-style: italic; margin-top: 8px; }}
.match-list li {{ margin: 6px 0; }}
.footer {{ margin-top: 64px; padding-top: 24px; border-top: 1px solid #E5E5E5; font-size: 12px; color: #888; }}
.footer a {{ color: var(--navy); text-decoration: underline; }}
.school-link {{ color: inherit; text-decoration: none; border-bottom: 1px dotted rgba(34, 45, 101, 0.35); }}
.school-link:hover {{ color: var(--crimson); border-bottom-color: var(--crimson); }}
table.matrix .school-link {{ border-bottom: none; }}
table.matrix .school-link:hover {{ text-decoration: underline; }}
ul.match-list {{ list-style: none; padding-left: 0; }}
.split {{ display: grid; grid-template-columns: 1fr 1fr; gap: 32px; }}
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
    <div class="label">NEPSAC Class A Tournament</div>
    <div class="value" style="font-size:22px;">May 16, 2026</div>
    <div class="meta">Bracket TBD · 18 Class A schools eligible</div>
  </div>
</div>

<div class="tabs" role="tablist">
  <div class="tab active" data-tab="isl" role="tab">ISL Only <span class="count">16</span></div>
  <div class="tab" data-tab="classa" role="tab">NEPSAC Class A <span class="count">18</span></div>
  <div class="tab" data-tab="total" role="tab">Total Record <span class="count">16</span></div>
</div>

<div class="tab-pane active" id="pane-isl">
  <h2>ISL Conference Standings</h2>
  <p class="subtitle">Ranked by ISL conference winning percentage. Only ISL-vs-ISL matches count toward this record.</p>
  <table>
    <thead><tr><th style="width:50px;">#</th><th>School</th><th style="width:90px;">ISL Record</th><th style="width:90px;">Win %</th><th style="width:140px;">Tier</th></tr></thead>
    <tbody>{standings_table(isl_standings)}</tbody>
  </table>

  <h2>ISL Head-to-Head Matrix</h2>
  <p class="subtitle">Read across: row team's result vs column team. Empty cells with a date show when that match is scheduled.</p>
  <div class="legend">
    <span class="dot" style="background:var(--win-bg);"></span> Win &nbsp;
    <span class="dot" style="background:var(--loss-bg);"></span> Loss &nbsp;
    <span class="dot" style="background:var(--upcoming-bg);"></span> Scheduled (date shown) &nbsp;
    <span class="dot" style="background:white; border:1px solid #DDD;"></span> No match this season
  </div>
  <div class="matrix-wrap">{h2h_matrix(isl_standings, isl_h2h, isl_scheduled, label_col_name="ISL")}</div>

  <h2>Belmont Hill Match Schedule</h2>
  <table>
    <thead><tr><th style="width:120px;">Date</th><th style="width:90px;">Home/Away</th><th>Opponent</th><th style="width:120px;">Score</th><th style="width:80px;">Result</th></tr></thead>
    <tbody>{bh_match_rows}</tbody>
  </table>
</div>

<div class="tab-pane" id="pane-classa">
  <h2>NEPSAC Class A Standings (2025-26)</h2>
  <p class="subtitle">Official Class A roster (18 schools) per <a href="https://nepsac.org/coaches-associations/boys-sports/boys-tennis-nepsbta/">NEPSBTA</a>. "Class A Record" counts only matches against other Class A teams.</p>
  <table>
    <thead><tr><th style="width:50px;">#</th><th>School</th><th style="width:130px;">Class A Record</th><th style="width:90px;">A Win %</th><th style="width:130px;">Overall Record</th></tr></thead>
    <tbody>{ca_table_rows}</tbody>
  </table>

  <h2>Class A vs Class A Head-to-Head Matrix</h2>
  <p class="subtitle">Direct matchups between Class A schools this season. Played matches are colored; empty cells with a date show when those teams are scheduled to meet (often at the May 16 NEPSAC tournament).</p>
  <div class="legend">
    <span class="dot" style="background:var(--win-bg);"></span> Win &nbsp;
    <span class="dot" style="background:var(--loss-bg);"></span> Loss &nbsp;
    <span class="dot" style="background:var(--upcoming-bg);"></span> Scheduled
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
    <thead><tr><th style="width:50px;">#</th><th>School</th><th style="width:130px;">Overall Record</th><th style="width:90px;">Win %</th><th style="width:140px;">Tier</th></tr></thead>
    <tbody>{standings_table(total_standings)}</tbody>
  </table>

  <h2>Recent Results Across the League</h2>
  <table>
    <thead><tr><th style="width:120px;">Date</th><th>Winner</th><th></th><th>Loser</th><th style="width:90px;">Score</th></tr></thead>
    <tbody>{recent_rows}</tbody>
  </table>
</div>

<div class="footer">
  <p><strong>Data sources:</strong> <a href="https://www.islsports.org/boys-tennis/">islsports.org</a> ISL feed; <a href="https://www.belmonthill.org/athletics/our-teams/athletic-teams-page/~athletics-team-id/181">BH Athletics</a>; <a href="https://nobilis.nobles.edu/Athletics/team_detail.php?team_id=51441">Nobles Athletics</a>; <a href="https://athletics.mxschool.edu/sports/mens-tennis/schedule">MX Athletics</a>; <a href="https://athletics.andover.edu/teams/btev">Phillips Andover Athletics</a>; <a href="https://www.roxburylatin.org/team/tennis-varsity/">Roxbury Latin Athletics</a>; <a href="https://nepsac.org/coaches-associations/boys-sports/boys-tennis-nepsbta/">NEPSBTA Class A roster</a>; <a href="https://phillipian.net/">The Phillipian</a>.</p>
  <p>Belmont Hill School · Computer Science Dept. · Generated {today} · To update: edit <code>data/matches.json</code> and rerun <code>python3 scripts/render_dashboard.py</code></p>
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

with open(OUTPUT, "w") as f:
    f.write(html)

print(f"Wrote {OUTPUT} ({len(html):,} chars)")
print(f"  Matches: {total_completed} completed, {total_scheduled} scheduled")
print(f"  ISL leader(s): {co_leader_names}")
