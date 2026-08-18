# Lecciones aprendidas — historial operativo consolidado

> Fuente única de las lecciones que costó aprender (2026-08-12 → 2026-08-18),
> para no repetir los mismos errores ni re-descubrir los mismos números.
> Consolidado (2026-08-18) del contenido operativo de los write-ups de la
> sesión 2026-08-14 (`plan-proxima-sesion-uram.md`,
> `revision-exhaustiva-2026-08-14.md`, `uram.md` — eliminados en la limpieza),
> de las decisiones 001/002 y de los loops de síntesis de fase 3
> (iteraciones 6-10, 2026-08-18). La evidencia formal de cada campaña vive en
> `specs/<campaña>/verify-report.md`; este documento es el resumen operativo.

---

## 1. Parámetros: el parámetro efectivo no es el default del módulo

`itch_chain.sv` declara su **propio** `QB` y lo pasa al parser con `.QB(QB)`;
cambiar el default de `itch_parser.sv` **no tiene efecto sobre la cadena**.

- **Síntoma engañoso**: dos builds limpios con fuentes supuestamente distintas
  dieron latencias idénticas a 3 decimales. La conclusión precipitada era
  errónea; la real: "el parámetro que creo cambiar no es el que elabora".
- **Cómo se resolvió**: instrumentando señales internas con cocotb (traza de
  `dut.u_parser.qn` por ciclo → JSON). La cola superaba QB=64 (69, 73...) →
  el binario usaba 128. Confirmado con el `git diff` del C++ de Verilator
  (constante `0x7f - qn`, shift de 1024 bits).
- **Regla operativa**: en fase 3 los parámetros de campaña viven en el top
  (`itch_chain.sv`), en `synth/itch_chain_synth.sv` y en la línea `-G`/`generic`
  del Makefile/tcl. Antes de medir un cambio de parámetro, verificar QUÉ módulo
  elabora el valor.

## 2. Latencia: modelo del backlog estacionario

La latencia wire→BBO NO es el tiempo de procesamiento del mensaje (~14-19
ciclos teóricos) sino **backlog + procesamiento**:

- La entrada fluye a 4 B/ciclo mientras `qn+4 ≤ QB`; el drenaje del parser solo
  ocurre en ST_CAP (todo el mensaje de golpe, ~38 B cada 14 ciclos = 2,7 B/c).
  Entrada > drenaje ⇒ la cola se fija en QB y cada mensaje espera su turno.
  Modelo: `latencia ≈ (QB/4)/7,7 × 11 + 16`.
- Verificado: QB 128→64 da media **69,26 → 42,40 ciclos** (214,9 → 131,5 ns a
  322,265625 MHz), p99 77→47 — **1,63×** con la corrección bit a bit intacta
  (CHAIN-01: 30.729 eventos, 0 gaps).
- El min (27) es la cola vacía (primer add del día); el steady state es backlog.
- QB ≥ 88 conservaría 0 stalls en el tramo probado (solo 1,4×); QB=64 recorta
  1,63× a costa de stalls acotados (~15 en el tramo) — régimen documentado.
- La semántica "sin registro parcial" (SEC-FRM-01/02) exige capturar el mensaje
  completo antes de emitir ⇒ el aligner streaming no reduce la espera de
  completitud; solo el tamaño de cola fija el backlog estacionario.

## 3. Técnica de diagnóstico: la traza interna vale más que la teoría

Hipótesis → experimento con build limpio (puede dar falso negativo) →
**instrumentación de señales internas** (verdad) → veredicto del binario
elaborado. Reglas:

- El test de diagnóstico (`dbg_qn`-style) es la herramienta estándar: leer
  `dut.<instancia>.<señal>` por jerarquía con cocotb. Ojo: los nombres internos
  son los del RTL (p. ej. `out_valid` no existe como puerto: es
  `m_axis_tvalid`).
- No borrar los instrumentos de diagnóstico: son reutilizables.
- Los bins de Verilator se pueden inspeccionar (constantes elaboradas del C++
  generado) para confirmar QUÉ parámetros se compilaron.

