# Makefile — testbench cocotb del parser MDP 3.0 (fase 4)
#   SIM=verilator, cocotb 2.x. Uso:
#       make sim            # correr la suite del área (DW=32)
#       make sim-dw64       # regresión DW=64 (criterio 8, M3-REG-01)
#       make sim TESTCASE=test_m3frm01   # un solo test
SIM ?= verilator
TOPLEVEL_LANG ?= verilog
TOPLEVEL = mdp3_parser
# MODULE por defecto: framing + robustez se corren por separado (el cocotb
# pegado no soporta MODULE con espacios). Uso: make sim, y make sim
# MODULE=test_mdp3_robustez para la suite de criterios 4-7.
MODULE ?= test_mdp3_framing
# DW de elaboración del top (32 en regresión normal, 64 en sim-dw64).
DW ?= 32

# Fuentes RTL del parser (común + parser). Se ensamblan aquí en orden de
# la jerarquía top => hojas.
RTL_PARSER = $(CURDIR)/../../../rtl/parser
RTL_COMMON = $(CURDIR)/../../../rtl/common

VERILOG_SOURCES = \
	$(wildcard $(RTL_COMMON)/*.sv) \
	$(wildcard $(RTL_PARSER)/*.sv)

COCOTB_RESULTS_FILE = $(CURDIR)/results.xml

REPO_ROOT := $(CURDIR)/../../..
# cocotb/Verilator exportan el PYTHONPATH que se pasa al intérprete Python
# embebido: por defecto usa SOLO el del entorno cocotb, así que propagamos el
# conjunto (raíz repo + golden_model + el área) aquí.
export PYTHONPATH := $(REPO_ROOT):$(REPO_ROOT)/golden_model:$(CURDIR):$(PYTHONPATH)

EXTRA_ARGS = -GDW=$(DW)

sim-dw64:
	$(MAKE) sim DW=64

include $(shell cocotb-config --makefiles)/Makefile.sim