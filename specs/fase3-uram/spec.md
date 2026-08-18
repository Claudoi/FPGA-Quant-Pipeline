# fase3-uram (fase 3 del maestro — iteración URAM y cierre del criterio 10)

## Goal

Hacer sintetizable el order book y cerrar el **criterio 10 (322,265625 MHz)**
del maestro: convertir la tabla de órdenes de registros planos (NSLOT=65.536
con sonda combinacional paralela — no sintetizable a 3,103 ns, bloqueadores
B1/B2 medidos en `docs/writeup/revision-exhaustiva-2026-08-14.md`) en un
diseño **URAM con sonda serializada y pipeline de niveles registrado**, sin
perder NI UN BIT de la corrección verificada en fases 2-3 (30.729 eventos BBO
bit a bit) ni la latencia actual (~42 ciclos de media; objetivo ≤ 45).

Además, por decisión del owner (2026-08-14): **recorte obligatorio del Anexo A
de 32 bits** (eliminar las words w2/w3 del timestamp que el book descarta) —
cambio de contrato explícito del criterio 1 de fase 3 que baja ~2 ciclos/
mensaje y ~15 % de palabras del stream interno.

## Scope

**In scope:**

- **Recorte del Anexo A de 32 bits**: nuevo layout `w0={type[7:0],
  locate[15:0], len[7:0]}`, `w1=msg_idx[31:0]`, `w2..=cuerpo MSB-first` (sin
  w2/w3 de ts). Parser y book alineados; el sanity `m_idx` del book se captura
  de w1 igual que hoy. El Anexo A de 64 bits NO se toca (regresión fases 1/2).
- **Tabla de órdenes en URAM**: los 5 arrays `o_valid/o_ref/o_side/o_price/
  o_qty` se consolidan en un array único de NSLOT×86 bits (65.536×86 ≈ 20
  URAM del XCKU3P) con **lectura síncrona registrada** (dirección → dato a los
  1 ciclo), nunca indexación combinacional. Reset por invalidación de slots
  (patrón que no bloquea la inferencia: jamás reset global del array).
- **Sonda serializada con prefetch**: `lookup_ref`/`first_empty` consumen
  ≤ 1 slot/ciclo; el probe de hasta PROBE=8 slots tarda ≤ 8+2 ciclos; el
  primer read del grupo de hash del mensaje en curso se emite **durante
  ST_BODY** (el hash se conoce antes de ST_APPLY) para no añadir latencia al
  caso con body ≥ 4 words (diseño documentado en `docs/writeup/uram.md`).
- **Pipeline del mantenimiento de niveles** (`level_add`): el reordenamiento
  O(P) actual en una pasada combinacional (~6-8 ns, bloqueador B2) se parte
  en etapas registradas; cada operación consume ≤ 2-3 ciclos extra en
  ST_APPLY/ST_UADD; invariantes de fase 3 intactos (nivel vacío no existe,
  lista ordenada best-first, jamás precio stale ni cantidad envuelta).
- **Regresión completa**: 30.729 eventos BBO bit a bit + depth 640 bits +
  anomalías/cross/gaps idénticos (CHAIN-01) con el layout recortado; suites
  completas vigentes de fases 1, 2 y 3 verdes, sin fijar un recuento obsoleto.
- **Latencia**: histograma wire→BBO por tipo regenerado con el layout nuevo;
  media ≤ 45 ciclos (mejorable a ~35-40 con el recorte del Anexo A),
  determinismo de SEC-LAT-01 conservado.
- **Artefactos de síntesis (criterio 10)**: constraints 3,103 ns + script tcl
  (part `xcku3p-ffva676-2L-e`, top `itch_chain`, DW=32) actualizados si el
  RTL nuevo cambia puertos o estructura de memoria; `scripts/verify/synth_check.py`
  10/10; WNS ≥ 0 del run externo del owner en `synth/reports/`.

**Out of scope (non-goals):**

- Cambiar la semántica del book (es la de fase 2/3, replicada del golden).
- Cambiar el layout del Anexo A de 64 bits (intocable).
- El Anexo A de 32 bits pierde el timestamp **solo** porque ningún consumidor
  lo usa; si en el futuro una etapa lo requiriera, es una campaña nueva.
