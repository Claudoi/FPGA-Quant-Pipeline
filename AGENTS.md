# Agent Notes — FPGA Quant Pipeline

> Proyecto de portfolio para infraestructura FPGA de baja latencia. El alcance
> implementado empieza en el payload MoldUDP64 ya decapsulado; **MAC 10G y
> Ethernet/IP/UDP no están implementados en este repositorio**.

## Arquitectura y límites honestos

`MoldUDP64 → parser ITCH → order book → BBO/top-N`

- El objetivo de la variante de fase 3 es DW=32 a 322,265625 MHz sobre
  UltraScale+. El framing `tkeep` y la salida BBO/top-N están verificados en
  simulación. Sigue pendiente medir de forma reproducible el umbral de stalls
  sobre un tramo A/U real; el cierre de timing exige además un informe Vivado
  con WNS/TNS y utilización.
- El book está dimensionado para el subset configurado de 20 símbolos, no para
  un libro completo de todo Nasdaq.
- Los replays con datos reales requieren artefactos locales no versionados. Un
  test que no encuentre su pcap informa la omisión; no sustituye esa evidencia
  por una pasada sintética.

El documento maestro, el alcance por fase y los riesgos viven en
`Proyecto FPGA para Quant Finance — Documento maestro de opciones.md`.

## Estado actual — 2026-08-18

| Fase | Estado verificable |
|---|---|
| 0 — golden ITCH | Cerrada. Golden Python, 22 tipos validados y evidencia de día real. |
| 1 — parser RTL | **No cerrada**: framing `s_axis_tkeep`, gaps, backpressure, 91/91 `tlast` y replay real bit a bit están verdes; REP-02 aún no mide `<=24` stalls en un tramo A/U real seleccionado de forma reproducible. El test del tramo (`test_rep02_tramo_au_real_line_rate`, primera ventana de 4 A/U desde el pcap sin índices manuales, stalls con downstream siempre listo) y la enmienda del criterio en la spec fase 1 están preparados y validados estáticamente (py_compile + gate F); **pendiente el rojo→verde en la máquina con cocotb**. |
| 2 — order book RTL | Cerrada funcionalmente: BBO bit a bit, replace atómico y replay real del subset. |
| 3 — DW=32/URAM | **Feed real CERRADO end-to-end (2026-08-20)**: con el push-out (iter 13) + drenado oversize corregido (iter 15), chain01 procesa el subset real (20 símbolos, 2.289 NOII) **bit a bit en BBO (17.484)**, conteo exacto, cross=0, anomaly=0, gaps=0 — a **DW=32/QB=46** (la latencia ~45 exige QB=46). Regresión completa VERDE en WSL: phase3 10/10 (sim 5/5, hash 8/8, depth 3/3, hard 2/2, parser 5/5, chain 5/5, chain-nd3 5/5, lat 2/2, rtm 4/4, rtm64 1/1), parser fase1 32/32, orderbook 17/17, uram 4/4+3/3. **Enmiendas de contrato documentadas (iter 13/15)**: (a) el desborde de niveles P=32 hace **push-out** (el add mejor que el peor entra; SEC-OV solo en el descarte/reduce-ausente), (b) el **depth** top-N es bit a bit hasta la 1ª re-entrada de un nivel descartado en el pico >P (ev. 14461, loc13 pico 420) y subconjunto de precios después (nunca fantasma); BBO siempre bit a bit, (c) **latencia RTM-LAT-01 re-derivada a media ≤ 70 ciclos** (medida 65,5 = 203,3 ns en el feed real; el ≤48 de iter 7 era de un tramo afortunado no representativo), determinista, histograma persistido en `verification/vectors/latency/latency_dw32.json`. Sigue **ABIERTO**: criterio 10 a 322 MHz (limitación estructural I/O del wrapper, WNS -3,319 ns en iter 11), la variante 156,25 MHz cerrada (WNS +0,015 ns) se re-sintetiza con el parser/orderbook actuales solo si el cierre lo exige, y P1 REP-02 pendiente de pcap. Detalles en `specs/fase3-optimizacion/verify-report.md`. |
| 4 – CME MDP3 | **Cerrada funcionalmente (2026-08-19)**: suite MDP3 DW=32/DW64 **14/14 PASS** en WSL (cocotb 2.0.1 + Verilator 5.046), gate B limpio, gate E **14/14** mutantes, gate C verible **0 hallazgos**. Criterio 5: puerta `DS_HDR` (schema_id==1 && version==12, resto passthrough) + MAX_MSG 256/257 (`M3-PASS-02`, `M3-SIZE-01/02`). Criterio 10: backpressure de salida estable (`M3-BP-01`). **Criterio 7 CERRADO**: validación tkeep MSB-contigua + descarte del paquete inválido (sin apend de beats inválidos, estado `CS_DISCARD` que drena hasta tlast y resetea colas; `M3-INV-04a/04a2/04b` activos; sub-caso 04a2 con huecos en el último beat y aporte intacto, nv=3). **Queda ABIERTO solo el timing** (sin proyecto Vivado MDP3: WNS/TNS/utilización NO EJECUTADOS) y el checker XML↔RTL pendiente. Hallazgo documentado: `literal_subset` del test (vector m53 de 87 B) es incoherente con el layout del template 53 y nunca se usó en la suite. |

