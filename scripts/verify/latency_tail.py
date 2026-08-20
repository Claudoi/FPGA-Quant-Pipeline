#!/usr/bin/env python3
"""Análisis de cola (tail latency) del vector SEC-LAT-01 (fase 3).

Lee verification/vectors/latency/latency_dw32.json y calcula los
percentiles exactos por tipo y total. Evidencia reproducible para
marcas.md y el write-up: p99/p99.9/p99.99/max y jitter (max-min).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "verification/vectors/latency/latency_dw32.json"
NS = 3.103  # ns/ciclo a 322,265625 MHz


def percentile(hist: dict, n: int, q: float) -> int:
    """Valor del percentil q (0..1) sobre el histograma de ciclos."""
    target = q * n
    acc = 0
    for ciclos in sorted(hist):
        acc += hist[ciclos]
        if acc >= target:
            return ciclos
    return max(hist)


def row(tag: str, data: dict) -> dict:
    n = data["n"]
    hist = {int(k): v for k, v in data["hist_ciclos"].items()}
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
        "tipo": tag,
        "n": n,
        "mean_ciclos": round(mean, 3),
        "mean_ns": round(mean * NS, 2),
        "min_ciclos": min_c,
        "p99_ciclos": percentile(hist, n, 0.99),
        "p99_ns": round(percentile(hist, n, 0.99) * NS, 2),
        "p99_9_ciclos": p999,
        "p99_9_ns": round(p999 * NS, 2),
        "p99_99_ciclos": p9999,
        "p99_99_ns": round(p9999 * NS, 2),
        "max_ciclos": max_c,
        "max_ns": round(max_c * NS, 2),
        "jitter_ciclos": max_c - min_c,
        "jitter_ns": round((max_c - min_c) * NS, 2),
    }


def main() -> int:
    data = json.loads(SRC.read_text(encoding="utf-8"))
    tipos = data["por_tipo"]
    rows = [row(t, tipos[t]) for t in ("A", "D", "E", "U", "X")]
    rows.append(row("TOTAL", data["total"]))

    header = ("tipo     n      media    p99     p99.9   p99.99  max     "
              "jitter (ciclos)   [ns]")
    print(header)
    print("-" * len(header))
    for r in rows:
        print(
            f"{r['tipo']:<7} {r['n']:<7} {r['mean_ciclos']:<8} "
            f"{r['p99_ciclos']:<7} {r['p99_9_ciclos']:<7} {r['p99_99_ciclos']:<7} "
            f"{r['max_ciclos']:<7} {r['jitter_ciclos']:<12} "
            f"media {r['mean_ns']} / p99 {r['p99_ns']} / "
            f"p99.9 {r['p99_9_ns']} / p99.99 {r['p99_99_ns']} / "
            f"max {r['max_ns']} / jitter {r['jitter_ns']}")
    print()
    print("percentil mas alla del max del histograma: "
          f"p99.99_total={rows[-1]['p99_99_ciclos']} ciclos "
          f"({rows[-1]['p99_99_ns']} ns); max={rows[-1]['max_ciclos']} "
          f"({rows[-1]['max_ns']} ns)")
    return 0


if __name__ == "__main__":
    sys.exit(main())