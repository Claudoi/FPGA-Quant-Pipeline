# verify-report — fase3-optimizacion — regresión `tkeep` DW=32

> Evidencia vigente ejecutada el 2026-08-15 desde el commit base
> `22130e3fae758edaf674a3ceb9c45b38711a2f5b`, con builds limpios y
> `PATH=/Volumes/WD_Black/FPGA/.venv/bin:$PATH`. Sustituye como evidencia
> vigente las pasadas producidas antes de que el driver representara límites
> de datagrama mediante `s_axis_tkeep`.

Fix Round 1 reejecutado el `2026-08-15T15:37:59+01:00` sobre
`785675bfcaf35937cf060fe0d0c4fc3bc0d6c52b`; parser DW64, cadena ND=5/3 y
Gate F se actualizaron con sus outputs nuevos.

## Veredicto

**PASS funcional del delta `tkeep` y de BBO/depth en la cadena DW=32. Fase 3
NO CERRADA.** La cadena real compara ahora las 30.729 palabras BBO y las
30.729 palabras depth para ND=5 y ND=3. Quedan dos bloqueadores: REP-02 aún no
mide el umbral `<=24` sobre un tramo A/U real derivado reproduciblemente del
pcap, y el **primer run Vivado real (2026-08-18) NO cierra timing ni cabe en
LUT**: WNS = **-10,492 ns** sobre un periodo de 3,103 ns y LUT al **100,33 %**
(163.259/162.720). La tabla `o_mem` sí se infiere en **32 URAM288 (66,67 % del
part)**.

`synth_check.py` solo demuestra coherencia estática entre RTL, Tcl y XDC. La
latencia de 44,318 ciclos es una medición de simulación; convertirla usando el
periodo objetivo no acredita que el dispositivo alcance 322,265625 MHz.

## Entorno reproducido

```text
fecha: 2026-08-15T14:58:46+01:00
Python 3.11.14; cocotb 2.0.1
Verilator 5.050 2026-07-01; GNU Make 3.81
verible-verilog-lint: no instalado
vivado: no instalado
/tmp/real_subset.pcap: 91 paquetes, 3000 mensajes
/tmp/real_trading.pcap: 3222 paquetes, 150000 mensajes
```

## Gates A–G

| Gate | Evidencia fresca del loop `tkeep` | Resultado |
|---|---|---|
| A — simulación | parser DW64 31/31; chain ND=5 4/4; chain ND=3 4/4; ANX 3/3, todos con `FAIL=0 SKIP=0`; CHAIN real compara BBO y depth | **PASS en suites ejecutadas; REP-02 line-rate abierto** |
| B — compilación | lint `--Wall` de parser DW32 y `itch_chain` DW32 con dependencias, exit 0 y cero warnings | **PASS** |
| C — estilo | `verible-verilog-lint` no instalado | **NO EJECUTADO** |
| D — cobertura | CHAIN-01 real cubre BBO+depth completos con no-vacío y longitudes para ND=5/3; P32-01/02 y framing mantienen sus espejos; REP-02 no aísla aún el tramo line-rate real | **PARCIAL por REP-02** |
| E — mutación | delta de entrada heredado del parser: 19/19 mutantes compilables y muertos; no se presenta la mutación histórica del order book como fresca | **PASS para el delta `tkeep`** |
| F — completitud | checker versionado: 12 IDs/3 campañas, unicidad por campaña, spec/test/report y rutas; negativos controlados; excepción externa URAM/CHAIN-01 verificada | **PASS** |
| G — rigor/timing | pcaps fuera de Git, golden independiente, `synth_check.py` 24/24 estático; **run Vivado 2026-08-18 completo (synth+place+route) con WNS = -10,492 ns, TNS = -590.856,875 ns y LUT 100,33 % — criterio 10 NO CERRADO**; REP-02 line-rate real pendiente | **ABIERTO** |

## Gate A — salida fresca desde builds limpios

```text
$ make -C verification/testbenches/phase3 clean-all
$ make -C verification/testbenches/phase3 sim-parser
P32-03 OK: 91 paquetes, 26904 words de 32 bits bit a bit
TESTS=5 PASS=5 FAIL=0 SKIP=0
exit 0

$ make -C verification/testbenches/phase3 clean-all
$ make -C verification/testbenches/phase3 sim-chain
CHAIN-01: 31400 msgs / 20 símbolos contra golden
CHAIN-01 OK ND=5: 30729 BBO y 30729 depth bit a bit,
cross=0, anomaly=671, gaps=0
TESTS=4 PASS=4 FAIL=0 SKIP=0
exit 0

$ make -C verification/testbenches/phase3 clean-all
$ make -C verification/testbenches/phase3 sim-chain-nd3
CHAIN-01 OK ND=3: 30729 BBO y 30729 depth bit a bit,
cross=0, anomaly=671, gaps=0
TESTS=4 PASS=4 FAIL=0 SKIP=0
exit 0

$ make -C verification/testbenches/phase3 clean-all
$ make -C verification/testbenches/phase3 sim-lat
SEC-LAT-01 OK: 30729 eventos, dos ejecuciones idénticas
TESTS=1 PASS=1 FAIL=0 SKIP=0
exit 0
```