## 4. Proceso: un criterio de spec sin test que lo pinche no está cerrado

El criterio 9 pasó con documentación de un mapeo URAM que **nunca se
implementó** (las "lecturas registradas" no existían en el RTL; el book era
estructuralmente no sintetizable: sondas combinacionales de índice variable =
muxes 65.536:1 → millones de LUTs; `level_add` O(P) ≈ 6-8 ns > 3,103 ns).
Lección: todo criterio que exige una implementación concreta debe tener un test
que la pinche (SEC-URAM-01: lectura registrada), no solo una auditoría y un
write-up.

## 5. Rigor: los tests acotados siguen cazando regresiones

La enmienda "0 stalls" → "stalls ≤ 24" (LIN-01/P32-02) no debilita el
regimiento: el límite viene de una medición (~15 en el tramo) y sigue matando
regresiones groseras (un drenaje roto dispara los stalls por encima del
límite). Regla: todo límite de test debe venir de una medición con evidencia, y
el comentario debe citarla. Y: los replays con datos reales omitidos por pcap
ausente se declaran SKIP, nunca PASS anticipado.

## 6. Datos reales: los invariantes "de libro" se miden, no se asumen

El cruce bid==ask en trading continuo (ZJZZT, 2 mensajes, transición
halt→trading) hizo abortar el run del día real. Decisión 001: el
cruce/bloqueo **se cuenta y se reporta**, no aborta; el modo estricto lo
ejercitan los tests sintéticos. El RTL de fase 2 hereda la semántica: un BBO
bloqueado transitoriamente en datos reales no es un bug.

## 7. Síntesis fase 3 (loops iter 7-10, 2026-08-18) — el historial resumido

| Iter | Cambio | WNS | TNS | LUT | Familia dominante |
|---|---|---|---|---|---|
| Base | wrapper original | -10,492 ns | -590.857 ns | 100,33 % | lógica del book (37-41 niveles) + I/O |
| 7 | ST_EMIT → etapas A/B/C registradas | -7,395 ns | -430.582 ns | 96,49 % | `lv_eq → lv2_mode` (31 niveles) + I/O |
| 8 | decode partido 2a/2b + FIFO wrapper | -4,052 ns | -213.041 ns | 95,68 % | `depth_tready` → URAM cascade (12 niveles) |
| 9 | guard solo tvalid + find-first precomputado | -3,527 ns | -211.438 ns | 95,80 % | I/O del wrapper (bbo_locate→pin, skew -2,67) |
| 10 | IOB=TRUE en puertos + tready registrado | -3,748 ns | -221.038 ns | 95,79 % | FFs del book sin packing (fanout interno) |

**Criterio 10: ABIERTO** (WNS < 0, TNS ≠ 0, LUT > 95 %). Detalle completo y
evidencia: `specs/fase3-optimizacion/verify-report.md` y
`synth/reports/README.md`.

### Lecciones de síntesis (las que evitan repetir runs de 2,5 h)

1. **I/O del wrapper con skew del árbol**: todo FF interno → pin pierde el
   skew del árbol de reloj de su área (2,7-3,1 ns con LUT al 96 %) + el output
   delay del XDC (1,0 ns): una ruta FF→pin de 1 nivel puede no cerrar por el
   skew, no por la lógica.
2. **IOB packing solo aplica a FFs sin fanout interno**: los FFs de salida del
   book (`bbo_tvalid`, `bbo_locate`, …) se releen a sí mismos (retención
   `bbo_tvalid <= bbo_tvalid && !bbo_tready`) y los lee el FSM (guard
   `!bbo_tvalid && !depth_tvalid`): el placer NO los mueve al IOB. Solo se
   replicó `tready_ff` (FF del wrapper). La vía correcta: pipeline de salida en
   el wrapper (FFs propios con retención del lado del pin + IOB).
