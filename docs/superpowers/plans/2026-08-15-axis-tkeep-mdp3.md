# AXI `tkeep` para framing MDP3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Impedir que padding AXI complete headers o mensajes MDP3, rechazar máscaras inválidas y recuperar el parser en el siguiente paquete tanto en DW=32 como en DW=64.

**Architecture:** Se conserva la FIFO circular y los buffers ping-pong actuales. La única fuente de bytes nuevos pasa a ser el prefijo MSB indicado por `s_axis_tkeep`; `qavail_eff` y `qw` avanzan por bytes válidos. Un flag de descarte drena el paquete defectuoso. El cierre exacto distingue paquete vacío de 12 bytes, residual incompleto y mensaje truncado, sin rollback de records ya confirmados.

**Tech Stack:** SystemVerilog sintetizable, cocotb 2.x, Verilator `--Wall`, Python 3.11 y runner de mutación existente.

**Spec:** `docs/superpowers/specs/2026-08-15-axis-tkeep-framing-design.md`, `specs/fase4-mdp3-parser/spec.md` y `specs/fase4-mdp3-parser/gherkin/mdp3.feature` (`M3-FRM-01/02/04`, `M3-INV-01/02/04`, `M3-BP-02`).

## Global Constraints

- Ejecutar este plan después del plan ITCH, en la misma rama y con árbol limpio.
- Seguir rojo→verde; solo el primer test puede fallar por ausencia de puerto.
- Verificar y soportar exclusivamente `DW=32` y `DW=64`; no generalizar la
  máscara a patrones dispersos ni hacer claims sobre otros anchos.
- Aceptar `tkeep` completo en beats intermedios y prefijo MSB contiguo no cero en el beat final.
- No leer ni contabilizar lanes con `tkeep=0`.
- Preservar records completos anteriores a un error; cancelar solo captura parcial y resto del paquete.
- Conservar FIFO de salida, ping-pong, layouts Anexo M y selector actuales.
- Este loop no corrige `schemaId/version`, selector por schema, límite general `MAX_MSG=256` ni backpressure de salida. Cada hallazgo conserva criterio abierto y tendrá plan propio.
- No modificar el golden para que imite el RTL. El oráculo sigue siendo `golden_model.mdp3`.

## File Responsibilities

| Archivo | Responsabilidad en este plan |
|---|---|
| `verification/testbenches/mdp3/test_mdp3_framing.py` | Driver `(data, keep, last)`, monitor de estabilidad y casos DW=32/64. |
| `rtl/parser/mdp3_parser.sv` | Puerto, bytes válidos, cola, descarte, paquete vacío y truncado exacto. |
| `scripts/verify/mutate_mdp3.py` | Mutantes de orientación, conteo, máscara, drenaje y padding. |
| `specs/fase4-mdp3-parser/verify-report.md` | Evidencia nueva de gates aplicables y criterios que siguen abiertos. |
| `specs/gherkin-espejos.json` | Coherencia literal de IDs MDP3. |

---

## Task 1: Crear el rojo reproducible MDP3 en ambos anchos

**Files:**

- Modify: `verification/testbenches/mdp3/test_mdp3_framing.py`
- Test: `verification/testbenches/mdp3/test_mdp3_framing.py`

- [ ] **Step 1: Cambiar el driver a beats por paquete**

  Añadir un helper local —el Makefile MDP3 no incluye el área parser y no merece una nueva dependencia—:

  ```python
  def packet_beats(packets, bytes_per_word):
      beats = []
      for packet in packets:
          assert packet
          for offset in range(0, len(packet), bytes_per_word):
              chunk = packet[offset:offset + bytes_per_word]
              shift = 8 * (bytes_per_word - len(chunk))
              beats.append((
                  int.from_bytes(chunk, "big") << shift,
                  ((1 << len(chunk)) - 1) << (bytes_per_word - len(chunk)),
                  offset + len(chunk) == len(packet),
              ))
      return beats
  ```

  Inicializar `s_axis_tkeep=0`. `drive_and_collect` debe mantener `(data, keep, last)` estable si `tvalid && !tready`, contar `accepted_tlast` y seguir ejerciendo `m_axis_tready` según el patrón existente.

