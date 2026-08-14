"""golden_model/mdp3 — modelo dorado del parser CME MDP 3.0 (SBE).

Campaña fase4-mdp3-parser. Fuente única de layout = el schema SBE XML oficial
de CME (templates_FixBinary_v12.xml, byteOrder=littleEndian). Ningún literal
de offset/tag a mano: todo se deriva del XML en runtime (regla del maestro).

El subset de libro = templates 46/47/52/53 (ver spec §Subset decodificado).
"""
from golden_model.mdp3.schema import Schema, load_schema
from golden_model.mdp3.codec import (
    encode_message,
    encode_packet,
    iter_packet_messages,
    decode_message,
    anexo_m_records,
    message_body_bytes,
    passthrough_record,
    record_bytes,
)
from golden_model.mdp3.generator import Corpus

__all__ = [
    "Schema",
    "load_schema",
    "encode_message",
    "iter_packet_messages",
    "decode_message",
    "anexo_m_records",
    "message_body_bytes",
    "Corpus",
]