# fase2-orderbook (phase 2 of the master plan)

## Goal

Build the **order book engine in RTL** (SystemVerilog, Verilator-compatible)
that consumes the Annex-A normalized record emitted by the phase-1 parser
(AXI-Stream of decoded messages) and maintains, per symbol, the book state:
**live order table** (order_ref → symbol/side/price/qty), **aggregated price
levels** and the **BBO** (best bid & offer) updated with deterministic latency.
It is the stage that closes, from the implemented boundary of the repository,
the pipeline `MoldUDP64 → parser → order book → BBO` of the master document.
10G MAC and Ethernet/IP/UDP stay outside this repository.

Correctness is verified **bit-exact against the phase-0 golden model**
(`golden_model/src/book.py`), which was already validated against full Nasdaq
days (2019-12-30: 268M messages, 0 anomalies). The RTL replicates that exact
semantics; any deviation is a FAIL.

## Scope

**In scope:**

- `rtl/orderbook/` — SystemVerilog modules of the engine:
  - **Annex-A record decoder**: extracts the fields by type
    (A/F/E/C/X/D/U/S/H) from the word burst emitted by the parser (word0 context
    header, word1 ts, words 2..N big-endian body).
  - **Order table in URAM**: order_ref (32 useful bits after strip; the real day
    ~268M refs < 2³²) → order entry (locate, side, price, remaining qty). **No
    hash is implemented in this phase**: it uses **direct order_ref indexing in
    a URAM space of 2^K entries** (K sized to the subset, see Constraints) —
    interview decision: hashing with probing is deferred to an optimization
    iteration if the real subset demands it.
  - **Price levels**: per (locate, side), an array of levels {price → aggregated
    qty}; the BBO is the best bid/ask level.
  - **Application FSM** for the 7 modifying types + S/H state.
  - **BBO output**: per symbol, (bid_px, bid_qty, ask_px, ask_qty), event on
    change (`BookEvent` semantics of the golden).
  - Top `orderbook`.
- `rtl/common/` — shared helpers if needed (handshake FIFO, etc.).
- `verification/testbenches/orderbook/` — cocotb + Verilator testbenches:
  - Synthetic Annex-A record feed (built in the same format the phase-1 parser
    emits) + **real stripped feed** of the local day (replay,
    `data/itch_sample/12302019…` → parser → book).
  - Oracle `golden_model/src/book.py` applied over the same messages; comparison
    **event-by-event and bit-exact** of the BBO.
- Frozen BBO vectors for the subset in `verification/vectors/bbo/`.

**Out of scope (non-goals):**

- Redoing the parser: the book consumes Annex A exactly as phase 1 emits it.
  (The testbench can feed records directly or chain parser+book.)
- Hash table with collisions/cuckoo (future optimization, only if the subset
  asks for it). In this phase the table is direct order_ref indexing.
- Top-N depth levels (depth book): only **BBO** (criterion of this phase). The
  deep book by levels exists (level state), but the public output is BBO.
- Full multi-symbol of 2000+ symbols: up to **N symbols** of the subset (20) are
  supported, with levels per (locate, side) in parameterized space.
- Optimal 322 MHz latency / Vivado timing closure: phase 3.
- CME MDP3 (stretch phase 4).
- Market-hours / strict halt-cross semantics: the golden counts `cross_events`
  and continues; the RTL replicates the golden's **no-abort** by default
  (`strict_cross=False`), see §Semantics.

**Measured radius (2026-08-13):** `rtl/orderbook/` empty (verified with
`find rtl/ -type f`). `rtl/parser/itch_parser.sv` exists and is reused as the
Annex-A generator. `verification/testbenches/orderbook/` does not exist (new
area). Nothing is renamed or moved.

## Constraints

- **Target family/part:** AMD/Xilinx UltraScale+ (concrete part in phase-3
  synthesis). Datapath 64-bit @ 156.25 MHz (parser clock).
- **URAM:** registered read (1–2 cycles of latency). The pipeline is designed
  around that latency: the BBO of a message reflects its effect on the next
  valid output beat, without "fixing" the sign with long logic.
- **Order table:** 2^K entries, K such that `2^K ≥ peak_live_orders` of the
  subset (measured peak 259,443 on 2019-12-30) — `K` is parameterized with a
  simulation-appropriate default and the URAM mapping is documented for phase 3.
- **Level sizing:** array per (locate, side) of `P` price levels; the golden
  assumes an unbounded dict, the RTL bounds it to `P` and signals level overflow
  (never silent).
- **Endianness:** body fields are wire big-endian (Annex A, no byte-swap); the
  decoder extracts by exact offset of `golden_model/itch/messages.py` (single
  source, phase-0/1 rule).
- **Determinism:** same stream → same BBO sequence, bit-exact against the
  golden; no loss or double-count.

## Semantics (contract inherited from the golden — does NOT redefine, replicates)

`golden_model/src/book.py` (phase 0, validated against a real day) defines:

- `A`/`F` → add (duplicate ref = invariant error; qty ≤ 0 = error).
- `E`/`C` → reduce qty; reaching 0 deletes the order. `C` reduces exactly like
  `E` (exec_price does not alter the order price).
- `X` → reduce (cancel). `D` → delete (unknown ref = anomaly, does not abort).
- `U` → **ATOMIC replace**: delete+add of a single resulting state (never a
  visible intermediate BBO with the order absent).
- `P` → does not touch the book.
- `S` (event) and `H` (trading state) → market/halt state; `S` in `Q` opens and
  in `M` closes market hours; crossed in continuous trading is COUNTED
  (`cross_events`), does not abort (by default).
- Operation on unknown ref → counted anomaly, continues.
- Empty BBO side = (price 0, qty 0).

The RTL must reproduce these rules EXACTLY. The invariant table (duplicate ref,
non-positive qty, inconsistent level, level overflow) are first-class `SEC-`
scenarios with signaled `error` (or counted `cross_events`), never silent
behavior.

## Surface and threats

**Inputs (ports of the top `orderbook`):** the phase-1 AXI-Stream — the same
`s_axis_tdata/tvalid/tready/tlast` set (64-bit), plus `clk`/`rst_n`. The record
is Annex A: word0 `{msg_type, locate, length, msg_idx}`, word1 ts, words 2..N
body.

**New outputs:**

| Signal | Width | Description |
|---|---|---|
| `bbo_locate` | 16 | locate of the symbol of the BBO event |
| `bbo_tdata` | 128 | `{bid_px[31:0], bid_qty[31:0], ask_px[31:0], ask_qty[31:0]}` (32-bit ITCH prices, 32-bit qtys) |
| `bbo_tvalid` | 1 | there is an output BBO event (per modifying message) |
| `bbo_tready` | 1 | backpressure from the BBO consumer |
| `bbo_changed` | 1 | the BBO changed vs. the previous one (`changed` semantics of the golden) |
| `cross_events` | 32 | counter of crossed books in continuous trading |
| `anomaly_count` | 32 | counter of unknown refs / non-aborting invalid operations |
| `error` | 1 | violated invariant (duplicate ref, qty ≤ 0, level overflow) — fail with signal |

**Domain abuse cases** (each with its `SEC-` scenario in Gherkin):

- **RAW hazards:** two consecutive messages on the same order/level
  (add→execute, add→cancel, replace→execute) → the second sees the state of the
  first (forwarding or selective stall). — SEC-HZ-01/02.
- **Atomic replace:** never an intermediate BBO with the order absent; the BBO
  of the `U` reflects the final state. — SEC-U-01.
- **Double-count:** execute/cancel/delete do not subtract the order's or the
  level's qty twice. — SEC-DC-01.
- **Overflow:** level/order qty, ref counter, and levels > `P` are signalled,
  never wrapped silently. The invalid operation emits no BBO and the next valid
  message is accepted. — SEC-OV-01.
- **Unknown ref** in E/X/D/U → counted anomaly, no abort, stream continues. —
  SEC-AN-01.
- **Bid ≥ ask in continuous trading** → `cross_events` counts, no abort. —
  SEC-CR-01.
- **Empty symbol**: a locate with no orders stays isolated while another locate
  is operated and emits no spurious event; in the active symbol any empty side
  is represented as (0,0). — BBO-02/SEC-EM-01.

**What is at risk from the master:** **deterministic latency** and **strict
state correctness** (double-count/hazard = incorrect BBO = the worst failure of
a trading pipeline). The book is the stage where a state error is not caught by
the parser: bit-exact verification against the golden is the only net.

## Reuse

- `golden_model/src/book.py` — **reference oracle** (phase 0). The RTL
  replicates its semantics; the testbench applies it over the same feed. No
  "the RTL is the golden": two implementations compared bit-exact.
- `golden_model/itch/messages.py` — **single source of field layouts** (body
  offsets per type). The RTL decoder uses these offsets; the testbench re-parses
  with `message_oracle` (independent of the RTL).
- `rtl/parser/itch_parser.sv` — real Annex-A generator (chained in the
  testbench for replay and synthetic vectors).
- `golden_model/src/message_oracle.py` — phase-1 message oracle.
- `requirements-dev.txt`, cocotb/Verilator — already-installed environment.
- **New code that duplicates** `book.py` semantics with another literal
  (hand-written prices/qtys) = FAIL of the `/grade` simplicity lens.

## Acceptance criteria (Definition of Done)

1. [ ] The book consumes Annex A and maintains the order table + levels; for a
     synthetic A/F/E/C/X/D/U sequence, the per-symbol BBO is **bit-exact
     against the golden `book.py`** (same feed, same order, event by event,
     including `changed`).
     — Gherkin: `orderbook.feature` §BBO-01, §BBO-02
2. [ ] **Atomic `U` replace**: the BBO emitted for a `U` is that of the final
     state (delete+add), never an intermediate with the order absent.
     — Gherkin: `orderbook.feature` §SEC-U-01
