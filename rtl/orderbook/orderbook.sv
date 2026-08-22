// orderbook.sv — order book engine (phase 2, Annex A -> BBO).
//
// Consumes the Annex-A register emitted by the phase-1 parser:
//   word0 = {msg_type[7:0], locate[15:0], length[7:0], msg_idx[31:0]}
//   word1 = ts_ns (not used by the book in this phase)
//   words 2..N = body of the message (wire fields, big-endian)
// At DW=32 (fase3-uram, Annex-A trim): w0={type,locate,len}, w1=msg_idx,
// w2..=body — WITHOUT timestamp words (amended contract).
//
// Replicates the EXACT semantics of golden_model/src/book.py (phase 0).
//
//   STRUCTURES (fase3-uram, iteration 2: URAM table + serialized probe):
//   - orders in URAM of NSLOT = 2^SLOT entries of OW=86 bits:
//     {qty[31:0], price[31:0], side, ref[19:0], valid}. hash(ref) =
//     ref[SLOT-1:0]; linear probing bounded to PROBE steps. The read is
//     SYNCHRONOUS REGISTERED (URAM inference pattern): one read port
//     (rd_addr -> rd_data 1 cycle later) and one write port (a SINGLE
//     o_mem[wr_addr] <= wr_data statement at the end of the always_ff —
//     writing via task broke the inference, Synth 8-7186, finding
//     2026-08-18; max 1 write per cycle, never in the same cycle as a probe
//     read). NEVER combinational indexing of the table (blocker B1 of
//     criterion 10, documented in docs/writeup/lessons-learned.md §7).
//   - The probe (probe engine) serializes the lookup to ≤1 slot/cycle and
//     starts DURING ST_BODY (prefetch of the hash group: the order_ref
//     travels in the first words of the body and the hash is known before
//     ST_APPLY): the results (found/slot/entry, first empty, full) stay in
//     registers and ST_APPLY consumes them WITHOUT re-reading the table.
//   - The reset does NOT touch the URAM content (it would kill the
//     inference): an ST_INVAL state invalidates the 65.536 slots at 1
//     slot/cycle (the URAM starts at 0 in silicon; the write-invalidation
//     pattern is standard and the only one compatible with synthesis).
//   - levels per (side): ordered list of P levels {price, qty}, best first
//     (bid = higher, ask = lower) — unchanged in this iteration (the level
//     pipeline is iteration 3).
//
// CORRECTNESS > speed: 1 message/clock cycle, O(P) logic.
module orderbook #(
    parameter DW  = 64,
    parameter K   = 64,          // order_ref width (bits). 64 = the wire's ref
                                 // untruncated: the real day exceeds 2^19
                                 // (refs ~1,6M at the open) and K=19 collided
                                 // residues (254 lost events, addendum
                                 // iter 12); K<=20 keeps the 86-bit layout of
                                 // the verified configs
    parameter SLOT = 16,         // 2^SLOT slots of the hashed table (criterion 5).
                                 // hash(ref) = ref[SLOT-1:0]
    parameter PROBE = 8,         // max linear-probing steps per op
    parameter ND   = 5,          // levels of the public top-N (criterion 6)
    parameter P   = 32,          // price levels per side. Measured max of the
                                 // real subset: 17 (locate 6960 ask, local
                                 // day); the >P overflow is still signaled (SEC-OV)
    parameter NSYM = 20,         // symbols of the subset
    parameter PXW = 32,          // price width (ITCH sub-cents)
    parameter QW  = 32           // qty width
) (
    input  wire              clk,
    input  wire              rst_n,
    input  wire [DW-1:0]     s_axis_tdata,
    input  wire              s_axis_tvalid,
    output wire              s_axis_tready,
    input  wire              s_axis_tlast,
    output reg  [15:0]       bbo_locate,
    output reg  [127:0]      bbo_tdata,
    output reg               bbo_tvalid,
    input  wire              bbo_tready,
    output reg               bbo_changed,
    output reg  [2*ND*64-1:0] depth_tdata,
    output reg               depth_tvalid,
    input  wire              depth_tready,
    output reg  [31:0]       cross_events,
    output reg  [31:0]       anomaly_count,
    output reg               error
);

    localparam NSLOT = 2**SLOT;
    // ref field in memory: max(K, 20) — the configs with K<=20 keep the
    // verified 86-bit layout; K>20 (e.g. K=64 of the real feed, addendum
    // iter 12) widens the input to OW=1+REFW+1+PXW+QW (130 bits at K=64)
    localparam REFW  = (K > 20) ? K : 20;
    localparam OW    = 1 + REFW + 1 + PXW + QW;   // {qty,px,side,ref,valid}

    // bytes per word and its log2: 64 bits -> 8 B (b>>3), 32 bits -> 4 B (b>>2)
    localparam BYTES = DW / 8;
    localparam L2B   = $clog2(DW / 8);
    // log2(P) for the tree first-hot encoder of stage 2a (iter 8); P must be
    // a power of 2 (the chain fixes P=32)
    localparam integer LOGP = $clog2(P);

    // ---------------------------------------------------------------
    // receive FSM
    // ---------------------------------------------------------------
localparam ST_W0         = 4'd0;
localparam ST_TS         = 4'd1;
localparam ST_BODY       = 4'd2;
localparam ST_APPLY      = 4'd3;
localparam ST_UADD       = 4'd5;
    localparam ST_WAIT_PROBE = 4'd6;   // the prefetch did not finish during the body
    localparam ST_INVAL      = 4'd7;   // post-reset invalidation (1 slot/cycle)
    // level pipeline (fase3-uram iter 3): level_add split into registered
    // stages — ST_LV2 (iter 8: tree find-first, decode_lv2a), ST_LV2B (iter
    // 8: priority + mux, decode_lv2b), ST_LV3 materializes and writes. Each
    // operation consumes 3 extra cycles at most (SEC-URAM-03 amended by the
    // +1 of iter 8; the average stays <= 48)
    localparam ST_LV2        = 4'd8;
    localparam ST_LV2B       = 4'd14;
    localparam ST_LV3        = 4'd9;
    localparam ST_SWAP       = 4'd10;   // atomic swap of the double buffer (iter 4)
    // event emission pipeline (iter 7, addendum): the single-cycle
    // combinational ST_EMIT is split into stages A (capture) / B
    // (selection+changed+depth) / C (handshake) — +2 cycles on the event
    // path; latency re-derived to avg <= 48 (RTM-LAT-01)
    localparam ST_EMIT_A     = 4'd11;
    localparam ST_EMIT_B     = 4'd12;
    localparam ST_EMIT_C     = 4'd13;
    reg [3:0]  st /* verilator public */;
    reg [SLOT-1:0] st_inval_cnt;   // counter of the post-reset invalidation (1/cycle)
    reg [6:0] nbody_w;      // remaining body words to consume
    reg [1:0]  hrem;        // remaining header words after w0 (DW=32: 1)
    reg emit_ok;            // the applied operation is emitted (it was not an anomaly/error)
    reg do_uadd;            // this cycle's U replace needs ST_UADD
    // combinational handshake (fase3-uram iter 4, version B): accepts input
    // in ALL states except the post-reset invalidation and the swap. The
    // in-flight message's tail (WAIT_PROBE/APPLY/LV2/LV3/EMIT/UADD) receives
    // the NEXT message's words into a double buffer nx_*: the level pipeline
    // overlaps the feed instead of stalling it. The swap is a dedicated
    // 1-cycle state (tready=0): a swap is never decided over an nx freshly
    // written in the same cycle (1-cycle race, finding iter 4). When nx_done
    // (body of the NEXT message COMPLETE) the input is cut until the swap:
    // never more than one message in the buffer (body over-fill) nor a w0
    // landing on a complete body. ST_TS/ST_BODY keep tready=1 even with
    // nx_done: the IN-FLIGHT message still needs its stream — cutting there
    // would be a deadlock.
    assign s_axis_tready = (st != ST_INVAL) && (st != ST_SWAP) &&
                           (!nx_done || st == ST_TS || st == ST_BODY);

    reg [7:0]  m_type;
    reg [15:0] m_locate;
    reg [7:0]  m_len;
    reg [31:0] m_idx;
    reg [3:0]  bi;
    reg [DW-1:0] body_acc[0:15];   // 16 words cover the max body at DW=32

    // ---------------------------------------------------------------
    // next-message receiver (fase3-uram iter 4, version B): while the
    // in-flight message's tail processes (WAIT_PROBE/APPLY/LV2/LV3/EMIT_A/
    // EMIT_B/EMIT_C/UADD), the next message's words accumulate here (double
    // buffer) and the swap into the in-flight message's registers happens at
    // the end of the tail (ST_EMIT_C or the ST_APPLY discard). Mirror of
    // W0/TS/BODY.
    // ---------------------------------------------------------------
    reg        nx_active;          // a next message is being received
    reg        nx_done;            // body of the next message COMPLETE
    reg [1:0]  nx_st;              // 0=w0 pending, 1=w1, 2=body
    reg [7:0]  nx_type;
    reg [15:0] nx_locate;
    reg [7:0]  nx_len;
    reg [31:0] nx_idx;
    reg [1:0]  nx_hrem;
    reg [3:0]  nx_bi;
    reg [6:0]  nx_nbody_w;
    reg        nx_bad_sym;
    reg [4:0]  nx_loc_idx;
    reg [DW-1:0] nx_body_acc[0:15];

    // ---------------------------------------------------------------
    // order table in URAM (fase3-uram): single array of NSLOT x OW bits
    // (65.536 x 86 ≈ 20 URAM of the XCKU3P). NO content reset (inference
    // pattern); the post-reset invalidation runs in ST_INVAL.
    // Entry: {valid[0], ref[REFW:1], side[REFW+1], price[REFW+PXW+1:REFW+2],
    // qty[OW-1:OW-QW]} — REFW=20 in the K<=20 configs (86 bits), REFW=K=64
    // in the real-feed config (130 bits, 2 columns of 72 bits per bank)
