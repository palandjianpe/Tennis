# Tennis Score Sources

How every NEPSAC Class A and ISL school's match data flows into `data/matches.json`. Update this file whenever you add, remove, or fix a source.

## Quick reference

| School | Conference | Source | Tier | Notes |
|---|---|---|---|---|
| All 17 ISL schools | ISL | `isl_feed` (rSchoolToday widget GUID `fef0129c-…`) | league_feed | Single API call covers every ISL boys-tennis match. |
| Phillips Exeter Academy | Eight Schools | `exeter_site` (SIDEARM HTML at `weareexeter.com`) | home_site | Full schedule + scores. |
| Phillips Academy Andover | Eight Schools | `andover_site` (custom HTML at `athletics.andover.edu`) | home_site | **Schedule only — past results require JS to render.** Scores come from opponent feeds or manual entry. |
| St. Paul's School | Eight Schools | `sps_site` (SIDEARM HTML at `athletics.sps.edu`) | home_site | Full schedule + scores. |
| Avon Old Farms | Founders | `avon_site` (Veracross ICS) | home_site | Full schedule + scores embedded in calendar event descriptions. |
| Loomis Chaffee | Founders | `loomis_site` (FinalSite athletics composite) | home_site | Full schedule + scores. |
| Hotchkiss School | Founders | `hotchkiss_site` (FinalSite) | home_site | Full schedule + scores. |
| Kent School | Founders | `kent_site` (FinalSite) | home_site | Full schedule + scores. |
| Brunswick School | Fairchester | `brunswick_site` (FinalSite) | home_site | Full schedule + scores. |
| Choate Rosemary Hall | Founders | `choate_site` (FinalSite, **partial**) | home_site | Static HTML caps at the first 5–6 events. "Load More" button uses JS — older games miss. |
| Northfield Mt. Hermon | NEPSAC | `nmh_site` (FinalSite, **partial**) | home_site | Same Load-More cap as Choate. |
| Deerfield Academy | Eight Schools | none | — | WordPress site, schedule rendered client-side. Scores arrive via opponent feeds (BH, SPS, etc.). |
| Hopkins School | Founders | none | — | Blackbaud / myschoolapp; client-side rendering. Scores arrive via opponent feeds. |
| Kingswood-Oxford | Founders | none | — | WordPress + Event Organiser plugin; per-event pages have scores in HTML but no aggregated feed. Scores arrive via opponent feeds (Loomis, Avon, Choate). |
| Taft School | Founders | none | — | rSchoolToday widget rendered client-side. Scores arrive via opponent feeds. |

## How sources are layered

The orchestrator (`scripts/update_scores.py`) merges every source by precedence:

```
manual > home_site > away_site > league_feed > newspaper > scraped
```

If two sources disagree on a score, the higher-tier one wins; same-tier ties keep the earlier write. Even when a school has no direct fetcher, their matches still show up in the database whenever they play someone who does. The Hopkins / Deerfield / K-O / Taft entries above currently have 4–9 completed matches each just from opponent-side ingestion.

## Fetcher modules

Each module is standalone and can be run from the CLI for one-off tests.

- `scripts/fetch_rschooltoday.py` — rSchoolToday widget by GUID. One GUID can return every team for an entire league. Use this whenever you find an `embed.rschooltoday.com` URL or a `widgetGuid="…"` attribute.
- `scripts/fetch_sidearm.py` — SIDEARM Sports HTML. Look for `class="sidearm-schedule-game"` blocks on a `/sports/{slug}/schedule` URL.
- `scripts/fetch_veracross.py` — Veracross calendar feed (`api.veracross.com/{org}/teams/{team_id}.ics?t=…&uid=…`). Find the URL on a school's tennis page as the "Add to Calendar" button.
- `scripts/fetch_finalsite.py` — FinalSite athletics composites. Pages contain `<tr class="fsResult…">` (table layout) or `<article class="fsResult…">` (card layout) with `fsAthleticsOpponentName` / `fsAthleticsScore` / `fsAthleticsAdvantage` cells. Filters to Varsity rows automatically.
- `scripts/fetch_andover.py` — Andover-specific custom CMS (`event__wrapper` / `event-opponent` / `event-result`). Schedule-only because past results require JS.

