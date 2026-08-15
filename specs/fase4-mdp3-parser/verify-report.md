# verify-report — fase4-mdp3-parser

> **Estado vigente: REABIERTA (2026-08-15).** La evidencia previa no representa
> últimos beats con un número parcial de bytes válidos. Los resultados se
> conservan como evidencia histórica, pero los criterios 1, 2, 3, 5, 7, 8, 9 y 10
> están abiertos. El framing requiere implementar y verificar `s_axis_tkeep`;
> los hallazgos de schema/version, tamaño y backpressure se resolverán por
> separado.

> Régimen de gates de Atenea re-mapeado al flujo HDL. Sin verify-report,
> `/grade` da FAIL directo. Lo escribe `/verify` campaña a campaña.
> Estado histórico: **se declaró cerrada funcionalmente (2026-08-15)**. Los criterios 1-9 pasaban
> en DW=32 y DW=64; el objetivo de frecuencia no se presenta como timing
> cerrado porque Vivado no está disponible en este entorno.

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

## Iteración 3 — framing, subset y robustez RTL (criterios 2-7)

El rojo vigente de 0/3 se resolvió en la causa común de captura y packet-end:

- la copia desde la cola debía admitir hasta `3*BYTES` disponibles en el
  handoff, no solo `2*BYTES`;
- `tlast` aceptado se conserva en `pkt_end` hasta drenar los bytes ya
  encolados, evitando perder el último mensaje o confundirlo con el header del
  paquete siguiente, especialmente en DW=64;
- el passthrough parcial alinea a MSB la última word y rellena a cero;
- los grupos validan `base + numInGroup*blockLength <= msg_size` antes de leer
  entries; un `ReferenceID` fuera de rango pulsa `error` y emite los campos
  dependientes a cero, igual que el golden;
- el último push de un grupo terminal libera el buffer en el mismo ciclo. El
  rojo específico era una racha real de **19 ciclos** en DW=64; tras eliminar
  tres estados ociosos queda dentro del contrato sin añadir otra FIFO.

Evidencia limpia de simulación:

```text
DW=32  TESTS=8 PASS=8 FAIL=0 SKIP=0
DW=64  TESTS=8 PASS=8 FAIL=0 SKIP=0
M3-FRM-03 DW=32: racha máxima tvalid&&!tready = 8
M3-FRM-03 DW=64: racha máxima tvalid&&!tready = 16
```

Los ocho tests cocotb cubren framing aleatorio, cruces de palabra, el vector
literal de throughput, 46/47/52/53 con valores no cero y multi-entry,
passthrough conocido/desconocido, gap/reset, tamaños/truncados con
recuperación, grupo incompleto y `ReferenceID` inválido.

El corpus válido también se corrigió: el generator ya no crea entries MBOFD
con `ReferenceID=0` cuando `NoMDEntries` está vacío. Los casos inválidos viven
en tests adversariales explícitos, no mezclados silenciosamente en el corpus
nominal.

## Iteración 4 — gates A-G y regresión 0-3 (criterios 8-9)

| Gate | Comando/evidencia actual | Resultado |
|---|---|---|
| A — simulación | `python3 -m unittest discover -s golden_model/tests -t .`; `make .../mdp3 sim`; `make .../mdp3 sim-dw64` | **37/37 Python, 8/8 DW32, 8/8 DW64 — PASS** |
| B — compilación | `python3 -m compileall -q golden_model scripts/verify verification/testbenches/mdp3`; Verilator en ambas anchuras | **PASS** |
| C — estilo | `verilator --lint-only --Wall -GDW=32/64 --top-module mdp3_parser rtl/parser/mdp3_parser.sv`; `command -v verible-verilog-lint` | **0 warnings Verilator; verible NO EJECUTADO (no instalado)** |
| D — cobertura | mapa literal de los 14 escenarios abajo; checker schema v12↔RTL | **PASS funcional** |
| E — mutación | `python3 scripts/verify/mutate_mdp3.py` | **8/8 compilables muertos, 0 supervivientes — PASS** |
| F — completitud | 14 IDs únicos en `mdp3.feature`; entrada de fase 4 en `specs/gherkin-espejos.json` | **PASS** |
| G — rigor/timing | golden desde XML, corpus sintético, ningún feed real versionado; `command -v vivado` | **Rigor PASS; timing NO EJECUTADO (Vivado ausente)** |

