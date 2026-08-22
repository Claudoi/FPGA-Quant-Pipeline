"""Reference-vector sink tests (the bit-exact record contract)."""
from __future__ import annotations

import io
import unittest

from golden_model.itch.parser import iter_messages
from golden_model.src.book import Book
from golden_model.src.vectors import RECORD_SIZE, VectorSink, dump_text, iter_records
from golden_model.tests.test_parser import binaryfile, p_a, p_d, p_r, p_s, p_x


def run_pipeline(payloads: list[bytes], subset: set[int]) -> io.BytesIO:
    """Parser -> Book -> VectorSink: the real vector emission chain."""
    book = Book()
    out = io.BytesIO()
    sink = VectorSink(out, subset)
    for msg in iter_messages(binaryfile(*payloads)):
        sink.handle(msg, book.apply(msg))
    out.seek(0)
    return out


class TestVectors(unittest.TestCase):
    def test_vec01_un_registro_por_mensaje_modificador_del_subset_con_flag_de_cambio(self):
        out = run_pipeline(
            [
                p_s(),                              # S: does not modify the book
                p_r(locate=1), p_r(locate=2),       # R: does not modify
                p_a(ref=1, side=b"B", shares=100, price=1000000, ts=10),  # locate 1
                p_a(ref=2, locate=2, side=b"B", shares=50, price=900000, ts=11),  # outside the subset
                p_x(ref=1, shares=40, ts=12),       # changes best bid qty -> changed=1
                p_a(ref=3, side=b"B", shares=10, price=800000, ts=13),    # worse level: same BBO -> changed=0
                p_d(ref=3, ts=14),                  # removes the worse level: same BBO -> changed=0
            ],
            subset={1},
        )
        recs = list(iter_records(out))
        # exactly the 4 modifying messages of locate 1 (idx 3,5,6,7)
        self.assertEqual([r[0] for r in recs], [3, 5, 6, 7])
        self.assertEqual([r[7] for r in recs], ["A", "X", "A", "D"])
        self.assertEqual([r[8] for r in recs], [1, 1, 0, 0])
        self.assertEqual(recs[0][2:6], (1000000, 100, 0, 0))
        self.assertEqual(recs[1][2:6], (1000000, 60, 0, 0))

    def test_vec02_layout_binario_fijo_de_40_bytes_por_registro(self):
        self.assertEqual(RECORD_SIZE, 40)
        out = run_pipeline([p_a(ref=i, ts=i) for i in range(1, 6)], subset={1})
        data = out.getvalue()
        self.assertEqual(len(data) % RECORD_SIZE, 0)
        self.assertEqual(len(data) // RECORD_SIZE, 5)
        for rec in iter_records(io.BytesIO(data)):
            self.assertEqual(rec[6], 1)          # locate
            self.assertIn(rec[7], "AFECXDU")     # modifying type

    def test_vec03_round_trip_binario_a_texto_conserva_campos(self):
        out = run_pipeline(
            [p_a(ref=1, side=b"B", shares=100, price=1000000, ts=10), p_x(ref=1, shares=40, ts=11)],
            subset={1},
        )
        binario = out.getvalue()
        txt = io.StringIO()
        dump_text(io.BytesIO(binario), txt)
        lineas = [ln for ln in txt.getvalue().splitlines() if ln and not ln.startswith("#")]
        recs = list(iter_records(io.BytesIO(binario)))
        self.assertEqual(len(lineas), len(recs))
        for linea, rec in zip(lineas, recs):
            partes = linea.split(",")
            self.assertEqual(
                tuple(int(p) for p in partes[:6]),
                (rec[0], rec[1], rec[2], rec[3], rec[4], rec[5]),
            )
            self.assertEqual(int(partes[6]), rec[6])
            self.assertEqual(partes[7], rec[7])
            self.assertEqual(int(partes[8]), rec[8])

    def test_vec04_indices_de_mensaje_son_globales_y_monotonicos(self):
        out = run_pipeline(
            [
                p_a(ref=1, ts=1),                       # idx 0, locate 1
                p_a(ref=2, locate=2, ts=2),             # idx 1, outside the subset
                p_a(ref=3, ts=3),                       # idx 2
                p_x(ref=1, shares=40, ts=4),            # idx 3
            ],
            subset={1},
        )
        indices = [r[0] for r in iter_records(out)]
        self.assertEqual(indices, [0, 2, 3])
        self.assertEqual(indices, sorted(indices))
        self.assertEqual(len(set(indices)), len(indices))  # strictly increasing


if __name__ == "__main__":
    unittest.main()