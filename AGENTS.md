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
| 3 — DW=32/URAM | **No cerrada** — evidencia de simulación verde (WSL, 2026-08-18): **sim-rtm 4/4, sim-rtm64 1/1, sim-lat 2/2** (media 44,5 ciclos ≤ 48) y regresión del área con SKIP solo por pcap ausente; gate B con 8x BLKSEQ deliberados (inferencia URAM) y gate E 30/30 mutantes. **Criterio 10 abierto**: 5 runs Vivado (base -10,492 → iter 9 -3,527 → iter 10 -3,748), URAM 32/48, DRC 0; el residual es I/O del wrapper (skew del área ~3 ns + output delay 1 ns; IOB packing no mueve los FFs del book por fanout interno). **Iter 11 (commit `bbd3b6c`)** lanzada: pipeline de salida del wrapper con retención del lado del pin (FFs propios con `IOB=TRUE`, mismo mecanismo que replicó `tready_ff`); resultado del run en `synth/reports/README.md`. **P1 REP-02**: pendiente de `/tmp/real_subset.pcap` (test listo; sin pcap no se cierra). |
| 4 — CME MDP3 | **No cerrada**: el framing `s_axis_tkeep` está **verde en WSL (cocotb 2.0.1 + Verilator 5.046, Python 3.12)**: suite MDP3 DW=32 9/9 y DW=64 9/9 (M3-FRM-05 a/b/c incluidos), gate B (verilator `--Wall`) limpio y gate E 9/9 mutantes (incluye `TKCNT-ALWAYS` del framing). Se corrigió el test M3-FRM-05b (mask del último beat mal derivada a DW=64: sumaba los bytes de relleno) y se añadió mutante tkeep. Siguen **abiertos**: criterio 5 (schema/version, MAX_MSG 256/257), criterio 7 restante (máscaras con huecos, loop separado), criterio 10 (backpressure de salida) y timing (sin Vivado MDP3). Gate C (verible) NO EJECUTADO (no instalado). Evidencia fresca pendiente de pegar en `specs/fase4-mdp3-parser/verify-report.md`. |

No presentar las fases 1, 3 o 4 como cerradas mientras sus criterios reabiertos
no tengan evidencia vigente en el `verify-report.md` correspondiente. Para
REP-02, el siguiente cierre debe seleccionar desde el pcap, sin índices
manuales, un tramo real de cuatro A/U consecutivos y contar sus stalls con el
downstream siempre listo; el total agregado del replay no sustituye esa medida.

## Fuentes de verdad

| Necesidad | Ubicación autoritativa |
|---|---|
| Reglas globales, proceso y estado | Este archivo |
| Contrato y criterios de una campaña | `specs/<campaña>/spec.md` y `gherkin/` |
| Evidencia de una campaña | `specs/<campaña>/verify-report.md` |
| Checks reproducibles | `verification/`, `scripts/verify/`, Makefiles y `synth/` |
| Instalación y problemas del entorno | `docs/DESARROLLO.md` |
| Plan de cierre ejecutable (qué falta y en qué orden) | `docs/writeup/plan-cierre.md` |

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
