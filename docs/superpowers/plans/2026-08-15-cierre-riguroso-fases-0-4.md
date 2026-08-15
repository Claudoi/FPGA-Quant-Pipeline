# Cierre riguroso de fases 0-4 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminar los falsos verdes detectados en la auditoría, restaurar gates reproducibles y cerrar cada fase hasta su límite honesto de evidencia local.

**Architecture:** Se trabaja campaña por campaña, sin mezclar el oráculo con el DUT en un mismo commit. Cada tarea actualiza primero el contrato, demuestra un rojo, aplica el cambio mínimo, reejecuta los gates aplicables y deja un commit Conventional Commit en español.

**Tech Stack:** Python 3.11 stdlib, unittest, SystemVerilog, Cocotb 2.0.1, Verilator 5.050, Tcl/XDC Vivado.

**Spec:** `AGENTS.md` y `specs/<campaña>/spec.md` + `gherkin/` de cada fase.

## Global Constraints

- El RTL empieza en payload MoldUDP64 ya decapsulado; MAC/Ethernet/IP/UDP siguen fuera de alcance.
- Datos reales y schema CME permanecen ignorados y nunca se añaden a Git.
- El golden es independiente del RTL y nunca se deriva del DUT.
- Todo cambio funcional sigue rojo→verde; no se rebaja `--Wall` ni un umbral para pasar.
- Gate no ejecutado se declara `NO EJECUTADO`; fase 3 no cierra sin WNS/TNS/utilización Vivado.
- Documentación y commits en español; Conventional Commits; staging selectivo por campaña.
- No se usan subagentes en esta ejecución; los checkpoints son commits locales por sección.
- Los comandos Python usan `VENV_BIN=/Volumes/WD_Black/FPGA/.venv/bin`; el entorno no se copia ni se versiona dentro del worktree.

---

### Task 1: Restaurar la integridad semántica del golden CME MDP3

**Files:**
- Modify: `specs/fase4-mdp3-parser/spec.md`
- Modify: `specs/fase4-mdp3-parser/gherkin/mdp3.feature`
- Modify: `golden_model/tests/test_mdp3.py`
- Modify: `golden_model/mdp3/codec.py`
- Modify: `specs/fase4-mdp3-parser/verify-report.md`

**Interfaces:**
- Consumes: `encode_message(schema, template_id, values) -> bytes` y `decode_message(schema, PacketMessage) -> dict`.
- Produces: codificación que conserva valores root, composites y grupos para templates 46/47/52/53.

- [x] **Step 1: Endurecer spec y Gherkin antes del código**

Añadir a M3-GEN-01 que los vectores conocidos contienen valores no cero y que `decode(encode(values))` conserva campo por campo los valores observables, incluido `PRICE9.mantissa` y grupos multi-entry.

- [x] **Step 2: Escribir los tests semánticos que fallen**

Construir mensajes literales 46/47/52/53; para cada uno, parsear el paquete y asertar valores como `TransactTime`, `SecurityID`, `OrderID`, `MDEntryPx.mantissa`, `MDDisplayQty` y `MDUpdateAction`, no solo presencia de claves.

- [x] **Step 3: Ejecutar el rojo específico**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 "$VENV_BIN/python" -m unittest \
  golden_model.tests.test_mdp3.TestM3Gen.test_m3gen01_el_encoder_preserva_valores_no_cero_del_subset -v
```

Expected: FAIL porque al menos `TransactTime`, `OrderID` o `SecurityID` decodifica como cero.

- [x] **Step 4: Implementar la escritura mínima sobre el buffer original**

Añadir en `codec.py` un helper privado que codifique en un `bytearray` temporal y copie sus bytes al rango exacto del destino:

```python
def _put_value(schema: Schema, type_name: str, value, target: bytearray, offset: int):
    encoded = bytearray()
    _encode_value(schema, type_name, value, encoded)
    target[offset:offset + len(encoded)] = encoded
