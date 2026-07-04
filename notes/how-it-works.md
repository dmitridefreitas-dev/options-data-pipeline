# How this project works — study notes

Plain-English walkthrough. Read alongside `notebooks/demo.ipynb`.

## What this project is

The infrastructure repo: a small ETL that snapshots option chains on a schedule,
stores them append-only, and derives the handful of features options research
actually consumes. It is deliberately the least glamorous repo in the portfolio —
and the one that makes two of the others' "next steps" possible: the IV-rank
mean-reversion study honest-backtester deferred (no historical IV data existed), and
real-market smiles for options-pricing-lib's surface tools.

## The pipeline, stage by stage

1. **Fetch** (`snapshot.fetch_chain`): pulls expiries from yfinance — but selected by
   *target days-to-expiry* (7, 14, 21, 30, 45, 60, 90, 120), not "first N". Reason,
   learned live: SPY/QQQ now list daily expirations, so the first 8 expiries span two
   weeks and contain no term structure at all. The first real run returned
   `term_slope = NaN` and this selection rule is the fix.
2. **Tidy** (`snapshot.tidy_chain`): pure function from raw yfinance frames to one
   fixed schema, one row per contract. Data hygiene happens here, once: mid =
   (bid+ask)/2 only when *both* sides are live (a one-sided quote never fabricates a
   price), contracts with no quote and no last trade are dropped, moneyness and DTE
   computed at ingestion. Pure function = testable offline with canned frames.
3. **Store** (`store`): `data/snapshots/<date>/<TICKER>.csv`, append-only.
   Re-saving an existing (date, ticker) raises `FileExistsError` unless
   `overwrite=True` is passed explicitly. Rationale: snapshots are historical facts;
   research built on a store that can silently rewrite its past inherits that
   untrustworthiness. Same instinct as honest-backtester's refusal of same-bar fills.
4. **Derive** (`features`): pure functions over the tidy frame —
   - `atm_iv`: IV at the strike nearest spot, call/put averaged.
   - `term_structure` / `term_slope`: ATM IV per expiry; slope = (~90d) − (~30d).
     Positive is normal; inversion (near vol over far) is the stress signature.
   - `skew`: put IV at 0.95 moneyness minus call IV at 1.05. Positive is the equity
     norm — crash protection costs more vol than upside.
   - `expected_move`: ATM straddle mid / spot — the market's priced move to expiry.
   - `iv_rank`: where today's IV sits in its own stored history, 0–1. Returns NaN
     without history — honestly, because any substitute is lookahead.

## What the first real snapshot showed (2026-07-02)

QQQ trading at nearly double SPY's implied vol (26% vs 14%), QQQ's term structure
mildly inverted while SPY's slopes normally, both with 5–6 points of put skew, and
30-day expected moves of 5.7% vs 3.1%. One tidy frame and four pure functions turn a
5,600-row chain dump into that sentence — which is the entire point of the repo.

## Testing philosophy

No test touches the network. The fixture (`tests/conftest.py`) constructs a synthetic
chain with a *linear* smile — iv = base + slope × (1 − moneyness) — so every feature
has a hand-computable answer: ATM IV is exactly the base, 95/105 skew is exactly
slope × 0.10, expected move is exactly straddle/spot. The storage tests cover the
round trip, the append-only refusal, multi-date history assembly, and schema
validation on read. The live path was verified once by running the real CLI (that run
produced the committed sample data), and its failure mode is graceful: one bad ticker
prints an error and doesn't kill the scheduled run for the others.

## Likely interview questions

- *Why store raw chains rather than just the features?* Features are opinions; raw
  contracts are facts. New features (a different skew definition, delta-bucketed
  surfaces) can be recomputed over stored history — but only if the raw rows exist.
- *Why is IV rank the options trader's normalisation?* Because vol levels aren't
  comparable across names or eras: 26% is unremarkable for QQQ and would be a crisis
  for SPY. Rank ("where is IV versus its own past year") makes 'rich' and 'cheap'
  meaningful, which is why IV-rank mean reversion is the canonical premium-selling
  filter — and why it needs exactly the history this pipeline accumulates.
- *What's wrong with this data?* It's delayed, indicative retail data: no NBBO
  timestamps, stale ITM quotes (visible as the wing divergence in the smile plot),
  and yfinance's IV is their solver's output, not the exchange's. Fine for
  daily-frequency features; wrong for anything microstructure.
- *Why CSV and not parquet/a database?* At a few hundred KB per ticker-day, CSV is
  greppable, diffable, and dependency-free; the store interface (`load_history`)
  hides the format, so switching to parquet later is a two-line change. Boring
  choices where boring is affordable.
