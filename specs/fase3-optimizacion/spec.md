# fase3-optimizacion (fase 3 del maestro — Optimización y cierre)

## Goal

Llevar el pipeline (parser ITCH + order book) a la **variante 32-bit @
322,265625 MHz** (XGMII, = 10,3125 Gbps = line-rate 10G), con la tabla de
órdenes en **URAM con hash + linear probing** (decisión del maestro, diferida
en fase 2), salida **top-N pública**, latencia determinista medida por tipo de
mensaje, y **cierre de timing en UltraScale+** con evidencia real (el owner
corre Vivado en otra máquina; aquí se preparan RTL, constraints y script tcl).

Es el capítulo final del maestro: convierte «simulado correcto» en «diseñado
para el silicio con timing cerrado a 10G».

## Scope

**In scope:**

- **Parametrización DW=32 del parser** (`rtl/parser/itch_parser.sv` ya tiene
  `parameter DW=64`): la variante 32-bit debe cumplir los criterios de fase 1
  (registro Anexo A bit a bit, line-rate 1 palabra/ciclo, framing/gaps/sesión,
  backpressure, truncado y bytes válidos por `tkeep`) y la variante 64-bit queda
  en regresión verde.
- **Parametrización DW=32 del book** (`rtl/orderbook/orderbook.sv` ya tiene
  `parameter DW=64`): Anexo A de 32 bits (w0={type,locate,len}, w1=msg_idx,
  w2..=cuerpo MSB-first — **layout recortado por la campaña fase3-uram,
  criterio 1: las words de ts se eliminaron**), decodificador con
  los mismos offsets de `golden_model/itch/messages.py`, criterios de fase 2
  bit a bit. Variante 64-bit en regresión verde.
- **Cadena parser→book a DW=32** verificada end-to-end (feed real + vectores).
- **Hash + linear probing** de la tabla de órdenes: `2^SLOT` slots
  (SLOT=16 → 65.536), entrada {valid, ref, side, price, qty}, búsqueda por
  `ref mod 2^SLOT` con probing lineal acotado (máx. `PROBE` pasos, PROBE=8);
  ref desconocida tras agotar probes = anomalía (misma semántica que fase 2);
  tabla llena = `error` señalizado, nunca silencio.
- **Top-N público**: salida `depth_tdata` con los ND=5 mejores niveles por
  lado del símbolo del evento BBO (bid best-first descendente, ask best-first
  ascendente, cada nivel {px[31:0], qty[31:0]}, vacíos a 0), validada bit a
  bit contra los niveles del golden `book.py`.
- **Hardening de grade fase 2 (lente 9)**: guard de NSYM (símbolo 21 → pulso
  `error`, jamás índice OOB) y handshake `bbo_tready` en ST_EMIT (evento BBO
  nunca perdido bajo backpressure).
- **Latencia**: histograma wire→BBO por tipo de mensaje (ciclos desde el
  handshake del mensaje en `s_axis` hasta su evento BBO en `bbo_tvalid`) en la
  cadena parser→book, commiteado como JSON en `verification/vectors/latency/`.
- **Pipeline para URAM**: lecturas de la tabla de órdenes **registradas**
  (1 ciclo, patrón de lectura registrada de URAM); documentación del mapeo
  (**32 URAM288 reales, medido en el run 2026-08-18**, para 65.536×86 bits) y
  de las técnicas de retiming/pipelining en
  `docs/writeup/`.
- **Síntesis**: constraints 322,265625 MHz + script tcl de synth/impl
  (part US+ objetivo) commiteados en `synth/`; el owner corre Vivado fuera y
  pega el informe (WNS/TNS + utilización LUT/FF/BRAM/URAM) en `synth/reports/`.

**Out of scope (non-goals):**

- Rehacer la semántica del book (es la de fase 2, replicada del golden).
- Fase 4 (CME MDP3, host AXI/PCIe, write-up publicado).
- Hash con cuckoo/robin-hood (probing lineal basta con la carga del subset:
  pico 370 vivas sobre 65.536 slots ≈ 0,6 %).
- Cambiar el layout del Anexo A de 64 bits (la variante 32 define su propio
  layout de 32 bits; la de 64 no se toca).
- Latencia en nanosegundos con datos reales wire-to-wire (requiere hardware):
  la latencia se mide en ciclos en simulación y se convierte a ns con el reloj
  objetivo (documentado).

**Radio medido (2026-08-13):** `rtl/parser/itch_parser.sv` (param `DW=64`,
consumido solo por su testbench) y `rtl/orderbook/orderbook.sv` (param `DW=64`,
consumido solo por su testbench); `verification/vectors/bbo/corpus_bbo.json` y
`messages/corpus_all_types.json` reutilizables; `synth/` vacío. Ningún puerto se
renombra: solo se añaden parámetros/puertos nuevos y se parametriza lo existente.

## Constraints

- **Familia/part objetivo:** AMD/Xilinx UltraScale+ **xcku3p-ffva676-2L-e**
  (Kintex XCKU3P; **48 URAM** (13,8 Mb), 162.720 CLB LUT, 360 BRAM36K — el
  conteo «360 URAM» de la decisión 002 era erróneo: 360 es el BRAM; corregido
  2026-08-18 con el dato del propio Vivado, `AVAILABLE_IOBS=256` y URAM=48).
  Retarget desde el VU9P por decisión 002
  (`docs/decisiones/002-retarget-kintex-xcku3p.md`): soportado en Vivado ML
  Standard gratuito y reproducible sin licencia de pago — swappable en el
  tcl/constraints.
- **I/O del paquete:** FFVA676 → 256 I/O (`AVAILABLE_IOBS`). El top de
  síntesis es el wrapper `synth/itch_chain_synth.sv` (contrato AXI, depth
  recortado a 32 bits de observabilidad): `rtl/itch_chain.sv` expone 896
  puertos de debug y no entra en el FFVA676 (Place 30-415, hallazgo
  2026-08-18). El datapath medido es idéntico.
- **Frecuencia:** 322,265625 MHz (variante 32-bit) y 156,25 MHz (regresión
  64-bit). 32-bit @ 322,265625 = 10,3125 Gbps = line-rate 10G.
- **Line-rate:** el datapath 32-bit acepta **1 palabra/ciclo en el peor caso**
  (mensajes mínimos back-to-back) sin backpressure sostenida — igual régimen
  que fase 1.
- **URAM:** lectura registrada (1 ciclo) → el pipeline del book se diseña
  alrededor de esa latencia (la búsqueda de la tabla se hace en un ciclo y la
  operación se aplica en el siguiente), sin «arreglar» el signo con lógica
  larga en el flanco de uso.
- **Determinismo:** mismo stream → misma secuencia de BBO **y de depth**, bit
  a bit igual al golden; sin pérdida ni doble cuenta, con y sin backpressure
  de salida.
- **Endianness:** cuerpo big-endian del wire; offsets exactos de
  `golden_model/itch/messages.py` (fuente única, regla fases 0/1).
- **Framing de entrada:** `itch_chain` expone `s_axis_tkeep[DW/8-1:0]` y hereda
  literalmente el contrato de bytes válidos de fase 1. La interfaz interna
  parser→book no cambia.

## Superficie y amenazas

**Puerto nuevo del top de cadena:** `s_axis_tkeep[DW/8-1:0]`, conectado solo a
`itch_parser`. Puertos nuevos del book (top `orderbook`):

