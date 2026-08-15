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
  backpressure, truncado) y la variante 64-bit queda en regresión verde.
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
  (≈20 URAM para 65.536×86 bits) y de las técnicas de retiming/pipelining en
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

- **Familia/part objetivo:** AMD/Xilinx UltraScale+ **xcvu9p-flga2104-2L-e**
  (VU9P; 960 URAM, 1182K LUT, 34,6 Mb BRAM) — swappable en el tcl/constraints.
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

## Superficie y amenazas

**Puertos nuevos del book (top `orderbook`):**

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
3. [ ] **Regresión 64-bit**: suites fase 1 (19/19) y fase 2 (14/14) verdes con
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
     (1 ciclo) y el mapeo (65.536×86 bits ≈ 20 URAM) se documenta en
     `docs/writeup/`; no hay ruta O(P·P) en el cálculo del mejor precio.
10. [ ] **Síntesis**: `synth/` contiene constraints (322,265625 MHz) + script
     tcl (synth/impl, part VU9P); el owner corre Vivado fuera y pega el
     informe WNS/TNS y utilización en `synth/reports/` — WNS ≥ 0 en la
     variante 32-bit.
11. [ ] Cocotb + Verilator compilan ambos tops a DW=32 con `--Wall` sin
     warnings reales silenciados; lint en verde sobre lo tocado.
     — Gates B/C de verify.

## Verificación

| Criterio | Cómo se prueba |
|---|---|
| 1 | cocotb: corpus sintético + replay REP-02 a DW=32 (words 32-bit vs `message_oracle`); peor caso mínimo back-to-back sin backpressure |
| 2 | cocotb: corpus BBO-01..SEC-* a DW=32 contra `book.py`; REPLAY-01 a 32 bits |
| 3 | cocotb: `make sim` en `testbenches/parser` (19) y `testbenches/orderbook` (14) tras el cambio |
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
   actualizado; `docs/writeup/revision-exhaustiva-2026-08-14.md` con el
   análisis completo (incl. los bloqueadores de síntesis B1/B2/B3 para el
   criterio 10).
6. **Pendiente para el criterio 10 (externo)**: la iteración URAM ya está
   implementada en RTL con lectura registrada, sonda serializada y pipeline de
   niveles (`docs/writeup/uram.md`). Falta ejecutar Vivado y adjuntar WNS/TNS,
   endpoints sin constraint y utilización para confirmar el cierre físico.
