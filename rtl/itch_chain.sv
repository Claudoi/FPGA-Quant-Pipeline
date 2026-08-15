// itch_chain.sv — cadena parser ITCH -> order book (fase 3, CHAIN-01).
//
// Top de integración del pipeline a datapath parametrizado: el Anexo A del
// parser se cablea directamente (1 palabra/ciclo) al consumidor del book, sin
// FIFO intermedia ni re-parseo. DW=32 es la variante objetivo de la fase 3
// (322,265625 MHz); DW=64 conserva la base de la fase 2.
module itch_chain #(
    parameter DW   = 32,
    // QB (iter 4, SEC-URAM-04): 64 -> 46. La latencia wire->BBO media del
    // feed real (make sim-lat) baja de 55,9 (QB=64) a 47,1 (QB=48); con la
    // medición en estado estacionario (espera de la INVAL post-reset antes
    // de alimentar, ~65,5k ciclos) queda en ~45.0 con QB=46 — el backlog de
    // la cola del parser adelantándose al book (sonda URAM serializada
    // ~13-15 c/msg) es el componente dominante; el QB acota el adelanto a
    // ~1,5 mensajes. QB=46 es el piso: el peor caso (P=44 B => 46 B con
    // prefijo) cabe exacto; QB=32 DEADLOCKEA (2+len=46 > 32).
    parameter QB   = 46,
    parameter K    = 19,
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
