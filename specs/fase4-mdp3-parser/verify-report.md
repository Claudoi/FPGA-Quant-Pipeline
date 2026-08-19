# verify-report — fase4-mdp3-parser

> **Estado vigente (2026-08-19): NO CERRADA — framing, criterio 5 y
> criterio 10 verdes; criterio 7 abierto.**
> El framing `s_axis_tkeep` del RTL `mdp3_parser` quedó implementado y
> verificado en WSL (cocotb 2.0.1 + Verilator 5.046, Python 3.12): suite
> DW=32 y DW=64 con 12/12 PASS + 2 SKIP (criterio 7 abierto), gate B
> (verilator `--Wall`) limpio y gate E 9/9 mutantes. En la pasada de
> 2026-08-19 se cerraron además los criterios **5** (schemaId/version no
> soportados → passthrough) y **10** (backpressure de salida): detalles en
> la iteración 6, y se ejecutó el **gate C (verible): 0 hallazgos** sobre
> `mdp3_parser.sv`. Sigue **abierto**: el criterio 7 (máscaras con huecos /
> parcial sin tlast, loop de robustez) y el timing (sin Vivado).

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

---

## Iteración 5 (2026-08-18) — framing `s_axis_tkeep` verde en WSL

El RTL `mdp3_parser` expone `s_axis_tkeep` (commit `62e4e46`) y el framing
tkeep se verifica por primera vez con el puerto presente en un entorno
reproducible (WSL2 Ubuntu 26.04, cocotb 2.0.1, Verilator 5.046, Python
3.12.13).

### Gate A — suite del área MDP3 (DW=32 y DW=64)

Desde `make clean-all`:

```text
=== DW=32 ===
TESTS=9 PASS=9 FAIL=0 SKIP=0
=== DW=64 ===
TESTS=9 PASS=9 FAIL=0 SKIP=0
```

Tests: M3-FRM-01, M3-FRM-02, M3-FRM-03, M3-SUB-01/02, M3-PASS-01, M3-GAP-01,
M3-INV-01/02, M3-INV-03, **M3-FRM-05** (a/b/c). M3-FRM-05 pasa en ambas
anchuras; el SkipTest por puerto ausente ya no aplica.

### Corrección del test M3-FRM-05b (mask del último beat)

Hallazgo del rojo DW=64: la máscara del último beat se calculaba como
`((1 << (b-1)) - 1) << 1` (b = `DW/8`), que **sumaba los bytes de relleno**
a DW=64: el último beat del paquete de 76 B es parcial (4 bytes reales, mask
`11110000`) y esa receta declaraba `11111110` (= 7 lanes), completando
falsamente la longitud declarada y suprimiendo el `error`. A DW=32 el paquete
es múltiplo de palabra (último beat completo) por lo que el caso funcionaba.
Se corrigió derivando la máscara del número real de bytes del beat (`nv` de la
mask nominal): `((1 << (nv-1)) - 1) << (b - (nv-1))`.

### Gate B — lint Verilator

```text
verilator --lint-only --Wall --top-module mdp3_parser rtl/parser/mdp3_parser.sv
Verilator 5.046 ... (0 warnings, exit 0)
```

### Gate E — mutación (aumentado a 9, incluido tkeep)

Se añadió el mutante `TKCNT-ALWAYS` (el beat avanza siempre `BYTES` en lugar
de `tk_cnt`), que ejercita la mecánica de la máscara; muere en `sim` DW=32.

```text
TKCNT-ALWAYS   killed (sim, FAIL=1)
TODOS LOS MUTANTES COMPILAN Y MUEREN. Gate E PASS.
```

Los `TKCNT-FULL`/`TKCNT-READY` iniciales se descartaron (equivalentes: escribir
lanes extra a `qbytes` sin avanzar `qw` no cambia el observable, porque el
decodificador lee de `tdata` directo para `k >= qavail`).

### Gate C — NO EJECUTADO

`verible-verilog-lint` no está instalado. Declarado NO EJECUTADO; no falsifica
el gate B.

### Declaración

- Criterios **2 y 8** (brazo tkeep): cubiertos con evidencia vigente (18/18,
  mutante tkeep). No se presentan como cierre de la campaña completa.
- Siguen **abiertos** (loops separados): criterio 5 (schemaId/version,
  MAX_MSG 256/257), criterio 7 restante (máscaras con huecos), criterio 10
  (backpressure de salida) y timing (sin Vivado MDP3).

## Iteración 6 (2026-08-19) — loops de criterio 5 y 10; criterio 7 abierto

Pasada cocotb (WSL, cocotb 2.0.1 + Verilator 5.046) sobre los criterios
reabiertos. Evidencia en commits `0250200` (criterio 5) y `345d7af`
(criterio 7) y este report.

