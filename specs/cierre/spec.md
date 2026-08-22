# cierre (closure and improvement campaign — phases 0–4)

> Contract of **all** the remaining work to close the project and, without
> lowering any threshold, **try to beat it**. It replaces the prose of
> `docs/writeup/close-plan.md` as the operational source of truth (that file
> stays as an index; the criteria live here).
>
> Cut-off date of the starting state: **2026-08-20**, HEAD `69a5701`. Nothing in
> this document is stated closed: the gates of *this* campaign start at NOT
> EXECUTED (`verify-report.md`).

## Goal

Leave the repository in a state where a third party (engineer or agent) can read
`AGENTS.md` + this spec + `verify-report.md` and state, **with real outputs**,
that:

1. Phases 0–2 and the functional of 3–4 stay green (not reopened).
2. The **blocking** holes (evidence hygiene, XML↔RTL checker, MDP3 timing,
   criterion 10 @ 322 MHz or its explicit amendment) are closed with the
   applicable A–G gates.
3. It was **attempted** to beat the current bar (more WNS margin, LUT ≤ 95 %,
   no-worse latency, exact depth, CI, MDP3 book) without hiding failures or
   trimming the representative corpus.

It is not a rewrite of the master plan. It is the campaign that **closes** what
is open and **pushes** what silicon and the golden permit.

## Scope

### In scope — blocking (closure DoD)

- **Evidence hygiene**: align stale docs, re-persist latency, archive Vivado
  reports per variant.
- **PENDING-C**: `scripts/verify/check_mdp3_schema.py` (phase-4 gate G,
  criterion 9 / `M3-SCH-01`).
- **PENDING-B**: Vivado MDP3 project (`synth/mdp3_synth.tcl` + XDC + reports)
  over `mdp3_parser`.
- **PENDING-A**: phase-3 criterion 10 at **32-bit @ 322.265625 MHz** (WNS ≥ 0,
  TNS = 0) **or** an explicit amendment of criterion 10 signed in this spec
  (156.25 MHz = industrial DoD; 322 stays an open chapter). Without that
  amendment, 156 **does not** close criterion 10.

### In scope — improvement (attempt; does not block the DoD if it fails with evidence)

Each improvement has its own criterion. A FAIL is documented; **no** threshold is
lowered to turn it into a PASS.

- Retiming `sm_asel` and `phys_opt_design -retime` to **close 322**.
- LUT as Logic **≤ 95 %** post-route in 156 and, if it closes, in 322.
- 156 WNS margin **> +0.057 ns** without touching semantics.
- Post-change latency **≤ 70** and **no worse** than the `CLO-LAT-01` mean plus
  the documented structural cycle of the split (max +1 emit cycle).
- Top-N depth **exact** on the day (option B: tail-hash in URAM; iter-13
  measure).
- Simulation CI without pcaps.
- Order-book port to MDP3 (campaign 4b, Annex M).
- Public write-up coherent with the current numbers.

### Out of scope (non-goals; not presented as work of this campaign)

- 10G MAC, Ethernet, IP, UDP (the repo starts at the decapsulated MoldUDP64).
- Full Nasdaq book (the book is the 20-symbol subset).
- iLink 3, A/B arbitration, TCP recovery, multi-channel demux.
- Real DataMine data (paid). Optional MDP3 REPLAY-03 if there is ever a local
  pcap; never versioned.
- AXI/PCIe host interface (historical master non-goal).
- Renaming phases 1–3 RTL constants for gate C verible (policy: closed RTL,
  documented convention findings, not touched).
- Lowering `set_output_delay -max 1.0` of the XDC, silencing `--Wall`, omitting
  mutants, or turning a SKIP-for-absent-pcap into a PASS.
- Reopening phases 0–2 except a red regression caused by a change of this
  campaign.

## Constraints

- **Part:** `xcku3p-ffva676-2L-e` (decision 002). Vivado ML 2023.2 on Windows
  (`C:\Xilinx\Vivado\2023.2\bin\vivado.bat`). Simulation on WSL (cocotb 2.0.1,
  Verilator 5.046; Python < 3.14).
- **Effective QB** of phase 3: `rtl/itch_chain.sv` and tcl/Makefile generics
  (`QB=46`, `K=64`, `DW` per variant). Do not change submodule defaults and
  believe the chain noticed.
