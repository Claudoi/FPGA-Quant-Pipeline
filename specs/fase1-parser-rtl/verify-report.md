# verify-report — fase1-parser-rtl (iteración 4)

> **Estado vigente: REABIERTA (2026-08-15).** La revisión adversarial demostró
> que el driver concatenaba datagramas antes de formar beats y no modelaba qué
> bytes del último beat eran válidos. Los outputs de la iteración 4 permanecen
> como evidencia histórica, pero los criterios 4, 7 y 8 vuelven a estar abiertos
> hasta implementar y verificar `s_axis_tkeep` por datagrama.

> Régimen de gates de Atenea re-mapeado al flujo HDL. El owner no lee HDL/Python:
> esta evidencia (outputs reales) es lo que `/grade` re-ejecutará.
> Fecha de verificación vigente: 2026-08-15. Área: `rtl/parser/` +
> `verification/testbenches/parser/`. Iteración 4: valida los 22 tipos, recupera
> el paquete posterior a un truncado y cubre las ocho alineaciones literales.

## Meta del atacante/diseño (1-2 frases)

¿Cómo podría este módulo dar un registro incorrecto, perder un mensaje, romper el
handshake AXI o atascarse con un feed real? Ataques cubiertos: mensaje que cruza
palabra/paquete, longitud incoherente por tipo, gap de secuencia, cambio de
sesión, count=0, backpressure intermitente de salida, tready bajo con datos
retenidos, feed real back-to-back que llena la cola (desbordamiento del contador),
tipo fuera de subset, **tlast en medio de un mensaje, frame truncado con el
datagrama terminado antes de completar el mensaje**.

## Cambios de iteración 3 (criterio 7)

- RTL histórico: la iteración 3 introdujo `eop_seen` y el salto a `ST_HDR`,
  pero limpiaba el latch al capturar un mensaje anterior y no vaciaba la cola;
  la iteración 4 demuestra y corrige esos dos huecos.
- Tests `test_sec_frm01` / `test_sec_frm02` reescritos con asserts reales
  (antes `or True`): verificar `errores > 0` y que el parser continúa / no
  emite registro parcial.

## Cambios de iteración 4

- `explen` cubre los 22 tipos de `MESSAGE_LENGTHS`; toda longitud canónica
  incorrecta pulsa `error`, también fuera del subset. Un H válido no emite,
  pero avanza el `msg_idx` observable del A posterior.
- `tlast` se latchea solo con handshake. Tras aceptarlo, la entrada se bloquea
  hasta cerrar o descartar el datagrama, evitando mezclar dos paquetes en una
  cola que no contiene marcadores internos. En truncado se vacía la cola y se
  prueba el A de un paquete íntegro posterior.
- En sesión nueva con `count=0`, `exp_seq` toma el `seq` del header actual; se
  elimina la carrera entre dos asignaciones no bloqueantes.
- LIN-01 queda reconciliado con QB=64: cuatro A/U, salida bit a bit y stalls
  `<=24`. ALN-01 recorre offsets 0–7, no tres muestras parciales.

## Tabla de gates

| Gate | Comando / evidencia | Resultado |
|---|---|---|
| **A. Simulación** | `make -C verification/testbenches/parser sim` desde build limpio | 20/20 PASS, 0 FAIL; REP-02 91 paquetes/17.937 words — **PASS** |
| **B. Compilación/lint sintaxis** | `verilator --lint-only --Wall --top-module itch_parser rtl/parser/itch_parser.sv` | 0 warnings — **PASS** |
| **C. Estilo** | `verible-verilog-lint` **NO EJECUTADO** (herramienta no instalada; sustituto `--Wall` + revisión manual) | **NO EJECUTADO** |
| **D. Cobertura + mapeo** | Tabla spec↔tests abajo; cobertura funcional runner **NO EJECUTADO** (no configurado) | Nivel 1 **PASS** |
| **E. Mutación HDL** | `python3 scripts/verify/mutate_parser.py` | **12/12 muertos, 0 sobreviven** — **PASS** |
| **F. Completitud Gherkin** | conteo reproducible | 20 escenarios ↔ 20 tests espejo — **PASS** |
| **G. Rigor + timing** | G0/G1/G3 checklist; G timing NO APLICA (fase 1) | **PASS** |

## Gate D nivel 1 — cruce spec ↔ tests

