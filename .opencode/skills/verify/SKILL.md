---
name: verify
description: >-
  Use ANTES de declarar cumplido un criterio de spec del proyecto FPGA, antes de
  commitear un cambio de campaña, y siempre antes de /grade — ejecuta los 7 gates
  de Atenea re-mapeados al flujo HDL (simulación cocotb/Verilator, lint y estilo,
  cobertura funcional, mutación HDL, completitud del parser ITCH, timing+recursos
  en Vivado) y deja la evidencia pegada en specs/<campaña>/verify-report.md.
  Sin este informe, /grade da FAIL directo. Triggers: "verifica el cambio",
  "comprueba que el parser cierra", "¿está verde?", "pasa los gates", "/verify".
---

# verify — el régimen de gates re-mapeado a FPGA

## Overview

`verify` es el régimen de restricciones del loop verificado, adaptado de la app
clínica al proyecto FPGA. El owner NO lee el HDL ni el Python: confía porque el
código sobrevivió a gates que no se pueden narrar. Cada gate es un comando que
falla de verdad. La salida es un **informe con outputs reales**
(`specs/<campaña>/verify-report.md`) que `/grade` re-ejecutará.

**Principio:** un gate «pasado» sin su output pegado NO está pasado. La narración
no es evidencia.

## Cuándo

- Después de `/build`, antes de `/grade`, en cada iteración del loop.
- Antes de cualquier commit que cierre un criterio de la spec.

## Los 7 gates (todos obligatorios para PASS)

> Los comandos exactos y umbrales detallados se fijan en `docs/DESARROLLO.md` y
> en `scripts/verify/thresholds.json` (si la campaña los define). Los comandos
> de abajo son el contrato conceptual; ajusta la invocación concreta a los
> makefiles/scripts del repo.

| Gate | Concepto re-mapeado | Falla si |
|---|---|---|
| **A. Simulación (tests)** | `cocotb` + `Verilator` (o Questa): correr los testbenches del área afectada. `test_critical` al cierre de campaña. | cualquier testbench en rojo |
| **B. Compilación/lint sintaxis** | `verilator --lint-only` (y `--Wall --Wno-*` con el trinquete del proyecto) sobre lo tocado; para Python, el lint/typecheck del repo. | errores de sintaxis/lint HDL; fichero Python tocado con error |
| **C. Estilo + rigidez** | `verible-verilog-lint` (o el linter de estilo de la casa) sobre lo tocado, + revisión de convenciones (reset, flancos, no latches). No el árbol entero: arrastra ruido preexistente. | cualquier uso fuera de convención en un fichero tocado |
| **D. Cobertura + mapeo** | **Dos niveles.** (1) cruce spec↔tests: cada criterio de la spec nombra el test que lo pincha (tabla en el verify-report). (2) cobertura funcional de simulación: ramas, estados FSM, saltos del parser — vía cocotb-coverage / Informe de cobertura Verilator. Umbrales en `thresholds.json`. | (1) criterio sin test nombrado; (2) cobertura por debajo del umbral |
| **E. Mutación HDL** | Mutation testing del módulo: mutar el RTL (p. ej. flip de comparador, borrar un `else`, invertir un guard) y confirmar que un test LO MATA. Verilator lo permite con runner de la casa o Stryker/questa-mutation si se pacta en spec. | algún mutante sobrevive |
| **F. Completitud Gherkin** | Cada escenario del `.feature` tiene su test espejo (título literal) en `verification/<área>/` y viceversa; cada área está declarada en `specs/gherkin-espejos.json`. | escenario sin test, test sin escenario, o área sin entrada |
| **G. Rigor + timing + recursos** | Checklist por superficie (abajo) + al cierre de campaña el informe de **timing closure y utilización** (LUT/FF/BRAM/URAM) del módulo en Vivado apuntando al part US+ objetivo. | cualquier ítem de la checklist sin evidencia; WNS/TNS negativo o utilización por encima del presupuesto sin descargo |

## Tres verdes que no miden nada (reproducidos en este dominio)

- **cobertura de código HDL ≠ cobertura funcional.** Un *line* coverage alto puede
  convivir con una FSM que salta una rama crítica del protocolo. El gate D mira el
  alcance real (ramas/estados/mensajes), no el conteo de lineas.
- **«compila en Verilator» sin `--Wall`.** Verilator sin warnings omite muchos
  errores de estilo/diseño. El gate B usa el nivel de warnings con la política del
  proyecto, no el default mínimo.
- **simulación de un solo vector dorado.** Un testbench que solo corre un pcap
  «feliz» no caza el peor caso (mensajes mínimos, cruces de límite, gaps). El gate
  A exige los vectores adversariales de la spec.

## Gate G en detalle — rigor por superficie

El diff decide qué sub-checks aplican. `git diff --name-only <base>` y clasifica.
Cada check pasado se evidencia en el informe (comando + output, o test `SEC-`).

**G0 — siempre, cualquier diff:**
- **Datos privados:** ningún literal que parezca dato real de mercado/clave en lo
  tocado; los feeds reales van a `data/` (gitignored) o `verification/vectors/`.
- **Nada de datos crudos commitados:** revisa `git status` por artefactos
  `.NASDAQ_ITCH50.gz`/`.pcap` fuera de `data/`.
