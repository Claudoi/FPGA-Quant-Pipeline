# Project Guide — FPGA Quant Pipeline

Portfolio/reference project for low-latency FPGA market-data infrastructure.
The implemented scope starts at the already-decapsulated MoldUDP64 payload;
the 10G MAC and Ethernet/IP/UDP layers are **not** part of this repository.

## Architecture and honest limits

```
MoldUDP64 -> ITCH parser -> order book -> BBO/top-N
```

- The phase-3 target variant is DW=32 at 322.265625 MHz on UltraScale+. The
  `tkeep` framing and the BBO/top-N output are verified in simulation. A
  reproducible stall-threshold measurement over a real A/U path remains the
  open item; timing closure also requires a Vivado report with WNS/TNS and
  utilization.
- The book is sized for the configured 20-symbol subset, not a full Nasdaq
  book.
- Replays against real data require local, non-versioned artifacts. A test that
  cannot find its pcap reports the omission; it never substitutes synthetic
  evidence for the pcap.

The master write-up (architecture, hazards, latency, timing, limits):
`docs/writeup/pipeline-itch-uram.md`.

## Status — 2026-08-22

| Phase | Verifiable status |
|---|---|
| 0 – golden ITCH | Closed. Python golden model, 22 validated types, real-day evidence. |
| 1 – parser RTL | Closed (2026-08-20). `s_axis_tkeep` framing, gaps, backpressure, 91/91 `tlast`, bit-exact real replay; REP-02 line-rate closed (real A/U burst msgs 241733..241736, 9 stalls <= 24). Suite 32/32. |
| 2 – order book RTL | Closed functionally. Bit-exact BBO, atomic replace, real subset replay. |
| 3 – DW=32/URAM | Functional closed end-to-end (17.484 BBO events bit-exact, cross=0, anomaly=0, gaps=0, DW=32/QB=46, latency mean 65.521 cycles = 203.3 ns). **156.25 MHz closed** (WNS +0.057 ns, URAM 32/48). **322 MHz open**: the internal `m_loc_idx -> sm_asel` path was split (CLO-322-02) and the book now fits (146.8k LUT), but the residual WNS is output-I/O-bound (SCD 2.695 ns + OBUF 2.334 ns at -2L). |
| 4 – CME MDP3 | Functional closed (14/14 DW=32 and DW=64, gate E 14/14). Criteria 5/7/10 closed. **Timing open**: the parser does not fit the XCKU3P (LUT over-utilization); repartition requires a spec addendum. |

Phase 3 is not presented as 322 MHz closed (the output-I/O limit keeps the
criterion open); the 156.25 MHz variant is the closed, evidence-backed claim.
Phases 1, 2 and 4 have their criteria closed with current evidence in their
respective `verify-report.md`; any reopened criterion requires red -> green and
fresh evidence before it is presented as closed again.

## Sources of truth

| Need | Authoritative location |
|---|---|
| Global rules, process, status | This file |
| Contract and criteria of a campaign | `specs/<campaign>/spec.md` and `gherkin/` |
| Evidence of a campaign | `specs/<campaign>/verify-report.md` |
| Reproducible checks | `verification/`, `scripts/verify/`, Makefiles and `synth/` |
| Setup and environment | `docs/DEVELOPMENT.md` |
| Executable close plan (index) | `docs/writeup/close-plan.md` |
| Close campaign contract (CLO-*) | `specs/cierre/spec.md` and `gherkin/` |
| Close campaign evidence | `specs/cierre/verify-report.md` |
| Verifiable numbers | `docs/writeup/marks.md` |
| Presentation document | `docs/writeup/pipeline-itch-uram.md` |

Historical reports may use an old stage name; they are dated evidence, not
operating instructions.

## Mandatory per-campaign process

1. **Specify.** Create or update `specs/<campaign>/spec.md` and its Gherkin
   scenarios before changing RTL or Python. Any decision that alters a contract
   is documented there.
2. **Build red -> green.** Add the failing test first; run the red; implement
   the minimal change; run the green. Never edit the spec to hide a failure.
3. **Verify.** Run the applicable gates A-G, paste the real output into
   `verify-report.md`, and explicitly state any gate not run. A gate without
   output is not passed.
4. **Review adversarially.** Re-run evidence from an angle that could refute it:
   a boundary vector, a mutant, a port consumer, or a timing report. A criterion
   closes only when all its applicable gates pass.

There are no magic commands or hidden flows; this file defines the process.

## Gates A-G

| Gate | Requirement |
|---|---|
| A – simulation | cocotb/Verilator or the area's unittest; any failure blocks. |
| B – compilation | `verilator --lint-only --Wall` on the touched RTL; Python compilable. |
| C – style | `verible-verilog-lint --rules_config_search` on the touched RTL (repo config `./.rules.verible_lint`). If not installed, declare NOT EXECUTED. |
| D – coverage | Literal spec<->test map and, if a tool exists, functional coverage. |
| E – mutation | Every mutant compiles and at least one test kills it; a broken mutant does not count. |
| F – completeness | `specs/gherkin-espejos.json` and test titles consistent with Gherkin. |
| G – rigor/timing | No raw data in Git, independent golden model, and Vivado WNS/TNS/resources when applicable. |

Reference commands:

```bash
# Golden model
python3 -m unittest discover -s golden_model/tests -t .

# RTL areas
make -C verification/testbenches/parser sim
make -C verification/testbenches/orderbook sim
make -C verification/testbenches/phase3 sim
make -C verification/testbenches/uram sim-uram
make -C verification/testbenches/mdp3 sim

# Phase-3 lint and static synthesis
verilator --lint-only --Wall --top-module itch_chain \
  rtl/itch_chain.sv rtl/parser/itch_parser.sv rtl/orderbook/orderbook.sv
python3 scripts/verify/synth_check.py
```

Each campaign fixes its full commands, thresholds and top in its spec or
Makefile. Do not relax `--Wall`, omit a mutant, or turn a data omission into a
PASS to close a campaign.

## Global rules

- Documentation and commits are written in English; Conventional Commits.
- Real market data is never versioned. Only synthetic samples and small vectors
  under `verification/vectors/`.
- The golden model is independent of the RTL: tests compare bit-exactly against
  it; never generate an oracle from the RTL under test.
- Before changing a port, signal, parameter or layout, find all its consumers.
  The effective `QB` of phase 3 is fixed in `itch_chain.sv` and in the Makefile,
  not only in submodule defaults.
- Do not introduce a FIFO, dependency or abstraction to hide missing throughput.
  Document the real backpressure and latency regime.
- The owner must be able to understand the state by reading the spec, the
  verify-report and this file, without reading HDL.

## Layout

| Directory | Contents |
|---|---|
| `golden_model/` | Reference ITCH and CME parser/model, vectors and Python tests. |
| `rtl/` | ITCH and MDP3 parsers, order book. |
| `verification/` | cocotb testbenches, vectors and Makefiles. |
| `scripts/verify/` | Mutation and reproducible validations. |
| `specs/` | Gherkin contracts and evidence reports per campaign. |
| `synth/` | Vivado Tcl/XDC and reports. |
| `docs/` | Setup, decisions and write-ups; does not define the operating process. |