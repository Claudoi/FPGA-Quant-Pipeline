# FPGA Pipeline ITCH -> Order Book -> BBO — candidate write-up

> Master presentation document. The specs, verify reports and synthesis
> reports are the evidence; this document only summarizes and links to them.
> Dated: 2026-08-22.
>
> Public and reproducible repository: `git log`,
> `make -C verification/... sim` and
> `vivado -mode batch -source synth/fase3_synth.tcl` regenerate every number
> in this document.

## 1. What it is

A **low-latency FPGA infrastructure for electronic markets** (Nasdaq ITCH and
CME MDP3) implemented in SystemVerilog, verified bit-exactly against an
independent Python golden model, with timing closure in Vivado for a Kintex
UltraScale+ `xcku3p-ffva676-2L-e`.

The implemented pipeline:

```
MoldUDP64 (payload already decapsulated) -> ITCH parser -> order book (URAM) -> BBO/top-N
```

- **ITCH parser** (`rtl/parser/itch_parser.sv`): 64-bit AXI-Stream framing with
  `s_axis_tkeep`, gaps, backpressure and per-message `tlast`; 91/91 `tlast`
  vectors green and bit-exact replay of a real trading day (spec
  `specs/fase1-parser-rtl/`).
- **Order book** (`rtl/orderbook/orderbook.sv`): 20-symbol subset in a **URAM**
  order table (hash + linear probing, registered read), BBO bit-exact against
  the golden model in real replay (spec `specs/fase2-orderbook/`).
- **Chain** (`rtl/itch_chain.sv` + synthesis wrapper
  `synth/itch_chain_synth.sv`): parser -> book with a registered pipeline and
  the DW=64 / 156.25 MHz **timing-closed** variant (spec
  `specs/fase3-optimizacion/`).
- **CME MDP3 parser** (`rtl/parser/mdp3_parser.sv`): the same `tkeep` framing
  discipline, pinned SBE schema
  (`data/mdp3/templates_FixBinary_v12.xml`), criteria 5 and 10 closed (spec
  `specs/fase4-mdp3-parser/`).

## 2. Honest limits

- **No MAC/Ethernet/IP/UDP in this repository**: the input is the
  already-decapsulated MoldUDP64 payload (the 10G network infrastructure is
  outside the implemented scope).
- **The book is sized for the configured 20-symbol subset**, not for the full
  Nasdaq book (7,000+ listings).
- **322 MHz (DW=32) remains an open optimization chapter**; the closed
  production variant is **DW=64 @ 156.25 MHz = line-rate 10G** (see §5).
- The **CME MDP3 parser does not fit the XCKU3P**: synthesis aborts on LUT
  over-utilization in both variants (documented red, pending a repartition
  spec addendum).

## 3. Book hazards (why the design is not trivial)

The order-table contract (spec phase 2) forces three classes of hazards to be
resolved without an escape FIFO:

1. **RAW hazards of the message queue**: two consecutive messages on the same
   order/level (add->execute, add->cancel, replace->execute); the second must
   observe the state of the first. Resolved with forwarding or selective
   stall (`SEC-HZ-01/02`).
2. **Atomic `U` replace**: delete+add as a single resulting state; never an
   intermediate BBO with the order absent (`SEC-U-01`). The BBO emitted for a
   `U` reflects the final state.
3. **URAM with 1 write/cycle and registered read**: the table (65,536 x 88
   bits = 32 real URAM288, measured in the runs) requires a registered read
   pipeline (1 cycle) and serialized writes; the BBO output is held in
   registers re-read by the retention and the FSM guard (internal fanout that
   synthesis does not pack into the IOB — documented in iteration 10).

Signaled invariants, never silence: duplicate ref, non-positive qty, level
overflow -> `error`; unknown ref or non-aborting invalid operation ->
`anomaly_count`; continuous crossed book -> `cross_events` (counted, not
aborting).

## 4. Latency wire->BBO

