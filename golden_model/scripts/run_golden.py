#!/usr/bin/env python3
"""run_golden.py — CLI del golden model: BinaryFILE -> vectores + stats.

Pipeline: parser -> book -> (VectorSink si hay subset) + StatsCollector,
con invariantes activas todo el run y chequeo profundo periódico y al cierre
(spec fase0, criterios 3 y 6).

Uso:
    python3 -m golden_model.scripts.run_golden <BinaryFILE[.gz]> \
        [--subset subset_symbols.json] [--out DIR] [--text] [--max-messages N]
"""
from __future__ import annotations

import argparse
import json
import sys
from os import PathLike
from pathlib import Path

from ..itch.parser import iter_messages
from ..src.book import Book
from ..src.stats import StatsCollector
from ..src.vectors import VectorSink, dump_text

DEEP_CHECK_EVERY = 1_000_000


def run(
    source: str | PathLike[str],
    subset_path: str | PathLike[str] | None,
    out_dir: str | PathLike[str],
    *,
    text: bool = False,
    deep_check_every: int = DEEP_CHECK_EVERY,
    max_messages: int | None = None,
    strict: bool = False,
) -> dict:
    """Ejecuta el pipeline completo; devuelve el resumen del run."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    book = Book(strict_cross=strict)
    stats = StatsCollector()
    sink = None
    vec_file = None
    vec_path = out_dir / "vectors.bin"
    if subset_path is not None:
        subset = {s["locate"] for s in json.loads(Path(subset_path).read_text())["symbols"]}
        vec_file = open(vec_path, "wb")
        sink = VectorSink(vec_file, subset)
    messages = 0
    try:
        for msg in iter_messages(source):
            event = book.apply(msg)
            stats.observe(msg, book)
            if sink is not None:
                sink.handle(msg, event)
            messages += 1
            if messages % deep_check_every == 0:
                book.check_deep()
            if max_messages is not None and messages >= max_messages:
                break
        book.check_deep()
    finally:
        if vec_file is not None:
            vec_file.close()
    if text and subset_path is not None:
        with open(out_dir / "vectors.txt", "w") as f:
            dump_text(vec_path, f)
    stats.write_csv(out_dir / "stats.csv")
    return {
        "messages": messages,
        "by_type": dict(stats.by_type),
        "symbols": len(stats.symbols),
        "anomalies": book.anomalies,
        "cross_events": book.cross_events,
        "records": sink.records if sink is not None else 0,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("src", help="BinaryFILE de entrada (acepta .gz)")
    ap.add_argument("--subset", default=None, help="subset_symbols.json (sin subset: solo stats)")
    ap.add_argument("--out", default="data/itch_sample/out")
    ap.add_argument("--text", action="store_true", help="vuelca tambien vectors.txt")
    ap.add_argument("--max-messages", type=int, default=None)
    ap.add_argument("--strict", action="store_true",
                    help="aborta ante libro cruzado en trading continuo (defecto: lo cuenta)")
    args = ap.parse_args(argv)
    summary = run(args.src, args.subset, args.out, text=args.text,
                  max_messages=args.max_messages, strict=args.strict)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
