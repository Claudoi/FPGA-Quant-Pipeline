# fase2-orderbook (fase 2 del maestro)

## Goal

Construir el **order book engine en RTL** (SystemVerilog compatible Verilator)
que consume el registro normalizado del Anexo A emitido por el parser de fase 1
(AXI-Stream de mensajes decodificados) y mantiene, por símbolo, el estado del
libro: **tabla de órdenes vivas** (order_ref → símbolo/lado/precio/cantidad),
**niveles de precio agregados** y el **BBO** (best bid & offer) actualizado con
latencia determinista. Es la etapa que cierra el pipeline
`10G MAC → decap → framing → parser → order book → BBO` del documento maestro.

La corrección se verifica **bit a bit contra el golden model de fase 0**
(`golden_model/src/book.py`), que ya fue validado contra días completos de
Nasdaq (2019-12-30: 268M mensajes, 0 anomalías). El RTL replica esa semántica
exacta; cualquier desviación es un FAIL.

## Scope

**In scope:**

- `rtl/orderbook/` — módulos SystemVerilog del engine:
  - **Decodificador de registro Anexo A**: extrae los campos por tipo
    (A/F/E/C/X/D/U/S/H) desde el burst de words que emite el parser (word0
    cabecera de contexto, word1 ts, words 2..N cuerpo big-endian).
  - **Tabla de órdenes en URAM**: order_ref (32 bits útiles tras decap; el día
    real ~268M refs < 2³²) → entrada de orden (locate, lado, precio, qty
    restante). **No se implementa hash** en esta fase: se usa **indexación por
    order_ref directa en espacio URAM de 2^K entradas** (K dimensionado al
    subset, ver Constraints) — decisión de la entrevista: el hash con probing
    se separa a una iteración de optimización si el subset real lo exige.
  - **Niveles de precio**: por (locate, lado), array de niveles
    {precio → qty agregada}; el BBO es el mejor nivel bid/ask.
  - **FSM de aplicación** de los 7 tipos modificadores + S/H de estado.
  - **Salida BBO**: por símbolo, (bid_px, bid_qty, ask_px, ask_qty), evento por
    cambio (semántica `BookEvent` del golden).
  - Top `orderbook`.
- `rtl/common/` — helpers compartidos si hacen falta (FIFO de handshake, etc.).
- `verification/testbenches/orderbook/` — testbenches cocotb + Verilator:
  - Feed de registros Anexo A sintéticos (construidos con el mismo formato que
    emite el parser de fase 1) + **feed real decapado** del día local
    (replay, `data/itch_sample/12302019…` → parser → book).
  - Oráculo `golden_model/src/book.py` aplicado sobre los mismos mensajes;
    comparación **evento a evento y bit a bit** del BBO.
- Vectores congelados de BBO para el subset en `verification/vectors/bbo/`.

**Out of scope (non-goals):**

- Rehacer el parser: el book consume el Anexo A tal cual lo emite fase 1.
  (El testbench puede alimentar registros directamente o encadenar parser+book.)
- Hash table con colisiones/cuckoo (optimización futura, solo si el subset lo
  pide). En esta fase la tabla es indexación directa por order_ref.
- Top-N niveles de profundidad (depth book): solo **BBO** (criterio de esta
  fase). El libro profundo por niveles existe (estado de niveles), pero la
  salida pública es BBO.
- Multi-símbolo completo de 2000+ símbolos: se soporta **hasta N símbolos**
  del subset (20), con niveles por (locate, lado) en espacio parametrizado.
- Latencia óptima 322 MHz / timing closure Vivado: fase 3.
- CME MDP3 (stretch fase 4).
- Market hours / halt-cross semántica estricta: el golden cuenta `cross_events`
  y sigue; el RTL replica el **no-abort** del golden por defecto
  (`strict_cross=False`), ver §Semántica.

**Radio medido (2026-08-13):** `rtl/orderbook/` vacío (verificado con
`find rtl/ -type f`). `rtl/parser/itch_parser.sv` existe y se reutiliza como
generador de Anexo A. `verification/testbenches/orderbook/` no existe (nueva
área). No se renombra ni mueve nada.

