# Belmont Hill Boys Tennis — 2026 Scouting Report

A live-updated scouting dashboard for the **Independent School League** (ISL) and **NEPSAC Class A** boys' tennis seasons.

## The dashboard

[`ISL_Tennis_Report_2026.html`](./ISL_Tennis_Report_2026.html) — single-page report with three tabs:

1. **ISL Only** — conference standings (only ISL-vs-ISL matches count) plus a 16×16 head-to-head matrix and Belmont Hill's match schedule.
2. **NEPSAC Class A** — all 18 official Class A schools with both their Class-A-vs-Class-A record and overall record, plus a Class A H2H matrix.
3. **Total Record** — every ISL school's overall record vs anyone (including non-ISL games), with a "Why ISL & Total Differ" explainer.

Empty cells in the matrices show the date when those teams are scheduled to play (e.g., `5/13`).

## Project structure

```
data/
  schools.json     — ISL & Class A school metadata, name aliases
  matches.json     — every match this season (the source of truth)
scripts/
  render_dashboard.py  — rebuilds the HTML from data/
ISL_Tennis_Report_2026.html  — generated dashboard
README.md
```

## How to update (every couple of days)

1. **Edit `data/matches.json`** to add or fill in scores. Each match looks like:

   ```json
   {
     "date": "05/02/2026",
     "home": "Belmont Hill",
     "away": "St. George's",
     "home_score": 6,
     "away_score": 1,
     "status": "completed",
     "source": "bh_site"
   }
   ```

   - For a completed match, set `status: "completed"` and fill in `home_score` / `away_score`.
   - For a not-yet-played match, leave it as `status: "scheduled"` (no scores).
   - Cancelled? Set `status: "cancelled"` — it'll be excluded from records.

2. **Run the renderer:**

   ```bash
   cd "~/Desktop/Belmont Hill Mac Mini/Sports/Tennis/League"
   python3 scripts/render_dashboard.py
   ```

3. **Done.** The HTML is regenerated. Open it in any browser.

You don't need to re-scrape anything — the data file is the source of truth.

## How records are computed

- **ISL Record** — only matches between two ISL schools count.
- **Class A Record** — only matches between two of the 18 NEPSAC Class A schools count.
- **Overall Record** — every completed match counts.

Scrimmages and cancelled matches are excluded automatically.

## Data sources (used to populate the initial dataset)

| Source | Use |
|---|---|
| [islsports.org boys tennis](https://www.islsports.org/boys-tennis/) | League-wide schedule + scores (live RSchoolToday widget) |
| [BH Athletics](https://www.belmonthill.org/athletics/our-teams/athletic-teams-page/~athletics-team-id/181) | Authoritative for BH match results |
| [Nobles Athletics](https://nobilis.nobles.edu/Athletics/team_detail.php?team_id=51441) | Nobles match log with scores |
| [Middlesex Athletics](https://athletics.mxschool.edu/sports/mens-tennis/schedule) | MX overall record |
| [Phillips Andover Athletics](https://athletics.andover.edu/teams/btev) | Andover schedule (Class A non-ISL matches) |
| [Roxbury Latin Tennis](https://www.roxburylatin.org/team/tennis-varsity/) | RL schedule |
| [NEPSBTA Class A roster (PDF)](https://assets-rst7.rschooltoday.com/rst7files/uploads/sites/328/2025/03/31092859/B-tennis-classifications-2025-2.pdf) | Official 18-school Class A list |
| [The Phillipian](https://phillipian.net/) | Andover game recaps + scores |

## 2026 season snapshot (April 27)

- **Belmont Hill 6-1 ISL / 8-1 overall** — #3 in ISL. Signature 4-3 win at Roxbury Latin (4/8); only loss is at home to Milton 2-5 (4/18).
- **ISL co-leaders:** Milton (7-0) and Nobles (7-0); they meet 5/22.
- **NEPSAC Class A Tournament:** May 16, 2026 (location TBD).

## Brand styling

The HTML uses Belmont Hill's design system — crimson `#8E1838` for accents/leaders, navy `#222D65` for headings, eyebrow labels at 16% letter-spacing, Open Sans body / Inter Bold display. Match cells: green for wins, pink for losses, gray for scheduled.

---

*Maintained by Petros Palandjian · Computer Science Dept., Belmont Hill School*
