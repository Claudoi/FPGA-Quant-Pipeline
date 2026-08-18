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

**Re-run iter 7 (2026-08-18 14:11, pipeline ST_EMIT → A/B/C, commit
`2fa7250`, mismo tcl)**: el gate abortó de nuevo (`FASE3 TIMING FAIL:
WNS=-7.395 ns`), pero los informes nuevos están en este directorio:
WNS **-7,395 ns** (+3,1 ns), TNS **-430.582,411 ns** (+160 µs), LUT as
Logic **96,49 %** (-3,84 pp), F7/F8 19.762/8.780, URAM 32/48 conservada,
DRC 0. Peor ruta interna `lv_eq → lv2_mode` (31 niveles, escaneo etapa B)
y peor absoluta I/O del wrapper (`msg_len → s_axis_tready`). El criterio
10 sigue abierto (WNS < 0, TNS ≠ 0, LUT > 95 %).

**Loop en curso (iter 8)**: candidatos documentados en el verify-report de
fase 3 — registrar los puertos de salida del wrapper y/o partir la etapa B
del escaneo en dos registros (spec antes de tocar RTL), y cerrar rojo→verde
+ gates A/E/B/C en la máquina con cocotb. Objetivo del re-run siguiente:
WNS ≥ 0, TNS = 0, LUT ≤ 95 %, URAM 32/48 conservada.

Verificación del tcl sin Vivado: `scripts/verify/synth_check.py` (o el lint de
la skill verify) valida que el tcl/constraints referencian puertos y RTL
existentes.