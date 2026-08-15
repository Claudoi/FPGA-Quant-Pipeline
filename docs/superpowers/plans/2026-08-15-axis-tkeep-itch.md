# AXI `tkeep` para ITCH y cadena de fase 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hacer que `itch_parser` y `itch_chain` consuman datagramas AXI-Stream físicamente representables mediante `s_axis_tkeep`, sin incorporar padding, cruzar límites de paquete ni perder recuperación tras framing inválido.

**Architecture:** Se conserva la cola compacta existente de `itch_parser` y se cambia únicamente su frontera de entrada: cada handshake aporta entre 1 y `DW/8` bytes válidos, siempre como prefijo MSB. Un estado de descarte drena el datagrama inválido hasta su `tlast`; el cierre lógico `count` se valida contra el cierre físico. `itch_chain` solo propaga el nuevo puerto y el Anexo A interno permanece sin `tkeep`.

**Tech Stack:** SystemVerilog sintetizable, cocotb 2.x, Verilator `--Wall`, Python 3.11, Tcl/XDC de Vivado, `unittest` y scripts de mutación del repositorio.

**Spec:** `docs/superpowers/specs/2026-08-15-axis-tkeep-framing-design.md`, `specs/fase1-parser-rtl/spec.md`, `specs/fase1-parser-rtl/gherkin/framing.feature`, `specs/fase1-parser-rtl/gherkin/replay.feature`, `specs/fase3-optimizacion/spec.md` y `specs/fase3-uram/spec.md`.

## Global Constraints

- Trabajar en `codex/cierre-riguroso-fases-0-4` y comprobar árbol limpio antes de cada tarea.
- Seguir rojo→verde: el primer rojo puede ser la ausencia del puerto; los rojos posteriores deben ser funcionales.
- Solo se verifican y soportan `DW=32` y `DW=64`; no ampliar ni hacer claims
  sobre otros anchos.
- `tkeep[k]` califica `tdata[8*k +: 8]`, pero el stream es MSB-first: solo se acepta todo unos o un prefijo MSB contiguo en el beat final.
- Un error no revierte registros Anexo A ya emitidos. Cancela el mensaje parcial y drena el datagrama defectuoso.
- No añadir FIFO, adaptador, dependencia, puerto de salida `tkeep` ni cambios al order book.
- El replay real se ejecuta solo si existe `/tmp/real_subset.pcap`; si falta, cocotb debe declararlo `SKIP`, nunca `PASS` anticipado.
- Cada commit usa español y Conventional Commits. No mezclar hallazgos MDP3, schema/version, `MAX_MSG`, backpressure de salida ni timing físico de Vivado.

## File Responsibilities

| Archivo | Responsabilidad en este plan |
|---|---|
| `verification/testbenches/parser/test_itch_parser.py` | Helper canónico `(data, keep, last)`, monitor de estabilidad y casos AXI-KEEP DW=64. |
| `rtl/parser/itch_parser.sv` | Puerto `s_axis_tkeep`, conteo/compactación por byte válido, descarte y cierre exacto `count↔tlast`. |
| `verification/testbenches/phase3/test_parser32.py` | Reutilizar el helper canónico y validar framing DW=32. |
| `rtl/itch_chain.sv` | Propagar `s_axis_tkeep` al parser, sin tocar el enlace Anexo A. |
| `verification/testbenches/phase3/test_chain32.py` | Emitir cada datagrama por separado y comprobar cadena DW=32, incluido `ND=3`. |
| `verification/testbenches/phase3/test_lat32.py` | Adaptar la fuente de latencia al nuevo puerto sin alterar la métrica. |
| `verification/testbenches/uram/test_anx32.py` | Hereda `drive_raw32`; regresión del Anexo A recortado. |
| `synth/constraints/fase3_322mhz.xdc` | Delays min/max de `s_axis_tkeep[*]`. |
| `scripts/verify/synth_check.py` | Se usa sin ampliar su alcance: debe detectar el puerto sin constraint. |
| `scripts/verify/mutate_parser.py` | Mutantes de orientación, máscara, conteo, drenaje y cierre exacto. |
| `specs/fase1-parser-rtl/verify-report.md` | Output real de gates A–G y estado del replay. |
| `specs/fase3-optimizacion/verify-report.md` | Evidencia nueva de parser/chain DW=32 y coherencia XDC. |
| `specs/fase3-uram/verify-report.md` | Regresión ANX/chain afectada; sin declarar timing cerrado. |

