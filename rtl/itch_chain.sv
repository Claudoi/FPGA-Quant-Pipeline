// itch_chain.sv — parser ITCH -> order book chain (phase 3, CHAIN-01).
//
// Integration top of the pipeline with a parameterized datapath: the parser's
// Annex A is wired directly (1 word/cycle) into the book's consumer, without
// an intermediate FIFO nor re-parsing. DW=32 is the phase-3 target variant
// (322,265625 MHz); DW=64 keeps the phase-2 baseline.
module itch_chain #(
    parameter DW   = 32,
    // QB (iter 4, SEC-URAM-04): 64 -> 46. The avg wire->BBO latency of the
    // real feed (make sim-lat) with QB=46 lands at ~45 (RTM-LAT-01 threshold
    // avg <= 48); raising QB (experimental iter 15: 64) broke the criterion
    // (avg 72,7). QB=46 is the floor: the canonical worst case (P=44 B => 46 B
    // with prefix) fits exactly; QB=32 DEADLOCKS (2+len=46 > 32). Messages
    // > QB (I=50 B, 2+len=52) are drained via ST_DRAIN (addendum
    // iter 12), with the boundary accounting fixed in iter 15.
    parameter QB   = 46,
    // K=64 (addendum iter 12): the wire's ref travels untruncated. The real
    // day exceeds 2^19 (refs ~1,6M at the open; K=19 truncated residues and
    // lost subset events); the book widens its input to OW=130 bits
    parameter K    = 64,
    parameter P    = 32,
    parameter ND   = 5,
    parameter NSYM = 20,
    parameter PXW  = 32,
    parameter QW   = 32
) (
    input  wire              clk,
    input  wire              rst_n,
    input  wire [DW-1:0]     s_axis_tdata,
    input  wire [DW/8-1:0]   s_axis_tkeep,
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
    output wire              error,
    output wire              gap_detected
);

    wire [DW-1:0] p_m_axis_tdata;
    wire p_m_axis_tvalid, p_m_axis_tlast, p_m_axis_tready;
    wire p_error, b_error;

    itch_parser #(.DW(DW), .QB(QB)) u_parser (
        .clk(clk), .rst_n(rst_n),
        .s_axis_tdata(s_axis_tdata), .s_axis_tkeep(s_axis_tkeep),
        .s_axis_tvalid(s_axis_tvalid),
        .s_axis_tready(s_axis_tready), .s_axis_tlast(s_axis_tlast),
        .m_axis_tdata(p_m_axis_tdata), .m_axis_tvalid(p_m_axis_tvalid),
        .m_axis_tready(p_m_axis_tready), .m_axis_tlast(p_m_axis_tlast),
        .gap_detected(gap_detected), .error(p_error)
    );

    orderbook #(.DW(DW), .K(K), .P(P), .ND(ND), .NSYM(NSYM), .PXW(PXW), .QW(QW)) u_book (
        .clk(clk), .rst_n(rst_n),
        .s_axis_tdata(p_m_axis_tdata), .s_axis_tvalid(p_m_axis_tvalid),
        .s_axis_tready(p_m_axis_tready), .s_axis_tlast(p_m_axis_tlast),
        .bbo_locate(bbo_locate), .bbo_tdata(bbo_tdata),
        .bbo_tvalid(bbo_tvalid), .bbo_tready(bbo_tready),
        .bbo_changed(bbo_changed), .depth_tdata(depth_tdata),
        .depth_tvalid(depth_tvalid), .depth_tready(depth_tready),
        .cross_events(cross_events),
        .anomaly_count(anomaly_count), .error(b_error)
    );

    assign error = p_error | b_error;

endmodule
