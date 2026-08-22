# Makefile — cocotb testbench for phase 3 (32-bit variant @ 322 MHz)
#   SIM=verilator, cocotb 2.x. Tops parameterized to DW=32 via -G (EXTRA_ARGS).
#   Dedicated SIM_BUILD per (top, generics) combination: the Verilator cache
#   does NOT track -G or top changes — a shared build would silently reuse the
#   previous combination's binary (real gotcha: `sim-hash` after `sim` ran
#   with K=19 and SEC-HASH-01 failed with truncated refs).
#   Usage:
#     make sim                          -> orderbook (DW=32, MODULE=test_orderbook32)
#     make sim-hash                     -> orderbook DW=32 K=20 (real probing)
#     make sim-depth                    -> orderbook top-N ND=5
#     make sim-hard                     -> orderbook hardening (NSYM/backpressure)
#     make sim-lat                      -> itch_chain pipeline (latency)
#     make sim-parser                   -> itch_parser DW=32
#     make sim-chain                    -> itch_chain pipeline DW=32 (end-to-end)
#     make sim-chain-nd3                -> itch_chain pipeline DW=32 ND=3
#     make sim-rtm                      -> orderbook emission pipeline DW=32 (RTM-01..04)
#     make sim-rtm64                    -> orderbook emission pipeline DW=64 (RTM-REG-01)
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

# 32-bit variant: overrides the top's DW parameter at elaboration
EXTRA_ARGS ?= -GDW=32

# sim / sim-depth / sim-hard share (orderbook, DW=32, K=19): the binary is
# the same, only the Python module changes — the default SIM_BUILD is correct.
# Combinations with other generics or tops get their own SIM_BUILD.

# iteration 2: hashed table. K=20 yields more than PROBE refs per hash in 2^K
# (with K=19 the 9th ref of the same hash truncates to an existing one and the
# exhausted probe is unreachable — see test_hash32.py).
sim-hash:
	$(MAKE) sim TOPLEVEL=orderbook MODULE=test_hash32 EXTRA_ARGS="-GDW=32 -GK=20" SIM_BUILD=sim_build_hash

# iteration 3: public top-N (640-bit depth_tdata vs golden levels)
sim-depth:
	$(MAKE) sim TOPLEVEL=orderbook MODULE=test_depth32 EXTRA_ARGS="-GDW=32"

# iteration 4: hardening — symbol 21 (SEC-NSYM-01) and retention of the
# BBO/depth pair under backpressure (SEC-BP-01)
sim-hard:
	$(MAKE) sim TOPLEVEL=orderbook MODULE=test_hard32 EXTRA_ARGS="-GDW=32"

# iteration 4: wire->BBO latency by type in the chain (SEC-LAT-01)
sim-lat:
	$(MAKE) sim TOPLEVEL=itch_chain MODULE=test_lat32 EXTRA_ARGS="-GDW=32" SIM_BUILD=sim_build_chain

# area top variants (same DW=32 generics as the default)
sim-parser:
	$(MAKE) sim TOPLEVEL=itch_parser MODULE=test_parser32 EXTRA_ARGS="-GDW=32" SIM_BUILD=sim_build_parser

sim-chain:
	$(MAKE) sim TOPLEVEL=itch_chain MODULE=test_chain32 EXTRA_ARGS="-GDW=32" SIM_BUILD=sim_build_chain

sim-chain-nd3:
	$(MAKE) sim TOPLEVEL=itch_chain MODULE=test_chain32 EXTRA_ARGS="-GDW=32 -GND=3" SIM_BUILD=sim_build_chain_nd3

# iteration 7: level-scan retiming (ST_EMIT -> stages A/B/C,
# spec addendum). sim-rtm exercises the structural probe (DW=32) and sim-rtm64
# the parameterization regression (DW=64): the binary differs by -G, so each
# combination gets its own SIM_BUILD.
sim-rtm:
	$(MAKE) sim TOPLEVEL=orderbook MODULE=test_rtm32 EXTRA_ARGS="-GDW=32" SIM_BUILD=sim_build_rtm

sim-rtm64:
	$(MAKE) sim TOPLEVEL=orderbook MODULE=test_rtm64 EXTRA_ARGS="-GDW=64" SIM_BUILD=sim_build_rtm64

# clean all builds of the area (cocotb's clean only removes SIM_BUILD)
clean-all:
	rm -rf sim_build sim_build_hash sim_build_parser sim_build_chain sim_build_chain_nd3 sim_build_rtm sim_build_rtm64

COCOTB_RESULTS_FILE = $(CURDIR)/results.xml
REPO_ROOT := $(CURDIR)/../../..
export PYTHONPATH := $(REPO_ROOT):$(REPO_ROOT)/golden_model:$(CURDIR):$(REPO_ROOT)/verification/testbenches/orderbook:$(REPO_ROOT)/verification/testbenches/parser:$(PYTHONPATH)

include $(shell cocotb-config --makefiles)/Makefile.sim
