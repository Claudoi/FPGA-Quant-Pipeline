# verify-report — fase2-orderbook (iteración 3)

> Régimen de gates de Atenea re-mapeado al flujo HDL. El owner no lee HDL/Python:
> esta evidencia (outputs reales) es lo que `/grade` re-ejecutará.
> Fecha: 2026-08-13. Área: `rtl/orderbook/` + `verification/testbenches/orderbook/`.
> Iteración 3: cierra el criterio 8 (REPLAY-01 feed real) y el BUG-U del
> replace `U` documentado en `docs/research-orderbook-pendientes.md`.

## Meta del atacante/diseño (1-2 frases)

¿Cómo podría el order book dar un BBO incorrecto, perder una orden, contar dos
veces una cantidad o no señalar un estado inválido? Ataques cubiertos en esta
iteración: replace no atómico (BUG-U), colisiones de order_ref por truncado a
K bits, overflow de niveles (P=8 insuficiente), trading state global de 4 bits
(divergencia con el golden por locate), y el feed real de 20 símbolos como
prueba de integración bit a bit.

## Cambios de iteración 3 (cierre del criterio 8)

- RTL `orderbook.sv`: replace `U` atómico en **2 ciclos** — delete en
  `ST_APPLY`, add en `ST_UADD` (la segunda `level_add` ve la eliminación);
  routing con la salida bloqueante `out_uadd` de `apply_one`.
- `K = 19` (2^19 ≥ max ref del subset real, 372.297; antes 14 bits colisionaba
  4.443 refs). `P = 32` (máx medido 17 niveles por lado, símbolo 6960).
- `tstate[NSYM-1:0]` de 8 bits por símbolo comparado contra `8'h54` (`'T'`
  continuo), replicando el golden por locate.
- Testbench: `S`/`H` se pasan al golden como `chr()` (antes int vs str "Q"/"T"
  → market hours y crosses nunca contaban; SEC-CR-01 era vacuo).
- Tests: nuevo `test_inv_u01_replace_best_bid_estado_final` (repro mínima del
  BUG-U) y `test_replay01_feed_real_bbo` restaurado con el cuerpo real.

## Rojo (evidencia TDD — RTL de la iteración 2, tests nuevos)

```
test_sec_cr01: assert 0 == 1            # golden cross=1 (harness arreglado), RTL 0
test_inv_u01:  got=[...,(1101,(425800,500,0,0),0)] exp=[...,(1101,(425700,500,0,0),1)]
test_replay01: got(30556) exp(30729) sobre 31400 msgs / 20 símbolos
TESTS=14 PASS=11 FAIL=3 SKIP=0
```

## Tabla de gates

| Gate | Comando / evidencia | Resultado |
|---|---|---|
| **A. Simulación** | `make sim` (cocotb+Verilator, `verification/testbenches/orderbook/`) tras `make clean` | 14/14 PASS, 0 FAIL — **PASS** |
| **B. Compilación/lint sintaxis** | `verilator --lint-only -Wall -Wno-EOFNEWLINE --top-module orderbook` | 0 warnings — **PASS** |
| **C. Estilo** | `verible-verilog-lint` **NO EJECUTADO** (herramienta no instalada; sustituto `--Wall` + revisión manual) | **NO EJECUTADO** |
| **D. Cobertura + mapeo** | Tabla spec↔tests abajo; cobertura funcional runner **NO EJECUTADO** (no configurado) | Nivel 1 **PASS** |
| **E. Mutación HDL** | `python3 scripts/verify/mutate_orderbook.py` | **8/8 muertos, 0 sobreviven** — **PASS** |
| **F. Completitud Gherkin** | 12 escenarios ↔ 13 tests espejo (tabla abajo); REPLAY-01 restaurado | **PASS** |
| **G. Rigor + timing** | G0/G2/G3 checklist; G timing NO APLICA (fase 1-2, hasta fase 3) | **PASS** |

## Gate D nivel 1 — cruce spec ↔ tests

| Criterio spec | Test(s) espejo | Estado |
|---|---|---|
| 1 (BBO bit a bit vs golden) | `test_bbo01` + `test_rep02` | PASS |
| 2 (replace atómico) | `test_sec_u01` + `test_inv_u01` | PASS |
| 3 (hazards RAW) | `test_sec_hz01`, `test_sec_hz02` | PASS |
| 4 (doble cuenta) | `test_sec_dc01`, `test_sec_dc02` | PASS |
| 5 (overflow) | `test_sec_ov01` | PASS |
| 6 (anomalías y cruzados) | `test_sec_an01`, `test_sec_cr01` | PASS (SEC-CR-01 ahora pincha de verdad) |
| 7 (multi-símbolo) | `test_multi01` | PASS |
| 8 (replay real + vectores) | `test_replay01` (feed real 31400 msgs, **30729 eventos bit a bit**, anomaly 671, cross 0) + `test_rep02` (vectores congelados) | **PASS** |
| 9/10 (lint/estilo) | gates B/C | B PASS, C NO EJECUTADO |