- Cuckoo/robin-hood hashing (probing lineal basta: carga pico 0,4 %).
- Cierre de timing real en Vivado (externo al owner, como en fase 3).
- Fase 4 (CME MDP3).

**Radio medido (2026-08-14):** el recorte del Anexo A de 32 bits toca
`rtl/parser/itch_parser.sv` (ST_TS, contador `hw`, 3 words → 1 word de
cabecera a DW=32), `rtl/orderbook/orderbook.sv` (ST_TS, `hrem` 3→1),
`verification/testbenches/orderbook/test_orderbook.py` (helper `anexo_words`,
2 apariciones — oráculo compartido por fase 2 y phase3),
`verification/testbenches/phase3/{test_orderbook32,test_depth32,test_hash32,
test_hard32}.py` (2 apariciones cada uno), `test_parser32.py`, `test_lat32.py`,
`verification/vectors/latency/latency_dw32.json` (regenerar) y el contrato del
criterio 1 de fase 3 (`specs/fase3-optimizacion/spec.md`, líneas 24-25).
La tabla hashada a URAM toca solo `rtl/orderbook/orderbook.sv` + sus tests de
fase 3 (sin cambio de puertos del top: el contrato externo del book no cambia
en esta campaña).

## Constraints

- **Familia/part:** UltraScale+ **xcku3p-ffva676-2L-e** (48 URAM ≈ 13,8 Mb,
  162.720 CLB LUT, 360 BRAM36K — corregido 2026-08-18 con el dato de Vivado;
  la «360 URAM» original era el BRAM). Retarget desde el VU9P por decisión 002
  (`docs/decisiones/002-retarget-kintex-xcku3p.md`): el XCKU3P está soportado
  en Vivado ML Standard (gratuito); la inferencia real de la tabla (32 URAM288
  con `(* ram_style = "ultra" *)`) cabe con margen 32/48 ≈ 1,5×.
- **Frecuencia:** 322,265625 MHz (periodo 3,103 ns) — la razón de ser de la
  campaña es que el RTL RESISTA esa ruta, no solo la simulación.
- **URAM:** lectura registrada obligatoria (1 ciclo de latencia);
  inferencia solo con el patrón síncrono. Sin reset global del array de
  memoria (mataría la inferencia).
- **Line-rate:** el contrato del criterio 1 de fase 3 se mantiene (1 palabra/
  ciclo sin backpressure sostenida; stalls acotados ≤ 24 en el tramo probado).
- **Determinismo:** mismo stream → misma secuencia de BBO **y depth**, bit a
  bit igual al golden, con y sin backpressure.
- **Latencia:** media wire→BBO ≤ 45 ciclos (línea base medible actual: 42,40
  con QB=64; el recorte del Anexo A la debe bajar, no subir).
- **Semántica:** mismas anomalías, mismo `anomaly_count` (671 en el feed del
  subset), mismos cross (0) y mismos errores señalizados que fase 3.

## Superficie y amenazas

**Un puerto nuevo de framing en `itch_chain`:** `s_axis_tkeep[DW/8-1:0]`,
heredado de fase 1 para marcar los bytes válidos del payload UDP. `orderbook`
no cambia de puertos; el contrato de salida
(`bbo_*`, `depth_*`, `cross/anomaly/error`) sigue siendo el de fase 3.

**Casos de abuso del dominio** (cada uno con escenario en Gherkin):

- **Lectura no registrada de la tabla**: el probe indexa combinacionalmente
  (patrón de URAM roto) sin que la simulación funcional lo note. — SEC-URAM-01
  pinza el retardo estructural (dato válido exactamente 1 ciclo después de la
  dirección; probe de 1 slot/ciclo) y `synth_check.py` prohíbe cualquier lectura
  directa `o_mem[pr_*]` que eluda `rd_data`.
- **Prefetch desacoplado**: el grupo de hash no se precarga en ST_BODY y el
  lookup serializado entra en ST_APPLY → latencia y throughput peores. —
  SEC-URAM-02 (colisión forzada, K=20, mismo resultado y mismo número de
  ciclos de lookup que el diseño actual).
- **Pipeline de niveles con burbuja**: escrituras de `level_add` partidas en
  dos ciclos que dejan precio stale o cantidad fantasma (escenario INV-OV-01
  de fase 3) o que rompen el invariante «nivel vacío no existe» (mutante
  DP-EMPTYSTALE/DP-TOPNCOUNT). — SEC-URAM-03.