### Gate E — resumen adversarial

```text
TPL47-ID       killed (DW32)
TRUNC-NOERROR  killed (DW32)
SEQ-NOGAP      killed (DW32)
GROUP-COUNT    killed (DW32)
GROUP-BOUNDS   killed (DW32)
PASS-NOBODY    killed (DW32)
PRICE-SWAP     killed (DW32)
PUSH-IDLE      killed (DW64)
TODOS LOS MUTANTES COMPILAN Y MUEREN. Gate E PASS.
```

El primer candidato `SIZE-PACKET` retiraba una comprobación temprana que el
FSM repetía de forma equivalente en `CS_BODY`; sobrevivió sin cambiar el
comportamiento. No se contó como evidencia: se sustituyó por
`TRUNC-NOERROR`, que silencia la propiedad observable y muere en M3-INV-01/02.

### Gate D/F histórico — mapa anterior a los escenarios reabiertos

| Escenario | Test o gate que lo cierra |
|---|---|
| M3-GEN-01 | cuatro tests semánticos/round-trip/passthrough en `golden_model/tests/test_mdp3.py` |
| M3-GEN-02 | `test_m3gen02_el_loader_deriva_los_tamanos_esperados_desde_el_xml` |
| M3-FRM-01 | `test_m3frm01_el_parser_emite_el_anexo_m_bit_a_bit_vs_el_golden` |
| M3-FRM-02 | `test_m3frm02_mensajes_que_cruzan_limites_de_palabra` |
| M3-FRM-03 | `test_m3frm03_peor_caso_a_1_palabra_por_ciclo_sin_backpressure` |
| M3-SUB-01/02 | `test_m3sub01_sub02_subset_y_multi_entry_bit_a_bit` |
| M3-PASS-01 | `test_m3pass01_passthrough_crudo_y_schema_desconocido` |
| M3-GAP-01 | `test_m3gap01_salto_y_reset_de_canal` |
| M3-INV-01/02 | `test_m3inv01_inv02_tamanos_invalidos_y_truncado_recuperan` |
| M3-INV-03 | `test_m3inv03_grupo_vacio_o_entry_fuera_del_mensaje` |
| M3-SCH-01 | `test_m3sch01_los_localparams_rtl_coinciden_con_el_schema_v12` |
| M3-REG-01 | matriz de regresión siguiente |

### M3-REG-01 — regresión integral post-mutación

```text
fase1 parser                 TESTS=20 PASS=20 FAIL=0
fase2 orderbook              TESTS=14 PASS=14 FAIL=0
fase3 book DW32              TESTS=5  PASS=5  FAIL=0
fase3 parser DW32            TESTS=4  PASS=4  FAIL=0
fase3 hash K=20              TESTS=8  PASS=8  FAIL=0
fase3 depth ND=5             TESTS=3  PASS=3  FAIL=0
fase3 hardening              TESTS=2  PASS=2  FAIL=0
fase3 chain ND=5             TESTS=3  PASS=3  FAIL=0
fase3 chain ND=3             TESTS=3  PASS=3  FAIL=0
fase3 latencia               TESTS=1  PASS=1  FAIL=0
fase3 Anexo A/URAM           TESTS=2  PASS=2  FAIL=0
fase3 URAM                   TESTS=4  PASS=4  FAIL=0
```

## Veredicto histórico — sustituido por la reapertura

El parser CME MDP3 se declaró **cerrado en su alcance funcional**: golden
schema-driven, framing multi-mensaje y packet-end en dos anchuras, subset
46/47/52/53, passthrough, gaps, inválidos, mutación y regresión completa. No
se incluyen datos DataMine ni se afirma evidencia real que no existe. Este
veredicto ya no representa el estado actual por los hallazgos descritos al
inicio del informe.

La frecuencia objetivo de 322,265625 MHz (DW=32) / 156,25 MHz (DW=64) sigue
siendo una **propiedad física no acreditada**: no hay Vivado en el entorno ni
WNS/TNS/utilización del `mdp3_parser`. Este límite no invalida el cierre
funcional histórico, pero prohíbe describir la fase como timing-closed.
