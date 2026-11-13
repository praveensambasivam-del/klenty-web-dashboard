"""GA4 Data API client using only the Python standard library + openssl (no pip packages).

Key: env GA4_KEY_JSON (the service-account JSON text, used in GitHub Actions) or env GA4_KEY_FILE (a path, used locally).
"""
import json, base64, time, subprocess, urllib.request, urllib.parse, os, tempfile

PROP = os.environ.get("GA4_PROPERTY", "264568011")
HERE = os.path.dirname(os.path.abspath(__file__))
_tok = {}


def _key():
    if os.environ.get("GA4_KEY_JSON"):
        return json.loads(os.environ["GA4_KEY_JSON"])
    return json.load(open(os.environ["GA4_KEY_FILE"]))


def token():
    if _tok.get("t") and _tok["exp"] > time.time() + 60:
        return _tok["t"]
    k = _key()
    b = lambda x: base64.urlsafe_b64encode(x).rstrip(b"=")
    now = int(time.time())
    si = b(json.dumps({"alg": "RS256", "typ": "JWT"}).encode()) + b"." + b(json.dumps({
        "iss": k["client_email"], "scope": "https://www.googleapis.com/auth/analytics.readonly",
        "aud": "https://oauth2.googleapis.com/token", "iat": now, "exp": now + 3600}).encode())
    fd, pem = tempfile.mkstemp()
    os.write(fd, k["private_key"].encode()); os.close(fd); os.chmod(pem, 0o600)
    try:
        sig = subprocess.run(["openssl", "dgst", "-sha256", "-sign", pem], input=si, capture_output=True, check=True).stdout
    finally:
        os.remove(pem)
    body = urllib.parse.urlencode({"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                   "assertion": (si + b"." + b(sig)).decode()}).encode()
    r = json.load(urllib.request.urlopen(urllib.request.Request("https://oauth2.googleapis.com/token", data=body), timeout=60))
    _tok.update(t=r["access_token"], exp=time.time() + r.get("expires_in", 3600))
    return _tok["t"]


def post(path, body, tries=4):
    url = f"https://analyticsdata.googleapis.com/v1beta/properties/{PROP}{path}"
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                         headers={"Authorization": "Bearer " + token(), "Content-Type": "application/json"})
            return json.load(urllib.request.urlopen(req, timeout=120))
        except urllib.error.HTTPError as e:
            # Google sometimes answers 502/504 or stalls for a moment: try again instead of failing the whole refresh
            if e.code in (429, 500, 502, 503, 504) and i < tries - 1:
                time.sleep(5 * (i + 1)); continue
            raise RuntimeError(f"GA4 {e.code}: {e.read().decode()[:300]}")
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            if i < tries - 1:
                time.sleep(5 * (i + 1)); continue
            raise RuntimeError(f"GA4 network error: {e}")


# Only the live site counts. Google Translate's copy of it is real visitors too. Test hosts (localhost, 127.0.0.1, test-*.kl-infra.com) are left out of every report.
SITE_HOSTS = ["www.klenty.com", "www-klenty-com.translate.goog"]


def run(flt, mets, dims, s, e):
    flt = _and({"filter": {"fieldName": "hostName", "inListFilter": {"values": SITE_HOSTS}}}, flt)
    rows, off = [], 0
    while True:
        body = {"dimensions": [{"name": d} for d in dims], "metrics": [{"name": m} for m in mets],
                "dateRanges": [{"startDate": str(s), "endDate": str(e)}], "limit": 100000, "offset": off}
        if flt is not None:
            body["dimensionFilter"] = flt
        r = post(":runReport", body)
        rows += r.get("rows", []); off += 100000
        if off >= r.get("rowCount", 0):
            return rows


dv = lambda r: [d["value"] for d in r["dimensionValues"]]
mv = lambda r: [float(m["value"]) for m in r["metricValues"]]
sf = lambda f, v: {"filter": {"fieldName": f, "stringFilter": {"value": v, "matchType": "EXACT"}}}
inl = lambda f, vs: {"filter": {"fieldName": f, "inListFilter": {"values": vs}}}
AND = lambda *e: {"andGroup": {"expressions": list(e)}}
OR = lambda *e: {"orGroup": {"expressions": list(e)}}
NOT = lambda e: {"notExpression": e}

# ---- the agreed real-visitor rule (same as CLEAN2 in the reports) ----
_CL = json.load(open(os.path.join(HERE, "..", "config", "derived_clusters.json")))["extra"]
LINUX = AND(sf("operatingSystem", "Linux"), sf("sessionSource", "(direct)"))
_GEO = OR(inl("country", ["China", "Hong Kong", "Japan", "Germany", "Ireland", "Netherlands", "South Korea", "France"]),
          AND(sf("country", "United States"), inl("city", ["(not set)", "Ashburn", "Flower Mound", "Glenview"])))
BOTLIKE = OR(sf("country", "Singapore"), AND(sf("country", "United States"), sf("city", "Ashburn"), sf("operatingSystem", "(not set)")), AND(sf("sessionSource", "(direct)"), OR(_GEO, *[
    AND(sf("operatingSystem", x["os"]), sf("country", x["country"]), sf("city", x["city"])) for x in _CL])))
CLEAN2 = AND(NOT(LINUX), NOT(BOTLIKE))
SEG = OR(LINUX, BOTLIKE)
ALL = None   # no filter
KEYEV = ["demo_button_clicks", "Demo_Form", "signup_button_clicks", "Signed_up_Success", "signup_form_submit", "one_tap_signup"]
D6 = ["dateHourMinute", "country", "city", "operatingSystem", "sessionSource", "sessionDefaultChannelGroup"]


def _and(*fs):
    fs = [f for f in fs if f is not None]
    return fs[0] if len(fs) == 1 else AND(*fs)


def distinct(flt, s, e):
    r = run(flt, ["totalUsers"], [], s, e)
    return mv(r[0])[0] if r else 0.0


def real_visitors(base, s, e):
    """(raw, clean, rescued, real): real = bots removed + key-action visitors rescued from the removed groups."""
    raw, clean = distinct(base, s, e), distinct(_and(base, CLEAN2), s, e)
    seg = {tuple(dv(r)): mv(r)[0] for r in run(_and(base, SEG), ["totalUsers"], D6, s, e)}
    # rescue only the people who did a key action, not everyone in the same minute/place/device group
    ka = {tuple(dv(r)): mv(r)[0] for r in run(_and(base, SEG, inl("eventName", KEYEV)), ["totalUsers"], D6, s, e) if mv(r)[0] > 0}
    resc = sum(min(seg[k], n) for k, n in ka.items() if k in seg)
    return raw, clean, resc, clean + resc