3. [ ] **RAW hazards**: two consecutive messages on the same order/level
     (add→execute, add→cancel, replace→execute) produce the correct BBO of the
     second (forwarding or selective stall), without incorrect results.
     — Gherkin: `orderbook.feature` §SEC-HZ-01, §SEC-HZ-02
4. [ ] **Double-count**: execute/cancel/delete do not subtract twice; the level
     and the order stay consistent with the golden.
     — Gherkin: `orderbook.feature` §SEC-DC-01
5. [ ] **Overflow**: order/level qty, levels > `P` and counters are signalled
     with `error`, never wrapped silently nor producing a BBO for the invalid
     operation; the immediately following valid message is processed normally.
     — Gherkin: `orderbook.feature` §SEC-OV-01
6. [ ] **Anomalies and crosses**: unknown ref counts in `anomaly_count`
     (no abort); bid ≥ ask in continuous trading counts in `cross_events`
     (no abort) — exact replica of the golden `strict_cross=False`.
     — Gherkin: `orderbook.feature` §SEC-AN-01, §SEC-CR-01
7. [ ] **Multi-symbol**: up to N subset symbols with independent state
     (levels per locate+side); one symbol's messages do not contaminate another.
     — Gherkin: `orderbook.feature` §MULTI-01
8. [ ] **Real replay (hybrid oracle)**: over the local day
     `data/itch_sample/12302019…` (parser → book), the subset BBO sequence is
     **bit-exact** against the golden `book.py` over the same feed; additionally
     frozen BBO vectors are committed in `verification/vectors/bbo/` and
     reproduced.
     — Gherkin: `orderbook.feature` §REPLAY-01, §REPLAY-02
9. [ ] Cocotb + Verilator compile the top with `--Wall` with no real warnings
     silenced.
     — Gate B/C of verify.
10. [ ] Lint and style green over `rtl/orderbook/` (`verilator --lint-only
     -Wall`; verible if installed).
     — Gate B/C of verify.

## Verification

| Criterion | How it is tested |
|---|---|
| 1 | cocotb: synthetic multi-type corpus → Annex-A feed → compare BBO vs `book.py` (event by event, bit-exact) |
| 2 | cocotb: `U` with non-empty prior BBO → the emitted event is the final one (not intermediate); a non-atomicity mutant kills it |
| 3 | cocotb: adjacent pairs add→execute, add→cancel, replace→execute over the same ref; compare vs golden |
| 4 | cocotb: execute/cancel/delete and verify order+level with the golden's `check_deep()` (or qty count) |
| 5 | cocotb: inject qty/level overflow → sample `error`, no wrap nor invalid BBO, and accept the following valid message |
| 6 | cocotb: unknown ref → `anomaly_count` increments; cross → `cross_events` increments; flow continues |
| 7 | cocotb: interleaved messages from 2+ symbols; independent BBO per locate |
| 8 | cocotb: local-day replay chained parser→book; compare vs golden; committed frozen vectors |
| 9/10 | `verilator --lint-only -Wall --top-module orderbook` + `verible-verilog-lint` (if installed) |

Full regime: skill `verify`. Gates: A = cocotb in
`verification/testbenches/orderbook/`; B/C = lint+style; D = functional
coverage (application FSM states + spec↔test table per criterion); E = HDL
mutation over `rtl/orderbook/` (flips of: `>`/`>=` in best bid/ask, level
off-by-one, non-atomic `U`, double subtract, ref comparator) — each killed by a
test; F = Gherkin mirrors (`specs/gherkin-espejos.json` →
`verification/testbenches/orderbook`); G = G0/G2/G3 (real data outside the repo;
book without inconsistency window; bit-exact comparison). G timing/Vivado: NOT
EXECUTED until phase 3 (justified in the verify-report).

**Geless contracts** — invariants that can break with suite and lint green:

1. **Mis-transcribed inherited semantics** between `book.py` and the RTL (e.g.
   `C` that alters the price, non-atomic `U`, execute on an empty level).
   Guardrail: test vectors are **literals** built from `messages.py`
   (independent of the RTL), and the oracle is `book.py` (never the RTL itself).
2. **Mis-decoded Annex-A layout** (shifted body offsets). Guardrail: the decoder
   uses `messages.py` offsets; the testbench re-parses the same feed with
   `message_oracle` and compares BBO, not loose fields.
3. **Unsignalled overflow** (silent qty/level wrap). Guardrail: `SEC-OV-01`
   scenarios with a reduced-width mutant.
4. **The book "loses" orders** due to order-table sizing (2^K < subset peak).
   Guardrail: golden `check_deep()` after the real replay; if there is loss,
   `error`/anomaly — never a silent result.

## Loop

Stop limit: **5 iterations**. Cadence: chain build→verify→grade while there is a
queue. When the limit is reached with criteria in FAIL, escalate to the owner.