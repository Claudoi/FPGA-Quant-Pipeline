# Revisión exhaustiva 2026-08-14 — corrección, síntesis y latencia

> Revisión de todo el repositorio tras el traslado al SSD: golden model,
> oráculos, testbenches, scripts, RTL y artefactos de fase 3. Objetivo:
> encontrar fallos, preparar el diseño para Vivado (criterio 10) y bajar la
> latencia wire→BBO de referencia.

## 1. Corrección (capa de verificación y golden)

Revisados: `golden_model/` (messages.py, parser.py, book.py, message_oracle.py),
los 8 testbenches (fase 1: parser; fase 2: orderbook; phase3: parser32, hash32,
depth32, hard32, chain32, lat32) y los runners de mutación (`mutate_parser.py`,
`mutate_orderbook.py`). **No se encontró ningún fallo de corrección**: la
semántica del RTL replica el golden bit a bit (30.729 eventos), los oráculos
derivan del golden y no del RTL (lente 6), los 22 mutantes están muertos y los
offsets de `messages.py` son la fuente única.

Nits menores (cosmética, sin impacto):

- `test_orderbook.py:195`: `ts = int.from_bytes(b"", "big") if False else 0` —
  código muerto (resto de una refactorización).
- `binaryfile_to_pcap.py:128`: el timestamp pcap deriva del primer mensaje del
  paquete (correcto); el RTL no lo consume (documentado).

## 2. Hallazgo mayor — el order book actual NO es sintetizable (criterio 10)

La variante actual del book (fase 3, iteración 2) usa **registros planos de
65.536 entradas con sonda combinacional paralela**:

- `lookup_ref`/`first_empty` (orderbook.sv:168-196): 8 sondas por operación
  leen `o_valid/o_ref/o_price/o_qty/o_side` con **índice variable** (h+ii) —
  cada lectura es un mux 65.536:1 (~22K LUTs por bit: árbol de muxes 2:1 de 16
  niveles con 6-LUTs ≈ 65.535/3). Las ~330 bits leídas por ciclo (o_ref 8×19 +
  o_price 2×32 + o_qty 3×32 + valid/side 18×1) suman **millones de LUTs** —
  superan con holgura los 1.182K LUTs de la VU9P. La indexación combinacional
  impide además inferir BRAM/URAM (lecturas síncronas), así que Vivado no tiene
  salida: ni siquiera es un problema de timing, es estructural.
- `level_add` (orderbook.sv:334-412): la pasada de reordenación O(P) con
  burbuja de inserción encadena hasta 32 iteraciones de (comparador de 32 bits
  + mux 33 bits) ≈ 6-8 ns combinacionales dentro de ST_APPLY — no cierra
  3,103 ns (322,265625 MHz).
- El parser es viable (~1,5-2 ns del barrel shifter de 1024 bits; ver §4), y
  `emit_bbo`/`loc_lookup` son árboles de prioridad aceptables.

**Conclusión:** el criterio 9 pasó con la documentación del mapeo URAM
(`docs/writeup/uram.md`), pero las "lecturas registradas (1 ciclo)" que exige
su texto **nunca se implementaron en el RTL**. El criterio 10 no puede pasar
con el RTL actual aunque el owner corra Vivado. El trabajo de la iteración de
URAM (sonda serializada 1 slot/ciclo con lectura registrada + prefetch durante
ST_BODY, niveles en memoria con mantenimiento pipelinizado) es la única vía a
322 MHz — es el punto de partida natural de la próxima campaña.

## 3. Latencia — dónde están los 69 ciclos medidos (y el hallazgo real)

Evidencia: `verification/vectors/latency/latency_dw32.json` (media 69,26;
p99 77; min 27). El modelo de la cadena (parser→book a DW=32, sin colas)
predice ~14-19 ciclos por mensaje (A: 14 de parser + book ≈ 16). Los ~50 ciclos
restantes son **backlog estacionario de la cola del parser**:

