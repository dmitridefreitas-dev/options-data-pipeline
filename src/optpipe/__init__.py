"""optpipe — a lightweight options-chain ETL.

Modules:
    snapshot   fetch a ticker's full option chain into one tidy frame
    store      append-only, date-partitioned snapshot storage
    features   derived per-snapshot features: ATM IV, term structure,
               skew, expected move — and IV rank across stored history

The pipeline is deliberately boring: fetch, tidy, store, derive. Boring is
the point — the interesting work (surfaces in options-pricing-lib, signals
in honest-backtester) needs data that arrives on schedule in a clean shape.
"""

from optpipe.snapshot import fetch_chain, tidy_chain

__all__ = ["fetch_chain", "tidy_chain"]
