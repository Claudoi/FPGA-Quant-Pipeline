# Plan de cierre — pipeline FPGA Nasdaq ITCH → order book URAM (fases 1-4)

> Documento maestro de **cierre del proyecto**: estado verificado al día,
> objetivos pendientes con su alcance exacto, riesgos y orden de ejecución.
> Escrito para ser leído por un ingeniero de verificación/RTL (o un modelo de
> IA) y arrancar la construcción del trabajo restante sin ambigüedad.
>
> Fuentes de verdad: `AGENTS.md`, `specs/<campaña>/spec.md` + `gherkin/`,
> `specs/<campaña>/verify-report.md`, `docs/writeup/pipeline-itch-uram.md`,
> `docs/writeup/marcas.md`. Todo fecha y número en este documento es la
> evidencia repositorio (2026-08-20).

---

## 1. Estado consolidado

### 1.1. Fases y criterios

| Fase | Estado | Evidencia clave |
|---|---|---|
| **0 — Golden ITCH** (Python) | ✅ **CERRADA** | 22 tipos validados, evidencia de día real |
| **1 — Parser RTL** (MoldUDP64 → Anexo A) | ✅ **CERRADA (2026-08-20)** | **REP-02 line-rate**: tramo A/U real msgs 241733..241736, **9 stalls ≤ 24**, salida bit a bit; suite 32/32 |
| **2 — Order book RTL** (URAM, BBO) | ✅ **CERRADA funcional** | REPLAY-01: 17.484 BBO bit a bit; replace atómico; replay real del subset |
| **3 — Fase 3 (DW=32/URAM, feed real)** | ✅ **CERRADA funcional end-to-end** | chain01 feed real: 17.484 BBO bit a bit, cross=0, anomaly=0, gaps=0; regresión completa |
| **3 — Cierre timing 156,25 MHz** | ✅ **CERRADA** | WNS **+0,057 ns**, TNS 0, WHS +0,021 ns, URAM **32/48**, IOB **194/256**, DRC 0 (iter 16, RTL actual) |
| **3 — Cierre timing 322 MHz** | ⛔ **ABIERTA** | WNS **−3,458 ns**; ruta estructural `m_loc_idx[1] → sm_asel[0]_rep` del book (iter 16) |
| **4 — MDP3 (CME) parser** | ✅ **CERRADA funcional** | suite 14/14 (DW=32/64), gate E 14/14 mutantes, gate C verible 0 |
| **4 — MDP3 timing** | ⛔ **NO EJECUTADO** | sin proyecto Vivado MDP3 (WNS/TNS/utilización pendientes) |
| **4 — Checker XML↔RTL** | ⛔ **PENDIENTE** | validación automática del RTL contra el schema SBE |

### 1.2. Métricas de referencia (persistidas, no re-derivadas de memoria)

- Latencia wire→BBO media a **DW=32/QB=46**: **65,5 ciclos = 203,3 ns @ 322,265625 MHz**,
  determinista entre re-ejecuciones. Histograma por tipo persistido en
  `verification/vectors/latency/latency_dw32.json`. Umbral de contrato:
  **media ≤ 70 ciclos** (RTM-LAT-01, re-derivado en el addendum iter 15).
- Variante 156,25 MHz: **64b @ 156,25 MHz = 10G**; período 6,400 ns; WNS +0,057 ns.
- Variante 322 MHz: **32b @ 322,265625 MHz**; período 3,103 ns; WNS −3,458 ns (abierta).
- Tabla de órdenes: **URAM 32/48** (array `o_mem` de 65.536 slots × 130 bits = 8,52 Mbit).
- Part objetivo: **Kintex UltraScale+ xcku3p-ffva676-2L-e** (Vivado ML 2023.2 en esta máquina).

### 1.3. Enmiendas de contrato vigentes (iter 13/15) — NO renegociables sin re-campaña

1. **Push-out P=32** (`SEC-OV-01`): con la lista de niveles llena, un add con
   `delta > 0` mejor que el peor **entra al top-P** y descarta el peor; solo el
   reduce sobre un nivel descartado (o add peor que el peor) señala error. El
   BBO queda siempre bit a bit (evento 3353 del feed real era el rojo pre-fix).
2. **Depth top-N**: bit a bit **hasta la 1ª re-entrada** de un nivel descartado
   en un pico >P (loc13 llega a **420 niveles** en el día 2019-12-30; evento
   14461 es la primera re-entrada); después el depth es **subconjunto de
   precios** del golden (nunca un fantasma). BBO siempre bit a bit.
