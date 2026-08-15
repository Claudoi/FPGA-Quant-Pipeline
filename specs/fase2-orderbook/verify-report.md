# verify-report — fase2-orderbook (iteración 4)

> Fecha: 2026-08-15. Área: `rtl/orderbook/`, testbench DW=64 y mutantes
> funcionales nacidos en fase 2. La campaña queda cerrada funcionalmente; el
> runner compartido con fase 3 conserva tres hallazgos posteriores explícitos
> que se cierran en la campaña de fase 3, no se cuentan como PASS aquí.

## Objetivo adversarial

Refutar que el book pueda producir el BBO correcto mientras silencia una
invariante, contaminar un locate vacío, aceptar un cancel inválido o aparentar
un gate B limpio mediante una supresión. La iteración 4 elimina tres falsos
positivos históricos: `SEC-OV-01` no observaba `error`, `BBO-02` no ejercitaba
un segundo locate y la suite oficial no compilaba con Verilator 5.050 por
`UNSIGNED`.

## Rojo reproducido antes del cambio

### Gate B/A bloqueado por warning real

```text
%Warning-UNSIGNED: rtl/orderbook/orderbook.sv:818:48:
Comparison is constant due to unsigned arithmetic
  : (nx_bi >= 4'd0 && lt(nx_type));
%Error: Exiting due to 1 warning(s)
make: *** [sim] Error 2
```

No se añadió `-Wno-UNSIGNED`: la rama DW=64 se redujo a `lt(nx_type)`.

### Test rojo de observabilidad

```text
test_sec_ov01_overflow_cantidad
ValueError: not enough values to unpack (expected 4, got 3)
TESTS=1 PASS=0 FAIL=1 SKIP=0
```

El driver no devolvía ni muestreaba `error`. Después del cambio devuelve
`error_cycles`; el escenario exige al menos un pulso, ausencia de evento para
el cancel inválido y aceptación del add válido posterior.

## Gates A–G

| Gate | Comando / evidencia real | Resultado |
|---|---|---|
| **A — simulación** | `PATH=/Volumes/WD_Black/FPGA/.venv/bin:$PATH make -C verification/testbenches/orderbook clean sim` | **14/14 PASS, 0 FAIL — PASS** |
| **B — compilación** | `verilator --lint-only --Wall --top-module orderbook rtl/orderbook/orderbook.sv` + `python3 -m py_compile ...` | **0 warnings/errores — PASS** |
| **C — estilo** | `command -v verible-verilog-lint` | **NO EJECUTADO: herramienta no instalada** |
| **D — cobertura** | mapa literal de abajo; cobertura funcional instrumentada no disponible | **nivel 1 PASS; nivel 2 NO EJECUTADO** |
| **E — mutación** | mutantes aplicables de fase 2, ejecutados individualmente por `mutate_orderbook.py --mutant ID` | **9/9 muertos — PASS fase 2** |
| **F — completitud** | 12 escenarios en `orderbook.feature`, 14 tests cocotb y entrada en `specs/gherkin-espejos.json` | **PASS** |
| **G — rigor/timing** | replay local real, golden independiente, datos no versionados; timing Vivado fuera de fase 2 | **G0/G2/G3 PASS; timing NO APLICA** |

## Gate A — evidencia funcional

La suite oficial produjo 14 casos y cero fallos. Los dos escenarios reparados
también se ejecutaron por separado:

```text
test_sec_ov01_overflow_cantidad  PASS
TESTS=1 PASS=1 FAIL=0 SKIP=0

test_sec_em01_simbolo_vacio      PASS
TESTS=1 PASS=1 FAIL=0 SKIP=0
```

El replay real no fue sustituido por un vector sintético:

```text
REPLAY-01: 31400 mensajes de 20 símbolos contra golden
REPLAY-01 OK: 30729 eventos bit a bit, cross=0, anomaly=671
TESTS=1 PASS=1 FAIL=0 SKIP=0
```

`test_replay01_feed_real_bbo` queda decorado con `skip=` si
`/tmp/real_trading.pcap` no existe. En selección manual, la ausencia produce
un mensaje `REPLAY-01 OMITIDO`; nunca se presenta la falta de datos como
evidencia real.

## Gate D/F — mapa spec ↔ Gherkin ↔ tests