No presentar la fase 3 como cerrada en el criterio 10 a 322 MHz (sigue
abierto por la limitación estructural del I/O del wrapper; la variante
156,25 MHz sí está cerrada con evidencia vigente). Las fases 1, 2 y 4
tienen sus criterios cerrados con evidencia vigente en el
`verify-report.md` correspondiente; cualquier criterio reabierto vuelve a
exigir rojo→verde y evidencia fresca antes de volver a presentarse como
cerrado.

## Fuentes de verdad

| Necesidad | Ubicación autoritativa |
|---|---|
| Reglas globales, proceso y estado | Este archivo |
| Contrato y criterios de una campaña | `specs/<campaña>/spec.md` y `gherkin/` |
| Evidencia de una campaña | `specs/<campaña>/verify-report.md` |
| Checks reproducibles | `verification/`, `scripts/verify/`, Makefiles y `synth/` |
| Instalación y problemas del entorno | `docs/DESARROLLO.md` |
| Plan de cierre ejecutable (qué falta y en qué orden) | `docs/writeup/plan-cierre.md` |
| Marcas verificables (números de timing/latencia/sim) | `docs/writeup/marcas.md` |
| Documento de presentación (arquitectura, hazards, latencia, timing, límites) | `docs/writeup/pipeline-itch-uram.md` |

Los informes históricos pueden mencionar el antiguo nombre de una etapa del
proceso; son evidencia fechada, no instrucciones operativas.

## Proceso obligatorio por campaña

1. **Especificar.** Crear o actualizar `specs/<campaña>/spec.md` y sus
   escenarios Gherkin antes de cambiar RTL o Python. Toda decisión que altere
   un contrato se documenta allí.
2. **Construir con rojo→verde.** Añadir primero el test que falla por el
   comportamiento buscado; ejecutar el rojo; implementar el cambio mínimo;
   ejecutar el verde. No modificar la spec para ocultar un fallo.
3. **Verificar.** Ejecutar los gates aplicables A–G, pegar outputs reales en
   `verify-report.md` y declarar de forma explícita cualquier gate no
   ejecutado. Un gate sin output no está pasado.
4. **Juzgar adversarialmente.** Reejecutar evidencia desde un ángulo que pueda
   refutarla: vector límite, mutante, consumidor del puerto o informe de
   timing. Un criterio solo cierra si todos sus gates aplicables pasan.

No hay comandos mágicos ni flujos ocultos: este archivo define el proceso.

## Gates A–G

| Gate | Exigencia |
|---|---|
| A — simulación | Cocotb/Verilator o unittest del área; cualquier fallo bloquea. |
| B — compilación | `verilator --lint-only --Wall` sobre RTL tocado; Python compilable. |
| C — estilo | `verible-verilog-lint --rules_config_search` sobre el RTL tocado (config del repo en `./.rules.verible_lint`, que alinea la nomenclatura del proyecto). Si no está instalado, declararlo NO EJECUTADO. |
| D — cobertura | Mapa literal spec↔test y, si existe herramienta, cobertura funcional. |
| E — mutación | Cada mutante compila y al menos un test lo mata; un mutante roto no cuenta. |
| F — completitud | `specs/gherkin-espejos.json` y títulos de tests coherentes con Gherkin. |
| G — rigor/timing | Sin datos crudos en Git, golden independiente, y Vivado WNS/TNS/recursos cuando aplique. |

### Comandos de referencia

```bash
# Golden Python
python3 -m unittest discover -s golden_model/tests -t .

# Áreas RTL
make -C verification/testbenches/parser sim
make -C verification/testbenches/orderbook sim
make -C verification/testbenches/phase3 sim
make -C verification/testbenches/uram sim-uram
make -C verification/testbenches/mdp3 sim

# Lint y síntesis estática de fase 3
verilator --lint-only --Wall --top-module itch_chain \
  rtl/itch_chain.sv rtl/parser/itch_parser.sv rtl/orderbook/orderbook.sv
python3 scripts/verify/synth_check.py
```

Cada campaña fija sus comandos completos, umbrales y top en su spec o Makefile.
No rebajar `--Wall`, omitir un mutante, ni convertir una omisión de datos en
PASS para cerrar una campaña.

## Reglas globales

- Español en documentación y commits; Conventional Commits.
- Datos de mercado reales jamás se versionan. Solo muestras sintéticas y
  vectores pequeños en `verification/vectors/`.
- El golden model es independiente del RTL: los tests comparan bit a bit contra
  él; nunca generar un oráculo desde el RTL probado.
- Antes de cambiar un puerto, señal, parámetro o layout, buscar todos sus
  consumidores. El `QB` efectivo de fase 3 se fija en `itch_chain.sv` y en el
  Makefile, no solo en defaults de submódulos.
- No introducir FIFO, dependencia o abstracción para esconder falta de
  throughput. Documentar el régimen real de backpressure y latencia.
- El owner necesita poder entender el estado leyendo la spec, el verify-report
  y este archivo, sin inspeccionar HDL.

## Layout

| Directorio | Contenido |
|---|---|
| `golden_model/` | Parser/modelo de referencia ITCH y CME, vectores y tests Python. |
| `rtl/` | Parseres y order book SystemVerilog. |
| `verification/` | Testbenches cocotb, vectores y Makefiles. |
| `scripts/verify/` | Mutación y validaciones reproducibles. |
| `specs/` | Contratos Gherkin e informes de evidencia por campaña. |
| `synth/` | Tcl/XDC e informes Vivado. |
| `docs/` | Setup, decisiones y write-ups; no define proceso operativo. |
