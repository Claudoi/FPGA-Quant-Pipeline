# fase4-mdp3-parser (phase 4 of the master plan — Stretch: port to CME MDP 3.0)

## Goal

Port the ITCH pipeline parser to **CME MDP 3.0** (SBE — Simple Binary Encoding):
an RTL parser that decodes the MDP 3.0 packet (Binary Packet Header + SBE
messages with their framing) and emits normalized records ("Annex M") for the
subset of book templates (incremental book + snapshot), with **raw passthrough**
of the remaining templates, verified **bit-exact against a Python golden model
generated from the official CME XML schema**.

The master fixes it as the final chapter: *"porting your ITCH pipeline to MDP3
(even if only the SBE parser verified with synthetic packets generated from the
XML schemas) demonstrates design generality and protocol knowledge of the
largest futures market in the world"*.

## Scope

**In scope:**

- **MDP3 golden model** (`golden_model/mdp3/`): loader of the SBE XML schema
  (templates, fields with offsets, repeating groups, composite types), decoder
  (packet → messages → Annex-M records), generator (valid synthetic SBE corpus)
  and vectors.
- **Schema fetch**: `scripts/fetch_mdp3_schema.py` (CME FTP over HTTPS, with
  **fallback to the official archive via the Wayback Machine** and a pinned md5
  fail-closed, because cmegroup.com answers 403 to the bot) → `data/mdp3/`
  (gitignored, rule G0: schemas are spec, not market data, but are kept out of
  the repo anyway). Pinned schema: `templates_FixBinary_v12.xml` (2021-03-10,
  id=1 version=12, byteOrder=littleEndian), md5 in the script itself.
- **RTL `rtl/parser/mdp3_parser.sv`** (its own module): decodes the packet
  (MsgSeqNum u32 + SendingTime u64, 12 B), the per-message framing (MessageSize
  u16 + 8 B SBE header: blockLength/templateId/schemaId/version) and the subset
  of templates; emits Annex M on AXI-Stream. Parameterized DW (32 target @
  322.265625 MHz; 64 in regression).
- **Per-channel sequence gaps**: MsgSeqNum contiguity (one channel per instance)
  → `gap_detected` (same semantics as MoldUDP64 in phase 1).
- **Verification**: cocotb vs golden bit-exact (synthetic corpus + invariants) +
  mutation of the MDP3 parser + phases 1–3 regression.

**Out of scope (non-goals):**

- Porting the order book to MDP3 (campaign 4b later; Annex M is designed to feed
  it).
- A/B feed arbitration, TCP recovery, multi-channel demux (config.xml): one
  instance = one channel.
- Field-by-field decoding of non-book templates (statistics, trades, instrument
  definitions, security status): raw passthrough with their template_id
  (transparent routing).
- Real DataMine data (paid): the corpus is synthetic, generated from the schema.
  If pcaps are ever paid for, the same bank is re-fed (optional REPLAY-03, not
  blocking).
- iLink 3 (SBE of client orders): market data only.

**Historical radius of the original build (2026-08-14):** `mdp3_parser.sv` was
added without connecting or modifying the ITCH chain. The framing campaign
reopened in 2026-08-15 widens the radius to `itch_parser`, `itch_chain`, their
input testbenches, the XDC and `synth_check.py`; the `orderbook` and the
normalized parser→book link remain unchanged.

**Changelog 2026-08-14 (build edit with evidence):** the official schema
`templates_FixBinary_v12.xml` (archived from cmegroup.com via Wayback, md5
verified) corrects the contract: **little-endian byte-order** (the spec said
big-endian), **subset IDs 46/47/52/53** (the spec expected the pre-event-era
27/30/32), **msg_size includes the 10 B prefix** (evidence roq-cme `parser.cpp`),
and **two group dimensionTypes** (`groupSize` 3 B / `groupSize8Byte` 8 B). Annex
M gains the MBOFD record (18 words) with `record_type` in w7[23] and the per-
template derivation table. Criteria 1–9 and the Gherkin did not change in that
iteration. Later reopenings are reflected in the current Definition of Done of
this document.

## Constraints

- **Target family/part:** UltraScale+ (same family as phases 1–3); frequency
  322.265625 MHz (DW=32) and 156.25 MHz (DW=64) — same regime.
