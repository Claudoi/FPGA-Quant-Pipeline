# Próxima sesión: campaña URAM del order book — plan y lecciones de la sesión anterior

> Documento de transición entre sesiones. Parte A: lo que hay que hacer en la
> próxima sesión (campaña de la iteración URAM, único camino al criterio 10).
> Parte B: todo lo aprendido en la sesión del 2026-08-14 (revisión exhaustiva
> y optimización de latencia), con las lecciones operativas verificadas.
> Contexto: `AGENTS.md`, `docs/DESARROLLO.md`,
> `docs/writeup/revision-exhaustiva-2026-08-14.md`.

---

# Parte A — Plan de la próxima sesión (campaña URAM)

## A.0 Objetivo de la sesión

Cerrar el **criterio 10 (síntesis a 322,265625 MHz)** del documento maestro,
convirtiendo el order book de registros planos no sintetizables en un diseño
URAM que pueda cerrar timing, manteniendo la corrección bit a bit contra el
golden (30.729 eventos) y la latencia actual (~42 ciclos).

El bloqueador es estructural y está medido (B1/B2/B3):

| Bloqueador | Dónde | Problema | Remedio (campaña) |
|---|---|---|---|
| B1 | `lookup_ref`/`first_empty` (orderbook.sv:168-196) | 8 sondas combinacionales con índice variable sobre registros planos 65.536 → muxes 65.536:1 (~22K LUTs/bit, ~330 bits leídas/ciclo → millones de LUTs; >1,18M de la VU9P) | Sonda **serializada 1 slot/ciclo** con **lecturas registradas** (prefetch del grupo de hash durante ST_BODY); tabla en ~20 URAM (65.536×86 bits) |
| B2 | `level_add` (orderbook.sv:334-412) | Burbuja O(P) encadenada en ST_APPLY ≈ 6-8 ns combinacionales vs 3,103 ns de periodo | Pipeline del mantenimiento de niveles en 2-3 etapas registradas |
| B3 | barrel shifter 1024 bits del parser | ~1,5-2 ns (ajustado; ya bajado a 512 bits con QB=64) | Verificar en la síntesis; si sobra, recorte del Anexo A |

El criterio 9 pasó con la documentación de `docs/writeup/uram.md`, pero las
"lecturas registradas (1 ciclo)" que exige su texto **nunca se implementaron
en RTL** — esta campaña las implementa.

## A.1 Paso 1 — `/spec` de la campaña (primera hora)

Contrato nuevo en `specs/fase3-uram/` (campaña nueva del ciclo
spec → build → verify → grade), con:

- **Escenario de negocio**: mismo pipeline (parser ITCH → book → BBO/depth),
  mismo Anexo A de 32 bits, misma semántica de eventos; cambia la
  implementación interna del book (tabla en URAM + sonda serializada +
  pipeline de niveles).
- **Criterios numerados** (espejo de fase 3 + lo nuevo):
  1. La tabla hash vive en URAM: 65.536 slots × 86 bits ≈ 20 URAM, inferida
     (lectura síncrona, sin indexación combinacional).
  2. Sonda serializada: máximo 1 slot/ciclo, con `first_empty`/`lookup_ref`
     resultado de lecturas registradas; el probe de 8 refs consume ≤ 8+2
     ciclos y usa el **prefetch durante ST_BODY** (los slots del grupo de
     hash del mensaje en curso se leen antes de ST_APPLY — el diseño
     documentado en `uram.md`).
  3. `level_add` pipelinizado: el reordenamiento O(P) se parte en etapas
     registradas; el nivel insertado/borrado no puede crear burbujas >2
     ciclos ni precios stale (mutante DP-EMPTYSTALE ya cubre el fantasma).
  4. Regresión total: 30.729 eventos BBO bit a bit + depth 640 bits +
     anomalías/cross idénticos (CHAIN-01) con la latencia ≤ 45 ciclos de
     media (SEC-LAT-01 determinista).
  5. Criterio 10: artefacts de síntesis (constraints 3,103 ns + tcl) listos
     para el run Vivado del owner; `scripts/verify/synth_check.py` 10/10.
- **Stop limit**: 4 iteraciones (el diseño ya está documentado; el riesgo
  principal es el pipeline de niveles, no la URAM).
