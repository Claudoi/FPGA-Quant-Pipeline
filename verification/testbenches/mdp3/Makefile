# Makefile — testbench cocotb del parser MDP 3.0 (fase 4)
#   SIM=verilator, cocotb 2.x. Uso:
#       make sim            # correr la suite del área
#       make sim TESTCASE=test_m3frm01   # un solo test
SIM ?= verilator
TOPLEVEL_LANG ?= verilog
TOPLEVEL = mdp3_parser
MODULE ?= test_mdp3_framing

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

include $(shell cocotb-config --makefiles)/Makefile.sim