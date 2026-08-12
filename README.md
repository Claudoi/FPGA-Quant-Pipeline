# FPGA Quant Pipeline

Pipeline de market data para trading de baja latencia sobre **AMD/Xilinx
UltraScale+**: parser Nasdaq TotalView-ITCH 5.0 a line-rate 10G + order book
en URAM con salida BBO. Proyecto por fases del documento maestro
(`Proyecto FPGA para Quant Finance — Documento maestro de opciones.md`),
orientado a perfil FPGA / low-latency trading infrastructure.

```
10G MAC → decap IP/UDP → framing MoldUDP64 → parser ITCH → order book (URAM) → BBO
```

## Estado del proyecto

| Fase | Contenido | Estado |
|---|---|---|
| **0** | Golden model Python (parser ITCH + order book + vectores de referencia + tooling de datos) | **Cerrada — PASS** (3 iteraciones del ciclo) |
| 1 | Parser RTL a line rate (64-bit @ 156,25 MHz), verificación cocotb contra el golden | Siguiente |
| 2 | Order book engine en URAM (hash por order ref, niveles, BBO) | Pendiente |
| 3 | Optimización 32-bit @ 322,265625 MHz + cierre de timing | Pendiente |
| 4 | Stretch: port CME MDP3/SBE, interfaz host, write-up | Pendiente |

### Evidencia de la fase 0 (día Nasdaq 2019-12-30, 3,5 GB reales)

- **268.744.780 mensajes** parseados y procesados por el book en **17 min**
  (objetivo de spec: ≤ 2 h). 0 anomalías de protocolo.
- **14.427.667 vectores BBO** (registros de 40 B, layout fijado en
  `specs/fase0-golden-model/spec.md` Anexo A) para un subset de 20 símbolos
  elegido por actividad medida del propio fichero (AMZN, AAPL, MSFT…).
- 29/29 tests, 5/5 mutantes HDL-par muertos, stdlib pura.
- Contrato, Gherkin, verify-report y veredictos de grade en
  `specs/fase0-golden-model/`.

## Estructura

| Directorio | Contenido |
|---|---|
| `golden_model/` | Parser ITCH (`itch/`), order book (`src/book.py`), vectores (`src/vectors.py`), stats, CLIs (`scripts/`), tests espejo (`tests/`) |
| `scripts/` | `fetch_itch.py` (descarga + md5, fail closed), `binaryfile_to_pcap.py` (BinaryFILE → pcap MoldUDP64/UDP/IP/Eth) |
| `rtl/` | (fases 1-3) `parser/`, `orderbook/`, `common/` |
| `verification/` | (fases 1+) testbenches cocotb; `vectors/` con muestras pequeñas y `subset_symbols.json` |
| `specs/` | Contratos del ciclo por campaña: `spec.md` + `gherkin/` + `verify-report.md` |
| `synth/` | (fase 3) constraints e informes Vivado |
| `docs/` | `DESARROLLO.md` (setup/gates), `decisiones/`, `writeup/` |
| `data/itch_sample/` | Datos reales — **nunca commiteados** (gitignored) |

## Uso

```bash
# tests del golden model (29 espejos del Gherkin)
python3 -m unittest discover -s golden_model/tests -t .

# descargar un día de muestra de emi.nasdaq.com (verificación md5; fail closed)
python3 scripts/fetch_itch.py 12302019.NASDAQ_ITCH50.gz

# run del golden model: stats + vectores para el subset
python3 -m golden_model.scripts.run_golden data/itch_sample/12302019.NASDAQ_ITCH50.gz \
    --subset verification/vectors/subset_symbols.json --out data/itch_sample/out --text

# BinaryFILE -> pcap MoldUDP64 para los testbenches RTL
python3 scripts/binaryfile_to_pcap.py in.ITCH50 out.pcap
```

Requisitos: Python 3.10+ stdlib pura (fase 0). Fases RTL: Verilator + cocotb
+ Vivado (ver `docs/DESARROLLO.md`).

## Ciclo de trabajo

Cada campaña sigue el loop **spec → build → verify → grade** (skills en
`.opencode/skills/`): spec escribe el contrato testeable, build implementa
con TDD estricto (rojo evidenciado), verify ejecuta los gates A-G re-mapeados
a HDL, grade juzga adversarialmente. El criterio de cierre está en
`AGENTS.md` y `docs/DESARROLLO.md`.

## Reglas

- Datos de mercado reales jamás commiteados (`data/itch_sample/**` ignorado).
- Commits en español, Conventional Commits.
- La optimización 322 MHz es capítulo final, no punto de partida.
