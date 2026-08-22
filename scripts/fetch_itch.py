#!/usr/bin/env python3
"""fetch_itch.py — downloads ITCH feeds from emi.nasdaq.com with md5 verification.

The raw files are NEVER committed: they go to data/itch_sample/ (gitignored).
The download writes to <file>.part and only renames it to its final name if
the md5 matches the one published by Nasdaq (<file>.md5sum). Wrong md5
= aborts and no apparently-valid file remains (spec phase 0, SEC-07).

Usage:
    python3 scripts/fetch_itch.py 12302019.NASDAQ_ITCH50.gz [--dest data/itch_sample]
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import urllib.request
import warnings
from pathlib import Path
from typing import Callable, BinaryIO

BASE_URL = "https://emi.nasdaq.com/ITCH/Nasdaq%20ITCH/"


class Md5MismatchError(RuntimeError):
    """The md5 of the downloaded file does not match the published one."""


class Md5NotAvailableError(RuntimeError):
    """The server does not serve the .md5sum (fail closed except --no-md5-verify)."""


def _md5_of(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(
    filename: str,
    dest_dir: str | Path,
    *,
    base_url: str = BASE_URL,
    opener: Callable[..., BinaryIO] = urllib.request.urlopen,
    allow_no_md5: bool = False,
) -> Path:
    """Downloads filename (+ its .md5sum) verified; returns the final path.

    Fail closed: if the server does not serve the .md5sum, aborts with
    Md5NotAvailableError except allow_no_md5 (then warns).
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    final = dest_dir / filename
    part = dest_dir / (filename + ".part")
    try:
        with opener(base_url + filename + ".md5sum") as r:
            esperado: str | None = r.read().decode().split()[0]
    except Exception:
        if not allow_no_md5:
            raise Md5NotAvailableError(
                f"{filename}: the server does not serve .md5sum; "
                f"without md5 verification no download (fail closed). "
                f"Use --no-md5-verify to force."
            )
        esperado = None
        warnings.warn(
            f"{filename}: downloading WITHOUT md5 verification "
            f"(.md5sum endpoint unavailable)",
            UserWarning,
        )
    try:
        with opener(base_url + filename) as r, open(part, "wb") as f:
            shutil.copyfileobj(r, f)
        if esperado is not None:
            obtenido = _md5_of(part)
            if obtenido != esperado:
                raise Md5MismatchError(
                    f"{filename}: md5 {obtenido} != published {esperado}"
                )
        part.rename(final)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    return final


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("filename")
    ap.add_argument("--dest", default="data/itch_sample")
    ap.add_argument("--no-md5-verify", action="store_true",
                    help="download even if the server does not serve .md5sum (warns)")
    args = ap.parse_args(argv)
    try:
        final = fetch(args.filename, args.dest,
                      allow_no_md5=args.no_md5_verify)
    except (Md5MismatchError, Md5NotAvailableError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    print(final)
    return 0


if __name__ == "__main__":
    sys.exit(main())