//    ram_style="ultra": forces URAM inference at elaboration. The real
//    inference blocker was the write via task (bisect 2026-08-18); the
//    attribute pins the memory family and avoids the pathological
//    optimization pass over 5,64 M flops.
//    ---------------------------------------------------------------
    (* ram_style = "ultra" *)
    reg [OW-1:0] o_mem [NSLOT-1:0];
    // probe read port (registered: rd_data <= o_mem[rd_addr])
    reg [SLOT-1:0] rd_addr /* verilator public */;
    reg [OW-1:0]  rd_data /* verilator public */;

    // entry access (each accessor receives ONLY its field: the valid bit is
    // read directly with rd_data[0])
    function automatic logic [REFW-1:0] e_ref(input [REFW-1:0] e);
        e_ref = e;
    endfunction
    function automatic logic e_side(input e);
        e_side = e;
    endfunction
    function automatic logic [PXW-1:0] e_price(input [PXW-1:0] e);
        e_price = e;
    endfunction
    function automatic logic [QW-1:0] e_qty(input [QW-1:0] e);
        e_qty = e;
    endfunction
    function automatic logic [OW-1:0] entry_new(input [K-1:0] r,
                                                input        side,
                                                input [PXW-1:0] px,
                                                input [QW-1:0]  q);
        entry_new = {q, px, side, REFW'(r), 1'b1};
    endfunction

