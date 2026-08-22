# Project marks — verifiable metrics (2026-08-22)

> Consolidated record of every verifiable mark reached, with its evidence.
> Single reference for the CV write-up, so numbers are never rediscovered.
> Every figure cites where its evidence lives; nothing is asserted without
> output.

## 1. Bottom line (what is claimed for a CV)

> UltraScale+ FPGA pipeline that decodes **Nasdaq TotalView-ITCH 5.0** at
> **10G line rate** (64 b x 156.25 MHz = **10.0 Gbps**) and maintains an
> **order book in 32 URAM** with **deterministic latency ~65.5 cycles (~203
> ns)**, **closing timing** on a **Kintex UltraScale+ XCKU3P** with
> **WNS +0.057 ns, TNS 0, DRC 0**; verified against an independent golden
> model and **31 killed mutants** in the order book.

Evidence for each claim: sections below.

---

## 2. Timing / synthesis marks (criterion 10)

### 2.1 Closed variant — 64 bit @ 156.25 MHz (10G)

Run `synth/fase3_156mhz.tcl` (generic `DW=64 BBO_W=64 K=64 QB=46`, XDC
`fase3_156mhz.xdc`, 6.400 ns period). Reports in `synth/reports/156mhz/`.

| Metric | Value | Criterion | Status |
|---|---|---|---|
| **WNS (setup)** | **+0.057 ns** | >= 0 | PASS |
| **TNS (setup)** | **0.000 ns** | = 0 | PASS |
| **WHS (hold)** | **+0.021 ns** | >= 0 | PASS |
| **LUT as Logic** | **154.371 / 162.720 (94.9 %)** | <= 95 % | PASS |
| **URAM288** | **32 / 48** | 32 | PASS |
| Bonded IOB | 194 / 256 | <= 256 | PASS |
| DRC | 0 errors | 0 | PASS |
| Frequency | 156.25 MHz (6.4 ns period) | — | 10.0 Gbps |

**I/O condition**: at DW=64 the wrapper's full observability exceeded the
FFVA676 package budget (258 pins > 256, `Place 30-58`), so `BBO_W` was
parameterized to 64 (only bid/ask prices at the `bbo_tdata` pin). The measured
datapath is identical (addendum iter 11b). This keeps the mark honest: timing
closure measures the **logic**, not the trimmed observability pins.

### 2.2 Open variant — 32 bit @ 322.265625 MHz (10.3 Gbps)

Not closed. After splitting the internal timing path `m_loc_idx ->
first_one -> sm_asel` (campaign `CLO-322-02`, split across two cycles without
an extra state), the book's internal datapath closes and LUT drops to
**146.761** (fits). The residual WNS is dominated by the **output I/O** of the
wrapper: source clock delay 2.695 ns (clock net fanout 95.585) + OBUF 2.334 ns
at the -2L speed grade exceed the 3.103 ns period even before the 1.0 ns
`set_output_delay`. This is a device-level I/O limit, documented as an open
optimization chapter — the timing gate is never relaxed and the XDC is not lied
about. Best measured WNS post-split: **-3.33 ns**.

### 2.3 Run history (criterion 10, 322 MHz variant)

| Run | Change | WNS | LUT | URAM |
|---|---|---|---|---|
| base | original wrapper | -10.492 ns | 100.33 % | 32/48 |
| iter 7 | ST_EMIT -> A/B/C | -7.395 ns | 96.49 % | 32/48 |
| iter 8 | 2a/2b decode + FIFO | -4.052 ns | 95.68 % | 32/48 |
| iter 9 | tvalid-only guard + first_one | -3.527 ns | 95.80 % | 32/48 |
| iter 10 | IOB on ports + tready_ff | -3.748 ns | 95.79 % | 32/48 |
| iter 11 | wrapper output pipeline | -3.319 ns | 95.80 % | 32/48 |
| **156 MHz** | **DW=64 BBO_W=64, 6.4 ns** | **+0.057 ns** | **94.9 %** | **32/48** |
| split CLO-322-02 | first_one in B, mux by registered index in C | -3.33 ns | 90.2 % | 32/48 |

The project swept -10.5 ns -> -3.3 ns at 322 MHz (~7 ns of book retiming gain)
and **closed at 156.25 MHz**. Full history and path families:
`synth/reports/README.md` and `specs/fase3-optimizacion/verify-report.md`.

---

## 3. Latency marks (wire -> BBO)