- [ ] **Step 2: Hacer que M3-FRM-01/02 prueben palabras parciales reales**

  Eliminar el relleno implícito contado como datos. Conservar la construcción de paquetes del golden y exigir para cada corpus:

  ```python
  accepted_tlast == len(packets)
  got == expected_for(schema, packets)
  ```

  `test_m3frm02_mensajes_que_cruzan_limites_de_palabra` debe seleccionar tamaños no divisibles por el ancho elaborado y validar que el paquete siguiente empieza en un beat nuevo.

- [ ] **Step 3: Añadir M3-FRM-04, M3-INV-02/04 y M3-BP-02**

  Añadir estos tests:

  - `test_m3frm04_header_vacio_y_residual_incompleto`: paquete exacto de 12 bytes sin salida/error; paquete de 13 bytes con un residual produce `error`; un tercer paquete válido se decodifica.
  - `test_m3inv02_truncados_subword_no_usan_padding`: para `missing in range(1, bytes_per_word)`, un packet contiene un record completo y después un mensaje al que faltan `missing` bytes; preserva el primero, pulsa `error`, no emite parcial y recupera.
  - `test_m3inv04_tkeep_invalido_descarta_y_recupera`: máscaras cero, con huecos, LSB y parcial no-final para cada ancho; exactamente un evento de error por caso y paquete posterior correcto.
  - `test_m3bp02_entrada_estable_mientras_no_acepta`: llena la captura hasta `CS_WAIT`, mantiene `tvalid` y falla ante cambio de data/keep/last antes del handshake.
  - `test_axi_keep_mdp3_orientacion_msb_lsb`: el mismo prefijo de bytes se acepta con máscara MSB y se rechaza con la máscara desplazada al LSB.

- [ ] **Step 4: Ejecutar el primer rojo DW=32 y confirmar el mismo rojo DW=64**

  Run:

  ```bash
  make -C verification/testbenches/mdp3 clean-all
  make -C verification/testbenches/mdp3 sim \
    TESTCASE=test_m3frm04_header_vacio_y_residual_incompleto
  make -C verification/testbenches/mdp3 clean-all
  make -C verification/testbenches/mdp3 sim-dw64 \
    TESTCASE=test_m3frm04_header_vacio_y_residual_incompleto
  ```

  Expected: ambos fallan al resolver `dut.s_axis_tkeep` porque el puerto no
  existe. Guardar el primer output; el segundo solo confirma que ambos tops
  están cubiertos.

- [ ] **Step 5: Revisar el diff rojo sin commit**

  Run:

  ```bash
  python3 -m py_compile verification/testbenches/mdp3/test_mdp3_framing.py
  git diff --check
  git diff -- verification/testbenches/mdp3/test_mdp3_framing.py
  ```

  No crear commit hasta lograr el verde de la capacidad.

## Task 2: Incorporar bytes válidos a la FIFO circular MDP3

**Files:**

- Modify: `rtl/parser/mdp3_parser.sv`
- Test: `verification/testbenches/mdp3/test_mdp3_framing.py`

- [ ] **Step 1: Añadir el puerto sin ampliar los anchos soportados**

  Añadir:

  ```systemverilog
  input wire [DW/8-1:0] s_axis_tkeep,
  ```

  junto a `s_axis_tdata`. Mantener `BYTES=DW/8`; los únicos builds de cierre
  son DW=32 y DW=64.

- [ ] **Step 2: Validar máscara y obtener byte-count**

  Añadir las dos funciones locales, sin crear package ni helper RTL nuevo:

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

  Adaptar únicamente los casts al estilo aceptado por Verilator en este
  archivo y definir:

  ```systemverilog
  wire [7:0] in_keep_bytes = keep_nbytes(s_axis_tkeep);
  wire in_keep_ok = keep_is_msb_prefix(s_axis_tkeep) &&
                    (s_axis_tlast || s_axis_tkeep == {BYTES{1'b1}});
  wire in_hs = s_axis_tvalid && s_axis_tready;
  wire in_good_hs = in_hs && in_keep_ok;
  ```

  `tkeep==0`, huecos, LSB parcial y parcial no-final quedan fuera de `in_good_hs`.

