# verify-report — fase3-optimizacion

> Régimen de gates de Atenea re-mapeado al flujo HDL. El owner no lee HDL/Python:
> esta evidencia (outputs reales) es lo que `/grade` re-ejecutará.

## Iteración 1 — variante DW=32 parser + book + cadena (criterios 1-3), REG-01

### Meta del atacante/diseño

La parametrización de 64 bits fijos a DW ∈ {32, 64} no debe cambiar NI un bit
del contrato de 64 bits (fases 1/2) y debe producir el Anexo A de 32 bits del
Anexo de la spec (w0={type,locate,len}, w1=idx, w2=ts[31:0], w3={ts[47:32],16'b0},
w4..=cuerpo) bit a bit contra el oráculo, y la cadena parser→book debe cerrar
BBO bit a bit con el golden sobre el feed real.

### Rojo con evidencia (TDD)

| Test | Rojo | Causa raíz |
|---|---|---|
| P32-01 (parser DW=32) | `%Warning-WIDTHTRUNC` + `%Error: Exiting due to 5 warning(s)` en itch_parser.sv (RHS de 64 bits a reg de 32) | cbody/body_w/W0-TS fijos a 64 bits |
| B32-01 (book DW=32) | `%Warning-SELRANGE` + `%Error: Exiting due to 7 warning(s)` — `63:56 outside 31:0` | campos del w0 fijos a 64 bits |
| P32-01 (tras compilar) | `got(0) exp(95)` — sin emisión | cola: `qn += 8` por palabra (fijo 64) → nunca se junta el header de 20 B |
| P32-01 (tras cola) | words de cuerpo desalineadas (stride de 8 B por palabra) | `cbody(..., 11 + 8*bi)` — stride fijo; a DW=32 debe ser `11 + BYTES*bi` |
| CHAIN-01 | `got(146343) exp(30729)`; primer desajuste evento 67 | test mal dirigido: alimentaba el feed completo (150K registros, todos los símbolos) — overflow NSYM es el hallazgo F1 del grade, hardening de la iteración 4; el contrato es el stream del subset |

### Verde (evidencia)

| Suíte | Resultado |
|---|---|
| phase3/parser32 (P32-01, P32-02, INV-P32-01, P32-03 replay pcap real) | **4/4 PASS** (P32-03: 150.000 registros decapados bit a bit) |
| phase3/book32 (B32-01, B32-02 replay real, INV-B32-01/02/03) | **5/5 PASS** (B32-02: 31.400 msgs → 30.729 eventos bit a bit, cross=0) |
| phase3/chain32 (CHAIN-01 real, INV-CHAIN-01 sintético) | **2/2 PASS** (31.400 msgs → 30.729 eventos bit a bit, gaps=0) |
| fase1 regresión DW=64 (REG-01) | **19/19 PASS** |
| fase2 regresión DW=64 (REG-01) | **14/14 PASS** (incl. REPLAY-01) |

### Cambios

- `rtl/parser/itch_parser.sv`: localparams BYTES/L2B; cola con `BYTES` por beat
  (qn/can_aug/can_da, shifts con `+ drain_int` corregido — signo); `cbody` a DW;
  `body_w = ceil((len-11)/BYTES)`; ST_W0/ST_TS emiten el layout de 32 bits con
  contador `hw` (w0, w1=idx, w2-3=ts); casts `DW'()` y `8'()/32'()` para el
  trinquete de anchos en ambas variantes.
- `rtl/orderbook/orderbook.sv`: `pbody` generalizado (índice `b>>L2B`, byte
  `DW-1-8*(b&(BYTES-1))`); campos del w0 por `[DW-1 -: 8]` etc.; `nbody_w`
  a `ceil((len-11)/BYTES)`; `hrem` consume 3 words de cabecera a DW=32 (captura
  `m_idx` de w1); `bi` a 4 bits y `body_acc[0:15]` (cuerpo máximo a DW=32).
- `rtl/itch_chain.sv` (nuevo): top de integración parser→book sin FIFO, DW
  parametrizado, `error = p_error | b_error`.
- `verification/testbenches/phase3/`: Makefile (EXTRA_ARGS `-GDW=32`),
  `test_parser32.py`, `test_orderbook32.py`, `test_chain32.py` — espejos
  P32-01/02, B32-01/02, CHAIN-01 + adversariales; reuso de helpers de fases 1/2.

### Pendiente para iteraciones siguientes

- Criterios 4-11 (hash+probing, top-N, hardening F1/F2, latencia, URAM/synth).
- F1 (NSYM overflow) y F2 (bbo_tready) son SEC-NSYM-01/SEC-BP-01 (criterios 8-9).

## Iteración 2 — tabla de órdenes hashada + linear probing (criterios 4-6)

### Meta del atacante/diseño

La tabla `o_*[2^K]` de indexación directa (fase 2) se reemplaza por una tabla
hashada de `NSLOT = 2^SLOT = 65.536` slots con `hash(ref) = ref[SLOT-1:0]` y
linear probing acotado a `PROBE = 8` pasos, reproduciendo EXACTO el contrato de
la fase 2 (mismos eventos, anomalías y refs) y añadiendo la semántica del
criterio 5: ref no encontrada tras agotar probes = anomalía (sin abortar);
tabla llena = `error` señalizado, nunca wrap ni overwrite silencioso.

Decisión de diseño: tabla en **registros con lookup combinacional de hasta
PROBE slots/ciclo** (8 comparadores en paralelo) — el mapeo a URAM y la lectura
registrada se difieren a la iteración 5 (criterio 9); los tiempos ST_APPLY /
ST_UADD no cambian, así que la regresión de fase 2 pasa sin tocar sus tests.
Los borrados dejan `valid=0` y el lookup continúa a través de esos slots
(semántica de tombstones sin bit muerto: el bit `tomb` era lógica no leída y se
eliminó durante el build — la entrada coincide con la spec `{valid, ref, side,
price, qty}`); el insert reutiliza el primer slot `valid=0` del camino.

**Radio real del feed (31.400 msgs del subset)**: 12.742 adds, **13.456 refs
distintas**, pico 272 vivas, carga pico 0,415 % de los 65.536 slots,
max_ref = 372.297 (19 bits), 12.662 hashes-16 distintos → sin cadenas largas
ni riesgo de llenado (incluso acumulando borrados, 13.456/65.536 = 20,5 %);
con carga 20 % la probabilidad de agotar 8 probes es ~2,6e-6.

### Rojo con evidencia (TDD)

| Test | Rojo | Causa raíz |
|---|---|---|
| SEC-HASH-02 (tabla llena) | `SEC-HASH-02: la tabla llena debe señalar error` (`assert 0 > 0`) | con indexación directa de 2^K nunca hay llenado: el 9º add del hash cabe siempre |
| SEC-HASH-02 (tras el hash) | `got` ≠ `expected[:8] + expected[9:]` | el test asumía igualdad bit a bit tras el fallo; el golden no modela la tabla y su estado diverge tras el add fallido → el test se reformuló cerrado (adds previos bit a bit + ausencia del evento del add fallido + BBO posterior verificado de forma cerrada) |

(Nota: con K=19 y PROBE=8, el probe agotado es inalcanzable por construcción
— 2^19/2^16 = 8 refs por hash; SEC-HASH-01/02 se ejecutan con `-GK=20` vía el
target `sim-hash` del Makefile para hacer real el 9º ref del hash.)

### Verde (evidencia)

| Suíte | Resultado |
|---|---|
| phase3/hash32 (SEC-HASH-01/02/02b/02c/03/04, K=20) | **6/6 PASS** |
| phase3/book32 (B32-01/02, INV-B32-01/02/03, K=19) | **5/5 PASS** (B32-02: 31.400 msgs → 30.729 eventos bit a bit, cross=0) |
| phase3/parser32 | **4/4 PASS** |
| phase3/chain32 (CHAIN-01 real) | **2/2 PASS** (bit a bit, gaps=0) |
| fase1 regresión DW=64 | **19/19 PASS** |
| fase2 regresión DW=64 (incl. REPLAY-01) | **14/14 PASS** |

### Cambios

- `rtl/orderbook/orderbook.sv`: parámetros `SLOT=16`, `PROBE=8`; arrays
  `o_valid/o_ref/o_side/o_price/o_qty` de `NSLOT=2**SLOT` (entrada exacta de la
  spec, sin bit `tomb` — lógica muerta eliminada); funciones `lookup_ref`
  (proba hasta PROBE comparando `o_ref`, `found` por salida) y `first_empty`
  (primer slot `valid=0`, `full` si el camino está lleno); `apply_one`
  reescrito (A/F: dup-ref o qty 0 o tabla llena → error; E/C/X/D/U: lookup →
  anomalía si no existe; U con `newref` duplicada → error); `reduce_order` por
  slot; tarea `apply_uadd_half` para ST_UADD (mitad add: `first_empty` → si
  llena, error y BBO del replace cancelado vía `emit_ok`); reset de los 5
  arrays. Tras el refactor el lint queda limpio (BLKSEQ movido a tarea,
  UNUSEDSIGNAL de bits altos resuelto pasando el hash ya truncado a
  `first_empty`).
- `verification/testbenches/phase3/test_hash32.py` (nuevo): 6 tests espejo
  SEC-HASH-01/02/03 + bordes; driver con muestreo del pulso `error`.
- `verification/testbenches/phase3/Makefile`: target `sim-hash`
  (`TOPLEVEL=orderbook MODULE=test_hash32 EXTRA_ARGS="-GDW=32 -GK=20"`).
- `scripts/verify/mutate_orderbook.py`: runner del gate E con doble suite
  (fase 2 a DW=64 + hash a K=20) y 7 mutantes nuevos de la tabla hashada
  (ref sin comparar, bounds de probing off-by-one en lookup e insert, guard de
  tabla llena en add y en mitad-add del replace, dup-ref sin error, insert sin
  valid).

### Mutación (gate E)

15/15 mutantes muertos (8 de fase 2 actualizados al RTL hashado + 7 nuevos de
hash). Evidencia `scripts/verify/mutate_orderbook.py` (runner), re-ejecutable.

### Pendiente para iteraciones siguientes

- Criterios 7-11 (top-N, hardening F1/F2, latencia, URAM/synth).

## Iteración 3 — top-N público ND=5 (criterio 6)

### Meta del atacante/diseño

Nuevos puertos del book (y de la cadena): `depth_tdata` (2*ND*64 = 640 bits),
`depth_tvalid`, `depth_tready`. El depth acompaña al BBO como **par atómico**
(mismo pulso registrado): `depth_tdata` = ND niveles por lado del símbolo del
evento, best-first, `{bid[ND-1..0], ask[ND-1..0]}` MSB→LSB con el mejor a la
izquierda (depth[639:576] = mejor bid), cada nivel `{px[31:0], qty[31:0]}`,
vacíos a 0. Los niveles se leen de las listas ordenadas internas (slot 0 =
mejor, invariante de la burbuja de fase 2), NUNCA se recalculan: el oráculo de
los tests es `book.py` (`run_book_depth`, snapshot de `_levels` por evento).

El handshake `depth_tready` entra en el guard de ST_APPLY junto al de BBO
(par aceptado solo con ambos tready; la retención completa bajo backpressure
es SEC-BP-01, iteración 4).

### Rojo con evidencia (TDD)

| Test | Rojo | Causa raíz |
|---|---|---|
| DP-01 (top-N) | `AttributeError: orderbook contains no child object named depth_tready` | el RTL aún no tiene puertos de depth |
| DP-02 (replay real) | `DP-02: depth diverge en evento 5 (locate 6960): got=…00149bc8…` — un slot del bid con `px=0x149bc8, qty=0` | **BUG real del feed**: `level_add` ponía `qty=0` al vaciar un nivel pero dejaba el **precio stale** en el slot; el BBO solo lee el primer slot con qty≠0 (nunca se notó en fases 1-2), el top-N empaqueta el slot entero y filtra el precio muerto. Fix en la raíz: nivel vacío se limpia completo (`lpr[found]=0`), invariante «el nivel vacío no existe» del golden |

### Verde (evidencia)

| Suíte | Resultado |
|---|---|
| phase3/depth32 (DP-01 sintético, SEC-DP-01 vacíos a 0, DP-02 replay real) | **3/3 PASS** (DP-02: 31.400 msgs → **30.729 depths bit a bit** contra el golden, todos los símbolos) |
| phase3/book32 + hash32 + chain32 + parser32 | **5/5 + 6/6 + 2/2 + 4/4 PASS** (regresión tras el fix de nivel vacío) |
| fase1 regresión DW=64 | **19/19 PASS** |
| fase2 regresión DW=64 (incl. REPLAY-01) | **14/14 PASS** |

### Cambios

- `rtl/orderbook/orderbook.sv`: parámetro `ND=5`; puertos `depth_tdata/
  depth_tvalid/depth_tready`; `emit_bbo` empaqueta el depth (bucle de ND
  niveles por lado con `dacc = {dacc[…], px, qty}` MSB→LSB, slot 0 = mejor) y
  valida el par; guard de ST_APPLY extendido a ambos tready; reset de los
  puertos; **fix de nivel vacío** (`lqt[found]=0` + `lpr[found]=0`).
- `rtl/itch_chain.sv`: puertos de depth cableados del book al top.
- `verification/testbenches/phase3/test_depth32.py` (nuevo): driver que
  muestrea el par y **exige depth_tvalid=1 en cada handshake de BBO**
  (mata al mutante DP-NOVALID); DP-01/DP-02/SEC-DP-01.
- `verification/testbenches/orderbook/test_orderbook.py`: oráculos
  `run_book_depth` (snapshot de niveles por evento) y `pack_depth` (bus de
  640 bits).
- `verification/testbenches/phase3/Makefile`: target `sim-depth`.
- `scripts/verify/mutate_orderbook.py`: tercera suite (sim-depth) y 4 mutantes
  de depth (DP-BADORDER, DP-ASKSWAP, DP-NOVALID, DP-EMPTYSTALE).

### Mutación (gate E)

19/19 mutantes muertos (15 previos + 4 de depth). Evidencia:
`scripts/verify/mutate_orderbook.py` (runner, triple suite), re-ejecutable.

### Pendiente para iteraciones siguientes

- Criterios 7-11 (hardening F1/F2, latencia, URAM/synth).

## Tabla de gates

| Gate | Comando / evidencia | Resultado |
|---|---|---|
| **A. Simulación** | 5 suites phase3 (20/20) + fase1 19/19 + fase2 14/14 PASS | ✔ |
| **B. Compilación/lint sintaxis** | Verilator 5.050 `--lint-only -Wall` limpio en DW∈{32,64} × K∈{19,20} y chain | ✔ |
| **C. Estilo** | `verible-verilog-lint` (si instalado) | — |
| **D. Cobertura + mapeo** | Tabla spec↔tests (pendiente al cierre) | — |
| **E. Mutación HDL** | 19/19 mutantes muertos (triple suite fase2+hash+depth) | ✔ |
| **F. Completitud Gherkin** | espejos del `.feature` ↔ tests | — |
| **G. Rigor + timing** | G0/G2/G3 ✔ (vectores/feed no commiteados); G timing: run externo del owner (criterio 10) | — |

## Veredicto

Iteración 1 (criterios 1-3 + REG-01), iteración 2 (criterios 4-5) e
iteración 3 (criterio 6, top-N): **verde con evidencia**; pendiente de
`/verify` formal y criterios 7-11.