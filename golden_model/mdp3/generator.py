"""Generator de corpus sintético MDP 3.0 (determinista, seeded).

Produce paquetes válidos del subset (46/47/52/53) y passthrough (templates
reales no-subset y desconocidos). Todo el layout se deriva del schema. Los
paquetes se exportan/importan como vectores JSON (base64) para los testbenches
cocotb (iter 2+), y se conservan en verification/vectors/mdp3/.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from golden_model.mdp3.codec import (
    MESSAGE_PREFIX_SIZE,
    encode_message,
    encode_packet,
    iter_packet_messages,
    decode_message,
    anexo_m_records,
    passthrough_record,
)
from golden_model.mdp3.schema import Schema, SUBSET_TEMPLATES

PASSTHROUGH_TEMPLATES = (4, 12, 30, 37, 48)  # reales no-subset del schema v12
UNKNOWN_TEMPLATE = 777


class Corpus:
    """Corpus sintético: paquetes + records Anexo M esperados (oráculo)."""

    def __init__(self, schema: Schema, seed: int = 20260814):
        self.schema = schema
        self.rng = random.Random(seed)
        self.security_ids = (101, 202, 303, 404)
        self.packets: list[bytes] = []
        self.expected: list[list[int]] = []  # words por record, en orden de emisión

    # ── construcción ──────────────────────────────────────────────────────────

    def _price(self):
        return {"mantissa": self.rng.randrange(-1_000_000_000, 1_000_000_001)}

    def _mbp_entry(self, rpt: int):
        return {
            "MDEntryPx": self._price(),
            "MDEntrySize": self.rng.randrange(1, 10_000),
            "SecurityID": self.rng.choice(self.security_ids),
            "RptSeq": rpt,
            "NumberOfOrders": self.rng.randrange(1, 50),
            "MDPriceLevel": self.rng.randrange(1, 10),
            "MDUpdateAction": self.rng.randrange(0, 3),
            "MDEntryType": self.rng.randrange(0, 2),
            "TradeableSize": self.rng.randrange(0, 10_000),
        }

    def _mbofd_entry(self, ref: int):
        return {
            "OrderID": self.rng.getrandbits(64),
            "MDOrderPriority": self.rng.getrandbits(64),
            "MDDisplayQty": self.rng.randrange(1, 10_000),
            "ReferenceID": ref,
            "OrderUpdateAction": self.rng.randrange(0, 3),
        }

    def _order_entry(self):
        return {
            "OrderID": self.rng.getrandbits(64),
            "MDOrderPriority": self.rng.getrandbits(64),
            "MDEntryPx": self._price(),
            "MDDisplayQty": self.rng.randrange(1, 10_000),
            "SecurityID": self.rng.choice(self.security_ids),
            "MDUpdateAction": self.rng.randrange(0, 3),
            "MDEntryType": self.rng.randrange(0, 2),
        }

    def subset_message(self, template: int) -> bytes:
        if template == 46:
            n_mbp = self.rng.randrange(0, 4)
            mbp = [self._mbp_entry(self.rng.randrange(1, 1000)) for _ in range(n_mbp)]
            n_oid = self.rng.randrange(0, 4)
            oid = [self._mbofd_entry(self.rng.randrange(0, max(n_mbp, 1)))
                   for _ in range(n_oid)]
            return encode_message(self.schema, 46, {
                "TransactTime": self.rng.getrandbits(64),
                "MatchEventIndicator": self.rng.randrange(0, 256),
                "NoMDEntries": mbp,
                "NoOrderIDEntries": oid,
            })
        if template == 47:
            return encode_message(self.schema, 47, {
                "TransactTime": self.rng.getrandbits(64),
                "MatchEventIndicator": self.rng.randrange(0, 256),
                "NoMDEntries": [self._order_entry()
                                for _ in range(self.rng.randrange(0, 5))],
            })
        if template == 52:
            return encode_message(self.schema, 52, {
                "LastMsgSeqNumProcessed": self.rng.randrange(0, 2**31),
                "TotNumReports": self.rng.randrange(0, 2**31),
                "SecurityID": self.rng.choice(self.security_ids),
                "RptSeq": self.rng.randrange(1, 1000),
                "TransactTime": self.rng.getrandbits(64),
                "LastUpdateTime": self.rng.getrandbits(64),
                "TradeDate": self.rng.randrange(18000, 20000),
                "MDSecurityTradingStatus": self.rng.randrange(0, 4),
                "HighLimitPrice": self._price(),
                "LowLimitPrice": self._price(),
                "MaxPriceVariation": self._price(),
                "NoMDEntries": [{
                    "MDEntryPx": self._price(),
                    "MDEntrySize": self.rng.randrange(1, 10_000),
                    "NumberOfOrders": self.rng.randrange(1, 50),
                    "MDPriceLevel": self.rng.randrange(1, 10),
                    "TradingReferenceDate": self.rng.randrange(18000, 20000),
                    "OpenCloseSettlFlag": self.rng.randrange(0, 2),
                    "SettlPriceType": self.rng.randrange(0, 256),
                    "MDEntryType": self.rng.randrange(0, 2),
                } for _ in range(self.rng.randrange(0, 5))],
            })
        if template == 53:
            return encode_message(self.schema, 53, {
                "LastMsgSeqNumProcessed": self.rng.randrange(0, 2**31),
                "TotNumReports": self.rng.randrange(0, 2**31),
                "SecurityID": self.rng.choice(self.security_ids),
                "NoChunks": self.rng.randrange(1, 10),
                "CurrentChunk": self.rng.randrange(0, 10),
                "TransactTime": self.rng.getrandbits(64),
                "NoMDEntries": [{
                    "OrderID": self.rng.getrandbits(64),
                    "MDOrderPriority": self.rng.getrandbits(64),
                    "MDEntryPx": self._price(),
                    "MDDisplayQty": self.rng.randrange(1, 10_000),
                    "MDEntryType": self.rng.randrange(0, 2),
                } for _ in range(self.rng.randrange(0, 5))],
            })
        raise ValueError(f"template fuera del subset: {template}")

    def passthrough_message(self, unknown: bool = False) -> bytes:
        """Mensaje crudo no decodificado: template real no-subset o desconocido."""
        if unknown:
            body = bytes(self.rng.randrange(8, 64)
                         for _ in range(self.rng.randrange(8, 64)))
            size = MESSAGE_PREFIX_SIZE + len(body)
            return size.to_bytes(2, "little") + (8).to_bytes(2, "little") \
                + UNKNOWN_TEMPLATE.to_bytes(2, "little") \
                + (999).to_bytes(2, "little") + (0).to_bytes(2, "little") + body
        template = self.rng.choice(PASSTHROUGH_TEMPLATES)
        body = bytes(self.rng.randrange(0, 256)
                     for _ in range(self.rng.randrange(1, 48)))
        size = MESSAGE_PREFIX_SIZE + len(body)
        return size.to_bytes(2, "little") + (16).to_bytes(2, "little") \
            + template.to_bytes(2, "little") \
            + (0).to_bytes(2, "little") + (0).to_bytes(2, "little") + body

    def add_packet(self, n_messages: int = 4, seq: int | None = None) -> bytes:
        """Un paquete con n_messages mensajes mezclados; actualiza el oráculo."""
        if seq is None:
            seq = self.rng.randrange(0, 2**31)
        sending = self.rng.getrandbits(64)
        msgs = [self.subset_message(self.rng.choice(SUBSET_TEMPLATES))
                for _ in range(n_messages // 2)]
        msgs += [self.passthrough_message() for _ in range(n_messages - len(msgs))]
        self.rng.shuffle(msgs)
        packet = encode_packet(self.schema, seq, sending, msgs)
        self.packets.append(packet)
        for pm in iter_packet_messages(packet):
            if pm.template_id in SUBSET_TEMPLATES:
                decoded = decode_message(self.schema, pm)
                self.expected.extend(anexo_m_records(self.schema, pm, decoded))
            else:
                self.expected.append(passthrough_record(self.schema, pm))
        return packet

    def build(self, n_packets: int = 16) -> "Corpus":
        for _ in range(n_packets):
            self.add_packet()
        return self

    # ── vectores ──────────────────────────────────────────────────────────────

    def save(self, path: str | Path):
        payloads = [p.hex() for p in self.packets]
        Path(path).write_text(json.dumps({
            "schema_version": self.schema.version,
            "n_packets": len(self.packets),
            "packets_hex": payloads,
        }, indent=1))

    @staticmethod
    def load(schema: Schema, path: str | Path) -> "Corpus":
        data = json.loads(Path(path).read_text())
        corpus = Corpus(schema)
        corpus.packets = [bytes.fromhex(p) for p in data["packets_hex"]]
        for packet in corpus.packets:
            for pm in iter_packet_messages(packet):
                if pm.template_id in SUBSET_TEMPLATES:
                    decoded = decode_message(schema, pm)
                    corpus.expected.extend(anexo_m_records(schema, pm, decoded))
                else:
                    corpus.expected.append(passthrough_record(schema, pm))
        return corpus