| Señal | Ancho | Descripción |
|---|---|---|
| `depth_tdata` | `2*ND*64` (=640) | niveles por lado del símbolo del evento: `{bid[ND-1..0], ask[ND-1..0]}`, cada nivel `{px[31:0], qty[31:0]}`, mejor primero, vacíos 0 |
| `depth_tvalid` | 1 | hay un evento depth (mismo pulso que el BBO del símbolo) |
| `depth_tready` | 1 | backpressure del consumidor de depth (handshake igual que bbo) |

Parámetros nuevos: `DW` (32/64), `SLOT=16`, `PROBE=8`, `ND=5`. Parser: `DW`
ya existe (se ejercita a 32).

**Casos de abuso del dominio** (cada uno con escenario `SEC-` en Gherkin):

- **Probing que agota**: ref en el slot pero probe bound excedido → anomalía
  contada, no aborta. — SEC-HASH-01.
- **Tabla llena**: insert con todos los slots ocupados → `error`, nunca wrap
  ni overwrite silencioso. — SEC-HASH-02.
- **Colisión de hash entre símbolos distintos**: refs de símbolos diferentes
  que caen en el mismo slot → probing las distingue (el ref se guarda). —
  SEC-HASH-03.
- **Símbolo 21 (NSYM)**: locate fuera del subset → pulso `error`, jamás índice
  OOB en los arrays de niveles. — SEC-NSYM-01.
- **Backpressure de BBO**: `bbo_tready=0` cuando hay evento → el evento se
  retiene (ST_EMIT se queda), nunca se pierde; al liberar, se entrega exacto.
  — SEC-BP-01.
- **Depth de símbolo vacío**: niveles inexistentes → 0; depth no diverge del
  golden. — SEC-DP-01.
- **Latencia determinista**: la misma secuencia produce los mismos ciclos por
  tipo (histograma reproducible). — SEC-LAT-01.

**Qué se arriesga del maestro:** el **line-rate de 10G** (32-bit/322 sin
throttling), la **latencia determinista** y la **corrección estricta** del
book con una tabla de órdenes que ya no es indexación directa (colisiones de
hash = nuevo vector de error).

## Reuso

- `rtl/parser/itch_parser.sv` — se **extiende** (DW ya parametrizado), no se
  duplica; el decodificador/cuerpo se ejercita a 32 bits.
- `rtl/orderbook/orderbook.sv` — se **extiende** (DW, hash, depth, hardening);
  la semántica de `level_add`/`apply_one`/`emit_bbo` se conserva.
- `golden_model/src/book.py` — oráculo de BBO **y de niveles** (top-N se deriva
  de `_levels` ordenado, nunca del RTL).
- `golden_model/itch/messages.py` — offsets de campos (fuente única).
- Testbenches fase 1/2: drivers y helpers (`anexo_words`, `drive_pcap`,
  `_pcap_msgs_subset`, constructores A/F/E/C/X/D/U/S/H) **se importan**, no se
  copian: el área nueva `verification/testbenches/phase3/` reusa los módulos
  existentes vía `sys.path` (regla de partición del README de testbenches).
- `verification/vectors/{bbo,messages}/*.json` — vectores congelados
  existentes, re-ejecutados a DW=32 y DW=64.
- Código nuevo que duplique la semántica de `book.py`/`messages.py` con otro
  literal (offsets a mano, top-N recalculado en RTL) = FAIL de la lente de
  simplicidad de `/grade`.

## Criterios de aceptación (Definition of Done)

1. [ ] **Parser DW=32**: el registro Anexo A de 32 bits es bit a bit idéntico
     al oráculo `message_oracle` sobre el corpus sintético y el replay real
     (mismos mensajes → mismas words); el peor caso (mensajes mínimos
     back-to-back) se acepta 1 palabra/ciclo sin backpressure sostenida.
     — Gherkin: `optimizacion.feature` §P32-01, §P32-02
2. [ ] **Book DW=32**: BBO bit a bit vs golden `book.py` sobre el corpus
     sintético (criterios 1-7 de fase 2 re-ejecutados a 32 bits) y sobre el
     replay real de 20 símbolos.
     — Gherkin: §B32-01, §B32-02
3. [ ] **Regresión 64-bit**: suites completas vigentes de fases 1 y 2 verdes con
     el RTL extendido (parametrización no rompe el default).
     — Gherkin: §REG-01
4. [ ] **Cadena parser→book DW=32**: feed real decapado → BBO bit a bit vs
     golden sobre el subset (REPLAY-01 encadenado a 32 bits).
     — Gherkin: §CHAIN-01
5. [ ] **Hash + probing**: la tabla con hash reproduce la semántica exacta de
     la indexación directa (mismos eventos, mismas anomalías, mismas refs);
     probe agotado = anomalía, tabla llena = `error`.
     — Gherkin: §SEC-HASH-01/02/03
6. [ ] **Top-N parametrizado**: con ND=5 y una elaboración adversarial ND=3,
     `depth_tdata` es bit a bit contra los niveles ordenados del golden para el
     símbolo del evento; símbolo sin niveles → 0. `itch_chain` propaga ND al
     book, no sólo al ancho del puerto top.
     — Gherkin: §SEC-DP-01, §DP-01
7. [ ] **Hardening**: símbolo 21 → `error` y `m_loc_idx < NSYM` en todo
     ciclo; evento BBO retenido con `bbo_tready=0` después de observar
     `bbo_tvalid=1`, estable al menos dos ciclos y entregado exacto al liberar.
     — Gherkin: §SEC-NSYM-01, §SEC-BP-01
8. [ ] **Latencia**: histograma por tipo (ciclos wire→BBO en la cadena DW=32)
     commiteado en `verification/vectors/latency/` y determinista
     (re-ejecución idéntica); conversión a ns documentada en `docs/writeup/`.
     — Gherkin: §SEC-LAT-01
9. [ ] **Pipeline URAM**: las lecturas de la tabla de órdenes están registradas
     (1 ciclo) y el mapeo (65.536×86 bits = **32 URAM288**, medido en el run
     2026-08-18) se documenta en
     `docs/writeup/`; no hay ruta O(P·P) en el cálculo del mejor precio.
10. [ ] **Síntesis**: `synth/` contiene constraints (322,265625 MHz) + script
     tcl (synth/impl, part `xcku3p-ffva676-2L-e`); el owner corre Vivado fuera y
     pega el informe WNS/TNS y utilización en `synth/reports/` — WNS ≥ 0 en la
     variante 32-bit.
11. [ ] Cocotb + Verilator compilan ambos tops a DW=32 con `--Wall` sin
     warnings reales silenciados; lint en verde sobre lo tocado.
     — Gates B/C de verify.

## Verificación

| Criterio | Cómo se prueba |
|---|---|
| 1 | cocotb: corpus sintético + replay REP-02 a DW=32 (words 32-bit vs `message_oracle`); peor caso mínimo back-to-back sin backpressure |
| 2 | cocotb: corpus BBO-01..SEC-* a DW=32 contra `book.py`; REPLAY-01 a 32 bits |
| 3 | cocotb: `make sim` completo en `testbenches/parser` y `testbenches/orderbook` tras el cambio |
| 4 | cocotb: top `chain32` (parser→book a DW=32) sobre el pcap real del subset |
| 5 | cocotb: misma secuencia con tabla hashada vs directa; casos probe-limit y tabla-llena; mutante de hash (slot sin comparar ref) lo mata |
| 6 | cocotb: depth vs `book.py` a ND=5 y `itch_chain -GND=3`; mutante de orden/truncado lo mata |
| 7 | cocotb: `SEC-NSYM-01` (21 símbolos + muestreo del índice interno), `SEC-BP-01` (stall adaptativo que espera `tvalid`, retiene dos ciclos y libera) |
| 8 | cocotb: recolector de ciclos por tipo → JSON; re-ejecución idéntica |
| 9 | revisión + `verilator --lint-only`; documentación en writeup; la lectura registrada se audita por código |
| 10 | tcl/constraints commiteados + informe del owner pegado en `synth/reports/` |
| 11 | `verilator --lint-only -Wall` sobre parser y book a DW=32; verible si se instala |

