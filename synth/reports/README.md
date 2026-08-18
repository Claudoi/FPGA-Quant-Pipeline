# synth/reports — historial de runs Vivado (criterio 10)

> Los informes de este directorio (`timing_impl.txt`, `util_impl.txt`,
> `timing_synth.txt`, `util_synth.txt`, `ram_*.txt`, `drc_impl.txt`,
> `check_timing_*.txt`, `clocks_synth.txt`) son los del **último run**; los
> números de los runs anteriores están en las tablas de este documento y en
> `specs/fase3-optimizacion/verify-report.md`.

Run reproducible con Vivado ML Standard (gratuito, part `xcku3p-ffva676-2L-e`,
decisión 002; top de síntesis `synth/itch_chain_synth.sv`, wrapper del contrato
AXI: el `itch_chain.sv` completo expone 896 puertos y no entra en el paquete
FFVA676; DW=32, periodo 3,103 ns):

```bash
vivado -mode batch -source synth/fase3_synth.tcl
```

El tcl aborta con `FASE3 TIMING FAIL` ante slack negativo (gate sin rebajar).
Verificación estática sin Vivado: `scripts/verify/synth_check.py`.

## Historial de runs (2026-08-18, mismo tcl en todos)

| Run | Cambio (commit) | WNS | TNS | Endpoints failing | LUT as Logic | URAM | Peor familia |
|---|---|---|---|---|---|---|---|
| Base 10:59 | wrapper original | **-10,492 ns** | -590.856,875 ns | 181.711 | 163.259 (100,33 %) | 32/48 | lógica del book (37-41 niveles) + I/O `msg_len→tready` |
| Iter 7 14:11 | ST_EMIT → etapas A/B/C registradas (`2fa7250`) | **-7,395 ns** | -430.582,411 ns | 189.127 | 157.011 (96,49 %) | 32/48 | `lv_eq → lv2_mode` (31 niveles, etapa B) + I/O |
| Iter 8 15:55 | decode partido 2a/2b + FIFO/rst_n_c del wrapper (`7d728de`) | **-4,052 ns** | -213.040,636 ns | 176.945 | 155.697 (95,68 %) | 32/48 | `depth_tready` → URAM cascade (12 niveles, 7 URAM288, skew pin 2,2 ns) |
| Iter 9 17:50 | guard solo tvalid + find-first precomputado (`5fbf6ac`) | **-3,527 ns** | -211.438,033 ns | 177.459 | 155.893 (95,80 %) | 32/48 | I/O del wrapper: `bbo_locate → pin` (1 nivel, skew árbol -2,67 ns); internas `out_data`/`body_acc` |
| Iter 10 19:45 | IOB=TRUE en puertos + tready registrado (`b3d5327`) | **-3,748 ns** | -221.038,368 ns | 178.310 | 155.876 (95,79 %) | 32/48 | FFs de salida del book SIN packing (fanout interno: retención + guard); solo se replicó `tready_ff` |

DRC: 0 errores en todos los runs. IOB: 222 en todos.

## Lectura del historial

- El retiming del book funcionó: WNS -10,49 → -3,53 ns y LUT 100,33 % →
  95,79 % entre el base y la iter 9; la familia `depth_tready` → URAM del
  run 8 murió con el guard solo-tvalid de la iter 9.
- El cuello residual es **I/O del wrapper**: todo FF interno → pin pierde el
  skew del árbol de reloj del área del book (~2,7-3,1 ns con LUT ~96 %) + el
  output delay de 1,0 ns del XDC. La iter 10 demostró que el IOB packing NO
  mueve los FFs de salida del book (se releen en la retención y los lee el
  guard del FSM): solo los FFs del wrapper sin fanout (como `tready_ff`) se
  replican al IOB.
- **Candidato documentado y ejecutado (iter 11)**: pipeline de salida en el
  wrapper — FFs propios `bbo_*_o`/`depth_*_o` con retención del lado del pin
  (`tvalid_o <= tvalid_o && !tready`), captura con `tvalid_i && !tvalid_o`,
  `(* IOB = "TRUE" *)` en esos FFs (ver addendum iter 11 de la spec). Mejoró
  a WNS **-3,319 ns** (el mejor histórico) pero **no cerró**: los buses anchos
  (`bbo_locate_o_reg`, `depth_tdata_o_reg`, `bbo_tdata_o_reg`) no se replican
  al IOB; solo los FFs de 1 bit (`bbo_tvalid_o`, `depth_tvalid_o`,
  `tready_ff`) y la ruta FF_IOB→pin ancha sigue con skew ~2,7 ns + output
  delay 1,0 ns.

## Estado del criterio 10

**ABIERTO**: WNS < 0, TNS ≠ 0, LUT > 95 % en los 5 runs (más iter 11
WNS -3,319); URAM 32/48 conservada y DRC 0. No se declara timing cerrado sin
WNS ≥ 0 y TNS = 0 en un run post-route. **Limitación estructural del modelo
I/O del wrapper de síntesis**: cualquier FF→pin de un bus ancho pierde el
skew del árbol (~2,7 ns, LUT al 96 %) + el output delay (1,0 ns); el IOB
packing solo replica FFs de 1 bit; un PHY/IOB registrado con el reloj del
pin no existe en un wrapper. Cerrar 322 MHz exigiría bajar el output delay
del XDC (rechazado: trampa del gate).

**Camino del CV / variante industrial**: **DW=64 @ 156,25 MHz** (periodo
6,400 ns, mismo 10G lineal) con el mismo RTL: holgura sobrada con el
residual actual (~3,3 ns). El 322 MHz queda documentado como capítulo de
optimización no cerrado; el gate del tcl no se rebaja. Las lecciones de
síntesis que evitan repetir runs: sección 7 de
`docs/writeup/lecciones-aprendidas.md`.

## Artefactos adicionales (en `synth/`)

- `iter_100_CongestedCLBsAndNets.txt` — CLBs congestionados y nets con
  iter 100 (evidencia del diagnóstico del área del book).
- `tight_setup_hold_pins.txt`, `clockInfo.txt` — informes auxiliares.