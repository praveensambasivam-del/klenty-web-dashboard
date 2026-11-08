"""Builds the dashboard data file.

usage: python3 scripts/build_data.py --mode full|live [--weeks 13] [--history data/history.json] [--out site/data.json] [--fixture DIR]

full : recompute every week (visitors, pages, deals, engagement). Run once a day. Saves data/history.json.
live : recompute only the current week and the one before it (plus the same-weekday comparison), and reuse
       everything else, including the engagement numbers, from data/history.json. Run every 30 minutes.
Weeks run Monday to Sunday (India time). The current week stops at today.
"""
import argparse, json, os, sys, statistics
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ga4, pipedrive as pd

PAGES = json.load(open(os.path.join(HERE, "..", "config", "pages.json")))
NAME_BY_PATH = {(p["path"].rstrip("/") or "/"): p["name"] for p in PAGES}
TRK_PATHS = [x for p in NAME_BY_PATH for x in ((p + "/", p) if p != "/" else ("/",))]
TRK = ga4.inl("pagePath", TRK_PATHS)
MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DIMS8 = ["dateHourMinute", "country", "city", "operatingSystem", "browser", "deviceCategory", "sessionSource", "sessionDefaultChannelGroup"]


def today_ist():
    return (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).date()


def label(s, e):
    return f"{MON[s.month-1]} {s.day} - {e.day}" if s.month == e.month else f"{MON[s.month-1]} {s.day} - {MON[e.month-1]} {e.day}"


def week_windows(n):
    t = today_ist(); mon = t - timedelta(days=t.weekday()); out = []
    for i in range(n):
        s = mon - timedelta(weeks=i); e = s + timedelta(days=6)
        out.append((s, min(e, t), e > t))
    return out[::-1]    # oldest first


# ------------------------------------------------------------------ GA4 numbers
def page_visitors(s, e):
    clean = {}
    for r in ga4.run(ga4._and(TRK, ga4.CLEAN2), ["totalUsers"], ["pagePath"], s, e):
        p = ga4.dv(r)[0].rstrip("/") or "/"
        if p in NAME_BY_PATH: clean[NAME_BY_PATH[p]] = clean.get(NAME_BY_PATH[p], 0) + ga4.mv(r)[0]
    d7 = ga4.D6 + ["pagePath"]
    seg = {tuple(ga4.dv(r)): ga4.mv(r)[0] for r in ga4.run(ga4._and(TRK, ga4.SEG), ["totalUsers"], d7, s, e)}
    for r in ga4.run(ga4._and(TRK, ga4.SEG, ga4.inl("eventName", ga4.KEYEV)), ["totalUsers"], d7, s, e):
        k = tuple(ga4.dv(r))
        if ga4.mv(r)[0] > 0 and k in seg:
            p = k[6].rstrip("/") or "/"
            # rescue only the people who did the key action, not everyone in the same minute/place/device group
            if p in NAME_BY_PATH: clean[NAME_BY_PATH[p]] = clean.get(NAME_BY_PATH[p], 0) + min(seg[k], ga4.mv(r)[0])
    return clean


def site_numbers(s, e):
    raw, clean, resc, real = ga4.real_visitors(ga4.ALL, s, e)
    return {"visitors": round(real), "visitors_raw": round(raw)}


def _median_stats(rows):
    """rows of (average seconds per user in this slice, users): expand by users, then median and share over 10 seconds."""
    vals = []
    for a, n in rows: vals += [a] * n
    if not vals: return {"visits": 0, "median": 0, "over10": 0}
    return {"visits": len(vals), "median": round(statistics.median(vals), 1), "over10": round(100 * sum(1 for t in vals if t > 10) / len(vals))}


def engagement(s, e):
    """Average time per person (GA4's own figure) and an estimated median per visit, bots removed."""
    out = {"site": {}, "pages": {}}
    r = ga4.run(ga4.CLEAN2, ["userEngagementDuration", "activeUsers"], [], s, e)
    if r:
        m = ga4.mv(r[0]); out["site"]["avg"] = round(m[0] / m[1], 1) if m[1] else 0; out["site"]["users"] = round(m[1])
    rows = []
    for r in ga4.run(ga4.CLEAN2, ["userEngagementDuration", "activeUsers"], DIMS8, s, e):
        m = ga4.mv(r); n = int(m[1])
        if n >= 1: rows.append((m[0] / n, n))
    out["site"].update(_median_stats(rows))
    tot, usr, prow = {}, {}, {}
    for r in ga4.run(ga4._and(TRK, ga4.CLEAN2), ["userEngagementDuration", "activeUsers"], ["pagePath"], s, e):
        p = ga4.dv(r)[0].rstrip("/") or "/"; m = ga4.mv(r)
        if p in NAME_BY_PATH:
            n = NAME_BY_PATH[p]; tot[n] = tot.get(n, 0) + m[0]; usr[n] = usr.get(n, 0) + m[1]
    for r in ga4.run(ga4._and(TRK, ga4.CLEAN2), ["userEngagementDuration", "activeUsers"], ["pagePath"] + DIMS8, s, e):
        d = ga4.dv(r); m = ga4.mv(r); n = int(m[1]); p = d[0].rstrip("/") or "/"
        if n >= 1 and p in NAME_BY_PATH: prow.setdefault(NAME_BY_PATH[p], []).append((m[0] / n, n))
    for n in set(tot) | set(prow):
        out["pages"][n] = {"avg": round(tot.get(n, 0) / usr[n], 1) if usr.get(n) else 0, **_median_stats(prow.get(n, []))}
    return out