## Constraints

- **Familia/part objetivo:** AMD/Xilinx UltraScale+ (part concreto en síntesis
  fase 3). Datapath 64-bit @ 156,25 MHz (reloj del parser).
- **URAM:** lectura registrada (1-2 ciclos de latencia). El pipeline se diseña
  alrededor de esa latencia: el BBO de un mensaje refleja su efecto en el
  siguiente beat válido de salida, sin «arreglar» el signo con lógica larga.
- **Tabla de órdenes:** 2^K entradas, K tal que `2^K ≥ peak_live_orders` del
  subset (pico medido 259.443 en 2019-12-30) — se parametriza `K` con default
  adecuado a simulación y se documenta el mapeo a URAM para fase 3.
- **Dimensionado de niveles:** array por (locate, lado) de `P` niveles de
  precio; el golden asume dict sin tope, el RTL lo acota a `P` y señala
  overflow de niveles (nunca silencio).
- **Endianness:** los campos del cuerpo son big-endian del wire (Anexo A, sin
  byte-swap); el decodificador extrae por offset exacto de
  `golden_model/itch/messages.py` (fuente única, regla fase 0/1).
- **Determinismo:** mismo stream → misma secuencia de BBO, bit a bit igual al
  golden; sin pérdida ni doble cuenta.

## Semántica (contrato heredado del golden — NO redefine, replica)

`golden_model/src/book.py` (fase 0, validado contra día real) define:

- `A`/`F` → add (ref duplicada = error invariante; qty ≤ 0 = error).
- `E`/`C` → reduce cantidad; si llega a 0, elimina la orden. `C` reduce igual
  que `E` (el exec_price no altera el precio de la orden).
- `X` → reduce (cancel). `D` → delete (ref desconocida = anomalía, no aborta).
- `U` → **replace ATÓMICO**: delete+add de un solo estado resultante (nunca
  visible un BBO intermedio con la orden ausente).
- `P` → no toca el libro.
- `S` (evento) y `H` (trading state) → estado de mercado/halt; `S` en `Q` abre
  y en `M` cierra market hours; el cruzado en trading continuo se CUENTA
  (`cross_events`), no aborta (por defecto).
- Operación sobre ref desconocida → anomalía contada, se continúa.
- BBO lado vacío = (precio 0, qty 0).

El RTL debe reproducir estas reglas EXACTAMENTE. La tabla de invariantes
(ref duplicada, qty no positiva, nivel inconsistente, overflow de niveles) son
escenarios `SEC-` de primera clase con `error` señalizado (o `cross_events`
contado), nunca comportamiento silencioso.

## Superficie y amenazas

**Entradas (puertos del top `orderbook`):** el AXI-Stream de fase 1 — mismo
conjunto `s_axis_tdata/tvalid/tready/tlast` (64-bit), más `clk`/`rst_n`. El
registro es el Anexo A: word0 `{msg_type, locate, length, msg_idx}`, word1 ts,
words 2..N cuerpo.

**Salidas nuevas:**

| Señal | Ancho | Descripción |
|---|---|---|
| `bbo_locate` | 16 | locate del símbolo del evento BBO |
| `bbo_tdata` | 128 | `{bid_px[31:0], bid_qty[31:0], ask_px[31:0], ask_qty[31:0]}` (precios ITCH de 32 bits, cantidades 32 bits) |
| `bbo_tvalid` | 1 | hay un evento BBO de salida (por mensaje modificador) |
| `bbo_tready` | 1 | backpressure del consumidor de BBO |
| `bbo_changed` | 1 | cambió el BBO respecto al anterior (semántica `changed` del golden) |
| `cross_events` | 32 | contador de libros cruzados en trading continuo |
| `anomaly_count` | 32 | contador de refs desconocidas / operaciones inválidas no abortantes |
| `error` | 1 | invariante violada (ref duplicada, qty ≤ 0, overflow de niveles) — fail con señal |

**Casos de abuso del dominio** (cada uno con su escenario `SEC-` en Gherkin):