| Criterio spec | Test(s) espejo | Estado |
|---|---|---|
| 1 (registro Anexo A byte a byte) | `test_par01`, `test_out01`, `test_rep01`, `test_rep02` | PASS |
| 2 (line-rate, alcance acotado) | `test_lin01`, `test_sec_lin01` | PASS (acotado) |
| 3 (alineador, 8 desplazamientos) | `test_aln01` | PASS |
| 4 (framing/gaps/sesión/count=0) | `test_frm01`, `test_sec_gap01/02`, `test_sec_frm03/04` | PASS |
| 5 (AXI-Stream con backpressure) | `test_out02`, `test_out03` | PASS |
| 6 (22 longitudes; no-subset avanza índice, sin registro) | `test_sec_par04`, `test_sec_par05` | PASS |
| 7 (longitud incoherente/truncado → error + recuperación) | `test_sec_par03`, `test_sec_par03b`, `test_sec_par05`, `test_sec_frm01`, `test_sec_frm02` | **PASS (iteración 4)** |
| 8 (replay real + vectores congelados) | `test_rep01`, `test_rep02` (pcap 12302019) | PASS |
| 10/11 (lint y estilo) | gates B/C | B PASS, C NO EJECUTADO |
| 9 (cabos fase 0: día 01302019) | `run_golden` completo, addendum inferior | PASS |

## Gate F — espejos Gherkin (título literal → test)

Los cinco `.feature` contienen 20 escenarios/esquemas y el módulo cocotb tiene
20 tests. SEC-PAR-05 añade el espejo de validación de tipos conocidos; ALN-01
recorre internamente los ocho ejemplos de su esquema.

## Gate E — mutación HDL (evidencia resumida)

Runner: `scripts/verify/mutate_parser.py` (aplica cada flip, corre la suite,
restaura, y limpia sim_build al final).

```
[MATADO] ALN-OFFBYONE: FAIL=18
[MATADO] ALN-PAD-FILL: FAIL=18
[MATADO] SEQ-GAP-NOGAP: FAIL=3
[MATADO] SEQ-GAP-SESSION: FAIL=2
[MATADO] NEXT-OFFBYONE: FAIL=7
[MATADO] LEN-BODY_W: FAIL=6
[MATADO] CAP-SUBSET: FAIL=6
[MATADO] OUT-FREE: FAIL=18
[MATADO] LEN-CAPT-ERR: FAIL=1
[MATADO] LEN-H: FAIL=2
[MATADO] SEQ-ZERO-SESSION: FAIL=1
[MATADO] TRUNC-EOP: FAIL=2
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
   no disponibles/configuradas en el entorno; verible no está en brew ni pip
   como binario). Declarados, no ocultados.
2. Criterio 9 (cabo fase 0): **CERRADO el 2026-08-15** con la jornada completa
   `01302019`: 368.366.634 mensajes, 8.713 símbolos, 0 anomalías y 63
   `cross_events`. Artefacto de 4.764.426.091 bytes ignorado por Git y
   `gzip -t` verde; evidencia completa en el verify-report de fase 0.
3. Line-rate mínimo infinito (criterio 2): **DECISIÓN DE SPEC TOMADA (edit
   2026-08-13)**: non-goal físico derivado del Anexo A (16 B overhead/mensaje →
   salida > entrada). Ver spec.md criterio 2.
4. El runner restaura el RTL en un `finally` por mutante y hace `make clean` al
   final; una interrupción no deja el DUT mutado ni objetos reutilizables.

## Veredicto histórico de la iteración 4 — sustituido por la reapertura

**Se declaró cerrada funcionalmente en la iteración 4.** Gates A/B/E/F PASS; C y cobertura
nivel 2 declarados NO EJECUTADOS por herramienta ausente; G0/G1/G3 PASS y
timing NO APLICA en fase 1. Quedan probados los 22 tipos, ocho offsets, sesión
nueva con count=0, recuperación tras truncado, replay real y mutación 12/12.
No se presenta el non-goal de mensajes mínimos infinitos como line-rate. Este
veredicto ya no representa el estado actual por el defecto de framing descrito
al inicio del informe.

## Addendum de evidencia — segundo día real (2026-08-15)

`python3 -m golden_model.scripts.run_golden
data/itch_sample/01302019.NASDAQ_ITCH50.gz --out /tmp/fpga-fase0-0130` procesó
368.366.634 mensajes completos con 0 anomalías, 8.713 símbolos y 63
`cross_events` en 22m15s. `gzip -t` sobre los 4.764.426.091 bytes terminó con
exit 0.
El feed y sus derivados siguen fuera de Git. El detalle autoritativo está en
`specs/fase0-golden-model/verify-report.md`.
