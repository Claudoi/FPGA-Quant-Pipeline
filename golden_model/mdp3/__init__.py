"""golden_model/mdp3 — golden model of the CME MDP 3.0 (SBE) parser.

Phase 4-mdp3-parser campaign. Single layout source = the official CME SBE XML schema
(templates_FixBinary_v12.xml, byteOrder=littleEndian). No offset/tag literal
by hand: everything is derived from the XML at runtime (master rule).

The book subset = templates 46/47/52/53 (see spec §Decoded subset).
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