## Gate F — espejos Gherkin (título literal → test)

| Escenario | Test espejo |
|---|---|
| BBO-01 | `test_bbo01_secuencia_bbo_igual_golden` |
| BBO-02 | `test_sec_em01_simbolo_vacio` |
| SEC-U-01 | `test_sec_u01_replace_atomico` (+ `test_inv_u01_replace_best_bid_estado_final`, borde) |
| SEC-HZ-01 | `test_sec_hz01_add_execute_raw` |
| SEC-HZ-02 | `test_sec_hz02_replace_execute_raw` |
| SEC-DC-01 | `test_sec_dc01_sin_doble_descuento` + `test_sec_dc02_delete_descuenta_exacto` |
| SEC-OV-01 | `test_sec_ov01_overflow_cantidad` |
| SEC-AN-01 | `test_sec_an01_ref_desconocida` |
| SEC-CR-01 | `test_sec_cr01_libro_cruzado` |
| MULTI-01 | `test_multi01_dos_simbolos_independientes` |
| REPLAY-01 | `test_replay01_feed_real_bbo` — **RESTAURADO** (cuerpo real, 31400 msgs) |
| REPLAY-02 | `test_rep02_vectores_congelados_bbo` |

## Gate E — mutación HDL (evidencia resumida)

Runner: `scripts/verify/mutate_orderbook.py` (actualizado al RTL de la
iteración 3; añadidos `U-DELETE-HALF` y `U-SKIP-ROUTE`).

```
[MATADO] OV-BEST: killed       # flip del comparador de mejor precio
[MATADO] OV-EMPTY: killed      # acepta overflow de niveles silencioso
[MATADO] U-NOTATOMIC: killed   # replace sin añadir la nueva orden (ST_UADD)
[MATADO] U-DELETE-HALF: killed # replace conserva la qty de la orig (doble cuenta)
[MATADO] U-SKIP-ROUTE: killed  # replace no entra en ST_UADD (ref nueva nunca registrada)
[MATADO] D-DOUBLE: killed      # delete descuenta 2× (SEC-DC-02 añadido)
[MATADO] RED-REF: killed       # reduce sobre ref desconocida sin anomalía
[MATADO] EMIT-NOCHANGED: killed# changed siempre 0
TODOS LOS MUTANTES MUERTOS. Gate E PASS.
```

## Gate G — checklist por superficie

**G0:** datos reales fuera del repo (pcap del día en `/tmp/` para REPLAY-01);
vectores commiteados sintéticos (`verification/vectors/bbo/`).

**G2 (rtl/orderbook/ — estado):**
- **Replace atómico**: `test_sec_u01` + `test_inv_u01` (borde best-bid) — el BBO
  del `U` es el estado final, nunca intermedio; mutantes U-NOTATOMIC,
  U-DELETE-HALF y U-SKIP-ROUTE muertos.
- **Doble cuenta**: `test_sec_dc01` (execute+cancel) y `test_sec_dc02` (delete
  exacto) — el mutante D-DOUBLE muerto lo prueba.
- **Hazards RAW**: `test_sec_hz01` (add→execute), `test_sec_hz02`
  (replace→execute) — el segundo mensaje ve el estado del primero.
- **Desbordamiento**: `test_sec_ov01` (reduce > qty → error), overflow de
  niveles >P señalizado (mutante OV-EMPTY muerto).

**G3 (golden/vectores):**
- BBO bit a bit vs `book.py` en `test_bbo01`, `test_replay01` (30.729 eventos
  del feed real) y vectores congelados en `test_rep02` — el oráculo es
  `book.py` (independiente del RTL).
- Los campos del cuerpo se decodifican con `message_oracle`/`book.py` (misma
  fuente), no con literales del RTL.

## D.2 / hallazgos abiertos

1. **Gate C (verible) y D nivel 2**: NO EJECUTADOS (herramientas no
   disponibles/configuradas en el entorno).
2. **Dimensionado documentado para fase 3**: tabla de órdenes 2^19 (≈4,3 MB ≈
   120 URAM si se implementa en URAM) y niveles P=32 por lado — medidos sobre
   el subset real (max ref 372.297, max 17 niveles ask en 6960).
3. **Profundidad de book (N niveles públicos) y pipeline URAM**: fuera de
   scope de fase 2 (BBO-only; optimización fase 3).

## Veredicto

**Listo para /grade (iteración 3).** Gates A/B/E/F PASS; C/D-nivel2 declarados
NO EJECUTADOS (entorno); G0/G2/G3 PASS; G timing NO APLICA. **Criterio 8
PASS completo** (REPLAY-01 feed real + REPLAY-02 vectores congelados). No queda
ningún criterio pendiente de la spec dentro del scope de fase 2.
