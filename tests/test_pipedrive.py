"""Offline tests: paging logic and counting rules, no network. Run: python3 -m unittest discover tests"""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import pipedrive as pd
from datetime import date

def deal(i, title, add, pipe, typ, origin="API", **cf):
    c = {pd.DT: typ, pd.LP: None, pd.SP: None, pd.DS: None, pd.MQ: None}; c.update(cf)
    return {"id": i, "title": title, "add_time": add, "pipeline_id": pipe, "origin": origin, "custom_fields": c}

class Rules(unittest.TestCase):
    P = {"/feature/dynamic-presence": "Dynamic Presence", "/": "Homepage"}
    def test_demo_rules(self):
        d = [deal(1, "a@x.com", "2026-10-20T08:00:00Z", 2, 312, **{pd.SP: "https://www.klenty.com/feature/dynamic-presence/"}),
             deal(2, "a@x.com", "2026-10-21T08:00:00Z", 2, 312),                     # same person twice -> one
             deal(3, "test@y.com", "2026-10-20T08:00:00Z", 2, 312),                  # test email
             deal(4, "b@z.com", "2026-10-20T08:00:00Z", 2, 312, origin="ManuallyCreated"),   # not website
             deal(5, "c@z.com", "2026-10-20T08:00:00Z", 2, 312, **{pd.DS: [7]}),     # outbound
             deal(6, "d@z.com", "2026-10-20T08:00:00Z", 9, 312),                      # unknown pipeline 9
             deal(7, "f@z.com", "2026-10-21T08:00:00Z", 2, 314),                      # trial type but in the demo pipeline: counts
             deal(8, "g@z.com", "2026-10-21T08:00:00Z", 14, 312)]                     # ICP Decision Delayed: counts when created in the period
        r = pd.deal_stats(d, date(2026, 10, 19), date(2026, 10, 25), {7}, self.P)
        self.assertEqual(r["demos"], 3); self.assertEqual(r["pages"]["Dynamic Presence"]["demos"], 1)
    def test_trials_are_pipelines_36_and_1_only(self):
        d = [deal(1, "t1@z.com", "2026-10-20T08:00:00Z", 36, 314, **{pd.LP: "https://www.klenty.com/", pd.MQ: 36}),
             deal(2, "t2@z.com", "2026-10-20T08:00:00Z", 1, 312),                    # MQL SDR Trial, any type
             deal(3, "t3@z.com", "2026-10-20T08:00:00Z", 5, 314),                    # trial type in AE Opportunities: a demo, not a trial
             deal(4, "t4@z.com", "2026-10-20T08:00:00Z", 9, 314)]                    # unknown pipeline
        r = pd.deal_stats(d, date(2026, 10, 19), date(2026, 10, 25), set(), self.P)
        self.assertEqual((r["trials"], r["trial_mql"], r["demos"], r["pages"]["Homepage"]["trials"]), (2, 1, 1, 1))
    def test_india_time_week_edge(self):
        # 20:00 UTC on Sunday Oct 25 is already Monday Oct 26 in India
        d = [deal(1, "e@z.com", "2026-10-25T20:00:00Z", 2, 312)]
        self.assertEqual(pd.deal_stats(d, date(2026, 10, 19), date(2026, 10, 25), set(), self.P)["demos"], 0)
        self.assertEqual(pd.deal_stats(d, date(2026, 10, 26), date(2026, 11, 1), set(), self.P)["demos"], 1)

class Paging(unittest.TestCase):
    def test_stops_when_old_enough(self):
        pages = [{"data": [{"id": 1, "add_time": "2026-10-30T00:00:00Z"}], "additional_data": {"next_cursor": "c1"}},
                 {"data": [{"id": 2, "add_time": "2026-09-01T00:00:00Z"}], "additional_data": {"next_cursor": "c2"}},
                 {"data": [{"id": 3, "add_time": "2026-08-01T00:00:00Z"}], "additional_data": {}}]
        calls = []
        def fake(path, params=None, tries=4):
            calls.append(params.get("cursor")); return pages[len(calls) - 1]
        old, pd._get = pd._get, fake
        try: out = pd.fetch_pipeline(2, date(2026, 10, 1))
        finally: pd._get = old
        self.assertEqual([x["id"] for x in out], [1, 2]); self.assertEqual(calls, [None, "c1"])

if __name__ == "__main__":
    unittest.main()
