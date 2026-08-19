# FPGA Quant Pipeline

Pipeline de market data para trading de baja latencia sobre **AMD/Xilinx
UltraScale+**: parser Nasdaq TotalView-ITCH 5.0 + order book con salida BBO.
El RTL implementado empieza en MoldUDP64 ya decapsulado; MAC 10G y
Ethernet/IP/UDP quedan fuera de este repositorio. Proyecto por fases del
documento maestro
(`Proyecto FPGA para Quant Finance — Documento maestro de opciones.md`),
orientado a perfil FPGA / low-latency trading infrastructure.

El repositorio empieza en el payload MoldUDP64 ya decapsulado. No implementa
MAC 10G ni Ethernet/IP/UDP.

```
MoldUDP64 → parser ITCH → order book (URAM) → BBO/top-N
```

## Estado del proyecto

| Fase | Contenido | Estado |
|---|---|---|
| **0** | Golden model Python (parser ITCH + order book + vectores y tooling) | **Cerrada**; 22 tipos y replay de día real |
| **1** | Parser RTL MoldUDP64/ITCH contra golden | **No cerrada**: framing `s_axis_tkeep` verde (91/91 `tlast`, gaps, backpressure, replay real bit a bit); pendiente REP-02 (medir `<=24` stalls en un tramo A/U real seleccionado del pcap sin índices manuales) |
| **2** | Order book RTL del subset de 20 símbolos | **Cerrada funcionalmente**; 14/14 tests y replay real |
| **3** | Variante DW=32, top-N y arquitectura URAM | **CERRADA la variante 64b/156,25 MHz (10G)**: WNS +0,015 ns, TNS 0, LUT 92,31 %, URAM 32/48 (run `fase3_156mhz.tcl`). 322 MHz sigue como capítulo de optimización abierto (mejor WNS -3,319). Evidencia de simulación verde en WSL (sim-rtm 4/4, sim-rtm64 1/1, sim-lat media 44,5 ≤ 48, gate E 30/30). REP-02 pendiente de pcap real. Detalle en `synth/reports/README.md` |
| **4** | Parser CME MDP3/SBE | **No cerrada**: framing `s_axis_tkeep` verde y **criterios 5 y 10 cerrados (2026-08-19)** en WSL (suite DW=32/DW64 12/12 PASS + 2 SKIP, gate B limpio, gate E 9/9); **criterio 7 (máscaras con huecos) abierto**; timing no acreditado (sin Vivado MDP3) |

El documento de presentación del proyecto (arquitectura, hazards, latencia,
timing y límites honestos) está en `docs/writeup/pipeline-itch-uram.md`.

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
| `rtl/` | Parseres ITCH/MDP3, `orderbook/`, cadena y módulos comunes |
| `verification/` | (fases 1+) testbenches cocotb; `vectors/` con muestras pequeñas y `subset_symbols.json` |
| `specs/` | Contratos del ciclo por campaña: `spec.md` + `gherkin/` + `verify-report.md` |
| `synth/` | (fase 3) constraints e informes Vivado |
| `docs/` | `DESARROLLO.md` (setup/gates), `decisiones/`, `writeup/` |
| `data/itch_sample/` | Datos reales — **nunca commiteados** (gitignored) |

## Uso

```bash
# regresión Python completa (ITCH + CME)
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

## Proceso y estado

Cada campaña sigue el loop **spec → rojo/verde → verify → juicio
adversarial**. Los gates A-G, el estado y el criterio de cierre están en
`AGENTS.md`; cada contrato y su evidencia viven en `specs/<campaña>/`.

## Reglas

- Datos de mercado reales jamás commiteados (`data/itch_sample/**` ignorado).
- Commits en español, Conventional Commits.
- La optimización 322 MHz es capítulo final, no punto de partida.
