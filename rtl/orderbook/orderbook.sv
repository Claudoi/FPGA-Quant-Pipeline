// orderbook.sv — order book engine (fase 2, Anexo A -> BBO).
//
// Consume el registro del Anexo A que emite el parser de fase 1:
//   word0 = {msg_type[7:0], locate[15:0], length[7:0], msg_idx[31:0]}
//   word1 = ts_ns (no usado por el book en esta fase)
//   words 2..N = cuerpo del mensaje (campos del wire, big-endian)
//
// Replica la semántica EXACTA de golden_model/src/book.py (fase 0).
//
// ESTRUCTURAS (iteración 1: un símbolo, niveles con lista ordenada):
//   - orders[ORD] indexado por order_ref: {valid, side(0=bid,1=ask),
//     price, qty}
//   - levels por (lado): lista ordenada de P niveles {price, qty}, mejor
//     primero (bid = mayor, ask = menor).
//   La aplicación se hace en el ciclo ST_APPLY: se leen orders (de la misma
//   cola del ciclo pasado, ya capturadas en flanco), se modifican levels y
//   orders, y se emite el BBO. `changed` compara contra el BBO previo.
//
// CORRECCIÓN > velocidad: 1 mensaje/ciclo de reloj, lógica O(P). El pipeline
// URAM y la latencia registrada se optimizan en la iteración de profundidad.
module orderbook #(
    parameter DW  = 64,
    parameter K   = 19,          // 2^K entradas de orden (refs). Indexación
                                 // directa por order_ref: 2^K >= max ref del
                                 // subset real (372.297 -> K=19); el mapeo a
                                 // URAM se dimensiona en fase 3.
    parameter P   = 32,          // niveles de precio por lado. Máx medido del
                                 // subset real: 17 (locate 6960 ask, día local);
                                 // el overflow >P sigue señalizándose (SEC-OV)
    parameter NSYM = 20,         // símbolos del subset
    parameter PXW = 32,          // ancho de precio (sub-céntimos ITCH)
    parameter QW  = 32           // ancho de cantidad
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
    output reg               error
);

    localparam ORD = 2**K;

    // ---------------------------------------------------------------
    // FSM de recepción
    // ---------------------------------------------------------------
    localparam ST_W0    = 3'd0;
    localparam ST_TS    = 3'd1;
    localparam ST_BODY  = 3'd2;
    localparam ST_APPLY = 3'd3;
    localparam ST_EMIT  = 3'd4;
    localparam ST_UADD  = 3'd5;
    reg [2:0] st;
    reg [6:0] nbody_w;      // words de cuerpo restantes por consumir
    reg emit_ok;            // la operación aplicada se emite (no fue anomalía/error)
    reg do_uadd;            // el replace U de este ciclo necesita ST_UADD
    // handshake combinacional: acepta entrada en W0/TS/BODY
    assign s_axis_tready = (st == ST_W0) || (st == ST_TS) || (st == ST_BODY);

    reg [7:0]  m_type;
    reg [15:0] m_locate;
    reg [7:0]  m_len;
    reg [31:0] m_idx;
    // (body_rem eliminado; se usa nbody_w)
    reg [2:0]  bi;
    reg [DW-1:0] body_acc[0:7];

    // ---------------------------------------------------------------
    // estado del libro
    // ---------------------------------------------------------------
    reg           o_valid [ORD-1:0];
    reg           o_side  [ORD-1:0];
    reg [PXW-1:0] o_price [ORD-1:0];
    reg [QW-1:0]  o_qty   [ORD-1:0];

    // niveles: [side*P + slot] = precio, qty (mejor primero)
    reg [PXW-1:0] lv_price [NSYM*2*P-1:0];
    reg [QW-1:0]  lv_qty   [NSYM*2*P-1:0];

    reg [PXW-1:0] prev_bp [NSYM-1:0], prev_ap [NSYM-1:0];
    reg [QW-1:0]  prev_bq [NSYM-1:0], prev_aq [NSYM-1:0];

    reg market_open;
    reg [7:0] tstate [NSYM-1:0];   // trading state por símbolo (golden: por locate)

    // reemplazo U: la mitad "add" se aplica en el ciclo siguiente (ST_UADD),
    // porque dos level_add en el mismo ciclo no ven la primera (no-bloqueante)
    reg [K-1:0] u_newref;
    reg        u_side;
    reg [PXW-1:0] u_price;
    reg [QW-1:0]  u_shares;

    // mapeo locate -> índice de símbolo (register-on-first-seen)
    reg [15:0] loc_map[NSYM-1:0];
    reg [4:0]  loc_cnt;         // número de símbolos registrados
    reg [4:0]  m_loc_idx;       // índice del símbolo del mensaje en curso

    // ---------------------------------------------------------------
    // helpers de extracción de bytes (big-endian)
    // ---------------------------------------------------------------
    function automatic logic [7:0] pbody(input [6:0] b);
        pbody = body_acc[3'(b >> 3)][63 - 8*3'(b & 3'd7) -: 8];
    endfunction
    function automatic logic [31:0] b32(input [6:0] b);
        b32 = {pbody(b), pbody(b+1), pbody(b+2), pbody(b+3)};
    endfunction
    function automatic logic [63:0] b64(input [6:0] b);
        b64 = {pbody(b), pbody(b+1), pbody(b+2), pbody(b+3),
               pbody(b+4), pbody(b+5), pbody(b+6), pbody(b+7)};
    endfunction

    // devuelve el índice del locate o 31 si no está registrado
    function automatic logic [4:0] loc_lookup(input [15:0] l);
        integer ii;
        loc_lookup = 5'd31;
        for (ii = 0; ii < NSYM; ii = ii + 1) begin
            if (loc_map[ii] == l) begin
                loc_lookup = 5'(ii);
                ii = NSYM;
            end
        end
    endfunction

    // ---------------------------------------------------------------
    // FSM principal
    // ---------------------------------------------------------------
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            st <= ST_W0;
            for (int i = 0; i < ORD; i++) o_valid[i] <= 1'b0;
            for (int i = 0; i < NSYM*2*P; i++) begin
                lv_price[i] <= 0; lv_qty[i] <= 0;
            end
            for (int i = 0; i < NSYM; i++) begin
                prev_bp[i] <= 0; prev_bq[i] <= 0; prev_ap[i] <= 0; prev_aq[i] <= 0;
            end
            bbo_tvalid <= 1'b0; bbo_locate <= 0; bbo_tdata <= 0; bbo_changed <= 1'b0;
            cross_events <= 0; anomaly_count <= 0; error <= 1'b0;
            market_open <= 1'b0; u_newref <= 0; u_side <= 0;
            u_price <= 0; u_shares <= 0;
            for (int i = 0; i < NSYM; i++) tstate[i] <= 8'h00;
            bi <= 0; nbody_w <= 0; emit_ok <= 1'b0;
            for (int i = 0; i < NSYM; i++) loc_map[i] <= 16'hffff;
            loc_cnt <= 0; m_loc_idx <= 0;
        end else begin
            bbo_tvalid <= 1'b0;
            error <= 1'b0;

            case (st)
                ST_W0: begin
                    if (s_axis_tvalid) begin
                        m_type   <= s_axis_tdata[63:56];
                        m_locate <= s_axis_tdata[55:40];
                        m_len    <= s_axis_tdata[39:32];
                        m_idx    <= s_axis_tdata[31:0];
                        // mapeo de símbolo: índice conocido o registro por orden
                        // (register-on-first-seen). loc_lookup lee loc_map/loc_cnt
                        // del estado previo; el registro se hace con <= en el flanco.
                        if (loc_lookup(s_axis_tdata[55:40]) == 5'd31 &&
                            loc_cnt < NSYM) begin
                            loc_map[loc_cnt] <= s_axis_tdata[55:40];
                            loc_cnt <= loc_cnt + 1;
                            m_loc_idx <= loc_cnt;
                        end else begin
                            m_loc_idx <= loc_lookup(s_axis_tdata[55:40]);
                        end
                        // words de cuerpo = ceil((len-11)/8)
                        nbody_w <= 7'(((8'(s_axis_tdata[39:32]) - 8'd11) + 8'd7) >> 3);
                        bi <= 0;
                        st <= ST_TS;
                    end
                end
                ST_TS: begin
                    // consume y descarta la word del timestamp
                    if (s_axis_tvalid) st <= ST_BODY;
                end
                ST_BODY: begin
                    if (s_axis_tvalid) begin
                        body_acc[bi] <= s_axis_tdata;
                        if (s_axis_tlast) begin
                            st <= ST_APPLY;   // tlast: fin del burst (cuerpo)
                        end else if (nbody_w <= 1) begin
                            st <= ST_APPLY;
                        end else begin
                            bi <= bi + 1;
                            nbody_w <= nbody_w - 1;
                        end
                    end
                end
                ST_APPLY: begin
                    if (!bbo_tvalid || bbo_tready) begin
                        if (m_len < 8'd11) error <= 1'b1;   // cuerpo inválido
                        if (m_idx == 32'hffffffff) error <= 1'b1;  // idx sane
                        apply_one(do_uadd);
                        if (do_uadd) st <= ST_UADD;   // replace: mitad add
                        else if (m_type == 8'h41 || m_type == 8'h46 || m_type == 8'h45 ||
                                 m_type == 8'h43 || m_type == 8'h58 || m_type == 8'h44 ||
                                 m_type == 8'h55) st <= ST_EMIT;
                        else st <= ST_W0;
                    end
                end
                ST_UADD: begin
                    // mitad add del replace: la segunda level_add ve el estado
                    // del ciclo anterior (la eliminación ya aplicada)
                    level_add(u_side, u_price, u_shares);
                    o_valid[u_newref] <= 1'b1;
                    o_side[u_newref] <= u_side;
                    o_price[u_newref] <= u_price;
                    o_qty[u_newref] <= u_shares;
                    st <= ST_EMIT;
                end
                ST_EMIT: begin
                    if (emit_ok) emit_bbo();
                    st <= ST_W0;
                end
                default: st <= ST_W0;
            endcase
        end
    end

    // ---------------------------------------------------------------
    // actualización de niveles: función pura que recibe el estado de un lado
    // (precios, cantidades, precio objetivo, delta) y devuelve por ref el
    // nuevo array. Para Verilator/SystemVerilog lo hacemos con una tarea que
    // escribe en los arrays lv_price/lv_qty SÓLO en el flanco (nunca leídos
    // tras escribir en el mismo ciclo). Como ST_APPLY es un flanco, las
    // lecturas de lv_* dentro ven el valor ANTERIOR (correcto: las
    // operaciones ahí leen el estado actual y generan el siguiente).
    // ---------------------------------------------------------------
    task automatic level_add;
        input        ask;
        input [PXW-1:0] price;
        input signed [31:0] delta;
        integer base, slot, found, empty, i, j;
        reg [PXW-1:0] tp;
        reg [QW-1:0] tq;
        reg [32:0] newq;
        reg [PXW-1:0] lpr[0:P-1];   // copias locales (bloqueantes) del lado
        reg [QW-1:0]  lqt[0:P-1];
        begin
            base = m_loc_idx*2*P + (ask ? P : 0);
            // copiar el estado actual del lado a variables locales
            for (slot = 0; slot < P; slot = slot + 1) begin
                lpr[slot] = lv_price[base+slot];
                lqt[slot] = lv_qty[base+slot];
            end
            // aplicar la operación sobre la copia local (bloqueante, visible ya)
            found = -1; empty = -1;
            for (slot = 0; slot < P; slot = slot + 1) begin
                if (lqt[slot] == 0 && empty == -1) empty = slot;
                else if (lqt[slot] != 0 && lpr[slot] == price) found = slot;
            end
            if (found == -1 && empty == -1) begin
                error <= 1'b1;
            end else if (found == -1) begin
                lpr[empty] = price;
                lqt[empty] = QW'(delta);
            end else begin
                newq = $signed(33'(lqt[found])) + $signed(33'(delta));
                if (newq[32]) error <= 1'b1;
                else if (newq == 0) lqt[found] = 0;
                else lqt[found] = QW'(newq);
            end
            // burbuja sobre las copias locales (mejor primero)
            for (i = 0; i < P; i = i + 1)
                for (j = i+1; j < P; j = j + 1) begin
                    if (lqt[j] != 0 &&
                        (lqt[i] == 0 ||
                         (ask ? (lpr[j] < lpr[i]) : (lpr[j] > lpr[i])))) begin
                        tp = lpr[i]; lpr[i] = lpr[j]; lpr[j] = tp;
                        tq = lqt[i]; lqt[i] = lqt[j]; lqt[j] = tq;
                    end
                end
            // escribir el resultado de una sola vez (non-blocking)
            for (slot = 0; slot < P; slot = slot + 1) begin
                lv_price[base+slot] <= lpr[slot];
                lv_qty[base+slot]   <= lqt[slot];
            end
        end
    endtask

    task automatic reduce_level;
        input        ask;
        input [PXW-1:0] price;
        input signed [31:0] delta;
        begin
            level_add(ask, price, delta);
        end
    endtask

    task automatic reduce_order;
        input [K-1:0] oref;
        input [31:0] qty;
        output reg did;
        reg [33:0] rest;
        begin
            did = 1'b0;
            if (!o_valid[oref]) anomaly_count <= anomaly_count + 1;
            else begin
                rest = 34'({2'b0, o_qty[oref]}) - 34'({2'b0, qty});
                if (rest[33]) error <= 1'b1;
                else if (rest == 0) begin
                    reduce_level(o_side[oref], o_price[oref], -$signed(o_qty[oref]));
                    o_valid[oref] <= 1'b0;
                    did = 1'b1;
                end else begin
                    o_qty[oref] <= QW'(rest);
                    reduce_level(o_side[oref], o_price[oref], -32'(qty));
                    did = 1'b1;
                end
            end
        end
    endtask

    task automatic emit_bbo;
        reg [PXW-1:0] bp, ap;
        reg [QW-1:0] bq, aq;
        reg changed;
        integer i;
        begin
            // mejor nivel por lado = primer slot con qty>0 (lista ordenada)
            bp = 0; bq = 0;
            for (i = 0; i < P; i = i + 1) begin
                if (lv_qty[m_loc_idx*2*P + i] != 0) begin
                    bp = lv_price[m_loc_idx*2*P + i]; bq = lv_qty[m_loc_idx*2*P + i];
                    i = P;
                end
            end
            ap = 0; aq = 0;
            for (i = 0; i < P; i = i + 1) begin
                if (lv_qty[m_loc_idx*2*P + P + i] != 0) begin
                    ap = lv_price[m_loc_idx*2*P + P + i]; aq = lv_qty[m_loc_idx*2*P + P + i];
                    i = P;
                end
            end
            if (market_open && tstate[m_loc_idx] == 8'h54 && bp != 0 && ap != 0 && bp >= ap)
                cross_events <= cross_events + 1;
            bbo_locate <= m_locate;
            bbo_tdata  <= {bp[31:0], bq[31:0], ap[31:0], aq[31:0]};
            changed = (bp != prev_bp[m_loc_idx]) || (bq != prev_bq[m_loc_idx]) ||
                      (ap != prev_ap[m_loc_idx]) || (aq != prev_aq[m_loc_idx]);
            bbo_changed <= changed;
            prev_bp[m_loc_idx] <= bp; prev_bq[m_loc_idx] <= bq;
            prev_ap[m_loc_idx] <= ap; prev_aq[m_loc_idx] <= aq;
            bbo_tvalid <= 1'b1;
        end
    endtask

    task automatic apply_one(output logic out_uadd);
        reg [K-1:0] oref, newref;
        reg [31:0] shares, price;
        reg ask;
        reg [7:0] ev;
        reg do_emit;
        begin
            do_emit = 1'b0;
            out_uadd = 1'b0;
            case (m_type)
                8'h41, 8'h46: begin
                    oref = K'(b64(0)); ask = (pbody(8) == 8'h53);
                    shares = b32(9); price = b32(21);
                    if (o_valid[oref] || shares == 0) begin
                        error <= 1'b1;
                    end else begin
                        o_valid[oref] <= 1'b1; o_side[oref] <= ask;
                        o_price[oref] <= price; o_qty[oref] <= shares;
                        level_add(ask, price, shares);
                        do_emit = 1'b1;
                    end
                end
                8'h45, 8'h43, 8'h58: begin
                    reduce_order(K'(b64(0)), b32(8), do_emit);
                end
                8'h44: begin
                    oref = K'(b64(0));
                    if (!o_valid[oref]) anomaly_count <= anomaly_count + 1;
                    else begin
                        level_add(o_side[oref], o_price[oref], -$signed(o_qty[oref]));
                        o_valid[oref] <= 1'b0;
                        do_emit = 1'b1;
                    end
                end
                8'h55: begin
                    oref = K'(b64(0)); newref = K'(b64(8));
                    shares = b32(16); price = b32(20);
                    if (!o_valid[oref]) anomaly_count <= anomaly_count + 1;
                    else if (shares == 0 || o_valid[newref]) error <= 1'b1;
                    else begin
                        // mitad delete (atómico): la add se aplica en ST_UADD,
                        // un ciclo después, para que vea la eliminación
                        level_add(o_side[oref], o_price[oref], -$signed(o_qty[oref]));
                        o_valid[oref] <= 1'b0;
                        u_newref <= newref;
                        u_side <= o_side[oref];
                        u_price <= price;
                        u_shares <= shares;
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