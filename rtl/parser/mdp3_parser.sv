// mdp3_parser.sv — parser CME MDP 3.0 (SBE) a line-rate (fase 4, Anexo M).
//
// Consume el payload UDP ya decapado: paquete = MsgSeqNum u32 LE + SendingTime
// u64 LE (12 B), seguido de mensajes con framing por msg_size (u16 LE que
// INCLUYE el prefijo de 10 B: msg_size + cabecera SBE 8 B con
// blockLength/templateId/schemaId/version u16 LE). Cada paquete llega como un
// burst AXI-Stream (tlast = fin de paquete). Emite records normalizados del
// Anexo M (words de 32 bits MSB-first, tlast por record) bit a bit contra el
// golden model (golden_model/mdp3/, schema templates_FixBinary_v12.xml).
//
// Subset de libro (offsets constantes derivados del schema v12):
//   46 MDIncrementalRefreshBook: root TS/MEI (bl 11), NoMDEntries (groupSize,
//      bl 32: Px@0,Sz@8,Sec@12,Rpt@16,No@20,Lvl@24,Act@25,Typ@26) +
//      NoOrderIDEntries (groupSize8Byte, bl 24: OrderID@0,Priority@8,Dq@16,
//      Ref@20,OA@21). MBP = 13 words; MBOFD = 18 words con ReferenceID
//      resuelto contra la entry MBP del MISMO mensaje (fuera de rango:
//      error + ceros, contrato #5).
//   47 MDIncrementalRefreshOrderBook: root TS/MEI (bl 11), NoMDEntries
//      (groupSize, bl 40: OrderID@0,Priority@8,Px@16,Dq@24,Sec@28,Act@32,
//      Typ@33). MBOFD.
//   52 SnapshotFullRefresh: root (bl 59: Sec@8,Rpt@12,TS@16), NoMDEntries
//      (groupSize, bl 22: Px@0,Sz@8,No@12,Lvl@16,Typ@21). MBP.
//   53 SnapshotFullRefreshOrderBook: root (bl 28: Sec@8,TS@20), NoMDEntries
//      (groupSize, bl 29: OrderID@0,Priority@8,Px@16,Dq@24,Typ@28). MBOFD.
// PRICE9/PRICENULL9: mantissa i64 LE; el exponent constante -9 NO se
// transmite (w10/w15 = 0xF7 << 24). Resto de templates: passthrough crudo
// (w0 = tpl<<16|msg_size, w1 = sid<<16|version, cuerpo crudo rellenado).
//
// ARQUITECTURA: captura ping-pong a line-rate. La entrada (1 palabra/ciclo)
// se acumula en una cola de bytes; el FSM de captura consume el framing
// (header de paquete de 12 B, msg_size, cuerpo) escribiendo los mensajes
// completos en dos buffers alternos (MAX_MSG bytes). Al completar un mensaje
// se marca (occ) para decodificación mientras la entrada llena el otro
// buffer; la decodificación (FSM de 32 bits por palabra) arma los records en
// rrec y los empuja a una FIFO de salida que el emisor drena a AXI-Stream.
// La entrada solo se para si ambos buffers están ocupados (mensajes MBOFD
// emiten 72 B por ~43 B de entrada: limitación inherente al Anexo M, igual
// que LIN-01 de fase 1). Sin RAM: el 46 resuelve el ReferenceID releyendo la
// entry MBP del mismo buffer. DW=32 en esta iteración (Anexo M definido en
// words de 32 bits); DW=64 en regresión (iter 3+, con byte-enables).
module mdp3_parser #(
    parameter int DW = 32
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

