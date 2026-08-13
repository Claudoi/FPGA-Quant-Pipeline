// itch_parser.sv — parser ITCH 5.0 a line-rate (fase 1, Anexo A).
//
// Consume el payload MoldUDP64 ya decapado de IP/UDP:
//   session(10B) + seq u64be + count u16be + [len u16be + mensaje]*
// Valida framing y gaps (seq esperado = seq_prev + count_prev), alinea
// mensajes que cruzan límites de palabra y emite por AXI-Stream el registro
// normalizado del Anexo A:
//   word0 = {msg_type[7:0], locate[15:0], length[7:0], msg_idx[31:0]}
//   word1 = ts_ns (48 bits útiles, en bits [47:0]; resto 0)
//   words 2..N = cuerpo (msg[11:len], MSB-first, relleno 0)
//
// ARQUITECTURA (captura a msg_reg): cuando el mensaje está COMPLETO en la
// cola (2+len <= QB), se captura de una vez a msg_reg (emisor estable e
// independiente del stream) y se drena el mensaje completo de la cola. Los
// estados de emisión solo emiten desde msg_reg (no leen el stream): no hay
// desincronía. La cola amortigua el peor caso (mensajes mínimos back-to-back)
// entre el consumo puntual del CAP y la llegada de la entrada.
//
// QB (iteración 6, 2026-08-14 — revisión exhaustiva): 128 -> 64. El backlog
// estacionario de la cola es QB/4 palabras (la entrada fluye a 4 B/c y el
// drenaje puntual del CAP promedia ~2,7 B/c => la cola se fija en QB y cada
// mensaje espera ~QB/16 mensajes de turno): QB=64 recorta la latencia
// wire->BBO de ~69 a ~42 ciclos de media (p99 77 -> 47; ~215 -> ~132 ns a
// 322,265625 MHz) y reduce el barrel shifter de 1024 a 512 bits para la
// síntesis (criterio 10). El tramo probado de mensajes back-to-back
// (LIN-01/P32-02) pasa de 0 stalls a stalls ACOTADOS (~15 en 4 mensajes A/U;
// "sin backpressure sostenida" del régimen de fase 1 — la limitación del feed
// infinito ya está documentada en LIN-01 alcance); la corrección bit a bit y
// el promedio de aceptación se mantienen. El peor caso de cola (P=44 B =>
// 46 B con prefijo) cabe con holgura (64 >= 46). No tocar QB sin re-medir la
// evidencia de latencia (SEC-LAT-01). ATENCIÓN: en la cadena (itch_chain.sv)
// el parámetro QB se sobrescribe desde el top — cambiar el default aquí no
// afecta a fase 3 (ver revision-exhaustiva-2026-08-14.md, §3).
module itch_parser #(
    parameter DW = 64,
    parameter QB = 64
) (
    input  wire              clk,
    input  wire              rst_n,
    input  wire [DW-1:0]     s_axis_tdata,
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

    localparam QQ = QB * 8;

    // bytes por palabra y su log2: 64 bits -> 8 B (>>3), 32 bits -> 4 B (>>2)
    localparam BYTES = DW / 8;
    localparam L2B   = $clog2(DW / 8);

    localparam ST_HDR  = 3'd0;
    localparam ST_LEN  = 3'd1;
    localparam ST_CAP  = 3'd2;   // capturar mensaje a msg_reg + drena 2+len
    localparam ST_W0   = 3'd3;
    localparam ST_TS   = 3'd4;
    localparam ST_BODY = 3'd5;
    localparam ST_NEXT = 3'd6;
    reg [2:0] st;

    reg  [QQ-1:0] q;
    reg  [7:0]    qn;      // 8 bits: QB=128 requiere qn+8 <= 128 (qn llega a 128)

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
    reg           eop_seen;   // latch: terminado el datagrama (tlast visto)
    reg  [351:0]  msg_reg;
    reg  [6:0]    body_w;
    reg  [6:0]    bi;
    reg  [1:0]    hw;         // índice de la word de cabecera restante (DW=32)
    reg           out_valid_reg;
    reg  [DW-1:0] out_data_reg;
    reg           out_last_reg;

    wire [7:0] avail = qn;

    // Emisión AXI-Stream: `m_axis_*` es la salida registrada física; la
    // presentación interna la hace `out_valid/out_data/out_last` con retención
    // estándar. Un beat se completa SOLO cuando tvalid y tready coaltos
    // (handshake AXI, OUT-03); el dato se mantiene mientras tvalid alta y
    // tready baja (OUT-03 "no cambia"); y el FSM solo avanza en beats.
    assign m_axis_tvalid = out_valid_reg;
    assign m_axis_tdata  = out_data_reg;
    assign m_axis_tlast  = out_last_reg;

    // El dato interno se captura en el flanco si hay sitio: sitio = sin dato
    // pendiente O el actual fue aceptado (tready) en este beat.
    wire out_take   = m_axis_tvalid && m_axis_tready;
    wire out_free   = !out_valid_reg || out_take;

    function automatic logic [7:0] pbyte(input [QQ-1:0] w, input [6:0] i);
        pbyte = w[(QB-1-i)*8 +: 8];
    endfunction

    function automatic logic issubset(input [7:0] t);
        issubset = (t == 8'h53) || (t == 8'h52) || (t == 8'h41) || (t == 8'h46) ||
                   (t == 8'h45) || (t == 8'h43) || (t == 8'h58) || (t == 8'h44) ||
                   (t == 8'h55) || (t == 8'h50);   // S R A F E C X D U P
    endfunction

    // longitud total esperada del mensaje por tipo (subset; fuente: messages.py).
    // 0 => tipo fuera del subset (no se valida longitud contra tabla).
    function automatic logic [7:0] explen(input [7:0] t);
        case (t)
            8'h53: explen = 8'd12;   // S
            8'h52: explen = 8'd39;   // R
            8'h41: explen = 8'd36;   // A
            8'h46: explen = 8'd40;   // F
            8'h45: explen = 8'd31;   // E
            8'h43: explen = 8'd36;   // C
            8'h58: explen = 8'd23;   // X
            8'h44: explen = 8'd19;   // D
            8'h55: explen = 8'd35;   // U
            8'h50: explen = 8'd44;   // P
            default: explen = 8'd0;
        endcase
    endfunction

    function automatic logic [7:0] mbyte(input [351:0] m, input [6:0] i);
        mbyte = m[351 - 8*i -: 8];
    endfunction

    // palabra de cuerpo desde msg_reg (base = 11+8*bi); relleno 0 fuera
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
    // drenaje de ESTE ciclo (combinacional), en bytes.
    //   HDR  : 20    (de una vez)
    //   LEN  : 0     (solo espera y captura)
    //   CAP  : 2+len (drena el mensaje entero de una vez)
    //   W0/TS/BODY/NEXT : 0 (solo emiten desde msg_reg)
    // ------------------------------------------------------------------
    wire [6:0] drain_need =
        (st == ST_HDR) ? 7'd20 :
        (st == ST_CAP) ? 7'(2 + msg_len) :
        7'd0;

    wire [7:0] drain_int = (8'(drain_need) <= avail) ? {1'b0, drain_need} : 8'd0;

    // tready combinacional: hay sitio y no drenamos este ciclo (el drain se
    // consume en el flanco con la palabra que ya estaba en la cola).
    wire drain_active = (drain_int > 0) && (qn >= drain_int);
    wire can_aug = s_axis_tvalid && !drain_active && (qn + 8'(BYTES) <= QB);
    wire can_da  = s_axis_tvalid && drain_active && (8'(qn) - 8'(drain_int) + 8'(BYTES) <= QB);
    assign s_axis_tready = can_aug || can_da;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            st <= ST_HDR; q <= 0; qn <= 0;
            msg_idx <= 0; exp_seq <= 64'd1; this_seq <= 0; session_id <= 0;
            pack_left <= 0; pack_count <= 0; msg_len <= 0;
            in_subset <= 1'b0; msg_type <= 0; locate <= 0; ts_ns <= 0; len_ok <= 1'b0;
            eop_seen <= 1'b0;
            msg_reg <= 0; body_w <= 0; bi <= 0; hw <= 0;
            out_valid_reg <= 1'b0; out_data_reg <= 0; out_last_reg <= 1'b0;
            gap_detected <= 1'b0; error <= 1'b0;
        end else begin
            gap_detected <= 1'b0;
            error <= 1'b0;
            // latch de fin de datagrama: se fija cuando el stream marca tlast
            // (SEC-FRM-01/02) y se limpia al capturar un mensaje o un header.
            if (s_axis_tlast) eop_seen <= 1'b1;

            // ------------------------------------------------------------
            // cola: drena drain_int y acepta entrada en paralelo si cabe
            // ------------------------------------------------------------
            if (can_da) begin
                q <= ((q << (8*drain_int)) |
                      (QQ'(s_axis_tdata) << ((32'(QB-1) - 32'(qn) + 32'(drain_int))*8 - (DW-8))));
                qn <= qn - drain_int + 8'(BYTES);
            end else if (drain_active) begin
                q <= q << (8*drain_int);
                qn <= qn - drain_int;
            end else if (can_aug) begin
                q <= q | (QQ'(s_axis_tdata) << ((32'(QB-1) - 32'(qn))*8 - (DW-8)));
                qn <= qn + 8'(BYTES);
            end


            case (st)
                ST_HDR: begin
                    if (drain_int == 20) begin
                        // header de un datagrama nuevo: reinicia el latch de tlast.
                        // Solo si el tlast NO está alto en este mismo ciclo (un tlast
                        // coincidente marca el truncado de ESTE datagrama, SEC-FRM-02).
                        if (!s_axis_tlast) eop_seen <= 1'b0;
                        this_seq <= {pbyte(q,10), pbyte(q,11), pbyte(q,12), pbyte(q,13),
                                     pbyte(q,14), pbyte(q,15), pbyte(q,16), pbyte(q,17)};
                        pack_left <= {pbyte(q,18), pbyte(q,19)};
                        pack_count <= {pbyte(q,18), pbyte(q,19)};
                        // cambio de sesión: resetea el seq esperado (SEC-FRM-03),
                        // nunca cuenta como gap
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
                        // count=0 (SEC-FRM-04): paquete sin mensajes, avanza y
                        // sigue esperando el siguiente header sin emitir nada.
                        // exp_seq avanza por 0 => queda = seq del header actual.
                        if ({pbyte(q,18), pbyte(q,19)} == 16'h0) begin
                            exp_seq <= exp_seq + 64'({pbyte(q,18), pbyte(q,19)});
                            st <= ST_HDR;
                        end else begin
                            st <= ST_LEN;
                        end
                    end
                end

                // ------------------------------------------------
                // LEN: esperar el mensaje completo (2+len) para capturar a msg_reg
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
                            msg_reg <= q[(QB-2)*8 - 1 -: 352];
                            // longitud incoherente (SEC-PAR-03): para un tipo del
                            // subset la longitud declarada debe ser la de messages.py
                            len_ok <= !issubset(pbyte(q,2)) ||
                                      (explen(pbyte(q,2)) == 8'({pbyte(q,0), pbyte(q,1)})) ||
                                      (8'({pbyte(q,0), pbyte(q,1)}) < 11);
                            if (8'({pbyte(q,0), pbyte(q,1)}) < 11) error <= 1'b1;
                            eop_seen <= 1'b0;
                            st <= ST_CAP;
                        end else if (eop_seen) begin
                            // frame truncado (SEC-FRM-01): el datagrama ya terminó
                            // (tlast) y el mensaje declarado no está completo.
                            error <= 1'b1;
                            st <= ST_HDR;
                        end
                    end else if (eop_seen) begin
                        // ni siquiera el campo len completo (SEC-FRM-02)
                        error <= 1'b1;
                        st <= ST_HDR;
                    end
                end

                // ------------------------------------------------
                ST_CAP: begin
                    out_valid_reg <= 1'b0;
                    // len_ok = 0: longitud incoherente o truncado -> sin registro
                    st <= ((in_subset && msg_len >= 11 && len_ok) ? ST_W0 : ST_NEXT);
                end

                ST_W0: begin
                    if (out_free) begin
                        if (in_subset && msg_len >= 11) begin
                            // w0: {type, locate, len, idx} a 64 bits; a 32 bits
                            // el idx se emite en su propia word (w1)
                            if (DW == 32)
                                out_data_reg <= DW'({msg_type, locate, msg_len});
                            else
                                out_data_reg <= DW'({msg_type, locate, msg_len, msg_idx[31:0]});
                            out_valid_reg <= 1'b1;
                            out_last_reg  <= 1'b0;
                        end
                        hw <= 2'd1;
                        st <= ST_TS;
                    end
                end

                ST_TS: begin
                    if (out_free) begin
                        if (DW == 32) begin
                            // cabecera de 32 bits: w1=idx, w2=ts[31:0],
                            // w3={ts[47:32], 16'b0}
                            case (hw)
                                2'd1: out_data_reg <= DW'(msg_idx);
                                2'd2: out_data_reg <= DW'(ts_ns[31:0]);
                                default: out_data_reg <= DW'({ts_ns[47:32], 16'h0});
                            endcase
                            out_valid_reg <= 1'b1;
                            out_last_reg  <= 1'b0;
                            if (hw == 2'd3) st <= ST_BODY;
                            else hw <= hw + 1;
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
                    // tlast cierra el datagrama UDP de entrada (consumido;
                    // el count del framing gobierna el flujo real).
                    if (s_axis_tlast) begin
                        // marcador de cierre de paquete (no altera el flujo)
                    end
                    if (out_free) begin
                        msg_idx <= msg_idx + 1;
                        out_valid_reg <= 1'b0;
                        // off-by-one corregido: si quedan mensajes del MISMO
                        // paquete (pack_left aun por encima de 1 tras decremento),
                        // sigue ST_LEN; este era el ultimo (pack_left==1) -> ST_HDR
                        if (pack_left > 1) begin
                            pack_left <= pack_left - 1;
                            st <= ST_LEN;
                        end else begin
                            exp_seq <= this_seq + 64'(pack_count);
                            st <= ST_HDR;
                        end
                    end
                end

                default: st <= ST_HDR;
            endcase
        end
    end

endmodule
