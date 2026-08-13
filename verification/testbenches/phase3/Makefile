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

# iteración 2: tabla hashada. K=20 da más de PROBE refs por hash en 2^K
# (con K=19 la 9ª ref del mismo hash se trunca a una existente y el probe
# agotado es inalcanzable — ver test_hash32.py).
sim-hash:
	$(MAKE) sim TOPLEVEL=orderbook MODULE=test_hash32 EXTRA_ARGS="-GDW=32 -GK=20"

# iteración 3: top-N público (depth_tdata de 640 bits vs niveles del golden)
sim-depth:
	$(MAKE) sim TOPLEVEL=orderbook MODULE=test_depth32 EXTRA_ARGS="-GDW=32"

COCOTB_RESULTS_FILE = $(CURDIR)/results.xml
REPO_ROOT := $(CURDIR)/../../..
export PYTHONPATH := $(REPO_ROOT):$(REPO_ROOT)/golden_model:$(CURDIR):$(REPO_ROOT)/verification/testbenches/orderbook:$(REPO_ROOT)/verification/testbenches/parser:$(PYTHONPATH)

include $(shell cocotb-config --makefiles)/Makefile.sim