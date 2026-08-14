# Makefile — testbench cocotb de la campaña fase3-uram (Anexo A recortado,
# URAM + sonda serializada + pipeline de niveles).
#   SIM=verilator, cocotb 2.x. Top itch_parser/orderbook a DW=32 vía -G.
#   Uso:
#     make sim-anx                        -> itch_parser DW=32 (ANX-01/02)
#     (los targets de la campaña se añaden iteración a iteración)
SIM ?= verilator
TOPLEVEL_LANG ?= verilog
TOPLEVEL ?= itch_parser
MODULE ?= test_anx32

RTL_ROOT = $(CURDIR)/../../..
RTL_ORDER = $(RTL_ROOT)/rtl/orderbook
RTL_COMMON = $(RTL_ROOT)/rtl/common
RTL_PARSER = $(RTL_ROOT)/rtl/parser

VERILOG_SOURCES = \
	$(wildcard $(RTL_ROOT)/rtl/itch_chain.sv) \
	$(wildcard $(RTL_COMMON)/*.sv) \
	$(wildcard $(RTL_ORDER)/*.sv) \
	$(wildcard $(RTL_PARSER)/*.sv)

EXTRA_ARGS ?= -GDW=32

sim-anx:
	$(MAKE) sim TOPLEVEL=itch_parser MODULE=test_anx32 EXTRA_ARGS="-GDW=32" SIM_BUILD=sim_build_anx

clean-all:
	rm -rf sim_build sim_build_anx

COCOTB_RESULTS_FILE = $(CURDIR)/results.xml
REPO_ROOT := $(CURDIR)/../../..
export PYTHONPATH := $(REPO_ROOT):$(REPO_ROOT)/golden_model:$(CURDIR):$(REPO_ROOT)/verification/testbenches/orderbook:$(REPO_ROOT)/verification/testbenches/parser:$(REPO_ROOT)/verification/testbenches/phase3:$(PYTHONPATH)

include $(shell cocotb-config --makefiles)/Makefile.sim
