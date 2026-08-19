# Pipeline FPGA ITCH → Order Book → BBO — write-up de candidatura

> Documento maestro de presentación del proyecto. Las specs, los
> verify-reports y los informes de síntesis son la evidencia; este documento
> solo las resume y las enlaza. Fechado: 2026-08-19.
>
> Repositorio público y reproducible: `git log`, `make -C verification/... sim`
> y `vivado -mode batch -source synth/fase3_156mhz.tcl` regeneran cada número
> de este documento.

## 1. Qué es

Una infraestructura FPGA de **baja latencia para mercado electrónico**
(Nasdaq ITCH y CME MDP3) implementada en SystemVerilog, verificada contra un
golden model Python independiente bit a bit, con cierre de timing en Vivado
para un Kintex UltraScale+ `xcku3p-ffva676-2L-e`.

El pipeline implementado:

```
MoldUDP64 (payload ya decapsulado) → parser ITCH → order book (URAM) → BBO/top-N
```

- **Parser ITCH** (`rtl/parser/itch_parser.sv`): framing AXI-Stream 64b con
  `s_axis_tkeep`, gaps, backpressure y `tlast` por mensaje; 91/91 vectores
  `tlast` verdes y replay bit a bit del día real (spec `specs/fase1-parser-rtl/`).
- **Order book** (`rtl/orderbook/orderbook.sv`): subset de 20 símbolos en
  tabla de órdenes en **URAM** (hash + linear probing, lectura registrada),
  BBO bit a bit contra el golden en replay real (spec `specs/fase2-orderbook/`).
- **Cadena** (`rtl/itch_chain.sv` + wrapper de síntesis
  `synth/itch_chain_synth.sv`): parser → book con pipeline registrado y
  variante DW=64/156,25 MHz **timing-cerrada** (spec `specs/fase3-optimizacion/`).
- **Parser CME MDP3** (`rtl/parser/mdp3_parser.sv`): misma disciplina de
  framing con `tkeep`, esquema SBE fijado (`data/mdp3/templates_FixBinary_v12.xml`),
  criterios 5 y 10 cerrados (spec `specs/fase4-mdp3-parser/`).

Documento maestro de opciones y alcance:
`Proyecto FPGA para Quant Finance — Documento maestro de opciones.md`.

## 2. Límites honestos

- **No hay MAC/Ethernet/IP/UDP en este repositorio**: la entrada es el
  payload MoldUDP64 ya decapsulado (el trabajo de la infraestructura de red
  10G queda fuera del alcance implementado).
- **El book está dimensionado para el subset configurado de 20 símbolos**,
  no para el libro completo de Nasdaq (7.000+ emisores).
- **322 MHz (DW=32) queda como capítulo de optimización abierto**; la
  variante industrial cerrada es **DW=64 @ 156,25 MHz = 10G lineal** (ver §5).
- **REP-02 (fase 1) pendiente de pcap real local**: el test está preparado
  pero un test sin su pcap informa la omisión, no sustituye esa evidencia.
- Fase 4: el **criterio 7** (máscaras con huecos / parcial sin `tlast`) y el
  **timing MDP3** (sin Vivado dedicado) quedan abiertos.

## 3. Hazards del book (por qué el diseño no es trivial)

El contrato de la tabla de órdenes (spec fase 2, §superficie y amenazas)
obliga a resolver tres clases de hazards sin FIFO de escape:

1. **Hazards RAW de la cola de mensajes**: dos mensajes consecutivos sobre
   la misma orden/nivel (add→execute, add→cancel, replace→execute); el
   segundo debe ver el estado del primero. Resuelto con forwarding o stall
   selectivo (`SEC-HZ-01/02`).
2. **Replace `U` atómico**: delete+add de un solo estado resultante; nunca
   un BBO intermedio con la orden ausente (`SEC-U-01`). El BBO emitido para
   un `U` refleja el estado final.
3. **URAM con 1 write/ciclo y lectura registrada**: la tabla (65.536×86 bits
   = 32 URAM288 reales, medido en run) exige pipeline de lectura registrada
   (1 ciclo) y serialización de escrituras; la salida BBO se retiene en
   registros releídos por la retención y el guard del FSM (fanout interno que
   la síntesis no empaqueta al IOB — hallazgo documentado en iter 10).

