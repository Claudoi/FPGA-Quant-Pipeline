**Goal:** build a project that establishes a strong FPGA / low-latency trading-infrastructure profile for entering quant finance, maximizing CV value, real technical experience, and demonstrable material (repo + write-up + metrics).

**Date:** August 2026 **Target device:** AMD/Xilinx UltraScale+ (Zynq US+ or Virtex/Kintex US+ family)

---

## 0. Terminology clarifications first (important)

Before comparing options, two clarifications that define the whole project:

### 0.1. What "32 bits @ 322 MHz without throttling" really means

- 32 bits × 322.265625 MHz = **10.3125 Gbps** → exactly the bandwidth of **10G Ethernet**.
- 322.265625 MHz is the standard clock of the 32-bit XGMII datapath in 10GBASE-R.
- Therefore, "processing without throttling at 32-bit/322 MHz" = **processing a market feed at 10G line rate**, which is the standard industry bar (Optiver, IMC, Jump Trading, HRT, Citadel Securities build exactly this).
- **Equivalent alternative that is easier to close in timing:** a **64-bit @ 156.25 MHz** datapath (same throughput, 10.0 Gbps effective with 64-bit XGMII). This is what Vivado's 10GBASE-R core delivers natively. Closing timing at 322 MHz with a 32-bit datapath is notably harder and **demonstrates nothing additional at 10G**; it serves as a documented optimization exercise afterward (it reads better in the write-up: "closed timing at 322 MHz on US+, here is how").

### 0.2. "URAM order book" (previously referred to as URX order book)

- UltraScale+ **URAM (UltraRAM)** blocks are 288 Kb (4K × 72-bit) on-chip memory blocks, far denser than BRAM.
- They are the ideal memory for storing **order state** (a hash table indexed by order reference number) and **price levels** in a hardware order book.
- In other words: the intuition was correct — the standard FPGA order-book architecture uses URAM for primary storage.

### 0.3. Structural conclusion: the two options do NOT compete

- **Option A (order book)** and **Option B (line-rate parser)** are **consecutive stages of the same pipeline**, not alternative projects:

```
10G MAC → IP/UDP decapsulation → framing (MoldUDP64) → message parser → order book engine (URAM) → BBO/top-of-book output
```

- A parser without a book is half a project: firms are not interested in decoded messages, they are interested in the **book state derived from them with low latency**.
- A book without a line-rate parser is a software project disguised as an FPGA.
- The winning project is **the complete pipeline**, built in phases. The real "options" are: **which exchange/protocol to choose** and **how far to go in each phase**.

---

## 1. Option A — Complete order book on FPGA

### 1.1. Description

Hardware order-book engine: receives already-parsed market messages (add, execute, cancel, delete, replace), maintains the complete book state (live orders + aggregated price levels), and emits the **BBO** (best bid & offer) or the N best levels per symbol, with deterministic nanosecond latency.

### 1.2. Detailed technical scope

**Hardware data structures:**

- **Order table:** hash table in URAM indexed by _order reference number_ (64 bits in ITCH). Each entry stores: symbol (or symbol index), side (bid/ask), price, remaining quantity, pointer to price level.
    - Collision handling: open addressing with bounded probing, or cuckoo hashing (more advanced, better worst case).
    - Sizing: a day of Nasdaq can have hundreds of millions of messages, but _simultaneously live_ orders per symbol are orders of magnitude fewer; for a symbol subset they fit in URAM.
- **Price levels:** per symbol and side, an array/list of levels with price and aggregated quantity.
    - Simple version: array indexed by price relative to the mid (price banding).
    - Advanced version: heap/tree in hardware for top-N levels.
- **BBO output:** per-symbol register with best bid, best ask, and quantities; an event is emitted each time it changes.

**Operations to support (map 1:1 to ITCH messages):**

|Operation|ITCH message|Action on the book|
|---|---|---|
|Add order|`A` / `F`|Insert into order table, update price level|
|Execute|`E` / `C`|Reduce quantity; if it reaches 0, remove order and update level|
|Partial cancel|`X`|Reduce order and level quantity|
|Delete|`D`|Remove order, update/remove level|
|Replace|`U`|Atomic delete + add (new reference, new price/quantity)|
|Hidden trade|`P`|Does not touch the book (trades against hidden orders); useful for statistics|

