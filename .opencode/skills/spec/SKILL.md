---
name: spec
description: >-
  Use al arrancar una feature, tarea o fase del proyecto FPGA quant (parser ITCH,
  order book URAM, golden model Python, síntesis/timing) sin especificación
  escrita y testeable — antes de cualquier /build. También para cerrar una fase
  del documento maestro. Triggers: "vamos a construir X", "necesito una spec",
  "define qué hay que hacer en la fase 1", "/spec". Produce el contrato del ciclo
  spec → build → verify → grade del proyecto FPGA.
---

# spec — contrato del proyecto FPGA

## Overview

`spec` produce la fuente única de verdad de un trabajo: una especificación con
**definition of done** ejecutable, adaptada al flujo FPGA. En el loop verificado
de este proyecto el owner no lee el HDL ni el Python: lee ESTE contrato y el
veredicto de `/grade`. Todo lo que el loop haga bien o mal nace aquí.

**Principio:** un requisito que no se puede comprobar pass/fail con un comando o
un test nombrado no pertenece a la spec. Reescríbelo hasta que se pueda. En HDL
eso significa: ¿cómo lo voy a verificar? — con un testbench cocotb, un chequeo de
lint/timing, o contra el golden model.

## Cuándo

- Antes de `/build` en cualquier cambio no trivial (módulo RTL, testbench, script
  de datos, migración de fase).
- Cuando los requisitos viven solo en el chat o en el documento maestro y hay
  que clavarlos en criterios verificables.
- Cuando el «qué es terminado» de una fase del maestro admite dos lecturas.

**NO** para ediciones mecánicas de una línea donde el cambio ES la spec.

## Workflow

1. **Entrevista — una pregunta enfocada cada vez** hasta poder escribir criterios
   sin ambigüedad: objetivo, alcance (y non-goals explícitos), entradas/salidas,
   latencia/throughput esperados, casos límite, restricciones, y qué es «done».
   En un proyecto FPGA, dos preguntas SIEMPRE caen:
   - **¿Es line-rate?** ¿El datapath acepta una palabra por ciclo en el peor caso
     (mensajes mínimos back-to-back), o admite backpressure/FIFO? Distingue
     "funciona en simulación" de "calidad industrial".
   - **¿Contra qué verifico?** ¿Golden model Python, vectores del feed, o coerción
     por invariante? Esto define el banco de pruebas y el gate D.
   No construyas ni adivines — pregunta.

2. **Estructura de campaña** (obligatoria para todo trabajo con comportamiento):
   ```
   specs/<kebab-campaña>/
     spec.md            ← este contrato
     gherkin/*.feature   ← el contrato FUNCIONAL, escenario a escenario
     verify-report.md   ← lo irá escribiendo /verify
   ```

3. **Gherkin obligatorio:** cada criterio de aceptación con comportamiento
   observable mapea **1:1** a escenarios numerables de un `.feature` (claves en
   español: `Escenario:` / `Esquema del escenario:`). En HDL el espejo lo
   construye `/build` como test cocotb cuyo título de test es IDÉNTICO al
   escenario (ver build). Los casos límite del protocolo (mensajes que cruzan
   límites de palabra/paquete, mensajes mínimos, reemplazos atómicos) son
   escenarios de primera clase.

4. **Declara el espejo:** añade la entrada a `specs/gherkin-espejos.json` con el
   mapa `"specs/<campaña>/gherkin": "verification/<área>"`. Sin entrada, el
   meta-gate de completitud de `/verify` falla — a propósito. (Ver
   `verification/` para la convención de nombres de área.)

5. **Superficie y amenazas** (adaptado del contexto clínico al de trading):
   - Datos que toca: ¿feed real de mercado? ¿BNF? — los feeds reales se mantienen
     fuera del repo; los testbenches consumen vectores en `verification/vectors/`.
   - **Entradas nuevas** (puertos del módulo, palabras del protocolo, campos del
     mensaje) y **salidas nuevas** (interfaz AXI-Stream, señales BBO, métricas de
     latencia): lista literal que el barrido de `/verify` ataca.
   - Casos de abuso específicos de este dominio: **sequence gaps** (MoldUDP64),
     **replace no atómico** (ventana de inconsistencia del BBO), **doble cuenta**
     de cantidades (execute/cancel/delet), **desbordamiento** de contadores URAM,
     **hazards** read-after-write entre mensajes consecutivos.