| Contrato | Test(s) espejo | Evidencia |
|---|---|---|
| BBO-01 | `test_bbo01_secuencia_bbo_igual_golden` | secuencia multi-tipo bit a bit |
| BBO-02 | `test_sec_em01_simbolo_vacio` | locate AAPL permanece vacío, sin evento; ask AMZN = (0,0) |
| SEC-U-01 | `test_sec_u01_replace_atomico`, `test_inv_u01_replace_best_bid_estado_final` | estado final único |
| SEC-HZ-01/02 | `test_sec_hz01_add_execute_raw`, `test_sec_hz02_replace_execute_raw` | hazards RAW |
| SEC-DC-01 | `test_sec_dc01_sin_doble_descuento`, `test_sec_dc02_delete_descuenta_exacto` | descuento exacto |
| SEC-OV-01 | `test_sec_ov01_overflow_cantidad` | pulso observado, descarte y recuperación |
| SEC-AN-01 | `test_sec_an01_ref_desconocida` | anomalía y continuidad |
| SEC-CR-01 | `test_sec_cr01_libro_cruzado` | contador de cruzado |
| MULTI-01 | `test_multi01_dos_simbolos_independientes` | aislamiento por locate |
| REPLAY-01 | `test_replay01_feed_real_bbo` | 30.729 eventos reales |
| REPLAY-02 | `test_rep02_vectores_congelados_bbo` | vector sintético congelado |

`specs/gherkin-espejos.json` contiene:

```text
specs/fase2-orderbook/gherkin -> verification/testbenches/orderbook
```

## Gate E — mutación aplicable de fase 2

Cada mutante compiló antes de ejecutar tests. El runner restaura el RTL en un
`finally` por mutante, limpia los builds y corta al primer test rojo: un
mutante roto no cuenta y una interrupción no deja el DUT alterado.

```text
OV-BEST           MATADO  FAIL=2
OV-EMPTY          MATADO  FAIL=1
U-NOTATOMIC       MATADO  FAIL=2
U-DELETE-HALF     MATADO  FAIL=2
U-SKIP-ROUTE      MATADO  FAIL=5
D-DOUBLE          MATADO  FAIL=3
RED-REF           MATADO  FAIL=2
QTY-NOERROR       MATADO  FAIL=1
EMIT-NOCHANGED    MATADO  FAIL=14
```

El mutante nuevo `QTY-NOERROR` cambia únicamente el pulso de reducción
excesiva a cero; lo mata `SEC-OV-01`. Esto demuestra que la observación de
`error` ya no es decorativa.

### Resultado integral compartido observado, todavía no PASS

Al ejecutar el runner completo de fases 2–3 se obtuvo **23/26 muertos** y tres
supervivientes de fase 3:

```text
URAM-COMB-INDEX  SOBREVIVE
NSYM-GUARD       SOBREVIVE
BP-NORET         SOBREVIVE
```

No afectan al cierre funcional DW=64 de esta campaña, pero sí bloquean el gate
E integral y la fase 3. Sus causas verificadas son: propiedad de inferencia
URAM no comprobada estáticamente, error agregado que oculta el índice OOB y
stall periódico que no garantiza coincidir con `tvalid`. Se corrigen y
reejecutan en `specs/fase3-*/verify-report.md`.

## Gate G — fronteras honestas

- El alcance documentado empieza en `MoldUDP64`; MAC 10G y Ethernet/IP/UDP no
  se atribuyen a este repositorio.
- El golden usado es `golden_model/src/book.py`, independiente del RTL.
- `/tmp/real_trading.pcap` se leyó localmente y no aparece en `git status`.
- La rama DW=64 compila con `--Wall` sin `Wno-UNSIGNED`.
- Vivado, WNS/TNS y utilización pertenecen a fase 3; no se infieren desde
  Verilator ni se declaran cerrados aquí.

## Veredicto

**Fase 2 cerrada funcionalmente.** Gates A, B, D nivel 1, E fase 2, F y G
aplicables están en PASS; C y cobertura instrumentada están declarados NO
EJECUTADOS. El replay real aporta 30.729 comparaciones bit a bit. El gate E
integral compartido permanece abierto hasta cerrar los tres supervivientes de
fase 3, registrados sin convertirlos en PASS.
