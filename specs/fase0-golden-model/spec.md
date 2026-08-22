# fase0-golden-model (phase 0 of the master plan)

## Goal

Build the project's single source of truth: a Nasdaq TotalView-ITCH 5.0
parser + order book in **pure Python stdlib** that reads the BinaryFILEs from
`emi.nasdaq.com`, maintains the book for the ENTIRE market, and emits the
**reference vectors** (message-by-message BBO, for a subset of symbols)
against which the RTL will be verified in phases 1–2. It includes the data
tooling: `fetch_itch.py` (download + md5) and `binaryfile_to_pcap.py`
(BinaryFILE → MoldUDP64/UDP/IP/Ethernet pcap for the testbench). Without this
campaign there is no "what to verify against"; it is the foundation of the
entire cycle.

## Scope

**In scope:**

- `golden_model/itch/messages.py` — canonical table of ITCH 5.0 layouts (single
  source: types, lengths, fields; no protocol literals anywhere else).
- `golden_model/itch/parser.py` — BinaryFILE iterator → typed messages.
  - All ITCH 5.0 types **validated** (exact length per type).
  - Common header (type, Stock Locate, tracking, timestamp) decoded in all.
  - Full fields only in: `A, F, E, C, X, D, U` (book), `R` (Stock Directory),
    `S` (System Event), `H` (Stock Trading Action — needed to gate the bid<ask
    invariant to the continuous-trading state).
  - Remaining types: counted by type. Unknown type or incorrect length =
    **hard error** (exception, not warning).
- `golden_model/src/book.py` — multi-symbol order book: order table keyed by
  order reference, aggregated price levels, BBO per symbol. Semantics:
  - `U` (Replace) is **atomic**: delete + add produce a SINGLE resulting state.
  - Empty side of the BBO is represented as `price=0, qty=0`.
  - Operation on an unknown order reference (partial windows): counted as an
    anomaly and skipped, does not abort.
- `golden_model/src/vectors.py` — writer of the canonical binary format (Annex A)
  + on-demand text dump (`--text`).
- `golden_model/src/stats.py` — day statistics: messages per type; per symbol:
  messages, peak live orders, peak levels (URAM sizing).
- `golden_model/scripts/run_golden.py` — CLI: BinaryFILE → vectors (subset) +
  stats + active invariants.
- `golden_model/scripts/select_subset.py` — symbol activity ranking; writes
  `verification/vectors/subset_symbols.json` (committed, it is config).
- `scripts/fetch_itch.py` — download from `emi.nasdaq.com/ITCH/` + md5 verification.
- `scripts/binaryfile_to_pcap.py` — BinaryFILE → real pcap (openable in
  Wireshark/tcpdump): packing up to ~1400 B of UDP payload (configurable,
  `--msgs-per-packet 1` for targeted tests), synthetic monotonic sequence
  numbers from 1, fixed configurable synthetic MAC/IP-multicast/port.
- `golden_model/tests/` — mirror tests (stdlib `unittest`; see the naming rule
  in Verification).
- Small **synthetic** vectors committed in `verification/vectors/`.

**Out of scope (non-goals):**

- RTL, cocotb, 10G MAC: phases 1+.
- numpy/pandas in the generation pipeline (pure stdlib; numpy only for
  ad-hoc analysis outside the pipeline).
- Full fields of `P, Q, B, I, N, M, T, O, Y, L, V, W, K, J` (they are counted).
- Recovery/GLIMPSE/snapshot: the sample files are full days.
- Latency metrics (phase 2), per-type histograms (phase 2+).
- Automated CI of the full-day run (decided once runtime figures exist).
- Raw data or large vectors committed (they go to `data/itch_sample/`,
  gitignored; only small synthetic vectors in `verification/vectors/`).

**Measured radius:** not applicable — initial campaign on an empty tree
(`golden_model/{itch,src,scripts,tests}/` and `scripts/` contain no sources;
verified with `find` on 2026-08-12). Nothing existing is renamed or moved.

## Constraints

- **Pure Python stdlib** in `golden_model/` and `scripts/` (precompiled struct,
  memoryview, gzip, unittest). A new dependency = explicit edit of this spec.
  Recorded decision: tests use `unittest` (stdlib), NOT pytest.
- **Performance:** the main full day (see Verification) in **≤ 2 h** on the
  owner's machine, measured with `time` over `run_golden.py`. If it does not
  meet this, the hot loop is optimized before admitting dependencies.
- Universe: book for the **entire market**; vectors only for the symbol subset
  of `subset_symbols.json` (selection rule: top 20 by **peak live orders**
  among the high-activity symbols of the main day, configurable N; the final
  choice is confirmed by the owner with the stats table).
- Determinism: same input BinaryFILE → same vectors, bit-exact.
- Endianness: ITCH is big-endian on the wire; the binary vector file is
  native little-endian (Annex A). Do not mix.

