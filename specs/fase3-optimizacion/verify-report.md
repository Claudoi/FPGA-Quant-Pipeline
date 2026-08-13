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

## Iteración 4 — hardening (criterios 7-8) y latencia (criterio 8)

### Meta del atacante/diseño

Cierra los dos hallazgos de la lente 9 del grade de fase 2 y mide la latencia:

- **SEC-NSYM-01 (F1)**: un locate fuera del subset con NSYM=20 registrados
  señaliza `error` (pulso) y el mensaje se descarta **sin tocar el libro**;
  nunca un índice OOB en `lv_*`/`loc_map`. El guard se implementa en ST_W0
  (registro `bad_sym` + pulso de error) y se consume en ST_APPLY (el mensaje
  salta apply_one y vuelve a ST_W0).
- **SEC-BP-01 (F2)**: el par BBO/depth se **retiene** en AXI: `tvalid`
  permanece en 1 mientras `tready` no lo acepte, y el guard de ST_APPLY frena
  el pipeline mientras el par penda (evento entregado exactamente una vez).
- **SEC-LAT-01 (criterio 8)**: latencia wire→BBO por tipo en la cadena DW=32:
  desde el handshake en `s_axis` de la word que cubre el primer byte del
  mensaje hasta el handshake de su evento BBO. Histograma determinista
  (re-ejecución idéntica) + JSON commiteado en `verification/vectors/latency/`
  + conversión a ns en `docs/writeup/latencia.md` (1 ciclo = 3,103 ns a
  322,265625 MHz).

### Rojo con evidencia (TDD)

| Test | Rojo | Causa raíz |
|---|---|---|
| SEC-NSYM-01 | `AssertionError: el símbolo 21 no señalizó error` | el RTL no tenía guard: el locate desconocido con loc_cnt=NSYM entraba con `m_loc_idx=31` (OOB en `lv_*`) |
| SEC-BP-01 | `AssertionError: got(5) exp(7) — evento perdido` | `tvalid` se limpiaba incondicionalmente: un emit durante `tready=0` se perdía (2 de 7 eventos) |
| regresión fase 3 | `sim-hash: 6/6 -> 5/6` y `fase2: 14/14 -> 3/14` | gotcha del entorno: drivers antiguos sin `depth_tready` (X) + retención nueva → `depth_tvalid` en X → guard de ST_APPLY bloqueado → timeout. Fix: los drivers conducen ambos `tready` (el consumidor AXI debe) |

### Verde (evidencia)

| Suíte | Resultado |
|---|---|
| phase3/hard32 (SEC-NSYM-01, SEC-BP-01 con ventanas de tready=0) | **2/2 PASS** |
| phase3/lat32 (SEC-LAT-01: 2 re-ejecuciones idénticas) | **1/1 PASS** — 31.400 msgs → 30.729 eventos; p99 ≈ 77 ciclos ≈ 239 ns; media 69,3 ciclos ≈ 215 ns |
| phase3 regresión (book32 5/5, hash 6/6, depth 3/3, parser32 4/4, chain32 2/2) | **20/20 PASS** |
| fase1 regresión | **19/19 PASS** |
| fase2 regresión (incl. REPLAY-01) | **14/14 PASS** |

### Cambios

- `rtl/orderbook/orderbook.sv`: reg `bad_sym` (reset + clear en ST_W0 + set en
  el guard del símbolo 21); ST_APPLY con rama `bad_sym` (descarta sin
  apply_one); **retención AXI** del par (`tvalid <= tvalid && !tready` para
  bbo y depth).
- `verification/testbenches/phase3/test_hard32.py` (nuevo): driver con
  backpressure opcional (ventanas de 5 ciclos de tready=0 cada 17) y muestreo
  del pulso `error`; SEC-NSYM-01 (forma cerrada: golden sobre el subset
  filtrado) y SEC-BP-01 (bit a bit + exactamente una vez).
- `verification/testbenches/phase3/test_lat32.py` (nuevo): driver con tracking
  de ciclos de handshake; mapeo evento→mensaje vía índices emisores del golden;
  histograma por tipo; doble ejecución + comparación; persistencia del JSON.
- `verification/testbenches/phase3/Makefile`: targets `sim-hard` y `sim-lat`.
- `verification/testbenches/phase3/test_orderbook32.py`, `test_hash32.py` y
  `verification/testbenches/orderbook/test_orderbook.py`: los drivers conducen
  `depth_tready` (consumidor AXI completo).
- `verification/vectors/latency/latency_dw32.json` (nuevo, evidencia derivada
  sin datos crudos) y `docs/writeup/latencia.md` (conversión a ns).
- `scripts/verify/mutate_orderbook.py`: cuarta suite (sim-hard) y 2 mutantes
  (NSYM-GUARD, BP-NORET).

