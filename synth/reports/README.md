# synth/reports — Vivado run history (criterion 10)

> **CLO-RPT-01 (2026-08-20): per-variant reports.** Each tcl writes to its own
> directory and a run never overwrites another:
>
> - `synth/reports/322mhz/` — variant **32b @ 322.265625 MHz**
>   (`fase3_synth.tcl`, 3.103 ns period).
> - `synth/reports/156mhz/` — variant **64b @ 156.25 MHz**
>   (`fase3_156mhz.tcl`, 6.400 ns period). The iter-16 156 run (WNS +0.057 ns,
>   TNS 0, URAM 32/48, DRC 0) was archived here on 2026-08-20 before the next
>   batch.
>
> The `.dcp` files are not versioned (project rule); the `timing_*.txt`,
> `util_*.txt`, `ram_*.txt`, `drc_*.txt`, `check_timing_*.txt`,
> `clocks_synth.txt` and `methodology_*.txt` are.

Reproducible run with Vivado ML Standard (free, part `xcku3p-ffva676-2L-e`,
decision 002; synthesis top `synth/itch_chain_synth.sv`, an AXI-contract
wrapper: the full `itch_chain.sv` exposes 896 ports and does not fit the FFVA676
package; DW=32, 3.103 ns period):

```bash
vivado -mode batch -source synth/fase3_synth.tcl   # 322 MHz -> reports/322mhz/
vivado -mode batch -source synth/fase3_156mhz.tcl  # 156 MHz -> reports/156mhz/
```

The tcl aborts with `FASE3 TIMING FAIL` on any negative slack (the gate is
never relaxed).

## Run history (2026-08-18, same tcl throughout; pre-CLO-RPT-01)

> The table keeps the 2026-08-18 322 runs (informative; their reports are no
> longer on disk — they were overwritten by the iter-16 156 run). The current
> numbers live in the `322mhz/` and `156mhz/` subdirectories.

| Run | Change (commit) | WNS | TNS | Failing endpoints | LUT as Logic | URAM | Worst family |
|---|---|---|---|---|---|---|---|
| Base 10:59 | original wrapper | **-10.492 ns** | -590.856.875 ns | 181.711 | 163.259 (100.33 %) | 32/48 | book logic (37-41 levels) + I/O `msg_len->tready` |
| Iter 7 14:11 | ST_EMIT -> registered A/B/C stages (`2fa7250`) | **-7.395 ns** | -430.582.411 ns | 189.127 | 157.011 (96.49 %) | 32/48 | `lv_eq -> lv2_mode` (31 levels, stage B) + I/O |
| Iter 8 15:55 | 2a/2b decode split + wrapper FIFO/rst_n_c (`7d728de`) | **-4.052 ns** | -213.040.636 ns | 176.945 | 155.697 (95.68 %) | 32/48 | `depth_tready` -> URAM cascade (12 levels, 7 URAM288, 2.2 ns pin skew) |
| Iter 9 17:50 | tvalid-only guard + precomputed find-first (`5fbf6ac`) | **-3.527 ns** | -211.438.033 ns | 177.459 | 155.893 (95.80 %) | 32/48 | wrapper I/O: `bbo_locate -> pin` (1 level, -2.67 ns tree skew); internal `out_data`/`body_acc` |
| Iter 10 19:45 | IOB=TRUE on ports + registered tready (`b3d5327`) | **-3.748 ns** | -221.038.368 ns | 178.310 | 155.876 (95.79 %) | 32/48 | book output FFs WITHOUT packing (internal fanout: retention + guard); only `tready_ff` replicated |
| Iter 11 | wrapper output pipeline (`bbd3b6c`) | **-3.319 ns** | — | — | ~95.8 % | 32/48 | wide output buses not replicable to IOB |
| split CLO-322-02 | first_one in B, cap mux by registered index in C | **-3.33 ns** | — | — | 90.2 % | 32/48 | output I/O (SCD 2.695 ns + OBUF 2.334 ns) |

DRC: 0 errors in every run. IOB: 222 in all 322 runs.

## Reading the history

- The book retiming worked: WNS -10.49 -> -3.53 ns and LUT 100.33 % -> 95.79 %
  between base and iter 9; the `depth_tready` -> URAM family of run 8 died with
  the tvalid-only guard of iter 9.
- The residual bottleneck was the **wrapper I/O**: every internal FF -> pin lost
  the clock-tree skew of the book area (~2.7-3.1 ns with LUT ~96 %) plus the
  1.0 ns XDC output delay. Iter 10 showed IOB packing does NOT move the book's
  output FFs (they are re-read by the retention and read by the FSM guard): only
  wrapper FFs without fanout (`tready_ff`) replicate to the IOB.
- **Documented and executed candidate (iter 11)**: output pipeline in the
  wrapper — dedicated `bbo_*_o`/`depth_*_o` FFs with pin-side retention
  (`tvalid_o <= tvalid_o && !tready`), capture with `tvalid_i && !tvalid_o`,
  `(* IOB = "TRUE" *)` on those FFs (see iter-11 spec addendum). Improved to
  WNS **-3.319 ns** (historical best) but **did not close**: wide buses
  (`bbo_locate_o_reg`, `depth_tdata_o_reg`, `bbo_tdata_o_reg`) do not replicate
  to the IOB; only 1-bit FFs (`bbo_tvalid_o`, `depth_tvalid_o`, `tready_ff`),
  and the wide FF_IOB->pin path still has ~2.7 ns skew + 1.0 ns output delay.

## Criterion 10 state

After CLO-322-02 (split): the internal `m_loc_idx -> first_one -> sm_asel` path
is split across two cycles. The book's internal datapath closes and LUT drops to
**146,761** (fits). The top-10 violating paths are now **all output-pad paths**
(`bbo_locate_o_reg` / `depth_tdata_o_reg` -> OBUF -> pin): source clock delay
2.695 ns (clock net fanout 95.585) + OBUF 2.334 ns at the -2L speed grade exceed
the 3.103 ns period even before the 1.0 ns `set_output_delay`. This is a
device-level I/O limit; the timing gate is never relaxed and the XDC is not lied
about. **322 MHz stays open.**

**CV path / production variant**: **DW=64 @ 156.25 MHz** (6.400 ns period, same
line-rate 10G) with the same RTL: **CLOSED** (2026-08-20, iter 16) — WNS
**+0.057 ns**, TNS 0, LUT 154.4k (94.9 %), URAM 32/48, DRC 0 (run
`fase3_156mhz.tcl`, XDC `fase3_156mhz.xdc`, reports archived in
`synth/reports/156mhz/`). At DW=64 the full observability exceeds the FFVA676
I/O budget (258 > 256), so `BBO_W` was parameterized to 64 (prices only at the
pin); datapath identical. The 322 MHz is documented as a non-closed optimization
chapter; the tcl gate is not relaxed. Synthesis lessons that avoid re-running
runs.

## Additional artifacts (in `synth/`)

- `iter_100_CongestedCLBsAndNets.txt` — congested CLBs and nets at iter 100
  (evidence of the book-area placement diagnosis).
- `tight_setup_hold_pins.txt`, `clockInfo.txt` — auxiliary reports.