# ------------------------------------------------------------------ regions and sources (visitors)
NA_C = {"United States", "Canada"}
LATAM_C = {"Mexico", "Guatemala", "Belize", "Honduras", "El Salvador", "Nicaragua", "Costa Rica", "Panama", "Cuba", "Dominican Republic", "Haiti",
           "Jamaica", "Trinidad & Tobago", "Bahamas", "Barbados", "Puerto Rico", "Colombia", "Venezuela", "Ecuador", "Peru", "Bolivia", "Brazil",
           "Chile", "Argentina", "Uruguay", "Paraguay", "Guyana", "Suriname"}
EUK_C = {"United Kingdom", "Ireland", "Germany", "France", "Spain", "Portugal", "Italy", "Netherlands", "Belgium", "Luxembourg", "Switzerland", "Austria",
         "Denmark", "Sweden", "Norway", "Finland", "Iceland", "Poland", "Czechia", "Slovakia", "Hungary", "Romania", "Bulgaria", "Greece", "Croatia",
         "Slovenia", "Serbia", "Bosnia & Herzegovina", "Montenegro", "North Macedonia", "Albania", "Kosovo", "Estonia", "Latvia", "Lithuania", "Malta",
         "Cyprus", "Ukraine", "Moldova", "Belarus", "Georgia", "Armenia", "Azerbaijan", "Russia", "Türkiye", "Turkey"}


def region_of(country):
    if country in NA_C: return "North America"
    if country in LATAM_C: return "Latin America"
    if country in EUK_C: return "Europe / UK"
    if country in ("(not set)", ""): return None
    return "AMEA"


CH = lambda *n: ga4.OR(*[ga4.sf("sessionDefaultChannelGroup", x) for x in n]) if len(n) > 1 else ga4.sf("sessionDefaultChannelGroup", n[0])
LINKEDIN_TAGS = ("ayesha", "chris", "amish-cri", "amish")
TAGS = ga4.OR(*[ga4.sf("sessionSourceMedium", f"linkedin / {t}") for t in LINKEDIN_TAGS])
KNOWN = CH("Organic Search", "AI Assistant", "Direct", "Unassigned", "Organic Social", "Email", "Referral", "Paid Search", "Organic Video")
S0, S1, S2, S3, S4, S5, S6 = pd.SOURCES
SRC_FILTER = {S0: CH("Organic Search", "AI Assistant"), S1: ga4.OR(CH("Direct", "Unassigned"), ga4.NOT(KNOWN)),
              S2: ga4.AND(CH("Organic Social"), ga4.NOT(TAGS)), S3: ga4.OR(CH("Email"), TAGS), S4: CH("Referral"), S5: CH("Paid Search"), S6: CH("Organic Video")}


def source_of(channel, source_medium):
    tagged = source_medium in tuple("linkedin / " + t for t in LINKEDIN_TAGS)
    if channel in ("Organic Search", "AI Assistant"): return S0
    if channel == "Email" or (tagged and channel == "Organic Social"): return S3
    if channel == "Organic Social": return S2
    if channel == "Referral": return S4
    if channel == "Paid Search": return S5
    if channel == "Organic Video": return S6
    return S1


def _rescued(s, e):
    """Key-action visitors from the removed (bot-like) groups: [(country, channel, source_medium, users)]."""
    d = ga4.D6 + ["sessionSourceMedium"]
    seg = {tuple(ga4.dv(r)): ga4.mv(r)[0] for r in ga4.run(ga4.SEG, ["totalUsers"], d, s, e)}
    out = []
    for r in ga4.run(ga4._and(ga4.SEG, ga4.inl("eventName", ga4.KEYEV)), ["totalUsers"], d, s, e):
        k = tuple(ga4.dv(r))
        if ga4.mv(r)[0] > 0 and k in seg: out.append((k[1], k[5], k[6], min(seg[k], ga4.mv(r)[0])))   # only the people who acted
    return out


