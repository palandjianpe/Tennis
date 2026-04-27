# Belmont Hill Boys Tennis — 2026 Scouting Report

A live-updated scouting dashboard for the **Independent School League** (ISL) and **NEPSAC Class A** boys' tennis seasons, built for Belmont Hill School.

## What's in the dashboard

[`ISL_Tennis_Report_2026.html`](./ISL_Tennis_Report_2026.html) is a single-page report with three tabs:

1. **ISL Only** — conference standings (only ISL-vs-ISL matches count) plus a 16×16 head-to-head matrix and Belmont Hill's match schedule.
2. **NEPSAC Class A** — all 18 official Class A schools with both their Class-A-vs-Class-A record and overall record, plus a Class A H2H matrix.
3. **Total Record** — every ISL school's overall record vs anyone (including non-ISL games like BH vs Deerfield), with a "Why ISL & Total Differ" explainer.

## Open it

Open `ISL_Tennis_Report_2026.html` in any browser — it's a self-contained file with no dependencies.

Or view it via GitHub Pages: enable Pages in repo Settings → Pages → "Deploy from a branch" → main / root, then visit `https://palandjianpe.github.io/Tennis/ISL_Tennis_Report_2026.html`.

## Data sources

| Source | Use |
|---|---|
| [islsports.org](https://www.islsports.org/boys-tennis/) | League-wide schedule + scores (live RSchoolToday widget) |
| [BH Athletics](https://www.belmonthill.org/athletics/our-teams/athletic-teams-page/~athletics-team-id/181) | BH match-by-match record (authoritative for BH) |
| [Nobles Athletics](https://nobilis.nobles.edu/Athletics/team_detail.php?team_id=51441) | Nobles match log |
| [Middlesex Athletics](https://athletics.mxschool.edu/sports/mens-tennis/schedule) | MX overall record + scores |
| [NEPSBTA Class A PDF](https://assets-rst7.rschooltoday.com/rst7files/uploads/sites/328/2025/03/31092859/B-tennis-classifications-2025-2.pdf) | Official 18-school Class A roster |
| [The Phillipian](https://phillipian.net/) | Phillips Andover and cross-conference results |

## 2026 season snapshot (as of April 27)

- **Belmont Hill 6-1 ISL / 8-1 overall** — #3 in the ISL, signature 4-3 win at Roxbury Latin (4/8) ended RL's three-peat run; only loss is at home to Milton 2-5 (4/18).
- **Co-leaders:** Milton (7-0) and Nobles (7-0); they don't meet until 5/22.
- **NEPSAC Class A Tournament:** May 16 (location TBD).

## Brand styling

The HTML uses Belmont Hill's design system — crimson `#8E1838` for accents/leaders, navy `#222D65` for headings, eyebrow labels at 16% letter-spacing. Match cells use win-green and loss-pink so the H2H matrix reads at a glance.

---

*Maintained by Petros Palandjian · Computer Science Dept., Belmont Hill School*
