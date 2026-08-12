#!/usr/bin/env python3
"""fetch_itch.py — descarga feeds ITCH de emi.nasdaq.com con verificación md5.

Los crudos NUNCA se commitean: van a data/itch_sample/ (gitignored).
La descarga escribe a <fichero>.part y solo lo renombra a su nombre final si
el md5 cuadra con el publicado por Nasdaq (<fichero>.md5sum). md5 incorrecto
= aborta y no queda fichero aparentemente válido (spec fase0, SEC-07).

Uso:
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
    """El md5 del fichero descargado no coincide con el publicado."""


class Md5NotAvailableError(RuntimeError):
    """El servidor no sirve el .md5sum (fail closed salvo --no-md5-verify)."""


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
    """Descarga filename (+ su .md5sum) verificado; devuelve la ruta final.

    Fail closed: si el servidor no sirve el .md5sum, aborta con
    Md5NotAvailableError salvo allow_no_md5 (entonces avisa con warning).
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
                f"{filename}: el servidor no sirve .md5sum; "
                f"sin verificacion md5 no se descarga (fail closed). "
                f"Usa --no-md5-verify para forzar."
            )
        esperado = None
        warnings.warn(
            f"{filename}: descargando SIN verificacion md5 "
            f"(endpoint .md5sum no disponible)",
            UserWarning,
        )
    try:
        with opener(base_url + filename) as r, open(part, "wb") as f:
            shutil.copyfileobj(r, f)
        if esperado is not None:
            obtenido = _md5_of(part)
            if obtenido != esperado:
                raise Md5MismatchError(
                    f"{filename}: md5 {obtenido} != publicado {esperado}"
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
                    help="descarga aunque el servidor no sirva .md5sum (avisa)")
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
