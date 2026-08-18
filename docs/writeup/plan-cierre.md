# Plan de cierre — ejecución detallada

> Plan operativo para cumplir el objetivo del documento maestro sin repetir
> runs ni reabrir contratos. Fuente de verdad de **qué falta**; las specs y
> verify-reports siguen siendo el contrato y la evidencia. Fecha: 2026-08-18.
> No presenta las fases 1, 3 o 4 como cerradas.

## 0. Objetivo que hay que poder afirmar

Frase de CV del maestro (honesta):

> Pipeline FPGA UltraScale+ que decodifica Nasdaq TotalView-ITCH 5.0 a line
> rate de 10G y mantiene un order book en URAM con latencia determinista,
> verificado contra datos reales.

Alcance del repo: `MoldUDP64 → parser ITCH → book URAM → BBO/top-N`.
**MAC 10G / Ethernet / IP / UDP no se implementan.** CME MDP3 es stretch.
Cerrar 322,265625 MHz es el capítulo de optimización; 64b @ 156,25 MHz es el
equivalente de 10G si el criterio 10 no cierra.

Definición de cumplido (todas a la vez):

1. Fases 0 y 2 siguen cerradas (no reabrirlas).
2. REP-02 tiene output real: stalls ≤ 24 en la primera ventana de 4 A/U del
   pcap, downstream siempre listo, salida bit a bit vs oráculo.
3. `sim-rtm` + `sim-rtm64` + `sim-lat` verdes sobre el RTL de iter 7/8/9
   (media ≤ 48 ciclos). Gates A/E/B de fase 3 con output pegado.
4. Criterio 10 **o** WNS ≥ 0 y TNS = 0 y LUT ≤ 95 % en un run post-route,
   **o** explícitamente abierto + (opcional) variante 156,25 MHz cerrada +
   write-up del intento a 322.
5. Write-up de candidatura en el repo. Ninguna fase 1/3/4 se presenta
   cerrada si le falta evidencia vigente.

## 1. Mapa de máquinas

| Tarea | Dónde | Por qué |
|---|---|---|
| Vivado (criterio 10) | PC Windows, `C:\Xilinx\Vivado\2023.2` | Única máquina con Vivado |
| Parse rápido RTL | mismo PC, `xvlog.bat --sv --nolog` | Falso positivo preexistente `nx_done` |
| Sim cocotb / Verilator / mutación | máquina macOS (venv `.venv`) | Este PC no tiene verilator/cocotb/make |
| Docs / spec / wrapper | cualquiera | Texto y RTL de wrapper |

