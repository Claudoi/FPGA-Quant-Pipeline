# fase1-parser-rtl (fase 1 del maestro)

## Goal

Construir el parser RTL **a line rate** Nasdaq TotalView-ITCH 5.0 en
SystemVerilog (compatible Verilator): consume el **payload MoldUDP64**
(decapado de IP/UDP en el testbench), valida el framing y la secuencia,
alinea los mensajes que cruzan límites de palabra/paquete, decodifica los
tipos del subset (`S, R, A, F, E, C, X, D, U, P`) y emite por AXI-Stream un
**registro decodificado por mensaje**, byte a byte idéntico al de los
vectores de mensajes del golden model. Es la etapa previa al order book
(fase 2): su salida es la entrada del engine URAM.

No construye libro: convierte un flujo crudo en `mensajes normalizados +
señalización de gaps de secuencia`, a 1 palabra/ciclo en el peor caso, sobre
un datapath 64-bit @ 156,25 MHz.

## Scope

**In scope:**

- `rtl/parser/` — módulos SystemVerilog del datapath de parsing:
  - **Framing MoldUDP64** en el RTL: consumo del payload (session u64+u16,
    seq u64, count u16) y **detección/senialización de gaps de sequence
    number** (seq esperado = prev_seq + prev_count; gap si seq_actual >
    esperado). Decap IP/UDP queda en el testbench (ver no-goals). — decisión
    de la entrevista Q8: los gaps SÍ entran en fase 1.
  - **Alineador** (barrel shifter): mensajes que cruzan límites de palabra de
    8 B y de paquete (tlast), manteniendo 1 palabra/ciclo.
  - **FSM de parsing**: identifica `msg_type`, valida longitud declarada,
    extrae campos.
  - **Decoder `S,R,A,F,E,C,X,D,U,P`** → registro normalizado.
  - Top `itch_parser`.
- `rtl/parser/common/` (o `rtl/common/`) — helpers compartidos (registros de
  pipeline, FIFO de handshake) si `rtl/common/` no los aporta ya.
- `verification/testbenches/parser/` — testbenches cocotb + Verilator:
  - **Replay de pcaps** generados con `scripts/binaryfile_to_pcap.py`:
    decap de Ethernet/IPv4/UDP en el testbench (los paquetes reales que sí
    cruzan palabras/paguetes), alimentando el payload MoldUDP64 al RTL.
  - Oráculo byte a byte contra los **vectores de mensajes** del golden.
  - Vectores congelados commiteados en `verification/vectors/messages/`.
- **Extensión pactada de fase 0** (`golden_model/`): nuevo modo de volcado
  `--emit-messages` que emite, por cada mensaje modificador/del subset, el
  registro decodificado (Anexo A) — oráculo de mensajes, no BBO. Es un edit
  explícito pactado de la spec fase 0 (no reabre la campaña).
- Vectores congelados pequeños de mensajes commiteados en
  `verification/vectors/` (híbrido: congelado + por-iteración).

**Out of scope (non-goals):**

- Order book / BBO / URAM: fase 2 (aquí solo mensajes normalizados).
- Decap Ethernet/IPv4/UDP **en el RTL**: lo hace el testbench; el RTL recibe
  el payload MoldUDP64 (sesión+seq+count+mensajes). (El MAC 10G / decap full
  IP/UDP sería una fase propia posterior.)
- Detección de desduplicación/arbitraje A/B de feeds (avanzado, no ITCH).
- Recovery/GLIMPSE/snapshot.
- Variantes 32-bit @ 322 MHz (fase 3), timing closure Vivado (fase 3).
- Métricas de latencia wire-to-BBO (fase 2).
- Consumo de los 22 tipos: solo los 10 del subset se decodifican a registro;
  los demás (H, I, B, N, W, O, …) se **validan por longitud y se cuentan**
  (en línea, sin romper line rate), idéntico al criterio de fase 0.
- CME MDP3 (fase stretch 4).

**Radio medido (2026-08-12):** `rtl/parser/` y `rtl/orderbook/` están vacíos
(verificado con `find rtl/ -type f`); `rtl/common/` vacío de fuentes. No se
renombra ni mueve nada existente. `verification/testbenches/` y
`verification/scripts/` vacíos de fuentes.

## Constraints

- **Familia/part objetivo:** AMD/Xilinx UltraScale+ (part del documento
  maestro; se fija en síntesis fase 3). Datapath **64-bit @ 156,25 MHz**
  (el que entrega el core 10GBASE-R).
