# Makefile — testbench cocotb del order book (fase 2)
#   SIM=verilator, cocotb 2.x. Uso: make sim; make sim TESTCASE=test_bbo01
SIM ?= verilator
TOPLEVEL_LANG ?= verilog
TOPLEVEL = orderbook
MODULE ?= test_orderbook

RTL_ORDER = $(CURDIR)/../../../rtl/orderbook
RTL_COMMON = $(CURDIR)/../../../rtl/common
RTL_PARSER = $(CURDIR)/../../../rtl/parser

# Acá se ensamblan las fuentes del order book (top => hojas); el parser se
# incluye solo si este testbench lo encadena (p. ej. replay). En fase 2 el
# book consume Anexo A directamente; si se añade replay encadenado se agrega
# el parser a esta lista.
VERILOG_SOURCES = \
	$(wildcard $(RTL_COMMON)/*.sv) \
	$(wildcard $(RTL_ORDER)/*.sv) \
	$(wildcard $(RTL_PARSER)/*.sv)

COCOTB_RESULTS_FILE = $(CURDIR)/results.xml
REPO_ROOT := $(CURDIR)/../../..
export PYTHONPATH := $(REPO_ROOT):$(REPO_ROOT)/golden_model:$(CURDIR):$(PYTHONPATH)

include $(shell cocotb-config --makefiles)/Makefile.sim