---

## Task 1: Crear el rojo reproducible de framing ITCH DW=64

**Files:**

- Modify: `verification/testbenches/parser/test_itch_parser.py`
- Test: `verification/testbenches/parser/test_itch_parser.py`

- [ ] **Step 1: Sustituir la formación global de words por beats por datagrama**

  Añadir un único helper reutilizable y hacer que todos los drivers de entrada del archivo lo consuman:

  ```python
  def packet_beats(payloads, bytes_per_word):
      beats = []
      for payload in payloads:
          assert payload, "un datagrama no puede carecer de beat final"
          for offset in range(0, len(payload), bytes_per_word):
              chunk = payload[offset:offset + bytes_per_word]
              shift = 8 * (bytes_per_word - len(chunk))
              data = int.from_bytes(chunk, "big") << shift
              keep = ((1 << len(chunk)) - 1) << (bytes_per_word - len(chunk))
              last = offset + len(chunk) == len(payload)
              beats.append((data, keep, last))
      return beats
  ```

  Inicializar `dut.s_axis_tkeep.value = 0` en `_reset`. Mientras `tvalid && !tready`, guardar y comparar exactamente `(tdata, tkeep, tlast)` en cada driver; incrementar un contador `accepted_tlast` solo en handshake.

- [ ] **Step 2: Añadir los tests rojos de SEC-FRM-04..08**

  Incorporar estos tests con nombres espejo de Gherkin:

  - `test_sec_frm05_datagramas_no_alineados_no_comparten_beat`: dos `_packet_seq` de longitudes no múltiplo de 8, dos handshakes `tlast`, salida igual a `run_oracle_packets`.
  - `test_sec_frm04_count_cero_parcial_msb_y_recuperacion`: header MoldUDP64 de 20 bytes, `tkeep` final `8'b11110000`, seguido de paquete con mensaje válido; cero `error` y solo el segundo record.
  - `test_sec_frm07_count_tlast_cierre_exacto`: subcasos `count` menor, `count` mayor y `count=0` con payload; cada uno observa `error`, ausencia de header falso y recuperación con un paquete válido.
  - `test_sec_frm06_tkeep_invalido_descarta_y_recupera`: tabla con `0x00`, `0b10100000`, `0b01111111` y `0b11110000` sin `tlast`; observa un pulso `error`, drenaje y posterior salida válida.
  - `test_sec_frm08_fuente_estable_bajo_backpressure_entrada`: fuerza la cola a bajar `tready` y falla si cambia cualquier miembro de `(data, keep, last)` antes del handshake.
  - `test_axi_keep_orientacion_msb_lsb`: `0b11000000` produce el stream esperado y `0b00000011` se rechaza.

- [ ] **Step 3: Hacer honesto REP-02 y cubrir truncados 1..7 bytes**

  Definir `REAL_PCAP = "/tmp/real_subset.pcap"` y cambiar el decorador del test
  existente a `@cocotb.test(skip=not os.path.exists(REAL_PCAP))`. Eliminar
  cualquier `return` por fichero ausente. Conservar los payloads separados al
  decapsular y exigir `accepted_tlast == len(payloads)`. Extender
  `test_sec_frm01_frame_truncado` con faltantes `range(1, 8)`, un mensaje
  completo anterior y un paquete posterior válido.