- **Recorte del Anexo A desalineado**: parser emite 2 words y el book espera 3
  (o viceversa) → CHAIN-01 diverge y `m_idx` sane se corrompe. — ANX-01/ANX-02
  + CHAIN-01.
- **Semántica del hash cambiada**: tabla en URAM que altera las anomalías
  (probe agotado vs ref ausente) o el U atómico (INV-U-01). — SEC-HASH-01/02,
  INV-U-01 de fase 3 en regresión.
- **Reset del array global**: patrón `always @(posedge clk) for (i...) mem[i]
  <= 0` que mata la inferencia URAM sin romper la simulación. — guardarraíl:
  auditoría de patrón en `synth_check.py` (criterio 7) + revisión de código.

**Qué se arriesga del maestro:** el **cierre de timing a 322 MHz** (criterio
10, único criterio FAIL del grade de fase 3) y la **latencia determinista**
por el alargamiento del apply multi-ciclo.

## Reuso

- `rtl/orderbook/orderbook.sv` — se **refactoriza** internamente (memoria +
  FSM de sonda + pipeline de niveles); puertos y parámetros efectivos
  conservados (SLOT=16, PROBE=8, ND=5, K=19, P=32, NSYM=20).
- `rtl/parser/itch_parser.sv` — conserva el recorte de ST_TS y añade el contrato
  de bytes válidos en la captura/cola de entrada; el formato de salida no cambia.
- `rtl/itch_chain.sv` — propaga `s_axis_tkeep` al parser; el enlace normalizado
  parser→book y los parámetros efectivos no cambian.
- `golden_model/src/book.py` / `golden_model/itch/messages.py` — oráculos
  únicos; el layout recortado se define desde el oráculo, NUNCA con offsets a
  mano nuevos en RTL.
- `verification/testbenches/phase3/*` — suites y helpers existentes (25 tests)
  son el ariete de la regresión; el área nueva importa vía `sys.path`, no
  copia (regla de partición del README de testbenches).
- `scripts/verify/mutate_orderbook.py` — runner del gate E extendido con los
  mutantes de la sonda/pipeline nuevos (PIPE-SKIP-STAGE, URAM-NO-PREFETCH,
  URAM-COMB-INDEX, LV-STALE-STAGE).

## Criterios de aceptación (Definition of Done)

1. [ ] **Anexo A de 32 bits recortado**: parser y book emiten/consumen
     `w0={type,locate,len}`, `w1=idx`, `w2..=cuerpo` bit a bit contra el
     oráculo (edit explícito del criterio 1 de fase 3); el peor caso sigue
     aceptándose 1 palabra/ciclo con stalls acotados.
     — Gherkin: `fase3-uram.feature` §ANX-01, §ANX-02
2. [ ] **Tabla en URAM**: la tabla de órdenes es un único array NSLOT×86 bits
     con lectura síncrona registrada; ningún path indexa la memoria
     combinacionalmente (SEC-URAM-01 pinza el retardo de 1 ciclo); reset por
     invalidación sin patrón anti-inferencia.
     — Gherkin: §SEC-URAM-01
3. [ ] **Sonda serializada + prefetch**: lookup/first_empty a ≤ 1 slot/ciclo
     por lecturas registradas; probe completo ≤ 8+2 ciclos; el grupo de hash
     se precarga durante ST_BODY (SEC-URAM-02) y la semántica del hash de
     fase 3 es EXACTA (mismas anomalías, tabla llena → error, U atómico).
     — Gherkin: §SEC-URAM-02, regresión §SEC-HASH-01/02/03, INV-U-01
4. [ ] **Pipeline de niveles**: `level_add` en etapas registradas; burbujas
     ≤ 2 ciclos por operación; invariantes de fase 3 intactos (sin precio
     stale, sin fantasma, sin cantidad envuelta).
     — Gherkin: §SEC-URAM-03 + regresión INV-OV-01, DP-01/02, SEC-DP-01
5. [ ] **Regresión total**: suites completas vigentes de fases 1, 2 y 3 verdes
     con el RTL nuevo; CHAIN-01: 30.729 eventos BBO bit a bit + depth 640
     bits, anomaly=671, cross=0, gaps=0 con el layout recortado.
     — Gherkin: §REG-01, §CHAIN-01
