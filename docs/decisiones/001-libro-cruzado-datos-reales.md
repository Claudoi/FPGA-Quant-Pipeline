# 001 — Libro bloqueado/cruzado en datos reales: contar, no abortar

**Fecha:** 2026-08-12 (fase 0, iteración 2) · **Estado:** aceptada

## Contexto

La invariante «bid < ask en trading continuo, violación = abort» se escribió
en la spec de fase 0 asumiendo que el libro de Nasdaq nunca se cruza fuera de
subastas. El primer run sobre datos reales (día 2019-12-30) abortó en el
mensaje 39.778.763: símbolo ZJZZT (símbolo de test de Nasdaq) con
bid == ask == 130000 durante 2 mensajes, formado en una transición
halt→trading.

## Decisión

El cruce/bloqueo en trading continuo **se cuenta y se reporta**
(`Book.cross_events`, resumen del run), no aborta. El modo estricto
(`strict_cross=True` / `--strict`) mantiene el abort y es el que ejercitan
los tests sintéticos. Las demás invariantes (refs duplicadas, qty no
positiva, niveles inconsistentes) abortan siempre.

## Consecuencias

- Spec fase0 criterio 3 reescrito (con la evidencia) + escenario SEC-08.
- El RTL de fase 2 hereda esta semántica: el BBO puede quedar bloqueado
  transitoriamente en datos reales; el testbench no debe tratarlo como bug.
- Referencia para el write-up: 642 eventos / 268,7M mensajes ese día.

Evidencia completa: `specs/fase0-golden-model/verify-report.md` (sección
«Iteración 1 → hallazgo real»).