### Frontera real de `tlast`

- P32-03 conserva los 91 payloads reales de `/tmp/real_subset.pcap`; el
  assert `accepted_tlast == len(payloads)` verificó **91 handshakes `tlast`**.
- CHAIN-01 filtra el pcap de trading a 20 símbolos y reconstruye esos 31.400
  mensajes en **un** payload MoldUDP64 para el subset; su driver verificó
  **1 handshake `tlast`**. No se presenta ese único burst como preservación
  de los 3.222 límites originales del pcap.
- `test_chain_tkeep_datagramas_no_alineados_y_estabilidad` usa dos payloads
  sintéticos no múltiplos de cuatro, fuerza backpressure y verificó **2
  handshakes `tlast`**, `tkeep` y estabilidad de la fuente en la cadena.

Esta separación evita convertir el replay filtrado de cadena en una evidencia
que no produce: los límites reales los pinza P32-03; la integración
multi-datagrama la pinza el adversarial de cadena.

REP-02 DW64 añadió una caracterización de 15.023 stalls agregados sobre 91
datagramas con `m_axis_tready=1`. No se compara con `<=24`, que pertenece a
una ventana de cuatro A/U, ni cierra el tramo real pendiente. La selección
futura debe derivarse del pcap en orden de captura, sin índices manuales.

### Latencia de simulación

```text
eventos=30729; mean=44.318 ciclos; p50=44; p99=61; min=32; max=74
A mean=48.660; D mean=41.189; E mean=40.857;
U mean=55.408; X mean=39.402
```

El test hizo warm-up de invalidación URAM y dos ejecuciones idénticas sobre
el subset real. Es latencia desde el handshake de la word que contiene el
primer byte del mensaje hasta el evento BBO en simulación.

## Gates B/C/G — salida fresca

```text
$ verilator --lint-only --Wall --top-module itch_parser -GDW=32 \
    rtl/parser/itch_parser.sv
exit 0; cero warnings

$ verilator --lint-only --Wall --top-module itch_chain -GDW=32 \
    rtl/itch_chain.sv rtl/parser/itch_parser.sv rtl/orderbook/orderbook.sv
exit 0; cero warnings

Gate C NO EJECUTADO: verible-verilog-lint no instalado

$ python3 scripts/verify/synth_check.py
24 PASS; 0 FAIL
synth_check: OK — tcl/constraints coherentes con el RTL y la spec
exit 0
```

Los 24 checks (reenumerados el 2026-08-18 al apuntar al wrapper
`itch_chain_synth.sv`) incluyen periodo XDC de 3,103 ns, puertos/delays
min-max, lectura registrada de `o_mem` y comandos de informes/aborto del Tcl.
No ejecutan síntesis, place ni route.

## Gates D/E/F

| ID | Test/evidencia vigente |
|---|---|
| P32-01 | `test_p32_01_anexo_a_32_bits`, P32-03 real y validación `tkeep`/truncados |
| P32-02 | `test_p32_02_peor_caso_una_palabra_ciclo` |
| CHAIN-01 | `test_chain01_feed_real_bit_a_bit`: 30.729 BBO + 30.729 depth contra `run_book_depth(..., nd=ND)` y `pack_depth`, ND=5/3; sintético separado |
| DP-01 | `test_dp01_nd_parametrizado_llega_al_book`, ejecutado con ND=5 y ND=3 |

```text
$ python3 scripts/verify/mutate_parser.py
19/19 killed; cada mutante compiló; 0 supervivientes; 0 mutantes rotos
19/19 mutantes compilables y muertos. Gate E PASS.
exit 0

$ python3 -m unittest -v scripts.verify.test_check_itch_gherkin
15 tests: 1 snapshot sano y 14 negativos separados para declaraciones Gherkin,
AST de tests, spec/report, duplicado, rutas, manifiesto/mapping, coincidencia
exacta y espejo externo URAM/CHAIN-01
OK

$ python3 scripts/verify/check_itch_gherkin.py
Gate F PASS: 12 IDs en 3 campañas; Gherkin único por campaña,
spec/test/verify-report presentes y rutas del manifiesto existentes
Espejo externo verificado: fase3-uram/CHAIN-01 ->
verification/testbenches/phase3/test_chain32.py
exit 0
```

