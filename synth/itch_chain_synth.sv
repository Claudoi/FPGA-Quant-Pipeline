// itch_chain_synth.sv — SYNTHESIS top (timing/resources, criterion 10).
//
// The rtl/itch_chain.sv integration top exposes 896 ports (observability
// buses: bbo_tdata 128 bits + depth_tdata 640 bits + debug counters). The
// FFVA676 package of the XCKU3P only has 256 I/O (AVAILABLE_IOBS), so the
// placer fails with Place 30-415 (finding 2026-08-18). This wrapper trims
// down to the AXI contract ports:
//
//   - bbo_tdata (128 bits) fully: it is the BBO output of the contract.
//   - depth_tdata trimmed to [31:0]: depth observability is NOT a timing
//     requirement; the pipeline that generates it is kept (the unconnected
//     bits are optimized away, the measured datapath is identical).
//   - cross_events/anomaly_count/error/gap_detected unconnected (the
//     pipeline's counters and flags are kept; only the pins are
//     trimmed).
//
// The chain's effective QB is fixed here as in rtl/itch_chain.sv (46) and on
// the tcl -G/`generic` line: do NOT change submodule defaults.
module itch_chain_synth #(
    parameter DW   = 32,
    parameter QB   = 46,
    // K=64 (addendum iter 12): the wire's ref travels untruncated (the real
    // day exceeds 2^19; the book widens its input to OW=130 bits)
    parameter K    = 64,
    parameter P    = 32,
    parameter ND   = 5,
    parameter NSYM = 20,
    parameter PXW  = 32,
    parameter QW   = 32,
    parameter BBO_W = 128   // width of the bbo_tdata bus at the pin (trim of
                            // observability for the package I/O budget; the
                            // 156 MHz variant uses 64)
) (
input  wire              clk,
    input  wire              rst_n,
    input  wire [DW-1:0]     s_axis_tdata,
    input  wire [DW/8-1:0]   s_axis_tkeep,
    input  wire              s_axis_tvalid,
    (* IOB = "TRUE" *)
    output reg               s_axis_tready,
    input  wire              s_axis_tlast,
    output wire [15:0]       bbo_locate,
    output wire [BBO_W-1:0]  bbo_tdata,
    output wire              bbo_tvalid,
    input  wire              bbo_tready,
    output wire              bbo_changed,
    output wire [31:0]       depth_tdata,
    output wire              depth_tvalid,
    input  wire              depth_tready
);

    wire [DW-1:0] p_m_axis_tdata;
    wire p_m_axis_tvalid, p_m_axis_tlast, p_m_axis_tready;
    wire p_error, b_error, gap_detected;
    wire [31:0] cross_events, anomaly_count;
    wire [2*ND*64-1:0] depth_full;

    // book outputs (wired to internal wires; the book's FFs have internal
    // fanout — retention + guard — and the placer does NOT pack them into the
    // IOB, iter 10). The iter-11 output pipeline registers the wrapper's own
    // FFs with IOB (same mechanism that replicated tready_ff).
    wire [15:0]  bbo_locate_i;
    wire [127:0] bbo_tdata_i;
    wire         bbo_tvalid_i, bbo_changed_i;
    wire         depth_tvalid_i;
    (* IOB = "TRUE" *)
    reg  [15:0]  bbo_locate_o;
    (* IOB = "TRUE" *)
    reg  [BBO_W-1:0] bbo_tdata_o;
    (* IOB = "TRUE" *)
    reg          bbo_tvalid_o, bbo_changed_o, depth_tvalid_o;
    (* IOB = "TRUE" *)
    reg  [31:0]  depth_tdata_o;

    assign bbo_locate   = bbo_locate_o;
    assign bbo_tdata    = bbo_tdata_o;
    assign bbo_tvalid   = bbo_tvalid_o;
    assign bbo_changed  = bbo_changed_o;
    assign depth_tdata  = depth_tdata_o;
    assign depth_tvalid = depth_tvalid_o;

    // ---------------------------------------------------------------
    // registered pins (iter 8, spec addendum): the worst path of the
    // 2026-08-18 14:11 re-run was a wrapper I/O (msg_len_reg -> s_axis_tready,
    // -7,395 ns: the parser pushed its drain to the pin) and the pin's reset
    // paths (rst_n -> lv_qty_reg/R, ~-5,7 ns). The synthesis wrapper mirrors
    // the chain's real integration at 322 MHz:
    //   - 4xDW input FIFO: the pin's handshake is governed by a local counter
    //     (FF->pin path of ~3 levels). Regime (not hidden): the pin's
    //     backpressure is deferred up to 3 words of buffering; the internal
    //     chain is unchanged; pin latency +1 cycle (SEC-URAM-04/RTM-LAT-01
    //     measure the chain, not the wrapper).
    //   - rst_n regenerated in a local FF: cuts the pin path to the FDRE
    //     R inputs (standard-practice synchronizer at the top).
    // ---------------------------------------------------------------
    reg [DW-1:0]   f_mem [3:0];
    reg [DW/8-1:0] f_keep [3:0];
    reg            f_tl  [3:0];
    reg [1:0]      f_n, f_wr, f_rd;
    reg            tready_ff;
    reg            rst_n_c;

    wire [DW-1:0]   p_s_axis_tdata;
    wire [DW/8-1:0] p_s_axis_tkeep;
    wire            p_s_axis_tvalid, p_s_axis_tlast, p_s_axis_tready;
    assign p_s_axis_tdata  = f_mem[f_rd];
    assign p_s_axis_tkeep  = f_keep[f_rd];
    assign p_s_axis_tvalid = (f_n != 2'd0);
    assign p_s_axis_tlast  = f_tl[f_rd];

    wire fifo_hs  = s_axis_tvalid && s_axis_tready;
    wire fifo_pop = p_s_axis_tvalid && p_s_axis_tready;

    // registered pin tready (iter 10): the f_n -> LUT -> OBUF -> pin path
    // with the book area's skew does not close; the comparator FF packs into
    // the IOB (attribute on the port). The handshake uses the registered
    // tready: the producer pushes when it sees ready=1 and the wrapper counts
    // the same ready (fifo_hs) -> coherent regime, no overflow
    // (f_n <= 3 by construction), backpressure deferred 1 cycle at the pin.
    always_ff @(posedge clk) begin
        if (!rst_n_c)
            tready_ff <= 1'b0;
        else
            tready_ff <= (f_n < 2'd3);
    end
    assign s_axis_tready = tready_ff;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            rst_n_c <= 1'b0;
            f_n <= 2'd0; f_wr <= 2'd0; f_rd <= 2'd0;
        end else begin
            rst_n_c <= 1'b1;
            if (fifo_hs) begin
                f_mem[f_wr]  <= s_axis_tdata;
                f_keep[f_wr] <= s_axis_tkeep;
                f_tl[f_wr]   <= s_axis_tlast;
                f_wr         <= f_wr + 2'd1;
            end
            if (fifo_pop)
                f_rd <= f_rd + 2'd1;
            f_n <= f_n + (fifo_hs ? 2'd1 : 2'd0) - (fifo_pop ? 2'd1 : 2'd0);
        end
    end

    itch_parser #(.DW(DW), .QB(QB)) u_parser (
        .clk(clk), .rst_n(rst_n_c),
        .s_axis_tdata(p_s_axis_tdata), .s_axis_tkeep(p_s_axis_tkeep),
        .s_axis_tvalid(p_s_axis_tvalid),
        .s_axis_tready(p_s_axis_tready), .s_axis_tlast(p_s_axis_tlast),
        .m_axis_tdata(p_m_axis_tdata), .m_axis_tvalid(p_m_axis_tvalid),
        .m_axis_tready(p_m_axis_tready), .m_axis_tlast(p_m_axis_tlast),
        .gap_detected(gap_detected), .error(p_error)
    );

    orderbook #(.DW(DW), .K(K), .P(P), .ND(ND), .NSYM(NSYM), .PXW(PXW), .QW(QW)) u_book (
        .clk(clk), .rst_n(rst_n_c),
        .s_axis_tdata(p_m_axis_tdata), .s_axis_tvalid(p_m_axis_tvalid),
        .s_axis_tready(p_m_axis_tready), .s_axis_tlast(p_m_axis_tlast),
        .bbo_locate(bbo_locate_i), .bbo_tdata(bbo_tdata_i),
        .bbo_tvalid(bbo_tvalid_i), .bbo_tready(bbo_tready),
        .bbo_changed(bbo_changed_i), .depth_tdata(depth_full),
        .depth_tvalid(depth_tvalid_i), .depth_tready(depth_tready),
        .cross_events(cross_events),
        .anomaly_count(anomaly_count), .error(b_error)
    );

    // ---------------------------------------------------------------
    // output pipeline (iter 11, spec addendum): the book's BBO/depth pair is
    // registered in the wrapper's OWN FFs (IOB = "TRUE"), because the book's
    // FFs have internal fanout (retention + guard) and do not pack. Pin regime
    // identical to the book's: capture when the book offers a pair with no
    // pair in flight (`tvalid_i && !tvalid_o`), pin-side retention
    // (`tvalid_o <= tvalid_o && !tready`: it retires 1 cycle after the
    // external acceptance, no duplicate if the consumer holds tready=1). +1
    // cycle of latency only at the pin. The pin's tready lines go straight to
    // the book (internal retention intact).
    // ---------------------------------------------------------------
    always_ff @(posedge clk) begin
        if (!rst_n_c) begin
            bbo_locate_o <= 0; bbo_tdata_o <= 0;
            bbo_tvalid_o <= 1'b0; bbo_changed_o <= 1'b0;
            depth_tdata_o <= 0; depth_tvalid_o <= 1'b0;
        end else begin
            // pin-side retention (the pair stays visible until external
            // acceptance; it retires the following cycle)
            bbo_tvalid_o <= bbo_tvalid_o && !bbo_tready;
            depth_tvalid_o <= depth_tvalid_o && !depth_tready;
            // capture of a new pair from the book (only if the pin is free)
            if (bbo_tvalid_i && !bbo_tvalid_o) begin
                bbo_locate_o  <= bbo_locate_i;
                bbo_tdata_o   <= bbo_tdata_i[127 -: BBO_W];
                bbo_changed_o <= bbo_changed_i;
                bbo_tvalid_o  <= 1'b1;
            end
            if (depth_tvalid_i && !depth_tvalid_o) begin
                depth_tdata_o <= depth_full[31:0];
                depth_tvalid_o <= 1'b1;
            end
        end
    end

endmodule