Setup macOS (si el venv no está):

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
verilator --version
cocotb-config --version
```

Pcaps locales (gitignored; sin ellos los replays son SKIP, nunca PASS):

| Artefacto | Path que leen los tests |
|---|---|
| Replay parser / REP-02 / P32-03 | `/tmp/real_subset.pcap` |
| Replay book / chain / latencia | `/tmp/real_trading.pcap` |

## 2. Inventario: qué está hecho y qué está mentiroso en docs

### Hecho (no repetir)

| Ítem | Evidencia |
|---|---|
| Fase 0 golden ITCH | `specs/fase0-golden-model/` cerrada |
| Fase 2 book funcional | 14/14, replace atómico, replay real |
| Framing ITCH `tkeep` | fase 1: 91/91 `tlast`, replay bit a bit |
| Cadena BBO/depth ND=5/3 | verify-report fase 3 (histórico) |
| URAM 32/48 inferida, DRC 0 | 5 runs Vivado 2026-08-18 |
| Iter 7–10 de timing | `synth/reports/README.md` |
| RTL MDP3 `s_axis_tkeep` | commit `62e4e46` |
| Test REP-02 tramo A/U | `test_rep02_tramo_au_real_line_rate` |
| Test M3-FRM-05 | `test_m3frm05_tkeep_bytes_validos_y_truncado_por_mascara` |
| 30 mutantes orderbook migrados | `scripts/verify/mutate_orderbook.py` |
| Docs consolidadas | `docs/writeup/lecciones-aprendidas.md` |

### Docs desactualizados (corregir ANTES de ejecutar RTL)

Estos textos dicen que el puerto MDP3 no existe. El RTL ya lo tiene.

| Archivo | Qué dice hoy | Qué debe decir |
|---|---|---|
| `AGENTS.md` fila fase 4 | «Pendiente: implementar el framing en `mdp3_parser.sv`» y «SkipTest mientras el RTL no exponga el puerto» | RTL implementado (`62e4e46`); pendiente rojo→verde M3-FRM-05 + gates A/E/B/C en cocotb; schema/MAX_MSG/BP/timing en loops separados |
| `specs/fase4-mdp3-parser/spec.md` addendum (≈356–377) | «el RTL actual no expone `s_axis_tkeep`»; SkipTest «mientras el RTL no exponga el puerto» | El puerto existe; el SkipTest ya no aplica; el cierre es output real de `make -C verification/testbenches/mdp3 sim` y `sim-dw64` |
| `specs/fase4-mdp3-parser/verify-report.md` cabecera | «El framing requiere implementar y verificar `s_axis_tkeep`» | Implementado en RTL; verificación (gate A) pendiente de output |

`README.md` ya está alineado (RTL hecho, rojo→verde pendiente).

No tocar: specs/verify-reports de fases 0 y 2 (cerradas). No reescribir
addendums de iter 7–10 de fase 3 (son evidencia fechada).

## 3. Orden de ejecución (no saltar)

```
P0  Higiene docs (este PC, 15 min)
P1  Fase 1 REP-02          → máquina cocotb
P2  Fase 3 sim + gates     → máquina cocotb
P3  Fase 4 framing verde   → máquina cocotb
P4  Timing iter 11         → este PC (un solo run)
P5  Si P4 falla: stop o 156,25 MHz (decisión del owner)
P6  Write-up de candidatura
P7  Stretch MDP3 (schema / MAX_MSG / BP) — no bloquea el CV
```

P1, P2 y P3 son independientes entre sí una vez P0 esté hecho. P4 no toca
book/parser: no invalida P1–P3 si el wrapper es el único cambio.

## 4. P0 — Higiene de documentación (este PC)

### 4.1 AGENTS.md, fila fase 4

Sustituir el párrafo actual por uno que diga, en este orden:

- Framing `s_axis_tkeep` **implementado** en `rtl/parser/mdp3_parser.sv`
  (`62e4e46`): puerto, `tkeep_cnt`, `qavail_eff`, apend por lanes válidos,
  tready con `tk_cnt`.
- Test M3-FRM-05 preparado; el `SkipTest` por puerto ausente **ya no aplica**.
- Pendiente: rojo→verde en máquina cocotb (`make -C verification/testbenches/mdp3 sim` y `sim-dw64`), gates A/E/B/C, pegar outputs en verify-report.
- Criterios 5 (schema/MAX_MSG), 7 (máscaras con huecos, loop separado), 10
  (backpressure de salida) y timing: loops independientes, no este cierre.

### 4.2 spec fase 4, addendum tkeep

Enmendar el párrafo «el RTL actual no expone…» a: el puerto está en el RTL;
el loop se cierra con output de cocotb, no con el SkipTest. No borrar el
contrato de máscara MSB-contigua ni el orden (a)/(b)/(c) de M3-FRM-05.

### 4.3 verify-report fase 4

Cambiar la cabecera vigente. Añadir una nota: «RTL tkeep commiteado
2026-08-18; gate A de M3-FRM-05 NO EJECUTADO hasta pegar output». No marcar
PASS.

### 4.4 Comprobar

```bash
python3 scripts/verify/check_itch_gherkin.py
```

Exige Gate F PASS. No commitear si el checker falla.

## 5. P1 — Fase 1, cierre de REP-02 (máquina cocotb)

### 5.1 Contrato (no negociable)

Spec: `specs/fase1-parser-rtl/spec.md` enmienda REP-02.

- Selección: primera ventana deslizante de 4 mensajes A/U consecutivos en
  orden de captura. **Sin índices manuales.** Implementada en
  `_first_au_window` + `test_rep02_tramo_au_real_line_rate`.
- Downstream siempre listo (`m_axis_tready=1`).
- Stalls = ciclos con `s_axis_tvalid && !s_axis_tready` durante el tramo.
- Umbral: **≤ 24**.
- Salida del tramo bit a bit contra el oráculo Python (nunca contra el RTL).
- El total agregado del replay (15.023 stalls / 91 paquetes) **no cierra**.
- Sin pcap o sin ventana de 4 A/U: SkipTest → criterio **sigue abierto**.

### 5.2 Comandos

```bash
source .venv/bin/activate
test -f /tmp/real_subset.pcap || echo "FALTA pcap; no ejecutar como PASS"
make -C verification/testbenches/parser clean
make -C verification/testbenches/parser sim \
  TESTCASE=test_rep02_tramo_au_real_line_rate