- [ ] **Step 3: Recalcular `qbyte`, `qavail_eff` y append**

  Sustituir el aporte fijo `BYTES` por:

  ```systemverilog
  wire [15:0] qavail_eff =
      16'(qavail) + (in_good_hs ? 16'(in_keep_bytes) : 16'd0);
  ```

  Cuando `qbyte(k)` cae en el beat entrante, leer únicamente índices `k-qavail < in_keep_bytes`, con lane MSB `s_axis_tdata[8*(BYTES-1-index) +: 8]`. En el append:

  ```systemverilog
  if (in_good_hs) begin
      for (integer k = 0; k < BYTES; k = k + 1)
          if (k < in_keep_bytes)
              qbytes[(qw + k) % MAX_MSG] <=
                  s_axis_tdata[8*(BYTES - 1 - k) +: 8];
      qw <= (qw + in_keep_bytes) % MAX_MSG;
      if (s_axis_tlast) pkt_end <= 1'b1;
  end
  ```

  Ajustar `s_axis_tready` con la capacidad del peor beat completo, sin asumir que un beat parcial permite sobrellenar el anillo.

- [ ] **Step 4: Añadir descarte con prioridad sobre captura**

  Añadir `drop_packet`. En handshake de máscara inválida: pulso `error`, `qh=0`, `qw=0`, `pkt_end=0`, `hdr_pos=0`, `cap_len=0`, `skip_left=0`, `cst=CS_HDR`; `drop_packet=!s_axis_tlast`. Durante descarte, `s_axis_tready=1`, no se appendan bytes y se limpia `drop_packet` al aceptar `tlast`.

  La prioridad secuencial debe impedir que el `case(cst)` sobrescriba esos resets en el mismo ciclo. No limpiar `occ` ni FIFO de salida: los mensajes completos anteriores siguen observables.

- [ ] **Step 5: Hacer exacto el cierre de header, size y body**

  Aplicar reglas explícitas:

  - `CS_HDR`: `tlast` antes de 12 bytes es truncado y `error`.
  - `CS_SIZE`: si el header de 12 bytes ya terminó y `pkt_end_eff && qavail_eff==0`, aceptar paquete vacío y volver a `CS_HDR` sin error.
  - `CS_SIZE`: si `pkt_end_eff && qavail_eff==1`, emitir `error` y resetear captura; ese byte no inicia otro paquete.
  - `CS_BODY`: completar solo cuando los bytes válidos alcanzan `cap_size-cap_len`; si `tlast` llega antes, emitir `error`, cancelar parcial y conservar `occ` anteriores.
  - Tras completar exactamente el último mensaje en `tlast`, `qavail` residual debe ser cero. Cualquier residual válido es framing inválido, no padding.

  No usar lanes `tkeep=0` para satisfacer ninguna condición.

- [ ] **Step 6: Ejecutar rojos funcionales y verdes dirigidos**

  Tras el puerto, ejecutar primero cada test con la lógica aún incompleta para observar un FAIL funcional y después del cambio mínimo repetir:

  ```bash
  make -C verification/testbenches/mdp3 clean-all
  make -C verification/testbenches/mdp3 sim \
    TESTCASE=test_m3inv02_truncados_subword_no_usan_padding
  make -C verification/testbenches/mdp3 clean-all
  make -C verification/testbenches/mdp3 sim-dw64 \
    TESTCASE=test_m3inv02_truncados_subword_no_usan_padding
  make -C verification/testbenches/mdp3 clean-all
  make -C verification/testbenches/mdp3 sim \
    TESTCASE=test_m3inv04_tkeep_invalido_descarta_y_recupera
  make -C verification/testbenches/mdp3 clean-all
  make -C verification/testbenches/mdp3 sim-dw64 \
    TESTCASE=test_m3frm04_header_vacio_y_residual_incompleto
  ```

  Expected final: PASS en los cuatro comandos; el truncado subword no aparece como record completo.