## Surface and threats

- **New inputs:** BinaryFILE (`length u16be + payload`), Nasdaq `.md5sum` file,
  CLI of the three scripts (paths, `--subset`, `--msgs-per-packet`, `--text`,
  `--out`).
- **New outputs:** binary vectors `*.vec.bin` (Annex A layout), text dump
  `*.vec.txt`, `subset_symbols.json`, stats CSV, pcap `*.pcap`.
- **Domain abuse cases** (each with its `SEC-` scenario in Gherkin):
  unknown type (SEC-01), incorrect length (SEC-02), truncated message (SEC-03),
  operation on unknown ref (SEC-04), crossed book in auction (SEC-05), message
  larger than the max UDP payload (SEC-06), incorrect md5 (SEC-07), locked book
  in continuous trading on real data (SEC-08), md5 endpoint down (DAT-03).
- **What is at risk from the master:** if the golden model lies, the ENTIRE
  cycle verifies against a false reference (50 % of the project's value is
  bit-exact correctness). The binary vectors are also the contract that cocotb
  will consume: an ambiguous layout here is a bug in phase 1.

## Reuse

- No prior code to extend (initial campaign). `Grep`/`find` confirm
  `golden_model/`, `scripts/` are empty of sources.
- Only stdlib is used. Agreed dependencies: **none**. (`pytest` is discarded in
  favor of `unittest`; `numpy` outside the generation pipeline.)

## Acceptance criteria (Definition of Done)

1. [ ] The parser iterates the entire main day without errors: all messages
   validated by length, common header decoded, per-type count emitted;
   unknown type / incorrect length / truncated = hard error.
   — Gherkin: `parser.feature` §PAR-01, §PAR-02, §PAR-03, §SEC-01, §SEC-02, §SEC-03
2. [ ] The book produces the correct BBO in the known-answer cases (add, partial/
   total execute, cancel, delete, atomic replace, empty book), with hand-written
   expected values.
   — Gherkin: `book.feature` §LIB-01…§LIB-06
3. [ ] Invariants active in every real run, checked per message: qty > 0 in live
   orders and levels; unique order references; levels consistent with orders
   (periodic deep check + close). Violation = abort with a message identifying
   the message index. **Exception (iteration-2 correction, with evidence):** a
   locked/crossed book in continuous trading does NOT abort: it exists in real
   data (halt→trading transitions; e.g. symbol ZJZZT, msg 39778763 of the main
   day, bid==ask==130000 for 2 messages). The book counts those events with
   their message index and the run summary reports them. Strict mode
   (`strict_cross=True` / `--strict`) keeps the abort and is what the synthetic
   tests exercise.
   — Gherkin: `book.feature` §INV-01, §SEC-04, §SEC-05, §SEC-08
4. [ ] The vector writer emits one record per modifying message
   (`A/F/E/C/X/D/U`) of the subset symbols, with a monotonic global message
   index, the 40 B layout of Annex A, and the correct change flag.
   — Gherkin: `vectores.feature` §VEC-01, §VEC-02, §VEC-04
5. [ ] Round-trip: the text dump reproduces the binary field by field; the
   reader re-reads what it wrote without loss.
   — Gherkin: `vectores.feature` §VEC-03
6. [ ] Real run of the main day: vectors + stats generated, invariants without
   violations, runtime ≤ 2 h (`time` output pasted in the verify-report).
   — Gherkin: `parser.feature` §PAR-01, §PAR-02; `datos.feature` §DAT-02
7. [ ] `fetch_itch.py` downloads and verifies md5; an incorrect md5 aborts
   without leaving a seemingly valid file. If the server does not serve the
   `.md5sum` (today it returns 404), it aborts **fail closed** with a clear
   error and exit != 0 (no traceback); `--no-md5-verify` allows the download
   with a stderr warning (iteration-3 correction, grade finding: the 404 came
   through as an unhandled traceback).
   — Gherkin: `datos.feature` §DAT-01, §DAT-03, §SEC-07
8. [ ] `binaryfile_to_pcap.py`: pcap openable with `tcpdump -r` without errors;
   payload ≤ configured limit; monotonic seq from 1; **round-trip**: extracting
   the MoldUDP64 payloads from the pcap reconstructs the original BinaryFILE
   stream byte for byte.
   — Gherkin: `pcap.feature` §PCA-01…§PCA-04, §SEC-06
9. [ ] `subset_symbols.json` generated from main-day stats, with the ranking
   table that justifies it (artifact for the write-up and URAM sizing).
   — Gherkin: `datos.feature` §DAT-02
10. [ ] Pure stdlib: `grep` of imports in `golden_model/` and `scripts/` shows
   only stdlib modules (command in Verification).
   — No Gherkin scenario (static property, not behavior).

## Verification

