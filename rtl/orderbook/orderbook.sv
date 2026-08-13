// orderbook.sv — order book engine (fase 2, Anexo A -> BBO).
//
// Consume el registro del Anexo A que emite el parser de fase 1:
//   word0 = {msg_type[7:0], locate[15:0], length[7:0], msg_idx[31:0]}
//   word1 = ts_ns (no usado por el book en esta fase)
//   words 2..N = cuerpo del mensaje (campos del wire, big-endian)
//
// Replica la semántica EXACTA de golden_model/src/book.py (fase 0).
//
// ESTRUCTURAS (iteración 2, fase 3: tabla de órdenes con hash + linear probing):
//   - orders en tabla hashada de NSLOT = 2^SLOT slots: {valid, tomb, ref, side
//     (0=bid,1=ask), price, qty}. hash(ref) = ref[SLOT-1:0]; la inserción
//     proba linealmente hasta PROBE slots (reutiliza slots con valid=0, p. ej.
//     tombstones); el lookup continúa a través de slots ocupados por otras refs
//     y tombstones, comparando el ref: encontrada -> hit; slot libre sin tomb
//     -> no existe; PROBE pasos sin hueco -> no existe (anomalía, igual que la
//     indexación directa de fase 2). Insert sin hueco en PROBE pasos -> tabla
//     llena -> error (SEC-HASH-02), nunca wrap ni overwrite silencioso.
//     La tabla se mapea a URAM en la iteración 5 (criterio 9).
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
    parameter K   = 19,          // ancho de order_ref (bits). 2^19 >= max ref
                                 // del subset real (372.297); el mapeo a URAM
                                 // se dimensiona en fase 3.
    parameter SLOT = 16,         // 2^SLOT slots de la tabla hashada (criterio 5).
                                 // hash(ref) = ref[SLOT-1:0]
    parameter PROBE = 8,         // pasos máx de linear probing por op
    parameter ND   = 5,          // niveles del top-N público (criterio 6)
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
    output reg  [2*ND*64-1:0] depth_tdata,
    output reg               depth_tvalid,
    input  wire              depth_tready,
    output reg  [31:0]       cross_events,
    output reg  [31:0]       anomaly_count,
    output reg               error
);

    localparam NSLOT = 2**SLOT;

    // bytes por palabra y su log2: 64 bits -> 8 B (b>>3), 32 bits -> 4 B (b>>2)
    localparam BYTES = DW / 8;
    localparam L2B   = $clog2(DW / 8);

    // ---------------------------------------------------------------
    // FSM de recepción
    // ---------------------------------------------------------------
    localparam ST_W0    = 3'd0;
    localparam ST_TS    = 3'd1;
    localparam ST_BODY  = 3'd2;
    localparam ST_APPLY = 3'd3;
    localparam ST_EMIT  = 3'd4;
    localparam ST_UADD  = 3'd5;
    reg [2:0]  st;
    reg [6:0] nbody_w;      // words de cuerpo restantes por consumir
    reg [1:0]  hrem;        // words de cabecera restantes tras w0 (DW=32: 3)
    reg emit_ok;            // la operación aplicada se emite (no fue anomalía/error)
    reg do_uadd;            // el replace U de este ciclo necesita ST_UADD
    // handshake combinacional: acepta entrada en W0/TS/BODY
    assign s_axis_tready = (st == ST_W0) || (st == ST_TS) || (st == ST_BODY);

    reg [7:0]  m_type;
    reg [15:0] m_locate;
    reg [7:0]  m_len;
    reg [31:0] m_idx;
    // (body_rem eliminado; se usa nbody_w)
    reg [3:0]  bi;
    reg [DW-1:0] body_acc[0:15];   // 16 words cubren el cuerpo máximo a DW=32

    // ---------------------------------------------------------------
    // estado del libro: tabla de órdenes hashada (criterio 5, iter 2).
    // NSLOT slots: valid=1 ocupado, valid=0 libre o borrado; ref guardado
    // para distinguir colisiones del hash. Los borrados dejan valid=0 y el
    // lookup continúa a través de esos slots (semántica de tombstones sin
    // bit muerto); el insert reutiliza el primer slot valid=0 del camino.
    // La entrada es exactamente {valid, ref, side, price, qty} (spec).
    // ---------------------------------------------------------------
    reg           o_valid [NSLOT-1:0];
    reg [K-1:0]   o_ref   [NSLOT-1:0];
    reg           o_side  [NSLOT-1:0];
    reg [PXW-1:0] o_price [NSLOT-1:0];
    reg [QW-1:0]  o_qty   [NSLOT-1:0];

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
    reg bad_sym;                // locate fuera del subset (SEC-NSYM-01)

    // ---------------------------------------------------------------
    // helpers de extracción de bytes (big-endian)
    // ---------------------------------------------------------------
    function automatic logic [7:0] pbody(input [6:0] b);
        pbody = body_acc[4'(b >> L2B)][(8'(DW-1) - 8'(b & 7'(BYTES-1))*8) -: 8];
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
    // tabla hashada: hash(ref) = ref[SLOT-1:0], linear probing <= PROBE.
    // lookup_ref: devuelve el slot si la ref está (found=1); si no, recorre
    // hasta PROBE slots de refs ajenas/borradas y acaba con found=0 (slot
    // con valid=0 -> no existe; camino lleno -> probe agotado -> no existe,
    // anomalía igual que la fase 2).
    // first_empty: primer slot con valid=0 del camino (reutiliza borrados);
    // full=1 si los PROBE slots están ocupados -> tabla llena (SEC-HASH-02).
    // Entrada: el hash ya truncado (los bits altos del ref no participan).
    // ---------------------------------------------------------------
    function automatic logic [SLOT-1:0] lookup_ref(input [K-1:0] r,
                                                   output logic found);
        integer ii;
        logic [SLOT-1:0] h;
        h = r[SLOT-1:0];
        found = 1'b0;
        lookup_ref = h;
        for (ii = 0; ii < PROBE; ii = ii + 1) begin
            if (o_valid[h + SLOT'(ii)] && o_ref[h + SLOT'(ii)] == r) begin
                found = 1'b1;
                lookup_ref = h + SLOT'(ii);
                ii = PROBE;
            end
        end
    endfunction

    function automatic logic [SLOT-1:0] first_empty(input [SLOT-1:0] h,
                                                    output logic full);
        integer ii;
        full = 1'b1;
        first_empty = h;
        for (ii = 0; ii < PROBE; ii = ii + 1) begin
            if (!o_valid[h + SLOT'(ii)]) begin
                full = 1'b0;
                first_empty = h + SLOT'(ii);
                ii = PROBE;
            end
        end
    endfunction

    // ---------------------------------------------------------------
    // FSM principal
    // ---------------------------------------------------------------
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            st <= ST_W0;
            for (int i = 0; i < NSLOT; i++) begin
                o_valid[i] <= 1'b0; o_ref[i] <= 0; o_side[i] <= 1'b0;
                o_price[i] <= 0; o_qty[i] <= 0;
            end
            for (int i = 0; i < NSYM*2*P; i++) begin
                lv_price[i] <= 0; lv_qty[i] <= 0;
            end
            for (int i = 0; i < NSYM; i++) begin
                prev_bp[i] <= 0; prev_bq[i] <= 0; prev_ap[i] <= 0; prev_aq[i] <= 0;
            end
            bbo_tvalid <= 1'b0; bbo_locate <= 0; bbo_tdata <= 0; bbo_changed <= 1'b0;
            depth_tvalid <= 1'b0; depth_tdata <= 0;
            cross_events <= 0; anomaly_count <= 0; error <= 1'b0;
            market_open <= 1'b0; u_newref <= 0; u_side <= 0;
            u_price <= 0; u_shares <= 0;
            for (int i = 0; i < NSYM; i++) tstate[i] <= 8'h00;
            bi <= 0; nbody_w <= 0; hrem <= 2'd1; emit_ok <= 1'b0;
            for (int i = 0; i < NSYM; i++) loc_map[i] <= 16'hffff;
            loc_cnt <= 0; m_loc_idx <= 0; bad_sym <= 1'b0;
        end else begin
            // retención AXI (SEC-BP-01): el par BBO/depth se mantiene válido
            // hasta que su tready lo acepta; el guard de ST_APPLY frena el
            // pipeline mientras penda (sin pérdida ni duplicado)
            bbo_tvalid <= bbo_tvalid && !bbo_tready;
            depth_tvalid <= depth_tvalid && !depth_tready;
            error <= 1'b0;

            case (st)
                ST_W0: begin
                    if (s_axis_tvalid) begin
                        // campos del w0: {type, locate, len, idx} a 64 bits;
                        // a 32 bits el idx viaja en su propia word (w1)
                        m_type   <= s_axis_tdata[DW-1 -: 8];
                        m_locate <= s_axis_tdata[DW-9 -: 16];
                        m_len    <= s_axis_tdata[DW-25 -: 8];
                        // mapeo de símbolo: índice conocido o registro por orden
                        // (register-on-first-seen). loc_lookup lee loc_map/loc_cnt
                        // del estado previo; el registro se hace con <= en el flanco.
                        bad_sym <= 1'b0;
                        if (loc_lookup(s_axis_tdata[DW-9 -: 16]) == 5'd31 &&
                            loc_cnt < NSYM) begin
                            loc_map[loc_cnt] <= s_axis_tdata[DW-9 -: 16];
                            loc_cnt <= loc_cnt + 1;
                            m_loc_idx <= loc_cnt;
                        end else if (loc_lookup(s_axis_tdata[DW-9 -: 16]) == 5'd31) begin
                            // símbolo fuera del subset (NSYM registrados): pulso
                            // de error y mensaje descartado sin tocar el libro
                            // (nunca un índice OOB; hallazgo F1 del grade)
                            bad_sym <= 1'b1;
                            error <= 1'b1;
                            m_loc_idx <= 0;
                        end else begin
                            m_loc_idx <= loc_lookup(s_axis_tdata[DW-9 -: 16]);
                        end
                        // words de cuerpo = ceil((len-11)/BYTES)
                        nbody_w <= 7'(((8'(s_axis_tdata[DW-25 -: 8]) - 8'd11) +
                                       8'(BYTES-1)) >> L2B);
                        hrem <= (DW == 32) ? 2'd3 : 2'd1;
                        bi <= 0;
                        st <= ST_TS;
                    end
                end
                ST_TS: begin
                    // consume y descarta las words restantes de la cabecera
                    // (32 bits: w1=idx [se captura], w2=ts[31:0], w3=ts_hi)
                    if (s_axis_tvalid) begin
                        if (DW == 32 && hrem == 2'd3) m_idx <= s_axis_tdata[31:0];
                        if (hrem == 2'd1) st <= ST_BODY;
                        else hrem <= hrem - 1;
                    end
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
                    // el par BBO/depth se acepta solo con ambos tready; mientras
                    // el par pendiente no se acepte, el pipeline se frena aquí
                    // (SEC-BP-01: retención sin pérdida ni duplicado)
                    if ((!bbo_tvalid || bbo_tready) &&
                        (!depth_tvalid || depth_tready)) begin
                        if (m_len < 8'd11) error <= 1'b1;   // cuerpo inválido
                        if (m_idx == 32'hffffffff) error <= 1'b1;  // idx sane
                        if (bad_sym) begin
                            // mensaje de un símbolo fuera del subset: descartado
                            do_uadd <= 1'b0;
                            st <= ST_W0;
                        end else begin
                            apply_one(do_uadd);
                            if (do_uadd) st <= ST_UADD;   // replace: mitad add
                            else if (m_type == 8'h41 || m_type == 8'h46 || m_type == 8'h45 ||
                                     m_type == 8'h43 || m_type == 8'h58 || m_type == 8'h44 ||
                                     m_type == 8'h55) st <= ST_EMIT;
                            else st <= ST_W0;
                        end
                    end
                end
                ST_UADD: begin
                    // mitad add del replace: la segunda level_add ve el estado
                    // del ciclo anterior (la eliminación ya aplicada)
                    apply_uadd_half();
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
                else if (newq == 0) begin
                    // nivel vacío no existe (invariante golden): se limpia
                    // precio Y cantidad, o el top-N filtraría precios stale
                    lqt[found] = 0;
                    lpr[found] = 0;
                end
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
        input [SLOT-1:0] sidx;      // slot ya validado por el lookup del caller
        input [31:0] qty;
        output reg did;
        reg [33:0] rest;
        begin
            did = 1'b0;
            rest = 34'({2'b0, o_qty[sidx]}) - 34'({2'b0, qty});
            if (rest[33]) error <= 1'b1;
            else if (rest == 0) begin
                reduce_level(o_side[sidx], o_price[sidx], -$signed(o_qty[sidx]));
                o_valid[sidx] <= 1'b0;
                did = 1'b1;
            end else begin
                o_qty[sidx] <= QW'(rest);
                reduce_level(o_side[sidx], o_price[sidx], -32'(qty));
                did = 1'b1;
            end
        end
    endtask

    task automatic apply_uadd_half;
        // mitad add del replace (ST_UADD): inserta u_newref en la tabla.
        // Si los PROBE slots están ocupados -> tabla llena: no se aplica, se
        // señaliza error y se cancela el BBO del replace (SEC-HASH-02).
        logic full;
        logic [SLOT-1:0] nidx;
        begin
            nidx = first_empty(u_newref[SLOT-1:0], full);
            if (full) begin
                error <= 1'b1;
                emit_ok <= 1'b0;
            end else begin
                level_add(u_side, u_price, u_shares);
                o_valid[nidx] <= 1'b1;
                o_ref[nidx]   <= u_newref;
                o_side[nidx]  <= u_side;
                o_price[nidx] <= u_price;
                o_qty[nidx]   <= u_shares;
            end
        end
    endtask

    task automatic emit_bbo;
        reg [PXW-1:0] bp, ap;
        reg [QW-1:0] bq, aq;
        reg changed;
        reg [2*ND*64-1:0] dacc;
        integer i, di;
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
            // top-N público (criterio 6): ND niveles por lado del símbolo del
            // evento, mejor primero (slot 0 de la lista = mejor), vacíos a 0.
            // Bus: {bid[ND-1..0], ask[ND-1..0]} MSB->LSB, cada nivel
            // {px[31:0], qty[31:0]} -> depth[639:576] = mejor bid.
            dacc = 0;
            for (di = 0; di < ND; di = di + 1)
                dacc = {dacc[2*ND*64-65:0],
                        lv_price[m_loc_idx*2*P + di][31:0],
                        lv_qty[m_loc_idx*2*P + di][31:0]};
            for (di = 0; di < ND; di = di + 1)
                dacc = {dacc[2*ND*64-65:0],
                        lv_price[m_loc_idx*2*P + P + di][31:0],
                        lv_qty[m_loc_idx*2*P + P + di][31:0]};
            depth_tdata <= dacc;
            depth_tvalid <= 1'b1;
        end
    endtask

    task automatic apply_one(output logic out_uadd);
        reg [K-1:0] oref, newref;
        reg [31:0] shares, price;
        reg ask;
        reg [7:0] ev;
        reg do_emit;
        logic found, found2, full;
        logic [SLOT-1:0] sidx, nidx;
        begin
            do_emit = 1'b0;
            out_uadd = 1'b0;
            case (m_type)
                8'h41, 8'h46: begin
                    oref = K'(b64(0)); ask = (pbody(8) == 8'h53);
                    shares = b32(9); price = b32(21);
                    sidx = lookup_ref(oref, found);
                    if (found || shares == 0) begin
                        error <= 1'b1;      // ref duplicada o cantidad inválida
                    end else begin
                        nidx = first_empty(oref[SLOT-1:0], full);
                        if (full) begin
                            error <= 1'b1;  // tabla llena (SEC-HASH-02)
                        end else begin
                            o_valid[nidx] <= 1'b1;
                            o_ref[nidx]   <= oref;
                            o_side[nidx]  <= ask;
                            o_price[nidx] <= price;
                            o_qty[nidx]   <= shares;
                            level_add(ask, price, shares);
                            do_emit = 1'b1;
                        end
                    end
                end
                8'h45, 8'h43, 8'h58: begin
                    oref = K'(b64(0));
                    sidx = lookup_ref(oref, found);
                    if (!found) anomaly_count <= anomaly_count + 1;
                    else reduce_order(sidx, b32(8), do_emit);
                end
                8'h44: begin
                    oref = K'(b64(0));
                    sidx = lookup_ref(oref, found);
                    if (!found) anomaly_count <= anomaly_count + 1;
                    else begin
                        level_add(o_side[sidx], o_price[sidx], -$signed(o_qty[sidx]));
                        o_valid[sidx] <= 1'b0;
                        do_emit = 1'b1;
                    end
                end
                8'h55: begin
                    oref = K'(b64(0)); newref = K'(b64(8));
                    shares = b32(16); price = b32(20);
                    sidx = lookup_ref(oref, found);
                    if (!found) anomaly_count <= anomaly_count + 1;
                    else if (shares == 0) error <= 1'b1;
                    else begin
                        nidx = lookup_ref(newref, found2);
                        if (found2) error <= 1'b1;   // newref duplicada
                        else begin
                            // mitad delete (atómico): la add se aplica en ST_UADD,
                            // un ciclo después, para que vea la eliminación
                            level_add(o_side[sidx], o_price[sidx], -$signed(o_qty[sidx]));
                            o_valid[sidx] <= 1'b0;
                            u_newref <= newref;
                            u_side <= o_side[sidx];
                            u_price <= price;
                            u_shares <= shares;
                            do_emit = 1'b1;
                            out_uadd = 1'b1;
                        end
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