- Riesgos explícitos en la spec: (a) el `apply` multi-ciclo puede alargar la
  latencia si el prefetch no encaja en ST_BODY — el guardarraíl es SEC-LAT-01;
  (b) Vivado puede no inferir URAM por un patrón de reset/escritura — se
  declara la lectura síncrona y se deja el run al owner.

## A.2 Paso 2 — TDD estricto (rojo antes que nada)

Los testbenches existentes de fase 3 ya protegen el refactor (son el ariete
de la regresión):

- `sim-hash` (8/8: probing, tabla llena, tombstones, U atómico, fantasma),
- `sim-depth` (3/3: top-N bit a bit), `sim-hard` (2/2: NSYM y backpressure),
- `sim` (5/5: BBO golden, replay real, replace atómico, raw add/execute),
- `sim-chain` (2/2: 30.729 eventos), `sim-lat` (1/1: determinista),
- fase 1 (19/19) y fase 2 (14/14) en regresión.

Tests nuevos de la campaña (para que el criterio 9 deje de ser solo
documentación):

1. **SEC-URAM-01**: lectura registrada — verificar vía señal que la sonda
   NO indexa memoria combinacionalmente (el test puede pinzar el resultado
   con un probe de 1 solo ciclo y comprobar el retardo de 1 ciclo de la
   lectura: `lookup` válido en el ciclo posterior a la dirección).
2. **SEC-URAM-02**: prefetch en ST_BODY — el grupo de hash del mensaje se
   precarga antes de ST_APPLY (mismo resultado que el probing actual en un
   hash con colisión forzada, K=20).
3. **SEC-URAM-03**: pipeline de niveles — secuencia de 33 adds + D (el
   escenario INV-OV-01) sin fantasma y sin burbuja >2 ciclos.
4. **SEC-URAM-04**: latencia — re-ejecutar SEC-LAT-01 y exigir media ≤ 45
   ciclos con el mismo JSON determinista.

Rojo evidenciado de cada uno ANTES de tocar el RTL (el régimen de la casa).

## A.3 Paso 3 — Implementación (el orden de ataque)

1. **Sonda serializada + prefetch** (B1): sustituir las 8 lecturas
   paralelas de `lookup_ref` por un contador de slot y lecturas registradas;
   mover el arranque de la sonda a ST_BODY (el mensaje se está consumiendo y
   la tabla está libre). El `apply` al terminar ST_BODY entra en ST_APPLY con
   el grupo ya en registros.
2. **Tabla en URAM**: convertir los arrays `o_valid/o_ref/o_price/o_qty/o_side`
   en un único array 65.536×86 bits (o un `logic [85:0] mem [65535:0]`) con
   reset por invalidación de slots (nunca reset global del array — patrón
   estándar para BRAM/URAM; el reset global impediría la inferencia).
3. **Pipeline de `level_add`** (B2): las 3 pasadas (captura, burbuja,
   compactación) en etapas registradas separadas; cada mensaje de
   add/delete/replace consume ≤ 2-3 ciclos extra en ST_APPLY (el diseño ya
   está en `uram.md`; ahora es código).
4. **Recorte del Anexo A (dentro de esta campaña, si el cronómetro lo
   permite)**: eliminar las words w2/w3 de ts (el book no las usa; solo w1
   para el sanity `m_idx`). Es cambio de contrato del Anexo A de 32 bits
   (spec fase3, línea 24-25) → requiere su propio criterio en la spec de la
   campaña y actualizar `test_p32_01_anexo_a_32_bits`. Ganancia: ~2 ciclos/
   mensaje + ~15% menos palabras (cae la presión del barrel shifter y la
   cola). Si no entra, queda como C2 documentado (la spec del maestro ya lo
   lista).

## A.4 Paso 4 — Verificación completa y evidencia

- Las 9 suites + golden (32 tests) verdes: fase1 19, fase2 14, phase3 25,
  golden 32.
- Mutación: el runner existente (`mutate_orderbook.py`, 12 mutantes) +
  mutantes nuevos del pipeline de niveles (p. ej. PIPE-SKIP-STAGE,
  URAM-NO-PREFETCH). 100% muertos o equivalentes justificados.
- Latencia re-medida → `latency_dw32.json` regenerado + `latencia.md`
  actualizado (objetivo: ≤ 45 ciclos de media; con el recorte del Anexo A,
  ~35).
