"""Google Trends interest over time, as a drop-in for pytrends' TrendReq, without 429 errors.

pytrends calls Google directly, so servers and notebooks often get HTTP 429 "too many requests", and
its GitHub repository is archived. This client sends the same request to the hosted Google Trends
tool on Apify (https://apify.com/honestdata/google-trends-one-scale), which handles proxies and
retries. Two differences you get for free: no 5-keyword limit (up to 200), and every keyword on one
0-100 scale, with an error bar per keyword. $0.005 per keyword on Apify's free-plan pricing; keywords
Google has too little data for are free.

    from google_trends_cloud import TrendReq
    pytrends = TrendReq()                # reads APIFY_TOKEN
    pytrends.build_payload(["python", "rust", "go"], timeframe="today 12-m", geo="US")
    df = pytrends.interest_over_time()   # pandas DataFrame, like pytrends
"""
import json
import os
import urllib.error
import urllib.request
from typing import Dict, List, Optional

__version__ = "0.1.0"
__all__ = ["TrendReq", "TrendsError"]

ACTOR = "honestdata~google-trends-one-scale"
ENDPOINT = "https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"
MAX_KEYWORDS = 200
TIMEFRAMES = ("now 7-d", "today 1-m", "today 3-m", "today 12-m", "today 5-y", "all")
GPROPS = ("", "images", "news", "froogle", "youtube")


class TrendsError(Exception):
    """The request failed: missing or wrong token, a timeout, an unsupported option, or an error from Apify."""


def _is_date_range(s: str) -> bool:
    parts = s.split()
    return len(parts) == 2 and all(len(p) == 10 and p[4] == "-" and p[7] == "-" for p in parts)


class TrendReq:
    """pytrends-compatible client. Each interest_over_time() call is one cloud run (under 30 s for a few
    keywords over 3 months; 7 keywords over 12 months took 84 s).

    hl, tz, timeout, proxies, retries, backoff_factor and requests_args are accepted so existing code
    runs unchanged; proxies and retries are handled in the cloud, so they're ignored.
    """

    def __init__(self, hl: str = "en-US", tz: int = 360, token: Optional[str] = None, run_timeout: int = 300,
                 **_pytrends_options):
        self.token = token or os.environ.get("APIFY_TOKEN")
        if not self.token:
            raise TrendsError("No Apify token: set APIFY_TOKEN or pass token=. A free account's token is under "
                              "console.apify.com > Settings > API & Integrations.")
        self.hl, self.tz, self.run_timeout = hl, tz, run_timeout
        self.kw_list: List[str] = []
        self._input: Dict = {}
        self._rows: Optional[List[dict]] = None
        self.uncertainty_pct: Dict[str, Optional[float]] = {}  # error bar (+-1 sigma) on each keyword's level
        self.warnings: Dict[str, str] = {}  # keywords whose peak or growth sits in a market-wide jump
        self.below_threshold: List[str] = []  # too little data at Google: all zeros, not billed
        self.market_wide_jumps: List[str] = []  # dates where Google's data jumped across the board

    def build_payload(self, kw_list: List[str], cat: int = 0, timeframe: str = "today 5-y", geo: str = "",
                      gprop: str = "") -> None:
        """Same arguments as pytrends. Up to 200 keywords, all returned on one scale."""
        kws = list(dict.fromkeys(k.strip() for k in kw_list if k and k.strip()))
        if not kws:
            raise ValueError("kw_list is empty")
        if len(kws) > MAX_KEYWORDS:
            raise ValueError(f"at most {MAX_KEYWORDS} keywords per payload, got {len(kws)}")
        if gprop not in GPROPS:
            raise ValueError(f"gprop must be one of {GPROPS}")
        payload = {"keywords": kws, "geo": geo, "category": int(cat), "searchType": gprop, "outputMode": "point"}
        if timeframe in TIMEFRAMES:
            payload["timeRange"] = timeframe
        elif _is_date_range(timeframe):
            payload["customTimeRange"] = timeframe
        else:
            raise ValueError(f"timeframe {timeframe!r} isn't supported: use one of {TIMEFRAMES} or "
                             "'YYYY-MM-DD YYYY-MM-DD' (hourly ranges like 'now 1-H' aren't available)")
        self.kw_list, self._input, self._rows = kws, payload, None

    def _run(self, payload: dict) -> List[dict]:
        url = ENDPOINT.format(actor=ACTOR) + f"?timeout={self.run_timeout}"
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {self.token}",
                                              "User-Agent": f"google-trends-cloud/{__version__}"})
        try:
            with urllib.request.urlopen(req, timeout=self.run_timeout + 30) as r:
                rows = json.load(r)
        except urllib.error.HTTPError as e:
            raise TrendsError(f"Apify answered HTTP {e.code}: {e.read()[:300].decode(errors='replace')}") from None
        except urllib.error.URLError as e:
            raise TrendsError(f"Could not reach Apify: {e.reason}") from None
        if not isinstance(rows, list):
            raise TrendsError(f"Unexpected answer from Apify: {str(rows)[:300]}")
        return rows

    def interest_over_time_rows(self) -> List[dict]:
        """The raw rows, no pandas needed: one {keyword, date, value, partial, ...} per keyword per date."""
        if not self._input:
            raise TrendsError("call build_payload() first")
        if self._rows is None:
            rows = self._run(self._input)
            self.uncertainty_pct = {r["keyword"]: r.get("uncertaintyPct") for r in rows}
            self.warnings = {r["keyword"]: r["warning"] for r in rows if r.get("warning")}
            self.below_threshold = sorted({r["keyword"] for r in rows if r.get("status") == "below_threshold"})
            self.market_wide_jumps = sorted({r["date"] for r in rows if r.get("marketWideJump")})
            self._rows = rows
        return self._rows

    def interest_over_time(self):
        """A pandas DataFrame like pytrends': a date index, one column per keyword, then isPartial."""
        try:
            import pandas as pd
        except ImportError:
            raise ImportError("interest_over_time() needs pandas (pip install pandas); "
                              "interest_over_time_rows() returns the same data without it") from None
        rows = self.interest_over_time_rows()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows).pivot_table(index="date", columns="keyword", values="value", aggfunc="first")
        df = df.reindex(columns=[k for k in self.kw_list if k in df.columns])
        df.index = pd.to_datetime(df.index)
        df.columns.name = None
        partial = {r["date"]: bool(r.get("partial")) for r in rows}
        df["isPartial"] = [partial[d.strftime("%Y-%m-%d")] for d in df.index]
        return df.sort_index()

    def _not_yet(self, name: str):
        raise NotImplementedError(f"{name}() isn't in google-trends-cloud yet. If you need it, say so in an issue: "
                                  "https://github.com/Gwapspec/google-trends-cloud/issues")

    def interest_by_region(self, *a, **k):
        self._not_yet("interest_by_region")

    def related_queries(self, *a, **k):
        self._not_yet("related_queries")

    def related_topics(self, *a, **k):
        self._not_yet("related_topics")

    def trending_searches(self, *a, **k):
        self._not_yet("trending_searches")

    def suggestions(self, *a, **k):
        self._not_yet("suggestions")
