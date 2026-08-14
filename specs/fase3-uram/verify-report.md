# verify-report — fase3-uram

> Régimen de gates de Atenea re-mapeado al flujo HDL. Sin verify-report,
> `/grade` da FAIL directo. Lo escribe `/verify` campaña a campaña.

## Iteración 3 — pipeline de niveles registrado (SEC-URAM-03)

### Meta del atacante/diseño

El criterio 4 exige que la pasada O(P) combinacional de `level_add` (media
6-8 ns a P=32, bloqueador B2 para el cierre de 3,103 ns) desaparezca del
camino crítico. `level_add`/`reduce_level`/`apply_uadd_half` se sustituyen
por un **pipeline de 3 etapas registradas**, cada una de rutas cortas por
slot:

1. **Etapa 1 (launch, en ST_APPLY/ST_UADD)** — tarea `launch_lv`: captura la
   copia del lado (`lv_pr`/`lv_qt` de `lv_price`/`lv_qty`), el precio y delta
   objetivo (`lv_lprice`/`lv_delta`/`lv_base`), y computa **por slot, sin
   encadenar**: predicados `lv_eq` (precio objetivo), `lv_zer` (hueco),
   `lv_beat` (nivel estrictamente peor que el precio nuevo) y las sumas
   candidatas `lv_cand_newq[i] = qty[i]+delta`.