- [ ] **Step 7: Ejecutar ambas suites y lint antes del commit**

  Run:

  ```bash
  make -C verification/testbenches/mdp3 clean-all
  make -C verification/testbenches/mdp3 sim
  make -C verification/testbenches/mdp3 clean-all
  make -C verification/testbenches/mdp3 sim-dw64
  verilator --lint-only --Wall -GDW=32 --top-module mdp3_parser \
    rtl/parser/mdp3_parser.sv
  verilator --lint-only --Wall -GDW=64 --top-module mdp3_parser \
    rtl/parser/mdp3_parser.sv
  python3 -m py_compile verification/testbenches/mdp3/test_mdp3_framing.py
  git diff --check
  ```

  Expected: PASS DW=32/64 y cero warnings Verilator.

- [ ] **Step 8: Commit del loop funcional MDP3**

  Run:

  ```bash
  git add rtl/parser/mdp3_parser.sv \
    verification/testbenches/mdp3/test_mdp3_framing.py
  git commit -m "fix(mdp3): respetar tkeep en el framing de paquetes"
  ```

## Task 3: Endurecer la mutación específica de `tkeep` MDP3

**Files:**

- Modify: `scripts/verify/mutate_mdp3.py`
- Test: `verification/testbenches/mdp3/test_mdp3_framing.py`

- [ ] **Step 1: Añadir mutantes que compilen en DW=32 y DW=64**

  Conservar los ocho existentes y añadir:

  - `KEEP-ALL-BYTES`: `qavail_eff` suma `BYTES` en lugar de `in_keep_bytes`.
  - `KEEP-LSB-FIRST`: invierte el índice de lane al append.
  - `KEEP-HOLES`: `keep_is_msb_prefix` acepta cualquier máscara no cero.
  - `KEEP-PARTIAL-NONLAST`: elimina el requisito de word completa sin `tlast`.
  - `KEEP-NODRAIN`: una máscara inválida no activa `drop_packet`.
  - `KEEP-PADDING-COMPLETES`: la condición de body vuelve a sumar `BYTES`.
  - `EMPTY-HEADER-ERROR`: convierte el header-only exacto en truncado.
  - `RESIDUAL-ONE-OK`: acepta el byte residual en `CS_SIZE`.

  Los `old` se fijan sobre las líneas estables introducidas en Task 2 y deben aparecer exactamente una vez.

- [ ] **Step 2: Ejecutar primero los mutantes del bug raíz**

  Run:

  ```bash
  python3 scripts/verify/mutate_mdp3.py --mutant KEEP-ALL-BYTES
  python3 scripts/verify/mutate_mdp3.py --mutant KEEP-PADDING-COMPLETES
  python3 scripts/verify/mutate_mdp3.py --mutant KEEP-LSB-FIRST
  python3 scripts/verify/mutate_mdp3.py --mutant KEEP-HOLES
  python3 scripts/verify/mutate_mdp3.py --mutant KEEP-PARTIAL-NONLAST
  python3 scripts/verify/mutate_mdp3.py --mutant KEEP-NODRAIN
  python3 scripts/verify/mutate_mdp3.py --mutant EMPTY-HEADER-ERROR
  python3 scripts/verify/mutate_mdp3.py --mutant RESIDUAL-ONE-OK
  ```

  Expected: cada mutante compila en ambos DW y muere al menos en una suite. `ERROR` de lint/runner no cuenta como muerte.

- [ ] **Step 3: Ejecutar el gate completo y comprobar restauración**

  Run:

  ```bash
  python3 scripts/verify/mutate_mdp3.py
  test ! -e rtl/parser/mdp3_parser.sv.bak
  git diff --check
  git status --short
  ```

  Expected: todos `MATADO`, sin `.bak` y sin modificación residual del RTL.

- [ ] **Step 4: Commit del gate adversarial**

  Run:

  ```bash
  git add scripts/verify/mutate_mdp3.py
  git commit -m "test(mdp3): mutar framing tkeep y recuperación"
  ```

## Task 4: Ejecutar gates y actualizar evidencia honesta de fase 4

**Files:**

- Modify: `specs/fase4-mdp3-parser/verify-report.md`
- Verify: `specs/fase4-mdp3-parser/spec.md`
- Verify: `specs/fase4-mdp3-parser/gherkin/mdp3.feature`
- Verify: `specs/gherkin-espejos.json`