- **Input regime:** the datapath presents one word per cycle and only counts
  backpressure when `s_axis_tvalid && !s_axis_tready`. The agreed vector
  M3-FRM-03 is 24 literal template-47 messages, each with one entry (64 B derived
  from the XML); the maximum admitted stall run is 16 cycles. No infinite
  stall-free feed is promised: an Annex-M MBOFD record expands 64 B of message to
  72 B of output.
- **Schema = single source:** offsets, blockLength, composite types and
  enumeration values are derived from the XML schema in the golden. The
  specialized RTL may materialize them as `localparam` only if the checker
  compares them automatically against the pinned XML; the tests maintain no
  second manual offset table.
- **SBE:** little-endian (byteOrder of the official CME XML; confirmed by the
  roq-cme reference implementation, `little_endian_to_host`); 8 B message header;
  groups with two dimension forms — `groupSize` = blockLength u16 + numInGroup u8
  (3 B) and `groupSize8Byte` = blockLength u16 + 5 B pad + numInGroup u8 (8 B,
  used by NoOrderIDEntries). The RTL consumes `msg_size` without re-deriving
  alignment (offsets live in the XML and the golden respects them as-is).
- **Determinism:** same stream → same Annex-M sequence, bit-exact; no loss or
  double-count, with and without output backpressure.
- **Valid AXI bytes:** the input includes `s_axis_tkeep[DW/8-1:0]` with the
  standard bit↔lane association and masks restricted to full word or a contiguous
  MSB prefix. Lanes with `tkeep=0` do not count for `msg_size`. Masks with holes,
  zero or partial without `tlast` pulse `error` and discard the packet, draining
  it to `tlast` if the invalid beat was not final. Full contract:
  `docs/decisions/003-axis-tkeep-framing.md`.
- **Confirmed framing:** packet = MsgSeqNum(u32) + SendingTime(u64, ns from
  epoch) = 12 B; each message = **MessageSize(u16) that INCLUDES the 10 B
  prefix** (MessageSize + 8 B SBE header: blockLength/templateId/schemaId/
  version) + body (blockLength + groups). Several messages per packet. The
  message header and group dimensions live in the XML (`messageHeader`,
  `groupSize`, `groupSize8Byte`).

## Surface and threats

**Ports of `mdp3_parser`** (phase-1 AXI-Stream convention):

| Signal | Width | Description |
|---|---|---|
| `clk`, `rst_n` | 1 | datapath clock |
| `s_axis_tdata/tkeep/tvalid/tready/tlast` | DW/(DW/8)/1/1/1 | stripped UDP payload; `tkeep` marks the beat's valid bytes |
| `m_axis_tdata/tvalid/tready/tlast` | 32/1/1/1 | Annex-M 32-bit words; DW only parameterizes the input |
| `gap_detected` | 1 | pulse: MsgSeqNum != exp_seq (per channel) |
| `error` | 1 | pulse: incoherent message/packet (msg_size < 10, packet overflow) |

**Annex M** (normalized record per message; one record per ENTRY for book
templates; MSB-first per word layout, DW=32). Two record types, distinguished by
`record_type` in w7[23]: **MBP** (13 words) and **MBOFD** (18 words); each
record's burst ends with `tlast` and the consumer knows the length by the type
itself.

Record **MBP** (46 NoMDEntries, 52 NoMDEntries):

| Word | Content (decoded subset) |
|---|---|
| w0 | `{template_id[15:0], msg_size[15:0]}` |
| w1 | `{schema_id[15:0], version[15:0]}` |
| w2, w3 | `transact_time[63:0]` (u64 ns) |
| w4 | `{match_event_indicator[7:0], 24'b0}` |
| w5 | `security_id[31:0]` |
| w6 | `rpt_seq[31:0]` |
| w7 | `{record_type[7:0]=0, md_update_action[7:0], md_entry_type[7:0], 16'b0}` |
| w8, w9 | `md_entry_px.mantissa[63:0]` (i64) |
| w10 | `{md_entry_px.exponent[7:0], 24'b0}` (i8) |
| w11 | `md_entry_size[31:0]` (i32) |
| w12 | `{num_orders[15:0], md_price_level[15:0]}` |

