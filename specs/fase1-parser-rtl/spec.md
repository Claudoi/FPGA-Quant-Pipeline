# fase1-parser-rtl (phase 1 of the master plan)

## Goal

Build the **line-rate** Nasdaq TotalView-ITCH 5.0 RTL parser in SystemVerilog
(Verilator-compatible): it consumes the **MoldUDP64 payload** (IP/UDP stripped
in the testbench), validates framing and sequence, aligns messages that cross
word boundaries — a `tlast` crossing is a truncation and never a continuation —,
decodes the subset types (`S, R, A, F, E, C, X, D, U, P`) and emits on
AXI-Stream a **decoded record per message**, byte-exact against the golden
model's message vectors. It is the stage preceding the order book (phase 2):
its output is the input of the URAM engine.

It does not build a book: it turns a raw stream into `normalized messages +
sequence-gap signalling`, at 1 word/cycle in the worst case, on a 64-bit
datapath @ 156.25 MHz.

## Scope

**In scope:**

- `rtl/parser/` — SystemVerilog modules of the parsing datapath:
  - **MoldUDP64 framing** in the RTL: payload consumption (session u64+u16,
    seq u64, count u16) and **detection/signalling of sequence-number gaps**
    (expected seq = prev_seq + prev_count; gap if seq_actual > expected).
    IP/UDP strip stays in the testbench (see non-goals). — Interview decision
    Q8: gaps DO enter phase 1.
  - **Aligner** (barrel shifter): messages crossing 8 B word boundaries while
    keeping 1 word/cycle. A message never crosses `tlast`: if the datagram ends
    before the declared length, it is cancelled with `error` and is not resumed
    with bytes of the next packet.
  - **Parsing FSM**: identifies `msg_type`, validates declared length, extracts
    fields.
  - **Decoder `S,R,A,F,E,C,X,D,U,P`** → normalized record.
  - Top `itch_parser`.
- `rtl/parser/common/` (or `rtl/common/`) — shared helpers (pipeline registers,
  handshake FIFO) if `rtl/common/` does not already provide them.
- `verification/testbenches/parser/` — cocotb + Verilator testbenches:
  - **Replay of pcaps** generated with `scripts/binaryfile_to_pcap.py`:
    Ethernet/IPv4/UDP strip in the testbench (real packets that DO cross words
    but not datagram boundaries), feeding the MoldUDP64 payload to the RTL.
  - Byte-exact oracle against the golden model's **message vectors**.
  - Frozen vectors committed in `verification/vectors/messages/`.
- **Agreed phase-0 extension** (`golden_model/`): new dump mode
  `--emit-messages` that emits, per modifying/subset message, the decoded
  record (Annex A) — a message oracle, not a BBO. This is an explicit agreed
  edit of the phase-0 spec (does not reopen the campaign).
- Small frozen message vectors committed in `verification/vectors/` (hybrid:
  frozen + per-iteration).

**Out of scope (non-goals):**

- Order book / BBO / URAM: phase 2 (here only normalized messages).
- Ethernet/IPv4/UDP strip **in the RTL**: the testbench does it; the RTL
  receives the MoldUDP64 payload (session+seq+count+messages). (The 10G MAC /
  full IP/UDP strip would be a later phase of its own.)
- A/B feed dedup/arbitration detection (advanced, not ITCH).
- Recovery/GLIMPSE/snapshot.
- 32-bit @ 322 MHz variants (phase 3), Vivado timing closure (phase 3).
- Wire-to-BBO latency metrics (phase 2).
- Consuming the 22 types: only the 10 subset types decode to a record; the
  rest (H, I, B, N, W, O, …) are **validated by length and counted** (inline,
  without breaking line rate), identical to the phase-0 criterion.
- CME MDP3 (stretch phase 4).

**Measured radius (2026-08-12):** `rtl/parser/` and `rtl/orderbook/` are empty
(verified with `find rtl/ -type f`); `rtl/common/` empty of sources. Nothing
existing is renamed or moved. `verification/testbenches/` and
`verification/scripts/` empty of sources.

## Constraints

- **Target family/part:** AMD/Xilinx UltraScale+ (part from the master
  document; fixed in phase-3 synthesis). Datapath **64-bit @ 156.25 MHz** (the
  one delivered by the 10GBASE-R core).
- **Measured line rate, no impossible promise:** the datapath uses full
  AXI-Stream and the agreed test measures four A/U with QB=64, bit-exact output
  and accumulated stalls `<= 24`. The infinite worst case of minimum messages
  is a physical non-goal because Annex A produces more bytes than the wire; this
  is declared in criterion 2 and is not hidden with a FIFO or a zero-stall claim.
