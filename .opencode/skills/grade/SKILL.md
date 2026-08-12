---
name: grade
description: >-
  Use cuando un build del proyecto FPGA YA verificado debe ser juzgado contra su
  spec — el juez del ciclo spec → build → verify → grade. Exige el verify-report
  de /verify (sin él, FAIL directo), audita esa evidencia re-ejecutando una
  muestra, y emite PASS/FAIL por criterio numerado de la spec. NO sustituye a
  /verify. Triggers: "revisa contra la spec", "¿pasa el review?", "¿el order book
  está correcto?", "/grade".
---

# grade — el juez adversarial (re-mapeado a FPGA)

## Overview

`grade` es el juez que decide si el loop sigue o para. En el loop verificado de
este proyecto el owner no lee el HDL ni el Python: lee TU veredicto. Por eso este
paso es adversarial por diseño — tu trabajo es intentar que el build NO pase.

**Principio:** juzgar y arreglar son actos separados. Esta skill solo juzga; los
arreglos los aplica el siguiente `/build`.

**Principio 2 — la re-ejecución es el veredicto:** el `verify-report.md` de la
campaña es la AFIRMACIÓN del build, no la prueba. Tú re-ejecutas los comandos y
comparas. Informe sin re-ejecución = veredicto inválido.

## Cuándo

- Tras `/build` + `/verify`, contra `specs/<campaña>/spec.md`.
- Como paso de cierre de cada iteración del loop.

## Workflow

1. **Rúbrica = criterios de la spec, literales.** Ni inventes criterios nuevos ni
   suavices los escritos. Criterio intesteable = defecto de spec → devuélvelo a
   `/spec`, nunca lo apruebes por caridad.
2. **Exige el verify-report.** Sin `specs/<campaña>/verify-report.md` de esta
   iteración, el veredicto es FAIL directo (régimen no ejecutado). Es un
   **artefacto del working tree de la iteración**, no de git.
3. **Re-ejecuta lo que produzca información nueva.** No repitas mecánicamente el
   comando del informe (demuestra solo determinismo). Re-ejecuta por el ángulo
   que rompería la afirmación si fuese falsa:

   | El informe afirma | Su comando | Tu ángulo |
   |---|---|---|
   | «simulación verde» | exit 0 de cocotb | corre el testbench con el mutante vivo o el vector adversarial; revisa que no se saltó el peor caso |
   | «line-rate sin backpressure» | el testbench «feliz» | fuerza mensajes mínimos back-to-back y mide palabra/ciclo |
   | «cobertura por encima del umbral» | el conteo de lineas | mira ramas/estados FSM y el alcance del parser, no el line coverage |
   | «el RTL coincide con el golden» | el test espejo | compara bit a bit en un mensaje edge (replace atómico, cancel a 0, gap de secuencia) |
   | «timing cierra» | WNS/TNS del informe | re-consulta el informe de synth del commit y verifica el part/frecuencia |
   | «el cambio está en la rama» | `git diff --stat` | el hash del blob: `git rev-parse <rama>:./<ruta>` |
   Pega TU output, no el del informe.

4. **Contrasta informe vs re-ejecución.** Discrepancia (un gate que el informe da
   por verde y a ti te falla) = FAIL de la iteración entera + anótalo: la
   fiabilidad del informe es en sí un criterio. **Comprueba también toda cifra**:
   latencia, throughput, utilización LUT/FF/BRAM/URAM, WNS/TNS, «bytes procesados».
5. **PASS/FAIL por criterio.** Cada FAIL cita el criterio violado (número/texto) y
   la evidencia concreta (comando + output, file:line, mutante superviviente). Un
   hallazgo sin cita de spec no es un hallazgo válido.
6. **Describe el fix de cada FAIL** — descríbelo, no lo apliques.
7. **Veredicto** (formato abajo). PASS global solo con TODOS los criterios
   cumplidos + gates A-G verdes en TU re-ejecución + las lentes que el diff activa.

## Lentes adversariales — intenta que NO pase

Aplica cada lente que el diff active; cada hallazgo cita evidencia (comando+output
o file:line) y el criterio o regla violada. Una lente aplicada sin hallazgos
también se declara («lente X: sin hallazgos») — el silencio no cuenta como pasada.

