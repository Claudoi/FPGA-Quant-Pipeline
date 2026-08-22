#!/usr/bin/env python3
"""Tail-latency analysis of the SEC-LAT-01 vector (phase 3).

Reads verification/vectors/latency/latency_dw32.json and computes exact
percentiles per type and total. Reproducible evidence for marks.md and the
write-up: p99/p99.9/p99.99/max and jitter (max-min).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "verification/vectors/latency/latency_dw32.json"
NS = 3.103  # ns/cycle at 322,265625 MHz


def percentile(hist: dict, n: int, q: float) -> int:
    """Percentile value q (0..1) over the cycle histogram."""
    target = q * n
    acc = 0
    for cycles in sorted(hist):
        acc += hist[cycles]
        if acc >= target:
            return cycles
    return max(hist)


def row(tag: str, data: dict) -> dict:
    n = data["n"]
    hist = {int(k): v for k, v in data["hist_cycles"].items()}
    max_c = max(hist)
    min_c = min(hist)
    acc = 0
    mean = 0.0
    for c in sorted(hist):
        acc += hist[c]
        mean += c * hist[c]
    mean /= n
    p999 = percentile(hist, n, 0.999)
    p9999 = percentile(hist, n, 0.9999)
    return {
        "type": tag,
        "n": n,
        "mean_cycles": round(mean, 3),
        "mean_ns": round(mean * NS, 2),
        "min_cycles": min_c,
        "p99_cycles": percentile(hist, n, 0.99),
        "p99_ns": round(percentile(hist, n, 0.99) * NS, 2),
        "p99_9_cycles": p999,
        "p99_9_ns": round(p999 * NS, 2),
        "p99_99_cycles": p9999,
        "p99_99_ns": round(p9999 * NS, 2),
        "max_cycles": max_c,
        "max_ns": round(max_c * NS, 2),
        "jitter_cycles": max_c - min_c,
        "jitter_ns": round((max_c - min_c) * NS, 2),
    }


def main() -> int:
    data = json.loads(SRC.read_text(encoding="utf-8"))
    types = data["by_type"]
    rows = [row(t, types[t]) for t in ("A", "D", "E", "U", "X")]
    rows.append(row("TOTAL", data["total"]))

    header = ("type     n      mean     p99     p99.9   p99.99  max     "
              "jitter (cycles)   [ns]")
    print(header)
    print("-" * len(header))
    for r in rows:
        print(
            f"{r['type']:<7} {r['n']:<7} {r['mean_cycles']:<8} "
            f"{r['p99_cycles']:<7} {r['p99_9_cycles']:<7} {r['p99_99_cycles']:<7} "
            f"{r['max_cycles']:<7} {r['jitter_cycles']:<12} "
            f"mean {r['mean_ns']} / p99 {r['p99_ns']} / "
            f"p99.9 {r['p99_9_ns']} / p99.99 {r['p99_99_ns']} / "
            f"max {r['max_ns']} / jitter {r['jitter_ns']}")
    print()
    print("percentile beyond the histogram max: "
          f"p99.99_total={rows[-1]['p99_99_cycles']} cycles "
          f"({rows[-1]['p99_99_ns']} ns); max={rows[-1]['max_cycles']} "
          f"({rows[-1]['max_ns']} ns)")
    return 0


if __name__ == "__main__":
    sys.exit(main())