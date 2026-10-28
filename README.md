# mics-deep-analysis
## Stock cycle: how the reading is kept reliable

The cycle page leads with a status, not a bare phase. The phase comes from one rule
(a move of the stock's own threshold from its last high or low), the threshold is set
from the last five years of volatility, and the status adds whether the price is moving
with the phase or against it ("correcting", "rebounding"), judged by how much of the
threshold has been given back and by the 200-day trend. Each listing is compared with its
own market index for market-wide falls (`cycle.benchmark_for`). The price series is
checked for unrecorded splits, frozen prices, gaps, stale data and short history, and
every page shows a High, Medium or Low confidence with the reasons.

- `python -m pytest tests` checks the promises the page makes, including that confirmed
  turning points never move when new prices arrive. It runs on every push.
- `python calibrate.py` runs the rule across a mixed universe at several threshold
  multiples and summarises cycles per decade, whipsaws, captured return and how often the
  trend disagrees. Run it before changing `THRESHOLD_MULT` or the cap in `cycle.py`.