- Lint `-Wall` limpio en los 3 módulos.
- `verify-report.md` de la campaña con los outputs reales pegados (gate A) y
  la tabla spec↔tests (gate D).

## A.5 Paso 5 — Cierre del criterio 10 (con el owner)

- El RTL ya es sintetizable (sin B1/B2); el owner corre
  `synth/fase3_synth.tcl` (xcvu9p, DW=32, periodo 3,103 ns) y pega
  `timing_impl.txt` (WNS/TNS) y `util_impl.txt` (LUT/FF/BRAM/URAM) en
  `synth/reports/`.
- Validación estática sin Vivado: `scripts/verify/synth_check.py` (10/10).
- Cierre: `/grade` de la campaña (y re-grade de fase 3 si hace falta).

## A.6 Definición de "done" de la sesión

- [ ] Spec de campaña commiteada (`specs/fase3-uram/spec.md` + gherkin).
- [ ] Rojos de SEC-URAM-01/02/03 evidenciados (TDD).
- [ ] RTL del book sobre URAM + sonda serializada + pipeline de niveles,
      con las 9 suites verdes y 22+ mutantes muertos.
- [ ] Latencia re-medida ≤ 45 ciclos de media (JSON determinista regenerado).
- [ ] `verify-report.md` + veredicto `/grade`.
- [ ] Artefacts de síntesis listos para el run del owner (o run pegado si la
      máquina del owner está disponible).

---

# Parte B — Lo aprendido en la sesión del 2026-08-14

## B.1 Lección mayor: el parámetro efectivo no es el default del módulo

El hallazgo que destapó todo: `itch_chain.sv` declara su **propio** `QB=128`
y lo pasa al parser con `.QB(QB)` — el default `QB=64` que cambiamos en
`itch_parser.sv` **no tenía efecto sobre la cadena** (la latencia medida era
idéntica, 72,191, incluso con builds limpios).

- **Síntoma engañoso**: dos builds limpios de `sim_build_chain` con fuentes
  supuestamente distintas dieron latencias idénticas a 3 decimales. La
  conclusión precipitada ("mi teoría del backlog es falsa") era errónea; la
  real era "el parámetro que creo cambiar no es el que elabora".
- **Cómo se resolvió**: instrumentando señales internas con cocotb (un test
  de diagnóstico que lee `dut.u_parser.qn` y el estado por ciclo y vierte el
  trazo a JSON). El trazo mostraba `qn > 64` (69, 73...): la cola superaba
  el QB que creíamos → el binario usaba 128. Luego el `git diff` del binario
  (constante `0x7f - qn`, shift de 1024 bits) confirmó el origen.
- **Regla operativa**: en fase 3 los parámetros de campaña viven en el top
  (`itch_chain.sv`) y en la línea `-G` del Makefile (ya documentado para
  `-G`; ahora también para los defaults del top). Antes de medir un cambio de
  parámetro, verificar qué módulo elabora el parámetro efectivo.

## B.2 Lección de latencia: el modelo del backlog estacionario

La latencia wire→BBO NO es el tiempo de procesamiento del mensaje (~14-19
ciclos teóricos) sino **backlog + procesamiento**:

- La entrada fluye a 4 B/ciclo mientras `qn+4 ≤ QB`; el drenaje del parser
  solo ocurre en ST_CAP (todo el mensaje de golpe, ~38 B cada 14 ciclos =
  2,7 B/c). Entrada > drenaje ⇒ la cola se fija en QB y cada mensaje espera
  ~QB/16 mensajes de turno. Modelo: `latencia ≈ (QB/4)/7,7 × 11 + 16`.
- Verificado empíricamente: QB 128→64 da media **69,26 → 42,40 ciclos**
  (214,9 → 131,5 ns a 322,265625 MHz), p99 77→47, min 27→27 — **1,63×** con
  la corrección bit a bit intacta (CHAIN-01: 30.729 eventos, cross=0,
  anomaly=671, gaps=0).
- El min (27) es la cola vacía (primer add del día); el steady state es el
  backlog.
- Régimen de stalls: el tramo probado 4×A/U pasa de 0 a ~15 stalls acotados
  con QB=64 (QB≥88 conservaría 0 con solo 1,4× de ganancia). El criterio 1
  habla de "sin backpressure sostenida": feed infinito back-to-back está
  documentado fuera de alcance (LIN-01) — el diseño es correcto tal cual.