### Criterio 5 — CERRADO (schemaId/version + MAX_MSG)

- RTL: puerta en `DS_HDR` — el subset de libro decodifica solo si
  `template in {46,47,52,53}` **y** `schema_id==1` **y** `version==12`;
  cualquier otra combinación va a passthrough (w0/w1 + cuerpo crudo).
- Golden: `encode_message` default `schema_id=SCHEMA_ID` (firma real del
  schema pinned `id=1 version=12`) para que corpus y oráculo usen la firma
  correcta.
- Tests nuevos: **M3-PASS-02** (subset con firma inválida → passthrough) y
  **M3-SIZE-01/02** (msg_size 256 aceptado, 257 → error + recuperación).
- Evidencia: suite MDP3 DW=32 **11/11** y DW=64 **11/11** en el run del loop
  (antes de añadir 04/BP), gate B limpio, gate E 9/9.
- Hallazgo encadenado: el oráculo con firma correcta destapó un bug
  preexistente de decodificación de grupos (ver criterio 7) que no bloquea
  el criterio 5.

### Criterio 10 — CERRADO (backpressure de salida)

- El emisor del RTL ya retiene la tupla de salida bajo backpressure
  (`m_axis_tdata/tvalid/tlast` no cambian mientras `m_axis_tready=0`; la
  línea `if (!m_axis_tvalid || m_axis_tready)` solo avanza en handshake).
- Test nuevo **M3-BP-01**: `drive_and_collect(tready_high=False)` —
  backpressure de salida cada 3 ciclos; la salida final es bit a bit vs el
  golden (sin pérdida ni duplicación).
- Evidencia: M3-BP-01 1/1 PASS (DW=32); suite completa DW=32 y DW=64
  **12/12 PASS + 2 SKIP**.

### Criterio 7 — ABIERTO (máscaras con huecos / parcial sin tlast)

- Hallazgo: la validación de máscaras MSB-contiguas y el descarte del
  paquete inválido NO están implementados en el RTL. Se intentó
  implementar (`tk_contiguo`/`discard`) pero el descarte emite records
  parciales del paquete inválido (got duplica el record) y el fix no
  convergió en esta pasada.
- Tests `M3-INV-04a/04b` en **skip estático** (`@cocotb.test(skip=True)`)
  con el contrato documentado en la spec (addendum criterio 7). El RTL
  quedó revertido a limpio (sin validación de máscara).
- **Loop de robustez aparte**: requiere un descarte correcto del burst
  inválido (consumir el paquete hasta tlast sin emitir records parciales).
- Evidencia honesta: suite verde sin el criterio 7 (12/12 + 2 SKIP both DW);
  el criterio 7 NO se presenta cerrado.

### Estado final de los criterios de fase 4

| Criterio | Estado |
|---|---|
| 1 (golden MDP3) | cerrado (histórico) |
| 2 (framing) | cerrado (brazo tkeep, 18/18) |
| 3 (régimen entrada) | cerrado (M3-FRM-03) |
| 4 (subset decodificado) | cerrado (M3-SUB) |
| **5 (schema/version + MAX_MSG)** | **CERRADO (2026-08-19)** |
| 6 (gaps) | cerrado (M3-GAP) |
| **7 (robustez/máscaras)** | **ABIERTO** (criterio 7, loop de robustez) |
| 8 (regresión) | parcial: framing verde; máscaras fuera |
| 9 (lint/schema) | gate B verilator limpio; **gate C verible EJECUTADO (0 hallazgos, 2026-08-19)**; checker XML↔RTL pendiente |
| **10 (backpressure salida)** | **CERRADO (2026-08-19)** |

### Gate C — verible (2026-08-19, WSL)

Verible `v0.0-4148-g1ea007ec` instalado en el venv del repo (release oficial
de ChipsAlliance, tarball `linux-static-x86_64`). Ejecutado con la config del
repo (`--rules_config_search`, `./.rules.verible_lint`):

```text
$ verible-verilog-lint --rules_config_search rtl/parser/mdp3_parser.sv
(0 salidas — sin hallazgos)
```

**Gate C fase 4: PASS** — `mdp3_parser.sv` sin hallazgos de verible. Las fases
1-3 (RTL cerrado y verificado) conservan hallazgos de convención ya
documentados en su campaña y no se renombran constantes verificadas
(política del repo): itch_parser 21, orderbook 75, itch_chain 8 — todos de
estilo (tipos de parámetros, `always_ff` con bloqueantes para locals,
line-length), ninguno de funcionalidad.
| Timing | NO EJECUTADO (sin Vivado MDP3) |