```

Usarlo para root y fields de grupos; no añadir dependencias ni cambiar el formato público.

- [x] **Step 5: Ejecutar verde específico y regresión Python**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 "$VENV_BIN/python" -m unittest golden_model.tests.test_mdp3 -v
PYTHONDONTWRITEBYTECODE=1 "$VENV_BIN/python" -m unittest discover -s golden_model/tests -t . -v
```

Expected: todos los tests pasan y los valores no cero se conservan.

- [x] **Step 6: Rebaselinar RTL MDP3 contra el golden corregido**

Run:

```bash
PATH="$VENV_BIN:$PATH" PYTHONDONTWRITEBYTECODE=1 \
  make -C verification/testbenches/mdp3 sim
```

Expected inicial: rojo honesto; registrar primer desajuste, longitud y racha de backpressure sin suavizarlos.

- [x] **Step 7: Actualizar verify-report y commit de sección**

Documentar que la evidencia anterior de 4.000 round-trips era insuficiente y pegar rojo→verde real.

```bash
git add specs/fase4-mdp3-parser golden_model/mdp3/codec.py golden_model/tests/test_mdp3.py
git commit -m "fix(fase4-mdp3): preservar valores semánticos en el golden SBE"
```

### Task 2: Incorporar la regresión real pendiente de fase 0

**Files:**
- Modify: `specs/fase0-golden-model/verify-report.md`
- Modify: `specs/fase1-parser-rtl/verify-report.md`

**Interfaces:**
- Consumes: `run_golden` sobre `01302019.NASDAQ_ITCH50.gz`.
- Produces: evidencia fechada del segundo día sin versionar datos ni outputs crudos.

- [x] **Step 1: Verificar el artefacto local y repetir la regresión si el resumen temporal no está disponible**

```bash
PYTHONDONTWRITEBYTECODE=1 "$VENV_BIN/python" -m golden_model.scripts.run_golden \
  data/itch_sample/01302019.NASDAQ_ITCH50.gz --out /tmp/fpga-fase0-0130
```

Expected: 368.366.634 mensajes, 8.713 símbolos, 0 anomalías, 63 `cross_events`.

- [x] **Step 2: Actualizar ambos informes sin declarar gates no ejecutados**

Reemplazar la nota de fichero ausente por el comando, resumen y fecha reales. Mantener Gate C/cobertura/timing con su estado previo.

- [x] **Step 3: Reejecutar el golden completo de tests y commit**

```bash
PYTHONDONTWRITEBYTECODE=1 "$VENV_BIN/python" -m unittest discover -s golden_model/tests -t .
git add specs/fase0-golden-model/verify-report.md specs/fase1-parser-rtl/verify-report.md
git commit -m "docs(fase0): adjuntar regresión completa del segundo día Nasdaq"
```

### Task 3: Hacer literal y reproducible el contrato del parser ITCH

**Files:**
- Modify: `specs/fase1-parser-rtl/spec.md`
- Modify: `specs/fase1-parser-rtl/gherkin/datapath.feature`
- Modify: `specs/fase1-parser-rtl/gherkin/parser.feature`
- Modify: `verification/testbenches/parser/test_itch_parser.py`
- Modify: `rtl/parser/itch_parser.sv`
- Modify: `scripts/verify/mutate_parser.py`
- Modify: `specs/fase1-parser-rtl/verify-report.md`

**Interfaces:**
- Consumes: payload MoldUDP64 y AXI-Stream existente.
- Produces: validación de longitudes para los 22 tipos, recuperación real tras truncado y mutantes aplicables al RTL parametrizado.

- [x] **Step 1: Alinear contrato de throughput**

Cambiar LIN-01 Gherkin para describir cuatro mensajes A/U de tamaño medio, QB=64 y stalls acotados `<=24`; mantener explícitamente como non-goal el feed infinito de mensajes mínimos. Corregir SEC-LIN-01 para usar un tipo H real fuera del subset.