- **Non-negotiable amendments 13/15** without a re-campaign: P=32 push-out; depth
  bit-exact up to ev. 14461 and a price subset after; BBO always bit-exact;
  RTM-LAT-01 mean ≤ 70 cycles; K=64/OW=130.
- **Independent golden.** Oracle = Python. Never generate a reference from the
  DUT.
- **G0.** Pcaps and schema XML out of Git. XML checker fail-closed if the local
  schema is absent.
- **One report directory per run.** `synth/reports/` today overwrites 322 with
  156. This campaign demands variant subdirs **before** the next run.
- **Red→green and gates A–G** (`AGENTS.md`). A gate without output is not passed.
- **Spanish + Conventional Commits.** One commit per verifiable milestone.

## Starting state (evidence vs prose)

Read against the repo on 2026-08-20. Distinguish **EVIDENCE** from **stale**.

| Item | State that can be asserted | Artifact |
|---|---|---|
| Phase 0 | CLOSED | golden + real day |
| Phase 1 | CLOSED; REP-02 9 stalls ≤ 24, 32/32 | `specs/fase1-parser-rtl/verify-report.md` |
| Phase 2 | CLOSED functionally | 14/14 historical; 17 current tests; WSL 13/14+SKIP |
| Phase 3 functional | CLOSED; 17,484 bit-exact BBO | addendum iter 13/15 |
| Phase 3 @ 156.25 MHz | CLOSED WNS **+0.057 ns**, TNS 0, WHS +0.021, URAM 32/48, IOB 194/256 | `synth/reports/timing_impl.txt` 2026-08-20 07:40 |
| Phase 3 LUT 156 | **154,791/162,720 = 95.13 %** (as Logic 95.10 %) | `synth/reports/util_impl.txt` |
| Phase 3 @ 322 MHz | OPEN WNS **−3.458 ns** `m_loc_idx_reg[1] → sm_asel_reg[0]` | iter-16 prose; **322 reports not on disk** (overwritten) |
| Phase 4 functional | CLOSED 14/14, E 14/14, C 0 findings | phase-4 verify-report (table L446–459; **ignore** the duplicated L461–474) |
| Phase 4 timing | NOT EXECUTED | no `synth/mdp3_synth.tcl` exists |
| XML↔RTL checker | unittest `test_m3sch01_*` exists; **no** `check_mdp3_schema.py`; the unittest does **not** pinch `SCHEMA_ID`/`SCHEMA_VER` | `golden_model/tests/test_mdp3.py` |
| Latency JSON | `"mean_ciclos": 44.318` | `verification/vectors/latency/latency_dw32.json` |
| Latency prose | mean 65.5, threshold ≤ 70 | phase-3 spec L859–872; `LAT_THRESHOLD_CICLOS = 70` |
| Wrapper 322 | `depth_tdata` already trimmed to 32 b; outputs already registered (iter 11) | `synth/itch_chain_synth.sv` |
| `phys_opt_design` | called **without** `-retime` | `synth/fase3_synth.tcl` L59 |
| Docs stale | `marks.md`, `pipeline-itch-uram.md`, `latency.md`, phase-3 verify-report header, `AGENTS.md` preamble L12–14, `synth/reports/README.md` | do not use as current numbers |

**Incoherence that this campaign closes first:** spec/AGENTS cite 65.5 cycles
persisted in the JSON; the JSON has 44.318. Until `CLO-LAT-01` the mean 65.5 is
**pending verification**.

## Surface that can be touched

| Area | Files | When |
|---|---|---|
| Docs | `AGENTS.md`, `docs/writeup/*`, verify-report headers, `synth/reports/README.md` | batch 0 and batch 3 |
| Latency | `verification/vectors/latency/latency_dw32.json`, `verification/testbenches/phase3/test_lat32.py` | batch 0 and post-A |
| Synth layout | `synth/fase3_synth.tcl`, `synth/fase3_156mhz.tcl` (outdir per variant) | batch 0, **before** any run |
| Checker | **create** `scripts/verify/check_mdp3_schema.py`; touch `golden_model/tests/test_mdp3.py` | batch 1 |
| MDP3 synth | **create** `synth/mdp3_synth.tcl`, `synth/constraints/mdp3_322mhz.xdc`, `synth/constraints/mdp3_156mhz.xdc`; extend `scripts/verify/synth_check.py` | batch 1 |
| Book RTL | `rtl/orderbook/orderbook.sv` (`capture_emit_a` L1200–1221, regs `sm_asel`/`sm_bsel`, emit FSM) | batch 2, **after** spec addendum `CLO-322-02` |
| Wrapper | `synth/itch_chain_synth.sv` only if `BBO_W` is needed at 322 | batch 2 ladder, not first |
| Phase-3 tests | `test_rtm32.py`, `test_lat32.py`, uram SEC-URAM-03 | batch 2 |
| CI | **create** `.github/workflows/sim.yml` | improvement, batch 3 |
| 4b | RTL book MDP3 + golden + tests (new campaign if undertaken) | stretch improvement |