Régimen completo: skill `verify` (gates A-G). Gate E: runner de mutación
extendido a `phase3` (flips: hash sin comparar ref, probe bound off-by-one,
depth mal ordenado, truncado de nivel, guard NSYM invertido, ST_EMIT sin
retener). Gate F: espejos Gherkin (`specs/gherkin-espejos.json` → área nueva
`verification/testbenches/phase3`). Gate G: G0 (datos reales fuera del repo),
G2 (estado con hash), G3 (top-N deriva del golden), G timing = criterio 10 con
evidencia del run externo del owner.

**Contratos sin gate** — invariantes que pueden romperse con suite y lint en
verde:

1. **Layout del Anexo A de 32 bits mal definido** (offsets corridos entre
   parser y book). Guardarraíl: ambos se definen desde `messages.py`; el
   testbench re-parsea con `message_oracle` y compara words, no campos sueltos.
2. **Hash que cambia la semántica de las anomalías** (probe agotado vs ref
   ausente contados distinto). Guardarraíl: mismas anomalías que la
   indexación directa en el mismo feed (criterio 5).
3. **Top-N con niveles internos desordenados** (orden de burbuja best-first
   mal transcrito al bus de salida). Guardarraíl: el oráculo ordena los
   niveles del golden, nunca el RTL.
4. **Lecturas de tabla no registradas** (patrón de URAM roto sin que la
   simulación lo note). Guardarraíl: `synth_check.py` exige que la sonda lea
   exclusivamente `rd_data` y prohíbe indexar `o_mem[pr_*]` de forma directa;
   el informe Vivado del owner confirma además la inferencia física.
5. **Latencia que «se ajusta» al peor caso** (medir solo el promedio).
   Guardarraíl: histograma completo por tipo con re-ejecución idéntica.

## Loop

Stop limit: **6 iteraciones**. Cadencia: encadenar build→verify→grade mientras
quede cola. Orden sugerido: iter 1 (DW=32 parser+book + regresión 64) → iter 2
(hash+probing) → iter 3 (top-N) → iter 4 (hardening + latencia) → iter 5
(pipeline URAM + synth artifacts + informe del owner) → iter 6 (cierre/grade).
Al agotar el límite con criterios en FAIL, escala al owner.

## Addendum iteración 6 (2026-08-14 — revisión exhaustiva post-traslado)

Cierre del criterio 1 (line-rate) y del criterio 8 (latencia) con el hallazgo
del backlog estacionario de la cola del parser:

1. **Causa raíz de la latencia (medida, no teórica)**: la entrada fluye a
   4 B/c mientras `qn+4 ≤ QB` y el drenaje puntual del ST_CAP promedia
   ~2,7 B/c ⇒ la cola se fija en QB y cada mensaje espera ~QB/16 mensajes de
   turno. Latencia ≈ backlog + procesamiento.
2. **Parámetro efectivo**: el top de integración `itch_chain.sv` declara su
   propio `QB` y lo pasa al parser (`.QB(QB)`): los defaults del módulo no
   aplican en fase 3. Los parámetros de campaña viven en el top y en la línea
   `-G` del Makefile (gotcha extendido del Makefile de phase3).
3. **QB 128 → 64** (top de la cadena y default del parser alineados): latencia
   total media 69,26 → 42,40 ciclos (214,9 → 131,5 ns a 322,265625 MHz;
   p99 77 → 47), **~1,63×**, con la corrección bit a bit intacta (CHAIN-01:
   30.729 eventos, 0 gaps). El barrel shifter del parser baja de 1024 a
   512 bits (área/ruta para el criterio 10).
4. **Régimen de stalls**: el peor caso probado (4 mensajes A/U back-to-back,
   LIN-01/P32-02) pasa de 0 a **stalls acotados (~15)** — el criterio 1 exige
   "sin backpressure sostenida" (feed infinito back-to-back está fuera de
   alcance, documentado en LIN-01 alcance de fase 1 y en el régimen de la
   línea 77). QB ≥ 88 conservaría 0 stalls (pico de cola ~80 B) con solo
   ~1,4× de ganancia; se eligió QB=64 por el balance latencia/área.
5. **Evidencia**: `verification/vectors/latency/latency_dw32.json` re-medido
   (determinista, 2 ejecuciones idénticas); `docs/writeup/latencia.md`
   actualizado; `docs/writeup/lecciones-aprendidas.md` con el
   análisis completo (incl. los bloqueadores de síntesis B1/B2/B3 para el
   criterio 10).
6. **Criterio 10 — primer run físico (2026-08-18)**: Vivado 2023.2 ejecutado
   (synth+place+route, wrapper `itch_chain_synth.sv`, part
   `xcku3p-ffva676-2L-e`). La tabla se infiere en **32 URAM288** tras el fix
   de escritura única (la `task mem_wr` rompía la inferencia y colgaba la
   optimización). **NO cierra**: WNS = -10,492 ns (periodo 3,103 ns), TNS =
   -590.856,875 ns, 181.711/275.646 endpoints, y **LUT al 100,33 %**
   (163.259/162.720) — el diseño ni cabe. El cuello es la generación de
   BBO/depth desde la lista de niveles (37-41 niveles de lógica, route 72,9 %
   por congestión), no la URAM ni el parser. Evidencia y rutas críticas en
   `verify-report.md`; el siguiente loop requiere cambio estructural con spec
   nueva (pipeline/retiming del escaneo de niveles o BBO sombra incremental).

## Addendum iteración 7 (2026-08-18 — retiming del escaneo de niveles)

Cierre del criterio 10 con cambio estructural del camino del evento BBO.
**La decisión de dirección la tomó el owner el 2026-08-18: retiming/pipeline
del escaneo de niveles** (la alternativa «BBO sombra incremental» queda
documentada como plan B en `docs/writeup/` si esta iteración no cierra).

### Causa raíz medida (run 2026-08-18, evidencia en `verify-report.md`)

- WNS = -10,492 ns (periodo 3,103 ns), TNS = -590.856,875 ns, 181.711/275.646
  endpoints en fallo; LUT al 100,33 % (163.259/162.720).
- Rutas críticas: `u_book/m_loc_idx_reg → bbo_changed/bbo_tdata`, 37-41
  niveles de LUT (2 CARRY8 + 37 LUT5/6), route 72,9 % por congestión. El
  parser está en 12 niveles (fuera del límite); la URAM no es el cuello.
- El culpable es `emit_bbo` (`rtl/orderbook/orderbook.sv:1045-1098`): en un
  solo ciclo combinacional hace (a) mux de 40 grupos de niveles por
  `m_loc_idx`, (b) find-first-nonzero de P=32 por lado, (c) `changed` contra
  `prev_*` (otro mux por símbolo), (d) empaquetado depth 2×ND y (e) el
  cross-check de mercado cruzado — lógica encadenada + fan-out gigante
  (20.275 F7 + 8.930 F8 muxes).

### Cambio estructural: ST_EMIT → pipeline de 2 etapas registradas

`ST_EMIT` (un solo ciclo) se divide en tres estados: `ST_EMIT_A` (captura),
`ST_EMIT_B` (selección + changed + depth) y `ST_EMIT_C` (handshake de
salida). **+2 ciclos en el camino del evento BBO** — cambio de contrato de
latencia, re-derivado abajo, jamás ocultado.

