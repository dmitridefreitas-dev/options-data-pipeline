# Code walkthrough — how every module actually works

Companion to `how-it-works.md` (concepts). This is the code-level defense.

## Map

| File | Role | Key entry points |
|---|---|---|
| `snapshot.py` | fetch + normalise chains | `fetch_chain`, `tidy_chain`, `COLUMNS` |
| `store.py` | append-only partitioned storage | `save_snapshot`, `load_history`, `list_snapshots` |
| `features.py` | derived research features | `snapshot_features`, `atm_iv`, `term_slope`, `skew`, `expected_move`, `iv_rank` |
| `__main__.py` | scheduled CLI | `optpipe snapshot / features / list` |

## `snapshot.py` — fetch and tidy

### `tidy_chain` (pure function — all data hygiene lives here, once)

Input: raw yfinance calls/puts frames + (ticker, spot, expiry, snapshot_date).
Output: rows in the fixed `COLUMNS` schema. The rules, each one a test:

- **Mid only when both sides are live**: `mid = (bid+ask)/2 where (bid>0) & (ask>0)`,
  else NaN. A one-sided quote must never fabricate a price — half of a dead bid is
  not a value.
- **Priceless contracts dropped at the door**: no mid *and* no positive last trade →
  the row never enters the store. Garbage kept "just in case" becomes someone's
  silent NaN bug six months later.
- **Derived at ingestion**: `dte = (expiry − snapshot_date).days`,
  `moneyness = strike/spot` — computed once, consistently, instead of re-derived
  (differently) by every consumer.
- Output is sorted (type, strike) and column-ordered by `COLUMNS`, so files diff
  cleanly across days.

### `fetch_chain` — target-DTE expiry selection

The bug this design fixes (hit live on the first real run): SPY/QQQ now list
**daily** expirations, so "first 8 expiries" spans two weeks and `term_slope`
came back NaN — there was no 90-day point to measure. The fix:

```python
dtes   = pd.Series({e: (Timestamp(e) - snapshot_ts).days for e in expiries})
chosen = sorted({(dtes - target).abs().idxmin() for target in target_dtes})
```

For each target (7, 14, 21, 30, 45, 60, 90, 120 days), take the *nearest listed*
expiry; the set-comprehension dedupes when two targets resolve to the same expiry.
Snapshots stay compact (~8 expiries) while spanning the whole curve. Spot and
snapshot date come from the last daily bar of a 5-day history call — so a Saturday
run correctly stamps Friday's (or Thursday's, around holidays) trading date.

## `store.py` — append-only, and why it raises

Layout `<root>/<YYYY-MM-DD>/<TICKER>.csv` — date-partitioned so "everything from
day X" is one directory listing and per-ticker history is a glob
(`*/TICKER.csv`, lexicographically date-sorted for free).

`save_snapshot` refuses: empty frames; frames mixing tickers or dates (one file =
one fact); and **existing paths**, unless `overwrite=True` is passed explicitly.
The design position to defend: snapshots are facts about a moment, and a research
store that can silently rewrite its past contaminates every study built on it —
the same instinct as honest-backtester refusing same-bar fills. The weekend/holiday
scheduled run demonstrates it: fetch resolves to the last trading day, that file
exists, the CLI logs `FAILED — append-only` and exits 1. Correct behaviour, loudly.

`_read` re-validates the schema on the way back in (a hand-edited or truncated CSV
fails at load, not three functions later).

## `features.py` — pure frame-in, number-out

- `atm_iv`: filter to expiry, drop NaN IVs, find min |strike − spot|, average the
  call and put at that strike (averaging cancels one-sided staleness).
- `term_structure`: `atm_iv` + dte per expiry, ascending — the curve as a frame.
- `term_slope`: nearest-to-30d and nearest-to-90d rows via `(dte − target).abs()
  .argmin()`; **NaN if both targets resolve to the same expiry** (that guard is what
  turned the daily-expiration bug into a visible NaN instead of a fake zero).
  Positive slope = normal; inverted = near-dated protection bid (stress).
- `skew`: put leg nearest 0.95 moneyness minus call leg nearest 1.05 —
  OTM-put-over-OTM-call, the equity-market norm, in vol points.
- `expected_move`: ATM call mid + ATM put mid over spot — with a same-strike guard
  (if the nearest-to-spot call and put strikes differ, return NaN rather than a
  Frankenstein straddle).
- `iv_rank`: `(current − min) / (max − min)` over stored history, clipped to [0,1];
  NaN with fewer than 2 observations; 0.5 for a constant history. **Needs history
  by design** — any substitute for waiting is lookahead in disguise.
- `snapshot_features`: the one-row hand-off — spot, 30d ATM IV, term slope, 30d
  skew, 30d expected move — i.e. the columns a downstream signal (IV-rank mean
  reversion in honest-backtester) would consume.

## `__main__.py` — the scheduled entry point

Three subcommands. `snapshot` loops tickers with a per-ticker try/except — one bad
ticker prints `FAILED - <reason>` to stderr and the rest still run (a scheduled job
must not die on the first hiccup), exit code 1 if anything failed. `features` loads
a ticker's full stored history, computes today's row, then builds the ATM-IV series
across stored dates to feed `iv_rank`. `list` prints the (date, ticker, contracts)
inventory. Deployed as Windows scheduled task `optpipe-daily-snapshot` (weekdays
5 PM local, output appended to `data/snapshot.log`, catch-up on wake).

## The tests, as a defense layer

All 21 tests run offline. The fixture (`conftest.build_chain`) constructs a chain
with a **linear smile** — `iv = base + slope·(1 − moneyness)` — chosen so every
feature has a hand-computable answer: ATM IV = base exactly (the smile term
vanishes at moneyness 1), 95/105 skew = slope × 0.10 exactly, expected move =
straddle/spot exactly. Tidy tests cover the mid rule, the one-sided-quote case, and
priceless-row dropping with canned raw frames shaped like yfinance output. Store
tests cover the round trip, the append-only refusal (and explicit overwrite), multi-
date history assembly, mixed-ticker rejection. The live path was verified once by
running the real CLI — that run produced the committed `data/sample/` snapshots.

## Grilling Q&A (implementation level)

- *Why is `tidy_chain` separated from `fetch_chain`?* Purity = testability: the
  network wrapper is 20 lines that can only be integration-tested; every rule that
  could corrupt data lives in the pure function with offline tests.
- *IV rank vs IV percentile?* Rank = position in the min-max *range* (this
  implementation, the classic "IV rank"); percentile = fraction of days below
  current. Rank is sensitive to a single spike compressing the scale; percentile is
  robust. Knowing the distinction — and that this repo implements rank — is exactly
  the kind of detail that stops a grilling.
- *Why not use yfinance's IVs to build a surface directly?* They're a vendor
  solver's output on delayed quotes — fine for level/slope/rank features, but the
  named next step is inverting stored *mids* through options-pricing-lib's solver so
  the IVs are self-computed and auditable.
- *Why CSV over parquet?* Hundreds of KB per ticker-day: greppable, diffable,
  dependency-free beats compressed-and-fast at this scale. `load_history` hides the
  format, so parquet later is a two-line change (named in the README).
- *What breaks when a ticker has no listed options?* `fetch_chain` raises
  "no option expiries"; the CLI catches it per-ticker, logs FAILED, moves on, exits
  nonzero so the scheduler records the failure.