Search **all** consumers of a port/param before changing it.

## Acceptance criteria (Definition of Done)

The Gherkin IDs are literal. A criterion only closes if its applicable gates pass
with output in `specs/cierre/verify-report.md`.

### Block 0 — hygiene (blocks any new numerical claim)

1. [ ] **CLO-DOC-01 — prose = evidence.** `AGENTS.md` (preamble L12–14 and date),
     `docs/writeup/marks.md`, `docs/writeup/pipeline-itch-uram.md`,
     `docs/writeup/latency.md`, `synth/reports/README.md`, header verdict of
     `specs/fase3-optimizacion/verify-report.md`, duplicated table of
     `specs/fase4-mdp3-parser/verify-report.md` L461–474, and stale comments
     (`rtl/parser/mdp3_parser.sv` L79–80, `rtl/itch_chain.sv` L9–11) match the
     numbers of §Starting state **after** `CLO-LAT-01` and the runs of this
     campaign. Do not reintroduce WNS +0.015, LUT 92.31 %, latency 44.5 ≤ 48,
     REP-02 open, MDP3 12/12+SKIP, or criterion 7 MDP3 open.
     — Gherkin: `cierre.feature` §CLO-DOC-01

2. [ ] **CLO-LAT-01 — latency JSON re-persisted.** `make -C
     verification/testbenches/phase3 sim-lat` over the **current** RTL (before
     touching `sm_asel`). The JSON
     `verification/vectors/latency/latency_dw32.json` is overwritten with that
     run. `total.mean_ciclos` is the mean the rest of the criteria use as
     **baseline**. If the test `LAT_THRESHOLD_CICLOS = 70` fails, it is
     investigated; **no** threshold raise to hide it. If the mean is ~44.3, the
     65.5 prose is corrected. If ~65.5, the prose is accredited.
     — §CLO-LAT-01

3. [ ] **CLO-RPT-01 — reports per variant.** `fase3_synth.tcl` writes
     `synth/reports/322mhz/`; `fase3_156mhz.tcl` writes `synth/reports/156mhz/`.
     The current content of `synth/reports/*.txt` (run 156 iter 16, WNS +0.057) is
     copied to `synth/reports/156mhz/` **before** the next batch. The `.dcp` are
     not versioned if heavy; the `timing_*.txt`, `util_*.txt`, `ram_*.txt`,
     `drc_*.txt` are. `synth_check.py` demands distinct outdirs.
     — §CLO-RPT-01

### Block 1 — PENDING-C (XML↔RTL checker)

4. [ ] **CLO-SCH-01 — schema gate G.** `python3
     scripts/verify/check_mdp3_schema.py` compares the pinned XML
     (`templates_FixBinary_v12.xml`, id=1 version=12, md5
     `e6eb6c60b46e61dc154537879b3d18d2`) against **all** the structural
     `localparam`s of `mdp3_parser.sv`: the ones `test_m3sch01_*` already pinches
     **plus** `SCHEMA_ID=1`, `SCHEMA_VER=12`, `PKT_HDR=12`, `MAX_MSG=256`,
     `EXP_BYTE`. Fail-closed if the XML is absent. The existing unittest delegates
     to the script (a single table). `PASS` output with empty diff pasted in the
     verify-report. Phase-4 criterion 9 stops saying "checker pending".
     — §CLO-SCH-01 (mirror and extension of `M3-SCH-01`)

### Block 2 — PENDING-B (MDP3 timing)

