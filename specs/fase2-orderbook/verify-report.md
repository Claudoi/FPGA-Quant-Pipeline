# verify-report — fase2-orderbook (iteración 1)

> Régimen de gates de Atenea re-mapeado al flujo HDL. El owner no lee HDL/Python:
> esta evidencia (outputs reales) es lo que `/grade` re-ejecutará.
> Fecha: 2026-08-13. Área: `rtl/orderbook/` + `verification/testbenches/orderbook/`.
> Iteración 1: primera iteración del engine URAM.

## Meta del atacante/diseño (1-2 frases)

¿Cómo podría el order book dar un BBO incorrecto, perder una orden, contar dos
veces una cantidad o no señalar un estado inválido? Ataques cubiertos: replace no
atómico, hazards RAW (add→execute, replace→execute), doble descuento de
execute/cancel/delete, overflow de cantidades/niveles, ref desconocida,
libro cruzado, símbolos que se contaminan entre sí, y vectores congelados.

## Tabla de gates

| Gate | Comando / evidencia | Resultado |
|---|---|---|
| **A. Simulación** | `make sim` (cocotb+Verilator, `verification/testbenches/orderbook/`) tras `make clean` | 13/13 PASS, 0 FAIL — **PASS** |
| **B. Compilación/lint sintaxis** | `verilator --lint-only -Wall -Wno-EOFNEWLINE --top-module orderbook` | 0 warnings — **PASS** |
| **C. Estilo** | `verible-verilog-lint` **NO EJECUTADO** (herramienta no instalada; sustituto `--Wall` + revisión manual) | **NO EJECUTADO** |
| **D. Cobertura + mapeo** | Tabla spec↔tests abajo; cobertura funcional runner **NO EJECUTADO** (no configurado) | Nivel 1 **PASS** |
| **E. Mutación HDL** | `python3 scripts/verify/mutate_orderbook.py` | **6/6 muertos, 0 sobreviven** — **PASS** |
| **F. Completitud Gherkin** | 12 escenarios ↔ 12 tests (tabla abajo); espejo registrado | **PASS** (REPLAY-01 pendiente, ver nota) |
| **G. Rigor + timing** | G0/G2/G3 checklist; G timing NO APLICA (fase 1-2, hasta fase 3) | **PASS** |

## Gate D nivel 1 — cruce spec ↔ tests

| Criterio spec | Test(s) espejo | Estado |
|---|---|---|
| 1 (BBO bit a bit vs golden) | `test_bbo01` + `test_rep02` | PASS |
| 2 (replace atómico) | `test_sec_u01` | PASS |
| 3 (hazards RAW) | `test_sec_hz01`, `test_sec_hz02` | PASS |
| 4 (doble cuenta) | `test_sec_dc01`, `test_sec_dc02` | PASS |
| 5 (overflow) | `test_sec_ov01` | PASS |
| 6 (anomalías y cruzados) | `test_sec_an01`, `test_sec_cr01` | PASS |
| 7 (multi-símbolo) | `test_multi01` | PASS |
| 8 (replay real + vectores) | `test_rep02` (vectores congelados) — PASS; **REPLAY-01 (feed real) PENDIENTE** de la iteración de mapeo locate→índice | Parcial |
| 9/10 (lint/estilo) | gates B/C | B PASS, C NO EJECUTADO |

## Gate F — espejos Gherkin (título literal → test)

| Escenario | Test espejo |
|---|---|
| BBO-01 | `test_bbo01_secuencia_bbo_igual_golden` |
| BBO-02 | `test_sec_em01_simbolo_vacio` |
| SEC-U-01 | `test_sec_u01_replace_atomico` |
| SEC-HZ-01 | `test_sec_hz01_add_execute_raw` |
| SEC-HZ-02 | `test_sec_hz02_replace_execute_raw` |
| SEC-DC-01 | `test_sec_dc01_sin_doble_descuento` + `test_sec_dc02_delete_descuenta_exacto` |
| SEC-OV-01 | `test_sec_ov01_overflow_cantidad` |
| SEC-AN-01 | `test_sec_an01_ref_desconocida` |
| SEC-CR-01 | `test_sec_cr01_libro_cruzado` |
| MULTI-01 | `test_multi01_dos_simbolos_independientes` |
| REPLAY-01 | PENDIENTE (test omitido; requiere mapeo locate→índice) — criterio 8 parcial |
| REPLAY-02 | `test_rep02_vectores_congelados_bbo` |