- [ ] **Step 4: Ejecutar el primer rojo desde build limpio**

  Run:

  ```bash
  make -C verification/testbenches/parser clean
  make -C verification/testbenches/parser sim \
    TESTCASE=test_sec_frm05_datagramas_no_alineados_no_comparten_beat
  ```

  Expected: FAIL al resolver `dut.s_axis_tkeep` porque `itch_parser` aún no
  expone el puerto. Guardar este output para el verify-report; no contabilizarlo
  como gate pasado.

- [ ] **Step 5: Comprobar que el diff solo contiene tests rojos**

  Run:

  ```bash
  git diff --check
  git diff -- verification/testbenches/parser/test_itch_parser.py
  ```

  No crear commit todavía: el commit se hace al cerrar el verde de la misma capacidad.

## Task 2: Implementar `s_axis_tkeep` y recuperación en `itch_parser`

**Files:**

- Modify: `rtl/parser/itch_parser.sv`
- Test: `verification/testbenches/parser/test_itch_parser.py`

- [ ] **Step 1: Añadir el puerto sin ampliar los anchos soportados**

  Añadir junto a `s_axis_tdata`:

  ```systemverilog
  input wire [DW/8-1:0] s_axis_tkeep,
  ```

  Mantener `localparam BYTES = DW / 8;`. Los únicos builds de cierre son los
  de 32 y 64 bits; no añadir lógica para otros anchos.

- [ ] **Step 2: Calcular número de bytes y validez sin inspeccionar lanes inválidos**

  Añadir dos funciones locales pequeñas:

  ```systemverilog
  function automatic [7:0] keep_nbytes(input logic [BYTES-1:0] keep);
      keep_nbytes = 0;
      for (int k = 0; k < BYTES; k++)
          keep_nbytes = keep_nbytes + keep[k];
  endfunction

  function automatic logic keep_is_msb_prefix(input logic [BYTES-1:0] keep);
      logic seen_zero;
      begin
          seen_zero = 1'b0;
          keep_is_msb_prefix = (keep != '0);
          for (int k = BYTES-1; k >= 0; k--) begin
              if (!keep[k]) seen_zero = 1'b1;
              else if (seen_zero) keep_is_msb_prefix = 1'b0;
          end
      end
  endfunction
  ```

  Definir `in_nbytes`, `keep_shape_ok` e `in_keep_ok = keep_shape_ok && (s_axis_tlast || s_axis_tkeep == {BYTES{1'b1}})`; usar sus valores solo cuando `in_take` sea cierto.

- [ ] **Step 3: Compactar únicamente el prefijo válido en la cola existente**

  Sustituir los incrementos y checks de capacidad por `in_nbytes`. La alineación mínima conserva el dato MSB-first:

  ```systemverilog
  wire [DW-1:0] in_compact =
      s_axis_tdata >> (8 * (BYTES - in_nbytes));
  ```

  Para una ocupación `base_n`, insertar con desplazamiento `8 * (QB - base_n - in_nbytes)` y actualizar `qn` con `in_nbytes`. No leer `s_axis_tdata` si `in_keep_ok` es falso. Mantener las dos ramas actuales, con y sin `drain_active`, pero compartir la misma expresión de append para no duplicar la orientación.

- [ ] **Step 4: Añadir descarte de datagrama con prioridad inequívoca**

  Añadir `drop_packet`. El orden del bloque secuencial debe ser: reset; beat de descarte; beat inválido; operación normal de cola/FSM. Al aceptar máscara inválida:

  ```systemverilog
  error       <= 1'b1;
  q           <= '0;
  qn          <= '0;
  eop_seen    <= 1'b0;
  drain_active <= 1'b0;
  drop_packet <= !s_axis_tlast;
  st          <= ST_HDR;
  ```

  Mientras `drop_packet`, `s_axis_tready` permanece alto, no se toca `q`, y el estado vuelve a aceptar cabecera tras el handshake con `tlast`. No reiniciar `msg_idx`, `exp_seq` ni salidas ya emitidas.

