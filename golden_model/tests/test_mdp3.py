"""Tests espejo de specs/fase4-mdp3-parser/gherkin/mdp3.feature (criterio 1).

M3-GEN-01 y M3-GEN-02: round-trip decode(encode(m)) == m y tamaños esperados
derivados del schema SBE XML oficial de CME (templates_FixBinary_v12.xml).
El schema se lee desde data/mdp3/ (gitignored, regla G0); el fetch es
scripts/fetch_mdp3_schema.py (fail closed con md5).
"""
from __future__ import annotations

import unittest
from pathlib import Path

from golden_model.mdp3 import (
    Corpus,
    decode_message,
    encode_message,
    encode_packet,
    iter_packet_messages,
    load_schema,
    message_body_bytes,
)
from golden_model.mdp3.codec import MESSAGE_PREFIX_SIZE
from golden_model.mdp3.generator import UNKNOWN_TEMPLATE

SCHEMA_PATH = Path("data/mdp3/templates_FixBinary_v12.xml")


class TestM3Gen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = load_schema(SCHEMA_PATH)

    def test_m3gen01_el_golden_hace_roundtrip_decode_encode_m_es_m(self):
        schema = self.schema
        for template_id in (46, 47, 52, 53):
            msg_def = schema.messages[template_id]
            corpus = Corpus(schema, seed=template_id)
            for _ in range(5):
                raw = corpus.subset_message(template_id)
                pm = next(iter_packet_messages(encode_packet(schema, 1, 2, [raw])))
                decoded = decode_message(schema, pm)
                self.assertEqual(pm.template_id, template_id)
                for f in msg_def.fields:
                    self.assertIn(f.name, decoded, f"campo {f.name} ausente")
                for g in msg_def.groups:
                    self.assertIn(g.name, decoded, f"grupo {g.name} ausente")
                    for entry in decoded[g.name]:
                        for gf in g.fields:
                            self.assertIn(gf.name, entry,
                                          f"campo {gf.name} ausente en {g.name}")
                # round-trip de bytes: decode(encode(m)) re-encodeado es idéntico
                re_encoded = encode_message(schema, template_id, decoded)
                self.assertEqual(re_encoded, raw,
                                 f"round-trip byte a byte del template {template_id}")

    def test_m3gen01_el_passthrough_preserva_el_cuerpo_crudo(self):
        schema = self.schema
        corpus = Corpus(schema, seed=7)
        for unknown in (False, True):
            raw = corpus.passthrough_message(unknown=unknown)
            pm = next(iter_packet_messages(encode_packet(schema, 1, 2, [raw])))
            decoded = decode_message(schema, pm)
            self.assertEqual(decoded, {}, "un passthrough no se decodifica")
            self.assertEqual(message_body_bytes(pm), raw[MESSAGE_PREFIX_SIZE:],
                             "el cuerpo crudo del passthrough se preserva bit a bit")
        self.assertNotIn(UNKNOWN_TEMPLATE, schema.messages)

    def test_m3gen02_el_loader_deriva_los_tamanos_esperados_desde_el_xml(self):
        schema = self.schema
        # tamaños root del XML v12: incremental 11, snapshot 52=59, 53=28
        self.assertEqual(schema.messages[46].block_length, 11)
        self.assertEqual(schema.messages[47].block_length, 11)
        self.assertEqual(schema.messages[52].block_length, 59)
        self.assertEqual(schema.messages[53].block_length, 28)
        self.assertEqual(schema.header_size, 8)
        # dimensiones de grupo derivadas del XML
        self.assertEqual(schema.group_dim_size(schema.messages[46].groups[0]), 3)
        self.assertEqual(schema.group_dim_size(schema.messages[46].groups[1]), 8)
        # msg_size de cada mensaje del corpus == 10 + root + Σ(dim + n·blockLength)
        corpus = Corpus(schema, seed=42)
        for _ in range(20):
            for template_id in (46, 47, 52, 53):
                raw = corpus.subset_message(template_id)
                pm = next(iter_packet_messages(encode_packet(schema, 1, 2, [raw])))
                decoded = decode_message(schema, pm)
                expected = MESSAGE_PREFIX_SIZE + schema.messages[template_id].block_length
                for g in schema.messages[template_id].groups:
                    expected += schema.group_dim_size(g) \
                        + len(decoded.get(g.name, [])) * g.block_length
                self.assertEqual(pm.msg_size, expected,
                                 f"tamaño esperado (XML) del template {template_id}")
        # caso mínimo: 47 con una entry = 10 + 11 + 3 + 40 = 64 bytes
        raw = encode_message(schema, 47, {
            "TransactTime": 123, "MatchEventIndicator": 1,
            "NoMDEntries": [{
                "OrderID": 5, "MDOrderPriority": 6, "MDEntryPx": {"mantissa": 7},
                "MDDisplayQty": 8, "SecurityID": 9, "MDUpdateAction": 0,
                "MDEntryType": 0}],
        })
        self.assertEqual(len(raw), 64)
        pm = next(iter_packet_messages(encode_packet(schema, 1, 2, [raw])))
        self.assertEqual(pm.msg_size, 64)


if __name__ == "__main__":
    unittest.main()