| Criterion | How it is tested |
|---|---|
| 1, 2, 3, 4, 5 | `python3 -m unittest discover -s golden_model/tests -v` — mirror tests with normalized title (rule: scenario name lowercase, spaces→`_`, no accents or punctuation, prefix `test_`; e.g. §SEC-01 → `test_sec01_tipo_de_mensaje_desconocido_es_error_duro`) |
| 6 | `time python3 golden_model/scripts/run_golden.py data/itch_sample/12302019.NASDAQ_ITCH50.gz --subset verification/vectors/subset_symbols.json --out data/itch_sample/out/` (exit 0, no violations, runtime pasted) |
| 7 | `python3 scripts/fetch_itch.py <file>` over a full download via `file://` (real urllib), a deliberately corrupted file, and a 404 md5 endpoint (fail closed) |
| 8 | `python3 scripts/binaryfile_to_pcap.py <in> <out>.pcap` + `tcpdump -r <out>.pcap` + mirror round-trip test |
| 9 | `cat verification/vectors/subset_symbols.json` + stats table in the verify-report |
| 10 | `grep -RhE '^(import\|from) ' golden_model/ scripts/ \| sort -u` → only stdlib |

Full regime: skill `verify`. For this campaign: gate A = green unittest;
B/C = `python3 -m py_compile` of what was touched + conventions (type hints in
APIs, module docstrings); D = spec↔test table + coverage by message type of the
real day; E = **agreed manual mutation**: 5 mutants over `book.py`/`parser.py`
(flip `<`→`<=` in BBO, ±1 in qty, not deleting a level at qty 0, inverted
change flag, relaxed length check) — each one must die with a test;
F = Gherkin mirrors (this campaign maps to `golden_model/tests`, declared in
`specs/gherkin-espejos.json`); G = G0+G3 (real data outside the repo, golden as
source); **gate G timing/Vivado: NOT APPLICABLE** (no RTL in phase 0, declared
NOT EXECUTED with this justification).

**Geless contracts** — what can break with suite and lint green:

1. **Self-consistent but mis-transcribed layout table.** Parser and test packer
   share `messages.py`: if the table is copied wrongly from the PDF, the tests
   pass anyway. Guardrail: the synthetic test vectors are **hand-written hex
   literals from the spec PDF** (independent oracle), never generated by the
   code itself; and the per-type count of the real day must match known orders
   of magnitude (pasted in the verify-report).
2. **Binary record layout (Annex A) vs. the future cocotb reader.** Nothing in
   phase 0 forces the RTL to read it right. Guardrail: writer↔reader↔text
   round-trip in tests + layout fixed byte by byte in this spec (changing it =
   spec edit).
3. **Semantics inherited by the RTL** (atomic replace, empty side = 0/0, change
   flag): the golden defines them and phases 1–2 consume them; their specs must
   reference this contract, not redefine it.

## Loop

Stop limit: **5 iterations**. Cadence: chain build→verify→grade while there is
a queue; when the limit is reached with criteria in FAIL, escalate to the owner.

---

## Annex A — vector record layout (canonical, 40 bytes, little-endian)

| Offset | Size | Field | Description |
|---|---|---|---|
| 0 | 8 | `msg_idx` u64 | Global message index in the BinaryFILE (0-based) |
| 8 | 8 | `ts_ns` u64 | Message timestamp (ns from midnight, from the ITCH field) |
| 16 | 4 | `bid_px` u32 | Best bid (integer ITCH price, ×10⁴); 0 if side empty |
| 20 | 4 | `bid_qty` u32 | Aggregated qty at best bid; 0 if side empty |
| 24 | 4 | `ask_px` u32 | Best ask; 0 if side empty |
| 28 | 4 | `ask_qty` u32 | Aggregated qty at best ask; 0 if side empty |
| 32 | 2 | `locate` u16 | Stock Locate Code |
| 34 | 1 | `msg_type` u8 | ITCH ASCII type (`A,F,E,C,X,D,U`) |
| 35 | 1 | `flags` u8 | bit0 = BBO changed vs. the previous record of the symbol |
| 36 | 4 | `reserved` u32 | 0 (future depth/version) |

Python `struct`: `"<QQIIIIHBBI"`. One record per modifying message of each
subset symbol. No file header (the layout is the contract; the filename carries
day + subset hash).

## Annex B — campaign data

- **Main day:** `12302019.NASDAQ_ITCH50.gz` (~3.5 GB gz — the smallest v5.0 on
  the server as of 2026-08). **Regression day:** `01302019.NASDAQ_ITCH50.gz`
  (~4.8 GB gz). If they become unavailable: the smallest available v5.0, with an
  explicit edit of this annex.
- The raw data and generated vectors live in `data/itch_sample/` (gitignored).
- The files are NOT pcap: they are BinaryFILE (`length u16be + payload`), with
  no sequence numbers — the MoldUDP64 seq of the pcap are synthetic, and gap
  detection will be tested in RTL phases with fabricated sequences, not with
  this replay.