- **No-registros ni constantes mágicas del protocolo fuera de su fuente:** la
  talla/tipo de mensaje ITCH no se reescribe a mano si el golden model lo deriva.

**G1 — el diff toca `rtl/parser/` o añade lógica de decodificación:**
- **Line-rate:** el peor caso (mensajes mínimos back-to-back) se acepta palabra a
  palabra sin backpressure — con test `SEC-`.
- **Alineador/barrel shifter:** mensajes que cruzan límites de palabra y paquete
  con test dedicado.
- **Secuencia:** detección/señalización de gaps MoldUDP64 presente.
- **Endianness:** ITCH es big-endian; verifica el orden de bytes en cada campo.

**G2 — el diff toca `rtl/orderbook/` (estado):**
- **Replace atómico:** el BBO nunca muestra una ventana de inconsistencia (no
  Delete+Add visible entre ciclos).
- **Doble cuenta:** execute/cancel/delete no descuentan dos veces la cantidad de
  una orden ni de un nivel.
- **Hazards RAW:** dos mensajes consecutivos sobre la misma orden/nivel dan el
  resultado correcto (forwarding/stall) — con test concurrencial real.
- **Desbordamiento:** contadores de cantidad/precio URAM con ancho correcto y
  chequeo de overflow.

**G3 — el diff toca `golden_model/` o los vectores:**
- El RTL se compara **bit a bit** contra el golden model en cada mensaje; nunca
  «parecen coincidir».
- Labels sintéticos para vectores de demo; fechas/entradas del feed sin inventar.
- El golden model es la fuente de los vectores de referencia, no una copia del RTL.

**G4 — el diff toca `synth/` o constraints:**
- Constraints antecesores coherentes con la frecuencia objetivo (156,25 MHz →
  quizá 322 MHz en fase 3 con su propio constraint).
- Utilización (LUT/FF/BRAM/URAM) con presupuesto y descargo si se excede.
- Informe WNS/TNS pegado al cierre de campaña; WNS negativo = FAIL salvo descargo.

**G5 — cierre de campaña con superficie sensible (parser/order book):**
- Revisión de rigor/timing con ojos de reviewer independiente (o el agente
  `explore` de opencode como segunda opinión). Contrasta sus hallazgos.

## Cómo reportarlo

En `specs/<campaña>/verify-report.md`:
1. **Meta del atacante/diseño** para este cambio (1-2 frases): «¿cómo podría este
   módulo dar un BBO incorrecto, perder un mensaje o exceder timing?».
2. Tabla, una fila por gate: `A | cocotb ... | n passed | PASS`.
3. Cruce spec↔tests (gate D nivel 1).
4. Gate G: checklist por superficie con evidencia.
5. **Veredicto:** «listo para /grade» o «vuelve a /build con: …».

Un gate no ejecutado se declara **NO EJECUTADO**, nunca PASS. Todo hallazgo crítico
(pérdida de línea, BBO incorrecto, WNS negativo) escala al owner.

## Atajo y cortes

- Un orquestador `verify:change` (si lo define la campaña) corre el área afectada
  + lint + cobertura con resumen PASS/FAIL. La **mutación (gate E) corre en
  exclusiva** — muta el working tree; no la solapes con la simulación.
- Corte rápido del diff de un fichero: lint + simulación del testbench de ese
  módulo antes de la suite entera.
- **Si el diff no toca HDL ni Python** (p. ej. solo `synth/reports/` o `data/`),
  el atajo no aplica: verifica a mano lo que toque (informe de timing, tamaño de
  datos).

## Reglas

- **Umbrales en un solo sitio:** `scripts/verify/thresholds.json` (o el makefile
  de la campaña). No dupliques números aquí.
- **Rojo ajeno ≠ rojo tuyo:** si una prueba está roja por otra campaña del working
  tree, aísla y dilo en el informe; no lo ocultes ni lo arregles tú.
- **No se debilita un gate para pasar:** ni bajar umbral de cobertura, ni saltar
  un mutante, ni `--Wall` rebajado sin motivo.
- **Mutante superviviente = test que falta**, no mutante que sobra: escribe el
  test que lo mate. Si es equivalente-semántico genuino (raro), documéntalo.

## Cadencia

- **Paraleliza lo que no comparte estado:** lint (B, C) en paralelo con la
  simulación del área (A); el gate E (mutación) siempre en solitario.
- **Sin espera muerta:** monta el esqueleto del informe y la tabla spec↔tests
  (gate D nivel 1) mientras corren los shards/benchmarks.
- La optimización de timing (fase 3) se documenta como capítulo aparte, no como
  punto de partida (decisión del documento maestro).

## El ciclo

`/spec` define el contrato → `/build` implementa con TDD → **`/verify` ejecuta el
régimen y produce el informe** → `/grade` re-ejecuta y emite el veredicto. Si
`/grade` encuentra discrepancia entre tu informe y su re-ejecución, la iteración
entera queda bajo sospecha.

**Al terminar el informe, no duermas:** si el veredicto es «listo para /grade»,
encadena `/grade` en el mismo turno. Si es «vuelve a /build», encadena el build.
