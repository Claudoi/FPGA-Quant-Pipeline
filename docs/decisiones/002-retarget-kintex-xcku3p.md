# 002 — Retarget del part objetivo a Kintex XCKU3P (criterio 10 sin licencia de pago)

**Fecha:** 2026-08-17 · **Estado:** aceptada

## Contexto

El cierre de timing del criterio 10 exige un run real de Vivado sobre el part
objetivo. El part fijado en fase 3 era `xcvu9p-flga2104-2L-e` (Virtex
UltraScale+ VU9P), que **solo se sintetiza con Vivado ML Enterprise** (licencia
de pago, desde ~$4.395; la evaluación gratuita es única y temporal). Decisión
del owner: **no pagar nada** y priorizar que el run sea reproducible por
cualquiera.

Vivado ML Standard (gratuito, sin caducidad; y tier BASIC del modelo 2026.1)
soporta Kintex UltraScale+ `XCKU3P` y `XCKU5P` (tabla de soporte de UG973). El
documento maestro ya contempla la familia «Zynq US+ o Virtex/Kintex US+»: el
retarget no traiciona el objetivo del proyecto.

## Decisión

El part objetivo de la variante 32-bit @ 322,265625 MHz pasa a
**`xcku3p-ffva676-2L-e`** (Kintex UltraScale+, mismo speed grade -2L y grado de
temperatura -e que el VU9P fijado). Si Vivado rechazara ese string exacto en la
instalación, el fallback pactado es `xcku3p-ffva676-2-e` (a 0,85 V el -2LE
rinde igual que el -2 según DS922; se documenta aquí, no en el RTL).

Idoneidad medida:

- La tabla de órdenes es un array único de 65.536×86 bits ≈ 5,64 Mb.
- **ENMIENDA 2026-08-18 (dato del propio Vivado, no del datasheet):** el
  XCKU3P tiene **48 URAM** (288 Kb c/u ≈ 13,8 Mb) y 360 BRAM36K; el conteo
  original «360 URAM (36 Mb)» era erróneo (360 es el BRAM). La inferencia
  real de `o_mem` con `(* ram_style = "ultra" *)` mapea **32 URAM288**
  (16 de profundidad × 2 de ancho; cascade height 8) → 32/48 = 67 % de los
  URAM del part: cabe, pero con margen ~1,5×, no ~17×.
- LUTs: el diseño usa miles de LUT; el XCKU3P tiene 162.720 CLB LUTs.
- Misma arquitectura UltraScale+ y mismo régimen de reloj (322,265625 MHz /
  periodo 3,103 ns): el reto de timing es idéntico al del VU9P.

## Consecuencias

- Edit de contrato documentado en `specs/fase3-optimizacion/spec.md` y
  `specs/fase3-uram/spec.md` (Constraints y criterio 7/10).
- `synth/fase3_synth.tcl` (línea del part), `synth/constraints/fase3_322mhz.xdc`
  (comentario), `synth/reports/README.md` y `scripts/verify/synth_check.py`
  (constante PART + docstring) alineados.
- Los write-ups fechados de la era VU9P (mapeo URAM, revisión exhaustiva y
  plan de la sesión URAM) se consolidaron en
  `docs/writeup/lecciones-aprendidas.md` y sus originales se eliminaron en la
  limpieza de documentación de 2026-08-18; la referencia operativa vigente es
  la spec.
- El run `vivado -mode batch -source fase3_synth.tcl` se puede reproducir en
  cualquier máquina con Vivado ML Standard instalado (registro AMD gratuito,
  sin licencia de pago).
- Si en el futuro se dispone de licencia Enterprise (universitaria o de pago),
  revertir el part en `fase3_synth.tcl` a `xcvu9p-flga2104-2L-e` re-corre el
  mismo flujo sin más cambios (el RTL y el XDC no son dependientes del part).

Evidencia de soporte: tabla de soporte de UG973 (Vivado ML Standard incluye
Kintex UltraScale+ XCKU3P/XCKU5P) y hoja de datos DS922 (recursos del XCKU3P).