6. [ ] **Latencia**: histograma por tipo regenerado (JSON determinista, doble
     ejecución idéntica); **media ≤ 45 ciclos** en la cadena DW=32.
     — Gherkin: §SEC-URAM-04
7. [ ] **Criterio 10 (síntesis)**: `synth/` con constraints 3,103 ns + tcl
     coherentes con el RTL nuevo; `scripts/verify/synth_check.py` 10/10
     (incl. auditoría del patrón de memoria síncrona y sin reset global);
     WNS ≥ 0 y utilización (LUT/FF/BRAM/**URAM**) del run del owner pegados
     en `synth/reports/`.
8. [ ] Lint: Verilator `--lint-only -Wall` limpio en los 3 módulos a DW=32
     y DW=64 (gates B/C de verify).
     — Gates B/C

## Verificación

| Criterio | Cómo se prueba |
|---|---|
| 1 | cocotb `ANX-01` (words 32-bit vs oráculo recortado) + `ANX-02` (peor caso, stalls ≤ 24) + CHAIN-01 end-to-end |
| 2 | `SEC-URAM-01`: pinza estructural — dirección emitida → dato válido 1 ciclo después; probe a 1 slot/ciclo (contador de ciclos de la sonda en el driver) |
| 3 | `SEC-URAM-02`: colisión forzada (K=20, 9ª ref del mismo hash) con prefetch; mismas anomalías que fase 3 (bit a bit) |
| 4 | `SEC-URAM-03`: 33 adds + D (escenario INV-OV-01) sin fantasma y con burbuja ≤ 2; DP-01/02 bit a bit |
| 5 | suites fase 1/2/3 completas + `sim-chain` (CHAIN-01 bit a bit) |
| 6 | `sim-lat` regenerado: SEC-LAT-01 determinista + media ≤ 45 → JSON nuevo en `verification/vectors/latency/` |
| 7 | tcl/constraints actualizados + `python3 scripts/verify/synth_check.py` 10/10; informe del owner pegado |
| 8 | `verilator --lint-only -Wall` a DW=32/DW=64 sobre orderbook, itch_parser, itch_chain |

Régimen completo: skill `verify` (gates A-G). Gate E: `mutate_orderbook.py`
extendido (mutantes URAM-COMB-INDEX, URAM-NO-PREFETCH, PIPE-SKIP-STAGE,
LV-STALE-STAGE + los 22 existentes re-verificados contra el RTL nuevo).
Gate F: espejo Gherkin nuevo (`specs/gherkin-espejos.json` →
`verification/testbenches/uram`). Gate G: G0 (vectores solo en
`verification/vectors/`), G5 adversarial sobre el pipeline de niveles y la
sonda al cerrar la campaña.

**Contratos sin gate** — invariantes que pueden romperse con suite y lint en
verde:

1. **URAM realmente inferida**: la simulación (Verilator) no distingue un
   registro plano de una URAM; el guardarraíl es el patrón síncrono auditable
   (`synth_check.py`) + la inferencia del synth del owner (criterio 7).
2. **Layout recortado definido en un solo lugar**: el Anexo A de 32 bits
   nuevo existe solo en el oráculo (`anexo_words`/`message_oracle`); cualquier
   offset escrito a mano en RTL o en el test sin pasar por el oráculo = FAIL.
3. **Semántica de anomalías del hash**: la tabla URAM no puede cambiar qué se
   cuenta como anomalía vs error (bit a bit contra fase 3 en el mismo feed).

## Loop

Stop limit: **5 iteraciones** (las 4 del plan `plan-proxima-sesion-uram.md`
+ 1 por el recorte del Anexo A, ahora obligatorio). Cadencia:
build → verify → grade encadenados. Orden sugerido: iter 1 (recorte del Anexo
A + regresión: aislar el cambio de contrato) → iter 2 (memoria URAM + sonda
serializada + prefetch) → iter 3 (pipeline de niveles) → iter 4 (latencia
re-medida + synth artifacts + synth_check) → iter 5 (mutación extendida +
revisión adversarial G5 + cierre). Al agotar el límite con criterios en FAIL,
escala al owner.
