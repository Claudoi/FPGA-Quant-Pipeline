# Makefile — cocotb testbench for the order book (phase 2)
#   SIM=verilator, cocotb 2.x. Usage: make sim; make sim TESTCASE=test_bbo01
SIM ?= verilator
TOPLEVEL_LANG ?= verilog
TOPLEVEL = orderbook
MODULE ?= test_orderbook

RTL_ORDER = $(CURDIR)/../../../rtl/orderbook
RTL_COMMON = $(CURDIR)/../../../rtl/common
RTL_PARSER = $(CURDIR)/../../../rtl/parser

# The order book sources are assembled here (top => leaves); the parser is
# included only if this testbench chains it (e.g. replay). In phase 2 the
# book consumes Anexo A directly; if chained replay is added, the parser is
# appended to this list.
VERILOG_SOURCES = \
	$(wildcard $(RTL_COMMON)/*.sv) \
	$(wildcard $(RTL_ORDER)/*.sv) \
	$(wildcard $(RTL_PARSER)/*.sv)

COCOTB_RESULTS_FILE = $(CURDIR)/results.xml
REPO_ROOT := $(CURDIR)/../../..
export PYTHONPATH := $(REPO_ROOT):$(REPO_ROOT)/golden_model:$(CURDIR):$(PYTHONPATH)

include $(shell cocotb-config --makefiles)/Makefile.sim