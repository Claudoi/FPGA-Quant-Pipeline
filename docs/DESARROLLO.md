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

## Problemas conocidos

- Si `cocotb-config` no existe, el entorno Python no está activado o no se
  instaló `requirements-dev.txt`; los Makefiles RTL no pueden arrancar.
- `verible-verilog-lint` no está instalado en este entorno. Su ausencia se
  declara como gate C no ejecutado; no se transforma en PASS.
- Vivado no está disponible localmente. El run de fase 3 se ejecuta desde
  `synth/` y sus informes se guardan en `synth/reports/`.
- Los datos y pcaps reales son locales e ignorados por Git. Descargar el schema
  CME antes de ejecutar su golden: `python3 scripts/fetch_mdp3_schema.py`.
