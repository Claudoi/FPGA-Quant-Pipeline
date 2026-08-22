# Makefile — cocotb testbench for the MDP 3.0 parser (phase 4)
#   SIM=verilator, cocotb 2.x. Usage:
#       make sim            # DW=32 suite
#       make sim-dw64       # same suite with DW=64 input
#       make sim TESTCASE=test_m3frm01   # a single DW=32 test
SIM ?= verilator
TOPLEVEL_LANG ?= verilog
TOPLEVEL = mdp3_parser
MODULE ?= test_mdp3_framing
DW ?= 32
EXTRA_ARGS += -GDW=$(DW)
SIM_BUILD = sim_build_dw$(DW)

# Parser RTL source.
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
# cocotb/Verilator export the PYTHONPATH passed to the embedded Python
# interpreter: by default it uses ONLY the cocotb environment one, so we
# propagate the set (repo root + golden_model + the area) here.
export PYTHONPATH := $(REPO_ROOT):$(REPO_ROOT)/golden_model:$(CURDIR):$(PYTHONPATH)

include $(shell cocotb-config --makefiles)/Makefile.sim
