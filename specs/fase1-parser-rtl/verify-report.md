# verify-report — fase1-parser-rtl (iteración 3)

> Régimen de gates de Atenea re-mapeado al flujo HDL. El owner no lee HDL/Python:
> esta evidencia (outputs reales) es lo que `/grade` re-ejecutará.
> Fecha: 2026-08-13. Área: `rtl/parser/` + `verification/testbenches/parser/`.
> Iteración 3: cierra el criterio 7 (frame truncado) que grade marcó FAIL en la
> iteración 2 (tests placeholder `or True` + RTL sin detección de truncado).

## Meta del atacante/diseño (1-2 frases)

¿Cómo podría este módulo dar un registro incorrecto, perder un mensaje, romper el
handshake AXI o atascarse con un feed real? Ataques cubiertos: mensaje que cruza
palabra/paquete, longitud incoherente por tipo, gap de secuencia, cambio de
sesión, count=0, backpressure intermitente de salida, tready bajo con datos
retenidos, feed real back-to-back que llena la cola (desbordamiento del contador),
tipo fuera de subset, **tlast en medio de un mensaje, frame truncado con el
datagrama terminado antes de completar el mensaje**.

## Cambios de iteración 3 (criterio 7)

- RTL: flag `eop_seen` latchea `tlast`; en `ST_LEN` un mensaje incompleto con
  `eop_seen` → `error` + salto a `ST_HDR` (descarta el truncado, sigue con el
  siguiente datagrama). Se limpia al capturar un mensaje completo o al leer un
  header nuevo (salvo que el tlast coincida, para no enmascarar el propio
  truncado).
- Tests `test_sec_frm01` / `test_sec_frm02` reescritos con asserts reales
  (antes `or True`): verificar `errores > 0` y que el parser continúa / no
  emite registro parcial.

## Tabla de gates

| Gate | Comando / evidencia | Resultado |
|---|---|---|
| **A. Simulación** | `make sim` (cocotb+Verilator) tras `make clean` (la mutación deja sim_build sucio) | 19/19 PASS, 0 FAIL — **PASS** |
| **B. Compilación/lint sintaxis** | `verilator --lint-only -Wall -Wno-EOFNEWLINE --top-module itch_parser` | 0 warnings — **PASS** |
| **C. Estilo** | `verible-verilog-lint` **NO EJECUTADO** (herramienta no instalada; sustituto `--Wall` + revisión manual) | **NO EJECUTADO** |
| **D. Cobertura + mapeo** | Tabla spec↔tests abajo; cobertura funcional runner **NO EJECUTADO** (no configurado) | Nivel 1 **PASS** |
| **E. Mutación HDL** | `python3 scripts/verify/mutate_parser.py` | **10/10 muertos, 0 sobreviven** — **PASS** |
| **F. Completitud Gherkin** | 19 escenarios ↔ 19 tests espejo (tabla abajo) | **PASS** |
| **G. Rigor + timing** | G0/G1/G3 checklist; G timing NO APLICA (fase 1) | **PASS** |

## Gate D nivel 1 — cruce spec ↔ tests

| Criterio spec | Test(s) espejo | Estado |
|---|---|---|
| 1 (registro Anexo A byte a byte) | `test_par01`, `test_out01`, `test_rep01`, `test_rep02` | PASS |
| 2 (line-rate, alcance acotado) | `test_lin01`, `test_sec_lin01` | PASS (acotado) |
| 3 (alineador, 8 desplazamientos) | `test_aln01` | PASS |
| 4 (framing/gaps/sesión/count=0) | `test_frm01`, `test_sec_gap01/02`, `test_sec_frm03/04` | PASS |
| 5 (AXI-Stream con backpressure) | `test_out02`, `test_out03` | PASS |
| 6 (no-subset: validar y contar, sin registro) | `test_sec_par04` | PASS |
| 7 (longitud incoherente/truncado → error) | `test_sec_par03`, `test_sec_par03b`, `test_sec_frm01`, `test_sec_frm02` | **PASS (iteración 3)** |
| 8 (replay real + vectores congelados) | `test_rep01`, `test_rep02` (pcap 12302019) | PASS |
| 10/11 (lint y estilo) | gates B/C | B PASS, C NO EJECUTADO |
| 9 (cabos fase 0: día 01302019) | — | NO EJECUTADO |