Reproducible histogram of the parser->book chain at DW=32 (322.265625 MHz,
3.103 ns/cycle) over the 20-symbol subset of the real 2019-12-30 feed
(20,705 messages, 17,484 events, 0 gaps). Measurement: `s_axis` handshake
(word covering the message's first byte) -> `bbo_tvalid`. Artifact:
`verification/vectors/latency/latency_dw32.json` (criterion `SEC-LAT-01`).

| Type | n | min | mean | p50 | p99 | max |
|---|---|---|---|---|---|---|
| A (add) | 9441 | 35 | 68.03 | — | 85 | 103 |
| C (executed w/ price) | 22 | 41 | 58.18 | — | 72 | 72 |
| D (delete) | 4589 | 24 | 58.45 | — | 83 | 97 |
| E (executed) | 704 | 27 | 55.13 | — | 82 | 95 |
| F (add no MPID) | 1922 | 36 | 66.92 | — | 87 | 102 |
| U (replace) | 785 | 42 | 82.84 | — | 110 | 111 |
| X (cancel) | 21 | 53 | 62.29 | — | 77 | 77 |
| **Total** | **17,484** | **24** | **65.52** | **66** | **98** | **111** |

Campaign criterion `RTM-LAT-01`: mean **65.5 cycles (203.3 ns) <= 70**,
deterministic (verified in WSL, cocotb + Verilator; see
`specs/fase3-optimizacion/verify-report.md` and
`specs/cierre/verify-report.md`).

## 5. Vivado timing (criterion 10)

Synthesis top `synth/itch_chain_synth.sv` (AXI contract wrapper; the full
`itch_chain.sv` exposes 896 ports and does not fit the FFVA676 package).
Reproducible run: `vivado -mode batch -source synth/fase3_synth.tcl`. The tcl
aborts with `FASE3 TIMING FAIL` on any negative slack (gate is never relaxed).
Full history: `synth/reports/README.md`.

| Variant | Period | WNS | TNS | LUT (book) | URAM | Verdict |
|---|---|---|---|---|---|---|
| DW=64 @ 156.25 MHz (10G) | 6.400 ns | **+0.057 ns** | 0 | 150.466 | 32/48 | **CLOSED** (DRC 0, IOB 194/256) |
| DW=32 @ 322.265625 MHz | 3.103 ns | -3.33 ns | — | 146.761 | 32/48 | **OPEN** (see below) |

DRC: 0 errors in every run.

- **CLOSED — production variant DW=64 @ 156.25 MHz = line-rate 10G**: WNS
  +0.057 ns, TNS 0, WHS +0.021 ns, URAM 32/48, DRC 0. At DW=64 the full
  observability exceeds the FFVA676 I/O (258 > 256), so `BBO_W` is
  parameterized to 64 (prices only at the pin); the datapath is identical.
- **OPEN — 322 MHz (DW=32)**: the internal datapath now closes. The critical
  path `m_loc_idx -> first_one -> sm_asel` was split across two cycles
  (campaign `CLO-322-02`): stage A registers the level caps and non-empty
  predicates, stage B computes `first_one` into a registered index, stage C
  multiplexes the caps by that registered index. After the split, the top-10
  violating paths are **all output-pad paths** (`bbo_locate_o_reg` /
  `depth_tdata_o_reg` -> OBUF -> pin): source clock delay 2.695 ns (clock
  net fanout 95,585) + OBUF 2.334 ns at the -2L speed grade exceed the
  3.103 ns period even before the 1.0 ns `set_output_delay`. This is a
  device-level I/O limit, not a datapath limit; the timing gate is never
  relaxed and the XDC is not lied about.

## 6. `tkeep` framing and why infinite line-rate is a non-goal

AXI-Stream framing with `s_axis_tkeep` handles variable-size packets (2-64 B
ITCH messages; SBE groups in MDP3) without FIFOs or per-size parallelization:
`tkeep` declares the real lanes of the last beat, and non-MSBS-contiguous
masks are an error condition (never silent behavior). The mechanics are
verified by mutation (`TKCNT-ALWAYS` dead) and by 18/18 tests in both widths.

**Infinite line-rate with minimal messages is explicitly a non-goal** (spec
phase 1, criterion 2, and the lessons-learned §9): a real ITCH feed has a size
mix that the DW=32/DW=64 datapath consumes at 1 message per cycle as the
nominal regime; the goal is sustained throughput at the feed's *real*
line-rate with stable backpressure, not the theoretical upper bound of a
pathological stream. The real backpressure and latency regime is documented,
not hidden (a global repo rule).

## 7. Status by phase and what is not there

| Phase | Verdict |
|---|---|
| 0 — golden ITCH | **Closed**; 22 validated types, real 2019-12-30 day (268.7M messages in 17 min, 0 anomalies), 29/29 tests |
| 1 — parser RTL | **Closed**; `tkeep` framing, 91/91 `tlast`, gaps, backpressure, real bit-exact replay, **REP-02 line-rate closed** (real A/U burst, 9 stalls <= 24) |
| 2 — order book RTL | **Closed**; BBO bit-exact, atomic replace, real subset replay |
| 3 — DW=32/URAM | **Functional closed end-to-end**; **64b/156.25 MHz (10G) closed**; 322 MHz open (I/O-bound); full simulation green |
| 4 — CME MDP3 | **Functional closed** (14/14 DW=32/64, gate E 14/14); criteria 5/7/10 closed; **timing open** (over-utilization) |

Explicitly not present: MAC/Ethernet/IP/UDP, full Nasdaq book, 322 MHz closed,
CME MDP3 timing closure.

## 8. Verification (gates, no shortcuts)

- Independent golden model; bit-exact comparison (never an oracle generated
  from the RTL under test).
- Gates A-G of the repo process (`AGENTS.md`): cocotb simulation (Verilator),
  `--Wall` lint, verible style, spec<->test coverage, **mutation** (31 dead in
  the order book + 14 in MDP3), Gherkin completeness, Vivado timing.
- Commands: `make -C verification/testbenches/<area> sim` per area;
  `python3 scripts/verify/mutate_mdp3.py`;
  `python3 scripts/verify/synth_check.py`.

## 9. Evidence links

| Need | Location |
|---|---|
| Rules, status and process | `AGENTS.md` |
| Per-campaign contracts | `specs/<campaign>/spec.md` + `gherkin/` |
| Per-campaign evidence | `specs/<campaign>/verify-report.md` |
| Vivado run history | `synth/reports/README.md` |
| Latency (JSON histogram) | `verification/vectors/latency/latency_dw32.json` |
| Synthesis & simulation lessons | `docs/writeup/lessons-learned.md` |
| Executable close plan | `docs/writeup/close-plan.md` |
| Verifiable marks | `docs/writeup/marks.md` |
| Environment setup | `docs/DEVELOPMENT.md` |