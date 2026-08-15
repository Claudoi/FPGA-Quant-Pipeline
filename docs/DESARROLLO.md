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
- Vivado no está disponible localmente. El run de fase 3 se ejecuta desde
  `synth/` y sus informes se guardan en `synth/reports/`.
- Los datos y pcaps reales son locales e ignorados por Git. Descargar el schema
  CME antes de ejecutar su golden: `python3 scripts/fetch_mdp3_schema.py`.
- `verible-verilog-lint` sí está instalado (`.venv/bin`, ver Gate C arriba);
  usarlo siempre con `--rules_config_search` para respetar la config del repo.
  El estilo de los RTL de fases 1-3 aún reporta hallazgos de convención
  (está cerrado y no se renombran constantes verificadas); el gate C de fase 4
  cubre `mdp3_parser.sv`.