- [ ] **Step 1: Ejecutar gates A, B y golden desde cero**

  Run:

  ```bash
  python3 -m unittest discover -s golden_model/tests -t .
  make -C verification/testbenches/mdp3 clean-all
  make -C verification/testbenches/mdp3 sim
  make -C verification/testbenches/mdp3 clean-all
  make -C verification/testbenches/mdp3 sim-dw64
  verilator --lint-only --Wall -GDW=32 --top-module mdp3_parser \
    rtl/parser/mdp3_parser.sv
  verilator --lint-only --Wall -GDW=64 --top-module mdp3_parser \
    rtl/parser/mdp3_parser.sv
  ```

- [ ] **Step 2: Ejecutar estilo y mutación**

  Run:

  ```bash
  if command -v verible-verilog-lint >/dev/null; then
    verible-verilog-lint rtl/parser/mdp3_parser.sv
  else
    echo "Gate C NO EJECUTADO: verible-verilog-lint no instalado"
  fi
  python3 scripts/verify/mutate_mdp3.py
  ```

- [ ] **Step 3: Verificar mapa literal Gherkin↔tests**

  Run:

  ```bash
  python3 - <<'PY'
  import json
  from pathlib import Path
  json.loads(Path("specs/gherkin-espejos.json").read_text())
  feature = Path("specs/fase4-mdp3-parser/gherkin/mdp3.feature").read_text()
  tests = Path("verification/testbenches/mdp3/test_mdp3_framing.py").read_text().lower()
  for case in ("M3-FRM-01", "M3-FRM-02", "M3-FRM-04", "M3-INV-01", "M3-INV-02", "M3-INV-04", "M3-BP-02"):
      assert feature.count(case) == 1, (case, feature.count(case))
      assert case.lower().replace("-", "") in tests, case
  print("Mapa framing MDP3 completo")
  PY
  ```

  Si un test cubre dos IDs, su nombre debe contener ambos tokens normalizados, como ya ocurre con `m3inv01_inv02`.

- [ ] **Step 4: Actualizar verify-report sin cerrar criterios ajenos**

  Sustituir los outputs de drivers antiguos por la ejecución nueva DW=32/64. Registrar número de tests, PASS/FAIL, lint y mutación. Marcar explícitamente:

  - `M3-FRM-01/02/04`, `M3-INV-01/02/04` y `M3-BP-02`: cerrados solo si sus gates pasan.
  - `M3-GEN-03` y selector schema/version: abiertos.
  - `M3-PASS-02` (`MAX_MSG`): abierto salvo evidencia independiente de su límite documentado.
  - `M3-BP-01` (backpressure de salida): abierto.
  - Gate C: `NO EJECUTADO` si no hay Verible.

  La fase 4 permanece `EN CONSTRUCCIÓN`; cerrar framing no equivale a cerrar la fase.

- [ ] **Step 5: Ejecutar regresión cruzada de fases 1–3**

  Run:

  ```bash
  make -C verification/testbenches/parser clean
  make -C verification/testbenches/parser sim
  make -C verification/testbenches/phase3 clean-all
  make -C verification/testbenches/phase3 sim-parser
  make -C verification/testbenches/phase3 clean-all
  make -C verification/testbenches/phase3 sim-chain
  python3 scripts/verify/synth_check.py
  ```

  Expected: verde; un SKIP de pcap se informa como tal.

- [ ] **Step 6: Autorrevisión y commit de evidencia**

  Run:

  ```bash
  rg -n "M3-(FRM|INV|BP|GEN|PASS)|PASS|FAIL|NO EJECUTADO|EN CONSTRUCCIÓN" \
    specs/fase4-mdp3-parser/spec.md \
    specs/fase4-mdp3-parser/gherkin/mdp3.feature \
    specs/fase4-mdp3-parser/verify-report.md
  rg -n "TODO|TBD|FIXME|fase 4.*CERRADA" \
    specs/fase4-mdp3-parser docs/superpowers/specs || true
  git diff --check
  git status --short
  git add specs/fase4-mdp3-parser/verify-report.md
  git commit -m "docs(verificacion): cerrar evidencia tkeep de MDP3"
  ```

- [ ] **Step 7: Comprobar el límite exacto del loop**

  Run:

  ```bash
  git log --oneline -5
  git status --short --branch
  ```

  Expected: árbol limpio; framing `tkeep` versionado; fase 4 aún abierta por schema/version, máximo de mensaje y backpressure de salida.