- **Hazards RAW:** dos mensajes consecutivos sobre la misma orden/nivel
  (add→execute, add→cancel, replace→execute) → el segundo ve el estado del
  primero (forwarding o stall selectivo). — SEC-HZ-01/02.
- **Replace atómico:** nunca un BBO intermedio con la orden ausente; el BBO del
  `U` refleja el estado final. — SEC-U-01.
- **Doble cuenta:** execute/cancel/delete no descuentan dos veces la cantidad
  de la orden ni del nivel. — SEC-DC-01.
- **Overflow:** qty de nivel/orden, contador de refs, y niveles > `P` se
  señalizan, nunca envuelven silenciosamente. — SEC-OV-01.
- **Ref desconocida** en E/X/D/U → anomalía contada, no aborta, el stream
  continúa. — SEC-AN-01.
- **Bid ≥ ask en trading continuo** → `cross_events` cuenta, no aborta. — SEC-CR-01.
- **Símbolo vacío** (sin órdenes) → BBO (0,0,0,0). — SEC-EM-01.

**Qué se arriesga del maestro:** la **latencia determinista** y la **corrección
estricta del estado** (doble cuenta/hazard = BBO incorrecto = el peor fallo de
un pipeline de trading). El libro es la etapa donde un error de estado no se
detecta por el parser: la verificación bit a bit contra el golden es la única
red.

## Reuso

- `golden_model/src/book.py` — **oráculo de referencia** (fase 0). El RTL
  replica su semántica; el testbench lo aplica sobre el mismo feed. Nada de
  «el RTL es el golden»: son dos implementaciones comparadas bit a bit.
- `golden_model/itch/messages.py` — **fuente única de layouts** de campo
  (offsets del cuerpo por tipo). El decodificador RTL usa estos offsets; el
  testbench re-parsea con `message_oracle` (independiente del RTL).
- `rtl/parser/itch_parser.sv` — generador real de Anexo A (encadenado en el
  testbench para el replay y para los vectores sintéticos).
- `golden_model/src/message_oracle.py` — oráculo de mensajes de fase 1.
- `requirements-dev.txt`, cocotb/Verilator — entorno ya instalado.
- **Código nuevo que duplique** la semántica de `book.py` con otro literal
  (precios/cantidades a mano) = FAIL de la lente de simplicidad de `/grade`.

## Criterios de aceptación (Definition of Done)

1. [ ] El book consume el Anexo A y mantiene la tabla de órdenes + niveles;
     para una secuencia sintética de A/F/E/C/X/D/U, el BBO por símbolo es
     **bit a bit idéntico al golden `book.py`** (mismo feed, mismo orden,
     evento a evento, incluido `changed`).
     — Gherkin: `orderbook.feature` §BBO-01, §BBO-02
2. [ ] **Replace `U` atómico**: el BBO emitido para un `U` es el del estado
     final (delete+add), nunca un intermedio con la orden ausente.
     — Gherkin: `orderbook.feature` §SEC-U-01
3. [ ] **Hazards RAW**: dos mensajes consecutivos sobre la misma orden/nivel
     (add→execute, add→cancel, replace→execute) producen el BBO correcto del
     segundo (forwarding o stall selectivo), sin resultado incorrecto.
     — Gherkin: `orderbook.feature` §SEC-HZ-01, §SEC-HZ-02
4. [ ] **Doble cuenta**: execute/cancel/delete no descuentan dos veces; el
     nivel y la orden quedan consistentes con el golden.
     — Gherkin: `orderbook.feature` §SEC-DC-01
5. [ ] **Overflow**: qty de orden/nivel, número de niveles > `P` y contadores
     se señalizan con `error`, nunca envuelven en silencio.
     — Gherkin: `orderbook.feature` §SEC-OV-01
6. [ ] **Anomalías y cruzados**: ref desconocida cuenta en `anomaly_count`
     (no aborta); bid ≥ ask en trading continuo cuenta en `cross_events`
     (no aborta) — replica exacta del golden `strict_cross=False`.
     — Gherkin: `orderbook.feature` §SEC-AN-01, §SEC-CR-01
7. [ ] **Multi-símbolo**: hasta N símbolos del subset con estado independiente
     (niveles por locate+lado); los mensajes de un símbolo no contaminan otro.
     — Gherkin: `orderbook.feature` §MULTI-01