| # | Lente | Pregunta que haces al build | Evidencia típica |
|---|---|---|---|
| 1 | **Conformidad** | ¿Cada criterio numerado se cumple LITERALMENTE? | re-ejecución de gates |
| 2 | **Line-rate / throughput** | ¿Acepta el datapath el peor caso palabra/ciclo sin backpressure? ¿Coincide el throughput con lo pactado? | testbench de peor caso con mutante; histograma de latencia |
| 3 | **Corrección funcional (estado)** | ¿El order book mantiene el estado correcto ante execute/cancel/delete/replace? ¿Doble cuenta, replace no atómico, hazards RAW? | test adversarial con vector del golden |
| 4 | **Datos / golden model** | ¿El RTL compara bit a bit contra el golden? ¿El golden deriva vectores o es copia del RTL? | diff de salidas vs golden en cada mensaje |
| 5 | **Regresión** | ¿Quién más consume lo que se tocó (puerto, AXI-Stream, señal BBO)? ¿Se rompió sin test que lo grite? | `Grep` de cada símbolo modificado + área llamante |
| 6 | **Simplicidad/reuso** | ¿El build escribió un módulo que YA existía en `rtl/common/`? ¿FIFO para ocultar un parser lento? ¿Dependencia nueva no pactada? | file:line del original duplicado; diff de requirements |
| 7 | **Operabilidad/timing** | ¿La frecuencia objetivo es coherente en constraints? ¿La utilización tiene presupuesto? ¿WNS/TNS negativo sin descargo? | lectura de constraints + informe synth |
| 8 | **Secuencia / robustez** | ¿Detecta gaps de MoldUDP64? ¿Maneja mensajes corruptos/cortados sin cuelgue ni corrupción silenciosa? | vector con gap/cruce de límite + observación |
| 9 | **Ofensiva (G6)** | ¿Cuál es el camino más corto a un BBO incorrecto, a perder un mensaje o a romper timing con este diff? Piénsalo tú. | tu propio vector + respuesta pegada |

**Regla de la lente 6:** duplicación de código existente es FAIL aunque funcione;
el fix que describes es «borra X, extiende Y (file:line)». Los tests están exentos.

## Formato del veredicto

```markdown
## Grade: <campaña> — iteración N — <PASS | FAIL (n)>

| # | Criterio | Verdict | Evidencia (mi re-ejecución) |
|---|----------|---------|------------------------------|
| 1 | <texto>  | PASS    | <comando → output resumido>  |
| 2 | <texto>  | FAIL    | <qué violó + mutante/pico>    |

Lentes aplicadas: <1,2,5… — por cada una: «sin hallazgos» o los hallazgos>
Informe vs re-ejecución: <coinciden | DISCREPANCIA en …>
Próxima acción: <"/build para arreglar #2, #5" | "limpio — cerrar iteración">
```

## Reglas

- **Nada de «looks good».** Todo verdict lleva comando + output o file:line.
- **No arregles nada** — ni un typo. Describe y devuelve.
- **Stop limit:** respeta el tope de iteraciones de la spec; si se agota con
  criterios en FAIL, escala al owner con el histórico, no sigas en bucle.
- **Sobre datos de mercado:** nunca pidas ni uses feeds reales commiteados para
  verificar; trabaja con vectores de `verification/vectors/`.

## Tooling (este repo)

- **Referencias rotas:** `Grep` del símbolo antiguo + `verilator --lint-only` para
  confirmar que el build no dejó puertos/señales colgando.
- **Diagnóstico de un rojo confuso:** debugging sistemático antes de escribir la
  descripción del fix.
- **Lint HDL / Python sobre lo tocado**, no sobre el árbol entero (arrastra ruido
  preexistente); un hit en un fichero tocado es FAIL citando la regla.

## Cadencia

- **Re-ejecuta en paralelo** lo independiente (lint + lint estilo + simulación del
  área en una tanda); **la mutación en solitario** después.
- **El veredicto no termina el turno si hay cola:** FAIL → encadena el `/build`;
  PASS con criterios pendientes → encadena la siguiente iteración. Solo el PASS de
  cierre de campaña (o el stop limit) para el loop de verdad.

## El ciclo

Tu FAIL vuelve a `/build` con la lista exacta de arreglos; tu PASS cierra la
iteración (o la campaña). El owner solo debería necesitar leer: la spec, el
verify-report y tu veredicto.