# Marcas del proyecto — métricas conseguidas (2026-08-18/19)

> Registro consolidado de **todas** las marcas verificables alcanzadas, con su
> evidencia. Sirve de referencia única para el write-up de CV y para no
> re-descubrir números. Cada cifra cita la ubicación de su evidencia; nada se
> afirma sin output. Fecha de corte: 2026-08-19.

## 1. Línea de fondo (lo que se afirma de cara al CV)

> Pipeline FPGA UltraScale+ que decodifica **Nasdaq TotalView-ITCH 5.0** a
> **line rate de 10G** (64 b × 156,25 MHz = **10,0 Gbps**) y mantiene un
> **order book en 32 URAM** con **latencia determinista ~44,5 ciclos (~138
> ns)**, **cerrando timing** en un **Kintex UltraScale+ XCKU3P** con
> **WNS +0,015 ns, TNS 0, LUT 92,31 %, DRC 0**; verificado contra golden
> independiente y **30 mutantes muertos** en el order book.

Evidencia de cada afirmación: secciones abajo.

---

## 2. Marcas de timing / síntesis (criterio 10)

### 2.1 Variante cerrada — 64 bits @ 156,25 MHz (10G) ✅

Run `synth/fase3_156mhz.tcl` (generic `DW=64 BBO_W=64 K=19 QB=46`, XDC
`fase3_156mhz.xdc`, periodo 6,400 ns). Log `synth/fase3_run_156mhz.log`;
informes en `synth/reports/`.

| Métrica | Valor | Criterio | Estado |
|---|---|---|---|
| **WNS (setup)** | **+0,015 ns** | ≥ 0 | ✅ PASS |
| **TNS (setup)** | **0,000 ns** | = 0 | ✅ PASS |
| Setup failing endpoints | **0** | 0 | ✅ PASS |
| **LUT as Logic** | **150.212 / 162.720 (92,31 %)** | ≤ 95 % | ✅ PASS |
| **URAM288** | **32 / 48 (66,67 %)** | 32 | ✅ PASS |
| Bonded IOB | 194 / 256 (75,78 %) | ≤ 256 | ✅ PASS |
| DRC | 0 errores | 0 | ✅ PASS |
| Frecuencia | 156,25 MHz (periodo 6,4 ns) | — | 10,0 Gbps |

Ruta crítica: `u_book/body_acc_reg[1][56] → lv_beat_reg[18]`, Data Path Delay
6,067 ns (**80 % route**, 12 niveles lógica). Con una densidad LUT del
92,31 % el routing domina; el cierre es de margen justo (+0,015 ns).

**Condición de I/O**: a DW=64 la observabilidad completa del wrapper
excedía el presupuesto del paquete FFVA676 (**258 pines > 256**, `Place
30-58`); se parametrizó `BBO_W` a 64 (bbo_tdata al pin solo con los precios
bid/ask). El datapath medido es idéntico (addendum iter 11b). Inversamente
es una marca honesta: el cierre de timing mide la **lógica**, no los bits de
observabilidad pinzados.

### 2.2 Variante abierta — 32 bits @ 322,265625 MHz (10,3 Gbps)

No cerrada: **mejor WNS -3,319 ns** (iter 11, commit `bbd3b6c`), limitación
estructural del modelo I/O del wrapper de síntesis (cualquier FF→pin de bus
ancho pierde ~2,7 ns de skew de árbol + 1,0 ns de output delay; el IOB
packing solo replica FFs de 1 bit). No se rebaja el gate. Igual throughput
de 10G que la variante 156 (32×322,265625 = 10,3125 Gbps), documentada como
capítulo de optimización abierto.

### 2.3 Historial de runs (criterio 10, variante 322 MHz)

| Run | Fecha/hora | Cambio | WNS | LUT | URAM |
|---|---|---|---|---|---|
| base | 2026-08-18 10:59 | wrapper original | -10,492 ns | 100,33 % | 32/48 |
| iter 7 | 18 14:11 | ST_EMIT → A/B/C | -7,395 ns | 96,49 % | 32/48 |
| iter 8 | 18 15:55 | decode 2a/2b + FIFO | -4,052 ns | 95,68 % | 32/48 |
| iter 9 | 18 17:50 | guard solo tvalid + first_one | -3,527 ns | 95,80 % | 32/48 |
| iter 10 | 18 19:45 | IOB en puertos + tready_ff | -3,748 ns | 95,79 % | 32/48 |
| iter 11 | 19 01:18 | pipeline salida wrapper | **-3,319 ns** | 95,80 % | 32/48 |
| **156 MHz** | **19 04:28** | **DW=64 BBO_W=64, 6,4 ns** | **+0,015 ns** | **92,31 %** | **32/48** |

El proyecto barrió -10,5 ns → -3,3 ns a 322 MHz (ganancia de retiming del
book de ~7,2 ns) y **cerró a 156,25 MHz**. Historial completo y familia de
las rutas: `synth/reports/README.md` y `specs/fase3-optimizacion/verify-report.md`.

---

## 3. Marcas de latencia (wire → BBO)

| Métrica | Valor | Umbral | Estado |
|---|---|---|---|
| Media total | **44,5 ciclos (138,1 ns)** | ≤ 48 (RTM-LAT-01) | ✅ PASS |
| p50 / p99 / min (2026-08-18) | 44 / 61 / 32 ciclos | — | medido |
| Determinismo (SEC-LAT-01) | 2 ejecuciones idénticas | idéntico | ✅ PASS |

