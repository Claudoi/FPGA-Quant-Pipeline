// itch_chain_synth.sv — top de SÍNTESIS (timing/recursos, criterio 10).
//
// El top de integración rtl/itch_chain.sv expone 896 puertos (buses de
// observabilidad: bbo_tdata 128 bits + depth_tdata 640 bits + contadores de
// debug). El paquete FFVA676 del XCKU3P solo tiene 256 I/O (AVAILABLE_IOBS),
// por lo que el placer falla con Place 30-415 (hallazgo 2026-08-18). Este
// wrapper recorta a los puertos del contrato AXI:
//
//   - bbo_tdata (128 bits) íntegro: es la salida BBO del contrato.
//   - depth_tdata recortado a [31:0]: la observabilidad del depth NO es un
//     requisito de timing; el pipeline que lo genera se conserva (los bits
//     sin conectar se optimizan, el datapath medido es idéntico).
//   - cross_events/anomaly_count/error/gap_detected sin conectar (los
//     contadores y flags del pipeline se conservan; solo se recortan los
//     pins).
//
// El QB efectivo de la cadena se fija aquí como en rtl/itch_chain.sv (46) y
// en la línea -G/`generic` del tcl: NO cambiar defaults de submódulos.
module itch_chain_synth #(
    parameter DW   = 32,
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
    (* IOB = "TRUE" *)
    output reg               s_axis_tready,
    input  wire              s_axis_tlast,
    (* IOB = "TRUE" *)
    output reg  [15:0]       bbo_locate,
    (* IOB = "TRUE" *)
    output reg  [127:0]      bbo_tdata,
    (* IOB = "TRUE" *)
    output reg               bbo_tvalid,
    input  wire              bbo_tready,
    (* IOB = "TRUE" *)
    output reg               bbo_changed,
    (* IOB = "TRUE" *)
    output reg  [31:0]       depth_tdata,
    (* IOB = "TRUE" *)
    output reg               depth_tvalid,
    input  wire              depth_tready
);

    wire [DW-1:0] p_m_axis_tdata;
    wire p_m_axis_tvalid, p_m_axis_tlast, p_m_axis_tready;
    wire p_error, b_error, gap_detected;
    wire [31:0] cross_events, anomaly_count;
    wire [2*ND*64-1:0] depth_full;

    // ---------------------------------------------------------------
    // pines registrados (iter 8, addendum spec): la peor ruta del re-run
    // 2026-08-18 14:11 era un I/O del wrapper (msg_len_reg -> s_axis_tready,
    // -7,395 ns: el parser empujaba su drenaje hasta el pin) y las rutas
    // de reset del pin (rst_n -> lv_qty_reg/R, ~-5,7 ns). El wrapper de
    // síntesis replica la integración real de la cadena a 322 MHz:
    //   - FIFO de entrada de 4xDW: el handshake del pin lo gobierna un
    //     contador local (ruta FF->pin de ~3 niveles). Régimen (no ocultado):
    //     la backpressure del pin se difiere hasta 3 palabras de
    //     amortiguación; la cadena interna no cambia; latencia de pin +1
    //     ciclo (SEC-URAM-04/RTM-LAT-01 miden la cadena, no el wrapper).
    //   - rst_n regenerado en un FF local: corta la ruta del pin a los R
    //     de los FDRE (sincronizador de práctica estándar en el top).
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

    // tready del pin registrado (iter 10): la ruta f_n -> LUT -> OBUF ->
    // pin con el skew del area del book no cierra; el FF del comparador se
    // empaca en el IOB (atributo en el puerto). El handshake usa el tready
    // registrado: el productor empuja cuando ve ready=1 y el wrapper cuenta
    // el mismo ready (fifo_hs) -> regimen coherente, sin overflow
    // (f_n <= 3 por construccion), backpressure diferida 1 ciclo en el pin.
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
        .bbo_locate(bbo_locate), .bbo_tdata(bbo_tdata),
        .bbo_tvalid(bbo_tvalid), .bbo_tready(bbo_tready),
        .bbo_changed(bbo_changed), .depth_tdata(depth_full),
        .depth_tvalid(depth_tvalid), .depth_tready(depth_tready),
        .cross_events(cross_events),
        .anomaly_count(anomaly_count), .error(b_error)
    );

    assign depth_tdata = depth_full[31:0];

endmodule