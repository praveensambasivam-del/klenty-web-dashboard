"""Pipedrive reader + the agreed demo/trial counting rules (standard library only).

Token: env PIPEDRIVE_TOKEN. Tests can pass a folder of saved pulls instead (see load_fixture).
"""
import json, os, time, urllib.request, urllib.parse
from datetime import datetime, timedelta
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
DT, LP, SP, DS, RG, MQ = ("5a218b3c7ef1ce2c91b7144fb451acdd95c598f3", "3b0187d163a424b1b0fb080c6f61265519aecf67",
                          "533d24f49352ab690127ce300c770fca06e145a6", "17a15b65151c6b068b70c1572b9c36f36538eb62",
                          "421b89955beb32ce8f285a20095828822d246a91", "1d7827a726617844c6c85eff9d49fc563a2eda74")
FIELDS = [DT, LP, SP, DS, RG, MQ]
PIPELINES = (2, 5, 14, 36, 1)   # demos = Demo & Chat Requests (2) + AE Opportunities (5) + ICP Decision Delayed (14).  trials = Single User (36) + MQL SDR Trial (1).
DEMO_PIPES, TRIAL_PIPES = {2, 5, 14}, {36, 1}   # counted by pipeline, whatever the Deal Type says (rules set by Praveen 2026-11-01)
DEMO_TYPES = TRIAL_TYPES = None
TEST_WORDS = ("@klenty.com", "test", "@copytosh", "abc@xyz.com", "praveen@tutecircle.com")
API = "https://api.pipedrive.com"


def _get(path, params=None, tries=4):
    tok = os.environ["PIPEDRIVE_TOKEN"]
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"x-api-token": tok, "Accept": "application/json"})
            return json.load(urllib.request.urlopen(req, timeout=120))
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and i < tries - 1:
                time.sleep(3 * (i + 1)); continue
            raise RuntimeError(f"Pipedrive {e.code} on {path}")


def outbound_ids():
    """Deal Source option ids whose label contains 'outbound' (from the live field list; falls back to the saved list)."""
    try:
        r = _get("/api/v1/dealFields", {"limit": 500})
        for f in r["data"]:
            if f.get("key") == DS:
                ids = [o["id"] for o in f.get("options", []) if "outbound" in o["label"].lower()]
                if ids:
                    return set(ids)
    except Exception as e:
        print("warning: could not read deal fields, using saved outbound list:", e)
    return set(json.load(open(os.path.join(HERE, "..", "config", "outbound_ids.json")))["deal_source_outbound_option_ids"])


def fetch_pipeline(pid, since):
    """All non-archived deals of a pipeline added on/after `since` (a date, UTC-ish; callers pass a margin)."""
    out, cursor = [], None
    while True:
        p = {"pipeline_id": pid, "sort_by": "add_time", "sort_direction": "desc", "limit": 500, "custom_fields": ",".join(FIELDS)}
        if cursor:
            p["cursor"] = cursor
        r = _get("/api/v2/deals", p)
        rows = r.get("data") or []
        out += rows
        cursor = (r.get("additional_data") or {}).get("next_cursor")
        if not rows or not cursor or min(x["add_time"] for x in rows)[:10] < str(since):
            return out


def fetch_all(since):
    deals = {}
    for pid in PIPELINES:
        for x in fetch_pipeline(pid, since):
            deals[x["id"]] = x
    return list(deals.values())


def load_fixture(folder):
    deals = {}
    for pid in PIPELINES:
        f = os.path.join(folder, f"p{pid}.json")
        if os.path.exists(f):
            for x in json.load(open(f))["data"]:
                deals[x["id"]] = x
    return list(deals.values())