3. **Latencia RTM-LAT-01**: umbral re-derivado a **media ≤ 70 ciclos** (el ≤48
   del iter 7 era de un tramo «afortunado» declarado inexistente en el
   addendum iter 12 del repo; la medida representativa es 65,5).
4. **K=64** (ref sin truncar; OW=130 bits) y **QB=46** (piso de latencia; el
   subir a 64 rompía la media). El NOII `I` de 50 B (2+len=52 > QB=46) se
   **drena** por `ST_DRAIN` con la frontera de beat corregida (iter 15).

---

## 2. Trabajo pendiente — alcances exactos y riesgos

### 2.1. PENDIENTE-A — Criterio 10 a 322 MHz (fase 3)

**Estado**: WNS **−3,458 ns** (iter 16, RTL actual). La ruta crítica es
estructural y **no es culpa del datapath del parser/book**: el wrapper
`itch_chain_synth.sv` expone al pin los buses de **observabilidad**
(`bbo_tdata` 128→64 bits por el recorte `BBO_W`, `depth_tdata`, contadores),
y la **selección de niveles** del book (`m_loc_idx[1] → sm_asel[0]_rep`) come
el presupuesto. En la variante 64b/156,25 el mismo datapath cierra con
+0,057 ns, lo que confirma que el límite es la combinación **32b + 322 MHz +
observabilidad máxima**, no la lógica.

**Objetivo**: reducir WNS a ≥ 0 y TNS = 0 a período 3,103 ns.

**Candidatos de ingeniería (ordenar por impacto/riesgo):**
1. **Retiming del selector de niveles**: dividir la ruta `m_loc_idx →
   sm_asel` en 2 etapas (pre-compute del índice y mux en el siguiente ciclo),
   o calcular `sm_asel` por grupo de 8 slots con un mux árbol ya usar
   `first_one` (la misma técnica que se aplicó al decode `lv_cand → lv2_mode`
   en el iter 8: etapa 2a con encoders en árbol). Habilitar `phys_opt_design`
   con re-timing automático de Vivado (`set_param` de `phys_opt` retiming).
2. **Recorte adicional de observabilidad en el wrapper 322**: `depth_tdata`
   a 32 bits (ND menor en el pin) como ya se hizo con `BBO_W`; libera I/O y
   caminos de salida. Documentar como enmienda del addendum iter 11b.
3. **Pipeline de salida**: registrar `bbo_tdata/depth_tdata` un ciclo extra
   (el consumidor ya tolera latencia; impactaría el histograma — re-medir,
   re-derivar RTM-LAT-01 si hace falta, con el proceso de siempre: rojo→verde).
4. **Floorplanning / placement constraint** alrededor de `u_book` (p.ej.
   `Pblock` de las 32 URAM y el slice del selector) — última ratio, no
   debería hacer falta si el retiming del punto 1 cierra.

**Riesgos**: re-medir latencia si se toca el pipeline de salida; la util
LUT/FF y URAM no deben cambiar; la simulación debe quedar **bit a bit**
(re-regresión fase 2/3 + sim-lat). **Criterio de cierre**: `fase3_synth.tcl`
(DW=32, K=64, QB=46) devolviendo `FASE3 SYNTH/IMPL OK` + informes en
`synth/reports/` versionados.

### 2.2. PENDIENTE-B — Timing de MDP3 (fase 4)

**Estado**: el parser MDP3 (`rtl/parser/mdp3_parser.sv`, módulo propio, DW
parametrizado 32 objetivo/64 regresión) está funcional y mutado (14/14), pero
**no tiene proyecto Vivado** → WNS/TNS/utilización NO EJECUTADOS.

**Objetivo**: crear `synth/mdp3_synth.tcl` + XDC (mismo part
`xcku3p-ffva676-2L-e`; período 3,103 ns a DW=32; 6,400 ns a DW=64) sobre el
top `mdp3_parser` (puertos AXI-Stream: `s_axis_*`/`m_axis_*`, `gap_detected`,
`error`; sin wrapper de observabilidad — el módulo ya es pequeño). Gate igual
al de fase 3: fallar el batch si hay slack ≤ 0.

**Candidatos**: el parser SBE es una FSM + barrel shifter; el camino crítico
será el **alineador de campos** (shift + mux por `MessageSize/template`).
Posible split del shift en etapas si cierra justo.

