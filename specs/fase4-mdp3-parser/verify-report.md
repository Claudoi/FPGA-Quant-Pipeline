# verify-report — fase4-mdp3-parser

> Régimen de gates de Atenea re-mapeado al flujo HDL. Sin verify-report,
> `/grade` da FAIL directo. Lo escribe `/verify` campaña a campaña.
> Estado: **spec commiteada (2026-08-14), pendiente de /build (iteración 1)**.

## Iteración 1 — golden MDP3 (criterio 1: loader schema + decoder + generator)

**Rojo con evidencia (TDD):** el módulo `golden_model/mdp3/` no existía; los
tests espejo `golden_model/tests/test_mdp3.py` fallaron primero por
`ImportError` (módulo ausente) y luego por errores reales del codec al
arrancar el verde:
- `KeyError: 'name'` / `ValueError: 'J'` en el loader (constantes char).
- `KeyError: 'uInt8'` en `type_size` (nombres de tipo CME sin canonicalizar).
- `header_size 0` (el v12 no trae `<header>`: la cabecera es el composite
  `messageHeader`).
- grupos leídos en el offset equivocado (la dimensión va después del root
  blockLength) y base no acumulativa entre grupos.
- `decode_message` decodificaba cualquier template conocido del schema (48
  etc.); ahora solo el subset 46/47/52/53; el resto es passthrough.

**Verde final (gate A, golden):** `python3 -m unittest discover -s
golden_model/tests -t .` → **35 tests OK** (32 de fases 0-3 sin cambios + 3
nuevos). Espejos del criterio 1 (M3-GEN-01/02) en
`golden_model/tests/test_mdp3.py` (área de golden, precedente fase 0).

**Stress del round-trip (evidencia extra):** 4.000 mensajes del subset
(46/47/52/53, 50 seeds) con `decode(encode(m))` re-encodeado byte a byte
idéntico; corpus sintético de 30 paquetes → 206 records Anexo M de oráculo
(media 14 words/record).

**Schema pinned:** `data/mdp3/templates_FixBinary_v12.xml` (2021-03-10,
id=1 version=12, byteOrder=littleEndian, md5
`e6eb6c60b46e61dc154537879b3d18d2`) descargado vía
`scripts/fetch_mdp3_schema.py` (CME FTP 403 por bot → fallback Wayback con
hash verificado; fail closed).

**Correcciones de contrato con evidencia (edit de spec, changelog en spec.md):**
byte-order **little-endian** (XML oficial + roq-cme), IDs del subset
**46/47/52/53** (el v12 no usa los pre-event 27/30/32), `msg_size` incluye el
prefijo de 10 B (roq-cme `parser.cpp`), dimensionTypes `groupSize` (3 B) /
`groupSize8Byte` (8 B), Anexo M con record **MBOFD de 18 words** y tabla de
derivación por template (ReferenceID del 46 resuelto por índice).

**Mapa de cobertura (gate D nivel 1) — criterio 1:**
| Test | Espejo |
|---|---|
| `test_m3gen01_el_golden_hace_roundtrip_decode_encode_m_es_m` | M3-GEN-01 |
| `test_m3gen01_el_passthrough_preserva_el_cuerpo_crudo` | M3-GEN-01 (2ª parte) |
| `test_m3gen02_el_loader_deriva_los_tamanos_esperados_desde_el_xml` | M3-GEN-02 |

Pendiente: iter 2 (RTL `mdp3_parser.sv`: framing + Anexo M bit a bit vs
golden, criterios 2-3).
## Iteración 2 — RTL `mdp3_parser.sv` (criterios 2-3: framing + Anexo M bit a bit)

**Progreso frente al baseline** con la corrección estructural de captura
(ventana deslizante de 8 B → FIFO circular de 256 B, `qc` con conteo preciso,
`qh` avanzado en lugar de `qh<=0` en la rama parcial):
- `verilator --lint-only -Wall -Wno-DECLFILENAME -Wno-PINCONNECTEMPTY
  --top-module mdp3_parser rtl/parser/mdp3_parser.sv` → **0 warnings** (gate B/C).
- Simulación `make sim` → `longitud 6056 != 9664` (mejora desde el `0` previo
  a esta corrección y corroborado en 3 frentes M3-FRM-01/02/03).

**Hallazgo (estructural, pendiente de iter 3):** la captura `CS_SIZE→CS_BODY`
descorrelaciona la cola en el **reuso de buffer ping-pong**. La rama parcial
de `CS_BODY` consumía todos los bytes de la ventana y hacía `qh<=0; qc<=0`;
al alternar `cap_sel` a un buffer ya usado, bytes pre-cargados (greedy
prefetch de la word siguiente) quedaban huérfanos y `qc` los subcontaba →
el header SBE (`blockLength`+`templateId`, 4 B) se corrompía a ceros y el
cuerpo se desplazaba 4 B. Los mensajes del primer uso de cada buffer salen
correctos; los del reuso, no.

