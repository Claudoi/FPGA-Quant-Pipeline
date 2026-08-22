// itch_parser.sv — ITCH 5.0 parser at line-rate (phase 1, Annex A).
//
// Consumes the MoldUDP64 payload already decapsulated from IP/UDP:
//   session(10B) + seq u64be + count u16be + [len u16be + message]*
// Validates framing and gaps (expected seq = seq_prev + count_prev), aligns
// messages that cross word boundaries and emits over AXI-Stream the
// normalized Annex-A register:
//   word0 = {msg_type[7:0], locate[15:0], length[7:0], msg_idx[31:0]}
//   word1 = ts_ns (48 useful bits, in bits [47:0]; rest 0)
//   words 2..N = body (msg[11:len], MSB-first, zero-padded)
// At DW=32 (fase3-uram, Annex-A trim): w0={type,locate,len}, w1=msg_idx,
// w2..=body — WITHOUT timestamp words (the book does not consume them;
// contract amended by specs/fase3-uram/spec.md, criterion 1).
//
// ARCHITECTURE (capture to msg_reg): when the message is COMPLETE in the
// queue (2+len <= QB), it is captured at once into msg_reg (a stable emitter
// independent of the stream) and the whole message is drained from the queue.
// The emission states only emit from msg_reg (they do not read the stream):
// there is no desynchronization. The queue buffers the worst case (minimum back-to-back messages)
// between the CAP's punctual consumption and the arrival of the input.
//
// QB (iteration 6, 2026-08-14 — exhaustive review): 128 -> 64. The queue's
// stationary backlog is QB/4 words (the input flows at 4 B/c and the CAP's
// punctual drain averages ~2,7 B/c => the queue settles at QB and each
// message waits ~QB/16 messages of turn): QB=64 cuts the wire->BBO latency
// from ~69 to ~42 cycles on average (p99 77 -> 47; ~215 -> ~132 ns at
// 322,265625 MHz) and shrinks the barrel shifter from 1024 to 512 bits for
// synthesis (criterion 10). The tested stretch of back-to-back messages
// (LIN-01/P32-02) goes from 0 stalls to BOUNDED stalls (~15 across 4 A/U
// messages; "no sustained backpressure" of the phase-1 regime — the infinite
// feed limitation is already documented in LIN-01 scope); the bit-exact
// correctness and the acceptance average are kept. The queue worst case (P=44
// B => 46 B with prefix) fits with margin (64 >= 46). Do not touch QB without
// re-measuring the latency evidence (SEC-LAT-01). ATTENTION: in the chain
// (itch_chain.sv) the QB parameter is overridden from the top — changing the
// default here does not affect phase 3 (see docs/writeup/lessons-learned.md §1).
module itch_parser #(
    parameter DW = 64,
    parameter QB = 64
) (
    input  wire              clk,
    input  wire              rst_n,
    input  wire [DW-1:0]     s_axis_tdata,
    input  wire [DW/8-1:0]   s_axis_tkeep,
    input  wire              s_axis_tvalid,
    output reg               s_axis_tready,
    input  wire              s_axis_tlast,
    output reg  [DW-1:0]     m_axis_tdata,
    output reg               m_axis_tvalid,
    input  wire              m_axis_tready,
    output reg               m_axis_tlast,
    output reg               gap_detected,
    output reg               error
);

    // bytes per word and its log2: 64 bits -> 8 B (>>3), 32 bits -> 4 B (>>2)
    localparam BYTES = DW / 8;
    localparam L2B   = $clog2(DW / 8);

    // Byte-aligned queue with a one-beat margin (QBUFW): a message of exactly
    // 2+len == QB bytes (e.g. a P of 44 B, 2+44=46=QB at DW=32) only
    // completed if the previous residue ended up ≡ 2 mod 4 with whole beats;
    // with a margin of (BYTES-1) the last beat overflows into the queue and
    // the message always completes (finding iter 13: chain01 red, ST_LEN
    // frozen at qn=45 with a P of 2+len=46).
    localparam QBUFW = QB + BYTES - 1;
    localparam QQ = QBUFW * 8;

    localparam ST_HDR  = 3'd0;
    localparam ST_LEN  = 3'd1;
    localparam ST_CAP  = 3'd2;   // capture message into msg_reg + drains 2+len
    localparam ST_W0   = 3'd3;
    localparam ST_TS   = 3'd4;
    localparam ST_BODY = 3'd5;
    localparam ST_NEXT = 3'd6;
    localparam ST_DRAIN = 3'd7;  // oversize message (2+len > QB): drained over
                                 // the stream without buffer nor register
                                 // (addendum iter 12: ST_LEN deadlocked with
                                 // tready=0, message never fits the queue)
    reg [2:0] st;

    reg  [QQ-1:0] q;
    reg  [7:0]    qn;      // 8 bits cover the maximum supported QB of 128 bytes
    reg  [8:0]    drop_left;  // remaining bytes of the oversize message (2+len <= 257)

    reg  [31:0]   msg_idx;
    reg  [63:0]   exp_seq;
    reg  [63:0]   this_seq;
    reg  [79:0]   session_id;
    reg  [15:0]   pack_left;
    reg  [15:0]   pack_count;
    reg  [7:0]    msg_len;
    reg           in_subset;
    reg  [7:0]    msg_type;
    reg  [15:0]   locate;
    reg  [47:0]   ts_ns;
    reg           len_ok;
    reg           eop_seen;   // latch: datagram finished (tlast seen)
    reg           drop_packet;
    reg  [351:0]  msg_reg;
    reg  [6:0]    body_w;
    reg  [6:0]    bi;
    reg           out_valid_reg;
    reg  [DW-1:0] out_data_reg;
    reg           out_last_reg;

    wire [7:0] avail = qn;

    // AXI-Stream emission: `m_axis_*` is the physical registered output; the
    // internal presentation is done by `out_valid/out_data/out_last` with
    // standard retention. A beat completes ONLY when tvalid and tready are
    // co-high (AXI handshake, OUT-03); the data is held while tvalid is high
    // and tready is low (OUT-03 "does not change"); the FSM only advances on beats.
    assign m_axis_tvalid = out_valid_reg;
    assign m_axis_tdata  = out_data_reg;
    assign m_axis_tlast  = out_last_reg;

    // The internal datum is captured on the edge if there is room: room = no
    // pending datum OR the current one was accepted (tready) this beat.
    wire out_take   = m_axis_tvalid && m_axis_tready;
    wire out_free   = !out_valid_reg || out_take;

    function automatic logic [7:0] pbyte(input [QQ-1:0] w, input [6:0] i);
        pbyte = w[(32'(QBUFW) - 32'(i) - 1)*8 +: 8];
    endfunction

    function automatic [7:0] keep_nbytes(input logic [BYTES-1:0] keep);
        keep_nbytes = 0;
        for (int k = 0; k < BYTES; k++)
            keep_nbytes = keep_nbytes + keep[k];
    endfunction

    function automatic logic keep_is_msb_prefix(input logic [BYTES-1:0] keep);
        logic seen_zero;
        begin
            seen_zero = 1'b0;
            keep_is_msb_prefix = (keep != '0);
            for (int k = BYTES-1; k >= 0; k--) begin
                if (!keep[k]) seen_zero = 1'b1;
                else if (seen_zero) keep_is_msb_prefix = 1'b0;
            end
        end
    endfunction

    function automatic logic issubset(input [7:0] t);
        issubset = (t == 8'h53) || (t == 8'h52) || (t == 8'h41) || (t == 8'h46) ||
                   (t == 8'h45) || (t == 8'h43) || (t == 8'h58) || (t == 8'h44) ||
                   (t == 8'h55) || (t == 8'h50);   // S R A F E C X D U P
    endfunction

    // Expected total length of the 22 canonical types (source: messages.py).
    // 0 => unknown type; consumed without decoding nor table validation.
    function automatic logic [7:0] explen(input [7:0] t);
        case (t)
            8'h53: explen = 8'd12;   // S
            8'h52: explen = 8'd39;   // R
            8'h48: explen = 8'd25;   // H
            8'h59: explen = 8'd20;   // Y
            8'h4c: explen = 8'd26;   // L
            8'h56: explen = 8'd35;   // V
            8'h57: explen = 8'd12;   // W
            8'h4b: explen = 8'd28;   // K
            8'h4a: explen = 8'd35;   // J
            8'h4f: explen = 8'd21;   // O
            8'h41: explen = 8'd36;   // A
            8'h46: explen = 8'd40;   // F
            8'h45: explen = 8'd31;   // E
            8'h43: explen = 8'd36;   // C
            8'h58: explen = 8'd23;   // X
            8'h44: explen = 8'd19;   // D
            8'h55: explen = 8'd35;   // U
            8'h50: explen = 8'd44;   // P
            8'h51: explen = 8'd40;   // Q
            8'h42: explen = 8'd19;   // B
            8'h49: explen = 8'd50;   // I
            8'h4e: explen = 8'd20;   // N
            default: explen = 8'd0;
        endcase
    endfunction

    function automatic logic [7:0] mbyte(input [351:0] m, input [6:0] i);
        mbyte = m[351 - 8*i -: 8];
    endfunction

    // body word from msg_reg (base = 11+8*bi); zero-padded outside
    function automatic logic [DW-1:0] cbody(input [351:0] m, input [7:0] ml,
                                            input [6:0] base);
        logic [DW-1:0] r;
        for (int k = 0; k < BYTES; k++) begin
            if ((16'(base) + 16'(k)) < 16'(ml)) begin
                r[DW-1 - 8*k -: 8] = mbyte(m, 7'(base + k));
            end else begin
                r[DW-1 - 8*k -: 8] = 8'h0;
            end
        end
        cbody = r;
    endfunction

    // ------------------------------------------------------------------
    // drain of THIS cycle (combinational), in bytes.
    //   HDR   : 20    (at once)
    //   LEN   : 0     (only waits and captures)
    //   CAP   : 2+len (drains the whole message at once)
    //   DRAIN : min(drop_left, avail) — the oversize is drained
    //           incrementally through the queue (the parallel acceptance
    //           can_da preserves the alignment of the next message)
    //   W0/TS/BODY/NEXT : 0 (only emit from msg_reg)
    // ------------------------------------------------------------------
    wire [7:0] drain_need =
        (st == ST_HDR) ? 8'd20 :
        (st == ST_CAP) ? 8'(2 + msg_len) :
        (st == ST_DRAIN) ? 8'((drop_left < 9'(avail)) ? drop_left : avail) :
        8'd0;

    wire [7:0] drain_int = (drain_need <= avail) ? drain_need : 8'd0;

    wire [7:0] in_nbytes = keep_nbytes(s_axis_tkeep);
    wire keep_shape_ok = keep_is_msb_prefix(s_axis_tkeep);
    wire in_keep_ok = keep_shape_ok &&
                      (s_axis_tlast || s_axis_tkeep == {BYTES{1'b1}});
    wire [DW-1:0] in_compact = in_keep_ok ?
        (s_axis_tdata >> (8 * (32'(BYTES) - 32'(in_nbytes)))) : '0;

    // combinational tready: there is room after the possible drain of this
    // cycle. During a discard everything is accepted up to the physical tlast.
    wire drain_active = (drain_int > 0) && (qn >= drain_int);
    wire [7:0] base_n = drain_active ? qn - drain_int : qn;
    // Oversize (ST_DRAIN, addendum iter 14): the beats are skipped over the
    // stream with the message boundary. A whole beat within drop_left is
    // discarded (drain_drop); the beat that crosses the end of the message
    // keeps only its tail (drain_strad), bytes of the next message. The
    // drop_left count becomes per-stream (it is not re-summed inside the
    // queue): the previous design (iter 13) refilled the queue with can_da
    // and the last beat's residue ended up misaligned (chain01 consumed 3
    // bytes of the next message: loc 14 -> 13).
    wire in_drain = (st == ST_DRAIN);
    wire drain_live = in_drain && (drop_left > 0);
    wire drain_drop  = drain_live && (9'(in_nbytes) <= drop_left);
    wire drain_strad = drain_live && (9'(in_nbytes) > drop_left);
    wire [7:0] retain_n = in_nbytes - 8'(drop_left);
    // Tail kept at the crossing: the (in_nbytes - drop_left) LOW bytes of the
    // beat (in in_compact byte0 = the first-received = MSB; the tail of the
    // next message are the low bytes). The previous shift `>> 8*drop_left`
    // kept the HIGH bytes (those of the message to discard) -> it misaligned
    // the next message (iter 15: I2 without size/type).
    wire [QQ-1:0] tailmask = (QQ'(1) << (8 * (32'(retain_n)))) - 1;
    wire [QQ-1:0] tailblock = QQ'(in_compact) & tailmask;
    wire [QQ-1:0] retain_bits = tailblock << (8 * (32'(QBUFW) - 32'(retain_n)));
    // After accepting tlast the next datagram is not prefetched until the current
    // one is closed or discarded: the queue keeps no internal boundary markers.
    wire can_aug = s_axis_tvalid && !eop_seen && !drain_live &&
                   !drain_active &&
                   (32'(qn) + 32'(in_nbytes) <= 32'(QBUFW));
    wire can_da  = s_axis_tvalid && !eop_seen && drain_active &&
                   (32'(base_n) + 32'(in_nbytes) <= 32'(QBUFW));
    wire invalid_offer = s_axis_tvalid && !eop_seen && !in_keep_ok;
    assign s_axis_tready = drop_packet || invalid_offer || can_aug || can_da ||
                           drain_drop || drain_strad;
    wire in_take = s_axis_tvalid && s_axis_tready;
    wire [QQ-1:0] append_bits = QQ'(in_compact) <<
        (8 * (32'(QBUFW) - 32'(base_n) - 32'(in_nbytes)));
    wire [7:0] qn_post = base_n +
        ((in_take && in_keep_ok) ? in_nbytes : 8'd0);
    wire eop_eff = eop_seen ||
                   (in_take && in_keep_ok && s_axis_tlast);
    wire record_active = (st >= ST_CAP) && (st <= ST_NEXT);

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            st <= ST_HDR; q <= 0; qn <= 0; drop_left <= 0;
            msg_idx <= 0; exp_seq <= 64'd1; this_seq <= 0; session_id <= 0;
            pack_left <= 0; pack_count <= 0; msg_len <= 0;
            in_subset <= 1'b0; msg_type <= 0; locate <= 0; ts_ns <= 0; len_ok <= 1'b0;
            eop_seen <= 1'b0; drop_packet <= 1'b0;
            msg_reg <= 0; body_w <= 0; bi <= 0;
            out_valid_reg <= 1'b0; out_data_reg <= 0; out_last_reg <= 1'b0;
            gap_detected <= 1'b0; error <= 1'b0;
        end else begin
            gap_detected <= 1'b0;
            error <= 1'b0;
            if (out_take) out_valid_reg <= 1'b0;
            if (drop_packet) begin
                if (in_take && s_axis_tlast) begin
                    drop_packet <= 1'b0;
                    if (record_active) begin
                        eop_seen <= 1'b1;
                        pack_left <= 1;
                    end else begin
                        eop_seen <= 1'b0;
                        st <= ST_HDR;
                    end
                end
            end else if (in_take && !in_keep_ok) begin
                error <= 1'b1;
                q <= '0;
                qn <= '0;
                drop_packet <= !s_axis_tlast;
                if (record_active) begin
                    eop_seen <= s_axis_tlast;
                    pack_left <= 1;
                end else begin
                    eop_seen <= 1'b0;
                    st <= ST_HDR;
                end
            end else begin
                // end-of-datagram latch: set when the stream marks tlast (SEC-FRM-01/02)
                // and cleared on closing or discarding the datagram.
                if (in_take && s_axis_tlast) eop_seen <= 1'b1;

                // ------------------------------------------------------------
                // queue: drains drain_int and accepts valid input in parallel
                // (during ST_DRAIN only the boundary crossing is retained)
                // ------------------------------------------------------------
                if (drain_strad) begin
                    q <= retain_bits;
                    qn <= retain_n;
                end else if (drain_drop) begin
                    q <= '0;
                    qn <= 8'd0;
                end else if (can_da) begin
                    q <= (q << (8*drain_int)) | append_bits;
                    qn <= qn_post;
                end else if (drain_active) begin
                    q <= q << (8*drain_int);
                    qn <= base_n;
                end else if (can_aug) begin
                    q <= q | append_bits;
                    qn <= qn_post;
                end


                case (st)
                ST_HDR: begin
                    if (drain_int == 20) begin
                        this_seq <= {pbyte(q,10), pbyte(q,11), pbyte(q,12), pbyte(q,13),
                                     pbyte(q,14), pbyte(q,15), pbyte(q,16), pbyte(q,17)};
                        pack_left <= {pbyte(q,18), pbyte(q,19)};
                        pack_count <= {pbyte(q,18), pbyte(q,19)};
                        // session change: resets the expected seq (SEC-FRM-03),
                        // never counts as a gap
                        if ({pbyte(q,0),pbyte(q,1),pbyte(q,2),pbyte(q,3),
                             pbyte(q,4),pbyte(q,5),pbyte(q,6),pbyte(q,7),
                             pbyte(q,8),pbyte(q,9)} != session_id) begin
                            session_id <= {pbyte(q,0),pbyte(q,1),pbyte(q,2),pbyte(q,3),
                                           pbyte(q,4),pbyte(q,5),pbyte(q,6),pbyte(q,7),
                                           pbyte(q,8),pbyte(q,9)};
                            exp_seq <= {pbyte(q,10), pbyte(q,11), pbyte(q,12), pbyte(q,13),
                                        pbyte(q,14), pbyte(q,15), pbyte(q,16), pbyte(q,17)};
                        end else if ({pbyte(q,10), pbyte(q,11), pbyte(q,12), pbyte(q,13),
                             pbyte(q,14), pbyte(q,15), pbyte(q,16), pbyte(q,17)}
                            != exp_seq) gap_detected <= 1'b1;
                        // count=0 (SEC-FRM-04): packet without messages, it
                        // advances and keeps waiting for the next header emitting
                        // nothing. exp_seq advances by 0 => stays = seq of the
                        // current header. The header is used, not the previous
                        // exp_seq value: on a new session both assignments happen on this edge.
                        if ({pbyte(q,18), pbyte(q,19)} == 16'h0) begin
                            if (eop_eff && qn_post == 0) begin
                                exp_seq <= {pbyte(q,10), pbyte(q,11), pbyte(q,12), pbyte(q,13),
                                            pbyte(q,14), pbyte(q,15), pbyte(q,16), pbyte(q,17)};
                                eop_seen <= 1'b0;
                                st <= ST_HDR;
                            end else begin
                                error <= 1'b1;
                                q <= '0;
                                qn <= '0;
                                eop_seen <= 1'b0;
                                drop_packet <= !eop_eff;
                                st <= ST_HDR;
                            end
                        end else begin
                            st <= ST_LEN;
                        end
                    end else if (eop_seen) begin
                        // tlast before completing the 20 header bytes.
                        error <= 1'b1;
                        q <= '0;
                        qn <= '0;
                        eop_seen <= 1'b0;
                        st <= ST_HDR;
                    end
                end

                // ------------------------------------------------
                // LEN: wait for the complete message (2+len) to capture to msg_reg
ST_LEN: begin
                    if (avail >= 2) begin
                        if (8'(avail) >= 2 + 8'({pbyte(q,0), pbyte(q,1)})) begin
                            msg_len   <= 8'({pbyte(q,0), pbyte(q,1)});
                            msg_type  <= pbyte(q,2);
                            in_subset <= issubset(pbyte(q,2));
                            locate    <= {pbyte(q,3), pbyte(q,4)};
                            ts_ns     <= {pbyte(q,7), pbyte(q,8), pbyte(q,9),
                                          pbyte(q,10), pbyte(q,11), pbyte(q,12)};
                            body_w <= (8'({pbyte(q,0), pbyte(q,1)}) >= 11) ?
                                7'(((8'({pbyte(q,0), pbyte(q,1)}) - 8'd11) +
                                    8'(BYTES-1)) >> L2B) : 7'd0;
                            bi <= 0;
                            msg_reg <= q[(QBUFW-2)*8 - 1 -: 352];
                            // Every canonical type is validated, even if it emits no register.
                            // An unknown type (explen=0) continues as passthrough.
                            len_ok <= (explen(pbyte(q,2)) == 0) ||
                                      (explen(pbyte(q,2)) ==
                                       8'({pbyte(q,0), pbyte(q,1)}));
                            if ((8'({pbyte(q,0), pbyte(q,1)}) < 11) ||
                                ((explen(pbyte(q,2)) != 0) &&
                                 (explen(pbyte(q,2)) !=
                                  8'({pbyte(q,0), pbyte(q,1)}))))
                                error <= 1'b1;
                            st <= ST_CAP;
end else if (9'(2 + 8'({pbyte(q,0), pbyte(q,1)})) > 9'(QB)) begin
                            // message larger than the queue (2+len > QB, e.g.
                            // I=50 B with QB=46): never fits in the buffer —
                            // it is drained over the stream without register
                            // (addendum iter 12; the previous ST_LEN waited
                            // for progress -> tready=0 indefinitely,
                            // deadlock). The queue content is the prefix of
                            // the oversize message: it is discarded whole and
                            // only the missing bytes are counted. The length
                            // validation (explen) is kept. iter 14: drop_left
                            // subtracts qn_post (avail + the beat accepted in
                            // THIS cycle by can_aug); the previous design only
                            // subtracted avail and the cycle's beat went
                            // uncounted -> the drain consumed one extra beat
                            // of the next message (chain01: loc 14 -> 13, 3
                            // bytes eaten).
                            if ((explen(pbyte(q,2)) != 8'd0) &&
                                (explen(pbyte(q,2)) !=
                                 8'({pbyte(q,0), pbyte(q,1)})))
                                error <= 1'b1;
                            drop_left <= 9'(2 + 8'({pbyte(q,0), pbyte(q,1)})) -
                                         9'(qn_post);
                            q <= '0;
                            qn <= '0;
                            st <= ST_DRAIN;
                        end else if (eop_seen) begin
                            // truncated frame (SEC-FRM-01): the datagram already ended
                            // (tlast) and the declared message is not complete.
                            error <= 1'b1;
                            q <= 0;
                            qn <= 0;
                            eop_seen <= 1'b0;
                            pack_left <= 0;
                            st <= ST_HDR;
                        end
                    end else if (eop_seen) begin
                        // not even the len field complete (SEC-FRM-02)
                        error <= 1'b1;
                        q <= 0;
                        qn <= 0;
                        eop_seen <= 1'b0;
                        pack_left <= 0;
                        st <= ST_HDR;
                    end
                end

                // ------------------------------------------------
                ST_CAP: begin
                    if (out_free) begin
                        out_valid_reg <= 1'b0;
                        // len_ok = 0: incoherent or truncated length -> no register
                        st <= ((in_subset && msg_len >= 11 && len_ok) ? ST_W0 : ST_NEXT);
                    end
                end

                ST_W0: begin
                    if (out_free) begin
                        if (in_subset && msg_len >= 11) begin
                            // w0: {type, locate, len, idx} at 64 bits; at 32 bits
                            // the idx is emitted in its own word (w1, Annex-A
                            // trim: the ts words were removed — the book does
                            // not consume them; specs/fase3-uram criterion 1)
                            if (DW == 32)
                                out_data_reg <= DW'({msg_type, locate, msg_len});
                            else
                                out_data_reg <= DW'({msg_type, locate, msg_len, msg_idx[31:0]});
                            out_valid_reg <= 1'b1;
                            out_last_reg  <= 1'b0;
                        end
                        st <= ST_TS;
                    end
                end

                ST_TS: begin
                    if (out_free) begin
                        if (DW == 32) begin
                            // trimmed 32-bit header: a single word w1=msg_idx;
                            // the body starts at w2
                            out_data_reg <= DW'(msg_idx);
                            out_valid_reg <= 1'b1;
                            out_last_reg  <= 1'b0;
                            st <= ST_BODY;
                        end else begin
                            out_data_reg <= DW'({16'h0, ts_ns});
                            out_valid_reg <= 1'b1;
                            out_last_reg  <= 1'b0;
                            st <= ST_BODY;
                        end
                    end
                end

                ST_BODY: begin
                    if (out_free) begin
                        if (in_subset && msg_len >= 11 && bi < body_w) begin
                            out_data_reg <= cbody(msg_reg, msg_len, 7'(11 + BYTES*bi));
                            out_valid_reg <= 1'b1;
                            out_last_reg  <= (bi == body_w - 1);
                            bi <= bi + 1;
                        end else begin
                            out_valid_reg <= 1'b0;
                            st <= ST_NEXT;
                        end
                    end
                end

                ST_NEXT: begin
                    // tlast closes the input UDP datagram (consumed; the
                    // framing count governs the real flow).
                    if (s_axis_tlast) begin
                        // packet-close marker (does not alter the flow)
                    end
                    if (out_free) begin
                        msg_idx <= msg_idx + 1;
                        out_valid_reg <= 1'b0;
                        // fixed off-by-one: if messages of the SAME packet remain
                        // (pack_left still above 1 after the decrement), continue
                        // ST_LEN; this was the last (pack_left==1) -> ST_HDR
                        if (pack_left > 1) begin
                            pack_left <= pack_left - 1;
                            st <= ST_LEN;
                        end else if (eop_eff && qn_post == 0) begin
                            exp_seq <= this_seq + 64'(pack_count);
                            eop_seen <= 1'b0;
                            st <= ST_HDR;
                        end else begin
                            error <= 1'b1;
                            q <= '0;
                            qn <= '0;
                            eop_seen <= 1'b0;
                            pack_left <= 0;
                            drop_packet <= !eop_eff;
                            st <= ST_HDR;
                        end
                    end
                end

                    // ------------------------------------------------
                ST_DRAIN: begin
                    // incremental drain of the oversize message: the stream's
                    // beats are skipped with the message boundary (drain_drop
                    // / drain_strad, addendum iter 14) — nothing accumulates
                    // except the crossing's tail (bytes of the next message).
                    // On completion, ST_LEN resumes with the queue aligned.
                    // The drained message decrements pack_left like one more
                    // message of the datagram (iter 13: without the decrement,
                    // the header's pack_left ended up misaligned at packet
                    // close and ST_NEXT pulsed error).
                    if (drop_left == 0) begin
                        if (pack_left > 1) begin
                            pack_left <= pack_left - 1;
                            st <= ST_LEN;
                        end else if (eop_eff && qn_post == 0) begin
                            exp_seq <= this_seq + 64'(pack_count);
                            eop_seen <= 1'b0;
                            st <= ST_HDR;
                        end else begin
                            error <= 1'b1;
                            q <= '0;
                            qn <= '0;
                            eop_seen <= 1'b0;
                            pack_left <= 0;
                            st <= ST_HDR;
                        end
                    end else if (eop_seen) begin
                        // datagram truncated inside the oversize message
                        // (SEC-FRM-01): the stream ended and the declared
                        // message did not complete
                        error <= 1'b1;
                        q <= '0;
                        qn <= '0;
                        eop_seen <= 1'b0;
                        pack_left <= 0;
                        st <= ST_HDR;
                    end else if (drain_drop) begin
                        drop_left <= drop_left - 8'(in_nbytes);
                    end else if (drain_strad) begin
                        drop_left <= '0;
                    end
                end

                    default: st <= ST_HDR;
                endcase
            end
        end
    end

endmodule
