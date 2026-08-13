# synth/reports — evidencia de síntesis (criterio 10)

El **owner** corre Vivado fuera del ciclo y pega aquí los informes del run de
`fase3_synth.tcl` (part `xcvu9p-flga2104-2L-e`, top `itch_chain` con DW=32,
reloj 322,265625 MHz):

- `timing_impl.txt` — WNS/TNS (criterio: **WNS ≥ 0** en la variante 32-bit).
- `util_impl.txt` — utilización LUT/FF/BRAM/**URAM** (criterio 9: inferencia
  de ≈20 URAM para la tabla de órdenes).
- `timing_synth.txt` / `util_synth.txt` — mismos informes post-síntesis.

Verificación del tcl sin Vivado: `scripts/verify/synth_check.py` (o el lint de
la skill verify) valida que el tcl/constraints referencian puertos y RTL
existentes.