3. **tready registrado duplica el par si el guard lo mira**: un tready
   diferido 1 ciclo deja el par retenido visible dos ciclos con (tvalid=1,
   tready=1) → el consumidor lo captura dos veces. El guard de emisión debe
   mirar SOLO los tvalid (o la retención del pin debe retirar el par en el
   ciclo de la aceptación).
4. **Deadlock en FSMs**: toda rama de un `case` debe actualizar `st` (una rama
   else que no avanza el estado congela el FSM aunque las salidas parezcan
   correctas).
5. **La familia `depth_tready` → URAM (write con cascade de 7 URAM288) se mata
   moviendo el guard de aceptación fuera de la ruta del write**: el tready del
   pin no debe alimentar ninguna decisión de avance de la tabla.
6. **LUT al ~100 % degrada el árbol de reloj**: los skews internos de 1-3 ns
   son síntoma de área llena, no solo de rutas largas. Reducir LUT alivia
   también las rutas internas.
7. **xvlog 2023.2 es más estricto que Verilator**: rechaza patrones legales de
   SV (`mru32(...)[15:0]` part-select de llamada de función, identificadores
   usados antes de su declaración como `qavail`/`hdr_pos`/`rst_n_c`). Validar
   con verilator (gate B real) o con parches temporales solo para el parse; el
   único error real en el RTL limpio es el falso positivo preexistente de
   `nx_done` (legal en SV, Verilator lo acepta).

## 8. Entorno Windows (PC de trabajo 2026-08-18)

- **Vivado ML 2023.2** en `C:\Xilinx\Vivado\2023.2` (no está en el PATH):
  `vivado.bat -mode batch -source <tcl>` para runs; `xvlog.bat --sv --nolog`
  para parse rápido del RTL. La máquina de desarrollo (macOS) no tiene Vivado:
  allí solo corren los gates de simulación.
- **PowerShell 5.1 `Add-Content` escribe cp1252** (rompe el gate F) o UTF-8 con
  BOM: usar Python para ediciones de bytes o `-Encoding UTF8` y limpiar BOM.
- Los datos/pcaps reales son locales e ignorados; un replay omitido por pcap
  ausente NO cuenta como PASS.

## 9. Números de referencia (para no re-descubrirlos)

| Métrica | Valor | Dónde |
|---|---|---|
| Latencia media (QB=64) | 44,318 ciclos (137,5 ns) | `latency_dw32.json`, `docs/writeup/latencia.md` |
| p99 / p50 / min | 61 / 44 / 32 (pasada 2026-08-18) | idem |
| Eventos bit a bit | 30.729 (cross 0, anomaly 671, gaps 0) | CHAIN-01 |
| URAM inferidas (XCKU3P) | 32/48 (66,67 %), cascade height 8 | run 2026-08-18 |
| Tabla de órdenes | 65.536 slots × 86 bits ≈ 5,64 Mb | spec fase3-uram |
| LUTs del XCKU3P | 162.720 | decisión 002 |
| Periodo objetivo | 3,103 ns (322,265625 MHz) | XDC fase 3 |
| Refs máx. del subset real | 372.297 → K=19 | spec fase2 |
| Niveles máx. por lado (subset) | 17 → P=32 | spec fase2 |
| Límite físico del Anexo A | ratio salida/entrada > 1 → line-rate infinito imposible | spec fase1 (criterio 2) |

## 10. Mapa de la documentación (post-limpieza 2026-08-18)

| Necesidad | Ubicación |
|---|---|
| Estado maestro, proceso, gates A-G | `AGENTS.md` |
| Setup e instalación | `docs/DESARROLLO.md` |
| Decisiones de arquitectura | `docs/decisiones/001..003` (ADRs) |
| Contrato y criterios por campaña | `specs/<campaña>/spec.md` + `gherkin/` |
| Evidencia por campaña (gates A-G) | `specs/<campaña>/verify-report.md` |
| Historial de runs Vivado fase 3 | `synth/reports/README.md` + `synth/reports/*.txt` |
| Lecciones operativas | este documento |
| Latencia wire→BBO | `docs/writeup/latencia.md` |
| Documento maestro (opciones/alcance) | raíz del repo |