- **Line rate medido, sin promesa imposible:** el datapath usa AXI-Stream
  completo y el test pactado mide cuatro A/U con QB=64, salida bit a bit y
  stalls acumulados `<=24`. El peor caso infinito de mensajes mínimos es un
  non-goal físico porque el Anexo A produce más bytes que el wire; se declara
  en el criterio 2 y no se esconde con una FIFO ni con una afirmación de cero
  stalls.
- Endianness: ITCH y MoldUDP64 son **big-endian** en el cable; los registros
  decodificados (Anexo A) se emiten en el **orden de campos del wire**
  (big-endian), de modo que el RTL no hace byte-swaps y la comparación byte a
  byte vs. golden es directa. No mezclar.
- Determinismo: mismo pcap de entrada → mismos registros de salida bit a bit;
  si aparece un gap de secuencia, el parsing continúa (no aborta), lo señaliza
  y lo cuenta.

## Superficie y amenazas

**Entradas nuevas (puertos del top `itch_parser`):**

| Señal | Ancho | Descripción |
|---|---|---|
| `clk` | 1 | 156,25 MHz |
| `rst_n` | 1 | reset activo bajo, síncrono |
| `s_axis_tdata` | 64 | palabra del payload MoldUDP64 (ya decapado de IP/UDP) |
| `s_axis_tvalid` | 1 | hay palabra válida |
| `s_axis_tready` | 1 | el parser acepta la palabra |
| `s_axis_tlast` | 1 | última palabra del payload UDP (fin de paquete) |

**Salidas nuevas:**

| Señal | Ancho | Descripción |
|---|---|---|
| `m_axis_tdata` | 64 | registro de mensaje decodificado (Anexo A), 1+ palabras |
| `m_axis_tvalid` | 1 | hay datos de salida |
| `m_axis_tready` | 1 | el downstream consume |
| `m_axis_tlast` | 1 | última palabra del registro del mensaje |
| `gap_detected` | 1 | pulso cuando se detecta un hueco de seq (contado interno) |
| `error` | 1 | frame malformado / longitud incoherente (fail con señal, sin abortar el stream) |

**Mensajes de salida decodificados (10 tipos):** `S, R, A, F, E, C, X, D, U, P` —
es la lista literal que el barrido de `/verify` ataca.

**Casos de abuso del dominio** (cada uno con su escenario `SEC-` en Gherkin):

- **Gap de secuencia MoldUDP64** (`seq_actual > esperado`) — SEC-GAP-01.
- **Mensaje que cruza límite de palabra de 8 B** — SEC-ALN-01.
- **Mensaje que cruza límite de paquete** (tlast en medio de un mensaje:
  en MoldUDP64 un mensaje nunca se parte entre paquetes, pero el RTL debe
  gestionarlo con firmeza: count inconsistente con el último paquete) —
  SEC-FRM-02.
- **Tipo no decodificable** (fuera del subset): validar longitud, avanzar el
  `msg_idx` global y no emitir registro — SEC-PAR-04/05.
- **Longitud declarada incoherente / frame truncado** — SEC-FRM-01, SEC-PAR-03.
- **Tramo A/U back-to-back con QB=64** (régimen medido) — LIN-01/SEC-LIN-01.
- **Backpressure del downstream** (tready bajo) sin pérdida de datos — SEC-OUT-02.
- **Mensaje de sesión nueva** (session cambia) → reset de seq esperado — SEC-FRM-03.
- **count = 0** en un paquete (válido en MoldUDP64) — SEC-FRM-04.
- **Reemplazos/duplicados de seq** (seq == esperado, no gap): aceptar — SEC-GAP-02.

**Qué se arriesga del maestro:** la **latencia determinista y el throughput
medido**; un alineador mal diseñado o un decoder con lógica combinational larga
rompe la cadena de 64-bit @ 156,25 MHz. El framing + gaps acercan el manejo
real del feed (decisión Q8/Q9).

## Reuso

- `golden_model/itch/messages.py` — **fuente única de layouts ITCH** (nada de
  literales de protocolo fuera de aquí): el cocotb y el `--emit-messages` la
  usan como oráculo. Si un tipo del subset falta como layout completo, se
  añade aquí con `grep` de su struct (extensión pactada de fase 0).
- `golden_model/itch/parser.py`, `golden_model/src/vectors.py` — reutilizados
  por el modo `--emit-messages`.
- `scripts/binaryfile_to_pcap.py` — genera los pcaps de replay (disponible y
  verificado en fase 0, criterio 8).
