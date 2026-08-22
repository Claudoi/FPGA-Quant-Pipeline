# cierre.feature — closure and improvement campaign (phases 0-4)
#
# Mirror of the "Acceptance criteria" of specs/cierre/spec.md.
# Does not replace the phases 1-4 Gherkin; adds the closure holes and the
# improvements. A failed improvement scenario is documented; no threshold is lowered.

# language: en
Feature: Verifiable pipeline closure and improvement without lowering thresholds
  As owner of the FPGA portfolio repo
  I want evidence of gates A-G over what is still open
  So that the project closes with honest numbers and attempts to beat the bar

  Scenario: CLO-DOC-01 — the current prose matches the evidence
    Given AGENTS.md, marcas.md, pipeline-itch-uram.md, latencia.md and the verify-report headers
    When they are compared against this campaign's reports and latency JSON
    Then no stale figure reappears (WNS +0.015, LUT 92.31 %, mean 44.5 ≤ 48, REP-02 open, MDP3 12/12+SKIP)
    And criterion 7 MDP3 is not declared open
    And 322 MHz is not asserted closed if WNS < 0

  Scenario: CLO-LAT-01 — the latency JSON is the current RTL's sim-lat run
    Given the HEAD RTL without this campaign's sm_asel split
    When make -C verification/testbenches/phase3 sim-lat runs
    Then verification/vectors/latency/latency_dw32.json is overwritten with that mean
    And total.mean_ciclos is the baseline of CLO-322-04 and CLO-LAT-02
    And LAT_THRESHOLD_CICLOS = 70 is not raised to hide a FAIL

  Scenario: CLO-RPT-01 — each Vivado variant writes its own directory
    Given fase3_synth.tcl and fase3_156mhz.tcl
    When 322 and 156 runs are launched
    Then the reports go to synth/reports/322mhz and synth/reports/156mhz
    And the 156 iter-16 run (WNS +0.057 ns) is archived before the next batch
    And synth_check.py demands distinct outdirs

  Scenario: CLO-SCH-01 — the XML↔RTL checker covers signature and localparams
    Given the pinned templates_FixBinary_v12.xml schema and rtl/parser/mdp3_parser.sv
    When python3 scripts/verify/check_mdp3_schema.py runs
    Then each structural localparam matches the XML
    And SCHEMA_ID = 1 and SCHEMA_VER = 12 are pinched
    And the XML absence is a FAIL, not a silent SKIP

  Scenario: CLO-M3T-00 — the MDP3 Vivado project exists and the tcl aborts on negative slack
    Given synth/mdp3_synth.tcl and the 3.103 ns and 6.400 ns XDCs
    When synth_check.py validates part, top mdp3_parser, periods and delays 0.0/1.0
    Then the static check passes
    And the tcl contains the MDP3 TIMING FAIL abort
    And the maximum output_delay is not lowered

  Scenario: CLO-M3T-01 — mdp3_parser closes timing at 322.265625 MHz
    Given the top mdp3_parser DW=32 over xcku3p-ffva676-2L-e
    When Vivado finishes route
    Then WNS >= 0 and TNS = 0
    And the MDP3 suite 14/14 DW=32 and DW=64 stays green
    And if the aligner was split, mutate_mdp3.py re-runs 14/14

  Scenario: CLO-M3T-02 — the 156.25 MHz fallback is not presented as 322
    Given that CLO-M3T-01 does not close
    When the DW=64 @ 6.400 ns run executes
    Then its WNS/TNS are pasted as the 156 variant
    And the verify-report declares 322 open if WNS 322 < 0

  Scenario: CLO-322-00 — the 322 timing red is on disk
    Given the current RTL and fase3_synth.tcl with outdir reports/322mhz
    When the batch finishes
    Then 322mhz's timing_impl.txt contains WNS, TNS and the critical path
    And m_loc_idx → sm_asel is confirmed or corrected to -3.458 ns

  Scenario: CLO-322-01 — phys_opt -retime is tried before touching the book
    Given the same RTL as CLO-322-00
    When the only delta is phys_opt_design -retime
    Then a WNS >= 0 closes criterion 10 without semantic change
    And a WNS < 0 is documented and not counted as closure

  Scenario: CLO-322-02 — the sm_asel split keeps BBO bit-exact
    Given the addendum of this spec published before the RTL
    When capture_emit_a registers the non-empty predicates one cycle and first_one the next
    Then sim-rtm and CHAIN-01 stay bit-exact against book.py
    And mutate_orderbook.py kills 31/31
    And the emission handshake stretches no more than one cycle

  Scenario: CLO-322-03 — criterion 10 at 322 MHz closes without loosening the XDC
    Given DW=32 K=64 QB=46 and period 3.103 ns
    When fase3_synth.tcl prints FASE3 SYNTH/IMPL OK
    Then WNS >= 0, TNS = 0, DRC 0, URAM 32/48
    And set_output_delay -max stays at 1.0 ns

  Scenario: CLO-322-04 — the post-split latency meets the re-derived threshold
    Given the CLO-LAT-01 histogram
    When sim-lat is re-run after CLO-322-02
    Then the mean is <= 70 cycles
    And the mean is <= baseline + 1.0 cycle if the emit gained a stage
    And the JSON is re-persisted

  Scenario: CLO-322-05 — the ladder does not loosen the gate
    Given that CLO-322-03 does not close after the split
    When floorplan, BBO_W=64 and extra book output pipeline are applied in that order
    Then each rung leaves an archived run
    And output_delay is not lowered
    And an extra output pipeline re-measures CLO-322-04 before amending RTM-LAT-01

  Scenario: CLO-322-99 — denying 322 is an addendum, not a PASS
    Given that the ladder is exhausted with WNS < 0
    When the owner redefines phase-3 criterion 10 to 64b @ 156.25 MHz
    Then the addendum lives in specs/fase3-optimizacion/spec.md and in specs/cierre/spec.md
    And the current 322 WNS is cited as open
    And timing-closed at 322 MHz is not asserted

  Scenario: CLO-REG-01 — the phases 1-4 regression stays green
    Given a parser, book or chain change
    When the spec criterion-15 suites run
    Then phase3, parser, orderbook, uram and golden pass
    And --Wall is not loosened
    And a SKIP for absent pcap is informed and does not count as a real-data PASS

  Scenario: CLO-LUT-01 — LUT as Logic <= 95 % is attempted
    Given the current 95.13 % at 156 MHz
    When a 156 or 322 run of this campaign closes
    Then LUT as Logic <= 95 % is an improvement PASS
    And a value > 95 % is reported without reopening the already-closed 156 WNS

  Scenario: CLO-WNS-01 — more 156.25 MHz margin is attempted
    Given the current WNS +0.057 ns
    When fase3_156mhz.tcl is re-run without changing semantics
    Then a WNS > +0.057 ns with TNS 0 is recorded as an improvement
    And the same +0.057 ns does not force a speculative RTL change

  Scenario: CLO-LAT-02 — the representative mean is not degraded
    Given the CLO-LAT-01 baseline and the same 20-symbol subset
    When batch 2 finishes
    Then the mean does not exceed the baseline except the +1 structural of CLO-322-02
    And <= 48 is not pursued again by trimming the feed

  Scenario: CLO-DEP-01 — the top-N depth is bit-exact all day
    Given the loc13 >P peak (event 14461, 420 levels)
    When the URAM tail-hash is implemented
    Then CHAIN-01 compares depth bit-exact also after the first re-entry
    And the BBO stays bit-exact
    And o_mem stays at 32 URAM or the extra is documented in a resource addendum

  Scenario: CLO-CI-01 — CI reproduces simulation without pcaps
    Given a push to GitHub Actions
    When golden, parser, orderbook, synthetic phase3, mdp3 and synth_check.py run
    Then the workflow is green
    And no real pcaps are versioned nor downloaded

  Scenario: CLO-4B-01 — the MDP3 book emits a BBO bit-exact against golden
    Given Annex-M records of templates 46/47/52/53
    When a dedicated 4b campaign feeds an order book
    Then the BBO matches bit-exact against the MDP3 book golden
    And the ITCH RTL is not mixed into the same module

  Scenario: CLO-PUB-01 — the write-up cites current evidence
    Given pipeline-itch-uram.md and marcas.md
    When this campaign's marks are published
    Then each figure points to a verify-report or a Vivado report
    And the honest limits (absent MAC, 20 symbols, 322 open or closed per WNS) are written