Record **MBOFD** (46 NoOrderIDEntries, 47 NoMDEntries, 53 NoMDEntries):

| Word | Content |
|---|---|
| w0–w6 | same as MBP (same semantics; the per-template derivation fixes which field feeds each word) |
| w7 | `{record_type[7:0]=1, action[7:0], md_entry_type[7:0], 16'b0}` (action: 279 in 47, 37708 in 46) |
| w8, w9 | `order_id[63:0]` (u64) |
| w10, w11 | `md_order_priority[63:0]` (u64NULL) |
| w12 | `{reference_id[7:0], 24'b0}` (9633; 0 if not applicable) |
| w13, w14 | `md_entry_px.mantissa[63:0]` (i64) |
| w15 | `{md_entry_px.exponent[7:0], 24'b0}` (i8; PRICE9 ⇒ −9 constant) |
| w16 | `md_display_qty[31:0]` (i32) |
| w17 | `32'b0` (reserved) |

Passthrough (remaining templates): `w0, w1` + raw body byte by byte (0 padding
at the end), without decoding. The burst ends with `tlast` (phase-1 convention);
subset fields absent from a concrete template → 0 (the derivation table is the
authority).

**Decoded subset** (the numeric IDs derive from the schema; the pinned schema is
`templates_FixBinary_v12.xml`, 2021-03-10, which no longer uses the pre-event
27/30/32 IDs):

- **46 = MDIncrementalRefreshBook** (X, combined MBP+MBOFD): root blockLength=11
  (TransactTime 60, MatchEventIndicator 5799); group **NoMDEntries** (268,
  blockLength=32, MBP) with per entry: MDEntryPx (270, PRICENULL9 = i64 mantissa
  + i8 exponent), MDEntrySize (271), SecurityID (48), RptSeq (83),
  NumberOfOrders (346), MDPriceLevel (1023), MDUpdateAction (279), MDEntryType
  (269), TradeableSize (37719); group **NoOrderIDEntries** (37705, blockLength=24,
  `groupSize8Byte`, MBOFD) with per entry: OrderID (37), MDOrderPriority (37707),
  MDDisplayQty (37706), ReferenceID (9633 → index of the MBP entry of the same
  message), OrderUpdateAction (37708).
- **47 = MDIncrementalRefreshOrderBook** (X, MBOFD only): root 11; group
  NoMDEntries (268, blockLength=40) with per entry: OrderID (37 u64NULL),
  MDOrderPriority (37707), MDEntryPx (270 PRICENULL9), MDDisplayQty (37706),
  SecurityID (48), MDUpdateAction (279), MDEntryType (269).
- **52 = SnapshotFullRefresh** (W, MBP): root blockLength=59 (includes
  LastMsgSeqNumProcessed 369, TotNumReports 911, SecurityID 48, RptSeq 83,
  TransactTime 60, limits 1149/1148/1143); group NoMDEntries (268, blockLength=22,
  MBP) without MDUpdateAction nor SecurityID/RptSeq per entry (they live in the
  root) and generic MDEntryType (269).
- **53 = SnapshotFullRefreshOrderBook** (W, MBOFD): root 28 (includes SecurityID
  48, NoChunks 37709, CurrentChunk 37710, TransactTime 60); group NoMDEntries
  (268, blockLength=29) with per entry: OrderID (37 u64), MDOrderPriority (37707),
  MDEntryPx (270 PRICE9 = i64 mantissa, exponent constant −9), MDDisplayQty
  (37706 Int32), MDEntryType (269). No action (snapshot).
- The rest (admin 4/12/15/16, SecurityStatus 30, Volume 37, QuoteRequest 39,
  TradeSummary 48, statistics 49–51, instrument definitions 54–58, etc.):
  passthrough.

**Annex-M derivation per template** (which field feeds each word; the golden and
the RTL apply it, and bit-exact verification checks it):