**Real design challenges (what gives the write-up value):**

- Pipeline hazards: two consecutive messages on the same order/level (read-after-write) → forwarding or selective stalling.
- URAM latency (registered read, 1-2 cycles) → pipeline design around that latency.
- Atomic replace without an inconsistency window in the BBO.
- Multi-symbol: memory partitioning and an arbiter, or parallel instances.

### 1.3. Difficulty

- **High.** The hardest part of the pipeline: stateful data structures, hazards, strict functional correctness.
- Requires mastering the parser first (the book's input is parsed messages).

### 1.4. CV value

- **Maximum.** This is literally what FPGA teams at HFT firms build. A functional book verified against real data with a latency histogram is an exceptional project for a junior profile.

---

## 2. Option B — Line-rate exchange parser (32-bit @ 322 MHz / 10G)

### 2.1. Description

Hardware decoder for an exchange protocol that processes the feed at 10G line rate without backpressure: extracts from each packet the relevant fields (message type, order ref, symbol, price, quantity, timestamp) and emits them over an internal interface (AXI-Stream) to the consumer (in the complete project, the order book).

### 2.2. Detailed technical scope

**Receive pipeline layers:**

1. **10G PHY/MAC:** 10GBASE-R core + MAC (Vivado provides free IP in many configurations; open-source alternative: corundum cores or similar).
2. **Ethernet/IP/UDP decapsulation:** header validation, port/multicast group filtering. (Optional: UDP checksum — real feeds are usually validated upstream; document the decision.)
3. **Exchange transport-protocol framing:**
    - Nasdaq: **MoldUDP64** (session + sequence number + message count; each message carries a 2-byte length prefix).
    - CME: MDP packet with Binary Packet Header (sequence number + sending time) and concatenated SBE messages.
    - Cboe: **Sequenced Unit Header** (length, count, unit, sequence).
4. **Message parser:** state machine that consumes the stream (32 or 64 bits/cycle), identifies the message type and extracts fields. Messages can cross word and packet boundaries → a barrel shifter / aligner is the key piece.
5. **Sequence management:** sequence-number gap detection (minimum: count and flag them; advanced: recovery/A-B arbitration).

**What the "no throttling" requirement implies:**

- Worst case: minimal messages back-to-back (in ITCH, messages of ~26-40 bytes) → the parser must accept a new word **every cycle, without exceptions**. No elastic FIFOs hiding a slow parser.
- This forces a fully pipelined design: that is the difference between "a parser that works in simulation" and "an industrial-quality parser".

### 2.3. Difficulty

- **Medium-high.** Less state than the book, but strict line rate + message alignment + timing closure is a serious challenge for someone without prior RTL experience. It is the correct entry phase into the project.

### 2.4. CV value

- **High but incomplete on its own.** "Line-rate ITCH parser" is a well-known project, replicated across GitHub; what differentiates this one is (a) the rigor of verification against real data, (b) the latency metrics, and (c) continuing on to the book.

---

## 3. Exchange/protocol comparison (the decision that really matters)

### 3.1. Nasdaq TotalView-ITCH 5.0 — **RECOMMENDED as the initial target**

- **Spec:** public and free (nasdaqtrader.com, PDF "NQTVITCHspecification").
- **Protocol:** binary, fixed-length messages by type, identified by an ASCII character (`S`, `R`, `A`, `F`, `E`, `C`, `X`, `D`, `U`, `P`...). Big-endian. **Ideal for a hardware FSM.** Transport: MoldUDP64 (also with a public spec).
- **Real data:** **FREE.** Nasdaq publishes full-trading-day sample files (order-by-order) on its public server `emi.nasdaq.com/ITCH/`.
    - **Critical nuance:** those files are NOT standard libpcap pcaps (they do not open in Wireshark). They follow Nasdaq's **BinaryFILE** format: a sequence of messages with a length field (2 bytes) + payload. Wrapping them in MoldUDP64/UDP/IP/Ethernet to feed the testbench requires a Python script — that script is itself a valuable repo artifact.
- **Protocol complexity:** low-medium. A functional book needs only ~6-10 message types.
- **Why it is the de facto standard for FPGA order-book projects:** public spec + free data + simple protocol. Practically all published projects use ITCH.

### 3.2. CME MDP 3.0 — **RECOMMENDED as a second (stretch) target**

- **Spec:** public (cmegroup.com, "Market Data Platform 3.0", **SBE — Simple Binary Encoding**, with XML template schemas).
- **Protocol:** more sophisticated: SBE messages defined by versioned templates, incremental feed + snapshot for recovery, channels per product, duplicated A/B feeds that must be arbitrated. Technically more impressive than ITCH.
- **Real data:** **PAID.** CME sells historical pcaps via its DataMine platform (grouped by channels; e.g. channel 310 = E-mini S&P). Getting even a few sample days involves commercial paperwork and cost. There are no public sample files comparable to Nasdaq's.
- **Verdict:** starting here means hitting the data wall before writing a line of RTL. But **porting** the ITCH pipeline to MDP3 (even if only the SBE parser, verified with synthetic packets generated from the XML schemas) demonstrates design generality and knowledge of the protocol of the world's largest futures market. An excellent final chapter.

### 3.3. Cboe (BZX/EDGX...) Depth of Book — PITCH

- **Spec:** public (Cboe publishes the Multicast PITCH and Sequenced Unit Header specs).
- **Protocol:** binary, conceptually similar to ITCH (add/execute/cancel by order id), little-endian in the multicast version. Complexity comparable to ITCH.
- **Real data:** depth-feed sample captures are **much harder to obtain** than Nasdaq's; there is no public repository equivalent to `emi.nasdaq.com`.
- **Verdict:** no advantage over ITCH and worse data access. Discarded as an initial target; valid as an additional port if captures are ever obtained.

### 3.4. NYSE (XDP / Integrated Feed)

- **Spec:** public (XDP Integrated Feed Client Specification).
- **Real data:** NYSE has published downloadable sample data with relative ease.
- **Verdict:** a reasonable alternative to ITCH, but the ecosystem of projects, tools, and references around ITCH is much larger. A second option if one wants to stand out from the "typical ITCH project"; not recommended as a first target because the safety net of existing references is lost.

### 3.5. Summary table

|Criterion|Nasdaq ITCH 5.0|CME MDP 3.0|Cboe PITCH|NYSE XDP|
|---|---|---|---|---|
|Public spec|✅|✅|✅|✅|
|Free real data|✅ (emi.nasdaq.com)|❌ (DataMine, paid)|⚠️ difficult|⚠️ downloadable sample|
|Protocol complexity|Low-medium|High (SBE, recovery, A/B)|Low-medium|Medium|
|Suitability for hardware FSM|Excellent|Good (SBE is regular)|Excellent|Good|
|Existing references/projects|Very many|Few|Few|Few|
|Protocol prestige|High|Very high (futures)|High|High|
|**Role in the project**|**Main phase**|**Final stretch**|Discarded|Alternative/port|

---

## 4. Final recommendation: combined phased project

**A single project: "Line-rate ITCH 5.0 parser + URAM order book on UltraScale+", with a port to CME MDP3 as a stretch phase.**

### Phase 0 — Golden model in Python (1-2 weeks of real work)

- Golden ITCH parser + order book in pure Python reading the `emi.nasdaq.com` files.
- Objectives: learn the protocol in detail, generate the reference vectors (book state and BBO message by message) against which the RTL will be verified.
- Deliverable: `golden_model/` + `binaryfile_to_pcap.py` script (wraps BinaryFILE in MoldUDP64/UDP for the testbench).

### Phase 1 — Line-rate parser RTL (1-2 months)

- **64-bit @ 156.25 MHz** datapath (the one Vivado's native 10GBASE-R core delivers). Message subset: `S, R, A, F, E, C, X, D, U, P`.
- AXI-Stream output with normalized messages.
- Hard requirement: accept one word per cycle without exception (worst case: minimal messages back-to-back).
- Verification: cocotb (or a SystemVerilog testbench) replaying the real pcaps and comparing byte-for-byte against the golden model.

### Phase 2 — Order book engine (2-3 months)

- Order table in URAM (hash by order ref), price levels, BBO output.
- Start with a handful of symbols; scale later.
- Verification: same replay, comparing the RTL BBO against the golden model's on each message.
- Metrics: wire-to-book-update latency histogram in cycles/ns.

### Phase 3 — Optimization and closure (1 month)

- **Now yes:** a 32-bit @ 322.265625 MHz variant with a timing-closure report on the target US+ device. Document the techniques used (retiming, critical-path pipelining, floorplanning if needed). As an optimization chapter, this reads **better** than as the starting point.
- Utilization report (LUT/FF/BRAM/URAM) and timing.

### Phase 4 — Stretch (optional, ordered by CV value)

1. CME MDP3 SBE parser verified with synthetic packets from the XML schemas (+ DataMine pcaps if they are ever purchased).
2. AXI/PCIe host interface to dump the BBO to software.
3. Published technical write-up (blog/GitHub Pages) with latency benchmarks.

### Physical hardware: optional, not blocking

- The entire project is demonstrable **without a board**: simulation with real data + timing closure in Vivado targeting the US+ part is already a very strong project.
- For a later physical demo: a used Alveo U50, ZCU106, or repurposed used US+ boards from the mining market. A decision for the end, not the beginning.

### Honest total-effort estimate

- **4-7 months** of steady work alongside studies, starting with no RTL experience. The write-up documenting the learning curve is half the signal the project sends.

---

## 5. Final CV deliverables

1. Public repo: RTL + golden model + testbench + data scripts + simulation CI.
2. Timing/utilization report on UltraScale+ (156 MHz and the 322 MHz variant).
3. Per-message-type latency histograms (wire-in → BBO out).
4. Technical write-up: architecture decisions, book hazards, timing closure.
5. (Stretch) CME MDP3/SBE chapter.

**Target CV sentence:** _"Designed and verified an FPGA (UltraScale+) pipeline that decodes Nasdaq TotalView-ITCH 5.0 at 10G line rate and maintains a URAM order book with deterministic X-ns latency, verified against full days of real market data."_

---

## 6. Risks and common mistakes to avoid

- **Starting with CME:** runs out of real data before starting. ITCH first.
- **Starting with 32-bit @ 322 MHz:** gratuitous timing difficulty with no added value at 10G; do it as a final optimization.
- **Parser without book:** a half project, and also the most replicated one on GitHub.
- **Book without golden-model verification:** a book that "seems to work" is worthless; bit-exact correctness against real data is 50% of the value.
- **Supporting all ITCH message types from day 1:** a subset of ~10 types is enough for a functional book; the rest is added later.
- **Buying a board on day one:** premature expense; simulation + timing closure is already demonstrable.
- **Ignoring sequence numbers:** detecting MoldUDP64 gaps, even just counting them, is what separates a toy from a design that is aware of the real world.

---

## 7. Key resources

- **ITCH 5.0 spec:** nasdaqtrader.com → Technical Support → Specifications → "NQTVITCHspecification.pdf".
- **MoldUDP64 spec:** nasdaqtrader.com (same spec repository).
- **ITCH sample data:** `emi.nasdaq.com/ITCH/` (files `*.NASDAQ_ITCH50.gz`, BinaryFILE format).
- **CME MDP 3.0 spec + SBE schemas:** cmegroup.com → Market Data → MDP 3.0; SBE on the FIX Trading Community website.
- **Cboe PITCH spec:** cboe.com → US Equities → Technical Specifications.
- **NYSE XDP spec:** nyse.com → Market Data → Integrated Feed technical documentation.
- **Tools:** Vivado (WebPACK covers quite a few US+ parts), cocotb + Verilator/Questa for verification, Python for golden model and data tooling.