5. [ ] **CLO-M3T-00 — artifacts.** `synth/mdp3_synth.tcl`,
     `synth/constraints/mdp3_322mhz.xdc` (period 3.103 ns) and
     `synth/constraints/mdp3_156mhz.xdc` (6.400 ns) exist. Top `mdp3_parser`
     (without wrapper: the module fits in 256 IOB). Part `xcku3p-ffva676-2L-e`.
     Generics `DW=32` and a `DW=64` regression run. The tcl aborts with
     `MDP3 TIMING FAIL` if there is setup slack < 0 (same pattern as phase 3).
     Outdir `synth/reports/mdp3/322mhz` and `.../mdp3/156mhz`. `synth_check.py`
     covers part, top, period, min/max delays, abort. I/O delays: min 0.0 / max
     1.0 ns. **No** max lowering.
     — §CLO-M3T-00

6. [ ] **CLO-M3T-01 — 32-bit @ 322 MHz.** Post-route run WNS ≥ 0, TNS = 0.
     Reports versioned. MDP3 suite **14/14** DW=32 and DW=64 intact
     (`make -C verification/testbenches/mdp3 sim` and `sim-dw64`). If the RTL is
     split (aligner/shift), spec addendum **before**, red→green, and gate E 14/14
     re-run (`python3 scripts/verify/mutate_mdp3.py`).
     — §CLO-M3T-01

7. [ ] **CLO-M3T-02 — 64-bit @ 156.25 MHz fallback.** If `CLO-M3T-01` does not
     close, the 156 run **is** executed. A green 156 is **not** presented as a
     closed 322. Both numbers live in the phase-4 verify-report and in this
     campaign's.
     — §CLO-M3T-02

### Block 3 — PENDING-A (criterion 10 @ 322 MHz)

The current critical path (iter-16 prose, **reconfirm** in the first 322 run of
this campaign) is internal:

```
u_book/m_loc_idx_reg[1]/C -> u_book/sm_asel_reg[0]/D
```

in `capture_emit_a`: mux `lv_qty[m_loc_idx*2*P + i]` → `!=0` → `first_one` →
`sm_asel` **in the same cycle**. The `first_one` tree already exists (iter 9); it
is not registered apart from the mux.

**Already done, do not repeat:** `depth_tdata` trim to 32 b; wrapper output
pipeline (iter 11); `phys_opt_design` without `-retime`.

8. [ ] **CLO-322-00 — 322 baseline run.** With outdir `reports/322mhz/` and the
     RTL **unchanged**, `fase3_synth.tcl` produces WNS/TNS/critical-path **on
     disk**. Confirms or corrects −3.458 ns. This run is the campaign's timing
     red.
     — §CLO-322-00

9. [ ] **CLO-322-01 — phys_opt -retime without RTL change.** A run whose only
     delta is `phys_opt_design -retime` (and/or a second `phys_opt_design`). If
     WNS ≥ 0: criterion 10 closes **without** touching the book (max gain: zero
     semantic risk). If not: the new WNS is documented and it moves to
     `CLO-322-02`. A still-negative WNS is not counted as closure.
     — §CLO-322-01

10. [ ] **CLO-322-02 — `m_loc_idx → sm_asel` split.** Addendum in **this** spec
      **before** the RTL: cycle *n* registers `nza_next`/`nzb_next` (and caps);
      cycle *n+1* `first_one` → `sm_asel`/`sm_bsel`. BBO and depth semantics
      **identical**. Red: `sim-rtm` / CHAIN-01 stay the bit-exact mirror; if the
      FSM gains a state, an RTM test fails against the prior HEAD or a
      `CLO-322-02` is added fixing the +1 cycle. Green: minimal RTL. Full
      regression (below). Gate E orderbook 31/31.
      — §CLO-322-02

11. [ ] **CLO-322-03 — criterion 10 closed.** `fase3_synth.tcl` (DW=32, K=64,
      QB=46) prints `FASE3 SYNTH/IMPL OK`. WNS ≥ 0, TNS = 0, DRC 0, URAM
      **32/48**. Reports in `synth/reports/322mhz/`. The `fase3_322mhz.xdc` XDC
      **does not** change delays. `BBO_W` stays 128 unless ladder `CLO-322-05`.
      — §CLO-322-03

12. [ ] **CLO-322-04 — post-split latency.** `sim-lat` re-run. Mean ≤ 70. Mean ≤
      baseline `CLO-LAT-01` + 1.0 cycle if the split adds an emit stage; if it
      exceeds that, investigated (70 is not raised). JSON re-persisted.
      `docs/writeup/latency.md` updated.
      — §CLO-322-04