localparam logic [3:0]  BYTES     = 4'(DW / 8);
    localparam logic [8:0]  MAX_MSG    = 256;   // bytes por buffer (corpus <= ~250 B)
    localparam logic [8:0]  FIFO_DEPTH = 256;   // words de salida (32 bits c/u)
    localparam logic [7:0]  PKT_HDR    = 12;
    localparam logic [7:0]  MSG_PREFIX = 10;
    localparam logic [7:0]  EXP_BYTE   = 8'hF7; // PRICE9/PRICENULL9 exponent = -9

    localparam logic [15:0] TPL_46 = 16'd46, TPL_47 = 16'd47, TPL_52 = 16'd52, TPL_53 = 16'd53;

    // offsets dentro del cuerpo (desde byte 10 del mensaje), LE
    localparam logic [31:0] O46_TS=0, O46_MEI=8, O46_DIM=11, O46_ENT=14, O46_BL1=32, O46_BL2=24;
    localparam logic [31:0] O46_PX=0, O46_SZ=8, O46_SEC=12, O46_RPT=16, O46_NO=20, O46_LVL=24,
                           O46_ACT=25, O46_TYP=26;
    localparam logic [31:0] O46_OID=0, O46_PRI=8, O46_DQ=16, O46_REF=20, O46_OA=21;
    localparam logic [31:0] O47_OID=0, O47_PRI=8, O47_PX=16, O47_DQ=24, O47_SEC=28,
                           O47_ACT=32, O47_TYP=33, O47_BL=40;
    localparam logic [31:0] O52_SEC=8, O52_RPT=12, O52_TS=16, O52_DIM=59, O52_ENT=62, O52_BL=22;
    localparam logic [31:0] O52_PX=0, O52_SZ=8, O52_NO=12, O52_LVL=16, O52_TYP=21;
    localparam logic [31:0] O53_SEC=8, O53_TS=20, O53_DIM=28, O53_ENT=31, O53_BL=29;
    localparam logic [31:0] O53_OID=0, O53_PRI=8, O53_PX=16, O53_DQ=24, O53_TYP=28;

    // ── cola de bytes de entrada (FIFO circular de MAX_MSG bytes) ──────────
    // qw = puntero de escritura, qh = puntero de lectura (mod MAX_MSG).
    // qavail = bytes ya escritos sin consumir; qbyte() lee del FIFO y, para
    // el word que entra en este ciclo (k >= qavail), directamente de tdata.
    reg [7:0] qbytes [MAX_MSG];
    reg [7:0] qw, qh;

    function automatic [7:0] qbyte;
        input [31:0] k;
        if (k < 32'(qavail))
            qbyte = qbytes[(32'(qh) + k) % 32'(MAX_MSG)];
        else
            qbyte = s_axis_tdata[8*(32'(BYTES) - 1 - (k - 32'(qavail))) +: 8];
    endfunction

    wire [15:0] qavail = 16'((32'(qw) + 32'(MAX_MSG) - 32'(qh)) % 32'(MAX_MSG));
    wire [15:0] qavail_eff =
        16'(qavail) + (s_axis_tvalid && s_axis_tready ? 16'(BYTES) : 16'd0);

    // ── buffers de mensaje ping-pong ─────────────────────────────────────────
    reg [7:0] mbuf0 [MAX_MSG];
    reg [7:0] mbuf1 [MAX_MSG];
    reg       occ [2];

    function automatic [7:0] mrb;
        input [31:0] off;
        input        sel;
        mrb = sel ? mbuf1[off % 32'd256] : mbuf0[off % 32'd256];
    endfunction
    function automatic [15:0] mru16;
        input [31:0] off;
        input        sel;
        mru16 = 16'({8'h0, mrb(off, sel)} | ({8'h0, mrb(off+1, sel)} << 8));
    endfunction
    function automatic [31:0] mru32;
        input [31:0] off;
        input        sel;
        mru32 = 32'(mrb(off, sel)) |
                32'(mrb(off+1, sel)) << 8 |
                32'(mrb(off+2, sel)) << 16 |
                32'(mrb(off+3, sel)) << 24;
    endfunction
    function automatic [63:0] mru64;
        input [31:0] off;
        input        sel;
        mru64 = 64'(mru32(off, sel)) | (64'(mru32(off+4, sel)) << 32);
    endfunction

    function automatic [15:0] hdr_cons;
        // bytes consumibles del header de paquete en este ciclo (CS_HDR)
        hdr_cons = (qavail_eff > 16'(PKT_HDR) - 16'(hdr_pos)) ?
                   (16'(PKT_HDR) - 16'(hdr_pos)) : qavail_eff;
    endfunction

    // ── captura ──────────────────────────────────────────────────────────────
    reg [2:0]  cst;   // CS_WAIT=4 → 3 bits mínimo
    localparam logic [2:0] CS_HDR=0, CS_SIZE=1, CS_BODY=2, CS_SKIP=3, CS_WAIT=4;
    reg [7:0]  hdr_pos;
    reg        gap_check;
    reg        first_pkt;
    reg        wait_hdr;   // CS_WAIT entrado por tlast → reanudar en CS_HDR
    reg [31:0] seq, exp_seq;
    reg        cap_sel;
    reg [15:0] cap_len;
    reg [15:0] cap_size, skip_left;

    // ── decodificación ───────────────────────────────────────────────────────
    reg [3:0]  dst;
    localparam logic [3:0] DS_IDLE=0, DS_HDR=1, DS_ROOT=2, DS_G1=3, DS_G1_ENT=4, DS_PUSH=5,
                     DS_G2_DIM=6, DS_G2_ENT=7, DS_PASS=8, DS_DONE=9;
    reg        dec_sel;
    reg [15:0] d_tpl, d_size, d_sid, d_ver;
    reg [63:0] d_ts;
    reg [7:0]  d_mei;
    reg [31:0] d_sec, d_rpt;
    reg [15:0] g1_base, g2_base;
    reg [7:0]  g1_n, g2_n, g_idx;
    reg [31:0] rrec [18];
    reg [4:0]  rlen, r_idx;
    reg        g1_mode;
    reg [1:0]  p_n;
    reg [15:0] p_off;
    reg [31:0] p_word;
    reg [4:0]  p_cnt;

    // ── FIFO de salida (32 bits/palabra) ─────────────────────────────────────
    reg [31:0] f_mem [FIFO_DEPTH];
    reg        f_tl  [FIFO_DEPTH];
    reg [8:0]  f_cnt;          // words ocupadas (push - pop, un solo escritor)
    reg [7:0]  f_head, f_tail; // punteros circulares (wrappean solos)


    // push/pop de la FIFO: el núcleo emite push_commit (combinacional sobre su
    // estado) y el emisor muestra/popa. f_cnt se actualiza en el núcleo con el
    // balance neto; f_head solo en el emisor (single-driver).
    wire pop = m_axis_tvalid && m_axis_tready;
    wire push_commit =
        (dst == DS_PUSH  && f_cnt < FIFO_DEPTH && r_idx < rlen) ||
        (dst == DS_PASS  && f_cnt < FIFO_DEPTH &&
         (p_n == 0 ||
          p_n == 1 ||
          (p_n == 2 && p_off < d_size && (p_cnt == 3 || p_off + 1 == d_size))));

    // ── emisor: FIFO → m_axis ────────────────────────────────────────────────
    always @(posedge clk) begin
        if (!rst_n) begin
            m_axis_tvalid <= 0;
            m_axis_tdata  <= 0;
            m_axis_tlast  <= 0;
            f_head        <= 0;
        end else begin
            if (m_axis_tvalid && m_axis_tready)
                f_head <= f_head + 1;
            if (!m_axis_tvalid || m_axis_tready) begin
                m_axis_tvalid <= ((f_cnt > 9'd1) || (f_cnt == 9'd1 && !m_axis_tvalid));
                m_axis_tdata  <= f_mem[f_head + (m_axis_tvalid ? 8'd1 : 8'd0)];
                m_axis_tlast  <= f_tl [f_head + (m_axis_tvalid ? 8'd1 : 8'd0)];
            end
        end
    end

    // ── núcleo: captura + decodificación + push a FIFO ───────────────────────
    always @(posedge clk) begin
        if (!rst_n) begin
            s_axis_tready <= 0;
            qw <= 0; qh <= 0;
            cst <= CS_HDR; hdr_pos <= 0;
            gap_check <= 0; first_pkt <= 0; wait_hdr <= 0;
            seq <= 0; exp_seq <= 0;
            cap_sel <= 0; cap_len <= 0; cap_size <= 0; skip_left <= 0;
            occ[0] <= 0; occ[1] <= 0;
            dst <= DS_IDLE; dec_sel <= 0;
            d_tpl <= 0; d_size <= 0; d_sid <= 0; d_ver <= 0;
            d_ts <= 0; d_mei <= 0; d_sec <= 0; d_rpt <= 0;
            g1_base <= 0; g2_base <= 0; g1_n <= 0; g2_n <= 0; g_idx <= 0;
            rlen <= 0; r_idx <= 0; g1_mode <= 0;
            p_n <= 0; p_off <= 0; p_word <= 0; p_cnt <= 0;
            f_cnt <= 0; f_tail <= 0;
            gap_detected <= 0; error <= 0;
        end else begin
            gap_detected <= 0;
            error <= 0;

            // cola de bytes: apend del word entrante
            if (s_axis_tvalid && s_axis_tready) begin
                for (integer k = 0; k < BYTES; k = k + 1)
                    qbytes[(32'(qw) + 32'(k)) % 32'(MAX_MSG)] <=
                        s_axis_tdata[8*(32'(BYTES) - 1 - k) +: 8];
                qw <= 8'((32'(qw) + 32'(BYTES)) % 32'(MAX_MSG));
            end

            // ── captura ────────────────────────────────────────────────────
            case (cst)
                CS_HDR: begin
                    if (qavail_eff != 16'd0) begin
                        if (hdr_pos < PKT_HDR) begin
                            for (integer k = 0; k < PKT_HDR; k = k + 1)
                                if (k < 32'(hdr_cons()) && (32'(hdr_pos) + k) < 4)
                                    seq[8*(32'(hdr_pos) + k) +: 8] <= qbyte(k);
                            qh <= 8'((16'(qh) + hdr_cons()) % 16'(MAX_MSG));
                            hdr_pos <= 8'(16'(hdr_pos) + hdr_cons());
                            if (16'(hdr_pos) + hdr_cons() >= 16'(PKT_HDR)) begin
                                gap_check <= 1;
                                cst <= CS_SIZE;
                            end
                        end
                    end
                    if (s_axis_tlast) begin
                        error <= 1;
                        hdr_pos <= 0;
                        cst <= CS_HDR;
                    end
                end

                CS_SIZE: begin
                    if (qavail_eff >= 16'd2) begin
                        if (gap_check) begin
                            if (first_pkt && seq != exp_seq)
                                gap_detected <= 1;
                            exp_seq <= seq + 1;
                            first_pkt <= 1;
                            gap_check <= 0;
                        end
                        if ({qbyte(1), qbyte(0)} < 16'(MSG_PREFIX) ||
                            {qbyte(1), qbyte(0)} > 16'(MAX_MSG)) begin
                            error <= 1;
                            skip_left <= {qbyte(1), qbyte(0)} - 16'd2;
                            qh <= 8'((16'(qh) + 16'd2) % 16'(MAX_MSG));
                            cst <= CS_SKIP;
                        end else begin
                            // msg_size (2 B) forma parte del mensaje: se
                            // almacena en mbuf[0..1] antes del cuerpo
                            if (cap_sel)
                                mbuf1[0] <= qbyte(0);
                            else
                                mbuf0[0] <= qbyte(0);
                            if (cap_sel)
                                mbuf1[1] <= qbyte(1);
                            else
                                mbuf0[1] <= qbyte(1);
                            cap_size <= {qbyte(1), qbyte(0)};
                            cap_len <= 2;
                            qh <= 8'((16'(qh) + 16'd2) % 16'(MAX_MSG));
                            cst <= CS_BODY;
                        end
                    end
                    if (s_axis_tlast) begin
                        error <= 1;
                        hdr_pos <= 0;
                        cst <= CS_HDR;
                    end
                end

                CS_BODY: begin
                    // Consume en este ciclo la cantidad de bytes que realmente
                    // escribe: la menor entre lo que queda del mensaje
                    // (cap_size-cap_len), lo disponible (qavail_eff) y el ancho
                    // de captura por ciclo (2*BYTES). Hacerlo distinto (p. ej.
                    // avanzar cap_len/qh por qavail_eff escribiendo solo
                    // 2*BYTES) deja bytes del mensaje huérfanos en el buffer.
                    if (32'(qavail_eff) != 32'd0) begin
                        integer cnt;
                        cnt = (32'(cap_size) - 32'(cap_len) < 32'(qavail_eff)) ?
                              (32'(cap_size) - 32'(cap_len)) : 32'(qavail_eff);
                        if (cnt > 32'(2*BYTES)) cnt = 32'(2*BYTES);
                        for (integer k = 0; k < 2*BYTES; k = k + 1)
                            if (k < cnt)
                                if (cap_sel)
                                    mbuf1[(32'(cap_len) + k) % 32'(MAX_MSG)] <= qbyte(k);
                                else
                                    mbuf0[(32'(cap_len) + k) % 32'(MAX_MSG)] <= qbyte(k);
                        cap_len <= cap_len + cnt[15:0];
                        qh <= 8'((32'(qh) + cnt) % 32'(MAX_MSG));
                        if (32'(cap_len) + cnt >= 32'(cap_size)) begin
                            // mensaje completo
                            occ[cap_sel] <= 1;
                            if (s_axis_tlast) begin
                                // paquete termina en el borde del mensaje: descartar
                                // el padding residual (burst a alinear a palabra) y
                                // el header de 12 B del siguiente paquete se lee
                                // desde un burst nuevo (colas reset ad hoc)
                                qh <= 0; qw <= 0;
                                hdr_pos <= 0;
                                if (occ[~cap_sel] == 0) begin
                                    cap_sel <= ~cap_sel;
                                    wait_hdr <= 0;
                                    cst <= CS_HDR;
                                end else begin
                                    wait_hdr <= 1;
                                    cst <= CS_WAIT;
                                end
                            end else begin
                                if (occ[~cap_sel] == 0) begin
                                    cap_sel <= ~cap_sel;
                                    wait_hdr <= 0;
                                    cst <= CS_SIZE;
                                end else begin
                                    wait_hdr <= 0;
                                    cst <= CS_WAIT;
                                end
                            end
                        end else if (s_axis_tlast) begin
                            error <= 1;   // mensaje truncado por tlast
                            hdr_pos <= 0;
                            cst <= CS_HDR;
                        end
                    end
                end

                CS_SKIP: begin
                    if (qavail_eff >= skip_left) begin
                        qh <= 8'((16'(qh) + skip_left) % 16'(MAX_MSG));
                        cst <= CS_SIZE;
                    end else if (qavail_eff != 16'd0) begin
                        qh <= 8'((16'(qh) + 16'(qavail_eff)) % 16'(MAX_MSG));
                        skip_left <= skip_left - qavail_eff;
                    end
                    if (s_axis_tlast) begin
                        error <= 1;
                        hdr_pos <= 0;
                        cst <= CS_HDR;
                    end
                end

                CS_WAIT: begin
                    if (occ[~cap_sel] == 0) begin
                        cap_sel <= ~cap_sel;
                        cst <= wait_hdr ? CS_HDR : CS_SIZE;
                        wait_hdr <= 0;
                    end
                end
                default: begin
                    // cst no puede alcanzar 5..7 con la lógica actual; por
                    // robustez se vuelve a CS_HDR (recuperación ante X)
                    error <= 1;
                    hdr_pos <= 0;
                    cst <= CS_HDR;
                end
            endcase

            s_axis_tready <= (16'(qavail_eff) <= 16'(MAX_MSG) - 16'(BYTES)) && (cst != CS_WAIT);

            // ── decodificación ─────────────────────────────────────────────
            case (dst)
                DS_IDLE: begin
                    if (occ[0] || occ[1]) begin
                        dec_sel <= occ[0] ? 1'b0 : 1'b1;
                        dst <= DS_HDR;
                    end
                end
                DS_HDR: begin
                    d_tpl  <= mru16(4, dec_sel);
                    d_sid  <= mru16(6, dec_sel);
                    d_ver  <= mru16(8, dec_sel);
                    d_size <= mru16(0, dec_sel);
                    p_n    <= 0;   // passthrough vuelve a arrancar en w0
                    dst <= (mru16(4, dec_sel) == TPL_46 ||
                            mru16(4, dec_sel) == TPL_47 ||
                            mru16(4, dec_sel) == TPL_52 ||
                            mru16(4, dec_sel) == TPL_53) ? DS_ROOT : DS_PASS;
                end
                DS_ROOT: begin
                    case (d_tpl)
                        TPL_46, TPL_47: begin
                            d_ts  <= mru64(32'(MSG_PREFIX) + O46_TS, dec_sel);
                            d_mei <= mrb(32'(MSG_PREFIX) + O46_MEI, dec_sel);
                            g1_n  <= mrb(32'(MSG_PREFIX) + O46_DIM + 2, dec_sel);
                            g1_base <= 16'(MSG_PREFIX) + 16'(O46_ENT);
                            dst <= DS_G1;
                        end
                        TPL_52: begin
                            d_sec <= mru32(32'(MSG_PREFIX) + O52_SEC, dec_sel);
                            d_rpt <= mru32(32'(MSG_PREFIX) + O52_RPT, dec_sel);
                            d_ts  <= mru64(32'(MSG_PREFIX) + O52_TS, dec_sel);
                            d_mei <= 0;
                            g1_n  <= mrb(32'(MSG_PREFIX) + O52_DIM + 2, dec_sel);
                            g1_base <= 16'(MSG_PREFIX) + 16'(O52_ENT);
                            dst <= DS_G1;
                        end
                        TPL_53: begin
                            d_sec <= mru32(32'(MSG_PREFIX) + O53_SEC, dec_sel);
                            d_ts  <= mru64(32'(MSG_PREFIX) + O53_TS, dec_sel);
                            d_mei <= 0;
                            g1_n  <= mrb(32'(MSG_PREFIX) + O53_DIM + 2, dec_sel);
                            g1_base <= 16'(MSG_PREFIX) + 16'(O53_ENT);
                            dst <= DS_G1;
                        end
                        default: dst <= DS_DONE;
                    endcase
                end
                DS_G1: begin
                    g_idx <= 0;
                    if (g1_n == 0) begin
                        if (d_tpl == TPL_46) dst <= DS_G2_DIM;
                        else dst <= DS_DONE;
                    end else
                        dst <= DS_G1_ENT;
                end
                DS_G1_ENT: begin
                    if (g_idx < g1_n) begin
                        g1_mode <= 1;
                        dst <= DS_PUSH;
                    end else begin
                        if (d_tpl == TPL_46) dst <= DS_G2_DIM;
                        else dst <= DS_DONE;
                    end
                end
                DS_G2_DIM: begin
                    g2_base <= g1_base + 16'(g1_n) * 16'(O46_BL1) + 16'd8;
                    g2_n    <= mrb(32'(g1_base) + 32'(g1_n) * 32'(O46_BL1) + 32'd7, dec_sel);
                    g1_mode <= 0;
                    g_idx   <= 0;
                    dst <= DS_G2_ENT;
                end
                DS_G2_ENT: begin
                    if (g_idx < g2_n) dst <= DS_PUSH;
                    else dst <= DS_DONE;
                end
                DS_PUSH: begin
                    if (f_cnt < FIFO_DEPTH) begin
                        if (r_idx < rlen) begin
                            f_mem[f_tail] <= rrec[r_idx];
                            f_tl[f_tail]  <= (r_idx == rlen - 1);
                            f_tail <= f_tail + 1;
                            r_idx  <= r_idx + 1;
                        end else begin
                            r_idx <= 0;
                            g_idx <= g_idx + 1;
                            dst <= g1_mode ? DS_G1_ENT : DS_G2_ENT;
                        end
                    end
                end
                DS_PASS: begin
                    if (f_cnt < FIFO_DEPTH) begin
                        case (p_n)
                            0: begin
                                f_mem[f_tail] <= {d_tpl, d_size};
                                f_tl[f_tail]  <= 0;
                                f_tail <= f_tail + 1;
                                p_n <= 1;
                            end
                            1: begin
                                f_mem[f_tail] <= {d_sid, d_ver};
                                f_tl[f_tail]  <= (d_size == 16'(MSG_PREFIX));
                                f_tail <= f_tail + 1;
                                p_off <= 16'(MSG_PREFIX);
                                p_word <= 0;
                                p_cnt <= 0;
                                p_n <= (d_size == 16'(MSG_PREFIX)) ? 3 : 2;
                            end
                            2: begin
                                if (p_off < d_size) begin
                                    p_word <= (p_word << 8) | 32'(mrb(p_off, dec_sel));
                                    p_off  <= p_off + 1;
                                    p_cnt  <= p_cnt + 1;
                                    if (p_cnt == 5'd3 || p_off + 16'd1 == d_size) begin
                                        // alinear a la izquierda la palabra final
                                        // parcial (data al tope, ceros al final)
                                        f_mem[f_tail] <= ((p_word << 8) |
                                                          32'(mrb(p_off, dec_sel)))
                                                         << (8 * (3 - p_cnt));
                                        f_tl[f_tail]  <= (p_off + 16'd1 == d_size);
                                        f_tail <= f_tail + 1;
                                        p_word <= 0;
                                        p_cnt  <= 0;
                                        if (p_off + 16'd1 == d_size) p_n <= 3;
                                    end
                                end
                            end
                            3: dst <= DS_DONE;
                            default: dst <= DS_DONE;   // recuperación ante X
                        endcase
                    end
                end
                DS_DONE: begin
                    occ[dec_sel] <= 0;
                    dst <= DS_IDLE;
                end
                default: begin
                    // dst no puede alcanzar 10..15; recuperación segura
                    dst <= DS_DONE;
                end
            endcase

            // ── preparación de records (en DS_G1_ENT / DS_G2_ENT) ──────────
            case (dst)
                DS_G1_ENT: begin
                    if (g_idx < g1_n) begin
                        case (d_tpl)
                            TPL_46: begin
                                // MBP (46 NoMDEntries): 13 words
                                reg [31:0] eb;
                                eb = 32'(g1_base) + 32'(g_idx) * 32'(O46_BL1);
                                rlen <= 13;
                                rrec[0] <= {d_tpl, d_size};
                                rrec[1] <= {d_sid, d_ver};
                                rrec[2] <= d_ts[31:0];
                                rrec[3] <= d_ts[63:32];
                                rrec[4] <= {d_mei, 24'h0};
                                rrec[5] <= mru32(eb + O46_SEC, dec_sel);
                                rrec[6] <= mru32(eb + O46_RPT, dec_sel);
                                rrec[7] <= {8'h0,
                                            mrb(eb + O46_ACT, dec_sel),
                                            mrb(eb + O46_TYP, dec_sel),
                                            8'h0};
                                rrec[8] <= mru32(eb + O46_PX, dec_sel);
                                rrec[9] <= mru32(eb + O46_PX + 4, dec_sel);
                                rrec[10] <= {EXP_BYTE, 24'h0};
                                rrec[11] <= mru32(eb + O46_SZ, dec_sel);
                                rrec[12] <= {mru32(eb + O46_NO, dec_sel)[15:0],
                                             8'h0,
                                             mrb(eb + O46_LVL, dec_sel)};
                            end
                            TPL_47: begin
                                // MBOFD (47 NoMDEntries): 18 words
                                reg [31:0] eb;
                                eb = 32'(g1_base) + 32'(g_idx) * 32'(O47_BL);
                                rlen <= 18;
                                rrec[0] <= {d_tpl, d_size};
                                rrec[1] <= {d_sid, d_ver};
                                rrec[2] <= d_ts[31:0];
                                rrec[3] <= d_ts[63:32];
                                rrec[4] <= {d_mei, 24'h0};
                                rrec[5] <= mru32(eb + O47_SEC, dec_sel);
                                rrec[6] <= 0;
                                rrec[7] <= {8'h1,
                                            mrb(eb + O47_ACT, dec_sel),
                                            mrb(eb + O47_TYP, dec_sel),
                                            8'h0};
                                rrec[8] <= mru32(eb + O47_OID, dec_sel);
                                rrec[9] <= mru32(eb + O47_OID + 4, dec_sel);
                                rrec[10] <= mru32(eb + O47_PRI, dec_sel);
                                rrec[11] <= mru32(eb + O47_PRI + 4, dec_sel);
                                rrec[12] <= 0;
                                rrec[13] <= mru32(eb + O47_PX, dec_sel);
                                rrec[14] <= mru32(eb + O47_PX + 4, dec_sel);
                                rrec[15] <= {EXP_BYTE, 24'h0};
                                rrec[16] <= mru32(eb + O47_DQ, dec_sel);
                                rrec[17] <= 0;
                            end
                            TPL_52: begin
                                // MBP (52 NoMDEntries): 13 words, sec/rpt root
                                reg [31:0] eb;
                                eb = 32'(g1_base) + 32'(g_idx) * 32'(O52_BL);
                                rlen <= 13;
                                rrec[0] <= {d_tpl, d_size};
                                rrec[1] <= {d_sid, d_ver};
                                rrec[2] <= d_ts[31:0];
                                rrec[3] <= d_ts[63:32];
                                rrec[4] <= 0;
                                rrec[5] <= d_sec;
                                rrec[6] <= d_rpt;
                                rrec[7] <= {8'h0, 8'h0,
                                            mrb(eb + O52_TYP, dec_sel), 8'h0};
                                rrec[8] <= mru32(eb + O52_PX, dec_sel);
                                rrec[9] <= mru32(eb + O52_PX + 4, dec_sel);
                                rrec[10] <= {EXP_BYTE, 24'h0};
                                rrec[11] <= mru32(eb + O52_SZ, dec_sel);
                                rrec[12] <= {mru32(eb + O52_NO, dec_sel)[15:0],
                                             8'h0,
                                             mrb(eb + O52_LVL, dec_sel)};
                            end
                            TPL_53: begin
                                // MBOFD (53 NoMDEntries): 18 words, sec root
                                reg [31:0] eb;
                                eb = 32'(g1_base) + 32'(g_idx) * 32'(O53_BL);
                                rlen <= 18;
                                rrec[0] <= {d_tpl, d_size};
                                rrec[1] <= {d_sid, d_ver};
                                rrec[2] <= d_ts[31:0];
                                rrec[3] <= d_ts[63:32];
                                rrec[4] <= 0;
                                rrec[5] <= d_sec;
                                rrec[6] <= 0;
                                rrec[7] <= {8'h1, 8'h0,
                                            mrb(eb + O53_TYP, dec_sel), 8'h0};
                                rrec[8] <= mru32(eb + O53_OID, dec_sel);
                                rrec[9] <= mru32(eb + O53_OID + 4, dec_sel);
                                rrec[10] <= mru32(eb + O53_PRI, dec_sel);
                                rrec[11] <= mru32(eb + O53_PRI + 4, dec_sel);
                                rrec[12] <= 0;
                                rrec[13] <= mru32(eb + O53_PX, dec_sel);
                                rrec[14] <= mru32(eb + O53_PX + 4, dec_sel);
                                rrec[15] <= {EXP_BYTE, 24'h0};
                                rrec[16] <= mru32(eb + O53_DQ, dec_sel);
                                rrec[17] <= 0;
                            end
                            default: begin
                                rlen <= 0;
                                error <= 1;
                            end
                        endcase
                    end
                end
                DS_G2_ENT: begin
                    if (g_idx < g2_n) begin
                        // MBOFD (46 NoOrderIDEntries): 18 words, ReferenceID
                        // contra la entry MBP del mismo mensaje
                        reg [31:0] eb, src;
                        reg [7:0]  rref;
                        eb   = 32'(g2_base) + 32'(g_idx) * 32'(O46_BL2);
                        rref = mrb(eb + O46_REF, dec_sel);
                        src  = 32'(g1_base) + 32'(rref) * 32'(O46_BL1);
                        rlen <= 18;
                        rrec[0] <= {d_tpl, d_size};
                        rrec[1] <= {d_sid, d_ver};
                        rrec[2] <= d_ts[31:0];
                        rrec[3] <= d_ts[63:32];
                        rrec[4] <= {d_mei, 24'h0};
                        rrec[5] <= (rref < g1_n) ? mru32(src + O46_SEC, dec_sel) : 32'd0;
                        rrec[6] <= (rref < g1_n) ? mru32(src + O46_RPT, dec_sel) : 32'd0;
                        rrec[7] <= {8'h1, mrb(eb + O46_OA, dec_sel),
                                    (rref < g1_n) ? mrb(src + O46_TYP, dec_sel) : 8'h0,
                                    8'h0};
                        rrec[8] <= mru32(eb + O46_OID, dec_sel);
                        rrec[9] <= mru32(eb + O46_OID + 4, dec_sel);
                        rrec[10] <= mru32(eb + O46_PRI, dec_sel);
                        rrec[11] <= mru32(eb + O46_PRI + 4, dec_sel);
                        rrec[12] <= {rref, 24'h0};
                        rrec[13] <= (rref < g1_n) ? mru32(src + O46_PX, dec_sel) : 32'd0;
                        rrec[14] <= (rref < g1_n) ? mru32(src + O46_PX + 4, dec_sel) : 32'd0;
                        rrec[15] <= (rref < g1_n) ? {EXP_BYTE, 24'h0} : 32'd0;
                        rrec[16] <= mru32(eb + O46_DQ, dec_sel);
                        rrec[17] <= 0;
                        if (rref >= g1_n) error <= 1;   // contrato #5
                    end
                end
                default: ;   // solo G1_ENT/G2_ENT se preparan aquí
            endcase

            // FIFO: balance neto de esta ciclo (push del decodificador menos
            // pop del emisor). push_commit/pop son combinacionales sobre el
            // estado previo al flanco, igual que las ramas que escriben f_mem.
f_cnt <= f_cnt + (push_commit ? 9'd1 : 9'd0) -
                        (pop ? 9'd1 : 9'd0);
        end
    end

endmodule