- La entrada fluye a 1 palabra/ciclo (4 B/c) mientras `qn+4 ≤ QB`; el drenaje
  solo ocurre en ST_CAP (todo el mensaje de golpe, ~38 B cada 14 ciclos =
  2,7 B/c). Entrada > drenaje ⇒ la cola se fija en QB y la latencia ≈
  backlog + procesamiento ≈ (QB/4)/7,7 × 11 + 16. Con QB=128: ~60-70 ✓ (el
  min 27 es la cola vacía del arranque).
- **Hallazgo real (diagnóstico con traza interna `qn`, no teoría):** el
  `itch_parser.sv` ya declaraba `QB=64` en su default, pero `itch_chain.sv`
  tiene su **propio parámetro `QB=128`** que **sobrescribe** el default del
  parser al instanciarlo (`.QB(QB)`). Todos los experimentos de "QB 128→64"
  sobre el default del parser eran nulos para la cadena: la latencia quedaba
  idéntica (72,191) con builds limpios — síntoma engañoso que se resolvió
  instrumentando `qn` (la cola superaba 64 B ⇒ el binario usaba 128, no el
  parámetro que creíamos). La regla: **el área de fase 3 (chain) vive en los
  parámetros de `itch_chain.sv` y de la línea `-G` del Makefile, no en los
  defaults de los módulos** (ya documentado en el gotcha del Makefile para
  `-G`; faltaba para los defaults).
- **QB 128 → 64 en la cadena**: backlog 32 → 16 palabras ⇒ latencia total
  media **69,26 → 42,40 ciclos** (214,9 → 131,5 ns; p99 77 → 47) = **~1,63×**,
  con la corrección bit a bit intacta (CHAIN-01: 30.729 eventos, 0 gaps).
  El barrel shifter del parser baja de 1024 a 512 bits (área/ruta para Vivado).
- QB mínimo para conservar 0 stalls en el tramo probado de 4 mensajes A/U:
  pico de cola ≈ 80-88 B ⇒ QB ≥ 88 (recorte solo ~1,4×). QB=64 recorta ~1,63×
  a costa de stalls acotados (~15 en el tramo) — "sin backpressure sostenida"
  del régimen de fase 1 (la spec ya documenta la limitación del feed infinito,
  LIN-01 alcance).

Límite estructural: la semántica "sin registro parcial" (SEC-FRM-01/02) exige
capturar el mensaje completo antes de emitir ⇒ el drenaje en emisión
(aligner, el "pendiente" de la spec LIN-01) no reduce la espera de
completitud; solo el tamaño de cola fija el backlog estacionario.

## 4. Optimizaciones aplicadas en esta revisión (iteración 6)

1. **QB 128 → 64** (`rtl/itch_chain.sv` — el default del parser ya era 64):
   latencia total ~69,26 → **42,40 ciclos** (214,9 → 131,5 ns, ~1,63×) +
   barrel shifter 1024 → 512 bits (área/ruta crítica del parser para Vivado).
2. **Tests LIN-01 (fase 1) y P32-02 (phase3)**: "0 stalls" → "stalls acotados
   ≤ 24" (el tramo de 4 mensajes A/U con QB=64 acumula ~15; la corrección bit
   a bit se mantiene; el límite sigue cazando regresiones groseras).
3. Evidencia re-medida: `latency_dw32.json` (determinista, 2 ejecuciones
   idénticas) + `docs/writeup/latencia.md`.

## 5. Pendientes recomendados (próxima campaña)

- **Iteración URAM del book** (bloqueador del criterio 10): sonda serializada
  1 slot/ciclo con lecturas registradas (prefetch del hash durante ST_BODY),
  tabla en ~20 URAM (65.536×86 bits), mantenimiento de niveles pipelinizado
  (partir la burbuja O(P) en 2-3 etapas), `level_add` con copia local ya
  registrada. El diseño está documentado en `docs/writeup/uram.md`; falta
  implementarlo en RTL con TDD (las suites phase3/hash/depth/hard lo protegen).
- **Recorte del encabezado de 32 bits** (w2/w3 de ts, que el book descarta):
  ~2 ciclos/mensaje de latencia y ~15 % de palabras — cambio de contrato del
  Anexo A de 32 bits, mejor dentro de la campaña URAM.
- **Criterio 10**: sigue dependiendo del run Vivado del owner; ahora con un
  diseño (post-URAM) que pueda cerrar.