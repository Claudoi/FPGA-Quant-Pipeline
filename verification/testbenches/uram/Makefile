# Makefile — cocotb testbench for the fase3-uram campaign (trimmed Anexo A,
# URAM + serialized probe + level pipeline).
#   SIM=verilator, cocotb 2.x. Top itch_parser/orderbook at DW=32 via -G.
#   Usage:
#     make sim-anx                        -> itch_parser DW=32 (ANX-01/02)
#     make sim-uram                       -> orderbook DW=32 K=20 (SEC-URAM-01/02)
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

# criteria 2-3: serialized probe + prefetch. K=20 to make the exhausted probe
# real (9th ref of the same hash) — same regime as phase3's sim-hash.
sim-uram:
	$(MAKE) sim TOPLEVEL=orderbook MODULE=test_uram32 EXTRA_ARGS="-GDW=32 -GK=20" SIM_BUILD=sim_build_uram

clean-all:
	rm -rf sim_build sim_build_anx sim_build_uram

COCOTB_RESULTS_FILE = $(CURDIR)/results.xml
REPO_ROOT := $(CURDIR)/../../..
export PYTHONPATH := $(REPO_ROOT):$(REPO_ROOT)/golden_model:$(CURDIR):$(REPO_ROOT)/verification/testbenches/orderbook:$(REPO_ROOT)/verification/testbenches/parser:$(REPO_ROOT)/verification/testbenches/phase3:$(PYTHONPATH)

include $(shell cocotb-config --makefiles)/Makefile.sim
