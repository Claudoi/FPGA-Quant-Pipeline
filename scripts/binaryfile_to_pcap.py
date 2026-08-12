#!/usr/bin/env python3
"""binaryfile_to_pcap.py — BinaryFILE de Nasdaq -> pcap MoldUDP64/UDP/IP/Ethernet.

Los ficheros de muestra de emi.nasdaq.com son BinaryFILE (length u16be +
payload), no pcap. Este script los envuelve en datagramas MoldUDP64 reales
para alimentar los testbenches RTL (spec fase0, criterio 8):

- Empaqueta mensajes hasta ~1400 B de payload UDP (como el feed real);
  `--msgs-per-packet 1` para tests dirigidos.
- Sequence numbers sinteticos monotonicos desde 1 (el BinaryFILE no los
  trae: los gaps se prueban con secuencias fabricadas, no con este replay).
- Checksum UDP = 0 (valido en IPv4; el feed real se valida aguas arriba —
  decision avalada por el documento maestro).
- Timestamp de paquete pcap: derivado del timestamp ITCH (ns desde
  medianoche, offset fijo 5..11 en todo mensaje 5.0) del primer mensaje del
  paquete; solo cosmetica Wireshark, el RTL no lo consume.

No depende de golden_model: el framing BinaryFILE y el de mensajes
MoldUDP64 son el mismo (length + payload), asi que el round-trip es byte a
byte por construccion (PCA-04).
"""
from __future__ import annotations

import argparse
import socket
import struct
import sys
from os import PathLike
from typing import BinaryIO, Iterator

MOLD_HEADER = struct.Struct(">10sQH")  # session, sequence number, message count
PCAP_GLOBAL = struct.Struct("<IHHIIII")
PCAP_RECORD = struct.Struct("<IIII")

DEFAULT_MAX_PAYLOAD = 1400
DEFAULT_SESSION = b"SIM0000001"
DEFAULT_DST_IP = "233.54.12.111"
DEFAULT_SRC_IP = "192.168.1.1"
DEFAULT_DST_PORT = 26433
DEFAULT_SRC_PORT = 12345


class OversizedMessageError(ValueError):
    """Mensaje ITCH mayor que el payload UDP maximo."""


def _ip_checksum(header: bytes) -> int:
    if len(header) % 2:
        header += b"\x00"
    total = sum(
        (header[i] << 8) | header[i + 1] for i in range(0, len(header), 2)
    )
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return ~total & 0xFFFF


def _multicast_mac(ip: str) -> bytes:
    parts = [int(p) for p in ip.split(".")]
    return bytes([0x01, 0x00, 0x5E, parts[1] & 0x7F, parts[2], parts[3]])


def _udp_packet(src_ip: str, dst_ip: str, src_port: int, dst_port: int, payload: bytes) -> bytes:
    src = socket.inet_aton(src_ip)
    dst = socket.inet_aton(dst_ip)
    udp_len = 8 + len(payload)
    total_len = 20 + udp_len
    ip_wo_sum = struct.pack(
        ">BBHHHBBH4s4s",
        0x45, 0, total_len, 0, 0x4000, 64, 17, 0, src, dst,
    )
    ip = ip_wo_sum[:10] + struct.pack(">H", _ip_checksum(ip_wo_sum)) + ip_wo_sum[12:]
    udp = struct.pack(">HHHH", src_port, dst_port, udp_len, 0)
    return ip + udp + payload


def _ethernet_frame(dst_ip: str, ip_packet: bytes) -> bytes:
    src_mac = bytes([0x02, 0x00, 0x00, 0x00, 0x00, 0x01])  # locally administered
    return _multicast_mac(dst_ip) + src_mac + b"\x08\x00" + ip_packet


def _iter_binaryfile(f: BinaryIO) -> Iterator[bytes]:
    while True:
        prefix = f.read(2)
        if not prefix:
            return
        if len(prefix) < 2:
            raise ValueError("prefijo de longitud truncado en BinaryFILE")
        declared = int.from_bytes(prefix, "big")
        payload = f.read(declared)
        if len(payload) < declared:
            raise ValueError("mensaje truncado en BinaryFILE")
        yield payload