- [x] **Step 2: Añadir rojos de tipos no-subset y recuperación**

Tests nuevos o reforzados:

```text
H con longitud 25 entre dos A -> no salida para H, sí para ambos A, cero error
H con longitud declarada 24 -> error y siguiente A íntegro
paquete con A + A truncado, seguido de paquete con A íntegro -> 1 error y dos A válidos
sesión nueva, seq=100, count=0; siguiente paquete seq=100 -> cero gap
```

- [x] **Step 3: Ejecutar los rojos dirigidos**

Usar `COCOTB_TEST_FILTER`/`TESTCASE` para cada test y registrar el fallo observable, no solo timeout.

- [x] **Step 4: Implementar tabla literal de 22 longitudes y flush de datagrama truncado**

Extender `explen` con las longitudes de `golden_model/itch/messages.py`; una longitud conocida incorrecta pulsa `error`. Al ver truncado por `tlast`, descartar los bytes residuales del datagrama antes de volver a `ST_HDR`. Resolver la doble asignación de `exp_seq` en cambio de sesión + `count=0` usando el `seq` del header.

- [x] **Step 5: Actualizar los tres mutantes parametrizados**

Reemplazar patrones 64-bit obsoletos por expresiones vigentes basadas en `BYTES`, `DW` y `cbody`; ejecutar primero cada mutante y después el runner completo.

- [x] **Step 6: Gates de fase 1**

```bash
PATH="$VENV_BIN:$PATH" make -C verification/testbenches/parser sim
verilator --lint-only --Wall --top-module itch_parser rtl/parser/itch_parser.sv
PATH="$VENV_BIN:$PATH" python3 scripts/verify/mutate_parser.py
```

Expected: 0 fallos, 0 warnings y todos los mutantes aplicados/matados.

- [x] **Step 7: Informe y commit**

```bash
git add specs/fase1-parser-rtl rtl/parser/itch_parser.sv \
  verification/testbenches/parser/test_itch_parser.py scripts/verify/mutate_parser.py
git commit -m "fix(fase1): cerrar validación y recuperación del framing ITCH"
```

### Task 4: Restaurar los gates y espejos del order book DW64

**Files:**
- Modify: `specs/fase2-orderbook/gherkin/orderbook.feature`
- Modify: `verification/testbenches/orderbook/test_orderbook.py`
- Modify: `rtl/orderbook/orderbook.sv`
- Modify: `specs/fase2-orderbook/verify-report.md`

**Interfaces:**
- Consumes: records Anexo A DW64.
- Produces: suite oficial `--Wall` limpia, overflow observable y libro vacío realmente probado.

- [ ] **Step 1: Escribir/fortalecer rojos**

`SEC-OV-01` debe muestrear al menos un pulso `error`, no emitir el cancel inválido y aceptar un mensaje válido posterior. `BBO-02` debe mantener un segundo locate vacío mientras opera el primero y demostrar ausencia de contaminación.

- [ ] **Step 2: Verificar rojos**

Ejecutar ambos tests por filtro; el primero debe fallar porque el helper actual no devuelve errores y el segundo porque el vector actual no contiene un símbolo vacío.

- [ ] **Step 3: Arreglar el warning sin silenciarlo**

En `swap_next`, sustituir la rama DW64 `nx_bi >= 4'd0 && lt(nx_type)` por `lt(nx_type)`.

- [ ] **Step 4: Verde completo y mutación**

```bash
PATH="$VENV_BIN:$PATH" make -C verification/testbenches/orderbook sim
verilator --lint-only --Wall --top-module orderbook rtl/orderbook/orderbook.sv
PATH="$VENV_BIN:$PATH" python3 scripts/verify/mutate_orderbook.py
```

- [ ] **Step 5: Informe y commit**

```bash
git add specs/fase2-orderbook rtl/orderbook/orderbook.sv \
  verification/testbenches/orderbook/test_orderbook.py
git commit -m "fix(fase2): restaurar gates y observabilidad del order book"
```

