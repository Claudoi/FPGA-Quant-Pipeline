#!/usr/bin/env python3
"""fetch_mdp3_schema.py — descarga el schema SBE oficial de CME (fail closed con md5).

El schema de MDP 3.0 (templates_FixBinary_v12.xml, 2021-03-10) es la FUENTE
ÚNICA de offsets/blockLength/tipos del golden model (spec fase4, regla
"ningun literal a mano"). No es dato de mercado, pero se mantiene fuera del
repo igualmente (data/mdp3/, gitignored, regla G0).

cmegroup.com responde 403 a clientes que no sean navegador, asi que el script
prueba primero el FTP oficial via HTTPS y, si no puede, cae al archivo oficial
en Wayback Machine. En ambos casos el md5 se comprueba contra un pin del
propio script (fail closed): md5 incorrecto = aborta y no deja fichero valido.

Uso:
    python3 scripts/fetch_mdp3_schema.py [--dest data/mdp3] [--force]
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

# Schema pinned: templates_FixBinary_v12.xml, version 12, id=1, 2021-03-10.
# md5 del fichero tal como lo sirve CME (verificado contra la snapshot de Wayback).
SCHEMA_VERSION = "12"
FILENAME = f"templates_FixBinary_v{SCHEMA_VERSION}.xml"
EXPECTED_MD5 = "e6eb6c60b46e61dc154537879b3d18d2"

# Fuentes: FTP oficial de CME (preferida) y fallback al archivo oficial via
# Wayback Machine (mismo contenido, hash verificado).
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
    """El md5 del fichero descargado no coincide con el pin del script."""


class SchemaUnavailableError(RuntimeError):
    """Ninguna fuente respondio con el fichero esperado."""


def _md5_of(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(url: str, dest: Path) -> bool:
    """Descarga url a dest. Devuelve True si el fichero tiene el md5 esperado."""
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
        f"{FILENAME}: ninguna fuente sirvio el fichero con md5 "
        f"{EXPECTED_MD5} (CME y Wayback no disponibles)."
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