def convert(
    src: str | PathLike[str],
    dst: str | PathLike[str],
    *,
    max_payload: int = DEFAULT_MAX_PAYLOAD,
    msgs_per_packet: int | None = None,
    session: bytes = DEFAULT_SESSION,
    src_ip: str = DEFAULT_SRC_IP,
    dst_ip: str = DEFAULT_DST_IP,
    src_port: int = DEFAULT_SRC_PORT,
    dst_port: int = DEFAULT_DST_PORT,
) -> dict[str, int]:
    """Convierte un BinaryFILE en pcap; devuelve estadisticas de la conversion."""
    if len(session) != 10:
        raise ValueError("la sesion MoldUDP64 son exactamente 10 bytes")
    stats = {"messages": 0, "packets": 0, "bytes": 0}
    seq = 1
    with open(src, "rb") as fin, open(dst, "wb") as fout:
        fout.write(PCAP_GLOBAL.pack(0xA1B2C3D4, 2, 4, 0, 0, 65535, 1))
        group: list[bytes] = []
        group_len = 0

        def flush() -> None:
            nonlocal seq
            if not group:
                return
            payload = MOLD_HEADER.pack(session, seq, len(group)) + b"".join(
                len(m).to_bytes(2, "big") + m for m in group
            )
            frame = _ethernet_frame(dst_ip, _udp_packet(src_ip, dst_ip, src_port, dst_port, payload))
            # ts del paquete: del primer mensaje (ns desde medianoche)
            ts_ns = int.from_bytes(group[0][5:11], "big")
            fout.write(PCAP_RECORD.pack(ts_ns // 1_000_000_000, (ts_ns % 1_000_000_000) // 1000, len(frame), len(frame)))
            fout.write(frame)
            stats["packets"] += 1
            stats["bytes"] += len(frame)
            seq += len(group)
            group.clear()

        for idx, payload in enumerate(_iter_binaryfile(fin)):
            if len(payload) + 2 > max_payload:
                raise OversizedMessageError(
                    f"mensaje {idx}: {len(payload) + 2} B con length prefix > "
                    f"payload maximo {max_payload} B"
                )
            framed = len(payload) + 2
            over_size = group_len + MOLD_HEADER.size + framed > max_payload
            over_count = msgs_per_packet is not None and len(group) >= msgs_per_packet
            if group and (over_size or over_count):
                flush()
                group_len = 0
            group.append(payload)
            group_len += framed
            stats["messages"] += 1
        flush()
    return stats


def iter_pcap_packets(src: str | PathLike[str]) -> Iterator[tuple[int, list[bytes], bytes]]:
    """Itera un pcap generado: (sequence_number, [payloads ITCH], payload UDP crudo)."""
    with open(src, "rb") as f:
        magic = f.read(4)
        if magic != PCAP_GLOBAL.pack(0xA1B2C3D4, 0, 0, 0, 0, 0, 0)[:4]:
            raise ValueError("no es un pcap little-endian")
        f.read(20)  # resto de la cabecera global
        while True:
            rec = f.read(16)
            if not rec:
                return
            _ts_sec, _ts_usec, incl, _orig = PCAP_RECORD.unpack(rec)
            frame = f.read(incl)
            if len(frame) < incl:
                raise ValueError("paquete pcap truncado")
            udp = frame[14 + 20:]  # Ethernet + IPv4 sin opciones
            payload = udp[8:]
            session, seq, count = MOLD_HEADER.unpack(payload[: MOLD_HEADER.size])
            msgs: list[bytes] = []
            off = MOLD_HEADER.size
            for _ in range(count):
                mlen = int.from_bytes(payload[off : off + 2], "big")
                msgs.append(payload[off + 2 : off + 2 + mlen])
                off += 2 + mlen
            yield seq, msgs, payload


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("src", help="BinaryFILE de entrada (descomprimido)")
    ap.add_argument("dst", help="pcap de salida")
    ap.add_argument("--max-payload", type=int, default=DEFAULT_MAX_PAYLOAD)
    ap.add_argument("--msgs-per-packet", type=int, default=None)
    ap.add_argument("--dst-ip", default=DEFAULT_DST_IP)
    ap.add_argument("--dst-port", type=int, default=DEFAULT_DST_PORT)
    ap.add_argument("--src-ip", default=DEFAULT_SRC_IP)
    ap.add_argument("--src-port", type=int, default=DEFAULT_SRC_PORT)
    ap.add_argument("--session", default=DEFAULT_SESSION.decode())
    args = ap.parse_args(argv)
    stats = convert(
        args.src, args.dst,
        max_payload=args.max_payload,
        msgs_per_packet=args.msgs_per_packet,
        session=args.session.encode(),
        src_ip=args.src_ip, dst_ip=args.dst_ip,
        src_port=args.src_port, dst_port=args.dst_port,
    )
    print(f"paquetes={stats['packets']} mensajes={stats['messages']} bytes={stats['bytes']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
