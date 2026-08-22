# Makefile — cocotb testbench for the ITCH parser (phase 1)
#   SIM=verilator, cocotb 2.x. Usage:
#       make sim            # run the area's test suite
#       make sim TESTCASE=test_par01   # a single test
SIM ?= verilator
TOPLEVEL_LANG ?= verilog
TOPLEVEL = itch_parser
MODULE ?= test_itch_parser

# Parser RTL sources (common + parser). Assembled here in order of the
# hierarchy top => leaves.
RTL_PARSER = $(CURDIR)/../../../rtl/parser
RTL_COMMON = $(CURDIR)/../../../rtl/common

VERILOG_SOURCES = \
	$(wildcard $(RTL_COMMON)/*.sv) \
	$(wildcard $(RTL_PARSER)/*.sv)

COCOTB_RESULTS_FILE = $(CURDIR)/results.xml

REPO_ROOT := $(CURDIR)/../../..
# cocotb/Verilator export the PYTHONPATH passed to the embedded Python
# interpreter: by default it uses ONLY the cocotb environment one, so we
# propagate the set (repo root + golden_model + the area) here.
export PYTHONPATH := $(REPO_ROOT):$(REPO_ROOT)/golden_model:$(CURDIR):$(PYTHONPATH)

include $(shell cocotb-config --makefiles)/Makefile.sim