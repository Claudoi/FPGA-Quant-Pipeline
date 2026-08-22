"""pcap tooling tests (BinaryFILE -> MoldUDP64 pcap conversion)."""
from __future__ import annotations

import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

from golden_model.tests.test_parser import binaryfile, p_a, p_r, p_s
from scripts.binaryfile_to_pcap import (
    OversizedMessageError,
    convert,
    iter_pcap_packets,
)

UDP_PAYLOAD_MAX = 1400


class TestPcap(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.bf_path = self.dir / "in.ITCH50"
        self.pcap_path = self.dir / "out.pcap"
        self.payloads = [p_s(), p_r(), p_a(ref=1), p_a(ref=2), p_a(ref=3)]
        self.bf_path.write_bytes(binaryfile(*self.payloads).getvalue())

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _convert(self, **kwargs):
        return convert(self.bf_path, self.pcap_path, **kwargs)

    def test_pca01_el_pcap_se_abre_con_tcpdump_sin_errores(self):
        if shutil.which("tcpdump") is None:
            self.fail("tcpdump not installed: gate requirement (see spec criterion 8)")
        stats = self._convert()
        proc = subprocess.run(
            ["tcpdump", "-n", "-r", str(self.pcap_path)],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("bad pkt", proc.stdout + proc.stderr)
        lineas = [ln for ln in proc.stdout.splitlines() if "UDP" in ln]
        self.assertEqual(len(lineas), stats["packets"])
        self.assertGreater(stats["packets"], 0)

    def test_pca02_empaquetado_respeta_el_maximo_de_payload_configurable(self):
        stats = self._convert()
        self.assertEqual(stats["messages"], len(self.payloads))
        for _seq, msgs, raw in iter_pcap_packets(self.pcap_path):
            self.assertLessEqual(len(raw), UDP_PAYLOAD_MAX)
            # MoldUDP64 message count == messages of the datagram
            count = struct.unpack(">H", raw[18:20])[0]  # session 10 + seq 8
            self.assertEqual(count, len(msgs))
        # directed mode: 1 message per packet
        stats1 = self._convert(msgs_per_packet=1)
        self.assertEqual(stats1["packets"], len(self.payloads))

    def test_pca03_sequence_numbers_monotonicos_desde_1(self):
        self._convert(msgs_per_packet=2)
        seqs = [(seq, len(msgs)) for seq, msgs, _ in iter_pcap_packets(self.pcap_path)]
        self.assertEqual(seqs[0][0], 1)
        esperado = 1
        for seq, count in seqs:
            self.assertEqual(seq, esperado)
            esperado += count

    def test_pca04_round_trip_pcap_a_stream_binaryfile_identico(self):
        self._convert()
        reconstruido = b"".join(
            len(m).to_bytes(2, "big") + m
            for _seq, msgs, _raw in iter_pcap_packets(self.pcap_path)
            for m in msgs
        )
        self.assertEqual(reconstruido, self.bf_path.read_bytes())

    def test_pca05_max_messages_recorta_el_stream_sin_perder_grupo(self):
        """Truncation by max_messages: only the first N messages and the last
        partial group is flushed (rule G0: reproducible real-day segments)."""
        stats = self._convert(max_messages=3)
        self.assertEqual(stats["messages"], 3)
        reconstruido = b"".join(
            len(m).to_bytes(2, "big") + m
            for _seq, msgs, _raw in iter_pcap_packets(self.pcap_path)
            for m in msgs
        )
        esperado = binaryfile(*self.payloads[:3]).getvalue()
        self.assertEqual(reconstruido, esperado)

    def test_sec06_mensaje_mayor_que_el_payload_maximo_produce_error_claro(self):
        self.bf_path.write_bytes(binaryfile(p_a(ref=1)).getvalue())
        with self.assertRaises(OversizedMessageError) as ctx:
            self._convert(max_payload=30)  # the A message is 36 B + 2 of length
        self.assertIn("38", str(ctx.exception))
        self.assertIn("message 0", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()