**Riesgos**: ninguno sobre el repo (módulo aislado); solo horas de run.
**Criterio de cierre**: `mdp3_synth.tcl` OK + informes versionados +
```
regresión MDP3 14/14 (DW=32 y DW=64) sin cambios.

### 2.3. PENDIENTE-C — Checker XML↔RTL MDP3 (gate G / rigor)

**Estado**: `golden_model/mdp3/` tiene `schema.py`, `codec.py`, `generator.py`
(loader del schema SBE XML, decoder bit a bit y generador sintético). El
manifest del schema vive en el spec de fase 4 (`schemaId==1 && version==12`
verificado por el criterio 5). **No existe** un checker que compare la
**tabla de derivación del RTL** (longitudes de template, campos emitidos en el
Anexo M) contra el XML del schema de forma automática.

**Objetivo**: `scripts/verify/check_mdp3_schema.py` (manifiesto:
  - Lee el/los XML del schema SBE (templates con `blockLength`, `templateId`,
    campos con offset/length/encoding).
  - Extrae del RTL (`mdp3_parser.sv`) la tabla de `template_id → length` y de
    campos emitidos (w7[23]=record_type, etc.).
  - Compara: cada template declarado en el RTL existe en el XML con el
    `blockLength` correcto; no faltan templates del subset `S/R/A/F/E/C/X/D/U/P`.
  - `--rules_config_search` vibra el estilo; salida `PASS/FAIL` con diff por
    template.
  `python3 scripts/verify/check_mdp3_schema.py` como gate G.

**Riesgo**: edición del XML/uti mal ubicada. **Criterio**: PASS reproducible
y enlace al gate F/G del verify-report.

### 2.4. PENDIENTE-D — Stretch del documento maestro (NO bloquea el cierre)

- **Write-up público** (blog / GitHub Pages) con benchmarks de latencia y la
  decisión 002 (retarget Kintex xcku3p): artefacto de CV.
- **Interfaz host AXI/PCIe** para volcar BBO a software: campaña separada
  (fuera del alcance implementado hoy, `non-goal` explícito del repo).
- **Datos reales MDP3 (DataMine)**: pago; **out-of-scope**; el corpus MDP3 es
  sintético por diseño (REPLAY-03 opcional si algún día hay pcaps).
- **Port del order book a MDP3 (campaña 4b)**: diseñado (Anexo M) pero no
  implementado.

---

## 3. Orden de ejecución recomendado (lotes)

### Lote 1 — MDP3-timing + checker (independiente, no toca lo cerrado)

1. PENDIENTE-C (`check_mdp3_schema.py`): rápido, cierra gate G de fase 4.
2. PENDIENTE-B (`mdp3_synth.tcl` + XDC + run): horas de batch; evidencia en
   `synth/reports/`.

Async: en cualquier momento, PENDIENTE-A (322 MHz) en una ventana larga de
Vivado.

### Lote 2 — Cierre 322 MHz (riesgo/pendiente crítico del prior)

3. Retiming del selector de niveles (`sm_asel`) en 2 etapas / árbol
   (`first_one`), tal como el iter 8 hizo con `decode_lv2`.
4. Re-síntesis + re-regresión completa (phase3 10/10, parser 32/32, orderbook
   17/17, uram 7/7) + sim-lat re-medida.
5. Si el retiming no basta: recorte `depth_tdata` en el pin 322 y re-medir
   latencia. **NO recurrir a PIPELINE de salida sin documentar el impacto en
   RTM-LAT-01** (decisión de contrato, requiere rojo→verde explícito).

### Lote 3 — Docu y CI (cuando A y B cierren)

6. Pegar WNS/TNS/utilización de ambas campañas en sus verify-report; actualizar
   `AGENTS.md` (fase 3 criterio 10 CERRADO si aplica; fase 4 timing cerrado).
7. CI de simulación en GitHub Actions (los Makefiles ya son
   cocotb/Verilator); pcaps locales fuera (regla G0).

---

## 4. Reglas que cualquier implementación DEBE respetar

- **Rojo→verde**: no modificar spec/Gherkin para ocultar un fallo; el rojo
  primero, el verde después, con evidencia.
- **Gates A–G**: cada campaña ejecuta y pega outputs reales en su
  `verify-report.md`. Un gate sin output no está pasado.
- **Golden independiente del RTL**: jamás generar el oráculo desde el RTL
  probado.
- **Datos reales no versionados**: solo muestras sintéticas y vectores
  pequeños en `verification/vectors/`.
- **Español + Conventional Commits** en toda documentación/commits.
- **No rebajar `--Wall`**, no omitir mutantes, no convertir omisión de datos
  en PASS.
- El **QB efectivo** de fase 3 vive en `itch_chain.sv` y en el Makefile, no en
  defaults de submódulos. Cambiar un puerto/signal/param exige buscar todos
  sus consumidores.
- Cualquier cambio en latencia/backpressure exige re-medir y re-persistir el
  histograma (RTM-LAT-01).