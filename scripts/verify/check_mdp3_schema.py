#!/usr/bin/env python3
"""check_mdp3_schema.py — schema gate G (CLO-SCH-01, phase 4 criterion 9).

Compares the pinned CME XML (`data/mdp3/templates_FixBinary_v12.xml`,
id=1, version=12, md5 e6eb6c60b46e61dc154537879b3d18d2) against **all**
the structural localparams of `rtl/parser/mdp3_parser.sv`: those already
pinned by `test_m3sch01_*` plus `SCHEMA_ID`, `SCHEMA_VER`, `PKT_HDR`,
`MAX_MSG`, `EXP_BYTE`. Fail-closed if the XML is missing or its md5 does
not match. The existing unittest delegates here (a single table).

Usage:
    python3 scripts/verify/check_mdp3_schema.py
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "data" / "mdp3" / "templates_FixBinary_v12.xml"
RTL_PATH = ROOT / "rtl" / "parser" / "mdp3_parser.sv"
EXPECTED_MD5 = "e6eb6c60b46e61dc154537879b3d18d2"
EXPECTED_ID = 1
EXPECTED_VERSION = 12

sys.path.insert(0, str(ROOT))
from golden_model.mdp3 import load_schema  # noqa: E402


def _md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def expected_localparams(xml: Path = SCHEMA_PATH) -> dict[str, int]:
    """Single table: XML-derived localparams + structural pins."""
    schema = load_schema(xml)
    root = __import__("xml.etree.ElementTree", fromlist=["ET"]).parse(xml).getroot()

    def field_offset(fields, name):
        return next(field.offset for field in fields if field.name == name)

    m46, m47 = schema.messages[46], schema.messages[47]
    m52, m53 = schema.messages[52], schema.messages[53]
    g46_mbp, g46_oid = m46.groups
    g47, g52, g53 = m47.groups[0], m52.groups[0], m53.groups[0]

    expected = {
        "SCHEMA_ID": int(root.attrib["id"]),
        "SCHEMA_VER": int(root.attrib["version"]),
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
    # Structural RTL pins not derivable from the XML (design constants).
    expected.update({
        "PKT_HDR": 12,       # 2 (msg_size u16) + 10 B SBE prefix
        "MAX_MSG": 256,      # bytes per buffer (corpus <= ~250 B)
        "EXP_BYTE": 0xF7,    # PRICE9/PRICENULL9 exponent = -9
    })
    return expected


def rtl_localparams(rtl: Path = RTL_PATH) -> dict[str, int]:
    text = rtl.read_text()
    out = {}
    for m in re.finditer(
        r"\b(SCHEMA_ID|SCHEMA_VER|MSG_PREFIX|PKT_HDR|MAX_MSG|EXP_BYTE|"
        r"TPL_46|TPL_47|TPL_52|TPL_53|"
        r"O46_\w+|O47_\w+|O52_\w+|O53_\w+)\s*=\s*"
        r"(?:(?:\d+)'[dh]([0-9a-fA-F]+)|(\d+))\b",
        text,
    ):
        name = m.group(1)
        if m.group(2) is not None:
            out[name] = int(m.group(2), 16 if "h" in m.group(0) else 10)
        else:
            out[name] = int(m.group(3))
    return out


def check(xml: Path = SCHEMA_PATH, rtl: Path = RTL_PATH) -> tuple[bool, list[str]]:
    """Returns (ok, diff). Fail-closed if the XML is missing or the md5 does not match."""
    if not xml.exists():
        return False, [f"XML missing: {xml} (fail-closed; use scripts/fetch_mdp3_schema.py)"]
    if _md5(xml) != EXPECTED_MD5:
        return False, [f"XML md5 does not match the pin {EXPECTED_MD5}"]

    expected = expected_localparams(xml)
    rtl = rtl_localparams(rtl)
    diff = []
    for name, value in sorted(expected.items()):
        if name not in rtl:
            diff.append(f"missing RTL localparam: {name}")
        elif rtl[name] != value:
            diff.append(f"{name}: RTL={rtl[name]} != XML/pin={value}")
    return (not diff), diff


def main(argv: list[str] | None = None) -> int:
    ok, diff = check()
    if not ok:
        print("FAIL")
        for line in diff:
            print(f"  {line}")
        return 1
    n = len(expected_localparams(SCHEMA_PATH))
    print(f"PASS {n} identical localparams (empty diff): "
          f"XML id=1 version=12 md5 ok + RTL mdp3_parser.sv")
    return 0


if __name__ == "__main__":
    sys.exit(main())