### Task 5: Cerrar integración parametrizada y preparar evidencia Vivado de fase 3

**Files:**
- Modify: `verification/testbenches/phase3/test_chain32.py`
- Modify: `rtl/itch_chain.sv`
- Modify: `synth/constraints/fase3_322mhz.xdc`
- Modify: `synth/fase3_synth.tcl`
- Modify: `scripts/verify/synth_check.py`
- Modify: `specs/fase3-optimizacion/verify-report.md`
- Modify: `specs/fase3-uram/verify-report.md`

**Interfaces:**
- Consumes: parámetros `ND`, `QB`, `K`, `NSYM` del top.
- Produces: `ND` propagado, constraints auditables y todos los shards reproducibles.

- [ ] **Step 1: Test rojo de ND distinto de 5**

Elaborar `itch_chain` con `ND=3`, conducir tres niveles por lado y comparar `depth_tdata` de 384 bits contra golden. Debe fallar o no elaborar mientras `.ND(ND)` no llegue al book.

- [ ] **Step 2: Propagar ND mínimamente**

Añadir `.ND(ND)` a la instancia `u_book`; no cambiar el layout.

- [ ] **Step 3: Endurecer Tcl/XDC**

Añadir `check_timing -verbose`, `report_methodology`, informe de clocks y constraints. Restringir o documentar de forma explícita los puertos de ready/reset/estado; añadir delays mínimos coherentes con el wrapper supuesto, sin inventar una placa física.

- [ ] **Step 4: Extender synth_check**

El checker debe fallar si faltan `.ND(ND)`, `check_timing`, `report_methodology`, delays min/max o un puerto top queda fuera de la política declarada.

- [ ] **Step 5: Regresión completa local**

```bash
PATH="$VENV_BIN:$PATH" make -C verification/testbenches/phase3 sim
PATH="$VENV_BIN:$PATH" make -C verification/testbenches/phase3 sim-hash
PATH="$VENV_BIN:$PATH" make -C verification/testbenches/phase3 sim-depth
PATH="$VENV_BIN:$PATH" make -C verification/testbenches/phase3 sim-hard
PATH="$VENV_BIN:$PATH" make -C verification/testbenches/phase3 sim-parser
PATH="$VENV_BIN:$PATH" make -C verification/testbenches/phase3 sim-chain
PATH="$VENV_BIN:$PATH" make -C verification/testbenches/phase3 sim-lat
PATH="$VENV_BIN:$PATH" make -C verification/testbenches/uram sim-uram
python3 scripts/verify/synth_check.py
```

- [ ] **Step 6: Intentar Vivado y declarar la frontera real**

Si `vivado` y la licencia están disponibles, ejecutar `vivado -mode batch -source fase3_synth.tcl` desde `synth/` y exigir WNS>=0, TNS=0, cero endpoints relevantes sin constraint y utilización URAM. Si no están disponibles, pegar el error real y mantener fase 3 abierta.

- [ ] **Step 7: Informe y commit**

```bash
git add rtl/itch_chain.sv verification/testbenches/phase3 \
  synth scripts/verify/synth_check.py specs/fase3-optimizacion specs/fase3-uram
git commit -m "fix(fase3): cerrar parametrización y rigor de síntesis"
```

### Task 6: Completar el RTL CME MDP3 contra el golden fiable

**Files:**
- Modify: `specs/fase4-mdp3-parser/spec.md`
- Modify: `specs/fase4-mdp3-parser/gherkin/mdp3.feature`
- Modify: `verification/testbenches/mdp3/Makefile`
- Modify: `verification/testbenches/mdp3/test_mdp3_framing.py`
- Modify: `rtl/parser/mdp3_parser.sv`
- Modify: `specs/fase4-mdp3-parser/verify-report.md`

**Interfaces:**
- Consumes: paquetes CME MDP3 schema v12, DW32/DW64, AXI-Stream con tlast por paquete.
- Produces: records Anexo M bit a bit, passthrough y señales gap/error según criterios 2-9.

