#!/usr/bin/env python3
"""select_subset.py — picks the symbol subset for the vectors.

Rule (spec phase 0, Constraints): top N by peak live orders of the main day,
tie-broken by messages. The stats table that justifies it is pasted into the
verify-report (criterion 9).

Usage:
    python3 -m golden_model.scripts.select_subset <stats.csv> \
        [--n 20] [--day 2019-12-30] [--out verification/vectors/subset_symbols.json]
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from os import PathLike
from pathlib import Path


def select(
    stats_csv: str | PathLike[str],
    out_json: str | PathLike[str],
    *,
    n: int = 20,
    day: str | None = None,
) -> dict:
    with open(stats_csv, newline="") as f:
        filas = [
            {
                "locate": int(r["locate"]),
                "symbol": r["symbol"],
                "messages": int(r["messages"]),
                "peak_orders": int(r["peak_orders"]),
                "peak_levels": int(r["peak_levels"]),
            }
            for r in csv.DictReader(f)
        ]
    filas.sort(key=lambda r: (-r["peak_orders"], -r["messages"]))
    elegidos = filas[:n]
    data = {
        "day": day,
        "metric": "peak_live_orders",
        "n": len(elegidos),
        "source": str(stats_csv),
        "symbols": elegidos,
    }
    Path(out_json).write_text(json.dumps(data, indent=2) + "\n")
    return data


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("stats_csv")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--day", default=None)
    ap.add_argument("--out", default="verification/vectors/subset_symbols.json")
    args = ap.parse_args(argv)
    data = select(args.stats_csv, args.out, n=args.n, day=args.day)
    print(f"subset of {data['n']} symbols -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())