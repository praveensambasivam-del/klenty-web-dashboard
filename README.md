# Klenty website visitors dashboard

A live dashboard: four tiles (real visitors, demo requests, trials, overall website conversion), a week-over-week line graph
(visitors, demos, trials, conversion rate), the 22 tracked pages, and an engagement section (average and median time).
Refreshes every 30 minutes. Published on Cloudflare Pages as `klenty-web-dashboard`.

## How it works
- `scripts/build_data.py` reads GA4 (`scripts/ga4.py`) and Pipedrive (`scripts/pipedrive.py`) and writes `site/data.json`.
- `site/index.html` is the page. It reads `data.json` when opened and every 10 minutes after.
- `.github/workflows/refresh.yml` runs every 30 minutes: recalculates the current week and last week, publishes.
- `.github/workflows/daily.yml` runs at 02:00 India time: recalculates all 13 weeks including engagement, saves `data/history.json`
  (numbers only), publishes. **Run it once by hand first** (Actions tab, "Full recalculation", Run workflow). The 30-minute job
  skips itself until `data/history.json` exists.

## The agreed rules (do not change without agreement)
- Real visitors: bot rule in `scripts/ga4.py` (`CLEAN2`) plus key-action rescue. Distinct people per period.
- Demos (rules set by Praveen 2026-11-01): every deal created in the period in Demo & Chat Requests (2), AE Opportunities (5) and ICP Decision Delayed (14), whatever its Deal Type says.
  Website origin (API/Marketplace), test emails removed, one per person per week, outbound deal source excluded.
  Page by Deal Source Page then Landing Page.
- Trials: every deal in Single User (36) and MQL SDR Trial (1). Page by Landing Page.
  Not counted: the unknown pipeline (9), 25 and 56.
- Weeks are Monday to Sunday, India time. Conversion = (demos + trials) / real visitors.
- Tracked pages: `config/pages.json` (22). To add a page, add a line there; it counts from the next run.

## Secrets (GitHub repo, Settings > Secrets and variables > Actions)
`GA4_KEY_JSON`, `PIPEDRIVE_TOKEN`, `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`. Never put these in the code.

## Local test (no secrets in the repo)
    GA4_KEY_FILE=/path/to/key.json python3 scripts/build_data.py --mode full --weeks 5 --fixture tests/fixture --out /tmp/data.json
    python3 -m unittest discover tests
The fixture folder (saved Pipedrive pulls, personal data) is not committed.

## Checks to do after the first run
Oct 19-25 must read 1,274 visitors, 11 demos, 17 trials, 2.2%. Oct 12-18: 1,428 / 15 / 28.

## Known limits
- Median time is an estimate (GA4 has no per-person times).
- Custom range picks whole weeks within the last 12. Exact custom dates would need a small Cloudflare Worker.
- Deals archived later in Pipedrive disappear from live pulls, so old counts can drift slightly.
- GA4 revises the last day or two; the numbers can move a little.