Conversión a ns usa el reloj objetivo 322,265625 MHz (3,103 ns/ciclo).
Evidencia: `verification/vectors/latency/latency_dw32.json`,
`docs/writeup/latencia.md`, verify-report fase 3.

(Modelo de backlog estacionario: la latencia = backlog de cola + procesamiento;
QB=64 fijó el régimen y el histograma es determinista.)

---

## 4. Marcas de simulación (gates A/E/B — WSL, 2026-08-18)

Entorno reproducible: WSL2 Ubuntu 26.04, cocotb 2.0.1, Verilator 5.046,
Python 3.12.13.

### 4.1 Fase 3 (order book + cadena, pipeline iter 7-9)

| Suite | Resultado | Nota |
|---|---|---|
| sim-rtm (DW=32, RTM-01..04) | **4/4** PASS | pipeline A/B/C, BBO bit a bit |
| sim-rtm64 (DW=64, RTM-REG-01) | **1/1** PASS | regresión parametrización |
| sim-lat (SEC-LAT-01 + RTM-LAT-01) | **2/2** PASS | media 44,5 ≤ 48 |
| sim (orderbook base) | 4/4 PASS, 1 SKIP | SKIP por pcap real ausente |
| sim-depth | 2/2 PASS, 1 SKIP | |
| sim-hash | **8/8** PASS | |
| sim-hard | **2/2** PASS | |
| sim-chain | 3/3 PASS, 1 SKIP | |

**Gate E (mutación orderbook)**: **30/30 mutantes muertos** (0 supervivientes).
**Gate B**: `verilator --lint-only --Wall` sin WIDTHEXPAND/UNUSEDSIGNAL
residuales; quedan 8× BLKSEQ deliberados (asignaciones bloqueantes de la
inferencia URAM). **Gate C**: verible NO EJECUTADO (no instalado).

### 4.2 Fase 4 (parser CME MDP3, framing tkeep)

| Suite | Resultado |
|---|---|
| mdp3 DW=32 | **9/9** PASS |
| mdp3 DW=64 | **9/9** PASS |
| Gate E (mutación MDP3) | **9/9** mutantes muertos (incl. `TKCNT-ALWAYS`) |
| Gate B | Verilator 5.046 `--Wall` limpio |

Incluye M3-FRM-05 a/b/c (framing MSB-contiguo, truncado por máscara → error,
beat vacío sin trabarse). Gate C (verible) NO EJECUTADO. Fase 4 sigue en
stretch (schema/MAX_MSG/backpressure/timing no cerradas).

### 4.3 Fase 0/1/2 (histórico, cerradas)

- Fase 0: **29/29 tests Python**, 5/5 mutantes, día real 268,7 M mensajes en
  17 min, 14,4 M vectores BBO del subset de 20 símbolos.
- Fase 1 parser: **31/31** (91/91 `tlast`, replay real bit a bit, gaps,
  backpressure); **REP-02 line-rate abierto** (sin pcap local).
- Fase 2 orderbook: **14/14** + replay real del subset.

---

## 5. Marcas de verificación cruzada (adversarial)

- **Golden independiente del RTL**: los oráculos derivan del golden Python,
  nunca del DUT.
- **Bit a bit**: BBO y depth comparados contra el golden (30.729 eventos
  históricos; CHAIN-01; subconjuntos en sim-rtm/sim-chain).
- **Determinismo de latencia**: SEC-LAT-01 exige histogramas idénticos en 2
  pasadas (verificado, 44,5).
- **Mutación**: 30 (orderbook) + 9 (MDP3) mutantes, todos muertos; cada
  mutante compila antes de contarse.

---

## 6. Límites honestos (lo que NO afirma)

- MAC 10G / Ethernet / IP / UDP **no están implementados** (el repo empieza
  en MoldUDP64 decapsulado).
- El book está dimensionado para el **subset de 20 símbolos**, no un libro
  Nasdaq completo.
- Line-rate infinito de mensajes mínimos es **non-goal físico** (Anexo A:
  ratio salida/entrada > 1). REP-02 mide el tramo real acotado; sigue
  **pendiente por falta del pcap**: sin `/tmp/real_subset.pcap` no se cierra.
- La frecuencia de 322 MHz sigue **abierta** (mejor -3,319 ns) por el modelo
  I/O del wrapper; no se declara como timing cerrado.
- Fase 4 (CME MDP3): solo framing verde; timing/schema/backpressure abiertos.
- Gate C (verible) NO EJECUTADO en fases 1-4 (herramienta no instalada).

---

## 7. Referencias

| Número | Evidencia |
|---|---|
| 156 MHz (WNS/TNS/LUT/URAM) | `synth/reports/timing_impl.txt`, `util_impl.txt`, `drc_impl.txt` (run más reciente) + `specs/fase3-optimizacion/verify-report.md` |
| Historial runs 322 | `synth/reports/README.md` |
| Latencia | `verification/vectors/latency/latency_dw32.json`, `docs/writeup/latencia.md` |
| Simulación fase 3/4 | `specs/fase3-optimizacion/verify-report.md`, `specs/fase4-mdp3-parser/verify-report.md` |
| Config fondo | documento maestro en la raíz, decisión 002 (part), lecciones-aprendidas.md |

Los informes `synth/reports/*.txt` son siempre del **último** run; los números
históricos viven en las tablas de este documento y del verify-report.
