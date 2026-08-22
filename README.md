# FPGA Quant Pipeline

A low-latency market-data pipeline for **AMD/Xilinx UltraScale+**: a
Nasdaq TotalView-ITCH 5.0 parser and an order book with BBO / top-N output,
plus a CME MDP3/SBE parser, all verified bit-exactly against an independent
Python golden model.

The RTL starts at the already-decapsulated MoldUDP64 payload. The 10G MAC and
Ethernet/IP/UDP layers are intentionally **out of scope** for this repository.

```
MoldUDP64  ->  ITCH parser  ->  order book (URAM)  ->  BBO / top-N
```

## Project status

| Phase | Scope | Status |
|---|---|---|
| **0** | Python golden model (ITCH parser + order book + vectors + tooling) | **Closed** — 22 message types, full-day replay |
| **1** | MoldUDP64/ITCH parser RTL, verified against golden | **Closed** — `s_axis_tkeep` framing, gaps, backpressure, 91/91 `tlast`; **REP-02 line-rate closed** (real A/U burst, 9 stalls <= 24) |
| **2** | Order book RTL (20-symbol subset) | **Closed** — BBO bit-exact, atomic replace, real replay |
| **3** | DW=32 variant, top-N and URAM architecture | **Functional closed end-to-end** (17.484 BBO events bit-exact, cross=0/anomaly=0/gaps=0). **156.25 MHz / 10G closed** (WNS +0.057 ns, URAM 32/48). **322 MHz open** — the internal datapath closes, but the output I/O (OBUF + clock) of the -2L part is the limit |
| **4** | CME MDP3/SBE parser | **Functional closed** (14/14 DW=32/64, gate E 14/14). Timing open: the parser does not fit the XCKU3P (LUT over-utilization) |

The main architecture write-up (hazards, latency, timing, honest limits) is in
[`docs/writeup/pipeline-itch-uram.md`](docs/writeup/pipeline-itch-uram.md).

### Phase 0 evidence (Nasdaq 2019-12-30, 3.5 GB real capture)

- **268,744,780 messages** parsed and processed by the book in **17 min**
  (spec target: <= 2 h). 0 protocol anomalies.
- **14,427,667 BBO vectors** (40 B records, layout in
  `specs/fase0-golden-model/spec.md` Annex A) for a 20-symbol subset selected
  by measured activity (AMZN, AAPL, MSFT, ...).
- 29/29 tests, 5/5 HDL-paired mutants killed, pure stdlib.
- Contract, Gherkin, verify report and grade verdicts in
  `specs/fase0-golden-model/`.

## Verified numbers

- **Latency** wire->BBO, DW=32/QB=46: **65.5 cycles = 203.3 ns** @ 322.265625 MHz
  (mean, deterministic across re-runs). Histogram persisted in
  `verification/vectors/latency/latency_dw32.json`.
- **156.25 MHz variant**: 64b @ 156.25 MHz = 10G, **WNS +0.057 ns**, TNS 0,
  WHS +0.021 ns, URAM **32/48**, DRC 0.
- **322 MHz variant**: 32b @ 322.265625 MHz — the book's internal datapath
  closes after splitting the `m_loc_idx -> sm_asel` timing path; the residual
  WNS is dominated by the output I/O (source clock delay + OBUF) of the -2L
  speed grade. Documented as an open chapter, not a closing claim.

## Layout

| Directory | Contents |
|---|---|
| `golden_model/` | ITCH parser (`itch/`), order book (`src/book.py`), vectors (`src/vectors.py`), stats, CLIs (`scripts/`), mirror tests (`tests/`) |
| `scripts/` | `fetch_itch.py` (download + md5, fail-closed), `binaryfile_to_pcap.py` (BinaryFILE -> MoldUDP64/UDP/IP/Eth pcap) |
| `rtl/` | ITCH/MDP3 parsers, `orderbook/`, chain, and common modules |
| `verification/` | (phases 1+) cocotb testbenches; `vectors/` with small samples and `subset_symbols.json` |
| `specs/` | Per-campaign contracts: `spec.md` + `gherkin/` + `verify-report.md` |
| `synth/` | (phase 3) Vivado constraints and reports |
| `docs/` | `DEVELOPMENT.md` (setup/gates), `decisions/`, `writeup/` |
| `data/itch_sample/` | Real data — **never committed** (gitignored) |

## Usage

```bash
# Full Python regression (ITCH + CME)
python3 -m unittest discover -s golden_model/tests -t .

# Download one sample day from emi.nasdaq.com (md5 verification; fail-closed)
python3 scripts/fetch_itch.py 12302019.NASDAQ_ITCH50.gz

# Golden-model run: stats + vectors for the subset
python3 -m golden_model.scripts.run_golden data/itch_sample/12302019.NASDAQ_ITCH50.gz \
    --subset verification/vectors/subset_symbols.json --out data/itch_sample/out --text

# BinaryFILE -> MoldUDP64 pcap for the RTL testbenches
python3 scripts/binaryfile_to_pcap.py in.ITCH50 out.pcap
```

Requirements: Python 3.10+ pure stdlib (phase 0). RTL phases: Verilator + cocotb
+ Vivado (see `docs/DEVELOPMENT.md`).

## Process

Each campaign follows the loop **spec -> red/green -> verify -> adversarial
review**. The A-G verification gates and the closing criteria live in the
campaign specs under `specs/<campaign>/`; each contract and its evidence are
kept together there.

## Rules

- Real market data is never committed (`data/itch_sample/**` is ignored).
- Commits follow Conventional Commits.
- The 322 MHz optimization is a final chapter, not the starting point.