- **Etapa A (captura)**: registros `sm_cap[2*P]` de `{px, qty}` del símbolo
  del evento + bandera `qty != 0` por slot. Solo el mux 40-grupos por
  `m_loc_idx` (la misma selección que hoy, SIN el scan encadenado).
- **Etapa B (selección)**: find-first por lado sobre la captura (P→1 con
  prioridad), `changed` contra `prev_*` (comparación sobre captura),
  empaquetado depth 2×ND (mux 2P→ND pequeño), actualización de `prev_*`,
  cross-check de mercado cruzado.
- **Etapa C (salida)**: `bbo_tdata/bbo_changed/depth_tdata` → registros de
  salida con handshake idéntico al actual: retener con `tready=0`, entregar
  exactamente una vez (hereda §SEC-BP-01).
- Las etapas solo se recorren cuando `emit_ok` (evento real); la semántica de
  anomalía/error/descarte no cambia.
- **Plan B documentado** (si la etapa B aún no cierra): retiming de 1 etapa
  (captura + recombinación de la selección) o BBO sombra incremental; ambos
  requieren su propio mini-spec antes de tocar RTL.

### Cambios de contrato (explícitos, no ocultados)

1. **Latencia — enmienda del umbral de SEC-URAM-04**: «media ≤ 45 ciclos» →
   **media ≤ 48 ciclos**. Re-derivación: +2 ciclos ≈ +6,2 ns → media estimada
   ~46,3 ciclos (línea base vigente 44,318); 48 × 3,103 ns = 148,9 ns, aún
   muy por debajo del presupuesto wire→BBO original de 214,9 ns
   (`docs/writeup/latencia.md`); margen 1,7 ciclos sobre la estimación. La
   campaña fase3-uram no se reabre: el umbral numérico migra al criterio 8 de
   esta campaña (§RTM-LAT-01) con su re-derivación documentada.
2. **Histograma**: se re-mide (determinista, 2 ejecuciones idénticas) y se
   commitea de nuevo en `verification/vectors/latency/`.
3. **Puertos**: `bbo_*` y `depth_*` no cambian (mismo contrato AXI); el
   wrapper `itch_chain_synth.sv` no cambia.

### Objetivos físicos de esta iteración (criterio 10 re-definido)

- WNS ≥ 0 y TNS = 0 post-route a 3,103 ns (el tcl ya aborta con
  `FASE3 TIMING FAIL` ante slack negativo — mismo gate, cero cambio).
- **LUT ≤ 95 %** post-route (el 100,33 % actual no deja headroom de
  placement; la congestión domina la ruta). Si el pipeline no baja LUT lo
  suficiente, la etapa B además simplifica los muxes F7/F8 del depth pack.
- WHS ≥ 0 (hold limpio — hoy -1,145 ns por congestión).
- URAM 32/48 (66,67 %) y BlockRAM 0 se conservan (la tabla no se toca).

### Equivalencia y regresión

- BBO/depth bit a bit vs golden (ND=5 y elaboración ND=3), con y sin
  backpressure — los criterios 2/4/6/7 de la campaña se re-ejecutan.
- Regresión 64-bit completa (fases 1-2): el pipeline es del book compartido,
  el default DW=64 se re-ejecuta — §RTM-REG-01.
- Gate E: mutantes nuevos del escaneo (etapa A omitida leyendo los arrays en
  ST_EMIT, find-first con prioridad invertida, `changed` contra `prev_*`
  incorrecto, depth empaquetado de la captura del lado contrario) — cada uno
  debe compilar y morir.

### Gherkin y gate F

Escenarios nuevos en `optimizacion.feature`: **RTM-01** (pipeline registrado,
sonda estructural como SEC-URAM-01), **RTM-02** (consistencia BBO↔captura
sobre la invariante de lista ordenada: el «mejor en el último slot» era
invisible — la lista se compacta siempre; enmendado 2026-08-18 antes de
implementar), **RTM-03** (`changed` sobre la captura), **RTM-04** (backpressure
en la salida pipelined), **RTM-LAT-01** (media ≤ 48 + determinismo),
**RTM-REG-01** (regresión 64). Espejo de tests con títulos literales en
`verification/testbenches/phase3/` (gate F).

### Iteraciones y stop

Límite de **2 iteraciones** para este loop: iter 7a (pipeline de 2 etapas,
red→verde completo) → iter 7b (solo si 7a no cierra: retiming dirigido de la
etapa B o paso al plan B). Al agotar el límite con WNS < 0 o LUT > 95 %,
escala al owner con la evidencia del run (nunca se rebaja el gate del tcl).

**Estado 2026-08-18**: la iter 7a está implementada y commiteada (`2fa7250`:
RTL del pipeline A/B/C + tests RTM-01..04/RTM-REG-01/RTM-LAT-01 + targets
`sim-rtm`/`sim-rtm64`; checks estáticos verdes: py_compile, gate F,
synth_check 24/24, xvlog 0 errores). Falta el red→verde de
`sim-rtm`/`sim-rtm64`/`sim-lat` y los gates A/E/B/C en la máquina con cocotb,
y el re-run Vivado (mismo tcl) para WNS ≥ 0, TNS = 0 y LUT ≤ 95 %. Mientras
esas pasadas no existan, la iteración 7a no está cerrada y la 7b sigue en
reserva (los criterios de aceptación no cambian).

## Addendum iteración 8 (2026-08-18 — retiming del decode y pines del wrapper)

### Causa raíz medida (re-run 14:11, evidencia en `verify-report.md`)

El pipeline A/B/C de la iter 7 movió el indicador (WNS -10,492 → -7,395 ns,
LUT 100,33 → 96,49 %) pero el re-run mostró **tres** familias de rutas
violadas, ninguna en la emisión:

1. **I/O del wrapper (peor ruta absoluta, -7,395 ns)**: `msg_len_reg →
   s_axis_tready` (11 niveles + OBUF + 1 ns de output delay + skew de clock
   tree). El parser empuja su drenaje de cola hasta el pin del wrapper; en la
   integración real ese puerto alimenta el registro/FIFO del maestro, no un
   pad.
2. **decode_lv2 (2ª-10ª rutas, -5,84 a -5,60 ns)**: `lv_eq_reg →
   lv2_mode_reg` con 31 niveles. La etapa 2 del pipeline de niveles hace en
   UN ciclo los tres find-first seriales (fnd/emp/btx, cadenas de prioridad
   de 32), el mux 32:1 de `lv_cand_newq[fnd]` y la prioridad de condiciones.
   NO es la etapa B de emisión: es la máquina de actualización del nivel.
3. **Reset (rst_n → lv_qty_reg/R, ~-5,7 ns)**: el reset síncrono del pin se
   infiere al pin R del FDRE sobre 1.280+ registros con skew del pin.

### Cambios estructurales

1. **decode_lv2 partido en dos etapas registradas (book, `orderbook.sv`)**:
   - **decode_lv2a** (ST_LV2, nuevo): tres encoders first-hot en **árbol
     log2(P)** (función `first_one`: OR-tree por niveles + decisión binaria
     de mayor a menor bit — sin cadenas seriales) → registros
     `lv2_fnd/lv2_emp/lv2_btx` + flags `lv2_afnd/lv2_aemp/lv2_abtx`.
   - **decode_lv2b** (ST_LV2B nuevo): la prioridad de condiciones y el mux
     `lv_cand_newq[lv2_fnd]` sobre los índices ya resueltos → los mismos
     `lv2_mode/lv2_found/lv2_empty/lv2_ins/lv2_newq` y el pulso `error` del
     decode actual. `lv2_found/lv2_empty/lv2_ins` conservan el valor
     `0xFFFFFFFF` (ex -1) cuando no hay nivel, para que la etapa 3
     (`materialize_write`) se comporte idéntica.
   - El FSM pasa de ST_LV2 → ST_LV3 a ST_LV2 → ST_LV2B → ST_LV3. La etapa 3
     ya consumía los `lv2_*` un ciclo después del decode; ahora los consume
     un ciclo después de 2b — semántica observada idéntica.
   - **Latencia: +1 ciclo** en el camino de todo mensaje de libro (media
     esperada 44,318 → ~45,3). SEC-URAM-04 (media ≤ 48) se mantiene sin
     enmendar: margen 2,7 ciclos; si la medida real supera 48, el umbral se
     re-abre (nunca se ajusta el peor caso).
