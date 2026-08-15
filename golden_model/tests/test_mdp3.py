"""Tests espejo de specs/fase4-mdp3-parser/gherkin/mdp3.feature (criterio 1).

M3-GEN-01 y M3-GEN-02: round-trip decode(encode(m)) == m y tamaños esperados
derivados del schema SBE XML oficial de CME (templates_FixBinary_v12.xml).
El schema se lee desde data/mdp3/ (gitignored, regla G0); el fetch es
scripts/fetch_mdp3_schema.py (fail closed con md5).
"""
from __future__ import annotations

import unittest
from pathlib import Path
import re

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

    def test_m3gen01_el_encoder_preserva_valores_no_cero_del_subset(self):
        schema = self.schema

        def assert_preserved(expected, actual, path=""):
            if isinstance(expected, dict):
                for key, value in expected.items():
                    self.assertIn(key, actual, f"campo ausente: {path}{key}")
                    assert_preserved(value, actual[key], f"{path}{key}.")
            elif isinstance(expected, list):
                self.assertEqual(len(actual), len(expected), path.rstrip("."))
                for index, value in enumerate(expected):
                    assert_preserved(value, actual[index], f"{path}{index}.")
            elif isinstance(expected, int) and isinstance(actual, bytes):
                self.assertEqual(actual, bytes([expected]), path.rstrip("."))
            else:
                self.assertEqual(actual, expected, path.rstrip("."))

        def decoded(template_id, values):
            raw = encode_message(schema, template_id, values)
            packet = encode_packet(schema, 17, 23, [raw])
            result = decode_message(schema, next(iter_packet_messages(packet)))
            assert_preserved(values, result)
            return result

        m46 = decoded(46, {
            "TransactTime": 0x0102030405060708,
            "MatchEventIndicator": 0x81,
            "NoMDEntries": [
                {"MDEntryPx": {"mantissa": 101_250_000_000},
                 "MDEntrySize": 7, "SecurityID": 101, "RptSeq": 11,
                 "NumberOfOrders": 2, "MDPriceLevel": 1,
                 "MDUpdateAction": 0, "MDEntryType": 0,
                 "TradeableSize": 5},
                {"MDEntryPx": {"mantissa": -101_125_000_000},
                 "MDEntrySize": 9, "SecurityID": 202, "RptSeq": 12,
                 "NumberOfOrders": 3, "MDPriceLevel": 2,
                 "MDUpdateAction": 1, "MDEntryType": 1,
                 "TradeableSize": 6},
            ],
            "NoOrderIDEntries": [
                {"OrderID": 0x1112131415161718,
                 "MDOrderPriority": 0x2122232425262728,
                 "MDDisplayQty": 13, "ReferenceID": 0,
                 "OrderUpdateAction": 1},
                {"OrderID": 0x3132333435363738,
                 "MDOrderPriority": 0x4142434445464748,
                 "MDDisplayQty": 14, "ReferenceID": 1,
                 "OrderUpdateAction": 2},
            ],
        })
        self.assertEqual(m46["TransactTime"], 0x0102030405060708)
        self.assertEqual(m46["NoMDEntries"][1]["MDEntryPx"]["mantissa"],
                         -101_125_000_000)
        self.assertEqual(m46["NoOrderIDEntries"][1]["OrderID"],
                         0x3132333435363738)
        self.assertEqual(m46["NoOrderIDEntries"][1]["ReferenceID"], 1)

        m47 = decoded(47, {
            "TransactTime": 0x5152535455565758,
            "MatchEventIndicator": 0x82,
            "NoMDEntries": [{
                "OrderID": 0x6162636465666768,
                "MDOrderPriority": 0x7172737475767778,
                "MDEntryPx": {"mantissa": 99_875_000_000},
                "MDDisplayQty": 21, "SecurityID": 303,
                "MDUpdateAction": 2, "MDEntryType": 1,
            }],
        })
        self.assertEqual(m47["TransactTime"], 0x5152535455565758)
        self.assertEqual(m47["NoMDEntries"][0]["OrderID"],
                         0x6162636465666768)
        self.assertEqual(m47["NoMDEntries"][0]["MDDisplayQty"], 21)
        self.assertEqual(m47["NoMDEntries"][0]["MDUpdateAction"], 2)

        m52 = decoded(52, {
            "LastMsgSeqNumProcessed": 31, "TotNumReports": 32,
            "SecurityID": 404, "RptSeq": 33,
            "TransactTime": 0x8182838485868788,
            "LastUpdateTime": 0x9192939495969798, "TradeDate": 19_001,
            "MDSecurityTradingStatus": 3,
            "HighLimitPrice": {"mantissa": 110_000_000_000},
            "LowLimitPrice": {"mantissa": 90_000_000_000},
            "MaxPriceVariation": {"mantissa": 20_000_000_000},
            "NoMDEntries": [{
                "MDEntryPx": {"mantissa": 100_500_000_000},
                "MDEntrySize": 41, "NumberOfOrders": 4,
                "MDPriceLevel": 2, "TradingReferenceDate": 19_002,
                "OpenCloseSettlFlag": 1, "SettlPriceType": 5,
                "MDEntryType": 1,
            }],
        })
        self.assertEqual(m52["SecurityID"], 404)
        self.assertEqual(m52["RptSeq"], 33)
        self.assertEqual(m52["NoMDEntries"][0]["MDEntryPx"]["mantissa"],
                         100_500_000_000)
        self.assertEqual(m52["NoMDEntries"][0]["MDEntrySize"], 41)

        m53 = decoded(53, {
            "LastMsgSeqNumProcessed": 51, "TotNumReports": 52,
            "SecurityID": 505, "NoChunks": 3, "CurrentChunk": 2,
            "TransactTime": 0xA1A2A3A4A5A6A7A8,
            "NoMDEntries": [{
                "OrderID": 0xB1B2B3B4B5B6B7B8,
                "MDOrderPriority": 0xC1C2C3C4C5C6C7C8,
                "MDEntryPx": {"mantissa": 102_000_000_000},
                "MDDisplayQty": 61, "MDEntryType": 1,
            }],
        })
        self.assertEqual(m53["SecurityID"], 505)
        self.assertEqual(m53["NoMDEntries"][0]["OrderID"],
                         0xB1B2B3B4B5B6B7B8)
        self.assertEqual(m53["NoMDEntries"][0]["MDEntryPx"]["mantissa"],
                         102_000_000_000)
        self.assertEqual(m53["NoMDEntries"][0]["MDDisplayQty"], 61)

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

    def test_m3sch01_los_localparams_rtl_coinciden_con_el_schema_v12(self):
        schema = self.schema
        rtl = Path("rtl/parser/mdp3_parser.sv").read_text()

        def field_offset(fields, name):
            return next(field.offset for field in fields if field.name == name)

        m46, m47 = schema.messages[46], schema.messages[47]
        m52, m53 = schema.messages[52], schema.messages[53]
        g46_mbp, g46_oid = m46.groups
        g47, g52, g53 = m47.groups[0], m52.groups[0], m53.groups[0]
        expected = {
            "MSG_PREFIX": 2 + schema.header_size,
            "TPL_46": 46, "TPL_47": 47, "TPL_52": 52, "TPL_53": 53,
            "O46_TS": field_offset(m46.fields, "TransactTime"),
            "O46_MEI": field_offset(m46.fields, "MatchEventIndicator"),
            "O46_DIM": m46.block_length,
            "O46_ENT": m46.block_length + schema.group_dim_size(g46_mbp),
            "O46_BL1": g46_mbp.block_length, "O46_BL2": g46_oid.block_length,
            "O46_PX": field_offset(g46_mbp.fields, "MDEntryPx"),
            "O46_SZ": field_offset(g46_mbp.fields, "MDEntrySize"),
            "O46_SEC": field_offset(g46_mbp.fields, "SecurityID"),
            "O46_RPT": field_offset(g46_mbp.fields, "RptSeq"),
            "O46_NO": field_offset(g46_mbp.fields, "NumberOfOrders"),
            "O46_LVL": field_offset(g46_mbp.fields, "MDPriceLevel"),
            "O46_ACT": field_offset(g46_mbp.fields, "MDUpdateAction"),
            "O46_TYP": field_offset(g46_mbp.fields, "MDEntryType"),
            "O46_OID": field_offset(g46_oid.fields, "OrderID"),
            "O46_PRI": field_offset(g46_oid.fields, "MDOrderPriority"),
            "O46_DQ": field_offset(g46_oid.fields, "MDDisplayQty"),
            "O46_REF": field_offset(g46_oid.fields, "ReferenceID"),
            "O46_OA": field_offset(g46_oid.fields, "OrderUpdateAction"),
            "O47_OID": field_offset(g47.fields, "OrderID"),
            "O47_PRI": field_offset(g47.fields, "MDOrderPriority"),
            "O47_PX": field_offset(g47.fields, "MDEntryPx"),
            "O47_DQ": field_offset(g47.fields, "MDDisplayQty"),
            "O47_SEC": field_offset(g47.fields, "SecurityID"),
            "O47_ACT": field_offset(g47.fields, "MDUpdateAction"),
            "O47_TYP": field_offset(g47.fields, "MDEntryType"),
            "O47_BL": g47.block_length,
            "O52_SEC": field_offset(m52.fields, "SecurityID"),
            "O52_RPT": field_offset(m52.fields, "RptSeq"),
            "O52_TS": field_offset(m52.fields, "TransactTime"),
            "O52_DIM": m52.block_length,
            "O52_ENT": m52.block_length + schema.group_dim_size(g52),
            "O52_BL": g52.block_length,
            "O52_PX": field_offset(g52.fields, "MDEntryPx"),
            "O52_SZ": field_offset(g52.fields, "MDEntrySize"),
            "O52_NO": field_offset(g52.fields, "NumberOfOrders"),
            "O52_LVL": field_offset(g52.fields, "MDPriceLevel"),
            "O52_TYP": field_offset(g52.fields, "MDEntryType"),
            "O53_SEC": field_offset(m53.fields, "SecurityID"),
            "O53_TS": field_offset(m53.fields, "TransactTime"),
            "O53_DIM": m53.block_length,
            "O53_ENT": m53.block_length + schema.group_dim_size(g53),
            "O53_BL": g53.block_length,
            "O53_OID": field_offset(g53.fields, "OrderID"),
            "O53_PRI": field_offset(g53.fields, "MDOrderPriority"),
            "O53_PX": field_offset(g53.fields, "MDEntryPx"),
            "O53_DQ": field_offset(g53.fields, "MDDisplayQty"),
            "O53_TYP": field_offset(g53.fields, "MDEntryType"),
        }
        for name, value in expected.items():
            match = re.search(
                rf"\b{re.escape(name)}\s*=\s*(?:(?:\d+)'d)?(\d+)\b", rtl)
            self.assertIsNotNone(match, f"localparam RTL ausente: {name}")
            self.assertEqual(int(match.group(1)), value,
                             f"drift schema v12↔RTL en {name}")


if __name__ == "__main__":
    unittest.main()
