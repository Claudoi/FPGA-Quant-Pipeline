# Makefile — testbench cocotb del parser MDP 3.0 (fase 4)
#   SIM=verilator, cocotb 2.x. Uso:
#       make sim            # suite DW=32
#       make sim-dw64       # misma suite con entrada DW=64
#       make sim TESTCASE=test_m3frm01   # un solo test DW=32
SIM ?= verilator
TOPLEVEL_LANG ?= verilog
TOPLEVEL = mdp3_parser
MODULE ?= test_mdp3_framing
DW ?= 32
EXTRA_ARGS += -GDW=$(DW)
SIM_BUILD = sim_build_dw$(DW)

# Fuente RTL del parser.
RTL_PARSER = $(CURDIR)/../../../rtl/parser

VERILOG_SOURCES = \
	$(RTL_PARSER)/mdp3_parser.sv

.PHONY: sim-dw64 clean-all

sim-dw64:
	$(MAKE) sim DW=64

clean-all:
	rm -rf sim_build_dw32 sim_build_dw64

COCOTB_RESULTS_FILE = $(CURDIR)/results.xml

REPO_ROOT := $(CURDIR)/../../..
# cocotb/Verilator exportan el PYTHONPATH que se pasa al intérprete Python
# embebido: por defecto usa SOLO el del entorno cocotb, así que propagamos el
# conjunto (raíz repo + golden_model + el área) aquí.
export PYTHONPATH := $(REPO_ROOT):$(REPO_ROOT)/golden_model:$(CURDIR):$(PYTHONPATH)

include $(shell cocotb-config --makefiles)/Makefile.sim
