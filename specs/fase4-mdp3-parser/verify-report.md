# verify-report — fase4-mdp3-parser

> Régimen de gates de Atenea re-mapeado al flujo HDL. Sin verify-report,
> `/grade` da FAIL directo. Lo escribe `/verify` campaña a campaña.
> Estado: **en construcción; golden semántico reparado y RTL en rojo 0/3
> (2026-08-15)**.

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

**Verde histórico (gate A, golden; evidencia insuficiente):** `python3 -m
unittest discover -s golden_model/tests -t .` → **35 tests OK** (32 de fases
0-3 sin cambios + 3 nuevos). Espejos del criterio 1 (M3-GEN-01/02) en
`golden_model/tests/test_mdp3.py` (área de golden, precedente fase 0).

**Stress histórico del round-trip (invalidado como evidencia semántica):**
4.000 mensajes del subset
(46/47/52/53, 50 seeds) con `decode(encode(m))` re-encodeado byte a byte
idéntico; corpus sintético de 30 paquetes → 206 records Anexo M de oráculo
(media 14 words/record). Esa igualdad solo demostraba autoconsistencia de los
bytes: tanto el primer encode como el re-encode escribían ceros y, por tanto,
podían coincidir sin conservar los valores de entrada.

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
| `test_m3gen01_el_encoder_preserva_valores_no_cero_del_subset` | M3-GEN-01 (oráculo semántico) |
| `test_m3gen01_el_passthrough_preserva_el_cuerpo_crudo` | M3-GEN-01 (2ª parte) |
| `test_m3gen02_el_loader_deriva_los_tamanos_esperados_desde_el_xml` | M3-GEN-02 |

## Iteración 1b — reparación del falso verde del encoder (2026-08-15)

**Rojo semántico:**

```text
test_m3gen01_el_encoder_preserva_valores_no_cero_del_subset ... FAIL
AssertionError: 0 != 72623859790382856
```

El encoder pasaba `root[f.offset:]` y `e[gf.offset:]` a `_encode_value`.
Esos slices de `bytearray` son copias, de modo que los valores root y de grupo
no llegaban al mensaje original. Se corrigieron ambas rutas en el punto común:
codificar el valor y copiar los bytes resultantes al rango del buffer destino.

**Verde semántico (gate A):** el test literal compara todos los valores
provistos de 46/47/52/53, incluido precio signed, IDs y los dos grupos
multi-entry de 46. Resultado:

```text
golden_model.tests.test_mdp3 ... Ran 4 tests ... OK
golden_model/tests completo     ... Ran 36 tests ... OK
```

**Rebaselining RTL contra el golden reparado:**

```text
M3-FRM-01 FAIL: byte 116: got 0x00 exp 0x9f
M3-FRM-02 FAIL: bytes distintos (cruces de límite mal alineados)
M3-FRM-03 FAIL: backpressure sostenida: 139 ciclos
TESTS=3 PASS=0 FAIL=3 SKIP=0
```

La fase 4 permanece abierta. Este rojo sustituye como baseline vigente la
longitud histórica `6056 != 9664`; no se atribuye PASS al RTL.

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
