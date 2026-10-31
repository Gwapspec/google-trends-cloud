"""Offline tests: the HTTP call is replaced with result rows recorded from the tool (run EjJt61QN7yERqdt1p,
2026-10-30, US, today 3-m, point output)."""
import io
import json
import unittest
from unittest import mock

import google_trends_cloud as gtc

ROWS = [
    {"keyword": "serpapi", "date": "2026-10-01", "value": 0, "partial": False, "marketWideJump": False,
     "status": "ok", "uncertaintyPct": 0.45, "warning": None},
    {"keyword": "serpapi", "date": "2026-10-31", "value": 17, "partial": True, "marketWideJump": False,
     "status": "ok", "uncertaintyPct": 0.45, "warning": None},
    {"keyword": "google trends api", "date": "2026-10-01", "value": 0, "partial": False, "marketWideJump": True,
     "status": "ok", "uncertaintyPct": 2.03, "warning": None},
    {"keyword": "google trends api", "date": "2026-10-31", "value": 0, "partial": True, "marketWideJump": False,
     "status": "ok", "uncertaintyPct": 2.03, "warning": None},
    {"keyword": "pytrends", "date": "2026-10-01", "value": 0, "partial": False, "marketWideJump": False,
     "status": "below_threshold", "uncertaintyPct": None, "warning": None},
    {"keyword": "pytrends", "date": "2026-10-31", "value": 0, "partial": True, "marketWideJump": False,
     "status": "below_threshold", "uncertaintyPct": None, "warning": None},
]
KW = ["pytrends", "google trends api", "serpapi"]


def answer(rows):
    return mock.patch.object(gtc.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(rows).encode()))


class Payload(unittest.TestCase):
    def setUp(self):
        self.t = gtc.TrendReq(token="test-token", hl="en-US", tz=360, retries=2, backoff_factor=0.1)

    def test_pytrends_arguments_map_to_tool_input(self):
        self.t.build_payload(KW + ["serpapi"], cat=5, timeframe="today 3-m", geo="US", gprop="news")
        self.assertEqual(self.t._input, {"keywords": KW, "geo": "US", "category": 5, "searchType": "news",
                                         "outputMode": "point", "timeRange": "today 3-m"})

    def test_date_range(self):
        self.t.build_payload(KW, timeframe="2024-01-01 2024-12-31")
        self.assertEqual(self.t._input["customTimeRange"], "2024-01-01 2024-12-31")
        self.assertNotIn("timeRange", self.t._input)

    def test_refuses_what_the_tool_cant_do(self):
        for kw in ({"timeframe": "now 1-H"}, {"gprop": "shopping"}):
            with self.assertRaises(ValueError):
                self.t.build_payload(KW, **kw)
        with self.assertRaises(ValueError):
            self.t.build_payload([f"k{i}" for i in range(201)])

    def test_no_token(self):
        with mock.patch.dict("os.environ", {}, clear=True), self.assertRaises(gtc.TrendsError):
            gtc.TrendReq()


class Rows(unittest.TestCase):
    def setUp(self):
        self.t = gtc.TrendReq(token="test-token")
        self.t.build_payload(KW, timeframe="today 3-m", geo="US")

    def test_one_run_then_cached(self):
        with answer(ROWS) as urlopen:
            self.t.interest_over_time_rows()
            self.t.interest_over_time_rows()
        self.assertEqual(urlopen.call_count, 1)
        req = urlopen.call_args[0][0]
        self.assertEqual(req.get_header("Authorization"), "Bearer test-token")
        self.assertIn("honestdata~google-trends-one-scale", req.full_url)

    def test_honest_extras(self):
        with answer(ROWS):
            self.t.interest_over_time_rows()
        self.assertEqual(self.t.below_threshold, ["pytrends"])
        self.assertEqual(self.t.uncertainty_pct["google trends api"], 2.03)
        self.assertEqual(self.t.market_wide_jumps, ["2026-10-01"])

    def test_needs_payload(self):
        with self.assertRaises(gtc.TrendsError):
            gtc.TrendReq(token="x").interest_over_time_rows()

    def test_not_yet_points_to_issues(self):
        with self.assertRaises(NotImplementedError):
            self.t.related_queries()


try:
    import pandas  # noqa: F401
    HAVE_PANDAS = True
except ImportError:
    HAVE_PANDAS = False


@unittest.skipUnless(HAVE_PANDAS, "pandas not installed")
class Frame(unittest.TestCase):
    def test_shape_like_pytrends(self):
        t = gtc.TrendReq(token="test-token")
        t.build_payload(KW, timeframe="today 3-m", geo="US")
        with answer(ROWS):
            df = t.interest_over_time()
        self.assertEqual(list(df.columns), KW + ["isPartial"])
        self.assertEqual(str(df.index[0].date()), "2026-10-01")
        self.assertEqual(df["serpapi"].iloc[-1], 17)
        self.assertEqual(list(df["isPartial"]), [False, True])


if __name__ == "__main__":
    unittest.main()