13. [ ] **CLO-322-05 — ladder if 11 is not enough (fixed order).**
      (a) Floorplan `Pblock` of 32 URAM + slice of the `u_book` selector.
      (b) `BBO_W=64` also at 322 (addendum 11b; does not shorten `sm_asel`, only
      residual I/O).
      (c) Extra **book output** pipeline (not the wrapper's): only with a
      `CLO-322-04` / RTM-LAT-01 addendum if the mean moves.
      **Forbidden** to lower `output_delay`. Each rung is an archived run. If
      after (a)(b)(c) WNS < 0: **not** declared closed; `CLO-322-99` activates.
      — §CLO-322-05

14. [ ] **CLO-322-99 — denial amendment (only with owner decision).** If 11–13 do
      not close, the owner may redefine phase-3 criterion 10: DoD = **64b @
      156.25 MHz = linear 10G** (already green, WNS +0.057); 322 stays an open
      chapter. That is an **explicit addendum** in
      `specs/fase3-optimizacion/spec.md` **and** here, with the current 322 WNS in
      the verify-report. **Not** a 322 PASS.
      — §CLO-322-99

### Block 4 — regression that any RTL change must leave green

15. [ ] **CLO-REG-01 — suites.** After touching parser/book/chain: phase3 (`sim`,
      `sim-hash`, `sim-depth`, `sim-hard`, `sim-parser`, `sim-chain`,
      `sim-chain-nd3`, `sim-lat`, `sim-rtm`, `sim-rtm64`); parser 32/32; orderbook
      17/17 (a replay SKIP for absent pcap is **informed**, not turned into a
      PASS); uram `sim-uram` + `sim-anx`; golden
      `python3 -m unittest discover -s golden_model/tests -t .`; MDP3 14/14 if
      `mdp3_parser.sv` was touched. Lint: `verilator --lint-only --Wall
      --top-module itch_chain` over the three chain SV. Mutation:
      `mutate_parser.py`, `mutate_orderbook.py`, and `mutate_mdp3.py` if
      applicable. Gherkin: `python3 scripts/verify/check_itch_gherkin.py`.
      — §CLO-REG-01

### Block 5 — improvements (try to beat the bar; documented FAIL ≠ false closure)

16. [ ] **CLO-LUT-01 — LUT ≤ 95 %.** Post-route, LUT as Logic ≤ 95 % in 156
      **and** in 322 if it closes. Today 156 is at **95.13 %**: the current 156
      closure is WNS/TNS, not LUT. This improvement **attempts** to go below 95 %
      (retiming, fewer replicas, no semantic trimming). If not reached, 95.13 %
      (or the new value) is reported and the 156 WNS is **not** reopened.
      — §CLO-LUT-01

17. [ ] **CLO-WNS-01 — more 156 margin.** Re-run 156 after A.0/tcl outdir. Goal:
      WNS > +0.057 ns with TNS 0, URAM 32/48, DRC 0, **without** changing RTL
      semantics. If the outdir-only run gives the same +0.057, no speculative
      change is forced.
      — §CLO-WNS-01

18. [ ] **CLO-LAT-02 — do not degrade, try to improve.** After the closure (or
      denial) of 322, the `sim-lat` mean is ≤ baseline `CLO-LAT-01` except the
      +1 structural of `CLO-322-02`. **No** new pursuit of ≤ 48 trimming the feed:
      the iter-7 ≤ 48 was a non-representative stretch (amendment 15). Improve =
      fewer cycles on the **same** 20-symbol subset / same 2,289 NOII, or a lower
      p99, with a deterministic histogram (SEC-LAT-01).
      — §CLO-LAT-02

19. [ ] **CLO-DEP-01 — exact depth (option B).** Tail-hash in URAM so the top-N is
      bit-exact **all day**, not only up to ev. 14461. Iter-13 measure: ~1,465
      rebalances, tail ≤ 388 levels. Phase-3 spec is amended **before** the RTL.
      CHAIN-01 depth returns to fully bit-exact. BBO does not change. Extra URAM
      is documented; 32/48 of `o_mem` is not broken without a resource addendum.
      — §CLO-DEP-01

20. [ ] **CLO-CI-01 — simulation CI.** GitHub Actions workflow: unittest golden,
      `make` parser/orderbook/phase3 (synthetic), mdp3 DW=32/64, `synth_check.py`,
      `check_mdp3_schema.py` (fail-closed SKIP of the XML is declared). **No**
      pcaps. An omitted replay is not a real-data PASS.
      — §CLO-CI-01

21. [ ] **CLO-4B-01 — MDP3 book.** Campaign 4b: an order book consumes Annex M
      (templates 46/47/52/53) and emits a BBO bit-exact against an MDP3 book
      golden. **New** spec `specs/fase4b-mdp3-book/` if undertaken; not mixed with
      the ITCH RTL. Synthetic corpus.
      — §CLO-4B-01

22. [ ] **CLO-PUB-01 — candidacy write-up.** `docs/writeup/pipeline-itch-uram.md`
      and `marks.md` with **this** campaign's numbers, honest limits (absent MAC,
      20 symbols, 322 open or closed per evidence, real latency JSON). CV
      artifact. Does not claim 322 closed if WNS < 0.
      — §CLO-PUB-01

