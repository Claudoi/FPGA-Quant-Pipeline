# DESARROLLO.md — setup y gates del proyecto FPGA

> Guía operativa de desarrollo. Complementa a `AGENTS.md`; las skills
> `spec`/`build`/`verify`/`grade` referencian los comandos de aquí.

## Stack objetivo

| Capa | Herramienta |
|---|---|
| RTL | SystemVerilog (Verilog compatible Verilator) |
| Verificación | cocotb + Verilator (recomendado); Questa/Vivado xsim si la simulación lo exige |
| Estilo / lint HDL | `verible-verilog-lint` (estilo) + `verilator --lint-only --Wall` (sintaxis/diseño) |
| Golden model | Python (numpy) — `golden_model/` |
| Datos | Feeds ITCH de `emi.nasdaq.com` → vectores en `verification/vectors/` (NUNCA commitear crudos) |
| Síntesis | Vivado apuntando a part UltraScale+ objetivo (constraints en `synth/constraints/`) |

## Setup

```bash
# entorno python (cocotb, numpy)
# IMPORTANTE: cocotb 2.0.1 NO soporta Python >= 3.14. Usa Python 3.11/3.12.
#   En Homebrew con python@3.11:  /opt/homebrew/opt/python@3.11/bin/python3.11
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt   # cocotb, cocotb-bus, numpy, verilator scripts

# verificación de instalación
verilator --version
python -c "import cocotb, numpy; print('cocotb', cocotb.__version__)"
```

## Comandos (los que usan las skills verify/grade)

> Rellena los flags exactos según la convención del área. Los umbrales de
> cobertura viven en `scripts/verify/thresholds.json` (si la campaña lo define).

| Gate | Comando de referencia |
|---|---|
| A. Simulación | `make -C verification/<area> sim` (o `cocotb-config` + verilator makefile) |
| A. Simulación (fase 0, Python) | `python3 -m unittest discover -s golden_model/tests -t .` |
| B. Compilación/lint | `verilator --lint-only -Wall -Wno-<trinquete> --top-module <módulo> rtl/<area>/<file>.sv` |
| C. Estilo | `verible-verilog-lint rtl/<area>/<file>.sv` |
| D. Cobertura funcional | informe de cobertura Verilator/Questa + tabla spec↔test (gate D nivel 1) |
| E. Mutación HDL | runner de mutación sobre `rtl/<área>` (flip de guard/comparador → test debe matarlo) |
| F. Completitud | `specs/gherkin-espejos.json` consistente + títulos espejo literales |
| G. Timing/recursos | Vivado: `synth/` project, informe WNS/TNS y utilización LUT/FF/BRAM/URAM |

## Gotchas

- **opencode**, no Claude Code: las skills viven en `.opencode/skills/`; tras
  editarlas, **reinicia opencode** para recargarlas (no se hot-recargan).
- Los feeds reales de mercado jamás se commitean; los testbenches leen vectores
  de `verification/vectors/` (regla G0 de `verify`).
- La optimización 32-bit @ 322 MHz (fase 3) es capítulo final, no punto de
  partida (decisión del documento maestro).
- Verilator es estricto con `--Wall`; el trinquete de warnings del proyecto se
  documenta por área, nunca se silencia un warning real para pasar un gate.
- **Los parámetros de fase 3 se sobrescriben desde el top**: `itch_chain.sv`
  declara su propio `QB` (y otros) y los pasa a los módulos con `.QB(QB)` —
  cambiar un default de módulo NO afecta a la cadena (hallazgo 2026-08-14:
  "QB 64" en `itch_parser.sv` no movió la latencia; el binario elaboró 128).
  El parámetro efectivo vive en el top y en la línea `-G` del Makefile. Antes
  de medir un cambio de parámetro, confirmar QUÉ módulo elabora el valor
  (traza de señales internas con cocotb o inspección de constantes del C++
  generado por Verilator).
- `verible-verilog-lint` (gate C) no está instalado en el entorno; instalable
  en la próxima sesión para cerrar el único gate pendiente del ciclo.

## Verificación

Cada campaña cierra con los gates de `verify` (evidencia pegada en
`specs/<campaña>/verify-report.md`) y el veredicto adversarial de `grade`. Sin
verify-report, `grade` da FAIL directo.
