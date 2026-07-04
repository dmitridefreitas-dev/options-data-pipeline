"""CLI: `optpipe snapshot --tickers SPY,QQQ` / `optpipe features --ticker SPY`.

Designed to be run on a schedule. Windows Task Scheduler:
    schtasks /Create /SC DAILY /ST 16:45 /TN optpipe ^
        /TR "C:\\Python314\\Scripts\\optpipe.exe snapshot --tickers SPY,QQQ"
cron:
    45 16 * * 1-5 optpipe snapshot --tickers SPY,QQQ
"""

from __future__ import annotations

import argparse
import sys

from optpipe import features, snapshot, store


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="optpipe")
    sub = parser.add_subparsers(dest="command", required=True)

    snap = sub.add_parser("snapshot", help="fetch and store option chains")
    snap.add_argument("--tickers", required=True, help="comma-separated, e.g. SPY,QQQ")
    snap.add_argument("--root", default="data/snapshots")
    snap.add_argument("--dtes", default="7,14,21,30,45,60,90,120",
                      help="target days-to-expiry, comma-separated")

    feat = sub.add_parser("features", help="print features from the latest stored snapshot")
    feat.add_argument("--ticker", required=True)
    feat.add_argument("--root", default="data/snapshots")

    inv = sub.add_parser("list", help="inventory of stored snapshots")
    inv.add_argument("--root", default="data/snapshots")

    args = parser.parse_args(argv)

    if args.command == "snapshot":
        failures = 0
        target_dtes = tuple(int(d) for d in args.dtes.split(","))
        for ticker in [t.strip().upper() for t in args.tickers.split(",") if t.strip()]:
            try:
                chain = snapshot.fetch_chain(ticker, target_dtes=target_dtes)
                path = store.save_snapshot(chain, root=args.root)
                print(f"{ticker}: {len(chain)} contracts across "
                      f"{chain['expiry'].nunique()} expiries -> {path}")
            except Exception as error:  # one bad ticker must not kill the schedule
                failures += 1
                print(f"{ticker}: FAILED - {error}", file=sys.stderr)
        return 1 if failures else 0

    if args.command == "features":
        history = store.load_history(args.ticker, root=args.root)
        latest_date = history["snapshot_date"].max()
        latest = history[history["snapshot_date"] == latest_date]
        summary = features.snapshot_features(latest)

        by_date = history.groupby("snapshot_date", group_keys=False).apply(
            lambda day: features.snapshot_features(day)["atm_iv_30d"],
            include_groups=False,
        )
        summary["iv_rank"] = features.iv_rank(summary["atm_iv_30d"], by_date.to_numpy())
        print(f"{args.ticker} @ {latest_date.date()} "
              f"({by_date.notna().sum()} snapshots in history)")
        for key, value in summary.items():
            print(f"  {key:18s} {value:.4f}")
        return 0

    if args.command == "list":
        inventory = store.list_snapshots(root=args.root)
        print(inventory.to_string(index=False) if len(inventory) else "no snapshots yet")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
