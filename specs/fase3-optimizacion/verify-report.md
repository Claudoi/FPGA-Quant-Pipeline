# verify-report — fase3-optimizacion

> Régimen de gates de Atenea re-mapeado al flujo HDL. El owner no lee HDL/Python:
> esta evidencia (outputs reales) es lo que `/grade` re-ejecutará.

## Iteración 1 — variante DW=32 parser + book + cadena (criterios 1-3), REG-01

### Meta del atacante/diseño

La parametrización de 64 bits fijos a DW ∈ {32, 64} no debe cambiar NI un bit
del contrato de 64 bits (fases 1/2) y debe producir el Anexo A de 32 bits del
Anexo de la spec (w0={type,locate,len}, w1=idx, w2=ts[31:0], w3={ts[47:32],16'b0},
w4..=cuerpo) bit a bit contra el oráculo, y la cadena parser→book debe cerrar
BBO bit a bit con el golden sobre el feed real.

### Rojo con evidencia (TDD)

| Test | Rojo | Causa raíz |
|---|---|---|
| P32-01 (parser DW=32) | `%Warning-WIDTHTRUNC` + `%Error: Exiting due to 5 warning(s)` en itch_parser.sv (RHS de 64 bits a reg de 32) | cbody/body_w/W0-TS fijos a 64 bits |
| B32-01 (book DW=32) | `%Warning-SELRANGE` + `%Error: Exiting due to 7 warning(s)` — `63:56 outside 31:0` | campos del w0 fijos a 64 bits |
| P32-01 (tras compilar) | `got(0) exp(95)` — sin emisión | cola: `qn += 8` por palabra (fijo 64) → nunca se junta el header de 20 B |
| P32-01 (tras cola) | words de cuerpo desalineadas (stride de 8 B por palabra) | `cbody(..., 11 + 8*bi)` — stride fijo; a DW=32 debe ser `11 + BYTES*bi` |
| CHAIN-01 | `got(146343) exp(30729)`; primer desajuste evento 67 | test mal dirigido: alimentaba el feed completo (150K registros, todos los símbolos) — overflow NSYM es el hallazgo F1 del grade, hardening de la iteración 4; el contrato es el stream del subset |

### Verde (evidencia)

| Suíte | Resultado |
|---|---|
| phase3/parser32 (P32-01, P32-02, INV-P32-01, P32-03 replay pcap real) | **4/4 PASS** (P32-03: 150.000 registros decapados bit a bit) |
| phase3/book32 (B32-01, B32-02 replay real, INV-B32-01/02/03) | **5/5 PASS** (B32-02: 31.400 msgs → 30.729 eventos bit a bit, cross=0) |
| phase3/chain32 (CHAIN-01 real, INV-CHAIN-01 sintético) | **2/2 PASS** (31.400 msgs → 30.729 eventos bit a bit, gaps=0) |
| fase1 regresión DW=64 (REG-01) | **19/19 PASS** |
| fase2 regresión DW=64 (REG-01) | **14/14 PASS** (incl. REPLAY-01) |

### Cambios

- `rtl/parser/itch_parser.sv`: localparams BYTES/L2B; cola con `BYTES` por beat
  (qn/can_aug/can_da, shifts con `+ drain_int` corregido — signo); `cbody` a DW;
  `body_w = ceil((len-11)/BYTES)`; ST_W0/ST_TS emiten el layout de 32 bits con
  contador `hw` (w0, w1=idx, w2-3=ts); casts `DW'()` y `8'()/32'()` para el
  trinquete de anchos en ambas variantes.
- `rtl/orderbook/orderbook.sv`: `pbody` generalizado (índice `b>>L2B`, byte
  `DW-1-8*(b&(BYTES-1))`); campos del w0 por `[DW-1 -: 8]` etc.; `nbody_w`
  a `ceil((len-11)/BYTES)`; `hrem` consume 3 words de cabecera a DW=32 (captura
  `m_idx` de w1); `bi` a 4 bits y `body_acc[0:15]` (cuerpo máximo a DW=32).
- `rtl/itch_chain.sv` (nuevo): top de integración parser→book sin FIFO, DW
  parametrizado, `error = p_error | b_error`.
- `verification/testbenches/phase3/`: Makefile (EXTRA_ARGS `-GDW=32`),
  `test_parser32.py`, `test_orderbook32.py`, `test_chain32.py` — espejos
  P32-01/02, B32-01/02, CHAIN-01 + adversariales; reuso de helpers de fases 1/2.

### Pendiente para iteraciones siguientes

- Criterios 4-11 (hash+probing, top-N, hardening F1/F2, latencia, URAM/synth).
- F1 (NSYM overflow) y F2 (bbo_tready) son SEC-NSYM-01/SEC-BP-01 (criterios 8-9).

## Tabla de gates

| Gate | Comando / evidencia | Resultado |
|---|---|---|
| **A. Simulación** | 3 suites phase3 + 2 regresiones: 11/11 + 19/19 + 14/14 PASS | ✔ |
| **B. Compilación/lint sintaxis** | Verilator 5.050 limpio en ambas variantes (trinquete documentado) | ✔ |
| **C. Estilo** | `verible-verilog-lint` (si instalado) | — |
| **D. Cobertura + mapeo** | Tabla spec↔tests (pendiente al cierre) | — |
| **E. Mutación HDL** | Runner de mutación phase3 (iter 2+) | — |
| **F. Completitud Gherkin** | espejos del `.feature` ↔ tests | — |
| **G. Rigor + timing** | G0/G2/G3 ✔ (vectores/feed no commiteados); G timing: run externo del owner (criterio 10) | — |

## Veredicto

Iteración 1 (criterios 1-3 + REG-01): **verde con evidencia**; pendiente de
`/verify` formal y criterios 4-11.