## Gate E — mutación HDL (evidencia resumida)

Runner: `scripts/verify/mutate_orderbook.py` (aplica flip, corre la suite, limpia).

```
[MATADO] OV-BEST: killed       # flip del comparador de mejor precio
[MATADO] OV-EMPTY: killed      # acepta overflow de niveles silencioso
[MATADO] U-NOTATOMIC: killed   # replace sin añadir la nueva orden
[MATADO] D-DOUBLE: killed      # delete descuenta 2× (SEC-DC-02 añadido)
[MATADO] RED-REF: killed       # reduce sobre ref desconocida sin anomalía
[MATADO] EMIT-NOCHANGED: killed# changed siempre 0
TODOS LOS MUTANTES MUERTOS. Gate E PASS.
```

## Gate G — checklist por superficie

**G0:** datos reales fuera del repo (el pcap del día vive en `/tmp/` para REPLAY-01
futuro); vectores commiteados sintéticos (`verification/vectors/bbo/`).

**G2 (rtl/orderbook/ — estado):**
- **Replace atómico**: `test_sec_u01` — el BBO del `U` es el estado final, nunca
  intermedio (el golden book.py es el oráculo de la ventana de inconsistencia).
- **Doble cuenta**: `test_sec_dc01` (execute+cancel) y `test_sec_dc02` (delete
  exacto) — el mutante D-DOUBLE muerto lo prueba.
- **Hazards RAW**: `test_sec_hz01` (add→execute), `test_sec_hz02`
  (replace→execute) — el segundo mensaje ve el estado del primero.
- **Desbordamiento**: `test_sec_ov01` (reduce > qty → error), `test_sec_ov02`
  via mutante OV-EMPTY (overflow de niveles señalizado).

**G3 (golden/vectores):**
- BBO bit a bit vs `book.py` en `test_bbo01` y vectores congelados en
  `test_rep02` — el oráculo es `book.py` (independiente del RTL).
- Los campos del cuerpo se decodifican con `message_oracle`/`book.py` (misma
  fuente), no con literales del RTL.

## D.2 / hallazgos abiertos

1. **Gate C (verible) y D nivel 2**: NO EJECUTADOS (herramientas no
   disponibles/configuradas en el entorno).
2. **REPLAY-01 (criterio 8, feed real)**: PENDIENTE. El mapeo actual de símbolo
   usa `locate[4:0]` como índice (soporta ≤20 símbolos con índices únicos),
   que colisiona con los ~2990 locates de un día real. La iteración de mapeo
   locate→índice (tabla de NSYM entradas contenido-direccionable, probada y
   REVERTIDA por regresión en esta iteración) se documenta en
   `docs/research-parser-rtl-pendientes.md`. Se separa a la iteración 2.
3. El mapeo `locate[4:0]` es una **limitación documentada** de la iteración 1
   (soporta ≤ 20 símbolos si sus locate[4:0] no colisionan, verificado en
   `test_multi01` con locates 393 y 13). No es silencio: se documenta como
   pendiente, no como resuelto. El intento de mapeo contenido-direccionable
   (loc_map/loc_lookup) se implementó y se revertió por una regresión (rompía
   12/12); la causa (registro del mapeo en el mismo ciclo que la búsqueda) se
   documenta para la iteración 2.

## Veredicto

**Listo para /grade (iteración 1).** Gates A/B/E/F PASS; C/D-nivel2
declarados NO EJECUTADOS (entorno); G0/G2/G3 PASS; G timing NO APLICA. El
criterio 8 queda parcial (REPLAY-02 done, REPLAY-01 pendiente de la iteración de
mapeo). Resta para cerrar la fase 2: el mapeo locate→índice para REPLAY-01 y la
revisión de profundidad/URAM.