- `requirements-dev.txt` — cocotb/cocotb-bus/numpy (creado en esta campaña).
- Dependencia cocotb-bus: se evita si el handshake se prueba a mano (data + 3
  flags/sanitización); se añade solo si pacta aquí.
- **Código nuevo que duplique** una tabla de layout ITCH = FAIL de la lente de
  simplicidad de `/grade`: todo deriva de `messages.py`.

## Criterios de aceptación (Definition of Done)

1. [x] El parser consume el payload MoldUDP64 y emite un **registro
   decodificado (Anexo A) por cada mensaje de los 10 tipos del subset**,
   byte a byte idéntico al `--emit-messages` del golden model (known-answer
   sintético, incl. un mensaje de cada tipo).
   — Gherkin: `parser.feature` §PAR-01, §SEC-PAR-04; `output.feature` §OUT-01
2. [x] **Line rate (alcance acotado):** en un tramo literal de cuatro mensajes
   A/U back-to-back que cabe amortiguado en la cola (QB=64), con el downstream
   consumiendo, el RTL conserva la salida bit a bit y acumula como máximo 24
   ciclos de stall de entrada; no se presenta ese tramo como cero stalls.
   — Gherkin: `datapath.feature` §LIN-01
   — **Decisión de spec (edit 2026-08-13, iteración 3):** el peor caso de
   mensajes MÍNIMOS (`D` 19 B, `X` 23 B, `S` 12 B) **back-to-back infinito** se
   declara **non-goal físico** de esta campaña. El registro normalizado del
   Anexo A añade 16 B de overhead por mensaje (word0 + word1), de modo que la
   salida AXI-Stream siempre excede la entrada (D: 24 B salida por 21 B feed;
   S: 24/14) y ningún aligner alcanza «1 palabra/ciclo infinito» con una cola
   finita. Se verifica con el tramo acotado que cabe amortiguado (stalls `<=24`),
   y el límite se documenta en `docs/research-parser-rtl-pendientes.md` §C.0
   como non-goal derivado del Anexo A (no como defecto de RTL). Si en el futuro
   se requiere el caso infinito, la decisión es rediseñar el Anexo A (salida
   comprimida / bus más ancho), no parchear el parser.
   — Gherkin: `datapath.feature` §LIN-01
3. [x] El alineador decodifica correctamente cualquiera de las 8 alineaciones
   de un mensaje dentro de la palabra de 64-bit, incluidos mensajes que
   cruzan el límite de palabra.
   — Gherkin: `datapath.feature` §ALN-01
4. [x] **Framing MoldUDP64:** sesión, seq y count parseados; seq esperado =
   prev_seq + prev_count; un **gap** se señaliza (`gap_detected`), se cuenta y
   el parsing continúa; seq == esperado (sin gap) no señaliza; cambio de
   sesión resetea el seq esperado; count=0 es válido.
   — Gherkin: `framing.feature` §FRM-01, §FRM-02, §SEC-GAP-01, §SEC-GAP-02,
   §SEC-FRM-03, §SEC-FRM-04
5. [x] **AXI-Stream con backpressure:** con `tready` bajo intermite el parser
   retiene el stream sin perder ni duplicar ningún registro (oráculo byte a
   byte); la secuencia `tvalid/tready/tlast` respeta el handshake.
   — Gherkin: `output.feature` §OUT-02, §OUT-03
6. [x] Los 22 tipos canónicos de `MESSAGE_LENGTHS`, incluidos los que están
   fuera del subset, se validan por longitud antes de continuar. Los tipos
   fuera del subset se contabilizan en el `msg_idx` global y **no** emiten
   registro ni rompen el line rate; un tipo conocido con longitud incorrecta
   pulsa `error` y se descarta. No se añade un banco de contadores por tipo:
   nunca formó parte de los puertos y ningún consumidor del pipeline lo usa.
   — Gherkin: `parser.feature` §SEC-PAR-04
7. [x] Longitud incoherente / frame truncado cancelan el mensaje con `error`,
   descartan el resto del datagrama inválido y continúan desde la cabecera del
   siguiente paquete íntegro (sin abortar el stream, fail con señal).
   — Gherkin: `parser.feature` §SEC-PAR-03, §SEC-FRM-01, §SEC-FRM-02
8. [x] **Replay real de fase 1 (hybrid oracle):** el RTL procesa los registros
   de los mensajes del subset de un pcap local del día real/replay, y su
   salida es byte a byte idéntica al oráculo `--emit-messages` sobre ese mismo
   pcap. Además, un par de **vectores congelados** pequeños se commitean en
   `verification/vectors/messages/` y el RTL los reproduce.
   — Gherkin: `replay.feature` §REP-01, §REP-02