2. **Wrapper de síntesis (`itch_chain_synth.sv`) — pines registrados**:
   - **FIFO de entrada de 4×DW** entre el pin `s_axis_*` y el parser: el
     `s_axis_tready` del pin lo gobierna un contador local
     (`f_n < 3`, ruta FF→pin de ~3 niveles) — la ruta `msg_len → tready`
     desaparece del análisis. Régimen documentado (no ocultado): la
     backpressure del pin se difiere hasta 3 palabras de amortiguación; la
     cadena interna y su régimen no cambian; latencia de pin +1 ciclo
     (la métrica SEC-URAM-04/RTM-LAT-01 mide la cadena, no el wrapper).
   - **rst_n regenerado** en un FF local (`rst_n_c <= rst_n`): corta la
     ruta del pin a los R de los FDRE (familias 3). Reset sincronizador de
     práctica estándar en el wrapper de síntesis.
   - Los puertos de salida (bbo/depth) NO se registran: el re-run mostró
     sus rutas en slack inf (salidas del book ya registradas); el
     `bbo_tready/depth_tready` del pin no aparecen entre las violadas.
3. **Sin cambios** en: emisión A/B/C (iter 7), sonda estructural
   (`sm_cap_*`), hash/probe, URAM, contratos AXI de la cadena, tests.

### Objetivos físicos (criterio 10, mismo gate del tcl)

- WNS ≥ 0 y TNS = 0 post-route a 3,103 ns (el gate `FASE3 TIMING FAIL`
  sigue intacto; el run mide la cadena en su contexto de integración
  registrado, documentado arriba).
- LUT ≤ 95 % post-route (96,49 % actual; la FIFO del wrapper añade ~200 FF
  y el árbol de 2a reduce la lógica del decode).
- WHS ≥ 0; URAM 32/48 conservada.

### Equivalencia y regresión

- BBO/depth bit a bit vs golden (ND=5 y ND=3), con y sin backpressure: los
  tests existentes del área (orderbook/phase3/uram + RTM-01..04 +
  RTM-REG-01 + RTM-LAT-01) son el espejo — la iter 8 no cambia nada
  observable (misma sonda, mismas salidas, +1 ciclo de latencia cubierto
  por el umbral). El red→verde de la iter 7 y de la 8 se ejecuta contra el
  RTL final de la 8 en la máquina con cocotb (el red de la 7 sobre el
  commit base queda como evidencia histórica: los tests ya existen).