## Verification

| Criterion | How it is tested | Gates |
|---|---|---|
| CLO-DOC-01 | diff of prose vs §State table + current reports | G (documentary rigor) |
| CLO-LAT-01 | `make -C verification/testbenches/phase3 sim-lat`; committed JSON | A, G |
| CLO-RPT-01 | `python3 scripts/verify/synth_check.py` demands outdirs; `Test-Path` of `156mhz/` | static B/G |
| CLO-SCH-01 | `python3 scripts/verify/check_mdp3_schema.py`; MDP3 unittest | A, B, D, F, G |
| CLO-M3T-00 | `synth_check.py` + existence of tcl/xdc | static B, G |
| CLO-M3T-01/02 | Vivado batch; `make .../mdp3 sim{,-dw64}`; mutate if RTL | A, B, C, E, G |
| CLO-322-00/01/03/05 | Vivado `fase3_synth.tcl`; reports in `322mhz/` | G |
| CLO-322-02 | spec→red `sim-rtm`/CHAIN-01→RTL→green; mutate_orderbook | A, B, E, F |
| CLO-322-04 / CLO-LAT-02 | `sim-lat` + JSON | A |
| CLO-322-99 | dated addendum in **two** specs + cited 322 WNS | documentary G |
| CLO-REG-01 | commands of criterion 15 | A–F |
| CLO-LUT-01 / CLO-WNS-01 | `util_impl.txt` / `timing_impl.txt` of the run | G |
| CLO-DEP-01 | CHAIN-01 depth bit-exact post-14461 | A, E, F |
| CLO-CI-01 | green workflow on a push without secrets or pcaps | A/B in CI |
| CLO-4B-01 | own campaign 4b | A–G of that campaign |
| CLO-PUB-01 | review: every figure cites verify-report or report | G |

**Reference regression (WSL), copy/paste:**

```bash
python3 -m unittest discover -s golden_model/tests -t .
make -C verification/testbenches/parser sim
make -C verification/testbenches/orderbook sim
make -C verification/testbenches/phase3 sim
make -C verification/testbenches/phase3 sim-hash
make -C verification/testbenches/phase3 sim-depth
make -C verification/testbenches/phase3 sim-hard
make -C verification/testbenches/phase3 sim-parser
make -C verification/testbenches/phase3 sim-chain
make -C verification/testbenches/phase3 sim-chain-nd3
make -C verification/testbenches/phase3 sim-lat
make -C verification/testbenches/phase3 sim-rtm
make -C verification/testbenches/phase3 sim-rtm64
make -C verification/testbenches/uram sim-uram
make -C verification/testbenches/mdp3 sim
make -C verification/testbenches/mdp3 sim-dw64
verilator --lint-only --Wall --top-module itch_chain \
  rtl/itch_chain.sv rtl/parser/itch_parser.sv rtl/orderbook/orderbook.sv
python3 scripts/verify/mutate_parser.py
python3 scripts/verify/mutate_orderbook.py
python3 scripts/verify/mutate_mdp3.py
python3 scripts/verify/check_itch_gherkin.py
python3 scripts/verify/synth_check.py
```

**Vivado (Windows, cwd `synth/`):**