Invariantes con señal, nunca silencio: ref duplicada, qty no positiva,
overflow de niveles → `error`; ref desconocida y operación inválida no
abortante → `anomaly_count`; libro cruzado en continuo → `cross_events`
(contado, no aborta).

## 4. Latencia wire→BBO

Histograma reproducible de la cadena parser→book a DW=32 (322,265625 MHz,
3,103 ns/ciclo) sobre el subset de 20 símbolos del feed real 2019-12-30
(31.400 mensajes, 30.729 eventos, 0 gaps). Medición: handshake en `s_axis`
(word del primer byte del mensaje) → `bbo_tvalid`. Artefacto:
`verification/vectors/latency/latency_dw32.json` (criterio `SEC-LAT-01`).

| Tipo | n | min | media | p50 | p99 | max |
|---|---|---|---|---|---|---|
| A (add) | 12.742 | 37 | 48,66 | 48 | 62 | 74 |
| D (delete) | 12.368 | 32 | 41,19 | 41 | 55 | 64 |
| E (executed) | 14 | 33 | 40,86 | 41 | 45 | 45 |
| U (replace) | 686 | 46 | 55,41 | 54 | 70 | 74 |
| X (cancel) | 4.919 | 33 | 39,40 | 39 | 53 | 64 |
| **Total** | **30.729** | **32** | **44,32** | **44** | **61** | **74** |

Criterio de campaña `RTM-LAT-01`: media **44,5 ciclos (138,1 ns) ≤ 48**,
determinista (verificada en WSL, cocotb + Verilator; ver
`specs/fase3-optimizacion/verify-report.md`).

## 5. Timing Vivado (criterio 10, runs 2026-08-18/19)

Top de síntesis `synth/itch_chain_synth.sv` (wrapper del contrato AXI; el
`itch_chain.sv` completo expone 896 puertos y no entra en el paquete
FFVA676). Run reproducible: `vivado -mode batch -source synth/fase3_synth.tcl`.
El tcl aborta con `FASE3 TIMING FAIL` ante slack negativo (gate sin rebajar).
Historial completo: `synth/reports/README.md`.

| Run | Cambio (commit) | WNS | TNS | LUT as Logic | URAM | Peor familia |
|---|---|---|---|---|---|---|
| Base 10:59 | wrapper original | -10,492 ns | -590.856,875 ns | 163.259 (100,33 %) | 32/48 | lógica del book (37-41 niveles) + I/O |
| Iter 7 | ST_EMIT → etapas A/B/C registradas (`2fa7250`) | -7,395 ns | -430.582,411 ns | 157.011 (96,49 %) | 32/48 | `lv_eq → lv2_mode` + I/O |
| Iter 8 | decode partido 2a/2b + FIFO/rst_n_c wrapper (`7d728de`) | -4,052 ns | -213.040,636 ns | 155.697 (95,68 %) | 32/48 | `depth_tready` → URAM cascade |
| Iter 9 | guard solo tvalid + find-first precomputado (`5fbf6ac`) | -3,527 ns | -211.438,033 ns | 155.893 (95,80 %) | 32/48 | I/O del wrapper (skew árbol -2,67 ns) |
| Iter 10 | IOB=TRUE + tready registrado (`b3d5327`) | -3,748 ns | -221.038,368 ns | 155.876 (95,79 %) | 32/48 | FFs de salida del book SIN packing |
| Iter 11 | pipeline de salida del wrapper (`bbd3b6c`) | **-3,319 ns** | — | — | 32/48 | buses anchos no replicables al IOB |
| **156 MHz** | **DW=64, periodo 6,400 ns (`fase3_156mhz.tcl`, BBO_W=64)** | **+0,015 ns** | **0** | **150.212 (92,31 %)** | **32/48** | — |

DRC: 0 errores en todos los runs; IOB 194 en la variante 156 (222 en DW=32).
Veredictos:

- **CERRADO — variante industrial DW=64 @ 156,25 MHz = 10G lineal**: WNS
  +0,015 ns, TNS 0, LUT 92,31 %, URAM 32/48, DRC 0. A DW=64 la
  observabilidad completa excede el I/O del FFVA676 (258 > 256) y se
  parametrizó `BBO_W` a 64 (solo precios al pin); datapath idéntico.