| Template | record_type (w7[23]) | w5 security_id | w6 rpt_seq | w7 action | px (w8–w10) | w11 size | w12 {num_orders, price_level} | w8–w9/w10–w11/w12/w16 (MBOFD) |
|---|---|---|---|---|---|---|---|---|
| 46 MBP | 0 | 48 entry | 83 entry | 279 entry | 270 entry | 271 entry | {346, 1023} | — |
| 46 MBOFD | 1 | 48 of the linked MBP (ReferenceID) | 83 of the linked MBP | 37708 entry | 270 of the linked MBP | — (w16 = 37706 display_qty) | — | order_id 37, priority 37707, reference 9633 |
| 47 | 1 | 48 entry | 0 (absent) | 279 entry | 270 entry | — (w16 = 37706) | — | order_id 37, priority 37707, reference 0 |
| 52 | 0 | 48 root | 83 root | 0 (no action) | 270 entry | 271 entry | {346, 1023} | — |
| 53 | 1 | 48 root | 0 (absent) | 0 (no action) | 270 entry (PRICE9, exponent −9 const) | — (w16 = 37706) | — | order_id 37, priority 37707, reference 0 |

**Domain abuse cases** (each with a `SEC-`/`INV-` scenario):

- **Minimum message back-to-back** (packet full of minimum messages) → worst-case
  line rate. — M3-FRM-03.
- **Message crossing word boundaries** → correct alignment. If it crosses `tlast`,
  the datagram is truncated: the incomplete message is cancelled, never resumed
  with the next packet's bytes. — M3-FRM-02, M3-INV-02.
- **Sub-word truncation**: between 1 and `DW/8-1` bytes missing before `tlast`;
  invalid lanes cannot complete `msg_size`. — M3-INV-02.
- **Invalid `tkeep`**: mask with holes, zero, or partial without `tlast` →
  `error`, discard and recovery. — M3-INV-04.
- **Exact packet closure**: 12 bytes with no messages are valid; a residual byte
  that does not complete `msg_size` is truncated and does not block. — M3-FRM-04.
- **Sequence gap** (MsgSeqNum jumps) → `gap_detected` without abort; new channel
  (seq reset) → expected reset. — M3-GAP-01.
- **Incoherent `msg_size`** (smaller than the SBE header or overflows the packet)
  → `error`, never a hang nor silent corruption. — M3-INV-01.
- **Malformed entry within the message** (group with numInGroup 0 or size that
  exceeds `msg_size`) → `error`/anomaly, no truncation. — M3-INV-03.
- **Unknown templates** (schemaId/version outside the subset) → raw passthrough,
  never abort. — M3-PASS-01.

**What is at risk from the master:** the **design generality** (an ITCH pipeline
that does not port to another exchange = suspect), the **verification without
real data** (the schema-driven synthetic corpus is the honest substitute for
DataMine) and the **line rate** of the parameterized datapath.

## Reuse

- `rtl/parser/itch_parser.sv` and `rtl/itch_chain.sv` — receive and propagate
  `s_axis_tkeep` by the common framing campaign; their normalized output and the
  link to the order book do not change.
- `golden_model/itch/messages.py` — "single source of offsets" pattern; the MDP3
  equivalent is the XML schema (nothing by hand).
- Phases 1–3 testbenches: AXI-Stream driver helpers (`_reset`, word driving,
  pulse sampling). The `payload→beats` constructor is shared among the ITCH
  areas; MDP3 may keep a local helper, but must apply and monitor literally the
  same `data/keep/last` contract.
- `scripts/fetch_itch.py` — fail-closed-with-md5 pattern for `fetch_mdp3_schema.py`.
- The specialized structural RTL `localparam`s must match the pinned schema via
  checker; an additional manual table in tests or golden is FAIL of the `/grade`
  lens 6.

## Acceptance criteria (Definition of Done)

1. [ ] **MDP3 golden**: XML-schema loader + bit-exact decoder + synthetic
     generator with `decode(encode(m)) == m` round-trip for the subset and
     passthrough; mirror Python tests. The round-trip must start from known
     vectors with non-zero values and demonstrate field-by-field preservation of
     root, composites — including `PRICE9.mantissa` — and multi-entry groups; the
     byte equality after re-encoding one's own decode is not enough as an oracle.
     The loader also keeps `schemaId=1` and `version=12`, and the encoder uses
     them by default from the pinned XML.
     — Gherkin: `mdp3.feature` §M3-GEN-01, §M3-GEN-02, §M3-GEN-03