- [ ] **Step 5: Hacer exacto el cierre MoldUDP64 `count↔tlast`**

  Calcular en un único sitio la ocupación efectiva tras drenaje y posible append válido. En `count=0` y al finalizar el mensaje número `count`, aceptar cierre solo si simultáneamente:

  ```systemverilog
  eop_eff && qn_post == 0
  ```

  Si quedan bytes válidos, emitir `error`, limpiar el paquete y no reinterpretarlos. Si se agotó `count` antes de ver `tlast`, emitir `error` y activar `drop_packet` hasta el final físico. Si `tlast` llega con mensaje incompleto, conservar los records anteriores, cancelar el parcial y quedar en `ST_HDR`.

- [ ] **Step 6: Ejecutar verdes dirigidos y suite completa DW=64**

  Run:

  ```bash
  make -C verification/testbenches/parser clean
  make -C verification/testbenches/parser sim \
    TESTCASE=test_sec_frm05_datagramas_no_alineados_no_comparten_beat
  make -C verification/testbenches/parser clean
  make -C verification/testbenches/parser sim \
    TESTCASE=test_sec_frm06_tkeep_invalido_descarta_y_recupera
  make -C verification/testbenches/parser clean
  make -C verification/testbenches/parser sim \
    TESTCASE=test_sec_frm07_count_tlast_cierre_exacto
  make -C verification/testbenches/parser clean
  make -C verification/testbenches/parser sim
  ```

  Expected: todos los tests ejecutados PASS; REP-02 PASS con el pcap local o SKIP explícito si no existe.

- [ ] **Step 7: Lint y commit del loop ITCH DW=64**

  Run:

  ```bash
  verilator --lint-only --Wall --top-module itch_parser \
    rtl/parser/itch_parser.sv
  python3 -m py_compile verification/testbenches/parser/test_itch_parser.py
  git diff --check
  git status --short
  git add rtl/parser/itch_parser.sv \
    verification/testbenches/parser/test_itch_parser.py
  git commit -m "fix(parser): respetar tkeep y límites MoldUDP64"
  ```

## Task 3: Propagar el contrato a DW=32 y `itch_chain`

**Files:**

- Modify: `rtl/itch_chain.sv`
- Modify: `verification/testbenches/phase3/test_parser32.py`
- Modify: `verification/testbenches/phase3/test_chain32.py`
- Modify: `verification/testbenches/phase3/test_lat32.py`
- Test: `verification/testbenches/uram/test_anx32.py`

- [ ] **Step 1: Escribir el rojo DW=32 antes de tocar el top**

  Importar `packet_beats` desde `test_itch_parser` en `test_parser32.py` y
  `test_chain32.py`. Sustituir `_chunks32` y toda concatenación entre payloads.
  Añadir a `test_parser32.py`
  `test_p32_tkeep_invalido_y_truncados_recuperan`, que recorre cero, huecos,
  LSB parcial, parcial no-final y truncados de 1..3 bytes. Añadir a
  `test_chain32.py`
  `test_chain_tkeep_datagramas_no_alineados_y_estabilidad`.

  Run:

  ```bash
  make -C verification/testbenches/phase3 clean-all
  make -C verification/testbenches/phase3 sim-chain \
    TESTCASE=test_chain_tkeep_datagramas_no_alineados_y_estabilidad
  ```

  Expected: FAIL al resolver `dut.s_axis_tkeep` porque `itch_chain` carece del
  puerto.

- [ ] **Step 2: Propagar `s_axis_tkeep` sin modificar Anexo A**

  En `rtl/itch_chain.sv` añadir:

  ```systemverilog
  input wire [DW/8-1:0] s_axis_tkeep,
  ```

  y conectar `.s_axis_tkeep(s_axis_tkeep)` solo en `u_parser`. No añadir señal entre `u_parser` y `u_book`.