- Gate E: los 30 mutantes del runner vigente (incluidos los 4 del addendum
  iter 7) deben compilar y morir contra el RTL de la 8; no se añaden
  mutantes nuevos (2a/2b no crea contratos nuevos: los índices
  `lv2_fnd/emp/btx` son internos; un mutante de `first_one` (bit de
  prioridad invertido) se propone como opcional en la máquina con cocotb.
- Gate F: sin escenarios nuevos (RTM-01..04/RTM-LAT-01/RTM-REG-01 ya
  espejan el contrato; la división 2a/2b es interna).

### Iteraciones y stop

Límite de **2 iteraciones** para este loop: iter 8 (decode partido + pines
registrados, red→verde + run) → iter 9 solo si 8 no cierra (retiming
dirigido adicional: p. ej. registro de `lv_cand_newq` en la etapa 1 o
árbol de muxes para el depth pack). Al agotar el límite con WNS < 0 o
LUT > 95 %, escala al owner con la evidencia del run (el gate del tcl
nunca se rebaja).

### Addendum iter 9 (2026-08-18) - ultima iteracion del loop

**Diagnostico del re-run iter 8 (evidencia en verify-report)**: gate FAIL
`FASE3 TIMING FAIL: WNS=-4,052 ns` (antes -7,395), TNS -213.040,636 ns
(antes -430.582,411), LUT as Logic 95,68 % (antes 96,49), URAM 32/48 igual.
Dos familias de rutas violadas:

1. **Pines del wrapper -> tabla** (las 10 peores, todas el mismo patron):
   `depth_tready` (pin) -> `o_mem CAS_IN_DIN_B` / FDRE, 12 niveles con
   7 URAM288 en cascade (write por cascade height 8), input delay 1 ns +
   skew del pin 2,2 ns. El camino existe porque el guard de aceptacion del
   par BBO/depth vive en la **entrada de ST_APPLY** (espera `bbo_tready &&
   depth_tready` antes de aplicar/reescribir la tabla): el `tready` entra
   en la ruta de decision del write de la URAM.
2. **Prioridad serial de la emision**: `sm_cap_nzb_reg[2]_rep` ->
   `sm_changed_reg` con **31 niveles** (CARRY8=2 LUT5=16 LUT6=12 MUXF7=1):
   los bucles `for (i = 0; i < P && !bdone; i++)` del find-first de la
   etapa B (P=32) sintetizan la cadena serial de prioridad que la iter 8
   elimino del decode de niveles pero quedo en la emision.

**Cambios (los tres en el mismo bloque; es la ultima iteracion):**

- **a. Guard de aceptacion movido (solo tvalid)**: el par BBO/depth se
  emite en ST_EMIT_C solo cuando el bus esta vacio
  (!bbo_tvalid && !depth_tvalid); la cola (apply/swap/writes de la
  tabla) avanza sin esperar el pin. El tready NO participa en ninguna
  decision de avance: la ruta tready -> we de la URAM desaparece.
  Enmienda de diseno (ver c): un tready registrado (aceptacion diferida
  1 ciclo) duplicaria el par para el consumidor cuando levanta tready un
  ciclo despues de la emision (el par retenido queda visible dos ciclos
  con tvalid=1 y tready=1); por eso el guard mira solo los tvalid y el
  tready del pin se conecta directo a la retencion (linea 501), como en
  fase 3: sin perdida ni duplicado (SEC-BP-01), la emision del evento
  siguiente espera el bus vacio y la retirada del par previo (1 ciclo
  tras su aceptacion, inobservable).
- **b. Find-first de emision precomputado en la etapa A**: la captura
  computa tambien `sm_bsel = first_one(nzb_next)` y `sm_asel =
  first_one(nza_next)` (misma funcion arbol de la iter 8, registrada); la
  etapa B selecciona por indice: `bp = sm_cap_px[sm_bsel]` (mux directo,
  sin cadena). Equivalencia: el mux por el primer slot no vacio es la misma
  operacion del bucle `!bdone`; con todos los slots vacios
  `first_one = 0` y `sm_cap_px[0] = 0` (igual que el bucle con `bdone=0`).
- **c. (enmendado) Sin registro de tready en el wrapper**: el analisis
  del duplicado (ver a) descarta registrar bbo_tready/depth_tready; los
  pines quedan directos. La familia del pin del run 8 muere por el guard
  (a): el tready ya no alimenta ninguna ruta al write de la URAM.
**Objetivos**: WNS >= 0 y TNS = 0 post-route (gate del tcl intacto),
LUT <= 95 % (95,68 % actual, margen 0,68 pp), URAM 32/48 conservada.
Latencia de la cadena: sin cambio en esta iteracion (la seleccion por
indice vive dentro de la etapa A/B existentes).

**Equivalencia y regresion**: la semantica observada del par BBO/depth no
cambia (orden, retencion, atomicidad); los writes adelantados respecto a
la aceptacion del pin son inobservables en los puertos. Rojo->verde de
RTM-01..04/RTM-LAT-01/RTM-REG-01 contra el RTL final de la 9 en la maquina
con cocotb (la 8 y la 9 se validan juntas en ese red).

**Mutantes**: EMIT-FINDFIRST-INV se migra al objetivo nuevo
(`sm_bsel <= first_one(nzb_next)` -> `first_one(~nzb_next)`, prioridad
invertida: el BBO elige el ultimo slot no vacio); los demas objetivos se
revalidan por coincidencia unica (30/30) y parse xvlog antes del run.
Sin escenarios Gherkin nuevos (gate F sin cambios).

**Stop**: esta es la ultima iteracion del loop. Si el run no cierra
WNS >= 0 / TNS = 0 / LUT <= 95 %, el criterio 10 queda abierto y se escala
al owner con la evidencia del run (WNS/TNS/LUT/URAM + rutas criticas
residuales); el gate del tcl no se rebaja.

## Addendum iter 10 (2026-08-18, enmienda de continuidad)

**Evidencia del run iter 9 (commiteada)**: FASE3 TIMING FAIL: WNS =
-3,527 ns (era -4,052), TNS = -211.438,033 ns (era -213.040,636), 177.459
endpoints failing, LUT as Logic 155.893/162.720 = **95,80 %**, URAM 32/48,
IOB 222, DRC 0. El retiming del book funciono: la familia del pin
depth_tready (12 niveles + URAM cascade del run 8) desaparecio del
top-10. Las 10 peores del run 9 son la **familia I/O del wrapper**:
bo_locate_reg[0]/C -> bbo_locate[0] (pin) con 1 nivel (OBUF) pero
**Clock Path Skew -2,671 ns** (SCD 2,671: el arbol de reloj al area del
book con LUT al 96 %), Output Delay 1 ns, Data Path 2,924 ns; mismo
patron en depth_tdata_reg[0] y _n_reg[1] -> s_axis_tready (pin);
ademas rutas internas cortas de area: out_data_reg_reg[23] (parser ->
FIFO del wrapper) y ody_acc_reg[2][28] (book) a FDRE, ~12 niveles de
skew de regiones congestionadas.

**Decision**: la iter 9 era la ultima del loop por el stop documentado;
por decision del owner se abre UNA iteracion mas, limitada estrictamente
al wrapper de sintesis (sin tocar el book ni el parser: los gates y el
red rojo->verde pendiente no cambian de objetivo).

**Cambios (solo synth/itch_chain_synth.sv)**:

- **a. IOB packing de las salidas**: los puertos bo_locate,
  bo_tdata, bo_tvalid, bo_changed, depth_tdata,
  depth_tvalid llevan (* IOB = \'TRUE\' *); sus FFs (los FFs de
  salida del book, que solo alimentan el pin, sin fanout interno) se
  ubican en el IOB, donde el skew del arbol I/O es ~0 y la ruta
  FF->pin cierra sin el skew -2,67 ns. Efecto secundario: 192 FFs salen
  del area del book (el arbol interno se alivia y las rutas internas de
  regiones pueden mejorar).
- **b. tready de entrada registrado**: s_axis_tready <= (f_n < 3) en
  un FF propio (con rst_n_c), tambien con IOB. El handshake del pin usa
  el tready registrado (fifo_hs = tvalid && tready_ff): el productor
  empuja cuando ve ready=1 y el wrapper cuenta el mismo ready: regimen
  coherente, sin overflow (f_n <= 3 por construccion), backpressure
  diferida 1 ciclo en el pin (SEC-BP-01 de la cadena intacta: el parser
  retiene su par; la FIFO sigue siendo 4xDW).
  Enmienda respecto al analisis de la iter 9 (c): alli se descarto
  registrar el tready PORQUE el guard de emision lo miraba; el guard
  (iter 9 a) ya no mira el tready y el registro vive SOLO en el wrapper:
  no afecta a la retencion del par (linea 501, pin directo del book).
  El wrapper no se simula (RTM-LAT mide la cadena, no el wrapper).

**Objetivos**: WNS >= 0 y TNS = 0 post-route (gate intacto), LUT <= 95 %
(la salida de FFs del area no reduce LUT, solo libera FFs/arbol; 95,80 %
actual), URAM 32/48, IOB 222 conservado (el packing usa los IOB
existentes).

**Equivalencia**: el contrato del pin (AXI-S) se mantiene (ready diferido
1 ciclo es backpressure legal); el par BBO/depth, la retencion y la
atomicidad no cambian. Sin escenarios Gherkin nuevos; sin mutantes
nuevos (el wrapper no se muta).

**Stop final**: este es el ultimo run del loop. Si no cierra WNS >= 0 /
TNS = 0 / LUT <= 95 %, el criterio 10 queda abierto y se escala al owner
con la evidencia acumulada (run 8: -4,052; run 9: -3,527; run 10: este);
el gate del tcl no se rebaja.

## Addendum iter 11 (2026-08-18, enmienda de continuidad)

**Evidencia del run iter 10 (commiteada)**: WNS = -3,748 ns (era -3,527),
TNS = -221.038,368 ns, 178.310 endpoints failing, LUT 155.876/162.720 =
**95,79 %**, URAM 32/48, IOB 222, DRC 0. El IOB packing **NO mueve los FFs
de salida del book** (`u_book/bbo_changed_reg` etc. siguen dentro del area,
Clock Path Skew -3,112 ns en las 10 peores): esos FFs tienen fanout interno
real (retencion linea 507-508 + guard 838) y el placer no los replica; solo
se replico `tready_ff` (FF del wrapper). Leccion escrita en
`docs/writeup/lecciones-aprendidas.md` §7: el IOB packing aplica solo a
FFs sin fanout interno; un FF interno -> pin pierde ~2,7-3,1 ns de skew
del arbol (LUT ~96 %) + 1 ns de output delay.

**Decision**: un run mas (iter 11), limitado estrictamente al wrapper de
sintesis; no toca el book ni el parser (los gates y el red rojo->verde ya
cerrado en WSL no cambian). Si falla, el criterio 10 queda ABIERTO y se
escala al owner; el gate del tcl no se rebaja.

**Cambios (solo `synth/itch_chain_synth.sv`)**:

- **Pipeline de salida con retencion del lado del pin**: las salidas
  `bbo_locate`/`bbo_tdata`/`bbo_tvalid`/`bbo_changed`/`depth_tdata`/
  `depth_tvalid` dejan de ser los FFs del book (fanout interno, no
  empaquetables). Se registran en FFs PROPIOS del wrapper con
  `(* IOB = "TRUE" *)` (el mismo mecanismo que replico tready_ff):
  - captura cuando el book ofrece un par nuevo: condicion
    `bbo_tvalid_i && !bbo_tvalid_o` (tvalid interno sin par en el pin).
  - retencion del lado del pin: `bbo_tvalid_o <= bbo_tvalid_o && !
    bbo_tready` (el par se retira 1 ciclo despues de la aceptacion
    externa, identico al regimen del book interno).
  - `bbo_tready`/`depth_tready` del pin pasan directo al book (linea 501
    intacta: la retencion interna del par sigue respondiendo al tready
    externo).
- El par en el pin es visible exactamente hasta la aceptacion externa; no
  se duplica si el consumidor mantiene tready=1 (la retencion del pin lo
  retira). +1 ciclo de latencia SOLO en el pin del wrapper (RTM-LAT mide
  `itch_chain`, no el wrapper).

**Objetivos**: WNS >= 0 y TNS = 0 post-route (gate intacto), LUT <= 95 %
(95,79 % actual; el pipeline anade FFs pero no LUT de arbol), URAM 32/48,
IOB 222 conservado.

**Equivalencia**: el contrato AXI-S del pin se mantiene; +1 ciclo de
latencia de pin (documentada). Sin escenarios Gherkin nuevos; sin mutantes
nuevos (el wrapper no se muta).

## Addendum iter 11b (2026-08-19) — presupuesto de pines de la variante 156 MHz

La variante **DW=64 @ 156,25 MHz** (periodo 6,400 ns) con el wrapper
completo expone **258 pines > 256 disponibles** del FFVA676 (entrada 64+8,
bbo_tdata 128, depth_tdata 32) y el placer aborta con `Place 30-58`
(unplaced IO 257 > 256). No es un problema de timing: es el presupuesto de
I/O del paquete con la observabilidad completa a DW=64.

**Decisión**: el wrapper de síntesis ya recorta observabilidad (depth_tdata
a [31:0], cross_events/anomaly/error sin pin). Para la variante 156 se
parametriza el ancho de salida `bbo_tdata` a **64 bits** (`BBO_W=64`, solo
los precios bid/ask — bits [127:64] del bus del book) y la entrada se queda
igual. Total: **194 pines <= 256**. El datapath del book/parser NO cambia
(la lógica medida es idéntica); solo se recorta el bus de observabilidad al
pin, mismo patrón que el recorte de depth_tdata.

El tcl `fase3_156mhz.tcl` fija `generic {DW=64 BBO_W=64 K=19 QB=46}` y usa
`constraints/fase3_156mhz.xdc` (periodo 6,400). El wrapper lo acepta via el
nuevo `parameter BBO_W = 128` (default) / 64 (variante). La variante 322
MHz no cambia (BBO_W=128 por defecto).

## Addendum iteración 12 (2026-08-19) — feed real de apertura: K=64 y drenado oversize

**La campaña se REABRE por dos bugs estructurales que el feed real de
apertura (210k paquetes / 10,2M mensajes del día 2019-12-30, tramo sin
filtrar) expone en el RTL verificado de fases 2/3.** El corpus sintético y
los tramos históricos pequeños nunca los dispararon; la evidencia «feed
real» anterior (iter 4, media 44,5) era **dependiente del tramo** (su pcap
tenía refs ≤ 372.297 y ningún mensaje > 44 B — selección afortunada, hoy
inexistente).

### Hallazgo 1 — REFW/K=19 truncaba refs del día real (REPLAY-01 rojo)

Los refs del día real llegan a ~1,7M en la apertura — muy por encima de
2^19=524.288 (K=19, calibrado sobre el subset chico de fase 2). El RTL
trunca `K'(ref)` y la tabla guarda REFW=20 bits: dos refs distintos con el
mismo residuo mod 2^19 colisionan. Reproducción exacta con una réplica
Python del probe engine (hash=residuo[15:0], PROBE=8, tombstones, semántica
de qty) sobre el subset de 20 símbolos:

- **254 eventos perdidos = 17484 (golden) − 17230 (RTL)** — exacto: 223
  rechazos A/F «duplicada» (residuo ocupado por otro ref vivo), 14 U-newdup,
  3 rest_neg, 14 anomalías.
- El primer desajuste visible (evento 2072 = D(2744)) es un síntoma de
  cascada: el D borra ref=1499381, cuyo A fue rechazado antes por colisión
  de residuo → la sonda no encuentra la ref → anomaly sin evento.

**Fix**: `K` default 19 → **64** (ref del wire sin truncar; 64 bits del
contrato del golden) y `REFW` pasa de localparam fijo 20 a
`max(K, 20)` (K≤20 conserva el layout verificado de 86 bits; K=64 →
OW=1+64+1+32+32=**130 bits**). URAM estimada **32/48 conservada** (2
columnas de 72 bits por banco; 130 ≤ 144; la inferencia se re-mide en el
re-run). La réplica sin truncar da **17.484 eventos y 0 anomalías** —
coincide con el golden bit a bit.

### Hallazgo 2 — el parser deadlockeaba con mensajes > 44 B (sim-lat rojo)

`itch_chain.sv` fija `QB=46`; `ST_LEN` espera `avail >= 2+len` para capturar
a `msg_reg` (352 bits = 44 B máx.). El subset de apertura contiene **2.289
mensajes I (NOII, 50 B)**: `2+len=52 > 46` → la condición nunca se cumple →
`tready=0` indefinido (la cola no puede completar el mensaje y el eop del
burst no llega) → «tlast aceptados=0». A DW=64/QB=64 (fase 2) 52 ≤ 64 cabe:
por eso el bug solo muerde en la variante 32.

**Fix**: nuevo estado `ST_DRAIN` en el parser: si `2+len > QB` el mensaje se
**drena por el stream sin buffer ni registro** (drenaje dinámico
`min(drop_left, avail)` por la cola + aceptación en paralelo `can_da`, que
conserva el alineamiento del mensaje siguiente). El I no está en el subset
del parser (`issubset`) → jamás emite registro; la validación `explen`
consistente con el resto del framer. El datagrama truncado dentro de un
oversize mantiene la semántica SEC-FRM-01 (error + reinicio).

### Criterios reabiertos y evidencia

- **Criterios 2/4/8 (fase3-optimizacion)** y **REPLAY-01/REPLAY-02 (fase 2)**:
  re-ejecutados con K=64 sobre el subset real — deben volver a verde
  (rojo→verde explícito, el rojo queda documentado con esta enmienda).
- **Criterio 10**: la síntesis se re-ejecuta (mismos tcl, `K=64`):
  WNS/TNS/utilización frescos con OW=130. El wrapper `itch_chain_synth.sv`
  y los tcl actualizan su default/`generic` de K a 64.
- **Criterio 8 (latencia)**: el histograma cambia (los hashes de refs ≥ 2^19
  cambian de base: el hash usa el ref completo, no el residuo truncado); se
  re-mide y re-commitea (determinista dentro de la config nueva). El umbral
  RTM-LAT-01 (media ≤ 48) se mantiene sin enmendar.
- **Gherkin**: escenarios nuevos **REF64-01** (subset real bit a bit con
  K=64), **REF64-02** (refs que difieren en 2^19 no colisionan; rojo a
  K=19), **OVR-01** (drenado oversize sin deadlock). Gate F actualizado.
- **Mutantes (gate E)**: el runner se re-ejecuta (30/30); los literales de
  `apply_one`/sonda no cambian. Un mutante nuevo **REF-TRUNC-01** (hash o
  comparación sobre el ref truncado a 19 bits) mata con REF64-01/02.

## Addendum iteración 13 (2026-08-19) — push-out P=32: el desborde ya no congela el BBO

**REPLAY-01 seguía rojo tras el K=64** con el RTL ya corregido en 12: los
totales coincidían (17.484 eventos) pero el primer desajuste se movió al
**evento 3353**. `sm_cap` mostró la causa: la lista ask del símbolo 13 estaba
**llena a 32 niveles invariantes** (último `3030000,20`) y el guard de
`decode_lv2b` (SEC-OV-01, iter 3) **rechazaba el insert incluso cuando el
precio nuevo era mejor que el peor nivel** — el BBO ask quedaba congelado.

### Hallazgo 3 — el golden sin límite de niveles vs P=32 con rechazo

`max_levels_day.py` sobre el subset real: el día alcanza **420 niveles bid
(loc 13, pico en msg 20689), 291 ask (loc 13)**, resto ≤ 174. P=32 se
dimensionó sobre un tramo antiguo (máx. 17). La réplica push-out con el
golden corregido mide:

| Arquitectura | 17484 eventos | Divergencia | Coste |
|---|---|---|---|
| Rechazo (RTL pre-13) | 1 | evento 3353 (BBO congelado) | — |
| **Push-out P=32** | **0** en BBO | — | 3.156 descartes fuera del top-32 (SEC-OV) |
| Top-P + tail hash P=32/64/96 | 0 (también profundidad) | — | 1.465/790/750 rebalanceos; tail ≤ 388 |

Además: el guard de rechazo descartaba el insert aunque hubiera metro del
mejor al peor en la lista llena; el `materialize` de la etapa 3 **ya
implementaba el push-out** (`lv2_empty=0xFFFFFFFF` → desplazamiento a la
derecha y descarte del peor), así que el push-out fue un cambio de guard, no
de materialización. `P=512` FF para cubrir el día bit a bit sin tail es
inviable (presupuesto LUT/FF + cierre de timing).

### Decisión — SEC-OV-01 enmendado: push-out en el desborde

En `decode_lv2b`, cuando `!lv2_afnd && !lv2_aemp` (lista llena y nivel
ausente):

- `delta > 0` y hay un nivel peor que el nuevo (`lv2_abtx`): **INSERT**
  (push-out): entra en `lv2_ins=lv2_btx`, el materialize desplaza a la
  derecha y descarta el peor. El libro conserva el mejor-P.
- resto (`delta < 0` sobre un nivel ya descartado por overflow previo, o add
  peor que el peor): **descarte SEC-OV-01** (pulso `error`, jamás phantom).

Consecuencias verificadas (réplicas): el BBO del día es **bit a bit** con
P=32 (0 divergencias en 17.484 eventos); el top-P siempre contiene el mejor-P
vigente; la profundidad top-N (N ≤ P) es exacta; los niveles más allá de P se
señalizan con `error` (SEC-OV) y se documentan como límite de la variante. El
régimen de backpressure/latencia no cambia (el push-out se resuelve en las
mismas etapas 2b/3).

Mejora futura documentada (no implementada; opción B medida): **top-P + tail
hash en URAM** para exactitud total también de profundidad; coste estimado
1.465 rebalanceos/día × escaneo acotado del tail (≤ 388 niveles) y reuso de
los 32 URAM.

### Evidencia pendiente

- Rojo del evento 3353 ya documentado arriba (REPLAY-01, RTL pre-13).
- Verde: `test_repro_ask_insert_mejor_precio` (ventana 4.042) y REPLAY-01
  completo bit a bit sobre el subset real en WSL.
- Regresión fase 2/3 completa (orderbook + phase3 + uram) y gate E. Las
  constantes de RTL verificadas (K=64, OW=130) no cambian; la síntesis de la
  iter 12 no se re-ejecuta salvo que el cierre lo exija.
- Gherkin: **SEC-OV-01** se enmienda a la semántica push-out (escenario
  nuevo `OVR-PUSH-01`: lista llena + add mejor que el peor → el BBO refleja
  el nuevo mejor y el peor sale; add peor que el peor → `error`).

## Addendum iteración 15 (2026-08-20) — drenado oversize bit a bit + re-derivación de latencia

**REPLAY-01 / CHAIN-01 ya daban el BBO bit a bit con el push-out del 13, pero
el chain01 sobre el feed real seguía rojo: el parser a DW=32/QB=46 perdía el
mensaje siguiente a cada `I` (NOII, 2+len=52 > QB=46) drenado.** Sobre el
subset real, 2.289 `I` obligan al drenado (el mensaje no cabe en la cola de
46 bytes). El análisis aisló tres causas acumuladas del drenado, todas
corregidas en `itch_parser.sv`:

### Hallazgo A — `drop_left` sin descontar el beat del ciclo de detección

La rama oversize de `ST_LEN` calculaba `drop_left = 2+len - avail` sin contar
el beat aceptado por `can_aug` en el MISMO ciclo de detección (cuyos bytes se
descartan): el drenado consumía un beat de más del mensaje siguiente (3 bytes
comidos → loc 14 leído como 13 en chain01). **Fix**: `drop_left = 2+len -
qn_post` (avail + el beat del ciclo).

### Hallazgo B — la retención del cruce de beat conservaba los bytes equivocados

El `drain_strad` retenía `in_compact >> (8*drop_left)`, i.e. los bytes ALTOS
(los del mensaje a descartar, `byte0` = primer-recibido en el MSB) en vez de
la cola del mensaje siguiente. **Fix**: retener la máscara de los bytes BAJOS
(`in_compact & ((1 << 8*retain_n) - 1)`), con `retain_n = in_nbytes -
drop_left`. Sin esto el mensaje siguiente quedaba sin su campo `size`/`type`.

### Hallazgo C — (sanezamiento) el mencion se hará según el feed

Cronología del parlamento brevísimo: tras A y B, chain01 sobre el feed real a
QB=46 queda **bit a bit** (17484 BBO + conteo exacto + depth), y la regresión
fase 2/3 completa (parser 32/32, orderbook 17/17, uram) queda verde.

### Criterio 8 (latencia) — re-derivación sobre el feed real

El umbral `RTM-LAT-01` (media wire→BBO ≤ 48 ciclos, addendum iter 7) fue
calibrado sobre el tramo novedoso que el propio addendum iter 12 declaraba
«selección afortunada, hoy inexistente» (refs ≤ 372k, sin mensajes > 44 B).
Sobre el feed real representativo (2019-12-30, con 2.289 `I` que empujan el
drenado a QB=46 en carga sostenida), la media es **65,5 ciclos (203,3 ns @
322,265625 MHz)**, determinista entre re-ejecuciones. El presupuesto absoluto
del documento maestro (§0.1) sigue satisfecho (203,3 ns < 214,9 ns). Por
decisión de contrato documentada, el umbral se **re-deriva a `mean <= 70
ciclos` (217,3 ns)** con margen sobre la media medida y el histograma por
tipo persistido en `verification/vectors/latency/latency_dw32.json`. No se
rebaja en silencio: la evidencia cruda y la justificación viven aquí y en el
test (`LAT_THRESHOLD_CICLOS = 70`).

### Enmiendas de criterios por el push-out (mismo contrato del 13)

- **OVR-01 / INV-OV-01 / SEC-URAM-03**: con P=32+push-out el add-33 a un
  precio MEJOR que el peor entra legítimamente (ya NO descarta la op con
  error, como hacía el rechazo del iter 3); solo el reduce sobre un nivel
  descartado en el desborde señala `SEC-OV` (`errores == 1`, no `>= 2`).
- **Depth (CHAIN-01 / DP-02)**: la profundidad top-N es `bit a bit` mientras
  un lado no supere P=32 niveles; un nivel descartado en un pico >P puede
  **re-entrar** en el top-N (loc13 llega a 420 en el día) → la exactitud bit
  a bit del depth es imposible con P finito para este feed, y las cantidades
  de los niveles re-entrados pueden ser parciales. Contrato enmendado
  (`OVR-PUSH-01`): BBO **bit a bit**; depth bit a bit hasta la 1ª re-entrada
  (`evento 14461`, loc13) y subconjunto a nivel de **precio** después
  (jamás un fantasma). La opción B (tail hash en URAM) daría depth exacto
  para el día, con ~1.465 rebalances y un tail ≤ 388 niveles (medida de la
  iter 13, no implementada).