### Mutación (gate E)

21/21 mutantes muertos (19 previos + NSYM-GUARD + BP-NORET). Evidencia:
`scripts/verify/mutate_orderbook.py` (runner, cuádruple suite), re-ejecutable.

### Pendiente para iteraciones siguientes

- Criterios 9-11 (URAM/registrada, sin rutas O(P·P), síntesis).

## Iteración 5 — pipeline URAM y artefactos de síntesis (criterios 9-11)

### Meta del atacante/diseño

- **Criterio 9 (URAM)**: documentar el mapeo de la tabla de órdenes a URAM
  (65.536×86 bits ≈ 20 URAM del VU9P), el patrón de lectura registrada
  (probe serializado 1 slot/ciclo con prefetch durante ST_BODY) y auditar que
  no existe ninguna ruta O(P·P) en el cálculo del mejor precio.
- **Criterio 10 (síntesis)**: constraints 322,265625 MHz (period 3,103 ns) +
  script tcl synth/impl (part `xcvu9p-flga2104-2L-e`, top `itch_chain`,
  generic DW=32) commiteados en `synth/`; el run de Vivado es externo (owner).
- **Criterio 11 (lint)**: cubierto por el gate B — `verilator --lint-only
  -Wall` limpio en las 5 variantes (orderbook DW32/K19, DW32/K20, DW64/K19,
  chain DW32, chain DW64), sin warnings reales silenciados.

### Evidencia

| Entregable | Resultado |
|---|---|
| `docs/writeup/uram.md` | mapeo URAM + patrón registrado + auditoría de complejidad (sin O(P·P): emit O(P), level_add O(P) de una pasada, lookup O(PROBE), top-N O(ND)) |
| `synth/constraints/fase3_322mhz.xdc` | reloj 3,103 ns + I/O delays sobre puertos reales del top (verificados contra `itch_chain.sv`) |
| `synth/fase3_synth.tcl` | synth→opt→place→route + informes WNS/TNS/utilización → `synth/reports/` |
| `synth/reports/README.md` | qué pega el owner tras el run externo |
| Lint (criterio 11) | 5/5 variantes `--lint-only -Wall` sin errores |

### Pendiente del owner (externo)