- [ ] **Step 3: Adaptar drivers y métrica de latencia**

  `drive_raw32`, `drive_pcap32`, `drive_chain` y `drive_lat` deben conducir `tkeep` desde `packet_beats`, contar handshakes `tlast` y vigilar estabilidad. `test_lat32.py` conserva los mismos puntos de muestreo y umbrales; solo cambia la representación física de la fuente. `test_anx32.py` reutiliza `drive_raw32` sin helper nuevo.

- [ ] **Step 4: Ejecutar matriz verde DW=32**

  Run:

  ```bash
  make -C verification/testbenches/phase3 clean-all
  make -C verification/testbenches/phase3 sim-parser
  make -C verification/testbenches/phase3 clean-all
  make -C verification/testbenches/phase3 sim-chain
  make -C verification/testbenches/phase3 clean-all
  make -C verification/testbenches/phase3 sim-chain-nd3
  make -C verification/testbenches/phase3 clean-all
  make -C verification/testbenches/phase3 sim-lat
  make -C verification/testbenches/uram clean-all
  make -C verification/testbenches/uram sim-anx
  ```

  Expected: PASS bit a bit. Los replays sin artefacto local aparecen como SKIP; el test de latencia informa su medición sin convertirla en cierre Vivado.

- [ ] **Step 5: Lint y commit de integración**

  Run:

  ```bash
  verilator --lint-only --Wall --top-module itch_parser -GDW=32 \
    rtl/parser/itch_parser.sv
  verilator --lint-only --Wall --top-module itch_chain -GDW=32 \
    rtl/itch_chain.sv rtl/parser/itch_parser.sv rtl/orderbook/orderbook.sv
  python3 -m py_compile \
    verification/testbenches/phase3/test_parser32.py \
    verification/testbenches/phase3/test_chain32.py \
    verification/testbenches/phase3/test_lat32.py
  git diff --check
  git add rtl/itch_chain.sv \
    verification/testbenches/phase3/test_parser32.py \
    verification/testbenches/phase3/test_chain32.py \
    verification/testbenches/phase3/test_lat32.py
  git commit -m "fix(fase3): propagar tkeep por la cadena ITCH"
  ```

## Task 4: Cubrir el nuevo puerto en XDC y síntesis estática

**Files:**

- Modify: `synth/constraints/fase3_322mhz.xdc`
- Verify: `scripts/verify/synth_check.py`

- [ ] **Step 1: Observar el rojo estático con el top ya ampliado**

  Run:

  ```bash
  python3 scripts/verify/synth_check.py
  ```

  Expected: FAIL porque los bits de `s_axis_tkeep` son puertos de entrada sin delay min/max. Si el script no falla, detener esta tarea y corregir su comprobación antes de modificar XDC; no aceptar un falso verde.

- [ ] **Step 2: Añadir el puerto a ambos delays de entrada**

  Modificar las dos listas de `set_input_delay` para incluir exactamente `s_axis_tkeep[*]`:

  ```tcl
  {rst_n s_axis_tdata[*] s_axis_tkeep[*] s_axis_tvalid s_axis_tlast bbo_tready depth_tready}
  ```

- [ ] **Step 3: Ejecutar el verde y revisar Tcl**

  Run:

  ```bash
  python3 scripts/verify/synth_check.py
  git diff --check
  git diff -- synth/constraints/fase3_322mhz.xdc
  ```

  Expected: PASS de coherencia Tcl/XDC/RTL. Documentar expresamente que no es WNS/TNS ni utilización de Vivado.

- [ ] **Step 4: Commit del contrato físico estático**

  Run:

  ```bash
  git add synth/constraints/fase3_322mhz.xdc
  git commit -m "fix(synth): constreñir tkeep en la cadena de fase 3"
  ```

## Task 5: Endurecer el gate de mutación ITCH

**Files:**

- Modify: `scripts/verify/mutate_parser.py`
- Test: `verification/testbenches/parser/test_itch_parser.py`

