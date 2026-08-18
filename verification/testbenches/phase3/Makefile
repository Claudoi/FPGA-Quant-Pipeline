# Makefile — testbench cocotb de la fase 3 (variante 32-bit @ 322 MHz)
#   SIM=verilator, cocotb 2.x. Tops parametrizados a DW=32 vía -G (EXTRA_ARGS).
#   SIM_BUILD dedicado por combinación (top, generics): el cache de Verilator
#   NO rastrea cambios de -G ni de top — un build compartido reutilizaría el
#   binario de la combinación anterior en silencio (gotcha real: `sim-hash`
#   tras `sim` corría con K=19 y SEC-HASH-01 fallaba con refs truncadas).
#   Uso:
#     make sim                          -> orderbook (DW=32, MODULE=test_orderbook32)
#     make sim-hash                     -> orderbook DW=32 K=20 (probing real)
#     make sim-depth                    -> orderbook top-N ND=5
#     make sim-hard                     -> orderbook hardening (NSYM/backpressure)
#     make sim-lat                      -> cadena itch_chain (latencia)
#     make sim-parser                   -> itch_parser DW=32
#     make sim-chain                    -> cadena itch_chain DW=32 (end-to-end)
#     make sim-chain-nd3                -> cadena itch_chain DW=32 ND=3
#     make sim-rtm                      -> orderbook pipeline de emisión DW=32 (RTM-01..04)
#     make sim-rtm64                    -> orderbook pipeline de emisión DW=64 (RTM-REG-01)
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

# sim / sim-depth / sim-hard comparten (orderbook, DW=32, K=19): el binario es
# el mismo, solo cambia el módulo Python — SIM_BUILD por defecto es correcto.
# Las combinaciones con otros generics o tops tienen SIM_BUILD propio.

# iteración 2: tabla hashada. K=20 da más de PROBE refs por hash en 2^K
# (con K=19 la 9ª ref del mismo hash se trunca a una existente y el probe
# agotado es inalcanzable — ver test_hash32.py).
sim-hash:
	$(MAKE) sim TOPLEVEL=orderbook MODULE=test_hash32 EXTRA_ARGS="-GDW=32 -GK=20" SIM_BUILD=sim_build_hash

# iteración 3: top-N público (depth_tdata de 640 bits vs niveles del golden)
sim-depth:
	$(MAKE) sim TOPLEVEL=orderbook MODULE=test_depth32 EXTRA_ARGS="-GDW=32"

# iteración 4: hardening — símbolo 21 (SEC-NSYM-01) y retención del par
# BBO/depth bajo backpressure (SEC-BP-01)
sim-hard:
	$(MAKE) sim TOPLEVEL=orderbook MODULE=test_hard32 EXTRA_ARGS="-GDW=32"

# iteración 4: latencia wire->BBO por tipo en la cadena (SEC-LAT-01)
sim-lat:
	$(MAKE) sim TOPLEVEL=itch_chain MODULE=test_lat32 EXTRA_ARGS="-GDW=32" SIM_BUILD=sim_build_chain

# variantes de top del área (mismos generics DW=32 que el default)
sim-parser:
	$(MAKE) sim TOPLEVEL=itch_parser MODULE=test_parser32 EXTRA_ARGS="-GDW=32" SIM_BUILD=sim_build_parser

sim-chain:
	$(MAKE) sim TOPLEVEL=itch_chain MODULE=test_chain32 EXTRA_ARGS="-GDW=32" SIM_BUILD=sim_build_chain

sim-chain-nd3:
	$(MAKE) sim TOPLEVEL=itch_chain MODULE=test_chain32 EXTRA_ARGS="-GDW=32 -GND=3" SIM_BUILD=sim_build_chain_nd3

# iteración 7: retiming del escaneo de niveles (ST_EMIT -> etapas A/B/C,
# addendum spec). sim-rtm ejercita la sonda estructural (DW=32) y sim-rtm64 la
# regresión de la parametrización (DW=64): el binario difiere por -G, así que
# cada combinación lleva su SIM_BUILD.
sim-rtm:
	$(MAKE) sim TOPLEVEL=orderbook MODULE=test_rtm32 EXTRA_ARGS="-GDW=32" SIM_BUILD=sim_build_rtm

sim-rtm64:
	$(MAKE) sim TOPLEVEL=orderbook MODULE=test_rtm32 EXTRA_ARGS="-GDW=64" SIM_BUILD=sim_build_rtm64

# limpia todos los builds del área (el clean de cocotb solo borra SIM_BUILD)
clean-all:
	rm -rf sim_build sim_build_hash sim_build_parser sim_build_chain sim_build_chain_nd3 sim_build_rtm sim_build_rtm64

COCOTB_RESULTS_FILE = $(CURDIR)/results.xml
REPO_ROOT := $(CURDIR)/../../..
export PYTHONPATH := $(REPO_ROOT):$(REPO_ROOT)/golden_model:$(CURDIR):$(REPO_ROOT)/verification/testbenches/orderbook:$(REPO_ROOT)/verification/testbenches/parser:$(PYTHONPATH)

include $(shell cocotb-config --makefiles)/Makefile.sim
