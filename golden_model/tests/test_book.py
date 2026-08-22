"""Mirror tests of specs/fase0-golden-model/gherkin/book.feature.

Messages are built with the literal helpers of test_parser (offsets written
by hand from the spec PDF) and fed to the book through the real parser:
parser->book integration in each test.
"""
from __future__ import annotations

import unittest

from golden_model.itch.parser import iter_messages
from golden_model.src.book import Book, InvariantError
from golden_model.tests.test_parser import binaryfile, p_a, p_d, p_e, p_h, p_s, p_u, p_x


def feed(book: Book, *payloads: bytes):
    """Feeds the book with raw messages; returns the emitted events."""
    events = []
    for msg in iter_messages(binaryfile(*payloads)):
        ev = book.apply(msg)
        if ev is not None:
            events.append(ev)
    return events


class TestBook(unittest.TestCase):
    def test_lib01_add_order_crea_nivel_y_actualiza_bbo(self):
        book = Book()
        events = feed(book, p_a(ref=1, side=b"B", shares=100, price=1000000))
        self.assertEqual(len(events), 1)
        locate, bbo, changed = events[0]
        self.assertEqual(bbo, (1000000, 100, 0, 0))
        self.assertEqual(changed, 1)

    def test_lib02_execute_parcial_reduce_cantidad_sin_mover_el_bbo_en_precio(self):
        book = Book()
        feed(book, p_a(ref=1, side=b"B", shares=100, price=1000000))
        events = feed(book, p_e(ref=1, shares=40))
        self.assertEqual(events[0][1], (1000000, 60, 0, 0))
        self.assertEqual(book.orders[1][3], 60)  # remaining live qty

    def test_lib03_execute_total_elimina_la_orden_y_retrae_el_bbo(self):
        book = Book()
        feed(book, p_a(ref=1, side=b"B", shares=100, price=1000000))
        events = feed(book, p_e(ref=1, shares=100))
        self.assertNotIn(1, book.orders)
        self.assertEqual(events[0][1], (0, 0, 0, 0))

    def test_lib04_cancel_y_delete_mantienen_niveles_consistentes(self):
        book = Book()
        feed(
            book,
            p_a(ref=1, side=b"S", shares=50, price=2000000),
            p_a(ref=2, side=b"S", shares=70, price=2000000),
        )
        events = feed(book, p_x(ref=1, shares=30), p_d(ref=2))
        # level 2000000: 120 - 30 (X) - 70 (D) = 20
        self.assertEqual(events[-1][1], (0, 0, 2000000, 20))
        events = feed(book, p_x(ref=1, shares=20))
        self.assertEqual(events[-1][1], (0, 0, 0, 0))  # the level disappears

    def test_lib05_replace_es_atomico_y_emite_un_solo_estado_resultante(self):
        book = Book()
        feed(book, p_a(ref=1, side=b"B", shares=100, price=1000000))
        events = feed(book, p_u(orig=1, new=2))  # 200 @ 990000 in the helpers
        self.assertEqual(len(events), 1)  # one single resulting state
        self.assertEqual(events[0][1], (990000, 200, 0, 0))
        self.assertNotIn(1, book.orders)
        self.assertIn(2, book.orders)

    def test_lib06_libro_vacio_emite_bbo_cero(self):
        book = Book()
        feed(book, p_a(ref=1, side=b"B", shares=10, price=100), p_a(ref=2, side=b"S", shares=10, price=200))
        events = feed(book, p_d(ref=1), p_d(ref=2))
        self.assertEqual(events[-1][1], (0, 0, 0, 0))

    def test_sec04_operacion_sobre_order_reference_desconocida_se_cuenta_como_anomalia(self):
        book = Book()
        before = book.anomalies
        events = feed(book, p_e(ref=999), p_x(ref=999), p_d(ref=999), p_u(orig=999, new=1000))
        self.assertEqual(events, [])  # the book is not modified
        self.assertEqual(book.anomalies, before + 4)  # counted, does not abort

    def test_sec05_libro_cruzado_en_estado_de_subasta_no_dispara_la_invariante(self):
        book = Book(strict_cross=True)
        # halted symbol (H with trading_state 'H'): the book may cross
        events = feed(
            book,
            p_h(locate=1, state=b"H"),
            p_a(ref=1, side=b"B", shares=10, price=200),
            p_a(ref=2, side=b"S", shares=10, price=100),
        )
        self.assertEqual(events[-1][1], (200, 10, 100, 10))  # crossed and emitted as-is
        # control: in continuous trading (S 'Q' + H 'T') the same cross is a violated invariant
        book2 = Book(strict_cross=True)
        with self.assertRaises(InvariantError):
            feed(
                book2,
                p_s(event=b"Q"),
                p_h(locate=1, state=b"T"),
                p_a(ref=1, side=b"B", shares=10, price=200),
                p_a(ref=2, side=b"S", shares=10, price=100),
            )

    def test_sec08_libro_bloqueado_en_trading_continuo_en_datos_reales_se_cuenta_no_aborta(self):
        book = Book()  # default mode: not strict
        events = feed(
            book,
            p_h(locate=1, state=b"H"),                       # lock forms during halt
            p_a(ref=1, side=b"B", shares=10, price=200),
            p_a(ref=2, side=b"S", shares=10, price=100),
            p_s(event=b"Q"),
            p_h(locate=1, state=b"T"),                       # resumes with crossed book
            p_e(ref=1, shares=5, ts=50),                     # first modifying message after
        )
        self.assertEqual(events[-1][1], (200, 5, 100, 10))
        self.assertEqual(book.cross_events, 1)               # counted, not aborted

    def test_inv01_invariantes_del_libro_se_chequean_mensaje_a_mensaje(self):
        # duplicate reference
        with self.assertRaises(InvariantError) as ctx:
            feed(Book(strict_cross=True), p_a(ref=1), p_a(ref=1))
        self.assertIn("1", str(ctx.exception))  # message index
        # execution greater than the live quantity -> non-positive qty
        with self.assertRaises(InvariantError):
            feed(Book(strict_cross=True), p_a(ref=1, shares=50), p_e(ref=1, shares=60))
        # CLOSED book (bid == ask) in continuous trading is also a violation (strict mode)
        with self.assertRaises(InvariantError):
            feed(
                Book(strict_cross=True),
                p_s(event=b"Q"),
                p_h(locate=1, state=b"T"),
                p_a(ref=1, side=b"B", shares=10, price=100),
                p_a(ref=2, side=b"S", shares=10, price=100),
            )
        # inconsistent levels detected by the deep check
        book = Book()
        feed(book, p_a(ref=1, side=b"B", shares=100, price=1000000))
        book._levels[(1, "B")][1000000] = 999  # corruption on purpose
        with self.assertRaises(InvariantError):
            book.check_deep()


if __name__ == "__main__":
    unittest.main()