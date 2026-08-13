# Makefile — testbench cocotb de la fase 3 (variante 32-bit @ 322 MHz)
#   SIM=verilator, cocotb 2.x. Tops parametrizados a DW=32 vía -G (EXTRA_ARGS).
#   Uso:
#     make sim                          -> orderbook (DW=32, MODULE=test_orderbook32)
#     make sim TOPLEVEL=itch_parser  MODULE=test_parser32
#     make sim TOPLEVEL=itch_chain   MODULE=test_chain32
SIM ?= verilator
TOPLEVEL_LANG ?= verilog
TOPLEVEL ?= orderbook
MODULE ?= test_orderbook32

RTL_ROOT = $(CURDIR)/../../..
RTL_ORDER = $(RTL_ROOT)/rtl/orderbook
RTL_COMMON = $(RTL_ROOT)/rtl/common
RTL_PARSER = $(RTL_ROOT)/rtl/parser

VERILOG_SOURCES = \
	$(wildcard $(RTL_ROOT)/rtl/itch_chain.sv) \
	$(wildcard $(RTL_COMMON)/*.sv) \
	$(wildcard $(RTL_ORDER)/*.sv) \
	$(wildcard $(RTL_PARSER)/*.sv)

# variante 32-bit: sobrescribe el parámetro DW del top en elaboración
EXTRA_ARGS ?= -GDW=32

COCOTB_RESULTS_FILE = $(CURDIR)/results.xml
REPO_ROOT := $(CURDIR)/../../..
export PYTHONPATH := $(REPO_ROOT):$(REPO_ROOT)/golden_model:$(CURDIR):$(REPO_ROOT)/verification/testbenches/orderbook:$(REPO_ROOT)/verification/testbenches/parser:$(PYTHONPATH)

include $(shell cocotb-config --makefiles)/Makefile.sim