- Endianness: ITCH and MoldUDP64 are **big-endian** on the wire; decoded records
  (Annex A) are emitted in **wire-field order** (big-endian), so the RTL does no
  byte-swaps and byte-exact comparison vs. golden is direct. Do not mix.
- Determinism: same input pcap → same output records bit-exact; if a sequence
  gap appears, parsing continues (no abort), is signalled and counted.
- **Valid AXI bytes:** the input includes `s_axis_tkeep[DW/8-1:0]` with standard
  AXI semantics. Every non-final beat has all its lanes valid; the last uses a
  contiguous MSB prefix of ones. Lanes with `tkeep=0` do not enter the queue.
  Masks with holes, `tkeep=0` or a partial word without `tlast` pulse `error`
  and discard the datagram, draining it to `tlast` if the invalid beat was not
  final. Full contract: `docs/decisions/003-axis-tkeep-framing.md`.

## Surface and threats

**New inputs (ports of the top `itch_parser`):**

| Signal | Width | Description |
|---|---|---|
| `clk` | 1 | 156.25 MHz |
| `rst_n` | 1 | active-low reset, synchronous |
| `s_axis_tdata` | 64 | MoldUDP64 payload word (already IP/UDP-stripped) |
| `s_axis_tkeep` | 8 | valid byte per AXI lane; MSB prefix on the final beat |
| `s_axis_tvalid` | 1 | a valid word is present |
| `s_axis_tready` | 1 | the parser accepts the word |
| `s_axis_tlast` | 1 | last word of the UDP payload (end of packet) |

**New outputs:**

| Signal | Width | Description |
|---|---|---|
| `m_axis_tdata` | 64 | decoded message record (Annex A), 1+ words |
| `m_axis_tvalid` | 1 | output data present |
| `m_axis_tready` | 1 | downstream consumes |
| `m_axis_tlast` | 1 | last word of the message record |
| `gap_detected` | 1 | pulse when a seq gap is detected (counted internally) |
| `error` | 1 | malformed frame / incoherent length (fail with signal, without aborting the stream) |

**Decoded output messages (10 types):** `S, R, A, F, E, C, X, D, U, P` — the
literal list that the `/verify` sweep attacks.

**Domain abuse cases** (each with its `SEC-` scenario in Gherkin):

- **MoldUDP64 sequence gap** (`seq_actual > expected`) — SEC-GAP-01.
- **Message crossing an 8 B word boundary** — SEC-ALN-01.
- **Two consecutive unaligned datagrams**: each payload is an independent AXI
  burst and padding never precedes a later header. — SEC-FRM-05.
- **Invalid `tkeep`**: mask with holes, zero, or partial without `tlast` →
  `error`, discard and recover in the next packet. — SEC-FRM-06.
- **`count` does not match physical closure**: extra messages or bytes after
  consuming `count`, or `count=0` with payload, give `error` and are drained to
  `tlast`; never reinterpreted as header. — SEC-FRM-07.
- **Input backpressure**: `(tdata,tkeep,tlast)` stays stable while
  `tvalid && !tready`. — SEC-FRM-08.
- **Message crossing a packet boundary** (tlast in the middle of a message: in
  MoldUDP64 a message is never split between packets, but the RTL must handle
  it firmly: count inconsistent with the last packet) — SEC-FRM-02.
- **Non-decodable type** (outside the subset): validate length, advance the
  global `msg_idx` and emit no record — SEC-PAR-04/05.
- **Incoherent declared length / truncated frame** — SEC-FRM-01, SEC-PAR-03.
- **A/U back-to-back stretch with QB=64** (measured regime) — LIN-01/SEC-LIN-01.
- **Downstream backpressure** (tready low) without data loss — SEC-OUT-02.
- **New-session message** (session changes) → reset of expected seq — SEC-FRM-03.
- **count = 0** in a packet (valid in MoldUDP64) — SEC-FRM-04.
- **Seq replays/duplicates** (seq == expected, no gap): accept — SEC-GAP-02.

**What is at risk from the master:** **deterministic latency and measured
throughput**; a badly designed aligner or a decoder with long combinational
logic breaks the 64-bit @ 156.25 MHz chain. Framing + gaps bring the real feed
handling closer (decision Q8/Q9).

## Reuse

- `golden_model/itch/messages.py` — **single source of ITCH layouts** (no
  protocol literals elsewhere): cocotb and `--emit-messages` use it as oracle.
  If a subset type lacks a full layout, it is added here with a `grep` of its
  struct (agreed phase-0 extension).