```

Si se quiere la suite completa del área (regresión, no cierra REP-02 sola):

```bash
make -C verification/testbenches/parser sim
```

### 5.3 Interpretación

| Resultado | Acción |
|---|---|
| `REP-02 line-rate OK: … stalls N` con N ≤ 24 y words == expected | Pegar el bloque entero en `specs/fase1-parser-rtl/verify-report.md`. Actualizar veredicto: brazo line-rate **cerrado** solo si además el resto de criterios de fase 1 ya estaban verdes. |
| Assertion `stalls > 24` | No enmendar el umbral. Diagnosticar (traza `qn`, ver lecciones §1–2). El criterio sigue abierto. |
| SkipTest (pcap o ventana ausente) | Declarar NO EJECUTADO / abierto. No sustituir por sintético. |
| Fallo bit a bit | Bug de framing o de selección. No tocar el golden. |

### 5.4 Gates de fase 1 al cerrar REP-02

Pegar outputs reales (no «se ejecutó»):

```bash
verilator --lint-only --Wall --top-module itch_parser \
  rtl/parser/itch_parser.sv
python3 scripts/verify/mutate_parser.py
verible-verilog-lint --rules_config_search rtl/parser/itch_parser.sv
python3 scripts/verify/check_itch_gherkin.py
```

Gate C: si verible no está, `NO EJECUTADO` (ya documentado para fases 1–3;
no bloquea el estilo histórico). Gate E: un mutante que no compile no cuenta.

## 6. P2 — Fase 3, rojo→verde de iter 7/8/9 + gates (máquina cocotb)

El RTL de book/parser de las iter 7/8/9 **ya está commiteado**. No reimplementar.
Esta pasada valida que no se rompió semántica ni latencia.

### 6.1 Simulación (gate A)

```bash
source .venv/bin/activate
make -C verification/testbenches/phase3 clean-all
make -C verification/testbenches/phase3 sim-rtm
make -C verification/testbenches/phase3 sim-rtm64
make -C verification/testbenches/phase3 sim-lat
```

| Target | Top | Tests | Cierre |
|---|---|---|---|
| `sim-rtm` | orderbook DW=32 | RTM-01..04 (`test_rtm01`…`test_rtm04`) | 4/4 PASS |
| `sim-rtm64` | orderbook DW=64 | RTM-REG-01 (`test_rtm_reg01_…`) | 1/1 PASS |
| `sim-lat` | itch_chain DW=32 | SEC-LAT / RTM-LAT-01 | media **≤ 48** ciclos; JSON regenerado si el test lo escribe |

Gotcha: cada target usa `SIM_BUILD` propio (`sim_build_rtm`, `sim_build_rtm64`,
`sim_build_chain`). No reutilizar un build entre `-G` distintos.

Regresión recomendada (no sustituye a las tres de arriba):

```bash
make -C verification/testbenches/phase3 sim-chain
make -C verification/testbenches/phase3 sim-chain-nd3
make -C verification/testbenches/uram sim-uram
```

`sim-lat` y chain reales necesitan `/tmp/real_trading.pcap`. Sin pcap: SKIP,
no PASS.

### 6.2 Latencia

Umbral vigente: media ≤ 48 ciclos (SEC-URAM-04 enmendado / RTM-LAT-01).
Iter 8 añadió +1 ciclo (FIFO wrapper no se simula; la cadena sí puede haber
crecido por el pipeline A/B/C de iter 7). Si media > 48: no subir el umbral
sin medición citada en la spec. Actualizar `docs/writeup/latencia.md` y
`verification/vectors/latency/latency_dw32.json` **solo** con la pasada
fresca.

### 6.3 Gates B / E / C / F

```bash
verilator --lint-only --Wall --top-module itch_chain \
  rtl/itch_chain.sv rtl/parser/itch_parser.sv rtl/orderbook/orderbook.sv
