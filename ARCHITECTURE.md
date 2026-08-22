# Architecture — FPGA ITCH -> Order Book -> BBO

A low-latency market-data pipeline for AMD/Xilinx UltraScale+, implemented in
SystemVerilog and verified bit-exactly against an independent Python golden
model. This document explains the architecture and the design decisions; the
README is the entry point, and every number here is regenerable from the code.

## Pipeline

```
MoldUDP64 (payload already decapsulated) -> ITCH parser -> order book (URAM) -> BBO/top-N
```

- **ITCH parser** (`rtl/parser/itch_parser.sv`): 64-bit AXI-Stream framing with
  `s_axis_tkeep`, gaps, backpressure and per-message `tlast`; bit-exact replay
  of a real trading day.
- **Order book** (`rtl/orderbook/orderbook.sv`): a 20-symbol subset in a **URAM**
  order table (hash + linear probing, registered read), BBO bit-exact against
  the golden model in real replay.
- **Chain** (`rtl/itch_chain.sv` + synthesis wrapper
  `synth/itch_chain_synth.sv`): parser -> book with a registered pipeline and a
  DW=64 / 156.25 MHz **timing-closed** variant.
- **CME MDP3 parser** (`rtl/parser/mdp3_parser.sv`): the same `tkeep` framing
  discipline against a pinned SBE schema.

## The order book

The order table is a URAM hash table indexed by the 64-bit *order reference
number*. Each entry stores symbol, side (bid/ask), price and remaining
quantity, plus a pointer to the aggregated price level. Price levels are kept
per symbol and side as a sorted list (best first), from which the BBO and the
public top-N derive directly.

The book resolves three classes of hazards without an escape FIFO:

1. **RAW hazards of the message queue** — two consecutive messages on the same
   order/level (add->execute, add->cancel, replace->execute) where the second
   must observe the state of the first. Resolved with forwarding or selective
   stall.
2. **Atomic `U` replace** — delete+add as a single resulting state, never an
   intermediate BBO with the order absent. The BBO emitted for a `U` reflects
   the final state.
3. **URAM with 1 write/cycle and registered read** — the table (65,536 x 88
   bits = 32 real URAM288) requires a registered read pipeline (1 cycle) and
   serialized writes; the BBO is held in registers re-read by the retention
   logic and the FSM guard.

Signaled invariants, never silence: duplicate ref, non-positive qty, level
overflow -> `error`; unknown ref or non-aborting invalid operation ->
`anomaly_count`; a continuously crossed book -> `cross_events` (counted, not
aborting).

## Emission pipeline (timing)

The BBO/top-N selection is a registered pipeline split into three stages:

- **A** registers the 2*P level caps and the per-side non-empty predicates (a
  mux by symbol, `!= 0`).
- **B** computes `first_one` over the registered predicates into a 5-bit index.
- **C** multiplexes the caps by that registered index, computes `changed`/`cross`
  and drives the output handshake.

Splitting the `m_loc_idx -> first_one -> sm_asel` path across these stages (with
the index *registered* in B) removed the book's critical path and reduced LUT
from 161.8k to 146.8k, at zero extra emit stages (latency unchanged).

## Latency wire->BBO

Measured on the parser->book chain at DW=32 (322.265625 MHz, 3.103 ns/cycle)
over the 20-symbol subset of the real 2019-12-30 feed (20,705 messages, 17,484
events, 0 gaps). Latency is the `s_axis` handshake of the word covering the
message's first byte -> `bbo_tvalid`, per message type, deterministic across
re-runs. Artifact: `verification/vectors/latency/latency_dw32.json`.

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

Mean **65.5 cycles = 203.3 ns** at the 322.265625 MHz target clock.

## Vivado timing

Synthesis top `synth/itch_chain_synth.sv` (AXI-contract wrapper; the full
`itch_chain.sv` exposes 896 ports and does not fit the FFVA676 package). The
tcl aborts on any negative slack. Run history: `synth/reports/README.md`.

| Variant | Period | WNS | TNS | LUT (book) | URAM | Verdict |
|---|---|---|---|---|---|---|
| DW=64 @ 156.25 MHz (10G) | 6.400 ns | **+0.057 ns** | 0 | 150.466 | 32/48 | **CLOSED** (DRC 0, IOB 194/256) |
| DW=32 @ 322.265625 MHz | 3.103 ns | -3.33 ns | — | 146.761 | 32/48 | **OPEN** (see below) |

- **CLOSED — DW=64 @ 156.25 MHz = line-rate 10G**: WNS +0.057 ns, TNS 0, WHS
  +0.021 ns, URAM 32/48, DRC 0. At DW=64 full observability exceeds the FFVA676
  I/O (258 > 256), so `BBO_W` is parameterized to 64 (prices only at the pin);
  the datapath is identical.
- **OPEN — 322 MHz (DW=32)**: after splitting the internal timing path, the
  top-10 violating paths are **all output-pad paths** (`bbo_locate_o_reg` /
  `depth_tdata_o_reg` -> OBUF -> pin): source clock delay 2.695 ns (clock net
  fanout 95,585) + OBUF 2.334 ns at the -2L speed grade exceed the 3.103 ns
  period even before the 1.0 ns `set_output_delay`. This is a device-level I/O
  limit, not a datapath limit.

## `tkeep` framing and why infinite line-rate is a non-goal

AXI-Stream framing with `s_axis_tkeep` handles variable-size packets (2-64 B
ITCH messages; SBE groups in MDP3) without FIFOs or per-size parallelization:
`tkeep` declares the real lanes of the last beat, and non-MSBS-contiguous masks
are an error condition (never silent behavior).

Infinite line-rate with minimal messages is explicitly a **non-goal**: a real
ITCH feed has a size mix that the datapath consumes at 1 message per cycle as
the nominal regime. The goal is sustained throughput at the feed's *real*
line-rate with stable backpressure; the real backpressure and latency regime is
documented, not hidden.

## Verification

- An **independent golden model** (`golden_model/`) is the oracle; the RTL is
  compared bit-exactly against it, never the other way around.
- **cocotb + Verilator** testbenches (`verification/`) cover framing, the book
  hazards, the top-N depth, backpressure and latency.
- **Mutation testing** killed all mutants (31 in the order book, 14 in MDP3);
  every mutant compiles before being counted.
- **Vivado** timing closure is enforced by a tcl that fails on negative WNS/TNS.

## Honest limits

- **No MAC/Ethernet/IP/UDP** — the input is the already-decapsulated MoldUDP64
  payload; the 10G network infrastructure is out of scope.
- **The book is sized for the 20-symbol subset**, not the full Nasdaq book
  (7,000+ listings).
- **322 MHz stays open** (output-I/O-bound); the closed production variant is
  DW=64 @ 156.25 MHz = line-rate 10G.
- **The CME MDP3 parser does not fit the XCKU3P** (LUT over-utilization in both
  DW=32 and DW=64); this is documented red, pending a repartition.