// table write: there is NO mem_wr task — writing the array via task broke the
    // URAM inference (Synth 8-7186, bisect 2026-08-18: the direct pattern
    // infers 32 URAM288, the via-task pattern does not). Each path computes
    // wr_en/wr_addr/wr_data with blocking assignments and the always_ff emits
    // a SINGLE statement at the end (one driver, max 1 write per cycle; the
    // probe NEVER reads during ST_APPLY/ST_UADD — 1R+1W URAM without collision).
    reg wr_en;
    reg [SLOT-1:0] wr_addr;
    reg [OW-1:0] wr_data;

    // ---------------------------------------------------------------
    // probe engine (serialized probe + prefetch, fase3-uram).
    // Runs: old (the message's order_ref) and new (the U replace's newref). A
    // run walks h..h+PROBE-1 at 1 slot/cycle with REGISTERED reads:
    //   T0   start (rd_addr = h, WARM)
    //   T1   rd_data = mem[h]; rd_addr = h+1 (WALK)
    //   T2.. evaluates rd_data (slot h+i-1); continues or ends
    // The run ends on finding the ref (found) or exhausting the PROBE slots
    // (not found; full if the path had no free slot). Tombstones (valid=0)
    // do NOT cut the walk (phase-3 semantics: a ref may live past a
    // delete). Results in registers: pr_found/pr_slot/pr_entry (the whole
    // entry read), pr_empty_found/pr_empty (first hole),
    // pr_full.
    // ---------------------------------------------------------------
    localparam PR_IDLE = 2'd0, PR_WARM = 2'd1, PR_WALK = 2'd2;
    reg [1:0]  pr_phase /* verilator public */;
    reg        pr_pending_old /* verilator public */;
    reg        pr_pending_new /* verilator public */;
    reg [K-1:0] pr_oref;
    reg [K-1:0] pr_newref;
    reg        pr_need_empty;      // the old run also seeks the first hole (A/F)
    reg [SLOT-1:0] pr_base;
    reg [REFW-1:0] pr_target;
    reg [15:0] pr_i;               // step 0..PROBE-1 of the slot under evaluation
    reg        pr_rec_empty;
    reg        pr_is_old;          // identity of the run in flight (output latch)
    // working registers of the run in flight (conditions of the pass)
    reg        w_empty_found;
    // LATCHED results of the OLD run (the message's order_ref): consumed by
    // apply_one for A/F/E/C/X/D and for the delete half of the U
    reg        pr_found /* verilator public */;
    reg [SLOT-1:0] pr_slot /* verilator public */;
    reg [OW-1:0]  pr_entry;
    reg        pr_empty_found /* verilator public */;
    reg [SLOT-1:0] pr_empty /* verilator public */;
    reg        pr_full;
    // LATCHED results of the NEW run (the replace's newref): capacity check
    // and the U's insert slot. The two runs run IN SERIES and finish BEFORE
    // ST_APPLY: the U is atomic — the table is read pre-apply and the
    // original survives if the insert does not fit (finding G5)
    reg        pr_new_found;
    reg [SLOT-1:0] pr_new_empty;
    reg        pr_new_full;

    // ---------------------------------------------------------------
    // run accounting (fase3-uram iter 4): the probe is single-buffer and
    // in-order (runs are served in arming order). Each message that reads the
    // table anchors the STARTED-runs counter when its body starts
    // (cur_anchor_started) and waits in ST_WAIT_PROBE until
    //   (pr_runs_started - cur_anchor_started) >= cur_runs_needed  &&  !pr_active
    // Thus the NEXT message's pending/run (already received in the tail)
    // neither blocks nor overwrites the in-flight message's results (finding
    // of the iter-4 analysis: the naive !pending&&!active condition does not distinguish).
    // ---------------------------------------------------------------
    reg [15:0] pr_runs_started;    // runs launched by the probe (total)
    reg [15:0] cur_anchor_started; // pr_runs_started when the body starts
    reg [1:0]  cur_runs_needed;    // runs of the in-flight message (1; 2 if U; 0 if no read)
    reg        pr_pause;           // 1-cycle pause after ST_APPLY/ST_UADD

    wire pr_active = (pr_phase != PR_IDLE);
    // iter 4: the probe neither starts nor advances while the FSM writes the
    // table (ST_APPLY/ST_UADD): (a) the start is deferred so apply_one reads
    // the in-flight message's run results BEFORE the next message's run
    // overwrites them (the probe is single-buffer); (b) an in-flight run is
    // PAUSED one cycle so the registered read never collides in the same
    // phase with the apply's write (1R+1W URAM, registered pattern).
    wire engine_hold = (st == ST_APPLY) || (st == ST_UADD);
    wire pr_start_old = pr_pending_old && !pr_active && !engine_hold;
    wire pr_start_new = pr_pending_new && !pr_active && !pr_pending_old && !engine_hold;

    // types that read the table (prefetch in ST_BODY)
    function automatic logic lt(input [7:0] t);
        lt = (t == 8'h41) || (t == 8'h46) || (t == 8'h45) || (t == 8'h43) ||
             (t == 8'h58) || (t == 8'h44) || (t == 8'h55);
    endfunction

    // the FSM decides the ST_BODY exit with the cycle's arming COMBINATION:
    // the arming is NB (invisible until the edge) and no message can escape
    // to ST_APPLY with a probe in flight or about to be armed
    wire arm_old_this = (DW == 32) ? (bi == 4'd1 && lt(m_type))
                                   : (bi == 4'd0 && lt(m_type));
    wire arm_new_this = (DW == 32) ? (bi == 4'd3 && m_type == 8'h55)
                                   : (bi == 4'd1 && m_type == 8'h55);
    wire probe_inflight = pr_pending_old || pr_pending_new || pr_active ||
                          arm_old_this || arm_new_this;

    // levels: [side*P + slot] = price, qty (best first)
    reg [PXW-1:0] lv_price [NSYM*2*P-1:0];
    reg [QW-1:0]  lv_qty   [NSYM*2*P-1:0];

    // ---------------------------------------------------------------
    // level pipeline (fase3-uram iter 3): level_add split into 3 registered
    // stages to close 3,103 ns (blocker B2: the combinational O(P) pass
    // averaged 6-8 ns).
    //   Stage 1 (ST_APPLY/ST_UADD): side capture + per-slot predicates
    //     (eq/zer/stop) + candidate sums — all per slot, unchained.
    //   Stage 2 (ST_LV2): priority decode (found/empty/ins, newq, mode,
    //     error) over the stage-1 registers.
    //   Stage 3 (ST_LV3): materialization (2:1/3:1 muxes per slot) + single
    //     write of lv_price/lv_qty. Phase-3 invariants intact: an empty level
    //     does not exist (the remove sweeps price AND qty), never a stale
    //     price nor a wrapped qty (NONE mode on error).
    // ---------------------------------------------------------------
    localparam LV_MODE_NONE   = 2'd0;
    localparam LV_MODE_UPDATE = 2'd1;
    localparam LV_MODE_INSERT = 2'd2;
    localparam LV_MODE_REMOVE = 2'd3;
    // parameters of the in-flight operation (stage 1)
    reg        lv_en;          // a level operation was launched (stage 1)
    reg        lv_uadd;        // after the 1st op (U's delete) must go to ST_UADD
    reg [PXW-1:0] lv_lprice;
    reg signed [31:0] lv_delta;
    reg [31:0] lv_base;
    reg [PXW-1:0] lv_pr[0:P-1];   // copy of the side (pre-op)
    reg [QW-1:0]  lv_qt[0:P-1];
    reg [P-1:0]  lv_eq;           // lv_qt[i]!=0 && lv_pr[i]==price (found)
    reg [P-1:0]  lv_zer;          // lv_qt[i]==0 (first hole)
    reg [P-1:0]  lv_beat;         // level i is STRICTLY worse than the new
                                  // price (insertion bubble: the new element
                                  // beats it and shifts it down)
    reg signed [32:0] lv_cand_newq[0:P-1];   // qty[i]+delta per slot (parallel)
    // stage-2 decode (registered; stage 3 consumes them 1 cycle late). 32
    // bits to compare against integer indices without WIDTHEXPAND
    reg [31:0] lv2_found, lv2_empty, lv2_ins;
    reg [31:0] lv2_newq;
    reg [1:0]  lv2_mode;
    // decode 2a (iter 8): tree first-hot indices and any flags, registered
    // (the single-cycle full decode was the lv_eq -> lv2_mode path); the
    // priority and the mux live in 2b (decode_lv2b, one cycle later).
    reg [LOGP-1:0] lv2_fnd, lv2_emp, lv2_btx;
    reg            lv2_afnd, lv2_aemp, lv2_abtx;
    // materialization (stage 3): per-mode muxes, then a single write
    reg [PXW-1:0] wp[0:P-1];
    reg [QW-1:0]  wq[0:P-1];

    reg [PXW-1:0] prev_bp [NSYM-1:0], prev_ap [NSYM-1:0];
    reg [QW-1:0]  prev_bq [NSYM-1:0], prev_aq [NSYM-1:0];

    // emission pipeline (iter 7): registered capture of the 2*P levels of the
    // event's symbol (stage A) and the selection results (stage B). The
    // single-cycle combinational emission was the critical path of the
    // 2026-08-18 run (37-41 logic levels, WNS -10,492 ns). sm_cap_* are
    // exposed public for the RTM-01 structural probe (SEC-URAM-01 style).
    reg [PXW-1:0] sm_cap_px [0:2*P-1] /* verilator public */;
    reg [QW-1:0]  sm_cap_qt [0:2*P-1] /* verilator public */;
    // iter 9 + CLO-322-02 split: first non-empty slot per side. Stage A
    // registers caps and non-empty predicates (sm_nza_next/sm_nzb_next);
    // stage B does the tree first_one -> sm_bsel/sm_asel (registered); stage
    // C selects the caps by that REGISTERED index and emits. Splits the
    // m_loc_idx -> mux -> !=0 path (cycle A) from first_one (cycle B) from
    // the cap mux (cycle C), with no extra state. A COMBINATIONAL-index mux
    // in B (first fold) inflated LUT to 161k (> the part's 162,7k) and did not fit.
    reg [LOGP-1:0] sm_bsel, sm_asel /* verilator public */;
    reg [P-1:0] sm_nza_next, sm_nzb_next /* verilator public */;
    reg [2*ND*64-1:0] sm_dacc;

    reg market_open;
    reg [7:0] tstate [NSYM-1:0];   // trading state per symbol (golden: per locate)

// U replace: the "add" half is applied on the next cycle (ST_UADD), because
// two level_add in the same cycle do not see the first one (non-blocking)
reg [K-1:0] u_newref;
reg        u_side;
reg [PXW-1:0] u_price;
reg [QW-1:0]  u_shares;
    reg [SLOT-1:0] u_nidx;      // pre-verified slot of the add half (atomic U)

    // locate -> symbol index mapping (register-on-first-seen)
    reg [15:0] loc_map[NSYM-1:0];
    reg [4:0]  loc_cnt;         // number of registered symbols
    reg [4:0]  m_loc_idx;       // index of the in-flight message's symbol
    reg bad_sym;                // locate outside the subset (SEC-NSYM-01)

    // ---------------------------------------------------------------
    // byte extraction helpers (big-endian)
    // ---------------------------------------------------------------
    function automatic logic [7:0] pbody(input [6:0] b);
        pbody = body_acc[4'(b >> L2B)][(8'(DW-1) - 8'(b & 7'(BYTES-1))*8) -: 8];
    endfunction
    function automatic logic [31:0] b32(input [6:0] b);
        b32 = {pbody(b), pbody(b+1), pbody(b+2), pbody(b+3)};
    endfunction
    function automatic logic [63:0] b64(input [6:0] b);
        b64 = {pbody(b), pbody(b+1), pbody(b+2), pbody(b+3),
               pbody(b+4), pbody(b+5), pbody(b+6), pbody(b+7)};
    endfunction

    // returns the locate's index or 31 if it is not registered (early exit
    // with a flag: assigning ii in the loop body does not converge in
    // Vivado's elaboration — Synth 8-3380)
    function automatic logic [4:0] loc_lookup(input [15:0] l);
        integer ii;
        logic done;
        loc_lookup = 5'd31;
        done = 1'b0;
        for (ii = 0; ii < NSYM && !done; ii = ii + 1) begin
            if (loc_map[ii] == l) begin
                loc_lookup = 5'(ii);
                done = 1'b1;
            end
        end
    endfunction

    // first-hot encoder with lower-index priority, in a log2(P) tree of
    // OR/mux levels (iter 8). any_lvl[k][j] = |v[(j+1)*2^k-1 : j*2^k]; the
    // index is decided from most to least significant bit: at each level, if
    // the left half of the current block is empty, the first 1 lives on the
    // right (bit k = 1). No serial chains: the single-cycle full decode was
    // the 31-level lv_eq -> lv2_mode path of the 2026-08-18 14:11 re-run.
    function automatic logic [LOGP-1:0] first_one(input logic [P-1:0] v);
        logic [P-1:0] any_lvl [LOGP];
        logic [LOGP-1:0] blk;
        integer k, i;
        begin
            any_lvl[0] = v;
            for (k = 0; k < LOGP - 1; k = k + 1)
                for (i = 0; i < (P >> (k + 1)); i = i + 1)
                    any_lvl[k + 1][i] = any_lvl[k][2*i] | any_lvl[k][2*i + 1];
            first_one = {LOGP{1'b0}};
            blk = {LOGP{1'b0}};
            for (k = LOGP - 1; k >= 0; k = k - 1) begin
                if (!any_lvl[k][blk * 2])
                    first_one[k] = 1'b1;
                blk = {blk[LOGP-2:0], first_one[k]};
            end
        end
    endfunction

    // ---------------------------------------------------------------
    // probe engine: advances 1 slot/cycle even while the FSM is receiving the
    // body (prefetch). Lives INSIDE the FSM's always_ff (a single driver: the
    // ST_BODY arming and the start/advance share edge and process)
    // ---------------------------------------------------------------
    // main FSM
    // ---------------------------------------------------------------
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            st <= ST_INVAL;
            for (int i = 0; i < NSYM*2*P; i++) begin
                lv_price[i] <= 0; lv_qty[i] <= 0;
            end
            for (int i = 0; i < NSYM; i++) begin
                prev_bp[i] <= 0; prev_bq[i] <= 0; prev_ap[i] <= 0; prev_aq[i] <= 0;
            end
            // emission pipeline (iter 7)
            for (int i = 0; i < 2*P; i++) begin
                sm_cap_px[i] <= 0; sm_cap_qt[i] <= 0;
            end
            sm_bsel <= 0; sm_asel <= 0;
            sm_nza_next <= 0; sm_nzb_next <= 0;
            sm_dacc <= 0;
            bbo_tvalid <= 1'b0; bbo_locate <= 0; bbo_tdata <= 0; bbo_changed <= 1'b0;
            depth_tvalid <= 1'b0; depth_tdata <= 0;
            cross_events <= 0; anomaly_count <= 0; error <= 1'b0;
            market_open <= 1'b0; u_newref <= 0; u_side <= 0;
            u_price <= 0; u_shares <= 0; u_nidx <= 0;
            for (int i = 0; i < NSYM; i++) tstate[i] <= 8'h00;
            bi <= 0; nbody_w <= 0; hrem <= 2'd1; emit_ok <= 1'b0;
            for (int i = 0; i < NSYM; i++) loc_map[i] <= 16'hffff;
            loc_cnt <= 0; m_loc_idx <= 0; bad_sym <= 1'b0;
            // the URAM is not reset (inference pattern): ST_INVAL invalidates
            // it whole at 1 slot/cycle
            st_inval_cnt <= 0;
            // probe engine state (same edge, a single driver)
            pr_phase <= PR_IDLE;
            pr_pending_old <= 1'b0; pr_pending_new <= 1'b0;
            rd_addr <= 0; rd_data <= 0;
            pr_base <= 0; pr_target <= 0; pr_i <= 0;
            pr_rec_empty <= 1'b0; pr_need_empty <= 1'b0; pr_is_old <= 1'b1;
            w_empty_found <= 1'b0;
            pr_found <= 1'b0; pr_slot <= 0; pr_entry <= 0;
            pr_empty_found <= 1'b0; pr_empty <= 0; pr_full <= 1'b0;
            pr_new_found <= 1'b0; pr_new_empty <= 0; pr_new_full <= 1'b0;
            pr_oref <= 0; pr_newref <= 0;
            // run accounting and nx receiver (fase3-uram iter 4)
            pr_runs_started <= 0; cur_anchor_started <= 0;
            cur_runs_needed <= 2'd0; pr_pause <= 1'b0;
            nx_active <= 1'b0; nx_done <= 1'b0; nx_st <= 2'd0;
            nx_type <= 0; nx_locate <= 0; nx_len <= 0; nx_idx <= 0;
            nx_hrem <= 2'd0; nx_bi <= 0; nx_nbody_w <= 0;
            nx_bad_sym <= 1'b0; nx_loc_idx <= 0;
            for (int i = 0; i < 16; i++) nx_body_acc[i] <= 0;
            // level pipeline (stage 1 + decode + materialization)
            lv_en <= 1'b0; lv_uadd <= 1'b0;
            lv_lprice <= 0; lv_delta <= 32'sd0; lv_base <= 0;
            for (int i = 0; i < P; i++) begin
                lv_pr[i] <= 0; lv_qt[i] <= 0;
                lv_eq[i] <= 1'b0; lv_zer[i] <= 1'b0; lv_beat[i] <= 1'b0;
                lv_cand_newq[i] <= 33'sd0;
                wp[i] <= 0; wq[i] <= 0;
            end
            lv2_found <= 0; lv2_empty <= 0; lv2_ins <= 0;
            lv2_newq <= 32'd0; lv2_mode <= LV_MODE_NONE;
            lv2_fnd <= 0; lv2_emp <= 0; lv2_btx <= 0;
            lv2_afnd <= 1'b0; lv2_aemp <= 1'b0; lv2_abtx <= 1'b0;
        end else begin
            // AXI retention (SEC-BP-01): the BBO/depth pair stays valid until
            // its tready accepts it; the ST_APPLY guard stalls the pipeline
            // while it is pending (no loss nor duplicate)
            bbo_tvalid <= bbo_tvalid && !bbo_tready;
            depth_tvalid <= depth_tvalid && !depth_tready;
            error <= 1'b0;

            // defaults of the table write port: each path may overwrite them
            // with blocking assignments; the single o_mem[wr_addr] <= wr_data
            // statement is emitted at the end of the always_ff
            wr_en = 1'b0;
            wr_addr = 0;
            wr_data = 0;

            // ---- probe engine (serialized probe): advances 1 slot/cycle
            // even while the FSM is receiving the body (prefetch). The read
            // is REGISTERED (rd_data <= o_mem[rd_addr]) — URAM pattern.
            rd_data <= o_mem[rd_addr];
            if (engine_hold) begin
                // the probe does not advance while the FSM writes the table
                // (see wire engine_hold): the pause is marked and this cycle's
                // capture is discarded (it could be stale if the apply wrote
                // the evaluated slot — re-sync on the next cycle)
                pr_pause <= 1'b1;
            end else if (pr_pause) begin
                // re-sync: one cycle without eval after the pause; the pause
                // cycle's capture is never evaluated
                pr_pause <= 1'b0;
            end else if (pr_start_old) begin
                pr_pending_old <= 1'b0;
                pr_runs_started <= pr_runs_started + 1;
                pr_phase <= PR_WARM;
                pr_i <= 16'd0;
                pr_base <= pr_oref[SLOT-1:0];
                pr_target <= REFW'(pr_oref);
                pr_rec_empty <= pr_need_empty;
                pr_is_old <= 1'b1;
                w_empty_found <= 1'b0;
                pr_found <= 1'b0; pr_slot <= 0; pr_entry <= 0;
                pr_empty_found <= 1'b0; pr_empty <= 0; pr_full <= 1'b0;
                rd_addr <= pr_oref[SLOT-1:0];
            end else if (pr_start_new) begin
                pr_pending_new <= 1'b0;
                pr_runs_started <= pr_runs_started + 1;
                pr_phase <= PR_WARM;
                pr_i <= 16'd0;
                pr_base <= pr_newref[SLOT-1:0];
                pr_target <= REFW'(pr_newref);
                pr_rec_empty <= 1'b1;
                pr_is_old <= 1'b0;
                w_empty_found <= 1'b0;
                pr_new_found <= 1'b0; pr_new_empty <= 0; pr_new_full <= 1'b0;
                rd_addr <= pr_newref[SLOT-1:0];
            end else if (pr_phase == PR_WARM) begin
                pr_phase <= PR_WALK;
                rd_addr <= pr_base + 16'd1;
            end else if (pr_phase == PR_WALK) begin
                // evaluates the datum read 1 cycle ago (rd_data); the slot
                // under evaluation is pr_base + pr_i (pr_i before the
                // increment). The results are LATCHED into the in-flight run's
                // set with direct writes (a latch task with NB would read the
                // old value of the working registers: 1-cycle race)
                if (rd_data[0] && (rd_data[REFW:1] == pr_target)) begin
                    if (pr_is_old) begin
                        pr_found <= 1'b1;
                        pr_slot <= pr_base + pr_i;
                        pr_entry <= rd_data;
                    end else begin
                        pr_new_found <= 1'b1;
                    end
                    pr_phase <= PR_IDLE;
                end else begin
                    if (!rd_data[0] && pr_rec_empty && !w_empty_found) begin
                        w_empty_found <= 1'b1;
                        if (pr_is_old) begin
                            pr_empty_found <= 1'b1;
                            pr_empty <= pr_base + pr_i;
                        end else begin
                            pr_new_empty <= pr_base + pr_i;
                        end
                    end
                    if (pr_i == 16'(PROBE-1)) begin
                        // last slot of the path: not found; full if the path
                        // had no hole (insert A/F, U-new). NOTE: the CURRENT
                        // slot's hole is latched in the branch above in this
                        // same cycle (w_empty_found NB); reading w_empty_found
                        // here would see the OLD value — therefore rd_data[0]
                        // (slot occupied) is also required: if the hole is the
                        // terminal slot itself, the empty was already recorded
                        // and it is NOT a full table (race 2026-08-14).
                        if (pr_rec_empty && !w_empty_found && rd_data[0]) begin
                            if (pr_is_old) pr_full <= 1'b1;
                            else pr_new_full <= 1'b1;
                        end
                        pr_phase <= PR_IDLE;
                    end else begin
                        pr_i <= pr_i + 1;
                        // the NEXT slot's addr: pr_i+2 (pr_i is the slot under evaluation; the
                        // WARM transition already emitted base+1 and pr_i+1 would re-emit the
                        // current slot: a 1-cycle offset between the datum read and the slot
                        // evaluated)
                        rd_addr <= pr_base + (pr_i + 2);
                    end
                end
            end

            case (st)
                ST_INVAL: begin
                    // post-reset invalidation: the 65.536 slots to valid=0
                    // (never a global array reset: it would kill the URAM)
                    wr_en = 1'b1;
                    wr_addr = st_inval_cnt;
                    wr_data = {OW{1'b0}};
                    if (st_inval_cnt == NSLOT-1) st <= ST_W0;
                    else st_inval_cnt <= st_inval_cnt + 1;
                end
                ST_W0: begin
                    if (s_axis_tvalid) begin
                        // w0 fields: {type, locate, len, idx} at 64 bits; at
                        // 32 bits the idx travels in its own word (w1)
                        m_type   <= s_axis_tdata[DW-1 -: 8];
                        m_locate <= s_axis_tdata[DW-9 -: 16];
                        m_len    <= s_axis_tdata[DW-25 -: 8];
                        // symbol mapping: known index or register in order (register-on-first-seen).
                        // loc_lookup reads loc_map/loc_cnt from the previous state; the
                        // registration is done with <= on the edge.
                        bad_sym <= 1'b0;
                        if (loc_lookup(s_axis_tdata[DW-9 -: 16]) == 5'd31 &&
                            loc_cnt < NSYM) begin
                            loc_map[loc_cnt] <= s_axis_tdata[DW-9 -: 16];
                            loc_cnt <= loc_cnt + 1;
                            m_loc_idx <= loc_cnt;
                        end else if (loc_lookup(s_axis_tdata[DW-9 -: 16]) == 5'd31) begin
                            // symbol outside the subset (NSYM registered): error pulse
                            // and message discarded without touching the book
                            // (never an OOB index; finding F1 of the grade)
                            bad_sym <= 1'b1;
                            error <= 1'b1;
                            m_loc_idx <= 0;
                        end else begin
                            m_loc_idx <= loc_lookup(s_axis_tdata[DW-9 -: 16]);
                        end
                        // body words = ceil((len-11)/BYTES)
                        nbody_w <= 7'(((8'(s_axis_tdata[DW-25 -: 8]) - 8'd11) +
                                       8'(BYTES-1)) >> L2B);
                        // remaining header after w0: DW=64 no extra word;
                        // DW=32 a single one (w1=msg_idx) — the Annex-A ts
                        // words were trimmed (fase3-uram criterion 1)
                        hrem <= 2'd1;
                        bi <= 0;
                        st <= ST_TS;
                    end
                end
                ST_TS: begin
                    // consumes the remaining header word (DW=32: w1=idx, the
                    // only rest after the Annex-A trim — without ts)
                    if (s_axis_tvalid) begin
                        if (DW == 32) m_idx <= s_axis_tdata[31:0];
                        if (hrem == 2'd1) begin
                            st <= ST_BODY;
                        end else hrem <= hrem - 1;
                    end
                end
                ST_BODY: begin
                    if (s_axis_tvalid) begin
                        body_acc[bi] <= s_axis_tdata;
                        // PREFETCH (fase3-uram): the in-flight message's hash
                        // group is read during body reception. The order_ref
                        // (bytes 0-7) completes with the 2nd word at DW=32 (or
                        // the 1st at DW=64); the U's newref with the 4th (or
                        // the 2nd). The probe engine picks them up on start.
                        if (DW == 32) begin
                            if (bi == 4'd1 && lt(m_type)) begin
                                pr_pending_old <= 1'b1;
                                pr_oref <= K'({body_acc[0], s_axis_tdata});
                                pr_need_empty <= (m_type == 8'h41 ||
                                                  m_type == 8'h46);
                                // in-flight message's anchor IN THE ARMING CYCLE
                                // (iter 4): the runs launched before this cycle
                                // (previous message, tail still in flight) do not
                                // count toward its wait. Setting it at body start
                                // would inflate the counter with those runs and
                                // ST_WAIT_PROBE would exit with stale results
                                // (analysis finding)
                                cur_anchor_started <= pr_runs_started;
                                cur_runs_needed <= (lt(m_type) ? 2'd1 : 2'd0) +
                                                   (m_type == 8'h55 ? 2'd1 : 2'd0);
                            end
                            if (bi == 4'd3 && m_type == 8'h55) begin
                                pr_pending_new <= 1'b1;
                                pr_newref <= K'({body_acc[2], s_axis_tdata});
                            end
                        end else begin
                            if (bi == 4'd0 && lt(m_type)) begin
                                pr_pending_old <= 1'b1;
                                pr_oref <= K'(s_axis_tdata);
                                pr_need_empty <= (m_type == 8'h41 ||
                                                  m_type == 8'h46);
                                cur_anchor_started <= pr_runs_started;
                                cur_runs_needed <= (lt(m_type) ? 2'd1 : 2'd0) +
                                                   (m_type == 8'h55 ? 2'd1 : 2'd0);
                            end
                            if (bi == 4'd1 && m_type == 8'h55) begin
                                pr_pending_new <= 1'b1;
                                pr_newref <= K'(s_axis_tdata);
                            end
                        end
                        if (s_axis_tlast) begin
                            // end of burst (body): the prefetch may not have
                            // finished (short body) -> ST_WAIT_PROBE.
                            // probe_inflight includes THIS cycle's arming (NB
                            // not visible): no message escapes to ST_APPLY
                            // with a probe in flight or about to be armed
                            st <= probe_inflight ? ST_WAIT_PROBE : ST_APPLY;
                        end else if (nbody_w <= 1) begin
                            st <= probe_inflight ? ST_WAIT_PROBE : ST_APPLY;
                        end else begin
                            bi <= bi + 1;
                            nbody_w <= nbody_w - 1;
                        end
                    end
                end
                ST_WAIT_PROBE: begin
                    // in-flight message's tail: accepts the next message
                    // (never with nx_done: the body is already complete in the
                    // buffer and one more word would be an M+2 w0 — over-fill)
                    if (s_axis_tvalid && !nx_done) nx_recv();
                    // the in-flight message's probe finished: the runs
                    // launched from the ANCHOR (its probe's arming cycle) are
                    // cur_runs_needed and the engine is idle. The NEXT
                    // message's pending/run does not count (the probe starts
                    // its run in order, when it frees up)
                    if ((pr_runs_started - cur_anchor_started) >= 16'(cur_runs_needed) &&
                        !pr_active) st <= ST_APPLY;
                end
                ST_APPLY: begin
                    // in-flight message's tail: accepts the next message
                    // (never with nx_done: double-buffer over-fill)
                    if (s_axis_tvalid && !nx_done) nx_recv();
                    // iter 9: the BBO/depth pair's acceptance guard lives in ST_EMIT_C — the
                    // tail (apply/swap) no longer waits on the pin's tready: the tready ->
                    // URAM write path was the critical one of the iter-8 re-run (depth_tready
                    // -> CAS_IN_DIN_B)
if (m_len < 8'd11) error <= 1'b1;   // invalid body
                    if (m_idx == 32'hffffffff) error <= 1'b1;  // idx sanity
                    if (bad_sym) begin
                        // message of a symbol outside the subset: discarded
                        do_uadd <= 1'b0;
                        // atomic swap (iter 4): with a next-message word on
                        // the bus (nx not yet complete), it is consumed in nx
                        // (nx_recv was already called above) and the swap is
                        // deferred one cycle (ST_SWAP) — deciding the swap in
                        // this same cycle over a freshly written nx (NB
                        // invisible) was the race that sent the FSM to ST_W0
                        // and lost the word (finding iter 4)
                        if (s_axis_tvalid && !nx_done) st <= ST_SWAP;
                        else swap_next(st);
                    end else begin
                        apply_one(do_uadd, lv_en);
                        lv_uadd <= do_uadd;   // the U asks for the add half after the 1st op
                        if (do_uadd || lv_en) st <= ST_LV2;
                        else if (m_type == 8'h41 || m_type == 8'h46 || m_type == 8'h45 ||
                                 m_type == 8'h43 || m_type == 8'h58 || m_type == 8'h44 ||
                                 m_type == 8'h55) st <= ST_EMIT_A;
                        else if (s_axis_tvalid && !nx_done) st <= ST_SWAP;
                        else swap_next(st);
                    end
                end
                ST_LV2: begin
                    // stage 2a (iter 8): tree find-first over the
                    // registers captured in ST_APPLY/ST_UADD (visible
                    // here, one cycle after the launch); the indices and
                    // the flags are registered and 2b combines them one
                    // cycle later
                    if (s_axis_tvalid && !nx_done) nx_recv();
                    decode_lv2a();
                    st <= ST_LV2B;
                end
                ST_LV2B: begin
                    // stage 2b (iter 8): priority + mux over the indices
                    // resolved by 2a; the result is registered and stage 3
                    // consumes it one cycle later
                    if (s_axis_tvalid && !nx_done) nx_recv();
                    decode_lv2b();
                    st <= ST_LV3;
                end
                ST_LV3: begin
                    // stage 3: materializes the new list per the decode and
                    // writes it in one shot (single write of the side)
                    if (s_axis_tvalid && !nx_done) nx_recv();
                    materialize_write();
                    st <= lv_uadd ? ST_UADD : ST_EMIT_A;
                end
                ST_UADD: begin
                    // replace's add half: the second level operation sees the
                    // previous cycle's state (the delete already applied in
                    // the prior ST_LV3)
                    if (s_axis_tvalid && !nx_done) nx_recv();
                    launch_lv(u_side, u_price, u_shares);
                    wr_en = 1'b1;
                    wr_addr = u_nidx;
                    wr_data = entry_new(u_newref, u_side, u_price, u_shares);
                    lv_uadd <= 1'b0;
                    st <= ST_LV2;
                end
                ST_EMIT_A: begin
                    // stage A of the emission pipeline (iter 7 + CLO-322-02
                    // split): registered capture of the 2*P levels of the
                    // event's symbol and non-empty predicates — only the
                    // m_loc_idx mux. first_one + select live in B.
                    if (s_axis_tvalid && !nx_done) nx_recv();
                    if (emit_ok) capture_emit_a();
                    st <= ST_EMIT_B;
                end
                ST_EMIT_B: begin
                    // stage B (iter 7): best level per side + changed + depth
                    // over the registered capture; the handshake is stage C
                    if (s_axis_tvalid && !nx_done) nx_recv();
                    if (emit_ok) select_emit_b();
                    st <= ST_EMIT_C;
                end
                ST_EMIT_C: begin
                    // stage C (iter 7): emission with the semantics of the
                    // phase-3 ST_EMIT — atomic BBO/depth pair with AXI
                    // retention. iter 9: the acceptance guard lives here and
                    // looks ONLY at the tvalid lines (the pair is emitted with
                    // the bus empty; the tail advances without waiting on the
                    // pin). The tready takes part in NO advance decision: the
                    // pin -> URAM write path of the ST_APPLY guard was the
                    // critical one of the iter-8 re-run, and a registered
                    // tready (deferred acceptance) would duplicate the pair
                    // for the consumer if it raises tready one cycle after the
                    // emission (analysis in the iter-9 addendum). The
                    // retention of line 501 keeps using the pin's direct tready: no loss nor duplicate (SEC-BP-01).
                    emit_c_stage();
                end
                ST_SWAP: begin
                    // double-buffer swap in a dedicated state: tready=0 (the
                    // bus freezes) and nx_* is stable — the previous cycle's
                    // writes are already visible. Nothing is received here.
                    swap_next(st);
                end
                default: st <= ST_W0;
            endcase

            // SINGLE table-write statement (URAM inference pattern — see the
            // declaration of wr_en/wr_addr/wr_data)
            if (wr_en) o_mem[wr_addr] <= wr_data;
        end
    end

    // ---------------------------------------------------------------
    // next-message receiver (fase3-uram iter 4): consumes the words arriving
    // during the in-flight message's tail. Mirror of W0/TS/BODY (same field
    // semantics, probe arming and symbol registration) but over nx_*; a
    // single message in flight (1-element double buffer).
    // ---------------------------------------------------------------
    task automatic nx_recv;
        begin
            if (!nx_active) begin
                nx_active <= 1'b1;
                nx_st    <= 2'd1;
                nx_done  <= 1'b0;
                nx_bi    <= 4'd0;
                nx_hrem  <= 2'd1;
                nx_type   <= s_axis_tdata[DW-1 -: 8];
                nx_locate <= s_axis_tdata[DW-9 -: 16];
                nx_len    <= s_axis_tdata[DW-25 -: 8];
                nx_nbody_w <= 7'(((8'(s_axis_tdata[DW-25 -: 8]) - 8'd11) +
                                  8'(BYTES-1)) >> L2B);
                nx_bad_sym <= 1'b0;
                if (loc_lookup(s_axis_tdata[DW-9 -: 16]) == 5'd31 &&
                    loc_cnt < NSYM) begin
                    loc_map[loc_cnt] <= s_axis_tdata[DW-9 -: 16];
                    loc_cnt <= loc_cnt + 1;
                    nx_loc_idx <= loc_cnt;
                end else if (loc_lookup(s_axis_tdata[DW-9 -: 16]) == 5'd31) begin
                    // symbol outside the subset (SEC-NSYM-01): error pulse and
                    // discard at its ST_APPLY (same semantics as ST_W0)
                    nx_bad_sym <= 1'b1;
                    error <= 1'b1;
                    nx_loc_idx <= 5'd0;
                end else begin
                    nx_loc_idx <= loc_lookup(s_axis_tdata[DW-9 -: 16]);
                end
            end else if (nx_st == 2'd1) begin
                // next message's w1 (idx at DW=32; at DW=64 the idx traveled
                // in w0 and this ts word is not consumed)
                if (DW == 32) nx_idx <= s_axis_tdata[31:0];
                nx_st <= 2'd2;
            end else begin
                // body (nx_st == 2): ONLY accumulation in the double buffer.
                // The next message's probe arming does NOT happen here but in
                // the swap (swap_next): the probe is single-buffer in-order
                // and an arming during the in-flight message's tail would
                // invert the priority (M2's old run would block an M1's new
                // run in ST_WAIT_PROBE) and corrupt the U — finding iter 4
                nx_body_acc[nx_bi] <= s_axis_tdata;
                if (s_axis_tlast) begin
                    nx_done <= 1'b1;
                end else if (nx_nbody_w <= 1) begin
                    nx_done <= 1'b1;
                end else begin
                    nx_bi <= nx_bi + 1;
                    nx_nbody_w <= nx_nbody_w - 1;
                end
            end
        end
    endtask

    // ---------------------------------------------------------------
    // swap: the next message (nx_*) becomes the in-flight message when the
    // previous one's tail finishes (ST_EMIT_C, the ST_APPLY discard or, with
    // a word on the bus, the dedicated ST_SWAP state — never in the same
    // cycle as an nx write). Start state per what was received:
    //   nothing  -> ST_W0   (the tail overlapped no word)
    //   only w0  -> ST_TS   (half header: w1 missing)
    //   body     -> ST_BODY (resumes at the word after nx_bi)
    //   complete -> WAIT_PROBE/APPLY per the new message's probe
    // The incoming message's probe ARMING happens HERE (from nx_body_acc, per
    // the words already received), not in nx_recv: the probe is single-buffer
    // in-order and a message's pendings are only born when it is the
    // in-flight message (no priority inversion between M1's new run and M2's
    // old run). The message's anchor is set in this same cycle
    // (pr_runs_started prior to the launch of ITS runs).
    // ---------------------------------------------------------------
    task automatic swap_next(output reg [3:0] nxt);
        reg will_arm_old, will_arm_new, will_probe;
        begin
            // probe ARMING ONLY with the complete body words it consumes:
            // DW=32 old uses words 0-1, new words 2-3; DW=64 old uses word 0,
            // new word 1. NOTE: the last body word does NOT increment nx_bi
            // (nx_recv sets nx_done without counting) — a complete message
            // ends with nx_bi = nwords-1 and ALL its words valid; a
            // half-truncated message leaves nx_body_acc[nx_bi] stale from the
            // previous message. Hence the validity is nx_done || nx_bi >=
            // words_needed (amendment 16: the CLO-322-02 split cut a D at
            // nx_bi=1 without completing and the probe looked up a corrupt
            // oref -> pr_found=0 -> anomaly). The deferred arming falls into
            // ST_BODY with valid words from the bus.
            will_arm_old = (DW == 32) ? ((nx_done || nx_bi >= 4'd2) && lt(nx_type))
                                      : ((nx_done || nx_bi >= 4'd1) && lt(nx_type));
            will_arm_new = (DW == 32) ? ((nx_done && nx_bi >= 4'd3) ||
                                         nx_bi >= 4'd4) && (nx_type == 8'h55)
                                      : ((nx_done && nx_bi >= 4'd1) ||
                                         nx_bi >= 4'd2) && (nx_type == 8'h55);
            // the incoming message's probe will be in flight: previous pendings, an
            // active run or THIS swap's arming (the swap's pendings are NB:
            // probe_inflight would see them 1 cycle late — therefore it is computed
            // here explicitly and not with the old message's m_type/bi wire)
            will_probe = pr_pending_old || pr_pending_new || pr_active ||
                         will_arm_old || will_arm_new;
            if (!nx_active) begin
                nxt = ST_W0;
            end else begin
                m_type   <= nx_type;
                m_locate <= nx_locate;
                m_len    <= nx_len;
                m_idx    <= nx_idx;
                hrem     <= nx_hrem;
                bad_sym  <= nx_bad_sym;
                m_loc_idx <= nx_loc_idx;
                for (int i = 0; i < 16; i++)
                    body_acc[i] <= nx_body_acc[i];
                if (nx_done || will_arm_old || will_arm_new) begin
                    // arming of the incoming message's probe in the swap cycle
                    // (nx_body_acc is already stable): the refs are armed with
                    // the words received during the previous message's tail
                    if (will_arm_old) begin
                        pr_pending_old <= 1'b1;
                        if (DW == 32)
                            pr_oref <= K'({nx_body_acc[0], nx_body_acc[1]});
                        else
                            pr_oref <= K'(nx_body_acc[0]);
                        pr_need_empty <= (nx_type == 8'h41 || nx_type == 8'h46);
                    end
                    if (will_arm_new) begin
                        pr_pending_new <= 1'b1;
                        if (DW == 32)
                            pr_newref <= K'({nx_body_acc[2], nx_body_acc[3]});
                        else
                            pr_newref <= K'(nx_body_acc[1]);
                    end
                    // in-flight message's anchor in the arming cycle: the
                    // PREVIOUS message's already-launched runs (overlapped
                    // tail) do not count toward this message's wait
                    cur_anchor_started <= pr_runs_started;
                    cur_runs_needed <= (lt(nx_type) ? 2'd1 : 2'd0) +
                                       (nx_type == 8'h55 ? 2'd1 : 2'd0);
                end
                if (nx_done) begin
                    nxt = will_probe ? ST_WAIT_PROBE : ST_APPLY;
                end else if (nx_st == 2'd1) begin
                    // half header: ST_TS consumes w1 (idx) and the body
                    // continues from zero (bi/nbody_w of the WHOLE message)
                    bi <= 0;
                    nbody_w <= nx_nbody_w;
                    nxt = ST_TS;
                end else if (nx_st == 2'd2) begin
                    // the body already consumed words 0..nx_bi-1: nx_bi IS
                    // the index of the NEXT word (counter of consumed ones)
                    // and nx_nbody_w the remaining ones — resuming is copying
                    // BOTH without adjustments. The previous version added 1
                    // to bi (wrote the last body word at bi+1, leaving
                    // body_acc[bi] stale — corrupted price in the tail: 140000
                    // -> 140016) and subtracted nx_bi from nbody_w (ended the
                    // body early) — finding iter 4, trace INV-B32-03
                    bi <= nx_bi;
                    nbody_w <= nx_nbody_w;
                    nxt = ST_BODY;
                end else begin
                    nxt = ST_W0;
                end
                nx_active <= 1'b0;
                nx_done <= 1'b0;
                nx_st <= 2'd0;
                nx_bi <= 4'd0;
            end
        end
    endtask

    // ---------------------------------------------------------------
    // level pipeline (fase3-uram iter 3). launch_lv = stage 1: captures the
    // in-flight side (lv_pr/lv_qt) and computes per slot the predicates
    // (lv_eq/lv_zer/lv_beat) and the candidate sums (lv_cand_newq) — short
    // per-slot paths, without chaining the O(P) pass. Called in ST_APPLY (the
    // A/F/E/C/X/D/U operations) and in ST_UADD (the replace's add half).
    // ---------------------------------------------------------------
    task automatic launch_lv;
        input        ask;
        input [PXW-1:0] price;
        input signed [31:0] delta;
        integer i;
        integer base;
        begin
            base = m_loc_idx*2*P + (ask ? P : 0);
            lv_lprice <= price;
            lv_delta <= delta;
            lv_base <= base;
            for (i = 0; i < P; i = i + 1) begin
                lv_pr[i] <= lv_price[base+i];
                lv_qt[i] <= lv_qty[base+i];
                lv_eq[i] <= (lv_qty[base+i] != 0) && (lv_price[base+i] == price);
                lv_zer[i] <= (lv_qty[base+i] == 0);
                lv_beat[i] <= (lv_qty[base+i] != 0) &&
                              (ask ? (lv_price[base+i] > price)
                                   : (lv_price[base+i] < price));
                lv_cand_newq[i] <= $signed(33'(lv_qty[base+i])) + $signed(33'(delta));
            end
        end
    endtask

    // ---------------------------------------------------------------
    // stage 3: materializes the new list per the stage-2 decode and writes it
    // in one shot. Semantics identical to the phase-3 O(P) pass:
    //   REMOVE -> left sweep (the found hole is compacted)
    //   INSERT -> the new element enters at lv2_ins (insertion bubble) and
    //             [lv2_ins..empty-1] shifts right
    //   UPDATE -> only the qty of lv2_found changes
    //   NONE   -> copy (errors: overflow, reduce over an absent level, qty
    //             that wraps — never a stale price nor a phantom)
    // ---------------------------------------------------------------
    task automatic materialize_write;
        integer i;
        begin
            for (i = 0; i < P; i = i + 1) begin
                if (lv2_mode == LV_MODE_REMOVE) begin
                    wp[i] = (i < lv2_found) ? lv_pr[i]
                          : ((i < P-1) ? lv_pr[i+1] : PXW'(0));
                    wq[i] = (i < lv2_found) ? lv_qt[i]
                          : ((i < P-1) ? lv_qt[i+1] : QW'(0));
                end else if (lv2_mode == LV_MODE_INSERT) begin
                    wp[i] = (i <= lv2_empty) ? ((i < lv2_ins) ? lv_pr[i]
                          : ((i == lv2_ins) ? lv_lprice : lv_pr[i-1])) : lv_pr[i];
                    wq[i] = (i <= lv2_empty) ? ((i < lv2_ins) ? lv_qt[i]
                          : ((i == lv2_ins) ? QW'(lv_delta[31:0]) : lv_qt[i-1]))
                          : lv_qt[i];
                end else if (lv2_mode == LV_MODE_UPDATE) begin
                    wp[i] = lv_pr[i];
                    wq[i] = (i == lv2_found) ? QW'(lv2_newq[31:0]) : lv_qt[i];
                end else begin
                    wp[i] = lv_pr[i];
                    wq[i] = lv_qt[i];
                end
            end
            for (i = 0; i < P; i = i + 1) begin
                lv_price[lv_base+i] <= wp[i];
                lv_qty[lv_base+i]   <= wq[i];
            end
        end
    endtask

    // ---------------------------------------------------------------
    // stage 2a of the pipeline (iter 8): per-side find-first with tree
    // encoders (first_one, log2(P) levels) over the stage-1 predicates. The
    // single-cycle full decode (serial chains + mux + priority) was the
    // 31-level lv_eq -> lv2_mode path of the 2026-08-18 14:11 re-run. Only
    // the indices and the any flags are registered; the condition priority
    // and the mux live in 2b (decode_lv2b, one cycle later).
    // ---------------------------------------------------------------
    task automatic decode_lv2a;
        begin
            lv2_fnd  <= first_one(lv_eq);
            lv2_emp  <= first_one(lv_zer);
            lv2_btx  <= first_one(lv_beat);
            lv2_afnd <= |lv_eq;
            lv2_aemp <= |lv_zer;
            lv2_abtx <= |lv_beat;
        end
    endtask

    // ---------------------------------------------------------------
    // stage 2b (iter 8): priority decode over the indices already resolved by
    // 2a (O(1) per index: 32:1 mux of lv_cand_newq + conditions). Semantics
    // identical to the phase-3 decode_lv2 (iter 3): found/empty/ins keep the
    // 0xFFFFFFFF value (ex -1) when there is no level and stage 3
    // (materialize_write) behaves the same. The error pulse is shown here
    // (1 cycle, as in phase 3).
    // ---------------------------------------------------------------
    task automatic decode_lv2b;
        reg lverr;
        begin
            lverr = 1'b0;
            lv2_found <= lv2_afnd ? 32'(lv2_fnd) : 32'hFFFFFFFF;
            lv2_empty <= lv2_aemp ? 32'(lv2_emp) : 32'hFFFFFFFF;
            lv2_ins   <= (lv2_abtx ? 32'(lv2_btx) : 32'(lv2_emp));
            if (!lv2_afnd && !lv2_aemp) begin
                // level overflow. With push-out (sequence 11) it is distinguished:
                //   delta>0 better than the worst -> LV_MODE_INSERT: the materialize
                //     (lv2_empty=0xFFFFFFFF) shifts right from lv2_ins and discards
                //     the worst level (the top-P keeps the best-P).
                //   rest (reduce over a level discarded by overflow, or an add worse
                //     than the worst) -> discarded, SEC-OV-01 (never a phantom)
                if (lv_delta[31]) begin
                    lv2_mode <= LV_MODE_NONE;
                    lverr = 1'b1;
                end else if (lv2_abtx) begin
                    lv2_mode <= LV_MODE_INSERT;
                end else begin
                    lv2_mode <= LV_MODE_NONE;
                    lverr = 1'b1;
                end
            end else if (!lv2_afnd && lv_delta[31]) begin
                // reduce over a level that does not exist (an order in the
                // table without a level due to a prior overflow): never a
                // wrapped qty (finding G5)
                lv2_mode <= LV_MODE_NONE;
                lverr = 1'b1;
            end else if (!lv2_afnd) begin
                lv2_mode <= LV_MODE_INSERT;
            end else begin
                lv2_newq <= lv_cand_newq[lv2_fnd][31:0];
                if (lv_cand_newq[lv2_fnd][32]) begin
                    // the qty would wrap 32 bits: discard (never a phantom)
                    lv2_mode <= LV_MODE_NONE;
                    lverr = 1'b1;
                end else if (lv_cand_newq[lv2_fnd] == 0) begin
                    lv2_mode <= LV_MODE_REMOVE;   // an empty level does not exist
                end else begin
                    lv2_mode <= LV_MODE_UPDATE;
                end
            end
            error <= lverr;
        end
    endtask
    task automatic capture_emit_a;
        // stage A of the emission pipeline (iter 7 + CLO-322-02 split):
        // registered capture of the 2*P levels of the event's symbol +
        // per-side non-empty flags. Only a mux indexed by m_loc_idx;
        // first_one + selection/depth live in stage B (select_emit_b). The
        // m_loc_idx -> sm_asel path is split: A registers predicates, B does
        // first_one over registers (no extra state).
        integer i;
        logic [P-1:0] nzb_next, nza_next;
        begin
            for (i = 0; i < P; i = i + 1) begin
                nzb_next[i] = (lv_qty[m_loc_idx*2*P + i] != 0);
                nza_next[i] = (lv_qty[m_loc_idx*2*P + P + i] != 0);
                sm_cap_px[i]    <= lv_price[m_loc_idx*2*P + i];
                sm_cap_qt[i]    <= lv_qty[m_loc_idx*2*P + i];
                sm_cap_px[P+i]  <= lv_price[m_loc_idx*2*P + P + i];
                sm_cap_qt[P+i]  <= lv_qty[m_loc_idx*2*P + P + i];
            end
            sm_nzb_next <= nzb_next;
            sm_nza_next <= nza_next;
        end
    endtask
    task automatic select_emit_b;
        // stage B of the emission pipeline (iter 7 + CLO-322-02 split):
        // first_one over the predicates registered in A -> sm_bsel/sm_asel
        // (registered), and depth. The cap mux by sm_bsel/sm_asel + changed +
        // cross live in C (REGISTERED index: a combinational-index mux in B
        // inflated LUT and did not fit in the part).
        reg [2*ND*64-1:0] dacc;
        integer di;
        begin
            sm_bsel <= first_one(sm_nzb_next);
            sm_asel <= first_one(sm_nza_next);
            // public top-N (criterion 6): ND levels per side of the event's
            // symbol, best first (slot 0 of the list = best), empties at 0.
            // Bus: {bid[ND-1..0], ask[ND-1..0]} MSB->LSB, each level
            // {px[31:0], qty[31:0]} -> depth[639:576] = best bid.
            dacc = 0;
            for (di = 0; di < ND; di = di + 1)
                dacc = {dacc[2*ND*64-65:0],
                        sm_cap_px[di][31:0],
                        sm_cap_qt[di][31:0]};
            for (di = 0; di < ND; di = di + 1)
                dacc = {dacc[2*ND*64-65:0],
                        sm_cap_px[P+di][31:0],
                        sm_cap_qt[P+di][31:0]};
            sm_dacc <= dacc;
        end
    endtask
    task automatic emit_c_stage;
        // full stage C (CLO-322-02 split): cap mux by REGISTERED index +
        // changed + cross (combinational, this cycle) and the output handshake
        // with AXI retention + tail swap. prev_* are updated ONLY in the
        // handshake cycle (once per event).
        reg [PXW-1:0] bp, ap;
        reg [QW-1:0] bq, aq;
        reg changed, xing;
        begin
            bp = sm_cap_px[32'(sm_bsel)]; bq = sm_cap_qt[32'(sm_bsel)];
            ap = sm_cap_px[P + 32'(sm_asel)]; aq = sm_cap_qt[P + 32'(sm_asel)];
            changed = (bp != prev_bp[m_loc_idx]) || (bq != prev_bq[m_loc_idx]) ||
                      (ap != prev_ap[m_loc_idx]) || (aq != prev_aq[m_loc_idx]);
            xing = market_open && tstate[m_loc_idx] == 8'h54 && bp != 0 && ap != 0 && bp >= ap;
            if (emit_ok && !bbo_tvalid && !depth_tvalid) begin
                bbo_locate <= m_locate;
                bbo_tdata  <= {bp[31:0], bq[31:0], ap[31:0], aq[31:0]};
                bbo_changed <= changed;
                bbo_tvalid  <= 1'b1;
                depth_tdata <= sm_dacc;
                depth_tvalid <= 1'b1;
                prev_bp[m_loc_idx] <= bp; prev_bq[m_loc_idx] <= bq;
                prev_ap[m_loc_idx] <= ap; prev_aq[m_loc_idx] <= aq;
                if (xing) cross_events <= cross_events + 1;
                // atomic swap (iter 4): with a next-message word on the bus (nx
                // not yet complete), it is consumed in nx and the swap is deferred
                // one cycle (ST_SWAP); without a word (or with nx complete), the
                // swap is decided now — never over a half-written nx
                if (s_axis_tvalid && !nx_done) begin
                    nx_recv();
                    st <= ST_SWAP;
                end else begin
                    swap_next(st);
                end
            end else if (emit_ok) begin
                // bus busy: the emission waits (nx can keep receiving, as
                // ST_APPLY used to)
                if (s_axis_tvalid && !nx_done) nx_recv();
                st <= ST_EMIT_C;
            end else begin
                // no emission (emitter type but anomaly: do_emit=0): the tail
                // advances anyway and the bus is untouched
                if (s_axis_tvalid && !nx_done) begin
                    nx_recv();
                    st <= ST_SWAP;
                end else begin
                    swap_next(st);
                end
            end
        end
    endtask

    task automatic apply_one(output logic out_uadd, output logic out_lv);
        reg [K-1:0] oref, newref;
        reg [31:0] shares, price;
        reg ask;
        reg [7:0] ev;
        reg do_emit;
        reg [33:0] rest;
        reg [QW-1:0] qty_old;
        begin
            do_emit = 1'b0;
            out_uadd = 1'b0;
            out_lv = 1'b0;
            // the table was already read by the probe (prefetch): the results
            // pr_found/pr_slot/pr_entry/pr_empty/pr_full are from the run
            // that finished BEFORE ST_APPLY (ST_WAIT_PROBE guarantees it)
            case (m_type)
                8'h41, 8'h46: begin
                    oref = K'(b64(0)); ask = (pbody(8) == 8'h53);
                    shares = b32(9); price = b32(21);
                    if (pr_found || shares == 0) begin
                        error <= 1'b1;      // duplicate ref or invalid qty
                    end else if (pr_full) begin
                        error <= 1'b1;      // full table (SEC-HASH-02)
                    end else begin
                        wr_en = 1'b1;
                        wr_addr = pr_empty;
                        wr_data = entry_new(oref, ask, price, shares);
                        launch_lv(ask, price, shares);
                        out_lv = 1'b1;
                        do_emit = 1'b1;
                    end
                end
                8'h45, 8'h43, 8'h58: begin
                    oref = K'(b64(0));
                    if (!pr_found) begin
                        anomaly_count <= anomaly_count + 1;
                    end else begin
                        // reduce from the entry captured by the probe
                        qty_old = e_qty(pr_entry[OW-1:OW-QW]);
                        rest = {2'b0, qty_old} - {2'b0, b32(8)};
                        if (rest[33]) error <= 1'b1;   // execute > remaining
                        else if (rest == 0) begin
                            launch_lv(e_side(pr_entry[REFW+1]), e_price(pr_entry[REFW+PXW+1:REFW+2]),
                                      -$signed(qty_old));
                            wr_en = 1'b1;
                            wr_addr = pr_slot;
                            wr_data = {OW{1'b0}};   // valid=0
                            out_lv = 1'b1;
                            do_emit = 1'b1;
                        end else begin
                            wr_en = 1'b1;
                            wr_addr = pr_slot;
                            wr_data = {rest[31:0], e_price(pr_entry[REFW+PXW+1:REFW+2]),
                                       e_side(pr_entry[REFW+1]), e_ref(pr_entry[REFW:1]),
                                       1'b1};
                            launch_lv(e_side(pr_entry[REFW+1]), e_price(pr_entry[REFW+PXW+1:REFW+2]),
                                      -32'(b32(8)));
                            out_lv = 1'b1;
                            do_emit = 1'b1;
                        end
                    end
                end
                8'h44: begin
                    oref = K'(b64(0));
                    if (!pr_found) anomaly_count <= anomaly_count + 1;
                    else begin
                        launch_lv(e_side(pr_entry[REFW+1]), e_price(pr_entry[REFW+PXW+1:REFW+2]),
                                  -$signed(e_qty(pr_entry[OW-1:OW-QW])));
                        wr_en = 1'b1;
                        wr_addr = pr_slot;
                        wr_data = {OW{1'b0}};
                        out_lv = 1'b1;
                        do_emit = 1'b1;
                    end
                end
                8'h55: begin
                    oref = K'(b64(0)); newref = K'(b64(8));
                    shares = b32(16); price = b32(20);
                    if (!pr_found) anomaly_count <= anomaly_count + 1;
                    else if (shares == 0) error <= 1'b1;
                    else if (pr_new_found) error <= 1'b1;   // duplicate newref
                    else if (pr_new_full) error <= 1'b1;    // atomic U: the
                        // original survives (the capacity was checked in the
                        // probe, BEFORE the delete — finding G5)
                    else begin
                        launch_lv(e_side(pr_entry[REFW+1]), e_price(pr_entry[REFW+PXW+1:REFW+2]),
                                  -$signed(e_qty(pr_entry[OW-1:OW-QW])));
                        wr_en = 1'b1;
                        wr_addr = pr_slot;
                        wr_data = {OW{1'b0}};
                        u_newref <= newref;
                        u_side <= e_side(pr_entry[REFW+1]);
                        u_price <= price;
                        u_shares <= shares;
                        u_nidx <= pr_new_empty;
                        out_lv = 1'b1;
                        do_emit = 1'b1;
                        out_uadd = 1'b1;
                    end
                end
                8'h53: begin
                    ev = pbody(0);
                    if (ev == 8'h51) market_open <= 1'b1;
                    else if (ev == 8'h4d) market_open <= 1'b0;
                end
                8'h48: tstate[m_loc_idx] <= pbody(8);
                default: ;
            endcase
            emit_ok <= do_emit;
        end
    endtask

endmodule