2. [ ] **Framing**: packet (12 B) + messages (u16 size + SBE header) → Annex-M
     sequence bit-exact vs golden; messages crossing word boundaries; an
     independent AXI burst per payload with correct `tkeep`. A header-only packet
     is a valid empty and any incomplete residual before `tlast` is rejected
     without blocking. — §M3-FRM-01/02/04
3. [ ] **Input regime**: 24 literal template-47 messages, one entry and 64 B
     each, presented at 1 word/cycle; real stalls (`tvalid && !tready`) with max
     run ≤ 16. During each stall `(s_axis_tdata, s_axis_tkeep, s_axis_tlast)` stay
     stable until handshake. — §M3-FRM-03, §M3-BP-02
4. [x] **Decoded subset**: book records (46/47/52/53) bit-exact vs golden,
     including the composite price (mantissa+exponent) and multi-entry groups. —
     §M3-SUB-01, §M3-SUB-02
5. [ ] **Passthrough**: non-subset templates → w0/w1 + raw body bit-exact; a
     46/47/52/53 template with unsupported schemaId/version is also passthrough,
     not specialized decode. The maximum supported in this implementation is
     `msg_size <= 256` bytes, inclusive; 257 or more pulses `error`, emits no
     partial record, drains the packet and recovers in the next. — §M3-PASS-01,
     §M3-PASS-02
6. [x] **Sequence gaps**: `gap_detected` on jumps; reset on channel change
     (sequence restarted). — §M3-GAP-01
7. [ ] **Robustness**: incoherent `msg_size` and malformed groups → signalled
     `error`, no hang nor silent corruption; truncated input `tlast` (including
     1..`DW/8-1` missing bytes) and invalid `tkeep` masks handled. —
     §M3-INV-01/02/03/04
8. [ ] **Regression**: phases 1–3 green after propagating `tkeep` through the
     `itch_chain` input; DW=64 of the mdp3_parser in regression. — §M3-REG-01
9. [ ] Lint `--Wall` clean over `mdp3_parser.sv` (+ verible if installed); XML↔
     localparams checker for subset IDs, offsets and blockLength; 1:1 Gherkin
     mirrors. — §M3-SCH-01, gates B/C/F.
10. [ ] **Output backpressure**: with `m_axis_tvalid && !m_axis_tready`,
     `m_axis_tdata`, `m_axis_tvalid` and `m_axis_tlast` stay stable; on release
     no loss or duplication. — §M3-BP-01

## Verification

| Criterion | How it is tested |
|---|---|
| 1 | `python3 -m unittest` (MDP3 golden area, mirrors) + round-trip + schemaId/version literals from XML |
| 2 | cocotb `testbenches/mdp3`: synthetic corpus → Annex M bit-exact vs golden; split-message words, header-only/residual and one burst per packet |
| 3 | cocotb: 24 literal template-47 messages of 64 B; measure `tvalid && !tready`, run ≤ 16 and stable input tuple at DW=32/64 |
| 4 | cocotb: 46/47/52/53 records vs golden; composite price and multi-entry |
| 5 | cocotb: non-subset templates; 46/47/52/53 with incompatible schema/version; 256 B passthrough and 257 B rejection+recovery |
| 6 | cocotb: sequence with jump and channel restart → correct gap pulses |
| 7 | cocotb: invalid `msg_size`, numInGroup 0, truncation by 1..`DW/8-1` bytes and invalid `tkeep` with recovery |
| 8 | `make sim` in `testbenches/{parser,orderbook,phase3}` with the propagated `tkeep` contract |
| 9 | `verilator --lint-only -Wall` + version-12↔RTL schema checker + `specs/gherkin-espejos.json` |
| 10 | cocotb: adaptive output stall, stable output tuple and complete sequence on release |

Full regime: skill `verify` (gates A–G). Gate E: new mutation runner
`scripts/verify/mutate_mdp3.py` (flips: template lookup off-by-one, msg_size
unchecked against packet, seq uncompared, group with miscounted numInGroup,
passthrough without bytes, price with mantissa/exponent swapped). Gate F:
`mdp3.feature` ↔ `verification/testbenches/mdp3` mirrors. Gate G: G0 (schema and
synthetic corpus in vectors/derived; never real market data).

**Geless contracts** — invariants that can break with suite and lint green:

