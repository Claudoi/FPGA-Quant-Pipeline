// itch_chain.sv — cadena parser ITCH -> order book (fase 3, CHAIN-01).
//
// Top de integración del pipeline a datapath parametrizado: el Anexo A del
// parser se cablea directamente (1 palabra/ciclo) al consumidor del book, sin
// FIFO intermedia ni re-parseo. DW=32 es la variante objetivo de la fase 3
// (322,265625 MHz); DW=64 conserva la base de la fase 2.
module itch_chain #(
    parameter DW   = 32,
    parameter QB   = 128,
    parameter K    = 19,
    parameter P    = 32,
    parameter NSYM = 20,
    parameter PXW  = 32,
    parameter QW   = 32
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
        .s_axis_tdata(s_axis_tdata), .s_axis_tvalid(s_axis_tvalid),
        .s_axis_tready(s_axis_tready), .s_axis_tlast(s_axis_tlast),
        .m_axis_tdata(p_m_axis_tdata), .m_axis_tvalid(p_m_axis_tvalid),
        .m_axis_tready(p_m_axis_tready), .m_axis_tlast(p_m_axis_tlast),
        .gap_detected(gap_detected), .error(p_error)
    );

    orderbook #(.DW(DW), .K(K), .P(P), .NSYM(NSYM), .PXW(PXW), .QW(QW)) u_book (
        .clk(clk), .rst_n(rst_n),
        .s_axis_tdata(p_m_axis_tdata), .s_axis_tvalid(p_m_axis_tvalid),
        .s_axis_tready(p_m_axis_tready), .s_axis_tlast(p_m_axis_tlast),
        .bbo_locate(bbo_locate), .bbo_tdata(bbo_tdata),
        .bbo_tvalid(bbo_tvalid), .bbo_tready(bbo_tready),
        .bbo_changed(bbo_changed), .cross_events(cross_events),
        .anomaly_count(anomaly_count), .error(b_error)
    );

    assign error = p_error | b_error;

endmodule
