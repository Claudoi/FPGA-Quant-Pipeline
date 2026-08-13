"""Oráculo de mensajes de fase 1: consumidor del stream del RTL -> registro Anexo A.

El RTL (fase 1) consume el payload MoldUDP64 ya decapado de IP/UDP: una
secuencia de paquetes, cada uno `session(10) + seq(8) + count(2) + [len u16 +
mensaje]*`. Este módulo es el **oráculo**: recorre exactamente ese stream y, por
cada mensaje de los 10 tipos del subset (`S,R,A,F,E,C,X,D,U,P`), emite el
registro normalizado del Anexo A de `specs/fase1-parser-rtl/spec.md`:

    word0 = (msg_type<<56)|(locate<<40)|(length<<32)|(msg_idx)
    word1 = ts_ns
    body  = bytes del mensaje tras la cabecera común ITCH de 11 B (campos del
            wire, big-endian; el mismo struct de golden_model/itch/messages.py)

Comparado byte a byte contra la salida del RTL en cocotb. Los tipos fuera del
subset se validan por longitud y se cuentan, sin emitir registro (idéntico a
la semántica del criterio 6 de fase 1).

Determinismo: mismo stream -> mismos registros. Orden del wire, sin swap.
"""
from __future__ import annotations

from typing import Iterator, Sequence

from ..itch.messages import MESSAGE_LENGTHS

#: tipos del subset de fase 1 (10): S,R,A,F,E,C,X,D,U,P
SUBSET_TYPES = frozenset("SRCFDECXUAP")

#: tipo -> long. total del mensaje (bytes); FOndo para validar longitud.
_FOUND: dict[str, int] = MESSAGE_LENGTHS

#: tuple de registro de mensaje: (word0, word1_ts, body bytes)
MessageRecord = tuple[int, int, bytes]

COMMON_HEADER_LEN = 11


class BadMessageError(ValueError):
    """Mensaje con tipo fuera de la taba, longitud incoherente o truncado."""


def _word0(msg_type: str, locate: int, length: int, msg_idx: int) -> int:
    return (ord(msg_type) << 56) | (locate << 40) | (length << 32) | (msg_idx & 0xFFFFFFFF)


def iter_message_records(
    packets: Sequence[tuple[int, list[bytes], bytes]],
) -> Iterator[MessageRecord]:
    """Recorre el stream de paquetes MoldUDP64 y emite registros Anexo A.

    `packets` sigue el contrato de `binaryfile_to_pcap.iter_pcap_packets`:
    para cada paquete, (seq, [mensajes ITCH], payload crudo). El seq guía el
    conteo global de mensajes; no se requiere el payload crudo para decodificar.
    """
    global_idx = 0
    for _seq, messages, _payload in packets:
        for raw in messages:
            mtype = chr(raw[0])
            declared = len(raw)
            expected = _FOUND.get(mtype)
            if expected is None:
                raise BadMessageError(f"msg {global_idx}: tipo desconocido {mtype!r}")
            if declared != expected[1]:
                raise BadMessageError(
                    f"msg {global_idx}: tipo {mtype!r} declara {declared} B, "
                    f"la spec exige {expected[1]} B"
                )
            if mtype not in SUBSET_TYPES:
                global_idx += 1
                continue
            locate = int.from_bytes(raw[1:3], "big")
            ts_ns = int.from_bytes(raw[5:11], "big")
            w0 = _word0(mtype, locate, declared, global_idx)
            yield w0, ts_ns, raw[COMMON_HEADER_LEN:]
            global_idx += 1