python3 scripts/verify/mutate_orderbook.py
verible-verilog-lint --rules_config_search rtl/orderbook/orderbook.sv
python3 scripts/verify/check_itch_gherkin.py
python3 scripts/verify/synth_check.py
```

Gate E: 30 mutantes. Cada uno debe **compilar** y **morir** en al menos un
test. Objetivos ya migrados (no volver a `decode_lv2()` ni `fnd==-1`):

- `OV-EMPTY` → `!lv2_afnd && !lv2_aemp`
- `PIPE-SKIP-STAGE` → `decode_lv2b();`
- `LV-NEGWRAP` → `!lv2_afnd && lv_delta[31]`
- `EMIT-FINDFIRST-INV` → `first_one(~nzb_next)`

Si un mutante no encuentra su string: **parar** y migrar el objetivo; no
contar un mutante roto como muerto.

### 6.4 Verify-report fase 3

Pegar los bloques de `sim-rtm` / `sim-rtm64` / `sim-lat` / mutate / verilator
en `specs/fase3-optimizacion/verify-report.md`. Declarar explícitamente
cualquier gate no corrido. El gate G (Vivado) **sigue abierto** hasta P4/P5;
no marcarlo PASS porque las sims pasen.

## 7. P3 — Fase 4, framing tkeep verde (máquina cocotb)

### 7.1 Estado real del RTL (no reimplementar)

`rtl/parser/mdp3_parser.sv` ya tiene:

- `input wire [DW/8-1:0] s_axis_tkeep`
- `function tkeep_cnt` (popcount)
- `qavail_eff` usa `tk_cnt` en handshake
- apend solo `k < tk_cnt` bytes, MSB-first:
  `s_axis_tdata[8*(BYTES-1-k) +: 8]`
- `s_axis_tready = (qavail + tk_cnt <= MAX_MSG) && (cst != CS_WAIT) && !pkt_end_eff`
- beat `tkeep=0` se consume sin aportar

El test `test_m3frm05_…` hace `SkipTest` solo si `not hasattr(dut, "s_axis_tkeep")`.
Con el puerto presente el SkipTest **no debe dispararse**.

### 7.2 Rojo→verde

```bash
source .venv/bin/activate
make -C verification/testbenches/mdp3 clean-all
make -C verification/testbenches/mdp3 sim \
  TESTCASE=test_m3frm05_tkeep_bytes_validos_y_truncado_por_mascara
make -C verification/testbenches/mdp3 sim
make -C verification/testbenches/mdp3 sim-dw64
```

M3-FRM-05 exige, en el mismo test:

- (a) bytes válidos MSB-contiguos → record correcto
- (b) longitud declarada que cae en lanes `tkeep=0` → `error` + recuperación
- (c) beat vacío (`tkeep=0`) en medio del burst → no se traba

Regresión: toda la suite DW=32 y DW=64 (M3-FRM-01 … M3-INV-04). El driver
aplica `tkeep` completo por defecto cuando el puerto existe.

### 7.3 Gates

```bash
verilator --lint-only --Wall --top-module mdp3_parser \
  rtl/parser/mdp3_parser.sv