```text
C:\Xilinx\Vivado\2023.2\bin\vivado.bat -mode batch -source fase3_synth.tcl
C:\Xilinx\Vivado\2023.2\bin\vivado.bat -mode batch -source fase3_156mhz.tcl
C:\Xilinx\Vivado\2023.2\bin\vivado.bat -mode batch -source mdp3_synth.tcl
```

## Geless contracts (can break with green suites)

1. **Overwriting 156 reports with a 322 run** and citing WNS +0.057 as current.
   Guardrail: `CLO-RPT-01`.
2. **Presenting 156 as the closure of criterion 10 @ 322.** Guardrail:
   `CLO-322-03` vs `CLO-322-99`.
3. **Raising RTM-LAT-01 above 70** to absorb a pipeline. Guardrail: `CLO-322-04`;
   an addendum is needed, not a silent edit.
4. **JSON 44.318 cited as 65.5.** Guardrail: `CLO-LAT-01`.
5. **Checker that does not fail without XML.** Guardrail: fail-closed in
   `CLO-SCH-01`.
6. **Mutant that does not alter an observable** counted as killed. Precedent
   `SIZE-PACKET` / `DISCARD-NORESET`.
7. **Parser default QB ≠ `itch_chain` QB.** Guardrail: tcl and Makefile generics.

## Execution order (batches)

One Vivado at a time. Sim on WSL, synth on Windows.

```
Batch 0  CLO-RPT-01 → CLO-LAT-01 → (CLO-DOC-01 partial, without 322/MDP3 numbers)
Batch 1  CLO-SCH-01 → CLO-M3T-00 → CLO-M3T-01 (∥ CLO-M3T-02 if 01 fails)
Batch 2  CLO-322-00 → CLO-322-01 → [if not] CLO-322-02 → CLO-322-03
         → CLO-322-04 → CLO-REG-01
         → [if not] CLO-322-05 → [if not] CLO-322-99 (owner)
Batch 3  CLO-DOC-01 complete + CLO-PUB-01 + CLO-CI-01
Improv.  CLO-LUT-01, CLO-WNS-01, CLO-LAT-02, CLO-DEP-01, CLO-4B-01
         (parallel among themselves when they do not touch the same RTL)
```

**Parallel allowed:** batch 1 ∥ batch-2 start (`CLO-322-00`) if there is a single
Vivado queue. **Not parallel:** two tcls writing the same `reports/`.

**Relative effort:** batch 0 S · batch 1 C=S B=M · batch 2 L/high · batch 3 S–M ·
CLO-DEP-01 L · CLO-4B-01 XL.

## 322 ladder (engineering detail)

Goal: split the `m_loc_idx → first_one(nza_next)` path that today lives entirely
in `capture_emit_a` (`rtl/orderbook/orderbook.sv` ~L1200–1221).

1. **Measure** (`CLO-322-00`): fanout of `m_loc_idx`, logic levels, % route vs
   logic in `timing_impl.txt`.
2. **phys_opt -retime** (`CLO-322-01`) without RTL.
3. **1-cycle split** (`CLO-322-02`): register non-empty predicates **after** the
   per-symbol mux and **before** `first_one`. Same technique as iter 8 (`lv_eq →
   lv2_mode` split 2a/2b). **Chosen option:** A registers caps+predicates; B does
   `first_one` + select over those registers. Zero extra states, unchanged
   `ST_EMIT_C` handshake. A dedicated `ST_EMIT_A1` measured **+5.1 cycles** of
   mean (not +1): the extra `nx_recv` changed the `nx` cut and the slower book
   refilled QB — discarded. The `m_loc_idx → mux → !=0` path stays in A;
   `first_one → cap mux` in B.
4. **Do not** precompute `first_one` for the 20 symbols in parallel (LUT already
   at 95 %).
5. **Do not** touch `o_mem` nor the URAM inference pattern (single statement
   `if (wr_en) o_mem[wr_addr] <= wr_data`).
6. If the split closes with a marginal WNS (< 0.050 ns): do not declare slack;
   cite the real WNS.
