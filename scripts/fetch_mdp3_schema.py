#!/usr/bin/env python3
"""fetch_mdp3_schema.py — downloads the official CME SBE schema (fail closed with md5).

The MDP 3.0 schema (templates_FixBinary_v12.xml, 2021-03-10) is the SINGLE
SOURCE of offsets/blockLength/types of the golden model (spec phase 4, "no
hand-written literal" rule). It is not market data, but it is kept out of the
repo all the same (data/mdp3/, gitignored, rule G0).

cmegroup.com answers 403 to non-browser clients, so the script first tries the
official FTP over HTTPS and, if it cannot, falls back to the official archive
on Wayback Machine. In both cases the md5 is checked against a pin inside the
script itself (fail closed): wrong md5 = aborts and leaves no valid file.

Usage:
    python3 scripts/fetch_mdp3_schema.py [--dest data/mdp3] [--force]
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

# Schema pinned: templates_FixBinary_v12.xml, version 12, id=1, 2021-03-10.
# md5 of the file as served by CME (verified against the Wayback snapshot).
SCHEMA_VERSION = "12"
FILENAME = f"templates_FixBinary_v{SCHEMA_VERSION}.xml"
EXPECTED_MD5 = "e6eb6c60b46e61dc154537879b3d18d2"

# Sources: CME official FTP (preferred) and fallback to the official archive
# via Wayback Machine (same content, verified hash).
CME_URL = (
    "https://www.cmegroup.com/ftp/SBEFix/NRCert/Templates/"
    + FILENAME
)
WAYBACK_URL = (
    "https://web.archive.org/web/20220810180226id_/"
    "https://www.cmegroup.com/ftp/SBEFix/NRCert/Templates/"
    + FILENAME
)


class Md5MismatchError(RuntimeError):
    """The md5 of the downloaded file does not match the script's pin."""


class SchemaUnavailableError(RuntimeError):
    """No source responded with the expected file."""


def _md5_of(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(url: str, dest: Path) -> bool:
    """Downloads url to dest. Returns True if the file has the expected md5."""
    part = dest.with_suffix(dest.suffix + ".part")
    try:
        with urllib.request.urlopen(url, timeout=60) as r, open(part, "wb") as f:
            f.write(r.read())
        if _md5_of(part) != EXPECTED_MD5:
            part.unlink(missing_ok=True)
            return False
        part.rename(dest)
        return True
    except Exception:
        part.unlink(missing_ok=True)
        return False


def fetch(dest_dir: str | Path) -> Path:
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    final = dest_dir / FILENAME
    if final.exists() and _md5_of(final) == EXPECTED_MD5:
        return final
    for url in (CME_URL, WAYBACK_URL):
        if _download(url, final):
            return final
    raise SchemaUnavailableError(
        f"{FILENAME}: no source served the file with md5 "
        f"{EXPECTED_MD5} (CME and Wayback unavailable)."
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dest", default="data/mdp3")
    args = ap.parse_args(argv)
    try:
        final = fetch(args.dest)
    except (Md5MismatchError, SchemaUnavailableError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    print(final)
    return 0


if __name__ == "__main__":
    sys.exit(main())