# google-trends-cloud

**Google Trends without `429 Too Many Requests`:** a drop-in for pytrends' `TrendReq` that runs in the cloud.

**The problem:**
- [pytrends](https://github.com/GeneralMills/pytrends) calls Google directly. On servers, notebooks and
  scheduled jobs it often fails with `TooManyRequestsError` / HTTP 429.
- Its repository is archived (read-only), and its issues include dozens of 429 reports with no fix coming.
- pytrends takes at most 5 keywords per request, and each request is scaled 0-100 on its own, so numbers
  from two requests can't be compared.

**This client** sends the request to a hosted tool instead:
- The [Google Trends one-scale tool](https://apify.com/honestdata/google-trends-one-scale) on Apify
  handles the proxies and retries. You don't need a proxy account.
- **Up to 200 keywords per request, all on one 0-100 scale.** It chains overlapping requests through a
  shared keyword, so big and small terms are comparable.
- Each keyword gets an **error bar**, and dates where Google's data jumped across the board are flagged.

```bash
pip install "google-trends-cloud[pandas] @ git+https://github.com/Gwapspec/google-trends-cloud"
export APIFY_TOKEN=...   # free account: console.apify.com > Settings > API & Integrations
```

## Coming from pytrends

```python
# before
from pytrends.request import TrendReq

# after: the same calls
from google_trends_cloud import TrendReq

pytrends = TrendReq(hl="en-US", tz=360)
pytrends.build_payload(["python", "rust", "golang", "zig", "elixir", "haskell", "ocaml"],
                       timeframe="today 12-m", geo="US")
df = pytrends.interest_over_time()   # date index, one column per keyword, then isPartial
```

A real run (US, 12 months, 2026-10-30). Seven keywords in one request, all on one scale:

```
            python  rust  golang    zig  elixir  haskell  ocaml  isPartial
date
2026-10-11    39.0  25.0   2.022  2.022     5.0    1.643  0.087      False
2026-10-18    35.0  23.0   0.632  2.022     5.0    1.769  0.130      False
2026-10-25    35.0  23.0   0.758  2.022     5.0    1.643  0.130       True
```

Values are decimals, so small terms don't collapse to 0 or "<1" as they do in pytrends.

## What you get besides the numbers

```python
pytrends.uncertainty_pct     # {'python': 0.14, 'rust': 0.18, ..., 'ocaml': 1.17}  error bar (±1σ) on each level, in %
pytrends.market_wide_jumps   # ['2026-03-29', '2026-04-05', ...]  dates where Google's data jumped for everyone
pytrends.warnings            # {'python': "Peak falls inside a market-wide jump in Google's data.", ...}
pytrends.below_threshold     # keywords Google has too little data for (all zeros, and free)
rows = pytrends.interest_over_time_rows()   # the same data as plain dicts, no pandas needed
```

**Why the jump flags matter:** from late March to late June 2026, small US search terms rose together by
up to 2x and then fell back, while big terms stayed flat. A "trending" keyword whose peak sits in that
window may not be trending at all.
[The data and method](https://gwapspec.github.io/honest-data/) are public.

## Supported

| pytrends | Here |
|---|---|
| `build_payload(kw_list, cat, timeframe, geo, gprop)` | Yes. Up to 200 keywords. |
| `timeframe` | `now 7-d`, `today 1-m`, `today 3-m`, `today 12-m`, `today 5-y`, `all`, or `"YYYY-MM-DD YYYY-MM-DD"`. Hourly ranges aren't available. |
| `gprop` | `""`, `images`, `news`, `froogle`, `youtube` |
| `interest_over_time()` | Yes |
| `interest_by_region()`, `related_queries()`, `related_topics()`, `trending_searches()`, `suggestions()` | Not yet. Raises `NotImplementedError`. [Ask in an issue](https://github.com/Gwapspec/google-trends-cloud/issues) if you need one. |

`TrendReq` accepts pytrends' `retries`, `backoff_factor`, `proxies` and `requests_args`, so your code runs
unchanged. Retries and proxies happen in the cloud, so it ignores them.

## Cost

- **$0.005 per keyword** on Apify's free-plan pricing, less on paid plans. One `interest_over_time()`
  call bills each keyword once, whatever the time range.
- **Keywords Google has too little data for are free.**
- **Apify's free plan** includes a monthly usage credit. At this price it covers roughly 1,000 keywords
  a month.
- **Speed:** each call starts a cloud run. Seven keywords over 12 months took 84 seconds; a few keywords
  over 3 months take under 30. The result is cached on the object until the next `build_payload`.

## Errors

| Error | When |
|---|---|
| `TrendsError` | Missing or wrong token, a timeout, or an error from Apify |
| `ValueError` | An option the tool doesn't support (listed above) |

## Notes

- This is an independent project. It isn't affiliated with Google or pytrends.
- **Disclosure:** made by Honest Data, which sells the hosted tool this client calls. The client is free
  and MIT-licensed.

Tests: `python3 -m unittest discover -s tests` (offline).

Questions or bugs: [open an issue](https://github.com/Gwapspec/google-trends-cloud/issues).
