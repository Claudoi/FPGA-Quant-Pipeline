# Agent Notes — FPGA Quant Pipeline

> Proyecto para diferenciar candidatura en low-latency trading infrastructure
> (perfil FPGA). Pipeline de market data: parser Nasdaq TotalView-ITCH 5.0 a
> line-rate 10G + order book en URAM sobre AMD/Xilinx UltraScale+. Documento
> maestro con el alcance, las fases y los riesgos:
> `Proyecto FPGA para Quant Finance — Documento maestro de opciones.md`.
> Aquí corre el **ciclo de Atenea** (spec → build → verify → grade) pero
> re-mapeado de la app clínica a flujo HDL, y ejecutado con **opencode** (no
> Claude Code).

## Contexto del proyecto (en una frase)

`10G MAC → decap IP/UDP → framing MoldUDP64 → parser ITCH → order book engine (URAM) → BBO`.
El proyecto ganador es el **pipeline completo por fases**, no un parser suelto.

## Estado actual (actualizado 2026-08-13)

**Fase 0 (golden model) CERRADA con PASS** — ciclo completo en 3 iteraciones
(spec → build → verify → grade), contrato en `specs/fase0-golden-model/`.

- Golden model Python stdlib: parser ITCH 5.0 (22 tipos validados), order
  book multi-símbolo, vectores BBO de 40 B (Anexo A de la spec), stats,
  `fetch_itch.py`, `binaryfile_to_pcap.py`. 29/29 tests, 5/5 mutantes.
- Evidencia día real 2019-12-30 (en `data/itch_sample/`, no commiteado):
  268.744.780 mensajes en 17 min, 0 anomalías, 14,4M vectores sobre el
  subset de 20 símbolos (`verification/vectors/subset_symbols.json`).

**Fase 1 (parser RTL) CERRADA** — contrato en `specs/fase1-parser-rtl/`.
19/19 tests, 10/10 mutantes; criterio 7 (frame truncado) cerrado en iteración 3.

**Fase 2 (order book RTL) — iteración 3 CERRADA, lista para /grade.** Contrato
en `specs/fase2-orderbook/`. 14/14 tests, 8/8 mutantes. Cerrados: mapeo
locate→índice (iter 2) y REPLAY-01 con el feed real (iter 3): 31.400 mensajes
de 20 símbolos → **30.729 eventos BBO bit a bit vs golden** (anomaly 671,
cross 0). Hallazgos de la iteración 3: BUG-U del replace (U en 2 ciclos),
truncado de order_ref (K=19), overflow de niveles (P=32), trading state por
símbolo de 8 bits. Pendiente de fase 2: veredicto de `/grade`.
- **Siguiente paso: `/grade` de fase 2 → fase 3 (optimización 322 MHz / URAM).**

## Ciclo de trabajo (loop verificado, portado a FPGA + opencode)

- `/spec` → `/build` → `/verify` → `/grade`. Son **skills de opencode** en
  `.opencode/skills/{spec,build,verify,grade}/SKILL.md`; se invocan por su
  nombre o con `/skill`.
- El owner **no lee el código**: lee el contrato (`specs/<campaña>/spec.md`),
  el informe (`verify-report.md`) y el veredicto de grade.
- Los gates A-G del ciclo están re-mapeados del mundo JS/Node al flujo HDL:
  ver `verify` para el régimen. En resumen: cocotb/Verilator, lint/estilo HDL,
  cobertura funcional, mutación HDL, completitud del parser, timing+recursos.

## Layout del subproyecto

| Directorio | Contenido |
|---|---|
| `golden_model/` | Modelo dorado en Python (ITCH parser + order book) y vectores de referencia (fase 0). |
| `rtl/` | Fuente HDL: `parser/`, `orderbook/`, `common/` (fases 1-3). |
| `verification/` | Testbenches cocotb (`testbenches/`), vectores (`vectors/`), scripts de replay. |
| `scripts/` | Tooling de datos (`binaryfile_to_pcap.py`, fetch de `emi.nasdaq.com`, etc.). |
| `data/itch_sample/` | Datos de muestra ITCH (nunca se commitean feeds crudos; `.gitignore`). |
| `synth/` | Proyecto Vivado: constraints (`constraints/`), informes de timing/utilización (`reports/`). |
| `specs/<campaña>/` | Contratos del ciclo: `spec.md` + `gherkin/*.feature` + `verify-report.md`. |
| `docs/` | `DESARROLLO.md` (setup/gates/gotchas), `decisiones/`, `writeup/`. |

## Reglas globales

- **Idioma:** español en docs y mensajes de commit; Conventional Commits.
- **Hardware:** datos de mercado reales jamás commiteados (solo pequeñas
  muestras sintéticas o vectores en `verification/vectors/`).
- Cada fase del maestro se trabaja como una **campaña** con su spec en
  `specs/<campaña>/`. El master doc fija el orden: golden model (0) → parser
  (1) → order book (2) → optimización 322 MHz (3) → stretch CME MDP3 (4).
- **No comprar placa:** simulaciones con datos reales + timing closure en
  Vivado apuntando a un part US+ ya es un proyecto demostrable (decisión del
  documento maestro).

## Gotchas de este entorno

- **opencode** (no Claude Code): las skills viven en `.opencode/skills/` y se
  invocan por nombre. Tras editar una skill, **reiniciar opencode** para que la
  recargue (no se hot-recargan).
- Verilator + cocotb es el camio de verificación por defecto; Vivado/Questa si
  la simulación lo exige. Consulta `docs/DESARROLLO.md` para comandos exactos.

## Verificación

Cada campaña cierra con los gates de `verify` (evidencia pegada en
`specs/<campaña>/verify-report.md`) y el veredicto adversarial de `grade`.
Sin verify-report, `grade` da FAIL directo. Consulta `docs/SEGURIDAD-Y-RIGOR.md`
si se añade.