## Adding a new school — recipe

1. **Identify the CMS.** Visit the school's boys-varsity-tennis page. View source. Search for: `sidearm`, `fsResult`, `api.veracross.com`, `rschooltoday`, `widgetGuid`, `data-team-id`, `iframe src=`, `?action=ical`. The first hit usually tells you everything.
2. **Pick the fetcher.** Use the table above to map CMS → module. If it's a brand-new CMS, follow the `fetch_andover.py` template — write a regex for the row wrapper, the date, the opponent, the home/away marker, and the score.
3. **Verify alone.** From `Sports/Tennis/League/`: `python3 scripts/fetch_<cms>.py "School Name" "URL"`. You should see a JSON dump of matches with at least a few completed rows showing scores.
4. **Add a SOURCES entry.** In `scripts/update_scores.py`, append a dict to the `SOURCES` list with `name`, `tier` (almost always `home_site`), `tag` (a short slug like `loomis_site`), `owner`, and a `fetcher` lambda. Use `manual` tier only for `manual_scores.csv`.
5. **Add aliases if needed.** If the new feed names a school differently than the canonical name in `data/schools.json` (e.g., "Loomis Chaffee School" vs "Loomis Chaffee"), add a one-line `aliases.setdefault(...)` in the `load_aliases()` function.
6. **Run the orchestrator.** `python3 scripts/update_scores.py`. Look at the per-source row count and the new-completed list. If a verified row count appears, your source matched what's already in the database — that's good cross-source confirmation.
7. **Update this file.** Add the school to the table at the top, and note any quirks (paginated schedule, missing scores, naming variants).

## Token / link rotation

- **Veracross** tokens (the `t=…` and `uid=…` in the ICS URL) rotate rarely but can change on the school's side without notice. If `python3 scripts/fetch_veracross.py "Avon Old Farms" "<url>"` starts returning 0 rows, re-grab the URL from the "Add to Calendar" button on the school's page.
- **rSchoolToday** widget GUIDs are stable for years.
- **SIDEARM** schedule URLs follow `https://{site}/sports/{slug}/schedule` — the slug for boys tennis is sometimes `mens-tennis`, `boys-tennis`, or `btev`. If a fetcher 404s, browse to the team page in a browser and copy the schedule URL.
- **FinalSite** team URLs change when the school redesigns their site (every 3–5 years). They show up in `404` for the source — re-find the page on the school's athletics site and update the URL in `SOURCES`.

## Known limitations

- **Choate, NMH** initial render is capped at ~5 events. Their "Load More" button hits a FinalSite AJAX endpoint at `/fs/elements/{element_id}?row=N&filter=…` — adding a follow-up paginated fetch is a future improvement.
- **Andover** past results are JS-only. Pull from BH, SPS, or other Eight Schools opponent feeds instead, or type into `manual_scores.csv`.
- **Hopkins, Deerfield, Kingswood-Oxford, Taft** have no direct feed. Either write a custom fetcher (browser automation needed for Hopkins/Taft; per-event scrape for K-O) or rely on opponent ingestion plus `manual_scores.csv` for the gaps.

## Quickest manual-entry path

Don't fight the scrapers when a single match is missing. From any terminal:

```
cd ~/Desktop/Belmont\ Hill\ Mac\ Mini/Sports/Tennis/League
python3 scripts/log.py 2026-05-09 "Hopkins School" 4 "Loomis Chaffee" 3 "from program"
python3 scripts/update_scores.py
python3 scripts/render_dashboard.py
```

Manual rows have the highest precedence — they overwrite anything else.
