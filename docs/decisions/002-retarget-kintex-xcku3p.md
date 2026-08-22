# 002 — Retarget of the target part to Kintex XCKU3P (criterion 10 without a paid license)

**Date:** 2026-08-17 · **Status:** accepted

## Context

The criterion-10 timing close requires a real Vivado run on the target part.
The part fixed in phase 3 was `xcvu9p-flga2104-2L-e` (Virtex UltraScale+ VU9P),
which **only synthesizes with Vivado ML Enterprise** (paid license, from
~$4,395; the free evaluation is one-time and temporary). Owner's decision: **pay
nothing** and prioritize the run being reproducible by anyone.

Vivado ML Standard (free, no expiry; and the BASIC tier of the 2026.1 model)
supports Kintex UltraScale+ `XCKU3P` and `XCKU5P` (UG973 support table). The
master document already contemplates the family «Zynq US+ or Virtex/Kintex
US+»: the retarget does not betray the project's objective.

## Decision

The target part of the 32-bit @ 322.265625 MHz variant becomes
**`xcku3p-ffva676-2L-e`** (Kintex UltraScale+, same speed grade -2L and -e
temperature grade as the fixed VU9P). If Vivado rejected that exact string in
the installation, the agreed fallback is `xcku3p-ffva676-2-e` (at 0.85 V the
-2LE performs equally to the -2 according to DS922; documented here, not in the
RTL).

Measured suitability:

- The order table is a single array of 65,536 × 86 bits ≈ 5.64 Mb.
- **AMENDMENT 2026-08-18 (data from Vivado itself, not the datasheet):** the
  XCKU3P has **48 URAM** (288 Kb each ≈ 13.8 Mb) and 360 BRAM36K; the original
  count «360 URAM (36 Mb)» was wrong (360 is the BRAM). The real inference of
  `o_mem` with `(* ram_style = "ultra" *)` maps **32 URAM288** (16 of depth × 2
  of width; cascade height 8) → 32/48 = 67 % of the part's URAM: it fits, but
  with ~1.5× margin, not ~17×.
- LUTs: the design uses thousands of LUTs; the XCKU3P has 162,720 CLB LUTs.
- Same UltraScale+ architecture and same clock regime (322.265625 MHz / 3.103
  ns period): the timing challenge is identical to the VU9P.

## Consequences

- Contract edit documented in `specs/fase3-optimizacion/spec.md` and
  `specs/fase3-uram/spec.md` (Constraints and criterion 7/10).
- `synth/fase3_synth.tcl` (part line), `synth/constraints/fase3_322mhz.xdc`
  (comment), `synth/reports/README.md` and `scripts/verify/synth_check.py`
  (PART constant + docstring) aligned.
- The dated VU9P-era write-ups (URAM mapping, exhaustive review and URAM
  session plan) were consolidated into
  `docs/writeup/lessons-learned.md` and their originals were removed in the
  2026-08-18 documentation cleanup; the current operational reference is the
  spec.
- The `vivado -mode batch -source fase3_synth.tcl` run is reproducible on any
  machine with Vivado ML Standard installed (free AMD registration, no paid
  license).
- If an Enterprise license becomes available in the future (academic or paid),
  reverting the part in `fase3_synth.tcl` to `xcvu9p-flga2104-2L-e` re-runs the
  same flow with no further changes (the RTL and the XDC are not
  part-dependent).

Supporting evidence: UG973 support table (Vivado ML Standard includes Kintex
UltraScale+ XCKU3P/XCKU5P) and DS922 datasheet (XCKU3P resources).