- [ ] **Step 1: Añadir mutantes exactos sobre identificadores estables**

  Mantener los 12 mutantes existentes y añadir:

  - `KEEP-ALL-BYTES`: sustituye el incremento por `in_nbytes` por `BYTES`.
  - `KEEP-LSB-FIRST`: invierte la orientación usada para compactar los lanes.
  - `KEEP-HOLES`: hace que `keep_is_msb_prefix` acepte cualquier máscara no cero.
  - `KEEP-PARTIAL-NONLAST`: elimina la exigencia de word completa si `!tlast`.
  - `KEEP-NODRAIN`: deja `drop_packet` bajo tras máscara inválida no final.
  - `COUNT-NO-EOP`: elimina `eop_eff` del cierre exacto.
  - `COUNT-RESIDUAL`: elimina `qn_post == 0` del cierre exacto.

  Cada `old` debe aparecer exactamente una vez; mantener el fallo duro del runner si aparece cero o más de una.

- [ ] **Step 2: Ejecutar cada mutante nuevo de forma dirigida**

  Run:

  ```bash
  python3 scripts/verify/mutate_parser.py --mutant KEEP-ALL-BYTES
  python3 scripts/verify/mutate_parser.py --mutant KEEP-LSB-FIRST
  python3 scripts/verify/mutate_parser.py --mutant KEEP-HOLES
  python3 scripts/verify/mutate_parser.py --mutant KEEP-PARTIAL-NONLAST
  python3 scripts/verify/mutate_parser.py --mutant KEEP-NODRAIN
  python3 scripts/verify/mutate_parser.py --mutant COUNT-NO-EOP
  python3 scripts/verify/mutate_parser.py --mutant COUNT-RESIDUAL
  ```

  Expected: todos compilan y al menos un test falla. Un mutante que no compila se corrige; no cuenta como muerto.

- [ ] **Step 3: Ejecutar el gate E completo y restauración limpia**

  Run:

  ```bash
  python3 scripts/verify/mutate_parser.py
  test ! -e rtl/parser/itch_parser.sv.bak
  git diff --check
  git status --short
  ```

  Expected: todos los mutantes `MATADO`, el RTL restaurado y sin artefacto `.bak`.

- [ ] **Step 4: Commit del gate adversarial**

  Run:

  ```bash
  git add scripts/verify/mutate_parser.py
  git commit -m "test(parser): mutar framing tkeep y cierre de paquete"
  ```

## Task 6: Ejecutar gates A–G y versionar evidencia ITCH/fase 3

**Files:**

- Modify: `specs/fase1-parser-rtl/verify-report.md`
- Modify: `specs/fase3-optimizacion/verify-report.md`
- Modify: `specs/fase3-uram/verify-report.md`
- Verify: `specs/gherkin-espejos.json`

- [ ] **Step 1: Ejecutar regresión funcional desde builds limpios**

  Run:

  ```bash
  python3 -m unittest discover -s golden_model/tests -t .
  make -C verification/testbenches/parser clean
  make -C verification/testbenches/parser sim
  make -C verification/testbenches/phase3 clean-all
  make -C verification/testbenches/phase3 sim-parser
  make -C verification/testbenches/phase3 clean-all
  make -C verification/testbenches/phase3 sim-chain
  make -C verification/testbenches/phase3 clean-all
  make -C verification/testbenches/phase3 sim-chain-nd3
  make -C verification/testbenches/phase3 clean-all
  make -C verification/testbenches/phase3 sim-lat
  make -C verification/testbenches/uram clean-all
  make -C verification/testbenches/uram sim-anx
  ```

