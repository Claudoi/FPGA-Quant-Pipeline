# DESARROLLO.md — instalación y troubleshooting

Las reglas de trabajo, gates y comandos de verificación viven en `AGENTS.md`.
Este documento solo cubre cómo preparar y diagnosticar el entorno local.

## Stack

| Capa | Herramienta |
|---|---|
| RTL | SystemVerilog compatible con Verilator |
| Simulación | cocotb + Verilator; Questa/Vivado xsim si hace falta |
| Estilo HDL | `verible-verilog-lint` |
| Golden | Python 3.11+ |
| Síntesis | Vivado para UltraScale+ |

## Setup

```bash
# cocotb 2.0.1 no soporta Python >= 3.14.
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

verilator --version
cocotb-config --version
python -c "import cocotb, numpy; print('cocotb', cocotb.__version__)"
```

## Comandos de referencia

| Gate | Comando de referencia |
|---|---|
| A. Simulación | `make -C verification/<area> sim` (o `cocotb-config` + verilator makefile) |
| A. Simulación (fase 0, Python) | `python3 -m unittest discover -s golden_model/tests -t .` |
| B. Compilación/lint | `verilator --lint-only -Wall --top-module <módulo> rtl/<area>/<file>.sv` |
| C. Estilo | `verible-verilog-lint --rules_config_search rtl/<area>/<file>.sv` |
| D. Cobertura funcional | informe de cobertura Verilator/Questa + tabla spec↔test (gate D nivel 1) |
| E. Mutación HDL | runner de mutación sobre `rtl/<área>` (flip de guard/comparador → test debe matarlo) |
| F. Completitud | `specs/gherkin-espejos.json` consistente + títulos espejo literales |
| G. Timing/recursos | Vivado: `synth/` project, informe WNS/TNS y utilización LUT/FF/BRAM/URAM |

### Gate C — verible

`verible-verilog-lint` (y `verible-verilog-format`) está instalado en
`.venv/bin` desde el release oficial de Verible
(`chipsalliance/verible/releases`, tarball `*-macOS.tar.gz`). No hay fórmula
brew ni paquete pip; se copian los binarios:

```bash
# descargar verible-vX-macOS.tar.gz del release de ChipsAlliance/verible,
# extraer, y copiar los binarios al venv del proyecto:
cp verible-*/bin/verible-verilog-lint verible-*/bin/verible-verilog-format .venv/bin/

# lanzar el lint (usa la config del repo, raíz):
verible-verilog-lint --rules_config_search rtl/parser/mdp3_parser.sv
```

El repo lleva la config en `./.rules.verible_lint` (formato plano de
`--print_rules_file`): alinea la regla `parameter-name-style` con la
convención SCREAMING_SNAKE del proyecto (no renombrar constantes de RTL
verificado) y deja activas las reglas de consistencia genuinas.

## Problemas conocidos

- Si `cocotb-config` no existe, el entorno Python no está activado o no se
  instaló `requirements-dev.txt`; los Makefiles RTL no pueden arrancar.
- **Vivado ML 2023.2 SÍ está disponible en el PC de trabajo (Windows,
  `C:\Xilinx\Vivado\2023.2`)** desde el run 2026-08-18: `vivado -mode batch
  -source synth/fase3_synth.tcl` y los informes se guardan en
  `synth/reports/`. No está en el PATH: invocar
  `C:\Xilinx\Vivado\2023.2\bin\vivado.bat` (o `xvlog.bat` para un parse
  rápido del RTL sin Verilator: `xvlog --sv --nolog <file>.sv`; en aislamiento
  reporta un falso positivo preexistente de `nx_done` usado antes de su
  declaración — legal en SV, no bloquea el parse). En la máquina de
  desarrollo (macOS) Vivado NO está instalado; allí solo corren los gates de
  simulación (A/E/B/C).
- Los datos y pcaps reales son locales e ignorados por Git; los testbenches
  leen vectores de `verification/vectors/` o artefactos locales ignorados. Un
  replay omitido por pcap ausente no cuenta como PASS de datos reales.
- `scripts/verify/synth_check.py` comprueba coherencia estática entre
  RTL/Tcl/XDC; no sustituye una ejecución Vivado. Sin `vivado`, WNS, TNS y
  utilización permanecen NO EJECUTADOS y fase 3 no está timing-closed.
- **Los parámetros de fase 3 se sobrescriben desde el top**: `itch_chain.sv`
  declara su propio `QB` (y otros) y los pasa a los módulos con `.QB(QB)` —
  cambiar un default de módulo NO afecta a la cadena (hallazgo 2026-08-14:
  "QB 64" en `itch_parser.sv` no movió la latencia; el binario elaboró 128).
  El parámetro efectivo vive en el top y en la línea `-G` del Makefile. Antes
  de medir un cambio de parámetro, confirmar QUÉ módulo elabora el valor
  (traza de señales internas con cocotb o inspección de constantes del C++
  generado por Verilator).
- `verible-verilog-lint` sí está instalado (`.venv/bin`, ver Gate C arriba);
  usarlo siempre con `--rules_config_search` para respetar la config del repo.
  El estilo de los RTL de fases 1-3 aún reporta hallazgos de convención
  (está cerrado y no se renombran constantes verificadas); el gate C de fase 4
  cubre `mdp3_parser.sv`.
- Cada campaña conserva outputs reales y gates no ejecutados en
  `specs/<campaña>/verify-report.md`. Un gate sin output no está pasado.