def region_source_visitors(s, e):
    reg = {r: 0 for r in pd.REGIONS}
    for r in ga4.run(ga4.CLEAN2, ["totalUsers"], ["country"], s, e):
        g = region_of(ga4.dv(r)[0])
        if g: reg[g] += ga4.mv(r)[0]
    src = {n: ga4.distinct(ga4.AND(ga4.CLEAN2, f), s, e) for n, f in SRC_FILTER.items()}
    for country, ch, sm, n in _rescued(s, e):
        g = region_of(country)
        if g: reg[g] += n
        src[source_of(ch, sm)] += n
    return {k: round(v) for k, v in reg.items()}, {k: round(v) for k, v in src.items()}


# ------------------------------------------------------------------ one window
def window_metrics(s, e, deals, out_ids, with_pages=True):
    m = site_numbers(s, e)
    ds = pd.deal_stats(deals, s, e, out_ids, NAME_BY_PATH)
    m.update({k: ds[k] for k in ("demos", "trials", "demo_mql", "trial_mql")})
    m["conv"] = round((ds["demos"] + ds["trials"]) / m["visitors"] * 100, 2) if m["visitors"] else 0
    if with_pages:
        rv, sv = region_source_visitors(s, e)
        rd, sd = pd.group_stats(deals, s, e, out_ids)
        m["regions"] = {k: {"visitors": rv[k], **rd[k]} for k in pd.REGIONS}
        m["sources"] = {k: {"visitors": sv[k], **sd[k]} for k in pd.SOURCES}
        pv = page_visitors(s, e)
        m["pages"] = {p["name"]: {"visitors": round(pv.get(p["name"], 0)), **ds["pages"][p["name"]]} for p in PAGES}
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["full", "live"], default="live")
    ap.add_argument("--weeks", type=int, default=13)
    ap.add_argument("--history", default=os.path.join(HERE, "..", "data", "history.json"))
    ap.add_argument("--out", default=os.path.join(HERE, "..", "site", "data.json"))
    ap.add_argument("--fixture", help="folder of saved Pipedrive pulls (tests only)")
    a = ap.parse_args()

    wins = week_windows(a.weeks)
    oldest = wins[0][0] - timedelta(days=8)
    if a.fixture:
        deals, out_ids = pd.load_fixture(a.fixture), set(json.load(open(os.path.join(HERE, "..", "config", "outbound_ids.json")))["deal_source_outbound_option_ids"])
    else:
        recent = wins[-2][0] - timedelta(days=8)
        deals, out_ids = pd.fetch_all(oldest if a.mode == "full" else recent), pd.outbound_ids()
    print(f"{len(deals)} deals loaded; {len(wins)} weeks, mode={a.mode}", flush=True)

    hist = {}
    if a.mode == "live" and os.path.exists(a.history):
        hist = {w["start"]: w for w in json.load(open(a.history))["weeks"]}
    if a.mode == "live" and any(str(w[0]) not in hist for w in wins):
        sys.exit("live mode needs data/history.json from a full run first (run with --mode full)")
    weeks = []
    for i, (s, e, partial) in enumerate(wins):
        if a.mode == "full" or i >= len(wins) - 2:
            m = window_metrics(s, e, deals, out_ids)
            m["engagement"] = engagement(s, e) if a.mode == "full" else hist.get(str(s), {}).get("engagement")
            print(" ", s, e, "visitors", m["visitors"], "demos", m["demos"], "trials", m["trials"], "conv", m["conv"], flush=True)
        else:
            m = hist[str(s)]
        m.update({"start": str(s), "end": str(e), "label": label(s, wins[i][0] + timedelta(days=6)), "partial": partial})
        if partial:     # same weekdays one week earlier, for the tile comparison
            ps, pe = s - timedelta(days=7), e - timedelta(days=7)
            m["prior"] = {"start": str(ps), "end": str(pe), **window_metrics(ps, pe, deals, out_ids, with_pages=False)}
        weeks.append(m)
    data = {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "mode": a.mode,
            "pages": PAGES, "weeks": weeks[1:] if len(weeks) > 12 else weeks}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    json.dump(data, open(a.out, "w"), indent=1)
    if a.mode == "full":
        os.makedirs(os.path.dirname(os.path.abspath(a.history)), exist_ok=True)
        json.dump({"weeks": weeks}, open(a.history, "w"), indent=1)
    print("wrote", a.out)


if __name__ == "__main__":
    main()
