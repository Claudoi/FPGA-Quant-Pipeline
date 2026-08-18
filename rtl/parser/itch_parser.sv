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
// A DW=32 (fase3-uram, recorte del Anexo A): w0={type,locate,len},
// w1=msg_idx, w2..=cuerpo — SIN words de timestamp (el book no las consume;
// contrato enmendado por specs/fase3-uram/spec.md, criterio 1).
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
// afecta a fase 3 (ver docs/writeup/lecciones-aprendidas.md, §1).
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
    reg  [7:0]    qn;      // 8 bits cubren el QB máximo soportado de 128 bytes

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
    reg           drop_packet;
    reg  [351:0]  msg_reg;
    reg  [6:0]    body_w;
    reg  [6:0]    bi;
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

    // Longitud total esperada de los 22 tipos canónicos (fuente: messages.py).
    // 0 => tipo desconocido; se consume sin decodificar ni validar por tabla.
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

    wire [7:0] in_nbytes = keep_nbytes(s_axis_tkeep);
    wire keep_shape_ok = keep_is_msb_prefix(s_axis_tkeep);
    wire in_keep_ok = keep_shape_ok &&
                      (s_axis_tlast || s_axis_tkeep == {BYTES{1'b1}});
    wire [DW-1:0] in_compact = in_keep_ok ?
        (s_axis_tdata >> (8 * (32'(BYTES) - 32'(in_nbytes)))) : '0;

    // tready combinacional: hay sitio después del posible drenaje de este
    // ciclo. Durante un descarte se acepta todo hasta el tlast físico.
    wire drain_active = (drain_int > 0) && (qn >= drain_int);
    wire [7:0] base_n = drain_active ? qn - drain_int : qn;
    // Tras aceptar tlast no se prefetchea el datagrama siguiente hasta cerrar
    // o descartar el actual: la cola no guarda marcadores de frontera internos.
    wire can_aug = s_axis_tvalid && !eop_seen && !drain_active &&
                   (qn + in_nbytes <= QB);
    wire can_da  = s_axis_tvalid && !eop_seen && drain_active &&
                   (base_n + in_nbytes <= QB);
    wire invalid_offer = s_axis_tvalid && !eop_seen && !in_keep_ok;
    assign s_axis_tready = drop_packet || invalid_offer || can_aug || can_da;
    wire in_take = s_axis_tvalid && s_axis_tready;
    wire [QQ-1:0] append_bits = QQ'(in_compact) <<
        (8 * (32'(QB) - 32'(base_n) - 32'(in_nbytes)));
    wire [7:0] qn_post = base_n +
        ((in_take && in_keep_ok) ? in_nbytes : 8'd0);
    wire eop_eff = eop_seen ||
                   (in_take && in_keep_ok && s_axis_tlast);
    wire record_active = (st >= ST_CAP) && (st <= ST_NEXT);

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            st <= ST_HDR; q <= 0; qn <= 0;
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
                // latch de fin de datagrama: se fija cuando el stream marca tlast
                // (SEC-FRM-01/02) y se limpia al cerrar o descartar el datagrama.
                if (in_take && s_axis_tlast) eop_seen <= 1'b1;

                // ------------------------------------------------------------
                // cola: drena drain_int y acepta entrada válida en paralelo
                // ------------------------------------------------------------
                if (can_da) begin
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
                        // Se usa el header, no el valor previo de exp_seq: en una
                        // sesión nueva ambas asignaciones ocurren en este flanco.
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
                        // tlast antes de completar los 20 bytes de cabecera.
                        error <= 1'b1;
                        q <= '0;
                        qn <= '0;
                        eop_seen <= 1'b0;
                        st <= ST_HDR;
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
                            // Todo tipo canónico se valida, aunque no emita registro.
                            // Un tipo desconocido (explen=0) sigue como passthrough.
                            len_ok <= (explen(pbyte(q,2)) == 0) ||
                                      (explen(pbyte(q,2)) ==
                                       8'({pbyte(q,0), pbyte(q,1)}));
                            if ((8'({pbyte(q,0), pbyte(q,1)}) < 11) ||
                                ((explen(pbyte(q,2)) != 0) &&
                                 (explen(pbyte(q,2)) !=
                                  8'({pbyte(q,0), pbyte(q,1)}))))
                                error <= 1'b1;
                            st <= ST_CAP;
                        end else if (eop_seen) begin
                            // frame truncado (SEC-FRM-01): el datagrama ya terminó
                            // (tlast) y el mensaje declarado no está completo.
                            error <= 1'b1;
                            q <= 0;
                            qn <= 0;
                            eop_seen <= 1'b0;
                            pack_left <= 0;
                            st <= ST_HDR;
                        end
                    end else if (eop_seen) begin
                        // ni siquiera el campo len completo (SEC-FRM-02)
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
                        // len_ok = 0: longitud incoherente o truncado -> sin registro
                        st <= ((in_subset && msg_len >= 11 && len_ok) ? ST_W0 : ST_NEXT);
                    end
                end

                ST_W0: begin
                    if (out_free) begin
                        if (in_subset && msg_len >= 11) begin
                            // w0: {type, locate, len, idx} a 64 bits; a 32 bits
                            // el idx se emite en su propia word (w1, recorte del
                            // Anexo A: las words de ts se eliminaron — el book
                            // no las consume; specs/fase3-uram criterio 1)
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
                            // cabecera de 32 bits recortada: una sola word
                            // w1=msg_idx; el cuerpo arranca en w2
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

                    default: st <= ST_HDR;
                endcase
            end
        end
    end

endmodule