python3 scripts/verify/mutate_mdp3.py
verible-verilog-lint --rules_config_search rtl/parser/mdp3_parser.sv
python3 scripts/verify/check_itch_gherkin.py
```

Mutantes MDP3 actuales (8): `TPL47-ID`, `TRUNC-NOERROR`, `SEQ-NOGAP`,
`GROUP-COUNT`, `GROUP-BOUNDS`, `PASS-NOBODY`, `PRICE-SWAP`, `PUSH-IDLE`.
Si el framing nuevo no está cubierto por ninguno, **añadir un mutante**
(p. ej. `tk_cnt` forzado a `BYTES`, o apend que ignore la máscara) **antes**
de declarar gate E del loop tkeep. Un mutante nuevo: primero el test que lo
mata (M3-FRM-05), luego el string único en el RTL.

### 7.4 Qué NO cierra este loop

Aunque P3 esté verde, la fase 4 **sigue abierta** por:

| Criterio | Qué falta | Loop |
|---|---|---|
| 5 | schemaId/version no soportados → passthrough; `msg_size` 256 vs 257 | separado |
| 7 (parte) | máscaras con huecos / parcial sin `tlast` | separado (addendum: fuera de tkeep MSB-contiguo) |
| 8 | regresión fases 1–3 tras tkeep (P1+P2) | se cierra cuando P1 y P2 pasen |
| 9 | lint + checker XML↔localparam | gate B/C de este loop + checker existente |
| 10 | backpressure de **salida** (`m_axis_*` estables) | separado |
| Timing | Vivado sobre `mdp3_parser` | no se acredita sin run |

Pegar outputs en `specs/fase4-mdp3-parser/verify-report.md`. Un SkipTest de
M3-FRM-05 **no** cierra el criterio 2.

## 8. P4 — Timing, un solo run más (este PC)

### 8.1 Por qué no repetir iter 7–10

| Iter | Qué se probó | Resultado | No repetir |
|---|---|---|---|
| 7 | ST_EMIT → A/B/C | WNS -7,395 | retiming del escaneo |
| 8 | decode 2a/2b + FIFO wrapper | WNS -4,052 | partir decode otra vez |
| 9 | guard solo tvalid + `first_one` | WNS **-3,527** (mejor) | volver a meter tready en el guard |
| 10 | IOB=TRUE en puertos del book + tready_ff | WNS -3,748 (peor) | IOB sobre FFs del book |

Lección: los FFs `bbo_*` / `depth_*` del book tienen fanout interno
(retención `orderbook.sv:507-508` y guard `:838`). Vivado no los empaca
(`Synth 8-4163` solo replicó `tready_ff`). FF interno → pin pierde
skew ~2,7–3,1 ns + output delay 1,0 ns.

### 8.2 Único candidato no quemado

Pipeline de **salida en el wrapper** (`synth/itch_chain_synth.sv` solamente).
Book y parser **intocados**.

Diseño (no improvisar):

1. El book sigue conectado a wires internos (`bbo_locate_i`, `bbo_tdata_i`,
   `bbo_tvalid_i`, `bbo_changed_i`, `depth_full`, `depth_tvalid_i`).
   `bbo_tready` y `depth_tready` del pin van **directos** al book (línea 501
   del book intacta; no registrar esos tready).
2. FFs del wrapper, con `(* IOB = "TRUE" *)` en los puertos de salida (ya
   están en los puertos; el driver debe ser el FF del wrapper, no el del book):

```text
si !rst_n_c:
    bbo_tvalid   <= 0
    depth_tvalid <= 0
    (buses a 0)
si no:
    bbo_tvalid   <= bbo_tvalid && !bbo_tready
    depth_tvalid <= depth_tvalid && !depth_tready
    si (bbo_tvalid_i && !bbo_tvalid):
        capturar locate/tdata/changed del book
        bbo_tvalid <= 1
    si (depth_tvalid_i && !depth_tvalid):
        capturar depth_full[31:0]
        depth_tvalid <= 1