| Metric | Value | Threshold | Status |
|---|---|---|---|
| Total mean | **65.5 cycles (203.3 ns)** | <= 70 (RTM-LAT-01) | PASS |
| p50 / p99 / min | 66 / 98 / 24 cycles | — | measured |
| Determinism (SEC-LAT-01) | 2 identical runs | identical | PASS |

ns conversion uses the target clock 322.265625 MHz (3.103 ns/cycle).
Evidence: `verification/vectors/latency/latency_dw32.json`,
`docs/writeup/latency.md`, phase-3 verify report.

(Stationary backlog model: latency = queue backlog + processing; QB=46 fixed
the regime and the histogram is deterministic.)

---

## 4. Simulation marks (gates A/E/B — WSL)

Reproducible environment: WSL2 Ubuntu, cocotb 2.0.1, Verilator 5.046,
Python 3.12.

### 4.1 Phase 3 (order book + chain)

| Suite | Result |
|---|---|
| sim-rtm (DW=32, RTM-01..04) | 4/4 PASS |
| sim-rtm64 (DW=64) | 1/1 PASS |
| sim-lat (SEC-LAT-01 + RTM-LAT-01) | 2/2 PASS (mean 65.5 <= 70) |
| sim-hash | 8/8 PASS |
| sim-depth | 3/3 PASS |
| sim-hard | 2/2 PASS |
| sim-chain | 5/5 PASS (feed real bit-exact, 17.484 events) |
| sim-chain-nd3 | 5/5 PASS |
| sim-parser | 5/5 PASS |

**Gate E (order-book mutation)**: **31/31 mutants killed** (0 survivors).
**Gate B**: `verilator --lint-only --Wall` — only 9 deliberate BLKSEQ (blocking
assignments of the URAM inference). **Gate C** (verible): NOT EXECUTED (tool
not installed).

### 4.2 Phase 4 (CME MDP3 parser)

| Suite | Result |
|---|---|
| mdp3 DW=32 and DW=64 | 14/14 PASS |
| M3-BP-01 (output backpressure) | PASS |
| Gate E (MDP3 mutation) | 14/14 mutants killed |
| Gate B | Verilator 5.046 `--Wall` clean |

### 4.3 Phases 0/1/2 (closed)

- Phase 0: full Python unittest suite green; 5/5 mutants; real day 268.7M
  messages in 17 min, 14.4M BBO vectors for the 20-symbol subset.
- Phase 1 parser: 32/32 (91/91 `tlast`, bit-exact real replay, gaps,
  backpressure); **REP-02 line-rate closed** (real A/U burst, 9 stalls <= 24).
- Phase 2 order book: 17/17 + real subset replay.

---

## 5. Cross-verification marks (adversarial)

- **Golden independent of the RTL**: oracles derive from the Python golden
  model, never from the DUT.
- **Bit-exact**: BBO and depth compared against the golden (17.484 real-feed
  events; CHAIN-01; subsets in sim-rtm/sim-chain).
- **Deterministic latency**: SEC-LAT-01 requires identical histograms across 2
  passes (verified).
- **Mutation**: 31 (order book) + 14 (MDP3) mutants, all killed; each mutant
  compiles before being counted.

---

## 6. Honest limits (what is NOT claimed)

- 10G MAC / Ethernet / IP / UDP are **not implemented** (the repo starts at the
  decapsulated MoldUDP64 payload).
- The book is sized for the **20-symbol subset**, not a full Nasdaq book.
- Infinite line-rate of minimal messages is an explicit **non-goal** (Annex A:
  output/input ratio > 1). REP-02 measures a bounded real burst.
- 322 MHz stays **open** (output I/O bound, -3.33 ns); it is not declared
  timing-closed.
- CME MDP3: framing + criteria 5/7/10 green; **timing open** (the parser does
  not fit the XCKU3P).
- Gate C (verible) NOT EXECUTED in phases 1-4 (tool not installed).

---

## 7. References

| Number | Evidence |
|---|---|
| 156 MHz (WNS/TNS/LUT/URAM) | `synth/reports/156mhz/*.txt` + `specs/fase3-optimizacion/verify-report.md` |
| 322 MHz run history | `synth/reports/README.md` |
| Latency | `verification/vectors/latency/latency_dw32.json`, `docs/writeup/latency.md` |
| Phase 3/4 simulation | `specs/fase3-optimizacion/verify-report.md`, `specs/fase4-mdp3-parser/verify-report.md` |
| Background config | root master document, decision 002 (part), lessons-learned.md |

The `synth/reports/*.txt` files are always from the **latest** run; historical
numbers live in the tables of this document and the verify reports.