**Horizonte iter 3:** cerrar la contabilidad en el handoff `CS_WAIT→CS_SIZE`
(la tready de 1 ciclo deja `qc=0` tras leer el tamaño; `CS_BODY` debe leer la
word retenida vía `qc_eff` en el consumo, no desde `tdata` ya avanzada) y dejar
los 3 espejos en verde, luego correlación con corpus completo y commit.

## Iteración 3 — causa raíz del byte huérfano + gating del exponente (criterios 2-3)

**Rojo diagnosticado con dump de buffer.** Instrumenté el RTL (`M3_DBG`,
dump de `mbuf` en `DS_DONE`) y correlacioné los dumps contra los bytes de
cada mensaje reconstruidos del paquete (caminando desde el header de 12 B).
Resultado: **todos** los mensajes corruptos tenían exactamente **un byte
huérfano en `mbuf[10]`** (el primer byte del cuerpo, tras el prefijo de
10 B), que quedaba stale del uso previo del buffer ping-pong.

**Causa raíz (bug real, distinto del descrito en iter 2):** las ramas de
`CS_BODY` (parcial y completa) escribían en el buffer a lo sumo `2*BYTES`
(8) bytes por ciclo — el lazo `for (k=0; k<2*BYTES; k++)` — pero avanzaban
`cap_len`/`qh` por `qavail_eff` (o `cap_size-cap_len`), que puede superar 8
cuando la cola acumuló bytes. El byte sobrante (el 9º, `mbuf[10]`) nunca se
escribía. Se reescribió `CS_BODY` para consumir/avanzar **exactamente lo que
escribe**: `cnt = min(restante, qavail_eff, 2*BYTES)`, y ambas ramas quedan
unificadas en una sola.

**Hallazgo concatenado (contrato #5 — ReferenceID fuera de rango):** tras
cerrar el byte huérfano quedaron 7 bytes distintos en 7 records `tpl=46`
MBOFD: el golden pone `w15` (exponente) a `0` en el fallback
`src=None` (`ReferenceID >= NoMDEntries`, mensajes con `NoMD=0`), pero el
RTL hardcodeaba `EXP_BYTE=0xF7` en `rrec[15]`. El schema fija el exponente
constante `-9` (PRICENULL9/PRICE9), así que `0xF7` es correcto cuando la
referencia es válida; solo faltaba **gatearlo** por `rref < g1_n`, igual
que `rrec[5]/6/13/14`. Corregido.

**Verde (criterio 2 — framing bit a bit):**
```
** test_mdp3_framing.test_m3frm01_..._bit_a_bit_vs_el_golden   PASS
** test_mdp3_framing.test_m3frm02_mensajes_que_cruzan_limites  PASS
** test_mdp3_framing.test_m3frm03_peor_caso_a_1_palabra...      FAIL (backpressure 139 > 16)
** TESTS=3 PASS=2 FAIL=1
```
**Gate B/C:** `verilator --lint-only -Wall -Wno-DECLFILENAME
-Wno-PINCONNECTEMPTY --top-module mdp3_parser rtl/parser/mdp3_parser.sv`
→ **0 warnings**, exit 0.

**Régimen de `M3-FRM-03` (criterio 3, line-rate) — limitación inherente, no
bug:** el test arma un paquete de 24 mensajes `tpl=47` back-to-back que
decodifica en **56 records MBOFD = 1008 words de salida** frente a ~707
words de entrada (ratio **1.43**, expansión del Anexo M: cada record MBOFD
emite 72 B por ~43 B de entrada). A DW=32 el parser no puede sostener 1
palabra/ciclo de entrada si la salida crece más que la entrada: la FIFO se
llena y la captura bloquea (backpressure real, ya admitida en el comentario
de cabecera del RTL: *"limitación inherente al Anexo M, igual que LIN-01 de
fase 1"*). Un `max_stall <= 16` es inalcanzable para entradas MBOFD-dominadas
sin rediseño del régimen de captura/emisión. **Queda documentado como límite
inherente pendiente de decisión de spec** (si el line-rate del criterio 3 debe
medirse sobre el subset con expansión contenida, no sobre MBOFD puro).

**Regresión (criterio 8):** golden `35/35`; `make sim` en
`testbenches/{parser,orderbook,phase3}` sin cambios → **19/19, 14/14, 5/5**.