2. **Etapa 2 (ST_LV2=4'd8, decode)** — tarea `decode_lv2`: encoders
   first-hot por prioridad → `lv2_found`/`lv2_empty`/`lv2_ins`/`lv2_newq`/
   `lv2_mode` (NONE/UPDATE/INSERT/REMOVE). Errores con la semántica exacta
   de fase 3: overflow (found=-1 ∧ empty=-1), reduce sobre nivel ausente
   (found=-1 ∧ delta<0), cantidad que envuelve (cand[32]) → modo NONE +
   pulso `error` de 1 ciclo. **Insert**: `lv_beat` marca a los ESTRICTAMENTE
   peores; por invariante de orden forman un sufijo, así que j = primer
   vencido, y si no hay ninguno (elemento peor de todos) j = empty.
3. **Etapa 3 (ST_LV3=4'd9, materializar+escribir)** — tarea
   `materialize_write`: muxes por modo (REMOVE barre a la izquierda, INSERT
   burbujea `[j..empty-1]` a la derecha, UPDATE solo qty, NONE copia) y una
   **única** escritura de `lv_price`/`lv_qty`. Coste: +2 ciclos por operación
   de nivel (A/F/E/C/X/D), el replace U encadena delete+add con su ciclo
   `ST_UADD` de lanzamiento entre medias (la etapa 1 de la 2ª op debe leer el
   estado post-delete; la URAM 1W impide solapar las escrituras).

`st` pasa a 4 bits; el FSM secuencia `ST_APPLY→LV2→LV3→(UADD→LV2→LV3)→EMIT`.
El guard de emisión, el prefetch y la sonda no cambian.

### Rojo con evidencia (TDD)

| Test | Rojo | Causa raíz |
|---|---|---|
| SEC-URAM-03 (uram) | `0 runs de pipeline de niveles exp=35` — 1/2 FAIL | RTL aún sin ST_LV2/ST_LV3 (rojo genuino: el pin estructural solo existe con el pipeline registrado) |
| INV/SEC-URAM-03 | `0 runs de niveles exp=2` — 2/2 FAIL | idem |

### Hallazgos del diseño (corregidos en verde, sin tocar el contrato)

1. **Semántica del insert re-derivada**: la burbuja de inserción original
   swap-cuando-venzo; el run de vencidos es un **sufijo** → j = primer
   índice vencido (lv_beat), y el elemento peor de todos se queda en el
   hueco (j = empty), no en 0.
2. **El U encadena sus 2 ops con un ciclo de por medio**: delete
   (LV2→LV3) + add (lanzada en ST_UADD — el mismo ciclo de lanzamiento que
   existía en fase 3 — luego LV2→LV3). No es burbuja: cada operación ≤ 2
   ciclos de pipeline (pinza del gherkin), y el INV exige
   `runs[-1][0] == runs[-2][-1] + 2` (no +1).
3. Trinquete de warnings respetado (nada silenciado): `base`/`lv2_*` a
   32 bits para comparar contra índices `integer` sin WIDTHEXPAND; `lv_delta`
   a `[31:0]` (el bit 33 no se usa: el chequeo de envoltura vive en
   `lv_cand_newq[fnd][32]`).

### Verde (evidencia)

```
** TESTS=4 PASS=4 FAIL=0 **   (uram sim-uram: SEC-URAM-01/02 + SEC-URAM-03 35 ops,
                              35 runs <=2 ciclos, sin repetición/retroceso, sin
                              precio stale ni cantidad envuelta + INV: U = 2 runs)
** TESTS=2 PASS=2 FAIL=0 **   (uram sim-anx)
** TESTS=5 PASS=5 FAIL=0 **   (phase3 sim: feed real 31.400 msgs -> 30.729 eventos bit a bit, anomaly=671, cross=0)
** TESTS=8 PASS=8 FAIL=0 **   (phase3 sim-hash)
** TESTS=3 PASS=3 FAIL=0 **   (phase3 sim-depth)
** TESTS=2 PASS=2 FAIL=0 **   (phase3 sim-hard)
** TESTS=4 PASS=4 FAIL=0 **   (phase3 sim-parser)
** TESTS=2 PASS=2 FAIL=0 **   (phase3 sim-chain: CHAIN-01 bit a bit)
** TESTS=1 PASS=1 FAIL=0 **   (phase3 sim-lat: determinista, JSON regenerado)
** TESTS=14 PASS=14 FAIL=0 ** (fase 2)
** TESTS=19 PASS=19 FAIL=0 ** (fase 1)
** 32/32 OK **                (golden model)
** lint 0 warnings **         (verilator -Wall: DW32/K20, DW64/K19, DW32/K19)
```

Latencia re-medida (`latency_dw32.json` regenerado por SEC-LAT-01, 30.729
eventos, anomaly=671, cross=0, gaps=0):

| Métrica | Iter 2 (URAM) | Iter 3 (pipeline) | Δ |
|---|---|---|---|
| Media total | 54,943 (170,5 ns) | **64,586** (200,4 ns) | +9,6 |
| p99 / p50 | 66 / 50 | **76 / 60** | +10 / +10 |
| A media | 65,26 | 74,99 | +9,7 |
| D media | 47,59 | 57,09 | +9,5 |
| U media | 59,46 | 71,20 | +11,7 (2 ops × +2 + launch) |
| X media | 46,10 | 55,60 | +9,5 |
| max (A) | 65.579 | **65.583** | +4 (ST_INVAL 65.536 + pipeline) |

El pipeline registrado cuesta +2 ciclos por operación y la media del feed
real sube ~+9,5 por el efecto cola de las ráfagas (el book acepta 1 mensaje
más tarde cuando el parser está saturado). El bit a bit se mantiene
(30.729/30.729, anomaly=671). **SEC-URAM-04 (media ≤ 45) sigue abierta**: la
recuperación de los ~20+ ciclos pendientes pasa por recortar el run de la
sonda (8 lecturas a 1 slot/ciclo) o superponer BBO de la 1ª op con la 2ª del
U — candidatos para la iteración 4.

### Cambios

- `rtl/orderbook/orderbook.sv`: `st` a 4 bits; `ST_LV2`/`ST_LV3`; tareas
  `launch_lv` (etapa 1), `decode_lv2` (etapa 2), `materialize_write` (etapa
  3) — `level_add`/`reduce_level`/`apply_uadd_half` eliminadas; registros
  del pipeline (`lv_*`/`lv2_*`/`wp`/`wq`) con reset; `apply_one` con salida
  `out_lv`; `lv_uadd` latchado en ST_APPLY y limpio en ST_UADD.
- `verification/testbenches/uram/test_uram32.py`: `drive_sampling` devuelve
  `(out, trace, errores, anomaly)`; `_split_lv_runs`; tests SEC-URAM-03
  (espejo del gherkin: 35 ops, 35 runs ≤ 2 ciclos, sin repetición/retroceso,
  `out[-1]=(393,(100031,100,0,0),0)` sin wrap) e INV/SEC-URAM-03 (U: 4 runs
  totales, 2 del U encadenados con `+2` entre sí, BBO vs golden).
- `verification/vectors/latency/latency_dw32.json`: regenerado (tabla de
  latencia de arriba).

### Pendiente para iteraciones siguientes

- SEC-URAM-04: latencia media ≤ 45 ciclos — **abierta** (64,6; recorte del
  run de sonda y/o solapamiento del U son los candidatos).
- Criterio 10: synth en Vivado (timing 322,265625 MHz + URAM) — el pipeline
  de niveles quita el bloqueador B2 del camino crítico.

## Iteración 2 — tabla en URAM con sonda serializada + prefetch (SEC-URAM-01/02)

### Meta del atacante/diseño

El book pasa del array de registros a `reg [OW-1:0] o_mem [NSLOT-1:0]` (OW=86:
`{qty[31:0], price[31:0], side[21], ref[20:1], valid[0]}`) que sintetiza a
URAM. Sin reset global del array (mataría la URAM): `ST_INVAL` invalida 1
slot/ciclo (65.536 ciclos post-reset). El lookup es una **sonda serializada**
a 1 slot/ciclo (WARM + WALK) con lectura **registrada** (`rd_addr` → `rd_data`
1 ciclo; nunca combinacional — SEC-URAM-01) y **prefetch** del grupo de hash
durante `ST_BODY` (el `order_ref` viaja en las primeras words del cuerpo; el
run termina antes de `ST_APPLY` — SEC-URAM-02). El U atómico corre **dos runs
en serie** (old: lookup/delete; new: chequeo de capacidad) con latches de
resultados separados (`pr_*` / `pr_new_*`): si el new no cabe, la original
sobrevive (INV-U-01).

### Rojo con evidencia (TDD)

| Test | Rojo | Causa raíz |
|---|---|---|
| SEC-URAM-01/02 (uram) | `AttributeError: orderbook contains no child object named pr_phase` — 2/2 FAIL | RTL aún sin sonda (el área uram nació antes que el RTL URAM: rojo de TDD genuino) |
| SEC-URAM-01 (b) | discriminador de lectura registrada fallaba | el check comparaba contra el apply del S previo (sin probe) en vez del arranque del propio run |
| SEC-HASH-02 (regresión) | `la tabla llena debe señalar error` — errores=0 | dos bugs de la sonda (abajo) |

### Dos bugs de la sonda (hallazgos de traza con test_dbg_full)

1. **Off-by-one del WALK**: la transición WARM→WALK ya emitía `base+1` y el
   continue emitía `pr_base + pr_i + 1` → dirección duplicada → a partir del
   slot 2 el dato leído iba un ciclo por delante del slot evaluado (los datos
   leídos eran `5,6,6,7,8,9,10,11`: se duplicaba el 6 y el último slot del
   camino, `base+7`, jamás se leía). El 8º add "cabía" siempre en el hueco
   permanente del slot 7 → la tabla llena nunca señalaba error. Fix:
   `rd_addr <= pr_base + (pr_i + 2)` (alinea slot evaluado con dato leído;
   el run sigue durando 9 ciclos, pinza (c) intacta).
2. **Race del terminal**: cuando el hueco libre era el **último** slot del
   camino, la rama terminal leía `w_empty_found` con su valor **viejo** (0)
   mientras la rama de hueco lo asertaba en el mismo ciclo → `pr_full` se
   latcheaba con el hueco ya registrado → el 8º add daba error sin serlo (y
   su ref no entraba → anomalía fantasma en SEC-HASH-01). Fix: la condición
   de llena exige `rd_data[0]` (slot terminal ocupado):
   `pr_rec_empty && !w_empty_found && rd_data[0]`.

### Verde (evidencia)

```
** TESTS=2 PASS=2 FAIL=0 **   (uram sim-uram: SEC-URAM-01 10 runs/87 lecturas
                              + SEC-URAM-02 prefetch en el ciclo 65545 con st=ST_BODY)
** TESTS=2 PASS=2 FAIL=0 **   (uram sim-anx: ANX-01/02 contra el layout recortado)
** TESTS=8 PASS=8 FAIL=0 **   (phase3 sim-hash: SEC-HASH-01..04 + 02b/02c + INV-U-01/OV-01)
** TESTS=5 PASS=5 FAIL=0 **   (phase3 sim: B32-02 feed real 31.400 msgs -> 30.729 eventos bit a bit, anomaly=671, cross=0)
** TESTS=3 PASS=3 FAIL=0 **   (phase3 sim-depth)
** TESTS=2 PASS=2 FAIL=0 **   (phase3 sim-hard)
** TESTS=4 PASS=4 FAIL=0 **   (phase3 sim-parser)
** TESTS=2 PASS=2 FAIL=0 **   (phase3 sim-chain: CHAIN-01 bit a bit)
** TESTS=1 PASS=1 FAIL=0 **   (phase3 sim-lat: determinista, JSON regenerado)
** TESTS=14 PASS=14 FAIL=0 ** (fase 2)
** TESTS=19 PASS=19 FAIL=0 ** (fase 1)
** 32/32 OK **                (golden model)
```

Latencia re-medida con el RTL URAM (`latency_dw32.json` regenerado por
SEC-LAT-01, 30.729 eventos, anomaly=671, cross=0):

| Métrica | Iter 1 (recorte) | Iter 2 (URAM) | Δ |
|---|---|---|---|
| Media total | 34,835 (108,1 ns) | **54,943** (170,5 ns) | +20,1 ciclos |
| p99 / p50 / min | 39 / 34 / 24 | **66 / 50 / 39** | +27 / +16 / +15 |
| A media | 37,67 | 65,26 | +27,6 |
| D media | 32,41 | 47,59 | +15,2 |
| U media | 37,49 | 59,46 | +22,0 |
| X media | 33,20 | 46,10 | +12,9 |
| max (A) | 41 | **65.579** | arranque: espera los 65.536 ciclos de ST_INVAL (~203 µs @322 MHz) |

La sonda serializada (10 ciclos por operación de tabla, solapada con ST_BODY
solo en mensajes largos) sube la latencia media por encima del umbral ≤45 del
criterio: **SEC-URAM-04 queda pendiente para la iteración 3** (pipeline de la
sonda o recorte del run: el slot en WARM/WALK de 8 lecturas a 1 slot/ciclo es
el costo dominante).

### Cambios

- `rtl/orderbook/orderbook.sv`: reescritura del book — `o_mem` URAM (86 bits,
  sin reset global), FSM con `ST_INVAL`/`WAIT_PROBE`, sonda serializada
  WARM/WALK con prefetch en ST_BODY, latches dobles para el U atómico
  (`pr_*`/`pr_new_*`), `mem_wr` escribiendo el array directamente, fixes del
  off-by-one del WALK y de la race del terminal; `pr_i` a 16 bits (aritmética
  de direcciones sin WIDTHEXPAND).
- `verification/testbenches/uram/test_uram32.py` (nuevo): SEC-URAM-01/02
  (importan `_reset` de test_orderbook; checks (a) serialización por-run, (b)
  dato registrado inalterado en el arranque del run, (c) run de 9 ciclos).
- `verification/testbenches/uram/Makefile`: targets `sim-uram`, `sim-anx`,
  `clean-all`.
- `verification/vectors/latency/latency_dw32.json`: regenerado (evidencia de
  la latencia URAM, ver tabla).

### Pendiente para iteraciones siguientes

- SEC-URAM-03: pipeline de niveles registrado (la mitad del book sigue con
  lógica combinacional de 32 niveles por lado).
- SEC-URAM-04: latencia media ≤ 45 ciclos — **abierta** (54,9 con la sonda;
  iteración 3 debe recuperar ~10+ ciclos).
- REG-01/CHAIN-01: ya verdes bit a bit con el RTL URAM.
- Criterio 10: synth en Vivado (timing 322,265625 MHz + URAM).

## Iteración 1 — recorte del Anexo A de 32 bits (criterio 1, ANX-01/ANX-02)

### Meta del atacante/diseño

Cambio de contrato del Anexo A de 32 bits (edit explícito del criterio 1 de
fase 3, decidido por el owner): el layout pasa de
`w0={type,locate,len}, w1=idx, w2=ts[31:0], w3={ts[47:32],16'b0}, w4..=cuerpo`
a **`w0, w1=idx, w2..=cuerpo` — sin words de timestamp** (el book no las
consume; solo usa w1 para el sanity `m_idx`). Ganancia esperada ~2 ciclos/
mensaje + ~15 % de palabras del stream interno; la medición real dio más.

### Rojo con evidencia (TDD)

| Test | Rojo | Causa raíz |
|---|---|---|
| ANX-01 (parser) | `got(42) exp(34)` — 8 words de más en 4 mensajes | el RTL aún emitía w2/w3 de ts |
| ANX-02 (peor caso) | idem (42 vs 34) | idem |
| B32-01 (book) | `got=[] exp=[...]` — sin un solo evento BBO | `hrem=3` en ST_TS: el book comía la primera word del cuerpo como si fuera ts; con el layout recortado el desfase rompe todo |
| INV-B32-01 | `got=[(72164352,...)]` — garbage | idem (desalineación de cabecera) |

### Verde (evidencia)

```
** TESTS=2 PASS=2 FAIL=0 **   (uram sim-anx: ANX-01 corpus 75 words bit a bit +
                              feed real 31.400 msgs -> 197.452 words bit a bit; ANX-02 2 stalls <= 24)
** TESTS=5 PASS=5 FAIL=0 **   (phase3 sim)
** TESTS=8 PASS=8 FAIL=0 **   (phase3 sim-hash)
** TESTS=3 PASS=3 FAIL=0 **   (phase3 sim-depth)
** TESTS=2 PASS=2 FAIL=0 **   (phase3 sim-hard)
** TESTS=4 PASS=4 FAIL=0 **   (phase3 sim-parser)
** TESTS=2 PASS=2 FAIL=0 **   (phase3 sim-chain: CHAIN-01 bit a bit)
** TESTS=1 PASS=1 FAIL=0 **   (phase3 sim-lat: determinista, JSON regenerado)
** TESTS=14 PASS=14 FAIL=0 ** (fase 2)
** TESTS=19 PASS=19 FAIL=0 ** (fase 1)
** 32/32 OK **                (golden model)
```

Latencia re-medida con el layout recortado (`latency_dw32.json` regenerado por
SEC-LAT-01, 30.729 eventos, anomaly=671, cross=0):

| Métrica | Antes (QB=64) | Después del recorte | Δ |
|---|---|---|---|
| Media total | 42,40 ciclos | **34,835** (108,1 ns) | −18 % |
| p99 / p50 / min | 47 / 42 / 27 | **39 / 34 / 24** | −8 / −8 / −3 |
| A media | 45,39 | 37,67 | −17 % |
| D media | 39,86 | 32,41 | −19 % |
| U media | 40,66 | 37,49 | −8 % |
| X media | 40,66 | 33,20 | −18 % |

(* X era 40,66 (latencia.md pre-recorte, QB=64); el recorte elimina ~2 words/
mensaje de la cola → el drenaje acelera todos los tipos; la mejora supera la
estimación del plan.)

### Cambios

- `rtl/parser/itch_parser.sv`: ST_TS a DW=32 emite solo w1=msg_idx y pasa a
  ST_BODY; reg `hw` eliminada (era el contador de las 3 words de cabecera);
  comentario de cabecera con el layout recortado. DW=64 intacto.
- `rtl/orderbook/orderbook.sv`: `hrem` fijado a 1 (antes 3 a DW=32);
  ST_TS captura `m_idx` de la única word de cabecera a DW=32.
- `verification/testbenches/phase3/test_parser32.py`: `oracle_words32` sin las
  words de ts (layout recortado, docstring actualizado).
- `verification/testbenches/phase3/test_orderbook32.py`: `anexo_words32` sin
  las 2 words de ts (oráculo compartido por depth/hash/hard).
- `verification/testbenches/uram/` (área nueva de la campaña): `test_anx32.py`
  (espejos ANX-01/ANX-02, importan los oráculos — nunca los re-escriben) +
  Makefile con target `sim-anx`.
- `specs/fase3-optimizacion/spec.md` + gherkin P32-01: layout recortado
  (elimina la contradicción con el contrato nuevo; el campaign spec declara el
  edit explícito).

### Pendiente para iteraciones siguientes

- Criterios 2-8: memoria URAM (SEC-URAM-01), sonda serializada + prefetch
  (SEC-URAM-02), pipeline de niveles (SEC-URAM-03), latencia ≤ 45 (ya 34,8 —
  SEC-URAM-04), regresión con el RTL URAM (REG-01/CHAIN-01), synth (criterio 7).