8. [ ] **Replay real (hybrid oracle)**: sobre el día local
     `data/itch_sample/12302019…` (parser → book), la secuencia de BBO del
     subset es **bit a bit idéntica** al golden `book.py` sobre el mismo feed;
     además vectores congelados de BBO se commitean en
     `verification/vectors/bbo/` y se reproducen.
     — Gherkin: `orderbook.feature` §REPLAY-01, §REPLAY-02
9. [ ] Cocotb + Verilator compilan el top con `--Wall` sin warnings reales
     silenciados.
     — Gate B/C de verify.
10. [ ] Lint y estilo en verde sobre `rtl/orderbook/` (`verilator --lint-only
     -Wall`; verible si se instala).
     — Gate B/C de verify.

## Verificación

| Criterio | Cómo se prueba |
|---|---|
| 1 | cocotb: corpus sintético multi-tipo → feed de Anexo A → comparar BBO contra `book.py` (evento a evento, bit a bit) |
| 2 | cocotb: `U` con BBO previo no vacío → el evento emitido es el final (no intermedio); mutante de no-atomicidad lo mata |
| 3 | cocotb: pares adyacentes add→execute, add→cancel, replace→execute sobre la misma ref; comparar contra golden |
| 4 | cocotb: ejecutar/cancel/delete y verificar orden+nivel con `check_deep()` del golden (o conteo de qty) |
| 5 | cocotb: inyectar overflow de qty/niveles → `error` alto, sin wrap |
| 6 | cocotb: ref desconocida → `anomaly_count` incrementa; cross → `cross_events` incrementa; flujo continúa |
| 7 | cocotb: mensajes intercalados de 2+ símbolos; BBO independiente por locate |
| 8 | cocotb: replay del día local encadenado parser→book; comparar vs golden; vectores congelados commiteados |
| 9/10 | `verilator --lint-only -Wall --top-module orderbook` + `verible-verilog-lint` (si instalado) |

Régimen completo: skill `verify`. Gates: A = cocotb en
`verification/testbenches/orderbook/`; B/C = lint+estilo; D = cobertura
funcional (estados de la FSM de aplicación + tabla spec↔tests por criterio);
E = mutación HDL sobre `rtl/orderbook/` (flips de: `>`/`>=` en best bid/ask,
off-by-one de nivel, `U` no atómico, doble descuento, comparador de ref) —
cada uno muerto por un test; F = espejos Gherkin
(`specs/gherkin-espejos.json` → `verification/testbenches/orderbook`);
G = G0/G2/G3 (datos reales fuera del repo; libro sin ventana de inconsistencia;
comparación bit a bit). G timing/Vivado: NO EJECUTADO hasta fase 3 (justificado
en verify-report).

**Contratos sin gate** — invariantes que pueden romperse con suite y lint en
verde:

1. **Semántica heredada mal transcrita** entre `book.py` y el RTL (p. ej. `C`
   que altera el precio, `U` que no es atómico, ejecutado sobre nivel vacío).
   Guardarraíl: los vectores del test son **literales** construidos desde
   `messages.py` (independientes del RTL), y el oráculo es `book.py` (nunca el
   propio RTL).
2. **Layout del Anexo A mal decodificado** (offsets del cuerpo corridos).
   Guardarraíl: el decodificador usa offsets de `messages.py`; el testbench
   re-parsea el mismo feed con `message_oracle` y compara BBO, no campos sueltos.
3. **Overflow no señalizado** (wrap silencioso de qty/niveles).
   Guardarraíl: escenarios `SEC-OV-01` con mutante de ancho reducido.
4. **El book «pierde» órdenes** por dimensionado de la tabla de órdenes
   (2^K < peak del subset). Guardarraíl: `check_deep()` del golden tras el
   replay real; si hay pérdida, `error`/anomalía — nunca resultado silencioso.

## Loop

Stop limit: **5 iteraciones**. Cadencia: encadenar build→verify→grade mientras
quede cola. Al agotar el límite con criterios en FAIL, escala al owner.