- `golden_model/itch/parser.py`, `golden_model/src/vectors.py` — reused by the
  `--emit-messages` mode.
- `scripts/binaryfile_to_pcap.py` — generates replay pcaps (available and
  verified in phase 0, criterion 8).
- `requirements-dev.txt` — cocotb/cocotb-bus/numpy (created in this campaign).
- cocotb-bus dependency: avoided if the handshake is tested by hand (data + 3
  flags/sanitization); added only if agreed here.
- **New code that duplicates** an ITCH layout table = FAIL of the `/grade`
  simplicity lens: everything derives from `messages.py`.

## Acceptance criteria (Definition of Done)

1. [x] The parser consumes the MoldUDP64 payload and emits a **decoded record
   (Annex A) per message of the 10 subset types**, byte-exact against the
   golden model `--emit-messages` (synthetic known-answer, incl. one message of
   each type).
   — Gherkin: `parser.feature` §PAR-01, §SEC-PAR-04; `output.feature` §OUT-01
2. [x] **Line rate (bounded scope):** on a literal four-message A/U
   back-to-back stretch that fits buffered in the queue (QB=64), with the
   downstream consuming, the RTL keeps bit-exact output and accumulates at most
   24 input stall cycles; that stretch is not presented as zero stalls.
   — Gherkin: `datapath.feature` §LIN-01
   — **Spec decision (edit 2026-08-13, iteration 3):** the MINIMUM-message
   worst case (`D` 19 B, `X` 23 B, `S` 12 B) **infinite back-to-back** is
   declared a **physical non-goal** of this campaign. The Annex-A normalized
   record adds 16 B of overhead per message (word0 + word1), so the AXI-Stream
   output always exceeds the input (D: 24 B out per 21 B feed; S: 24/14) and no
   aligner reaches "infinite 1 word/cycle" with a finite queue. It is verified
   with the bounded stretch that fits buffered (stalls `<=24`), and the limit is
   documented (measured ratios and pressure evidence) in section 9 of
   `docs/writeup/lessons-learned.md` as a non-goal derived from Annex A
   (not as an RTL defect). If the infinite case is required in the future, the
   decision is to redesign Annex A (compressed output / wider bus), not to patch
   the parser.
   — Gherkin: `datapath.feature` §LIN-01
3. [x] The aligner correctly decodes any of the 8 alignments of a message
   within the 64-bit word, including messages crossing the word boundary.
   — Gherkin: `datapath.feature` §ALN-01
4. [ ] **MoldUDP64 framing:** session, seq and count parsed; expected seq =
   prev_seq + prev_count; a **gap** is signalled (`gap_detected`), counted and
   parsing continues; seq == expected (no gap) is not signalled; a session
   change resets the expected seq; count=0 is valid. Each payload is presented
   as an independent burst with `tkeep`; two unaligned packets do not share a
   beat nor contaminate headers. `count` must end exactly at `tlast`: any
   residual valid byte or late closure is signalled and drained.
   — Gherkin: `framing.feature` §FRM-01, §FRM-02, §SEC-GAP-01, §SEC-GAP-02,
   §SEC-FRM-03, §SEC-FRM-04, §SEC-FRM-05, §SEC-FRM-06, §SEC-FRM-07
5. [ ] **AXI-Stream with backpressure:** with `tready` intermittently low the
   parser holds the stream without losing or duplicating any record (byte-exact
   oracle); the `tvalid/tready/tlast` sequence respects the handshake and the
   producer keeps `(tdata,tkeep,tlast)` stable during each input stall.
   — Gherkin: `output.feature` §OUT-02, §OUT-03; `framing.feature` §SEC-FRM-08
6. [x] The 22 canonical types of `MESSAGE_LENGTHS`, including those outside the
   subset, are validated by length before continuing. Out-of-subset types are
   counted in the global `msg_idx` and **do not** emit a record nor break line
   rate; a known type with an incorrect length pulses `error` and is discarded.
   No per-type counter bank is added: it was never part of the ports and no
   pipeline consumer uses it.
   — Gherkin: `parser.feature` §SEC-PAR-04
7. [ ] Incoherent length / truncated frame cancel the message with `error`,
   discard the rest of the invalid datagram and continue from the header of the
   next intact packet (without aborting the stream, fail with signal). Bytes
   with `tkeep=0` never complete a declared length.
   — Gherkin: `parser.feature` §SEC-PAR-03, §SEC-FRM-01, §SEC-FRM-02