9. [x] **Cabos de fase 0** (decisión pendiente #2, cerrados ANTES del RTL):
   el día de regresión `01302019` se procesa sin anomalías de invariantes y
   los vectores sintéticos pequeños se commitean. Se documenta en el
   verify-report de fase 0 (edit de ese informe) o en este spec como
   pre-trabajo pactado.
   — Verificación: comando de `run_golden.py` sobre el día de regresión.
10. [x] Cocotb + Verilator compilan el top con `--Wall` sin warnings reales
    silenciados (trinquete documentado por área, cero silencios).
    — Gherkin: estático (gate B/C de verify; sin escenario).
11. [ ] Lint y estilo: `verible-verilog-lint` + `verilator --lint-only` en
    verde sobre `rtl/parser/`.
    — Sin escenario (gate B/C).

## Verificación

| Criterio | Cómo se prueba |
|---|---|
| 1 | cocotb `test_*` espejo de `parser.feature`/`output.feature` sobre vectores sintéticos (oráculo messages.py + `--emit-messages`) |
| 2 | cocotb: cuatro A/U back-to-back con QB=64, salida bit a bit y stalls `<=24` con tready=1 |
| 3 | cocotb: barrido de las 8 alineaciones (escenario ALN-01 con Esquema) |
| 4 | cocotb: secuencias fabricadas (gap, sin-gap, cambio de sesión, count=0) |
| 5 | cocotb: tready aleatorio/pérdida controlada, comparar salida vs oráculo sin pérdida/dup |
| 6 | cocotb: H canónico/longitud H incorrecta entre mensajes A; chequear validación, avance de `msg_idx` y no-registro |
| 7 | cocotb: longitudes rotas / frames truncados → `error`, continuación |
| 8 | cocotb: replay de pcap del día real (local, `data/itch_sample/`) + vectores congelados commiteados |
| 9 | `python3 -m golden_model.scripts.run_golden data/itch_sample/01302019.NASDAQ_ITCH50.gz …` (sin anomalías) + vectores sintéticos commiteados |
| 10 | `verilator --lint-only -Wall --top-module itch_parser rtl/parser/<files>.sv` |
| 11 | `verible-verilog-lint rtl/parser/<files>.sv` |

Régimen completo: skill `verify`. Gates específicos de esta campaña: A = cocotb/
Verilator verde (make en `verification/testbenches/parser/`); B/C = lint+estilo;
D = tabla spec↔tests + cobertura por tipo (los 10 del subset + no-subset);
E = mutación HDL manual pactada sobre el alineador/decoder/FSM de framing
(flip de `seq > esperado` → `>=`, `>=` a `>`, comparador de longitud relajado,
off-by-one en el barrel shifter, omitir `tlast`) — cada uno muerto por un test;
F = espejos Gherkin (`specs/gherkin-espejos.json` → `verification/testbenches/parser`);
G = G0/G3 (datos reales fuera del repo) + **G de timing/Vivado:** NO EJECUTADO
en fase 1 (se declara NO APLICA hasta fase 3; justificación en verify-report).

**Contratos sin gate** — invariantes que pueden romperse con suite y lint en
verde:

1. **Tabla de layouts autoconsistente pero mal transcrita** entre
   `messages.py`, el RTL y `--emit-messages`. Guardarraíl: los vectores
   sintéticos de los tests son **literales hex escritos a mano desde el PDF**
   (oráculo independiente), nunca generados por el propio RTL; cocotb redecodifica
   el stream de entrada con `messages.py` (independiente del RTL).
2. **Layout del registro normalizado (Anexo A)** vs. el que consumirá el order
   book en fase 2. Guardarraíl: Anexo A fijado byte a byte en esta spec
   (cambiarlo = edit de spec) + round-trip cocotb writer↔reader↔texto.
3. **Semántica heredada por fase 2** (qué campos del subset lleva el book):
   la define esta spec (Anexo A), no la redefine fase 2.
4. **Requisito de line rate** demostrado solo con vectores sintéticos: el
   replay real (criterio 8) usa pcaps reales que SÍ contienen back-to-back real,
   y el chequero de stalls (criterio 2) aplica también al replay real.

## Loop

Stop limit: **5 iteraciones**. Cadencia: encadenar build→verify→grade mientras
quede cola; al agotar el límite con criterios en FAIL, escala al owner.

---

## Anexo A — layout del registro de mensaje normalizado (canónico)

Cada mensaje decodificado del subset emite **una o más palabras de 64-bit**
en el orden y con los campos del wire (big-endian, sin byte-swap del RTL). Un
registro es un burst `tvalid` alta con `tlast` en la última palabra.

**Cabecera de contexto — Word 0:**

| Bits | Campo | Descripción |
|---|---|---|
| 63:56 | `msg_type` | tipo ITCH ASCII (`S,R,A,F,E,C,X,D,U,P`) |
| 55:40 | `locate` | Stock Locate Code |
| 39:32 | `length` | longitud total del mensaje ITCH (bytes, del campo de framing; max 50 → cabe) |
| 31:0 | `msg_idx` | índice global del mensaje en el stream (32 bits; el día real ~268M < 2³²) |

**Word 1 — contexto temporal:**

| Bits | Campo |
|---|---|
| 63:0 | `ts_ns` — timestamp ITCH (ns desde medianoche, del campo ITCH) |

**Words 2…N — cuerpo del mensaje (campos decodificados):** los bytes del
mensaje tras la cabecera común de ITCH (11 B: type, locate, tracking, ts), es
decir exactamente los campos específicos del tipo en **orden del wire**
(big-endian). Como los tipos del subset son de longitud fija, cada campo tiene
un offset fijo dentro del cuerpo (el mismo de `golden_model/itch/messages.py`):
decodificar = validar longitud por tipo y modulariar los campos a esos offsets
fijos; no hay re-encodificación (el book de fase 2 indexa el cuerpo por offset
de su tipo). Cero bytes de relleno a la palabra de 8 B (bits sobrantes en 0).

**Número de palabras de cuerpo por tipo** (`length − 11` B → `ceil(·/8)`):

| Tipo | len | cuerpo | words cuerpo | total (2+body) |
|---|---|---|---|---|
| S | 12 | 1 | 1 | 3 |
| D | 19 | 8 | 1 | 3 |
| X | 23 | 12 | 2 | 4 |
| R | 39 | 28 | 4 | 6 |
| A | 36 | 25 | 4 | 6 |
| F | 40 | 29 | 4 | 6 |
| E | 31 | 20 | 3 | 5 |
| C | 36 | 25 | 4 | 6 |
| U | 35 | 24 | 3 | 5 |
| P | 44 | 33 | 5 | 7 |

> El orden **exacto** de campos y sus offsets es EL de `golden_model/itch/
> messages.py` (fuente única); Anexo A fija la cabecera de contexto, la
> semántica de burst y el cuerpo = bytes del wire tras los 11 B comunes.
> `--emit-messages` emite exactamente estas palabras (cabecera + body).
> `m_axis_tlast` delimita el burst; cocotb reconstruye el registro por `tlast`
> y lo compara byte a byte contra `--emit-messages`.

> **Edit explícito de spec (2026-08-12, hallazgo de diseño durante /build):**
> la primera redacción de este Anexo tenía `msg_idx_lo[22:0]` de 23 bits
> (insuficiente para un día real, ~268M mensajes) y un recuento de palabras
> por tipo desajustado al tamaño real de los mensajes. Corregido a `msg_idx`
> de 32 bits, `length` en bits 39:32 y tabla de words/cuerpo verificada. Sin
> este edit, el criterio 8 (replay real byte a byte) y el contrato de fase 2
> habrían quedado rotos por construcción.

## Anexo B — datos y entorno de la campaña

- **Replay real (criterio 8):** pcap generado del día local
  `data/itch_sample/12302019…` con `scripts/binaryfile_to_pcap.py`
  (`--msgs-per-packet` configurable); nunca se commitea el crudo.
- **Vectores congelados (criterio 8/9):** pequeños, sintéticos, en
  `verification/vectors/messages/` y `verification/vectors/` (regla G0).
- **Toolchain (instalado en esta campaña):** Verilator 5.050 (brew),
  `.venv` con cocotb 2.0.1 / numpy 2.4.6 sobre **Python 3.11** (el 3.14 del
  sistema rompe cocotb 2.0.1 — ver DESARROLLO.md).
- Cabos de fase 0 (criterio 9): día de regresión `01302019.NASDAQ_ITCH50.gz`
  (~4,8 GB gz) + vectores sintéticos commiteados.
- **Part objetivo:** UltraScale+ (part concreto en síntesis fase 3); aquí solo
  se estipula datapath 64-bit @ 156,25 MHz y compatibilidad Verilator.
