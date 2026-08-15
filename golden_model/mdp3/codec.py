"""Codec SBE MDP 3.0: encode/decode de mensajes y paquetes + Anexo M.

Round-trip estricto: lo que encode_message escribe es exactamente lo que
decode_message lee (M3-GEN-01). El Anexo M materializa la tabla de derivación
por template de la spec (§Derivación del Anexo M por template).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

from golden_model.mdp3.schema import Schema, MessageDef, GroupDef, FieldDef, SUBSET_TEMPLATES

PACKET_HEADER_SIZE = 12
MESSAGE_PREFIX_SIZE = 10  # msg_size u16 + cabecera SBE 8 B

PRIMITIVE_SIZES = {
    "int8": 1, "uint8": 1, "char": 1,
    "int16": 2, "uint16": 2,
    "int32": 4, "uint32": 4,
    "int64": 8, "uint64": 8,
}


# ── utilidades de valor ──────────────────────────────────────────────────────

def _encode_value(schema: Schema, type_name: str, value, raw: bytearray):
    """Escribe `value` (int/bytes/dict-compuesto) con el layout de type_name."""
    if type_name in schema.composites:
        comps = schema.composites[type_name]
        for comp in comps:
            if comp.type.presence == "constant":
                continue
            v = value[comp.name] if isinstance(value, dict) else value
            _encode_primitive(schema, comp.type.primitive, v, raw)
    elif type_name in schema.enums:
        enum = schema.enums[type_name]
        if isinstance(value, str):
            value = enum.values[value]
        _encode_primitive(schema, enum.encoding, value, raw)
    elif type_name in schema.sets:
        _encode_primitive(schema, schema.sets[type_name].encoding, value, raw)
    else:
        _encode_primitive(schema, schema.types[type_name].primitive, value, raw)


def _put_value(schema: Schema, type_name: str, value,
               target: bytearray, offset: int):
    encoded = bytearray()
    _encode_value(schema, type_name, value, encoded)
    target[offset:offset + len(encoded)] = encoded


def _encode_primitive(schema: Schema, primitive: str, value, raw: bytearray):
    size = PRIMITIVE_SIZES[primitive]
    if primitive == "char":
        if isinstance(value, str):
            value = value.encode()
        raw.extend(value[:size].ljust(size, b"\x00") if isinstance(value, bytes) else bytes([value]))
        return
    raw.extend(int(value).to_bytes(size, "little", signed=primitive.startswith("int")))


def _decode_value(schema: Schema, type_name: str, buf: bytes, offset: int):
    """Lee un campo; devuelve int/bytes/(mantissa, exponent)."""
    if type_name in schema.composites:
        comps = schema.composites[type_name]
        out = {}
        for comp in comps:
            if comp.type.presence == "constant":
                out[comp.name] = comp.type.constant
                continue
            out[comp.name] = _decode_primitive(comp.type.primitive, buf, offset)
            offset += comp.type.size
        return out
    if type_name in schema.enums:
        enum = schema.enums[type_name]
        return _decode_primitive(enum.encoding, buf, offset)
    if type_name in schema.sets:
        return _decode_primitive(schema.sets[type_name].encoding, buf, offset)
    t = schema.types[type_name]
    if t.presence == "constant":
        return t.constant
    return _decode_primitive(t.primitive, buf, offset)


def _decode_primitive(primitive: str, buf: bytes, offset: int):
    size = PRIMITIVE_SIZES[primitive]
    if primitive == "char":
        return buf[offset:offset + size]
    raw = buf[offset:offset + size]
    if primitive.startswith("int"):
        return int.from_bytes(raw, "little", signed=True)
    return int.from_bytes(raw, "little")


# ── mensajes ─────────────────────────────────────────────────────────────────

def encode_message(schema: Schema, template_id: int, values: dict,
                   schema_id: int = 0, version: int | None = None) -> bytes:
    """Codifica un mensaje SBE (con su prefijo msg_size + cabecera de 8 B).

    `values`: dict con los campos del root por NOMBRE (o tag FIX como str) y
    los grupos por NOMBRE como listas de dicts de entrada.
    """
    msg = schema.messages[template_id]
    act_version = schema.version if version is None else version
    root = bytearray(msg.block_length)

    def put_field(f: FieldDef, v):
        if v is None:
            return
        _put_value(schema, f.type, v, root, f.offset)

    for f in msg.fields:
        if f.since_version <= act_version:
            key = f.name if f.name in values else str(f.id)
            put_field(f, values.get(key))

    body = bytes(root)
    for g in msg.groups:
        entries = values.get(g.name, [])
        dim = bytearray(schema.group_dim_size(g))
        struct.pack_into("<H", dim, 0, g.block_length)
        if g.dimension_type == "groupSize8Byte":
            dim[7] = len(entries)
        else:
            dim[2] = len(entries)
        body += bytes(dim)
        for entry in entries:
            e = bytearray(g.block_length)
            for gf in g.fields:
                if gf.since_version > act_version:
                    continue
                key = gf.name if gf.name in entry else str(gf.id)
                _put_value(schema, gf.type, entry.get(key), e, gf.offset)
            body += bytes(e)

    msg_size = MESSAGE_PREFIX_SIZE + len(body)
    header = struct.pack("<HHHH", msg.block_length, template_id, schema_id, act_version)
    return struct.pack("<H", msg_size) + header + body


def encode_packet(schema: Schema, seq: int, sending_time_ns: int,
                  messages: list[bytes]) -> bytes:
    """Paquete MDP 3.0: MsgSeqNum u32 + SendingTime u64 + mensajes."""
    return (struct.pack("<IQ", seq, sending_time_ns) + b"".join(messages))


# ── decode ───────────────────────────────────────────────────────────────────

@dataclass
class PacketMessage:
    seq: int
    sending_time_ns: int
    msg_size: int
    block_length: int
    template_id: int
    schema_id: int
    version: int
    body: bytes  # bloque declarado por msg_size (sin los 10 B de prefijo)


def iter_packet_messages(packet: bytes):
    """Camina un paquete; devuelve PacketMessage por mensaje declarado."""
    seq, sending = struct.unpack_from("<IQ", packet, 0)
    off = PACKET_HEADER_SIZE
    while off + 2 <= len(packet):
        (msg_size,) = struct.unpack_from("<H", packet, off)
        if msg_size < MESSAGE_PREFIX_SIZE or off + msg_size > len(packet):
            yield PacketMessage(seq, sending, msg_size, 0, 0, 0, 0, b"")
            return
        block_length, template_id, schema_id, version = struct.unpack_from(
            "<HHHH", packet, off + 2)
        body = packet[off + MESSAGE_PREFIX_SIZE: off + msg_size]
        yield PacketMessage(seq, sending, msg_size, block_length,
                            template_id, schema_id, version, body)
        off += msg_size


def decode_message(schema: Schema, pm: PacketMessage) -> dict:
    """Decodifica un mensaje a dict (root + grupos) respetando version/block_length.

    Solo el subset de libro se decodifica; cualquier otro template (aunque
    exista en el schema) es passthrough y devuelve {}.
    """
    if pm.template_id not in SUBSET_TEMPLATES:
        return {}
    msg = schema.messages.get(pm.template_id)
    if msg is None or pm.block_length > msg.block_length:
        return {}
    out: dict = {}
    act_ver = pm.version
    for f in msg.fields:
        if f.since_version <= act_ver and f.offset + schema.field_size(f) <= pm.block_length:
            out[f.name] = _decode_value(schema, f.type, pm.body, f.offset)
    base = pm.block_length
    for g in msg.groups:
        if g.since_version > act_ver:
            continue
        dim = schema.group_dim_size(g)
        if base + dim > len(pm.body):
            out[g.name] = []
            base += dim
            continue
        if g.dimension_type == "groupSize8Byte":
            num = pm.body[base + 7] if dim >= 8 else 0
        else:
            num = pm.body[base + 2] if dim >= 3 else 0
        base += dim
        entries = []
        for _ in range(num):
            if base + g.block_length > len(pm.body):
                break
            entry = {}
            for gf in g.fields:
                if gf.since_version <= act_ver and gf.offset + schema.field_size(gf) <= g.block_length:
                    entry[gf.name] = _decode_value(schema, gf.type, pm.body, base + gf.offset)
            entries.append(entry)
            base += g.block_length
        out[g.name] = entries
    return out


def message_body_bytes(pm: PacketMessage) -> bytes:
    """Cuerpo crudo del mensaje (para passthrough y verificaciones de tamaño)."""
    return pm.body


# ── Anexo M ──────────────────────────────────────────────────────────────────

MBP_RECORD_WORDS = 13
MBOFD_RECORD_WORDS = 18


def _price(px) -> tuple[int, int]:
    """(mantissa, exponent); el exponent constante viene del schema (PRICE9=-9)."""
    if px is None:
        return 0, 0
    return px["mantissa"], px["exponent"]


def anexo_m_records(schema: Schema, pm: PacketMessage, decoded: dict):
    """Records Anexo M (listas de words) para mensajes del subset; [] si passthrough."""
    tpl = pm.template_id
    if tpl not in SUBSET_TEMPLATES:
        return []
    records: list[list[int]] = []
    if tpl == 46:
        mbp = decoded.get("NoMDEntries", [])
        for e in mbp:
            mant, exp = _price(e.get("MDEntryPx"))
            records.append(_mbp_record(schema, pm, decoded, e, mant, exp))
        for o in decoded.get("NoOrderIDEntries", []):
            ref = o.get("ReferenceID")
            src = mbp[ref] if isinstance(ref, int) and 0 <= ref < len(mbp) else None
            mant, exp = _price(src.get("MDEntryPx")) if src else (0, 0)
            records.append(_mbofd_record(
                schema, pm, decoded,
                security_id=src.get("SecurityID") if src else 0,
                rpt_seq=src.get("RptSeq") if src else 0,
                action=o.get("OrderUpdateAction", 0),
                entry_type=src.get("MDEntryType") if src else 0,
                order_id=o.get("OrderID", 0),
                priority=o.get("MDOrderPriority", 0),
                reference_id=ref if isinstance(ref, int) else 0,
                mantissa=mant, exponent=exp,
                display_qty=o.get("MDDisplayQty", 0),
            ))
    elif tpl == 47:
        for e in decoded.get("NoMDEntries", []):
            mant, exp = _price(e.get("MDEntryPx"))
            records.append(_mbofd_record(
                schema, pm, decoded,
                security_id=e.get("SecurityID", 0),
                rpt_seq=0,
                action=e.get("MDUpdateAction", 0),
                entry_type=e.get("MDEntryType", 0),
                order_id=e.get("OrderID", 0),
                priority=e.get("MDOrderPriority", 0),
                reference_id=0,
                mantissa=mant, exponent=exp,
                display_qty=e.get("MDDisplayQty", 0),
            ))
    elif tpl == 52:
        for e in decoded.get("NoMDEntries", []):
            mant, exp = _price(e.get("MDEntryPx"))
            records.append(_mbp_record(schema, pm, decoded, e, mant, exp,
                                       root_security=decoded.get("SecurityID", 0),
                                       root_rpt=decoded.get("RptSeq", 0)))
    elif tpl == 53:
        for e in decoded.get("NoMDEntries", []):
            mant, exp = _price(e.get("MDEntryPx"))
            records.append(_mbofd_record(
                schema, pm, decoded,
                security_id=decoded.get("SecurityID", 0),
                rpt_seq=0,
                action=0,
                entry_type=e.get("MDEntryType", 0),
                order_id=e.get("OrderID", 0),
                priority=e.get("MDOrderPriority", 0),
                reference_id=0,
                mantissa=mant, exponent=exp,
                display_qty=e.get("MDDisplayQty", 0),
            ))
    return records


def _base_words(pm: PacketMessage, decoded: dict, record_type: int,
                action: int, entry_type: int) -> list[int]:
    transact = decoded.get("TransactTime", 0)
    mei = decoded.get("MatchEventIndicator", 0)
    return [
        (pm.template_id << 16) | (pm.msg_size & 0xFFFF),
        (pm.schema_id << 16) | (pm.version & 0xFFFF),
        transact & 0xFFFFFFFF,
        (transact >> 32) & 0xFFFFFFFF,
        (mei & 0xFF) << 24,
        0,  # w5 security_id
        0,  # w6 rpt_seq
        ((record_type & 0xFF) << 24) | ((action & 0xFF) << 16) | ((entry_type & 0xFF) << 8),
    ]


def _mbp_record(schema: Schema, pm: PacketMessage, decoded: dict, entry: dict,
                mantissa: int, exponent: int,
                root_security: int | None = None, root_rpt: int | None = None) -> list[int]:
    w = _base_words(pm, decoded, 0, entry.get("MDUpdateAction", 0),
                    _entry_type_int(entry.get("MDEntryType")))
    w[5] = root_security if root_security is not None else entry.get("SecurityID", 0)
    w[6] = root_rpt if root_rpt is not None else entry.get("RptSeq", 0)
    w += [mantissa & 0xFFFFFFFF, (mantissa >> 32) & 0xFFFFFFFF,
          (exponent & 0xFF) << 24,
          entry.get("MDEntrySize", 0) & 0xFFFFFFFF,
          ((entry.get("NumberOfOrders", 0) & 0xFFFF) << 16)
          | (entry.get("MDPriceLevel", 0) & 0xFFFF)]
    assert len(w) == MBP_RECORD_WORDS
    return w


def _mbofd_record(schema: Schema, pm: PacketMessage, decoded: dict,
                  security_id: int, rpt_seq: int, action: int, entry_type,
                  order_id: int, priority: int, reference_id: int,
                  mantissa: int, exponent: int, display_qty: int) -> list[int]:
    w = _base_words(pm, decoded, 1, action, _entry_type_int(entry_type))
    w[5] = security_id & 0xFFFFFFFF
    w[6] = rpt_seq & 0xFFFFFFFF
    w += [order_id & 0xFFFFFFFF, (order_id >> 32) & 0xFFFFFFFF,
          priority & 0xFFFFFFFF, (priority >> 32) & 0xFFFFFFFF,
          (reference_id & 0xFF) << 24,
          mantissa & 0xFFFFFFFF, (mantissa >> 32) & 0xFFFFFFFF,
          (exponent & 0xFF) << 24,
          display_qty & 0xFFFFFFFF,
          0]
    assert len(w) == MBOFD_RECORD_WORDS
    return w


def _entry_type_int(v):
    if v is None:
        return 0
    if isinstance(v, bytes):
        return v[0] if v else 0
    return v


def passthrough_record(schema: Schema, pm: PacketMessage) -> list[int]:
    """w0/w1 + cuerpo crudo rellenado a palabra (32 bits), cero al final.

    El cuerpo se empaqueta en words big-endian: el stream del Anexo M es
    byte-continuo con words MSB-first, así que los bytes del cuerpo se
    preservan exactamente (record_bytes == w0_be + w1_be + cuerpo + pad).
    """
    words = [pm.template_id << 16 | (pm.msg_size & 0xFFFF),
             (pm.schema_id << 16) | (pm.version & 0xFFFF)]
    body = pm.body
    if len(body) % 4:
        body = body + b"\x00" * (4 - len(body) % 4)
    words += [int.from_bytes(body[i:i + 4], "big") for i in range(0, len(body), 4)]
    return words


def record_bytes(record: list[int]) -> bytes:
    """Bytes del record en el stream: cada word MSB-first, concatenadas."""
    return b"".join((w & 0xFFFFFFFF).to_bytes(4, "big") for w in record)