- Implicación para el diseño: bajar la latencia SIN tocar el contrato se
  hace por la cola (ya hecho) y luego por el **recorte del Anexo A** (w2/w3
  de ts que el book descarta): ~2 ciclos/mensaje + ~15% de palabras.

## B.3 Lección de técnica: la traza interna vale más que la teoría

El flujo que funcionó: hipótesis → **experimento con build limpio** (dio
falso negativo) → **instrumentación de señales internas** (verdad) → veredicto
del binario elaborado. Para la próxima sesión:

- El test de diagnóstico (`dbg_qn`-style) es la herramienta estándar: leer
  `dut.<instancia>.<señal>` por jerarquía (cocotb lo permite; ojo: los
  nombres internos son los del RTL, p. ej. `out_valid` no existe como puerto —
  es `m_axis_tvalid`).
- No borrar los instrumentos: el de esta sesión se descartó; conviene
  conservar un `tools/dbg_trace_chain.py` o similar reutilizable.
- Los bins de Verilator se pueden inspeccionar (constantes elaboradas en el
  C++ generado) para confirmar QUÉ parámetros se compilaron.

## B.4 Lección de síntesis: el criterio 9 pasó por documentación, no por código

La auditoría reveló que el order book actual **no es sintetizable**:

- B1: 65.536 registros planos con sonda combinacional de índice variable
  (muxes 65.536:1 → ~22K LUTs/bit × ~330 bits → millones de LUTs; la VU9P
  tiene 1.182K). Ni siquiera es un problema de timing: es estructural, y
  bloquea la inferencia de BRAM/URAM (la lectura no es síncrona).
- B2: `level_add` O(P) en una pasada combinacional ≈ 6-8 ns > 3,103 ns.
- B3: barrel shifter 1024 bits ≈ 1,5-2 ns (bajado a 512 con QB=64).
- **Lección de proceso**: un criterio de spec que exige "lecturas
  registradas" debe tener un test que lo pinche (SEC-URAM-01 en el plan),
  no solo una auditoría de código y un writeup. La campaña URAM lo corrige.

## B.5 Lección de rigor: los tests acotados siguen cazando regresiones

La enmienda LIN-01/P32-02 ("0 stalls" → "stalls ≤ 24") no debilita el
regimiento: el límite está justificado por la medición (~15 en el tramo) y
sigue matando regresiones groseras (un drenaje roto dispara los stalls por
encima del límite). La regla: todo límite en un test debe venir de una
medición con evidencia, y el comentario debe citarla.

## B.6 Números de referencia (para no re-descubrirlos)

| Métrica | Antes (QB=128) | Después (QB=64) | Dónde |
|---|---|---|---|
| Latencia total media | 69,26 ciclos (214,9 ns) | 42,40 (131,5 ns) | `latency_dw32.json`, `latencia.md` |
| p99 / p50 / min | 77 / 68 / 27 | 47 / 42 / 27 | idem |
| A (add) media | 72,19 | 45,39 | idem |
| D / X media | 66,62 / 67,94 | 39,86 / 40,66 | idem |
| Eventos bit a bit | 30.729 | 30.729 (cross 0, anomaly 671, gaps 0) | CHAIN-01 |
| Barrel shifter | 1024 bits | 512 bits | `itch_parser.sv` |
| Ciclos por mensaje (DW=32) | parser 7+body_w; book 6+body_w | igual | análisis |

## B.7 Estado del repo al cerrar la sesión (para retomar sin fricción)

- Último commit: `9c9735f` — "fix(fase3): QB de la cadena 128→64...".
- Nuevos: `docs/writeup/revision-exhaustiva-2026-08-14.md` (el análisis
  completo), addendum iteración 6 en `specs/fase3-optimizacion/spec.md`,
  post-grade 6bis en `verify-report.md`.
- Suites: fase1 19/19, fase2 14/14, phase3 25/25, golden 32/32, lint limpio.
- Pendientes conocidos: criterio 10 (externo, Vivado del owner), schema CME
  MDP3 bloqueado en esta red (fase 4), `verible-verilog-lint` no instalado
  (gate C, NO EJECUTADO — puede instalarse en la próxima sesión para cerrar
  el único gate pendiente del ciclo).
- Gotcha operativo añadido: los parámetros de fase 3 se sobrescriben desde
  el top (`itch_chain.sv`) — ver `docs/DESARROLLO.md` §Gotchas.