# ---------------------------------------------------------------- the agreed rules
ist_date = lambda s: (datetime.strptime(s[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S") + timedelta(hours=5, minutes=30)).date()
is_test = lambda x: any(k in (x["title"] or "").lower() for k in TEST_WORDS)
is_web = lambda x: x["origin"] in ("API", "Marketplace")
url_path = lambda u: None if not u else (urlparse(u if "//" in u else "//" + u).path.rstrip("/") or "/")


def pick(deals, types, pipes, s, e, out_ids, drop_outbound):
    """Website deals of the given type in the window, one per person (first one), test emails and (optionally) outbound removed."""
    by = {}
    for x in deals:
        if (s <= ist_date(x["add_time"]) <= e and not is_test(x) and is_web(x)
                and (types is None or x["custom_fields"].get(DT) in types) and x["pipeline_id"] in pipes):
            by.setdefault((x["title"] or "").strip().lower(), []).append(x)
    firsts = [sorted(c, key=lambda x: x["add_time"])[0] for c in by.values()]
    if drop_outbound:
        firsts = [x for x in firsts if not (set(x["custom_fields"].get(DS) or []) & out_ids)]
    return firsts


def deal_stats(deals, s, e, out_ids, path_to_name):
    dm = pick(deals, DEMO_TYPES, DEMO_PIPES, s, e, out_ids, True)
    tr = pick(deals, TRIAL_TYPES, TRIAL_PIPES, s, e, out_ids, False)
    mql = lambda x: x["custom_fields"].get(MQ) == 36
    pages = {n: {"demos": 0, "trials": 0} for n in path_to_name.values()}
    for x in dm:
        n = path_to_name.get(url_path(x["custom_fields"].get(SP) or x["custom_fields"].get(LP)))
        if n: pages[n]["demos"] += 1
    for x in tr:
        n = path_to_name.get(url_path(x["custom_fields"].get(LP)))
        if n: pages[n]["trials"] += 1
    return {"demos": len(dm), "trials": len(tr), "demo_mql": sum(map(mql, dm)), "trial_mql": sum(map(mql, tr)), "pages": pages}


# ---------------------------------------------------------------- regions and sources of deals
REGION_BY_ID = {173: "North America", 174: "Latin America", 243: "Europe / UK", 244: "AMEA"}
REGIONS = ["AMEA", "North America", "Europe / UK", "Latin America"]
SEO, PAID, SOCIAL, EMAIL, VIDEO = {65, 66, 67, 68, 69, 70, 112, 113, 156, 157, 158, 159, 588}, {88, 80}, {110, 160, 111}, {74, 464}, {522}
REFER = {64, 521, 107, 75, 355, 62, 114, 115, 39, 78, 91, 72}
SOURCES = ["Organic Search (SEO and AEO)", "Direct (source not found)", "Social Media", "Email", "Referral", "Paid Search (Google Ads)", "Organic Video"]


def _ids(v):
    return set(v) if isinstance(v, (list, tuple, set)) else ({v} if v is not None else set())


def deal_region(x):
    for i in _ids(x["custom_fields"].get(RG)):
        if i in REGION_BY_ID:
            return REGION_BY_ID[i]
    return None


def deal_source(x):
    s = _ids(x["custom_fields"].get(DS))
    for name, grp in (("Organic Search (SEO and AEO)", SEO), ("Paid Search (Google Ads)", PAID), ("Social Media", SOCIAL),
                      ("Email", EMAIL), ("Referral", REFER), ("Organic Video", VIDEO)):
        if s & grp:
            return name
    return "Direct (source not found)"


def group_stats(deals, s, e, out_ids):
    """Demos and trials of the window split by region and by source (same picks as deal_stats)."""
    dm = pick(deals, DEMO_TYPES, DEMO_PIPES, s, e, out_ids, True)
    tr = pick(deals, TRIAL_TYPES, TRIAL_PIPES, s, e, out_ids, False)
    reg = {r: {"demos": 0, "trials": 0} for r in REGIONS}
    src = {n: {"demos": 0, "trials": 0} for n in SOURCES}
    for kind, rows in (("demos", dm), ("trials", tr)):
        for x in rows:
            r = deal_region(x)
            if r: reg[r][kind] += 1
            src[deal_source(x)][kind] += 1
    return reg, src