## Gate F — espejos Gherkin (título literal → test)

Todos los escenarios de los 5 `.feature` tienen test espejo (19/19). Ver tabla
de la iteración 2 — sin cambios estructurales, solo se reforzaron
`test_sec_frm01` y `test_sec_frm02`.

## Gate E — mutación HDL (evidencia resumida)

Runner: `scripts/verify/mutate_parser.py` (aplica cada flip, corre la suite,
restaura, y limpia sim_build al final).

```
[MATADO] ALN-OFFBYONE: FAIL=16   # off-by-one del offset de cuerpo
[MATADO] ALN-PAD-FILL: FAIL=16   # relleno del cuerpo en lugar de cero
[MATADO] SEQ-GAP-NOGAP: FAIL=3   # flip != a == en detección de gap
[MATADO] SEQ-GAP-SESSION: FAIL=1 # flip != a == en cambio de sesión
[MATADO] NEXT-OFFBYONE: FAIL=4   # off-by-one pack_left >1 → >0
[MATADO] LEN-BODY_W: FAIL=16     # ceil incorrecto de words de cuerpo
[MATADO] CAP-SUBSET: FAIL=1      # emite aunque no sea subset
[MATADO] OUT-FREE: FAIL=16       # heap sin out_take (duplica/pierde)
[MATADO] LEN-CAPT-ERR: FAIL=1    # umbral len<11 → <=11 (borde, test par03b)
[MATADO] TRUNC-EOP: FAIL=1       # ignora el latch de truncado (FRM-01/02)
TODOS LOS MUTANTES MUERTOS. Gate E PASS.
```

## Gate G — checklist por superficie

**G0:** feeds reales fuera del repo (`/tmp/real_subset.pcap` para REP-02);
vectores commiteados sintéticos; `.gz` del feed gitignored. Sin secretos.

**G1:** line-rate acotado (`test_lin01`, `test_sec_lin01`), alineador
(`test_aln01`), gaps/sesión/count=0 (`test_sec_gap*`, `test_sec_frm03/04`),
**secuencia robusta**: frame truncado y tlast en medio señalan `error` sin
cuelgue ni registro parcial (`test_sec_frm01/02`), big-endian cubierto por la
comparación byte a byte.

**G3:** comparación bit a bit contra `message_oracle` (independiente del RTL);
REP-02 17937 words byte a byte.

## D.2 / hallazgos abiertos

1. Gate C (verible) y D nivel 2 (cobertura runner): NO EJECUTADOS (herramientas
   no disponibles/configuradas en el entorno). Declarados, no ocultados.
2. Criterio 9 (cabo fase 0): NO EJECUTADO (pre-trabajo de fase 0).
3. Line-rate mínimo infinito: físicamente imposible con el Anexo A → decisión
   de `/spec` (documentado en research-parser-rtl-pendientes.md §C.0).
4. La mutación deja `sim_build` sucio (los objetos no se recompilan al restaurar
   el RTL); el runner ahora hace `make clean` al final. `make sim` en verde exige
   ese clean o compilación fresca.

## Veredicto

**Listo para /grade (iteración 3).** Criterio 7 cerrado con test reales que
pinchan y un mutante TRUNC-EOP muerto. Gates A/B/E/F PASS; C/D-nivel2 declarados
NO EJECUTADOS (entorno); G0/G1/G3 PASS; G timing NO APLICA (fase 1). Restan
decisiones de owner: line-rate mínimo infinito (criterio 2) y cabo fase 0.
