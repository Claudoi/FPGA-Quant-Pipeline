"""DW=64 regression of the emission pipeline (phase 3, iter 7) — module of the
sim-rtm64 elaboration.

RTM-REG-01: the pipelined book at DW=64 (RTL default) re-runs the phase 2
corpus bit-exact against the golden model. Separated from test_rtm32 because
the width skip is static in cocotb 2.0.1 (no runtime SkipTest): each Makefile
target points to the module of its width."""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

from test_orderbook import S, A, E, X, D, run_book, drive_and_collect_bbo

@cocotb.test()
async def test_rtm_reg01_regresion_64_bits_con_pipeline(dut):
    """Mirror §RTM-REG-01: the pipelined book at DW=64 (default) re-runs the phase 2
    corpus bit-exact against the golden model (parameterization regression;
    exercised in the sim-rtm64 elaboration)."""
    await _reset(dut)
    msgs = [
        S(AMZN, 1_000_000_000, ord("Q")),
        A(AMZN, 1_000_000_001, 1, b"B", 100, b"AMZN    ", 1_000_00),
        A(AMZN, 1_000_000_002, 2, b"S", 50, b"AMZN    ", 1_005_00),
        E(AMZN, 1_000_000_003, 1, 40, 1001),
        X(AMZN, 1_000_000_004, 2, 30),
        D(AMZN, 1_000_000_005, 1),
        A(AMZN, 1_000_000_006, 3, b"B", 200, b"AMZN    ", 999_00),
    ]
    expected, golden = run_book(msgs)
    got, cross, anomaly, errors = await drive_and_collect_bbo(dut, msgs)
    assert got == expected, (
        f"RTM-REG-01: got={got} exp={expected}")
    assert anomaly == golden.anomalies, (
        f"RTM-REG-01 anomaly: got={anomaly} exp={golden.anomalies}")
    assert cross == golden.cross_events, (
        f"RTM-REG-01 cross: got={cross} exp={golden.cross_events}")
    assert errors == 0, f"RTM-REG-01: {errors} spurious errors"
    cocotb.log.info(
        f"RTM-REG-01 OK: DW=64, {len(got)} events bit-exact vs golden "
        f"(parameterization regression with the emission pipeline)")


AMZN = 393


async def _reset(dut):
    dut.clk.setimmediatevalue(0)
    cocotb.start_soon(Clock(dut.clk, 5, unit="ns").start())
    dut.rst_n.value = 0
    dut.s_axis_tvalid.value = 0
    dut.s_axis_tdata.value = 0
    dut.s_axis_tlast.value = 0
    dut.bbo_tready.value = 1
    dut.depth_tready.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1