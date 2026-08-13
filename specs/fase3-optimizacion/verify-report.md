# verify-report — fase3-optimizacion

> Régimen de gates de Atenea re-mapeado al flujo HDL. El owner no lee HDL/Python:
> esta evidencia (outputs reales) es lo que `/grade` re-ejecutará.
> Estado: iteración 1 pendiente de `/build`.

## Meta del atacante/diseño (1-2 frases)

_Se rellena en cada iteración._

## Tabla de gates

| Gate | Comando / evidencia | Resultado |
|---|---|---|
| **A. Simulación** | `make sim` (área `verification/testbenches/phase3/`) | — |
| **B. Compilación/lint sintaxis** | `verilator --lint-only -Wall` sobre lo tocado | — |
| **C. Estilo** | `verible-verilog-lint` (si instalado; sustituto `--Wall`) | — |
| **D. Cobertura + mapeo** | Tabla spec↔tests | — |
| **E. Mutación HDL** | runner de mutación de phase3 | — |
| **F. Completitud Gherkin** | espejos del `.feature` ↔ tests | — |
| **G. Rigor + timing** | G0/G2/G3; G timing: informe del run externo del owner (criterio 10) | — |

## Veredicto

Pendiente de iteración 1.