7. **Amendment 16 (probe bug uncovered by the split).** The +1 `nx_recv()` of
   `ST_EMIT_A1` changed the cut point of the next message in `nx`: an 8 B `D` cut
   with `nx_bi=1` (1 sole body word, message **not completed**) and `swap_next`
   armed the probe with `{nx_body_acc[0], nx_body_acc[1]}` — word 1 **stale** of
   the previous message → corrupt oref → `pr_found=0` → anomaly and lost BBO event
   (17,483 vs 17,484, documented red). The swap arm required fewer body words than
   it consumes: DW=32 old `nx_bi>=1` (uses words 0–1) and new `nx_bi>=3` (uses
   words 2–3); DW=64 old unconditional (uses word 0) and new `nx_bi>=1` (uses word
   1). **Minimal fix (no semantic change):** the arm validity is `nx_done ||
   nx_bi >= words_needed` — the last body word does not increment `nx_bi`
   (`nx_recv` sets `nx_done` without counting), so a **complete** message stays
   with `nx_bi = nwords-1` and all its words valid, and a **cut** message only
   arms with the words really received: DW=32 old `nx_done || nx_bi>=2`, new
   `(nx_done && nx_bi>=3) || nx_bi>=4`; DW=64 old `nx_done || nx_bi>=1`, new
   `(nx_done && nx_bi>=1) || nx_bi>=2`. The deferred arm falls in `ST_BODY`
   (`bi==1`/`bi==3` DW=32; `bi==0`/`bi==1` DW=64), which always arms with valid
   bus words. Does not touch the split's +1 cycle nor the `cur_runs_needed` anchor
   (fixed at the `ST_BODY` arm when the swap does not arm). Green: 17,484
   bit-exact BBO, anomaly=0 and full regression `CLO-REG-01`.
   — §CLO-322-02 amendment 16

## Questions to the owner (they change which criteria apply)

1. **Is there budget to deny 322 (`CLO-322-99`) and stay on 156?** If yes
   **before** batch 2, batch 2 reduces to `CLO-322-00` (on-disk evidence) +
   addendum. If not, batch 2 is mandatory.
2. **Do `CLO-DEP-01` and `CLO-4B-01` enter this campaign or stay eternal
   stretch?** Default of this spec: **stretch**. They do not block the closure
   DoD (criteria 1–15 + decision 1).
3. **Is CI (`CLO-CI-01`) a batch-3 DoD or stretch?** Default: batch-3
   **improvement**; the batch-3 DoD is `CLO-DOC-01` + `CLO-PUB-01`.
4. **Are `.dcp` versioned?** Default: no.

Without an answer, the executor assumes the defaults and does **not** undertake
4b nor tail-hash.

## Summarized DoD

**Closure (must):** criteria 1–7, 8, 15, and **(11 and 12) or 14**.
**Improvement (attempts):** 9–10 (preferred path toward 11), 16–22.
**Never:** a laxer threshold, a laxer XDC, a laxer `--Wall`, an RTL-derived
oracle, a pcap in Git, 322 presented as closed with WNS < 0.

## Changelog

- **2026-08-21 (amendment 17):** the dedicated `ST_EMIT_A1` is discarded. Mean
  post-A1 **70.622** vs baseline CLO-LAT-01 **65.521** (+5.1, not +1). Cause: the
  extra `nx_recv` of A1 changes the `nx` cut (and uncovered the amendment-16 bug)
  and the book 1 cycle slower refills QB. Split CLO-322-02 stays: A registers
  caps+predicates; B does `first_one` → `sm_bsel`/`sm_asel` (registered); C muxes
  caps by that REGISTERED index + changed + cross + handshake. Zero extra states.
  A first fold with the index mux combinational in B inflated LUT to 161.8k (>
  162.7k of the part, UTLZ-1); with the registered index the book drops to
  **146.8k**. Amendment 16 (arm `nx_done || nx_bi >= words_needed`) is kept.
  CLO-322-04 contract: mean ≤ 66.521 (measured 65.521).
- **2026-08-20 (amendment 16):** probe-arm fix in `swap_next` uncovered by the
  CLO-322-02 split (documented red `sim-chain` 17,483 vs 17,484): the conditions
  demanded fewer body words than the arm consumes (stale at DW=32 and DW=64). See
  322 ladder point 7. Does not alter the CLO-322-02 contract (bit-exact BBO/depth,
  +1 cycle, latency ≤ 66.521) nor criterion 10.
- **2026-08-20:** creation. Freezes the verified starting state and the
  closure+improvement contract. Zero RTL. Gates of this campaign: NOT EXECUTED.