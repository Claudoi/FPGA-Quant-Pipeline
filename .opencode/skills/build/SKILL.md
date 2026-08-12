---
name: build
description: >-
  Use cuando ya existe una spec escrita (en specs/<campaña>/) del proyecto FPGA
  y el trabajo es implementarla con TDD estricto — el paso build del ciclo
  spec → build → verify → grade. En HDL esto significa escribir el testbench
  cocotb (rojo) antes que el módulo SystemVerilog, con el rojo evidenciado.
  Triggers: "construye esto", "implementa la spec", "/build", "escribe el parser
  ITCH de la fase 1".
---

# build — implementación con TDD estricto (HDL + Python)

## Overview

`build` implementa una feature estrictamente desde su spec escrita. La spec — no
la memoria, no el chat — es el contrato. En el loop verificado de este proyecto
el código que produzcas no lo leerá nadie: lo juzgarán los gates `/verify` y
`/grade`. Por eso el orden es innegociable: **el test existe y está en rojo ANTES
que el código** — en HDL, el testbench cocotb nace antes que el módulo RTL.

Ejemplo del orden correcto para un módulo:
1. Testbench cocotb que instancia un módulo aún inexistente y compara sus salidas
   contra un vector derivado del golden model.
2. Ver el rojo (el módulo no compila o la simulación falla).
3. Implementar el RTL mínimo hasta el verde.

## Cuándo

- Tras `/spec`, con `specs/<campaña>/spec.md` confirmada.
- Como paso build de cada iteración del loop.

**NO** sin spec. Spec ambigua → parar y arreglar LA SPEC, no adivinar en el
código. **Prohibido editar la spec desde build**: si está mal, vuelve a `/spec`.

## Workflow (TDD, en este orden)

1. **Lee la spec** y elige el/los criterios de esta iteración.
2. **Espejo Gherkin primero.** Para cada escenario del `.feature` que cubre el
   criterio: escribe su test de título IDÉNTICO en `verification/<área>/<módulo>_test.py`
   (el mapa `specs/<campaña>/gherkin → verification/<área>` vive en
   `specs/gherkin-espejos.json`, igual que en la app clínica). Tests de
   invariante o adversariales extra: prefijo `INV-` / `SEC-`.
3. **Rojo con evidencia.** Ejecuta el test y **pega el rojo** en el verify-report
   (`# fail N` con el título). Un test que nunca se vio fallar no demuestra nada.
   Si nace verde: o el comportamiento ya existía (dilo) o el test no pincha
   (arréglalo).
4. **Escalera de reuso ANTES de escribir** (aplica al código de producción,
   NUNCA a los tests):
   1. ¿Lo exige la spec? No → no se escribe, aunque sea «bueno».
   2. **¿Ya existe?** `Grep` por dominio en `rtl/common/`, `golden_model/`,
      `verification/testbenches/` antes de crear nada. Adaptar gana a crear: un
      parámetro nuevo > un módulo paralelo; extender el módulo existente > uno
      nuevo; el helper compartido > la copia local.
   3. ¿Lo trae el estándar? (SystemVerilog/Verilog, URAM/BRAM nativos, cores 10GBASE-R).
   4. ¿Lo trae una dependencia YA instalada? (cocotb, cocotb-bus, numpy, pycocotb
      utilities — en `requirements*.txt`, no asumas).
   5. Dependencia nueva = decisión de `/spec`, jamás de build.
5. **Implementa mínimo** hasta el verde, siguiendo las convenciones del código
   vecino. **Rigor por construcción** (lo que el gate G va a comprobar, hecho de
   serie):
   - **Line-rate:** si la spec exige sin-backpressure, el datapath acepta una
     palabra por ciclo en el peor caso; no lo ocultes con FIFOs elásticas.
   - **Hazards RAW:** dos mensajes consecutivos sobre la misma orden/nivel →
     forwarding o stall selectivo; nunca un resultado incorrecto.
   - **URAM:** latencia de lectura registrada (1-2 ciclos) → el pipeline se
     diseña alrededor de ella, no se "arregla" el signo del resultado.
   - **Mensajes que cruzan límites** de palabra y de paquete → barrel
     shifter/alineador con test `SEC-` dedicado.
   - **Datos de mercado reales jamás commiteados:** los testbenches consumen
     vectores de `verification/vectors/`; el dato crudo queda fuera del repo
     (`.gitignore`).
   - **Secuencia:** detecta y señala gaps de MoldUDP64 (mínimo: contarlos);
     nunca asumas un feed sin huecos.
6. **Verde + colocación.** Los tests cocotb se auto-cablean por ubicación: el
   runner de `verification/` recorre los `*_test.py` de cada `testbenches/`.
   El reglamento de partición (fichero → área) vive en
   `verification/testbenches/README.md` o en el runbook de la campaña.
7. **Mapa de cobertura.** Al terminar, lista qué criterios (por número) cubriste
   y con qué tests — es la tabla spec↔tests que `/verify` exige (gate D nivel 1).
   No declares «done»: eso lo deciden `/verify` y `/grade`.

## Reglas

- **La spec es la frontera.** No está en la spec → no se construye.
- **Cero fantasmas.** Ningún criterio se marca satisfecho sin su cambio + su test.
- **Nada de `skip`/`todo`** en tests de la campaña.
- **Sin `--no-verify`** jamás; los hooks/gates son parte del régimen.
- **Un commit Conventional (español) por avance coherente**, staging selectivo si
  el working tree lleva más campañas.

## Tooling (este repo)

- **Radio de impacto antes de editar:** `Grep` sobre cada símbolo a tocar
  (puertos, señales, campos de mensaje) + un subagente `Explore` para dónde
  cablear. Impacto mayor que lo que la spec implica → de vuelta a `/spec`.
- **Test que no entiendes por qué falla →** debugging sistemático antes de tocar
  nada (el fallo suele ser el test que pincha el peor caso del protocolo, no el RTL).
- **Compilador/lint HDL como segundo par de ojos:** `verilator --lint-only` sobre
  lo tocado para cazar errores de sintaxis/estilo antes de simular. Para Python,
  corre el linter y typecheck del proyecto (`docs/DESARROLLO.md` te da el comando
  exacto; no asumas que existe pyright/mypy).
- **Datapath:** si el objetivo es 32-bit @ 322 MHz (fase 3), trabájalo como
  optimización documentada sobre la base de 64-bit @ 156,25 MHz, no como punto de
  partida (decisión del documento maestro).

## Errores comunes

| Error | Corrección |
|---|---|
| Código antes que test | El rojo primero, con evidencia pegada |
| Test espejo con título «parecido» | IDÉNTICO al escenario; el gate F compara literal |
| Construir de memoria | Re-lee `specs/<campaña>/spec.md`; es el contrato |
| Features no pedidas | Proponer edit de spec, no colarlas |
| Declarar éxito | El veredicto es de `/verify` + `/grade` |
| Ocultar el backpressure con FIFO | Si el objetivo es line-rate, probar el peor caso palabra/ciclo |
| Verificar con dato real commitado | Usar vectores en `verification/vectors/`; el feed real queda fuera |

## Cadencia

- **Mientras corre el rojo/verde de un test, prepara el siguiente espejo.**
- **No termines el turno con cola:** encadena el siguiente criterio o `/verify`
  en el mismo turno.

## El ciclo

Tras construir: `/verify` ejecuta el régimen (gates A-G) y escribe el informe;
`/grade` re-ejecuta y emite veredicto. Cada FAIL vuelve aquí nombrando el criterio
violado; arregla exactamente eso y repite dentro del stop limit de la spec.