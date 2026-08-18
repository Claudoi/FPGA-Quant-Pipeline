# synth/reports — evidencia de síntesis (criterio 10)

El **owner** corre Vivado fuera del ciclo y pega aquí los informes del run de
`fase3_synth.tcl` (part `xcku3p-ffva676-2L-e` — decisión 002, Vivado ML
Standard gratuito; top de síntesis `itch_chain_synth.sv` — wrapper de 223
pins, el `itch_chain.sv` completo expone 896 puertos de debug y no entra en
el paquete FFVA676; DW=32, reloj 322,265625 MHz):

- `timing_impl.txt` — WNS/TNS (criterio: **WNS ≥ 0** en la variante 32-bit).
- `util_impl.txt` — utilización LUT/FF/BRAM/**URAM** (criterio 9: inferencia
  de 32 URAM288 para la tabla de órdenes, medido en el run 2026-08-18).
- `timing_synth.txt` / `util_synth.txt` — mismos informes post-síntesis.

El run 2026-08-18 (synth+place+route completo) es la evidencia vigente:
URAM 32/48 inferida y DRC 0 errores, pero **WNS = -10,492 ns** (periodo
3,103 ns) y **LUT al 100,33 %** — criterio 10 NO cerrado; el tcl aborta con
`FASE3 TIMING FAIL` ante slack negativo.

Verificación del tcl sin Vivado: `scripts/verify/synth_check.py` (o el lint de
la skill verify) valida que el tcl/constraints referencian puertos y RTL
existentes.