- **ABIERTO — 322 MHz (DW=32)**: mejor WNS -3,319 ns (iter 11). Limitación
  estructural del modelo I/O del wrapper: FF→pin de bus ancho pierde el skew
  del árbol (~2,7 ns, LUT ~96 %) + output delay 1,0 ns; el IOB packing solo
  replica FFs de 1 bit. No se rebaja el gate ni se miente con el XDC.

## 6. Framing `tkeep` y por qué el line-rate infinito es non-goal

El framing AXI-Stream con `s_axis_tkeep` trata los paquetes de tamaño
variable (mensajes de 2 a 64 B en ITCH; grupos SBE en MDP3) sin FIFO ni
paralelización por tamaño: el `tkeep` declara las lanes reales del último
beat, y las máscaras no MSB-contiguas son condición de error (nunca
comportamiento silencioso). La mecánica está verificada por mutación
(`TKCNT-ALWAYS` muerto) y por 18/18 tests en las dos anchuras.

**El line-rate infinito con mensajes mínimos es explícitamente un
non-goal** (spec fase 1, criterio 2, y lecciones §9): un feed real ITCH
tiene una mezcla de tamaños que el datapath DW=32/DW=64 consume a 1 mensaje
por ciclo como régimen nominal; el objetivo es throughput sostenido al
line-rate *real* del feed con backpressure estable, no la cota superior
teórica de un stream patológico. El régimen real de backpressure y latencia
está documentado, no escondido (regla global del repo).

## 7. Estado por fase y qué no está

| Fase | Veredicto |
|---|---|
| 0 — golden ITCH | **Cerrada**; 22 tipos validados, día real 2019-12-30 (268,7 M mensajes en 17 min, 0 anomalías), 29/29 tests |
| 1 — parser RTL | No cerrada: framing tkeep, 91/91 `tlast`, gaps, backpressure y replay real bit a bit verdes; **REP-02** (≤24 stalls en tramo A/U real) pendiente de pcap |
| 2 — order book RTL | **Cerrada funcionalmente**; BBO bit a bit, replace atómico, replay real del subset |
| 3 — DW=32/URAM | **Cerrada la variante 64b/156,25 MHz (10G)**; 322 MHz abierto como capítulo de optimización; sim verde (sim-rtm 4/4, rtm64 1/1, lat media 44,5 ≤ 48, gate E 30/30) |
| 4 — CME MDP3 | No cerrada: framing, criterio 5 (schema/version + MAX_MSG) y criterio 10 (backpressure de salida) verdes; **criterio 7 (máscaras) abierto**; timing sin Vivado MDP3 |

Qué no está (de forma explícita): MAC/Ethernet/IP/UDP, libro completo
Nasdaq, 322 MHz cerrado, criterio 7 de MDP3, timing MDP3, REP-02 sin pcap.

## 8. Verificación (gates, sin atajos)

- Golden independiente del RTL; comparación bit a bit (nunca oráculo desde
  el RTL probado).
- Gates A–G del proceso del repo (`AGENTS.md`): simulación cocotb
  (Verilator), lint `--Wall`, estilo verible (NO EJECUTADO: no instalado),
  cobertura spec↔test, **mutación** (30 muertos en order book + 9 en MDP3),
  completitud Gherkin, timing Vivado.
- Comandos: `make -C verification/testbenches/<area> sim` para cada área;
  `python3 scripts/verify/mutate_mdp3.py`; `python3 scripts/verify/synth_check.py`.

## 9. Enlaces de evidencia

| Necesidad | Ubicación |
|---|---|
| Reglas, estado y proceso | `AGENTS.md` |
| Contratos por campaña | `specs/<campaña>/spec.md` + `gherkin/` |
| Evidencia por campaña | `specs/<campaña>/verify-report.md` |
| Historial de runs Vivado | `synth/reports/README.md` |
| Latencia (histograma JSON) | `verification/vectors/latency/latency_dw32.json` |
| Lecciones de síntesis y simulación | `docs/writeup/lecciones-aprendidas.md` |
| Plan de cierre ejecutable | `docs/writeup/plan-cierre.md` |
| Marcas verificables | `docs/writeup/marcas.md` |
| Setup del entorno | `docs/DESARROLLO.md` |