1. **Meaning of `msg_size`** (does it include the 8 B SBE header or only the
   body?): **resolved by evidence** — roq-cme `parser.cpp`:
   `length = message_size.length - (2 + MessageHeader::encodedLength())` ⇒
   msg_size includes the 10 B prefix. M3-GEN-01 pinches it with the semantic
   round-trip of known vectors and the expected literal size.
2. **8 B root alignment**: the RTL consumes `msg_size` and does not re-derive the
   alignment (does not care); the golden applies it when generating (the book
   template blockLengths come from the XML: 11/11/59/28). If the golden applied
   it wrong, the bit-exact against its own decoder would not notice → M3-GEN-02
   pinches the layout with expected sizes from the XML.
3. **Nested / double groups**: template 46 carries TWO decoded groups (NoMDEntries
   MBP and NoOrderIDEntries MBOFD with dimensionType `groupSize8Byte`, 8 B); the
   other templates' groups (passthrough var-data, e.g. instrument definitions)
   are not decoded (raw) → the risk is only the golden's, which must respect the
   XML dimensionTypes.
4. **Multi-entry → multi-record**: the decision to emit one record per entry (not
   one per message) is contract; if book 4b expected otherwise, it changes here,
   not in the RTL.
5. **46 cross-reference** (ReferenceID → MBP entry of the same message): the px/
   security/rpt_seq of the 46 MBOFD record are resolved by index within the
   message; out of range ⇒ `error` (anomaly, not corruption).

## Loop

**Historical:** the initial build had a stop limit of 4 iterations: iter 1 (MDP3
golden: loader+decoder+generator, Python mirrors) → iter 2 (RTL framing + bit-
exact Annex M, line rate) → iter 3 (subset + passthrough + gaps + robustness +
regression) → iter 4 (mutation, gates, grade). The reopened criteria are now
resolved in independent framing, schema/passthrough, backpressure and synthesis
loops; no historical output closes them by inertia.

### Addendum framing tkeep (2026-08-18, amended after green) — loop contract

The phase-4 `s_axis_tkeep` framing is **implemented and green in WSL
(2026-08-18)**: RTL port `mdp3_parser` (commit `62e4e46`), suite DW=32 **9/9**
and DW=64 **9/9**, clean gate B and gate E 9/9 (including the mutant
`TKCNT-ALWAYS`) — evidence in the verify-report. The loop contract, already
closed by its criteria 2 and 8 in their tkeep arm:

1. **Port contract:** input `s_axis_tkeep[DW/8-1:0]`, MSB-contiguous mask per
   beat (the valid lanes are the high bytes of the word). The queue append
   (`qbytes`/`qw`) counts only the lanes with `tkeep=1`; a lane with `tkeep=0`
   never contributes bytes nor completes a declared length (same mechanic as the
   common phases 1-3 contract). Implementation: `tk_cnt = popcount(tkeep)`,
   `qavail_eff` and the tready use `tk_cnt`; the append only writes `k < tk_cnt`;
   a beat with `tkeep=0` is consumed without contributing and without stalling.
   `tlast` closes the packet burst as today; the last partial beat is the
   truncated one: if the declared length of a message falls on `tkeep=0` lanes,
   `error` is signalled and the next packet recovers intact.
2. **Closure (done):** red→green of M3-FRM-05 (a) nominal framing, (b) mask-
   truncation → `error` + recovery, (c) empty beat mid-burst → no stall. Fixed
   test (b): the last-beat mask derives from `nv` (real bytes of the nominal
   mask), not from `DW/8` — at DW=64 the last packet beat is usually partial and
   declaring `DW/8-1` valid lanes added the padding zeros, falsely completing the
   declared length.
3. **Regression (done):** the full mdp3-area suite DW=32 and DW=64 green
   (M3-FRM-01..03, M3-SUB-01/02, M3-PASS-01, M3-GAP-01, M3-INV-01/02/03,
   M3-FRM-05) without regression of the common contract.
4. **Statement:** criteria 2 and 8 (in their tkeep arm) of this campaign are
   updated in the verify-report **only** with the area's real outputs (gate A)
   and the gate E of the tkeep mutant; they remain **open** (separate loops):
   criterion 5 (schema/version, MAX_MSG 256/257), the remaining criterion 7
   (masks with holes, separate loop), criterion 10 (output backpressure) and the
   timing (no Vivado MDP3).