8. [ ] **Phase-1 real replay (hybrid oracle):** the RTL processes the subset
   message records of a local real-day/replay pcap, and its output is
   byte-exact against the `--emit-messages` oracle over that same pcap, emitting
   one burst and one `tlast` per UDP payload. Additionally, a pair of small
   **frozen vectors** is committed in `verification/vectors/messages/` and
   reproduced by the RTL.
   — Gherkin: `replay.feature` §REP-01, §REP-02
9. [x] **Phase-0 loose ends** (pending decision #2, closed BEFORE the RTL): the
   regression day `01302019` is processed without invariant anomalies and the
   small synthetic vectors are committed. Documented in the phase-0
   verify-report (edit of that report) or in this spec as agreed pre-work.
   — Verification: `run_golden.py` command over the regression day.
10. [ ] Cocotb + Verilator compile the top with `--Wall` with no real warnings
    silenced (per-area documented ratchet, zero silences).
    — Gherkin: static (gate B/C of verify; no scenario).
11. [ ] Lint and style: `verible-verilog-lint` + `verilator --lint-only` green
    over `rtl/parser/`.
    — No scenario (gate B/C).

## Verification

| Criterion | How it is tested |
|---|---|
| 1 | cocotb `test_*` mirror of `parser.feature`/`output.feature` over synthetic vectors (messages.py + `--emit-messages` oracle) |
| 2 | cocotb: four A/U back-to-back with QB=64, bit-exact output and stalls `<=24` with tready=1 |
| 3 | cocotb: sweep of the 8 alignments (ALN-01 scenario with Outline) |
| 4 | cocotb: fabricated sequences (gap, no-gap, session change, count=0), two unaligned datagrams, exact `count↔tlast` and valid/invalid `tkeep` masks |
| 5 | cocotb: random tready/controlled loss, compare output vs oracle and monitor stable `(tdata,tkeep,tlast)` on input stalls |
| 6 | cocotb: canonical H/incorrect H length between A messages; check validation, `msg_idx` advance and no-record |
| 7 | cocotb: broken lengths / truncated frames, incl. sub-word edges per `tkeep` → `error`, continuation |
| 8 | cocotb: real-day pcap replay as independent bursts + `tlast` count + committed frozen vectors |
| 9 | `python3 -m golden_model.scripts.run_golden data/itch_sample/01302019.NASDAQ_ITCH50.gz …` (no anomalies) + committed synthetic vectors |
| 10 | `verilator --lint-only -Wall --top-module itch_parser rtl/parser/<files>.sv` |
| 11 | `verible-verilog-lint rtl/parser/<files>.sv` |

Full regime: skill `verify`. Campaign-specific gates: A = cocotb/Verilator
green (make in `verification/testbenches/parser/`); B/C = lint+style;
D = spec↔test table + coverage by type (the 10 of the subset + non-subset);
E = agreed manual HDL mutation over the aligner/decoder/framing FSM (flip
`seq > expected` → `>=`, `>=` to `>`, relaxed length comparator, off-by-one in
the barrel shifter, omit `tlast`) — each killed by a test; F = Gherkin mirrors
(`specs/gherkin-espejos.json` → `verification/testbenches/parser`); G = G0/G3
(real data outside the repo) + **G timing/Vivado:** NOT EXECUTED in phase 1
(declared NOT APPLICABLE until phase 3; justification in the verify-report).

**Geless contracts** — invariants that can break with suite and lint green:

1. **Self-consistent but mis-transcribed layout table** across `messages.py`,
   the RTL and `--emit-messages`. Guardrail: the synthetic test vectors are
   **hand-written hex literals from the PDF** (independent oracle), never
   generated by the RTL itself; cocotb re-decodes the input stream with
   `messages.py` (independent of the RTL).
2. **Normalized record layout (Annex A)** vs. what the order book will consume
   in phase 2. Guardrail: Annex A fixed byte by byte in this spec (changing it =
   spec edit) + cocotb writer↔reader↔text round-trip.
3. **Semantics inherited by phase 2** (which subset fields the book carries):
   defined by this spec (Annex A), not redefined by phase 2.
4. **Line-rate requirement demonstrated only with synthetic vectors**: the real
   replay (criterion 8) uses real pcaps that DO contain real back-to-back, and
   the stall checker (criterion 2) applies also to the real replay.

## Loop

Stop limit: **5 iterations**. Cadence: chain build→verify→grade while there is a
queue; when the limit is reached with criteria in FAIL, escalate to the owner.

### REP-02 amendment (2026-08-18) — line-rate closure over a real stretch

Criterion 8 stays open in its line-rate arm. The aggregated replay closure
(byte-exact + `tlast` 91/91 + stall counter) is already in `verify-report.md`,
but it does **not substitute** the threshold measurement over a real stretch:
REP-02 must additionally:

1. Select from the pcap, **without manual indices**, a real stretch of four
   consecutive A or U messages (first sliding window of 4 in capture order;
   definition in the test, not in the RTL).
2. Process that isolated stretch with `m_axis_tready=1` always and count the
   input stalls (`s_axis_tvalid && !s_axis_tready`) during the stretch:
   **<= 24** (criterion 2 applied to the real replay).
3. Verify the stretch output bit-exact against the oracle (same derived
   selection, independent oracle).

Mirror: `test_rep02_tramo_au_real_line_rate` in
`verification/testbenches/parser/test_itch_parser.py`. If the local pcap does
not exist or does not contain the window, the test declares the omission
(SkipTest) and the criterion stays open.

---

## Annex A — normalized message record layout (canonical)

Each decoded subset message emits **one or more 64-bit words** in wire order
and fields (big-endian, no RTL byte-swap). A record is a burst with `tvalid`
high and `tlast` on the last word.

**Context header — Word 0:**

| Bits | Field | Description |
|---|---|---|
| 63:56 | `msg_type` | ITCH ASCII type (`S,R,A,F,E,C,X,D,U,P`) |
| 55:40 | `locate` | Stock Locate Code |
| 39:32 | `length` | total ITCH message length (bytes, from the framing field; max 50 → fits) |
| 31:0 | `msg_idx` | global message index in the stream (32 bits; the real day ~268M < 2³²) |

**Word 1 — temporal context:**

| Bits | Field |
|---|---|
| 63:0 | `ts_ns` — ITCH timestamp (ns from midnight, from the ITCH field) |

**Words 2…N — message body (decoded fields):** the message bytes after the
common ITCH header (11 B: type, locate, tracking, ts), i.e. exactly the
type-specific fields in **wire order** (big-endian). Since the subset types are
fixed length, each field has a fixed offset within the body (the same as
`golden_model/itch/messages.py`): decoding = validate length by type and
extract fields at those fixed offsets; no re-encoding (the phase-2 book indexes
the body by its type offset). Zero padding bytes to the 8 B word (leftover bits
at 0).

**Body word count per type** (`length − 11` B → `ceil(·/8)`):

| Type | len | body | body words | total (2+body) |
|---|---|---|---|---|
| S | 12 | 1 | 1 | 3 |
| D | 19 | 8 | 1 | 3 |
| X | 23 | 12 | 2 | 4 |
| R | 39 | 28 | 4 | 6 |
| A | 36 | 25 | 4 | 6 |
| F | 40 | 29 | 4 | 6 |
| E | 31 | 20 | 3 | 5 |
| C | 36 | 25 | 4 | 6 |
| U | 35 | 24 | 3 | 5 |
| P | 44 | 33 | 5 | 7 |

> The **exact** field order and offsets are those of
> `golden_model/itch/messages.py` (single source); Annex A fixes the context
> header, the burst semantics and body = wire bytes after the 11 common bytes.
> `--emit-messages` emits exactly these words (header + body). `m_axis_tlast`
> delimits the burst; cocotb reconstructs the record by `tlast` and compares it
> byte-exact against `--emit-messages`.

> **Explicit spec edit (2026-08-12, design finding during /build):** the first
> draft of this Annex had `msg_idx_lo[22:0]` of 23 bits (insufficient for a
> real day, ~268M messages) and a per-type word count misaligned with the real
> message sizes. Corrected to a 32-bit `msg_idx`, `length` in bits 39:32 and a
> verified words/body table. Without this edit, criterion 8 (byte-exact real
> replay) and the phase-2 contract would have been broken by construction.

## Annex B — campaign data and environment

- **Real replay (criterion 8):** pcap generated from the local day
  `data/itch_sample/12302019…` with `scripts/binaryfile_to_pcap.py`
  (`--msgs-per-packet` configurable); the raw data is never committed.
- **Frozen vectors (criterion 8/9):** small, synthetic, in
  `verification/vectors/messages/` and `verification/vectors/` (rule G0).
- **Toolchain (installed in this campaign):** Verilator 5.050 (brew), `.venv`
  with cocotb 2.0.1 / numpy 2.4.6 over **Python 3.11** (the system 3.14 breaks
  cocotb 2.0.1 — see DEVELOPMENT.md).
- Phase-0 loose ends (criterion 9): regression day `01302019.NASDAQ_ITCH50.gz`
  (~4.8 GB gz) + committed synthetic vectors.
- **Target part:** UltraScale+ (concrete part in phase-3 synthesis); here only
  the 64-bit @ 156.25 MHz datapath and Verilator compatibility are stipulated.