La mutación 19/19 cierra el delta compartido de framing. No se reejecutó en el
Fix Round 1 porque no cambiaron el RTL ni `mutate_parser.py`; corresponde a la
ejecución fresca del commit documental anterior. Tampoco se ejecutó
`mutate_orderbook.py`; sus resultados históricos no se usan para cerrar el
gate físico.

## Evidencia física — run Vivado 2026-08-18 (synth + place + route)

Primer run real de la campaña: `vivado -mode batch -source synth/fase3_synth.tcl`
(Vivado ML 2023.2, Windows), part `xcku3p-ffva676-2L-e`, top de síntesis
`synth/itch_chain_synth.sv` (223 pins del contrato AXI; el `itch_chain.sv`
completo tiene 896 puertos de debug y no entra en el paquete FFVA676 de 256
I/O — Place 30-415, por eso el wrapper, hallazgo 2026-08-18).

### Utilización post-route (`util_impl.txt`)

```text
| CLB LUTs                | 163259 |     0 |          0 |    162720 | 100.33 |
| CLB Registers           |  91001 |     0 |          0 |    325440 |  27.96 |
| CARRY8                  |   1270 |     0 |          0 |     27120 |   4.68 |
| F7 Muxes                |  20275 |     0 |          0 |    108480 |  18.69 |
| F8 Muxes                |   8930 |     0 |          0 |     54240 |  16.46 |
```

**El diseño NO cabe: LUT al 100,33 %.** El exceso está en la lógica de
niveles/BBO desplegada por símbolo (20.275 F7 + 8.930 F8 muxes) más la
congestión asociada.

### RAM (`ram_impl.txt`)

```text
| URAM                     |         32 |        48 | 66.67 |    100.00 |
|  URAM288                 |         32 |           |       |    100.00 |
| BlockRAM                 |          0 |       360 |  0.00 |      0.00 |
```

**La tabla `o_mem` se infiere íntegra en 32 URAM288** (cascade height 8,
Synth 8-5780) tras el fix 2026-08-18: la escritura vía `task mem_wr` rompía la
inferencia (Synth 8-7186 → array a flops → hang de optimización); se sustituyó
por una única sentencia síncrona `if (wr_en) o_mem[wr_addr] <= wr_data;`
(Bisect de smokes V6-V14: el patrón con task reproduce el fallo, el de
sentencia única infiere con reset de `rd_addr` incluido).

### Timing post-route (`timing_impl.txt`)

```text
clk_pipeline      -10.492  -590856.875                 181711               275646       -1.145   -65317.000                  90439               275646        0.851        0.000                       0                 91034
```

- WNS = **-10,492 ns** (periodo 3,103 ns → peor camino ~13,6 ns, ~74 MHz
  efectivos); TNS = -590.856,875 ns; **181.711 de 275.646 endpoints fallan**.
- WHS = -1,145 ns (hold también violado, secundario a la congestión).
- PW sin violaciones. `check_timing` sin errores de constraint; `report_drc`:
  **0 errores**.
- Rutas críticas (todas internas al book):
  - `u_book/m_loc_idx_reg[1]_replica_6/C → bbo_changed_reg/D`: 13,672 ns,
    **41 niveles de lógica** (2 CARRY8 + 37 LUT), route 72,9 % (congestión).
  - `u_book/m_loc_idx_reg[1]_replica_170/C → bbo_tdata_reg[111]/D`: 13,207 ns,
    37 niveles.
  - El parser está lejos del límite: `u_parser/st_reg[0]/C → s_axis_tready`:
    9,029 ns, 12 niveles (incluye OBUF).

### Diagnóstico y siguiente loop

El cuello está en la **generación de BBO/depth a partir de la lista de
niveles** (37-41 niveles de LUT encadenados + congestión al 100 % de LUT), no
en la URAM ni en el parser. El criterio 10 (322,265625 MHz sobre el part)
**NO está cerrado**; el siguiente loop necesita un cambio estructural de esa
lógica (p. ej. pipeline/retiming del escaneo de niveles o generación de BBO
sombra incremental) con spec nueva antes de tocar RTL.

El gate del tcl aborta correctamente con slack negativo (`FASE3 TIMING FAIL:
WNS=-10.492 ns`), así que un run futuro verde es reproducible y verificable
por el mismo script.

## Bloqueador funcional restante

- **REP-02 line-rate**: seleccionar desde el pcap, sin índices manuales, un
  tramo real de cuatro A/U consecutivos y contar stalls con el downstream
  siempre listo (umbral `<=24`); el agregado de 15.023 stalls no lo sustituye.
- Reejecutar las suites de simulación (orderbook/phase3/uram/mdp3) sobre el
  fix de `o_mem` (la máquina con cocotb/Verilator no es este PC; queda
  pendiente tras commitear).

Hasta adjuntar esa evidencia y cerrar la medición line-rate real de REP-02,
**fase 3 permanece NO CERRADA**.