- [ ] **Step 1: Corregir la medición de stalls y construir el mínimo literal**

Contar stall solo con `s_axis_tvalid && !s_axis_tready`. Construir el template 47 mínimo de manera literal, sin generador aleatorio, y añadir targets separados DW32/DW64.

- [ ] **Step 2: Cerrar M3-FRM-01/02/03 por rojo→verde**

Usar el primer byte divergente para localizar el handoff de `CS_BODY`/buffers ping-pong; corregir solo la contabilidad demostrada por el rojo. Exigir longitud y contenido completos, además de racha de stalls <=16 en el vector mínimo pactado.

- [ ] **Step 3: Añadir y cerrar subset/passthrough**

Tests por template 46/47/52/53 con valores no cero y multi-entry; template conocido no-subset y template 777 desconocido deben preservar cuerpo crudo.

- [ ] **Step 4: Añadir y cerrar gaps e inválidos**

Vectores: salto de MsgSeqNum, reinicio de canal, `msg_size` 0/1/9/mayor que paquete, tlast truncado, `numInGroup` cuyo cuerpo excede `msg_size`, ReferenceID fuera de rango.

- [ ] **Step 5: Checker schema v12**

Añadir un test Python que lea los localparams de offsets/block lengths del RTL y los contraste contra `templates_FixBinary_v12.xml`; el RTL sigue especializado, pero el drift deja de ser silencioso.

- [ ] **Step 6: Gates de fase 4 y regresión 0-3**

```bash
PATH="$VENV_BIN:$PATH" make -C verification/testbenches/mdp3 sim
PATH="$VENV_BIN:$PATH" make -C verification/testbenches/mdp3 sim-dw64
verilator --lint-only --Wall --top-module mdp3_parser rtl/parser/mdp3_parser.sv
PYTHONDONTWRITEBYTECODE=1 "$VENV_BIN/python" -m unittest discover -s golden_model/tests -t .
```

Reejecutar después los comandos autoritativos de parser, orderbook, phase3 y URAM.

- [ ] **Step 7: Informe y commit**

```bash
git add specs/fase4-mdp3-parser rtl/parser/mdp3_parser.sv \
  verification/testbenches/mdp3 golden_model/tests
git commit -m "feat(fase4-mdp3): cerrar framing y Anexo M contra golden fiable"
```

### Task 7: Auditoría final del árbol y entrega de la rama

**Files:**
- Modify only if evidence is stale: `AGENTS.md`, `README.md`, `docs/DESARROLLO.md`

**Interfaces:**
- Consumes: todos los commits y outputs de Tasks 1-6.
- Produces: estado maestro coherente y rama lista para integración.

- [ ] **Step 1: Reejecutar gates completos desde builds limpios**

Limpiar únicamente `sim_build*` de cada área mediante sus Makefiles y ejecutar todos los comandos de `AGENTS.md` más shards de fase 3/MDP3.

- [ ] **Step 2: Reconciliar spec↔Gherkin↔tests**

Extraer todos los IDs de escenarios y comprobar que cada uno tiene test o estado pendiente explícito; ningún `return` por pcap ausente puede contar como evidencia real.

- [ ] **Step 3: Revisar datos y diff**

```bash
git status --short --ignored
git diff --check a765d9a..HEAD
git ls-files | rg '\.(pcap|NASDAQ_ITCH50\.gz)$' && exit 1 || true
```

- [ ] **Step 4: Commit documental final si es necesario**

```bash
git add AGENTS.md README.md docs/DESARROLLO.md
git commit -m "docs: reconciliar estado verificable de las fases 0 a 4"
```

- [ ] **Step 5: Verificación final y opciones de integración**

Aplicar `superpowers:verification-before-completion` y después `superpowers:finishing-a-development-branch`; no mergear ni pushear sin elección explícita del owner.