```

3. Conservar `tready_ff` de iter 10 (sí se empacó; no revertirlo).
4. Conservar FIFO 4×DW + `rst_n_c` de iter 8.

Equivalencia: el par en el pin es visible 1 ciclo tras la aceptación del
consumidor; no duplica si el consumidor mantiene tready=1. +1 ciclo solo en
el pin. RTM-LAT mide la cadena (`itch_chain`), no este wrapper.

### 8.3 Spec antes del RTL

Enmendar el addendum iter 10 (o añadir **iter 11**) en
`specs/fase3-optimizacion/spec.md`:

- Evidencia run 10: WNS -3,748; IOB no aplicó a FFs del book.
- Cambio: pipeline de salida + retención del pin (el diseño de §8.2).
- Stop **final**: si no cierra, criterio 10 abierto; no más runs a 322 MHz
  sin decisión explícita del owner. Gate del tcl **intacto**.

No modificar la spec para ocultar un fallo. No bajar LUT/WNS del tcl.

### 8.4 Validación estática (antes del run de 2,5 h)

```text
C:\Xilinx\Vivado\2023.2\bin\xvlog.bat --sv --nolog synth\itch_chain_synth.sv
python3 scripts/verify/synth_check.py
python3 scripts/verify/check_itch_gherkin.py
```

xvlog: 0 ERROR nuevos. `rst_n_c` / `tready_ff` deben estar declarados
**antes** de usarse (xvlog 2023.2 lo exige; Verilator no).

### 8.5 Lanzar el run

Desde `synth/`:

```text
C:\Xilinx\Vivado\2023.2\bin\vivado.bat -mode batch -source fase3_synth.tcl -log fase3_run_iter11.log -journal fase3_journal_iter11.log
```

No cambiar `fase3_synth.tcl` ni el XDC (periodo 3,103 ns, output delay 1,0 ns,
part `xcku3p-ffva676-2L-e`).

### 8.6 Extraer evidencia

Al terminar, buscar `FASE3 TIMING FAIL` o `FASE3 SYNTH OK` en el log.

| Métrica | Dónde |
|---|---|
| WNS / TNS / endpoints | `synth/reports/timing_impl.txt` línea `Setup :` |
| LUT as Logic | `synth/reports/util_impl.txt` |
| URAM | misma, fila URAM |
| 10 peores rutas | `Slack (VIOLATED)` en `timing_impl.txt` |
| ¿IOB replicó los FFs nuevos? | log: `Replicating register … IOB=TRUE` debe citar `bbo_tvalid` / `bbo_tdata` / etc. del **wrapper**, no `u_book/bbo_*_reg` |

Actualizar en el mismo commit de evidencia:

- `specs/fase3-optimizacion/verify-report.md` (sección run 11)
- `synth/reports/README.md` (fila nueva)
- `AGENTS.md` fila fase 3
- `docs/writeup/lecciones-aprendidas.md` §7 si hay lección nueva

Los `synth/reports/*.txt` son siempre del **último** run; commitearlos con
la evidencia.

### 8.7 Criterio de parada

- WNS ≥ 0 **y** TNS = 0 **y** LUT ≤ 95 % **y** URAM 32/48 → criterio 10
  cierra (gate G de fase 3).
- Cualquier otro resultado → **STOP**. Criterio 10 abierto. Ir a P5.

Prohibido: otra iteración de retiming del book, otro IOB sobre FFs del book,
bajar el output delay del XDC, bajar el periodo, rebajar el `error` del tcl.

## 9. P5 — Si el criterio 10 no cierra (decisión del owner)

Dos opciones honestas; elegir **una** y documentarla en la spec:

**A. Dejar 322 MHz abierto.** El write-up (P6) cuenta los 5+1 runs, WNS
mejor -3,527 ns, LUT ~95,8 %, URAM 32/48, y por qué el residual es I/O del
wrapper de síntesis. El proyecto sigue siendo demostrable (maestro §203:
sim + informe Vivado, aunque WNS < 0, si se declara).

**B. Variante 64b @ 156,25 MHz** (maestro §0.1: mismo 10G, más fácil).
Requiere spec nueva o addendum (periodo 6,400 ns, `DW=64` en el tcl, XDC
nuevo o parametrizado). Un run. Si WNS ≥ 0, se afirma «10G cerrado a
156,25 MHz» y se deja 322 como intento documentado. **No** afirmar cierre
a 322.

No hacer las dos a la vez en el mismo commit. No vender B como si fuera A.

## 10. P6 — Write-up de candidatura

Crear **un** documento (p. ej. `docs/writeup/pipeline-itch-uram.md`) cuando
P1–P3 tengan outputs y P4/P5 tengan veredicto. Contenido mínimo del maestro:

1. Arquitectura del pipeline y límite honesto (sin MAC; subset 20 símbolos).
2. Hazards del book (replace atómico, URAM 1 write/ciclo, retención BBO).
3. Histograma de latencia (JSON vigente post `sim-lat`).
4. Tabla de runs Vivado (copiar de `synth/reports/README.md`).
5. Framing `tkeep` y por qué el line-rate infinito de mínimos es non-goal
   (Anexo A, lecciones §9 / spec fase 1 criterio 2).
6. Qué no está: MAC, libro completo Nasdaq, fase 4 timing, criterio 10 si
   quedó abierto.

No duplicar specs. Enlazarlas. Actualizar la tabla del `README.md` raíz
con los veredictos **después** de pegar evidencia, no antes.

## 11. P7 — Stretch MDP3 (no bloquea el CV)

Solo después de P3 verde. Un loop por vez, spec primero, rojo→verde:

1. Criterio 5: schemaId/version y techo `msg_size` 256/257.
2. Criterio 7 restante: máscaras con huecos / parcial sin `tlast`.
3. Criterio 10: backpressure de salida.
4. Timing MDP3: no se acredita sin Vivado dedicado; no mezclar con fase 3.

## 12. Checklist de commits (Conventional Commits, español)

| Paso | Tipo de mensaje | Archivos típicos |
|---|---|---|
| P0 | `docs:` higiene estado fase 4 | AGENTS.md, spec/verify fase 4 |
| P1 | `test:` / `docs:` evidencia REP-02 | verify-report fase 1 |
| P2 | `docs:` evidencia sim-rtm/lat + gates | verify-report fase 3, latencia.md, JSON |
| P3 | `docs:` / `test:` M3-FRM-05 verde (+ mutante si se añade) | verify-report fase 4, mutate_mdp3.py |
| P4 RTL | `perf(fase3):` iter 11 pipeline salida wrapper | spec addendum + itch_chain_synth.sv |
| P4 evidencia | `docs:` evidencia run 11 | reports + verify-report + AGENTS + README synth |
| P5 | `docs:` veredicto criterio 10 / spec 156 MHz | spec + write-up |
| P6 | `docs:` write-up de candidatura | docs/writeup/… |

Nunca commitear pcaps, schemas CME crudos de mercado, ni `xvlog.pb`.
Nunca `git add` de `data/`. Staging selectivo.

## 13. Prohibiciones (para no deshacer el proyecto)

- Presentar fases 1, 3 o 4 como cerradas sin output vigente en su
  verify-report.
- Convertir un SKIP de pcap en PASS.
- Generar el oráculo desde el RTL.
- Meter FIFO extra para esconder falta de throughput.
- Registrar `bbo_tready`/`depth_tready` hacia el book (duplica el par).
- Poner IOB=TRUE esperando que mueva `u_book/bbo_*_reg`.
- Cambiar defaults de `itch_parser.sv` creyendo que mueven la cadena (el
  QB efectivo está en `itch_chain.sv` / tcl `-G` / wrapper).
- Usar `Add-Content` de PowerShell 5.1 sobre markdown (cp1252 / BOM; rompe
  gate F). Editar con las herramientas del repo o Python UTF-8 sin BOM.
- Rebajar `--Wall`, omitir un mutante, o bajar WNS/LUT del tcl.
- Abrir MAC/PHY/IP/UDP para «completar 10G».
- Segundo run de 322 MHz después de un fallo de P4 sin decisión del owner.

## 14. Comandos de referencia (copia rápida)

```bash
# Golden
python3 -m unittest discover -s golden_model/tests -t .

# Áreas RTL
make -C verification/testbenches/parser sim
make -C verification/testbenches/orderbook sim
make -C verification/testbenches/phase3 sim
make -C verification/testbenches/phase3 sim-rtm
make -C verification/testbenches/phase3 sim-rtm64
make -C verification/testbenches/phase3 sim-lat
make -C verification/testbenches/uram sim-uram
make -C verification/testbenches/mdp3 sim
make -C verification/testbenches/mdp3 sim-dw64

# Gates
verilator --lint-only --Wall --top-module itch_chain \
  rtl/itch_chain.sv rtl/parser/itch_parser.sv rtl/orderbook/orderbook.sv
verilator --lint-only --Wall --top-module mdp3_parser rtl/parser/mdp3_parser.sv
python3 scripts/verify/mutate_parser.py
python3 scripts/verify/mutate_orderbook.py
python3 scripts/verify/mutate_mdp3.py
python3 scripts/verify/check_itch_gherkin.py
python3 scripts/verify/synth_check.py
verible-verilog-lint --rules_config_search rtl/parser/mdp3_parser.sv
```

Windows (Vivado, desde `synth/`):

```text
C:\Xilinx\Vivado\2023.2\bin\vivado.bat -mode batch -source fase3_synth.tcl -log fase3_run_iter11.log
C:\Xilinx\Vivado\2023.2\bin\xvlog.bat --sv --nolog synth\itch_chain_synth.sv
```

## 15. Dónde está cada verdad

| Pregunta | Archivo |
|---|---|
| ¿Está cerrada la fase X? | `AGENTS.md` + `specs/<fase>/verify-report.md` |
| ¿Qué exige el contrato? | `specs/<fase>/spec.md` + `gherkin/` |
| ¿Qué WNS salió? | `synth/reports/README.md` |
| ¿Por qué no repetir un run? | este plan §8.1 + `docs/writeup/lecciones-aprendidas.md` §7 |
| ¿Cómo se instala el entorno? | `docs/DESARROLLO.md` |
| ¿Cuál es el objetivo de CV? | documento maestro en la raíz |