## Addendum criterion 5 (2026-08-19) — passthrough by schema/version + MAX_MSG

Criterion 5 demands two things that today the M3-PASS-01 test does not cover
(which only tests a normal template and an unknown one):

1. **A subset template (46/47/52/53) with unsupported `schema_id` or `version`
   is passthrough, NOT decode.** The decodable book subset is: `template_id in
   {46,47,52,53} AND schema_id == SCHEMA_ID AND version == SCHEMA_VERSION`, with
   `SCHEMA_ID = 1` and `SCHEMA_VERSION = 12` (pinned schema
   `templates_FixBinary_v12.xml`, `id=1 version=12`). Any other SBE-header
   combination emits w0/w1 + raw body padded (same `passthrough_record` as an
   unknown template). It is an oracle+ change: the golden
   `decode_message`/`anexo_m_records` must decide the subset with these three
   conditions, and the RTL (`DS_HDR`) must gate the decode with `d_sid==1 &&
   d_ver==12`. LE SBE-header contract: `block_length(t2)`, `template_id(t2)`,
   `schema_id(t2)`, `version(t2)`.
2. **Message-size limit `MAX_MSG = 256` bytes, inclusive; 257 or more pulses
   `error`, emits no partial record, drains the packet and recovers the next.**
   `MAX_MSG=256` and the `msg_size` validation already exist, but the test must
   prove explicitly 256 B (accepted) and 257 B (rejection + recovery).

Tests:
- `M3-PASS-02` (mirror §M3-PASS-02): a template 47 with `schema_id=2` and one
  46/47/52/53 with correct schema_id but `version=13` go to passthrough; their
  records are `passthrough_record` (not the decoded Annex M).
- `M3-SIZE-01`/`M3-SIZE-02`: a message of exactly 256 B is accepted and decoded;
  one of 257 B pulses `error`, no partial record, and the next intact packet
  recovers bit-exact.

Golden rule: `decode_message` returns `{}` (passthrough) if `template_id not in
SUBSET_TEMPLATES or schema_id != SCHEMA_ID or version != SCHEMA_VERSION`.
`oracle_bytes` uses `passthrough_record` in those cases. The RTL replicates that
gate exactly in `DS_HDR`.

## Addendum criterion 7 (2026-08-19) — tkeep mask validation

Criterion 7 demands that the **invalid masks** of `s_axis_tkeep` pulse `error`
and discard the packet (a loop separate from the 2026-08-18 tkeep framing
addendum, which only restricted to MSB-contiguous masks without validating
them). Contract:

1. **Mask with holes** (not MSB-contiguous, e.g. `0b0101` at DW=32): in any beat
   pulses `error` and discards the current packet, draining it to `tlast` (the
   invalid non-final beat) or accepting the new one immediately (if it carries
   `tlast`).
2. **Partial word without `tlast`**: an MSB-contiguous mask with `nv < DW/8` in a
   NON-final beat (without `tlast`) is invalid framing → `error` and packet
   discard.
3. **Full `tkeep == 0`**: allowed (consumed without contributing, without
   `error`; a valid empty beat of the tkeep framing).
4. MSB-contiguous masks with `tlast` are the nominal case (the partial final beat
   declares only its real bytes).

RTL validation: `tkeep` is MSB-contiguous if there is no `0` between two `1`
(reading MSB→LSB); equivalently `tkeep & (tkeep >> 1)` does not "split" the ones
block — or, computationally, `tkeep` does not have the form `...0...1...` with a
`1` to the right of a `0`. Simple synthesizable implementation: `tkeep` contiguous
⟺ `(tkeep | (tkeep - 1)) == {DW/8{1'b1}}` (the OR with `tkeep-1` fills the
internal holes of the ones block up to the block LSB; if there is a hole, a `0`
remains). A partial without `tlast`: contiguous mask with `tk_cnt < DW/8` and
`!s_axis_tlast`.

Test: `M3-INV-04` (mask with holes → error + recovery; partial without `tlast` →
error). The driver injects `beats_override` with invalid `tkeep` in the middle of
a valid burst.