- [ ] **Step 2: Ejecutar compilación, estilo y checks estáticos**

  Run:

  ```bash
  verilator --lint-only --Wall --top-module itch_parser \
    rtl/parser/itch_parser.sv
  verilator --lint-only --Wall --top-module itch_parser -GDW=32 \
    rtl/parser/itch_parser.sv
  verilator --lint-only --Wall --top-module itch_chain -GDW=32 \
    rtl/itch_chain.sv rtl/parser/itch_parser.sv rtl/orderbook/orderbook.sv
  if command -v verible-verilog-lint >/dev/null; then
    verible-verilog-lint rtl/parser/itch_parser.sv rtl/itch_chain.sv
  else
    echo "Gate C NO EJECUTADO: verible-verilog-lint no instalado"
  fi
  python3 scripts/verify/synth_check.py
  python3 scripts/verify/mutate_parser.py
  ```

- [ ] **Step 3: Verificar completitud literal Gherkin↔tests**

  Comprobar que cada uno de `SEC-FRM-04..08`, `REP-02`, `P32-01/02`, `CHAIN-01`, `ANX-01/02` aparece en spec/Gherkin, test y verify-report, y que no hay IDs duplicados:

  ```bash
  python3 - <<'PY'
  import json
  from pathlib import Path
  data = json.loads(Path("specs/gherkin-espejos.json").read_text())
  assert data
  norm = lambda value: value.lower().replace("-", "").replace("_", "")
  text = "\n".join(p.read_text() for p in Path("specs").rglob("*.feature"))
  parser_tests = Path("verification/testbenches/parser/test_itch_parser.py").read_text().lower()
  for case in ("SEC-FRM-04", "SEC-FRM-05", "SEC-FRM-06", "SEC-FRM-07", "SEC-FRM-08", "REP-02"):
      assert text.count(case) == 1, (case, text.count(case))
      assert norm(case) in norm(parser_tests), case
  scoped = {
      "P32-01": "verification/testbenches/phase3/test_parser32.py",
      "P32-02": "verification/testbenches/phase3/test_parser32.py",
      "CHAIN-01": "verification/testbenches/phase3/test_chain32.py",
      "ANX-01": "verification/testbenches/uram/test_anx32.py",
      "ANX-02": "verification/testbenches/uram/test_anx32.py",
  }
  for case, path in scoped.items():
      assert norm(case) in norm(Path(path).read_text()), case
  print("IDs ITCH/fase 3 únicos y mapas a tests completos")
  PY
  ```

- [ ] **Step 4: Sustituir evidencia obsoleta en verify-reports**

  Pegar outputs reales con fecha 2026-08-15. Registrar el conteo de PASS/FAIL/SKIP, los handshakes `tlast` del replay, lint, mutación y `synth_check.py`. Marcar Gate C `NO EJECUTADO` si falta Verible. Mantener fase 3 `NO CERRADA` mientras falten WNS/TNS y utilización Vivado; no conservar como vigente evidencia producida por el driver que concatenaba datagramas.

- [ ] **Step 5: Autorrevisión final y commit de evidencia**

  Run:

  ```bash
  rg -n "PASS|FAIL|SKIP|NO EJECUTADO|WNS|TNS|tlast|tkeep" \
    specs/fase1-parser-rtl/verify-report.md \
    specs/fase3-optimizacion/verify-report.md \
    specs/fase3-uram/verify-report.md
  rg -n "TODO|TBD|FIXME|approval final pendiente" \
    docs/superpowers/specs/2026-08-15-axis-tkeep-framing-design.md \
    specs/fase1-parser-rtl specs/fase3-optimizacion specs/fase3-uram || true
  git diff --check
  git status --short
  git add specs/fase1-parser-rtl/verify-report.md \
    specs/fase3-optimizacion/verify-report.md \
    specs/fase3-uram/verify-report.md
  git commit -m "docs(verificacion): cerrar evidencia tkeep de ITCH"
  ```

- [ ] **Step 6: Verificar el loop ya versionado**

  Run:

  ```bash
  git log --oneline -6
  git status --short --branch
  ```

  Expected: árbol limpio y commits separados de parser, integración, XDC, mutación y evidencia. La fase 3 sigue abierta solo por evidencia física Vivado, no por este framing.