- Correr `fase3_synth.tcl` en Vivado y pegar `timing_impl.txt` (WNS/TNS,
  criterio: **WNS ≥ 0**) y `util_impl.txt` (LUT/FF/BRAM/**URAM**) en
  `synth/reports/`. La inferencia URAM del synth confirma el criterio 9
  (guardarraíl del contrato sin gate nº 4).

## Iteración 6 — revisión adversarial G5 y refactor O(P) de level_add

### Meta del atacante/diseño

Revisión adversarial independiente (G5) del libro al cerrar la iteración 5:
0 CRITICO, **2 MAYOR** + 1 hallazgo propio de complejidad:

1. **U no atómico con tabla llena (MAYOR)**: el delete se aplicaba en ST_APPLY
   y la capacidad del newref solo se comprobaba en ST_UADD; con el camino
   lleno, la mitad add se cancelaba (emit_ok=0) y la orden original se perdía
   silenciosamente (libro divergente, sin señal alguna).
2. **Wrap fantasma en `level_add` (MAYOR)**: un reduce (delta<0) sobre un
   precio ausente (orden en tabla sin nivel, cascada del overflow de P=32)
   escribía `QW'(delta)` envuelto en el slot libre -> nivel fantasma ~4,29e9
   que salía como mejor bid. Reproducible: 33 adds (el 33º desborda y entra
   en tabla sin nivel) + D que libera slot + D sobre el 33º.
3. **Burbuja O(P²) en `level_add`** (hallazgo propio): el reordenamiento tras
   cada operación era una burbuja anidada P×P -> contradecía el criterio 9
   y el propio `docs/writeup/uram.md` (que afirmaba O(P), falso).

### Rojo con evidencia (TDD)

`test_inv_u01_tabla_llena_no_borra_la_original` e
`test_inv_ov01_phantom_no_envuelve_cantidad` (sim-hash K=20):

```
INV-U-01: errores==0 exp>0 (el U con el path del newref lleno no señalizaba)
INV-OV-01: errores=1 exp>=2 (el reduce sobre nivel ausente no señalizaba)
** TESTS=8 PASS=6 FAIL=2 **
```

(Escenario U-01 rediseñado una vez: con un solo grupo de hash el delete
liberaba un slot del propio path y el U cabía; se usan dos grupos disjuntos
— A: hash 5 → slots 5..12, B: hash 100 → slots 100..107 — para que el path
del newref esté lleno con refs ajenas y el delete libere un slot ajeno al
path. El primer rojo de la iteración 4 (`SEC-HASH-02b: sin errores, vistos 2`)
era una aserción residual de la versión antigua del INV-OV-01, ya eliminada.)

### Verde (evidencia)

```
** TESTS=8 PASS=8 FAIL=0 **   (sim-hash)
** TESTS=5 PASS=5 FAIL=0 **   (sim, orderbook32)
** TESTS=3 PASS=3 FAIL=0 **   (sim-depth)
** TESTS=2 PASS=2 FAIL=0 **   (sim-hard)
** TESTS=1 PASS=1 FAIL=0 **   (sim-lat)
** TESTS=4 PASS=4 FAIL=0 **   (sim, parser32)
** TESTS=2 PASS=2 FAIL=0 **   (sim, chain32)
** TESTS=14 PASS=14 FAIL=0 ** (fase 2)
** TESTS=19 PASS=19 FAIL=0 ** (fase 1)
```

### Cambios

- **U atómico**: en ST_APPLY el caso U pre-verifica la capacidad
  (`first_empty(newref[SLOT-1:0], full)`); si `full` → `error`, SIN delete y
  SIN emit; si cabe → delete + captura `u_newref/u_side/u_price/u_shares` +
  `u_nidx` (nueva reg de SLOT bits, reseteada), emit con out_uadd. La mitad
  add (`apply_uadd_half`, ST_UADD) usa el `u_nidx` ya verificado: ni recompute
  ni rama full ni `emit_ok` (reg eliminada).
- **Guard anti-fantasma**: en `level_add`, `found == -1 && delta < 0` →
  `error` (el reduce sobre nivel ausente jamás escribe cantidad envuelta).
- **Refactor O(P)**: el reordenamiento ya no es una burbuja P×P: en borrados
  compacta a la izquierda en una pasada (el hueco queda en la cola, `P-1`
  limpio con `lpr/lqt = 0`); en inserts, burbuja de inserción de una pasada
  derecha→izquierda con comparación `(ask ? lpr[slot] < lpr[slot-1] :
  lpr[slot] > lpr[slot-1])` y parada al llegar a posición; un cambio de
  cantidad no reordena (invariante: la lista ya está ordenada). Con esto el
  precio stale de un nivel vaciado es estructuralmente imposible (la
  compactación lo barre en el mismo ciclo) — el mutante DP-EMPTYSTALE pasó a
  ser equivalente y se sustituyó por DP-TOPNCOUNT.
- **Runner de mutación**: `apply_safe` escribe el mutante en `.mut` temporal y
  usa `os.replace` — un SystemExit de un patrón no encontrado YA NO puede
  truncar el RTL (incidente en esta iteración: U-NOTATOMIC dejó el archivo en
  0 bytes por el `open(RTL,"w")` truncador; restaurado desde `.bak`).

### Mutación (gate E)

**22/22 mutantes muertos** (cuádruple suite fase2 + sim-hash + sim-depth +
sim-hard; OV-BEST re-textado a la comparación nueva, U-NOTATOMIC a
`o_valid[u_nidx]`, HASH-UADD-FULL a U-NOFULLCHECK del pre-check en ST_APPLY,
LV-NEGWRAP nuevo, DP-EMPTYSTALE → DP-TOPNCOUNT por equivalencia):

```
TODOS LOS MUTANTES MUERTOS. Gate E PASS.
```

Lint: `--lint-only -Wall` limpio en los 3 módulos (orderbook, itch_parser,
itch_chain con dependencias).

## Tabla de gates

| Gate | Comando / evidencia | Resultado |
|---|---|---|
| **A. Simulación** | 7 suites phase3 (25/25) + fase1 19/19 + fase2 14/14 PASS | ✔ |
| **B. Compilación/lint sintaxis** | Verilator 5.050 `--lint-only -Wall` limpio en orderbook, itch_parser, itch_chain (con deps) | ✔ |
| **C. Estilo** | `verible-verilog-lint` (si instalado) | — |
| **D. Cobertura + mapeo** | Tabla spec↔tests (pendiente al cierre) | — |
| **E. Mutación HDL** | 22/22 mutantes muertos (cuádruple suite fase2+hash+depth+hard) | ✔ |
| **F. Completitud Gherkin** | espejos del `.feature` ↔ tests | — |
| **G. Rigor + timing** | G0/G2/G3 ✔; G5 adversarial: 0 CRITICO, 2 MAYOR cerrados en iteración 6 (U atómico + guard anti-fantasma); G timing: run externo del owner (criterio 10) | — |

## Veredicto

Iteraciones 1-6 (criterios 1-9 + 11; criterio 10 con artefactos commiteados y
informe del run externo pendiente de pegar): **verde con evidencia**;
pendiente de `/verify` formal y del WNS del owner.