6. **Relee la spec entera antes de confirmarla** y borra lo que una decisión
   posterior retiró (dos verdades = `/grade` juzga por la que le convenga).
   **Confírmala con el owner** y congélala: cambiarla es un edit explícito.

## Estructura de spec.md

```markdown
# <Campaña> (fase <N> del maestro)

## Goal
Un párrafo: qué problema resuelve del pipeline (parser / order book / golden / timing).

## Scope
- In scope / Out of scope (non-goals) explícitos.
- **Radio medido** — REQUERIDO cuando se renombra, mueve o borra un módulo/puerto/
  señal que ya existe: el número y el comando que lo produjo (fuentes RTL, fuentes
  Python, testbenches, apariciones).

## Constraints
Familia/part objetivo (p. ej. UltraScale+), latencia/throughput objetivo,
tamaño de datapath (64-bit @ 156,25 MHz vs 32-bit @ 322 MHz),
gestión del reloj (CDC si aplica), line-rate sin backpressure.

## Superficie y amenazas
- Puertos/entradas/salidas nuevos (campo a campo) + señales de interfaz nuevas.
- Casos de abuso del dominio (sequence gaps, replace atómico, doble cuenta,
  desbordamiento, hazards RAW) → cada uno con su escenario `SEC-` en el Gherkin.
- Qué requisito del documento maestro se arriesga (latencia determinista, line rate).

## Reuso
Módulos/helpers existentes que esta campaña EXTIEENDE (con fichero). Código nuevo
que duplique uno de esta lista = FAIL de la lente de simplicidad de `/grade`.
Dependencia nueva (library de cocotb, core Vivado) solo si se pacta aquí.

## Criterios de aceptación (Definition of Done)
Numerados, cada uno pass/fail e independiente:
1. [ ] <observable> — Gherkin: <fichero.feature> §<escenarios>
2. [ ] ...

## Verificación
| Criterio | Cómo se prueba (test cocotb, lint, timing, humano) |
El régimen completo lo define la skill verify (gates A-G re-mapeados a HDL); aquí
se nombra lo específico de la campaña + el stop limit del loop.

**Contratos sin gate** — REQUERIDO: qué invariante de esta campaña se puede romper
con la suite y el lint en verde (acoplamiento por literal del protocolo, campos
de mensaje escritos a mano en RTL y en el test que no derivan del golden model).

## Loop
Stop limit: N iteraciones. Cadencia: encadenar build→verify→grade mientras quede cola.
```

## Tooling (este repo)

- **Reconocimiento primero:** un subagente `Explore` sobre el área («cómo
  funciona hoy el parser, quién consume su AXI-Stream, qué tocaría el cambio»)
  alimenta criterios y casos límite.
- **El radio se cuenta, no se estima:** usa `git grep -l` sobre `rtl/` y
  `golden_model/` para medir apariciones de un puerto/símbolo antes de aceptar
  renombrarlo. Dato de referencia del dominio: un mensaje ITCH mínimo ~26-40 bytes
  define el peor caso del parser.
- **Modalidad «no comprar placa»:** el cierre de criterio puede ser simulación
  con datos reales + timing closure en Vivado (part US+), sin hardware físico —
  decisión del documento maestro.

## Errores comunes

| Error | Corrección |
|---|---|
| Criterio vago («procesa el feed») | Reescribir como observable pass/fail (palabra/ciclo, latencia, BBO correcto) |
| Comportamiento sin escenario Gherkin | Cada criterio con conducta → su escenario 1:1 |
| Olvidar el manifiesto de espejos | Sin entrada en `gherkin-espejos.json` el gate F falla |
| «Funciona en simulación» como azúcar | Especificar si el objetivo es line-rate sin backpressure |
| Criterio sin verificación nombrada | Cada criterio lleva su cómo-se-prueba en la tabla de Verificación |
| Dos verdades en el mismo documento | Lo retirado se borra, no se tacha: `/grade` juzga por el texto |

## El ciclo

Tu spec confirmada es la entrada de `/build`; `/verify` prueba contra ella y
`/grade` juzga por sus criterios numerados. Un criterio intesteable que `/grade`
declare vuelve AQUÍ como edit explícito — nunca se suaviza en el veredicto.
