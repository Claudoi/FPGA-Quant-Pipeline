"""Mirror tests of specs/fase0-golden-model/gherkin/datos.feature."""
from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from golden_model.scripts.run_golden import run
from golden_model.scripts.select_subset import select
from golden_model.tests.test_parser import binaryfile, p_a, p_r, p_s, p_x
from scripts.fetch_itch import Md5MismatchError, Md5NotAvailableError, fetch


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def fake_opener(mapa: dict[str, bytes]):
    def opener(url: str):
        if url not in mapa:
            raise OSError(f"404: {url}")
        return FakeResp(mapa[url])

    return opener


class TestDatos(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_dat01_descarga_verificada_con_md5_correcto(self):
        contenido = b"\x00\x0cS" + b"\x00" * 11  # fake mini BinaryFILE
        md5 = hashlib.md5(contenido).hexdigest()
        mapa = {
            "https://emi.test/X.gz": contenido,
            "https://emi.test/X.gz.md5sum": f"{md5}  X.gz\n".encode(),
        }
        destino = fetch("X.gz", self.dir, base_url="https://emi.test/", opener=fake_opener(mapa))
        self.assertEqual(destino.read_bytes(), contenido)

    def test_dat03_md5sum_no_servido_aborta_fail_closed_con_error_claro(self):
        contenido = b"datos"
        mapa = {"https://emi.test/X.gz": contenido}  # no .md5sum -> 404
        # fail closed: clear exception, nothing usable in destination
        with self.assertRaises(Md5NotAvailableError):
            fetch("X.gz", self.dir, base_url="https://emi.test/", opener=fake_opener(mapa))
        self.assertEqual(list(self.dir.iterdir()), [])
        # with the omit flag: downloads and warns
        with self.assertWarnsRegex(UserWarning, "md5"):
            destino = fetch(
                "X.gz", self.dir, base_url="https://emi.test/",
                opener=fake_opener(mapa), allow_no_md5=True,
            )
        self.assertEqual(destino.read_bytes(), contenido)

    def test_sec07_md5_incorrecto_aborta_sin_dejar_fichero_aparentemente_valido(self):
        contenido = b"datos corrompidos"
        mapa = {
            "https://emi.test/X.gz": contenido,
            "https://emi.test/X.gz.md5sum": b"0" * 32 + b"  X.gz\n",
        }
        with self.assertRaises(Md5MismatchError):
            fetch("X.gz", self.dir, base_url="https://emi.test/", opener=fake_opener(mapa))
        self.assertEqual(list(self.dir.iterdir()), [])  # nothing usable remains

    def test_dat02_estadisticas_de_dimensionado_por_simbolo(self):
        bf = self.dir / "in.ITCH50"
        bf.write_bytes(
            binaryfile(
                p_s(),
                p_r(locate=1, stock=b"AAPL    "),
                p_r(locate=2, stock=b"MSFT    "),
                p_a(ref=1, locate=1, ts=10),
                p_a(ref=2, locate=1, ts=11),
                p_a(ref=3, locate=2, ts=12),
                p_x(ref=1, shares=40, ts=13),
            ).getvalue()
        )
        summary = run(bf, None, self.dir)
        # global count by type
        self.assertEqual(summary["messages"], 7)
        self.assertEqual(summary["by_type"]["A"], 3)
        # per-symbol stats in CSV
        csv_path = self.dir / "stats.csv"
        filas = {
            ln.split(",")[0]: ln.split(",")
            for ln in csv_path.read_text().splitlines()
            if ln and not ln.startswith("locate")
        }
        self.assertEqual(filas["1"][1], "AAPL")
        self.assertEqual(int(filas["1"][2]), 4)   # R + A + A + X
        self.assertEqual(int(filas["1"][3]), 2)   # peak live orders
        self.assertEqual(int(filas["1"][4]), 1)   # peak levels (one price)
        self.assertEqual(int(filas["2"][3]), 1)
        # select_subset picks the top by peak live orders
        out_json = self.dir / "subset.json"
        select(csv_path, out_json, n=1, day="2019-12-30")
        data = json.loads(out_json.read_text())
        self.assertEqual([s["symbol"] for s in data["symbols"]], ["AAPL"])
        self.assertEqual(data["symbols"][0]["locate"], 1)
        self.assertEqual(data["n"], 1)


if __name__ == "__main__":
    unittest.main()