// orderbook.sv — order book engine (fase 2, Anexo A -> BBO).
//
// Consume el registro del Anexo A que emite el parser de fase 1:
//   word0 = {msg_type[7:0], locate[15:0], length[7:0], msg_idx[31:0]}
//   word1 = ts_ns (no usado por el book en esta fase)
//   words 2..N = cuerpo del mensaje (campos del wire, big-endian)
// A DW=32 (fase3-uram, recorte del Anexo A): w0={type,locate,len},
// w1=msg_idx, w2..=cuerpo — SIN words de timestamp (contrato enmendado).
//
// Replica la semántica EXACTA de golden_model/src/book.py (fase 0).
//
//   ESTRUCTURAS (fase3-uram, iteración 2: tabla en URAM + sonda serializada):
//   - orders en URAM de NSLOT = 2^SLOT entradas de OW=86 bits:
//     {qty[31:0], price[31:0], side, ref[19:0], valid}. hash(ref) =
//     ref[SLOT-1:0]; linear probing acotado a PROBE pasos. La lectura es
//     SÍNCRONA REGISTRADA (patrón de inferencia URAM): un puerto de lectura
//     (rd_addr -> rd_data 1 ciclo después) y un puerto de escritura
//     (escritura condicional vía la tarea mem_wr, 1 write máx por ciclo,
//     nunca en el mismo ciclo que una lectura de la sonda). NUNCA indexación
//     combinacional de la tabla (bloqueador B1 del criterio 10, documentado
//     en docs/writeup/revision-exhaustiva-2026-08-14.md).
//   - La sonda (probe engine) serializa el lookup a ≤1 slot/ciclo y arranca
//     DURANTE ST_BODY (prefetch del grupo de hash: la order_ref viaja en las
//     primeras words del cuerpo y el hash se conoce antes de ST_APPLY):
//     los resultados (found/slot/entry, primer empty, full) quedan en
//     registros y ST_APPLY los consume SIN volver a leer la tabla.
//   - El reset NO toca el contenido de la URAM (mataría la inferencia): un
//     estado ST_INVAL invalida los 65.536 slots a 1 slot/ciclo (la URAM
//     arranca a 0 en silicio; el patrón de invalidación por escritura es el
//     estándar y el único compatible con la síntesis).
//   - levels por (lado): lista ordenada de P niveles {price, qty}, mejor
//     primero (bid = mayor, ask = menor) — sin cambios en esta iteración
//     (el pipeline de niveles es la iteración 3).
//
// CORRECCIÓN > velocidad: 1 mensaje/ciclo de reloj, lógica O(P).
module orderbook #(
    parameter DW  = 64,
    parameter K   = 19,          // ancho de order_ref (bits). 2^19 >= max ref
                                 // del subset real (372.297); el campo en
                                 // memoria es REFW=20 bits (uram.md)
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
    localparam REFW  = 20;      // campo ref en memoria (K <= REFW; uram.md)
    localparam OW    = 1 + REFW + 1 + PXW + QW;   // 86 bits {qty,px,side,ref,valid}

    // bytes por palabra y su log2: 64 bits -> 8 B (b>>3), 32 bits -> 4 B (b>>2)
    localparam BYTES = DW / 8;
    localparam L2B   = $clog2(DW / 8);

    // ---------------------------------------------------------------
    // FSM de recepción
    // ---------------------------------------------------------------
    localparam ST_W0         = 4'd0;
    localparam ST_TS         = 4'd1;
    localparam ST_BODY       = 4'd2;
    localparam ST_APPLY      = 4'd3;
    localparam ST_EMIT       = 4'd4;
    localparam ST_UADD       = 4'd5;
    localparam ST_WAIT_PROBE = 4'd6;   // el prefetch no acabó durante el cuerpo
    localparam ST_INVAL      = 4'd7;   // invalidación post-reset (1 slot/ciclo)
    // pipeline de niveles (fase3-uram iter 3): level_add partido en etapas
    // registradas — ST_LV2 decide (priority encoders), ST_LV3 materializa y
    // escribe. Cada operación consume 2 ciclos extra como máximo (SEC-URAM-03)
    localparam ST_LV2        = 4'd8;
    localparam ST_LV3        = 4'd9;
    reg [3:0]  st /* verilator public */;
    reg [SLOT-1:0] st_inval_cnt;   // contador de la invalidación post-reset (1/ciclo)
    reg [6:0] nbody_w;      // words de cuerpo restantes por consumir
    reg [1:0]  hrem;        // words de cabecera restantes tras w0 (DW=32: 1)
    reg emit_ok;            // la operación aplicada se emite (no fue anomalía/error)
    reg do_uadd;            // el replace U de este ciclo necesita ST_UADD
    // handshake combinacional: acepta entrada en W0/TS/BODY
    assign s_axis_tready = (st == ST_W0) || (st == ST_TS) || (st == ST_BODY);

    reg [7:0]  m_type;
    reg [15:0] m_locate;
    reg [7:0]  m_len;
    reg [31:0] m_idx;
    reg [3:0]  bi;
    reg [DW-1:0] body_acc[0:15];   // 16 words cubren el cuerpo máximo a DW=32

    // ---------------------------------------------------------------
    // tabla de órdenes en URAM (fase3-uram): array único de NSLOT x OW bits
    // (65.536 x 86 ≈ 20 URAM del VU9P). SIN reset de contenido (patrón de
    // inferencia); la invalidación post-reset corre en ST_INVAL.
    // Entrada: {valid[0], ref[REFW:1], side[21], price[PXW+22-1:22], qty[85:54]}
    // ---------------------------------------------------------------
    reg [OW-1:0] o_mem [NSLOT-1:0];
    // puerto de lectura de la sonda (registrado: rd_data <= o_mem[rd_addr])
    reg [SLOT-1:0] rd_addr /* verilator public */;
    reg [OW-1:0]  rd_data /* verilator public */;

    // acceso de la entrada (cada accesor recibe SOLO su campo: el bit valid
    // se lee directo con rd_data[0])
    function automatic logic [REFW-1:0] e_ref(input [REFW-1:0] e);
        e_ref = e;
    endfunction
    function automatic logic e_side(input e);
        e_side = e;
    endfunction
    function automatic logic [PXW-1:0] e_price(input [PXW-1:0] e);
        e_price = e;
    endfunction
    function automatic logic [QW-1:0] e_qty(input [QW-1:0] e);
        e_qty = e;
    endfunction
    function automatic logic [OW-1:0] entry_new(input [K-1:0] r,
                                                input        side,
                                                input [PXW-1:0] px,
                                                input [QW-1:0]  q);
        entry_new = {q, px, side, REFW'(r), 1'b1};
    endfunction

    // escritura de la tabla: la tarea escribe el ARRAY directamente (patrón de
    // la fase 3 con lv_price: un solo driver, la tarea — un puerto scalares
    // + tarea dispararía MULTIDRIVEN en Verilator). Cada camino de apply_one
    // emite a lo sumo UN write por ciclo; la sonda NUNCA lee durante
    // ST_APPLY/ST_UADD (URAM 1R+1W sin colisión)
    task automatic mem_wr(input [SLOT-1:0] a, input [OW-1:0] d);
        begin
            o_mem[a] <= d;
        end
    endtask

    // ---------------------------------------------------------------
    // probe engine (sonda serializada + prefetch, fase3-uram).
    // Runs: old (order_ref del mensaje) y new (newref del replace U). Un run
    // recorre h..h+PROBE-1 a 1 slot/ciclo con lecturas REGISTRADAS:
    //   T0   arranque (rd_addr = h, WARM)
    //   T1   rd_data = mem[h]; rd_addr = h+1 (WALK)
    //   T2.. evala rd_data (slot h+i-1); sigue o termina
    // El run termina al encontrar la ref (found) o al agotar los PROBE slots
    // (not found; full si el camino no tenía ningún slot libre). Los
    // tombstones (valid=0) NO cortan el recorrido (semántica de fase 3:
    // una ref puede vivir más allá de un borrado). Resultados en registros:
    // pr_found/pr_slot/pr_entry (la entrada completa leída), pr_empty_found/
    // pr_empty (primer hueco), pr_full.
    // ---------------------------------------------------------------
    localparam PR_IDLE = 2'd0, PR_WARM = 2'd1, PR_WALK = 2'd2;
    reg [1:0]  pr_phase /* verilator public */;
    reg        pr_pending_old /* verilator public */;
    reg        pr_pending_new /* verilator public */;
    reg [K-1:0] pr_oref;
    reg [K-1:0] pr_newref;
    reg        pr_need_empty;      // el run old busca también primer hueco (A/F)
    reg [SLOT-1:0] pr_base;
    reg [REFW-1:0] pr_target;
    reg [15:0] pr_i;               // paso 0..PROBE-1 del slot en evaluación
    reg        pr_rec_empty;
    reg        pr_is_old;          // identidad del run en curso (latch de salida)
    // registros de trabajo del run en curso (condiciones de la pasada)
    reg        w_empty_found;
    // resultados LATCHADOS del run OLD (order_ref del mensaje): consumidos por
    // apply_one para A/F/E/C/X/D y para la mitad delete del U
    reg        pr_found /* verilator public */;
    reg [SLOT-1:0] pr_slot /* verilator public */;
    reg [OW-1:0]  pr_entry;
    reg        pr_empty_found /* verilator public */;
    reg [SLOT-1:0] pr_empty /* verilator public */;
    reg        pr_full;
    // resultados LATCHADOS del run NEW (newref del replace): capacity check y
    // slot de insert del U. Los dos runs corren EN SERIE y terminan ANTES de
    // ST_APPLY: el U es atómico — la tabla se lee pre-apply y la original
    // sobrevive si el insert no cabe (hallazgo G5)
    reg        pr_new_found;
    reg [SLOT-1:0] pr_new_empty;
    reg        pr_new_full;

    wire pr_active = (pr_phase != PR_IDLE);
    wire pr_start_old = pr_pending_old && !pr_active;
    wire pr_start_new = pr_pending_new && !pr_active && !pr_pending_old;

    // tipos que leen la tabla (prefetch en ST_BODY)
    function automatic logic lt(input [7:0] t);
        lt = (t == 8'h41) || (t == 8'h46) || (t == 8'h45) || (t == 8'h43) ||
             (t == 8'h58) || (t == 8'h44) || (t == 8'h55);
    endfunction

    // el FSM decide la salida de ST_BODY con la COMBINACIÓN de armado del
    // ciclo: el armado es NB (invisible hasta el flanco) y ningún mensaje
    // puede escapar a ST_APPLY con un probe en vuelo o a punto de armarse
    wire arm_old_this = (DW == 32) ? (bi == 4'd1 && lt(m_type))
                                   : (bi == 4'd0 && lt(m_type));
    wire arm_new_this = (DW == 32) ? (bi == 4'd3 && m_type == 8'h55)
                                   : (bi == 4'd1 && m_type == 8'h55);
    wire probe_inflight = pr_pending_old || pr_pending_new || pr_active ||
                          arm_old_this || arm_new_this;

    // niveles: [side*P + slot] = precio, qty (mejor primero)
    reg [PXW-1:0] lv_price [NSYM*2*P-1:0];
    reg [QW-1:0]  lv_qty   [NSYM*2*P-1:0];

    // ---------------------------------------------------------------
    // pipeline de niveles (fase3-uram iter 3): level_add partido en 3 etapas
    // registradas para cerrar 3,103 ns (bloqueador B2: la pasada O(P)
    // combinacional media 6-8 ns).
    //   Etapa 1 (ST_APPLY/ST_UADD): captura del lado + predicados por slot
    //     (eq/zer/stop) + sumas candidatas — todo por slot, sin encadenar.
    //   Etapa 2 (ST_LV2): decode por prioridad (found/empty/ins, newq, modo,
    //     error) sobre los registros de la etapa 1.
    //   Etapa 3 (ST_LV3): materialización (muxes 2:1/3:1 por slot) + escritura
    //     única de lv_price/lv_qty. Invariantes de fase 3 intactos: nivel
    //     vacío no existe (el remove barre precio Y cantidad), jamás precio
    //     stale ni cantidad envuelta (modo NONE en error).
    // ---------------------------------------------------------------
    localparam LV_MODE_NONE   = 2'd0;
    localparam LV_MODE_UPDATE = 2'd1;
    localparam LV_MODE_INSERT = 2'd2;
    localparam LV_MODE_REMOVE = 2'd3;
    // parámetros de la operación en curso (etapa 1)
    reg        lv_en;          // hay operación de nivel lanzada (etapa 1)
    reg        lv_uadd;        // tras la 1ª op (delete del U) hay que ir a ST_UADD
    reg [PXW-1:0] lv_lprice;
    reg signed [31:0] lv_delta;
    reg [31:0] lv_base;
    reg [PXW-1:0] lv_pr[0:P-1];   // copia del lado (pre-op)
    reg [QW-1:0]  lv_qt[0:P-1];
    reg [P-1:0]  lv_eq;           // lv_qt[i]!=0 && lv_pr[i]==precio (found)
    reg [P-1:0]  lv_zer;          // lv_qt[i]==0 (primer hueco)
    reg [P-1:0]  lv_beat;         // el nivel i es ESTRICTAMENTE peor que el
                                  // precio nuevo (burbuja de inserción: el
                                  // elemento nuevo lo vence y lo desplaza)
    reg signed [32:0] lv_cand_newq[0:P-1];   // qty[i]+delta por slot (paralelo)
    // decode de la etapa 2 (registrado; la etapa 3 los consume 1 ciclo tarde)
    // 32 bits para comparar contra índices integer sin WIDTHEXPAND
    reg [31:0] lv2_found, lv2_empty, lv2_ins;
    reg [31:0] lv2_newq;
    reg [1:0]  lv2_mode;
    // materialización (etapa 3): muxes por modo, luego escritura única
    reg [PXW-1:0] wp[0:P-1];
    reg [QW-1:0]  wq[0:P-1];

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
reg [SLOT-1:0] u_nidx;      // slot pre-verificado de la mitad add (U atómico)

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
    // probe engine: avanza 1 slot/ciclo aunque el FSM esté recibiendo el
    // cuerpo (prefetch). Vive DENTRO del always_ff del FSM (un solo driver:
    // el armado en ST_BODY y el arranque/avance comparten flanco y proceso)
    // ---------------------------------------------------------------
    // FSM principal
    // ---------------------------------------------------------------
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            st <= ST_INVAL;
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
            u_price <= 0; u_shares <= 0; u_nidx <= 0;
            for (int i = 0; i < NSYM; i++) tstate[i] <= 8'h00;
            bi <= 0; nbody_w <= 0; hrem <= 2'd1; emit_ok <= 1'b0;
            for (int i = 0; i < NSYM; i++) loc_map[i] <= 16'hffff;
            loc_cnt <= 0; m_loc_idx <= 0; bad_sym <= 1'b0;
            // la URAM no se resetea (patrón de inferencia): ST_INVAL la
            // invalida entera a 1 slot/ciclo
            st_inval_cnt <= 0;
            // estado del probe engine (mismo flanco, un solo driver)
            pr_phase <= PR_IDLE;
            pr_pending_old <= 1'b0; pr_pending_new <= 1'b0;
            rd_addr <= 0; rd_data <= 0;
            pr_base <= 0; pr_target <= 0; pr_i <= 0;
            pr_rec_empty <= 1'b0; pr_need_empty <= 1'b0; pr_is_old <= 1'b1;
            w_empty_found <= 1'b0;
            pr_found <= 1'b0; pr_slot <= 0; pr_entry <= 0;
            pr_empty_found <= 1'b0; pr_empty <= 0; pr_full <= 1'b0;
            pr_new_found <= 1'b0; pr_new_empty <= 0; pr_new_full <= 1'b0;
            pr_oref <= 0; pr_newref <= 0;
            // pipeline de niveles (etapa 1 + decode + materialización)
            lv_en <= 1'b0; lv_uadd <= 1'b0;
            lv_lprice <= 0; lv_delta <= 32'sd0; lv_base <= 0;
            for (int i = 0; i < P; i++) begin
                lv_pr[i] <= 0; lv_qt[i] <= 0;
                lv_eq[i] <= 1'b0; lv_zer[i] <= 1'b0; lv_beat[i] <= 1'b0;
                lv_cand_newq[i] <= 33'sd0;
                wp[i] <= 0; wq[i] <= 0;
            end
            lv2_found <= 0; lv2_empty <= 0; lv2_ins <= 0;
            lv2_newq <= 32'd0; lv2_mode <= LV_MODE_NONE;
        end else begin
            // retención AXI (SEC-BP-01): el par BBO/depth se mantiene válido
            // hasta que su tready lo acepta; el guard de ST_APPLY frena el
            // pipeline mientras penda (sin pérdida ni duplicado)
            bbo_tvalid <= bbo_tvalid && !bbo_tready;
            depth_tvalid <= depth_tvalid && !depth_tready;
            error <= 1'b0;

            // ---- probe engine (sonda serializada): avanza 1 slot/ciclo
            // aunque el FSM esté recibiendo el cuerpo (prefetch). La lectura
            // es REGISTRADA (rd_data <= o_mem[rd_addr]) — patrón URAM.
            rd_data <= o_mem[rd_addr];
            if (pr_start_old) begin
                pr_pending_old <= 1'b0;
                pr_phase <= PR_WARM;
                pr_i <= 16'd0;
                pr_base <= pr_oref[SLOT-1:0];
                pr_target <= REFW'(pr_oref);
                pr_rec_empty <= pr_need_empty;
                pr_is_old <= 1'b1;
                w_empty_found <= 1'b0;
                pr_found <= 1'b0; pr_slot <= 0; pr_entry <= 0;
                pr_empty_found <= 1'b0; pr_empty <= 0; pr_full <= 1'b0;
                rd_addr <= pr_oref[SLOT-1:0];
            end else if (pr_start_new) begin
                pr_pending_new <= 1'b0;
                pr_phase <= PR_WARM;
                pr_i <= 16'd0;
                pr_base <= pr_newref[SLOT-1:0];
                pr_target <= REFW'(pr_newref);
                pr_rec_empty <= 1'b1;
                pr_is_old <= 1'b0;
                w_empty_found <= 1'b0;
                pr_new_found <= 1'b0; pr_new_empty <= 0; pr_new_full <= 1'b0;
                rd_addr <= pr_newref[SLOT-1:0];
            end else if (pr_phase == PR_WARM) begin
                pr_phase <= PR_WALK;
                rd_addr <= pr_base + 16'd1;
            end else if (pr_phase == PR_WALK) begin
                // evalúa el dato leído hace 1 ciclo (rd_data); el slot en
                // evaluación es pr_base + pr_i (pr_i previo al incremento).
                // Los resultados se LATCHAN en el set del run en curso con
                // writes directos (un latch task con NB leería el valor viejo
                // de los registros de trabajo: race de 1 ciclo)
                if (rd_data[0] && (rd_data[REFW:1] == pr_target)) begin
                    if (pr_is_old) begin
                        pr_found <= 1'b1;
                        pr_slot <= pr_base + pr_i;
                        pr_entry <= rd_data;
                    end else begin
                        pr_new_found <= 1'b1;
                    end
                    pr_phase <= PR_IDLE;
                end else begin
                    if (!rd_data[0] && pr_rec_empty && !w_empty_found) begin
                        w_empty_found <= 1'b1;
                        if (pr_is_old) begin
                            pr_empty_found <= 1'b1;
                            pr_empty <= pr_base + pr_i;
                        end else begin
                            pr_new_empty <= pr_base + pr_i;
                        end
                    end
                    if (pr_i == 16'(PROBE-1)) begin
                        // último slot del camino: no encontrada; llena si el
                        // camino no tenía ningún hueco (insert A/F, U-new).
                        // OJO: el hueco del slot ACTUAL se latchea en la rama
                        // de arriba en este mismo ciclo (w_empty_found NB); la
                        // lectura de w_empty_found aquí vería el valor VIEJO —
                        // por eso se exige además rd_data[0] (slot ocupado):
                        // si el hueco es el propio slot terminal, el empty ya
                        // quedó registrado y NO es tabla llena (race 2026-08-14).
                        if (pr_rec_empty && !w_empty_found && rd_data[0]) begin
                            if (pr_is_old) pr_full <= 1'b1;
                            else pr_new_full <= 1'b1;
                        end
                        pr_phase <= PR_IDLE;
                    end else begin
                        pr_i <= pr_i + 1;
                        // el addr del PRÓXIMO slot: pr_i+2 (pr_i es el slot en
                        // evaluación; la transición WARM ya emitió base+1 y
                        // pr_i+1 re-emitiría el slot actual: desfase de 1
                        // ciclo entre el dato leído y el slot evaluado)
                        rd_addr <= pr_base + (pr_i + 2);
                    end
                end
            end

            case (st)
                ST_INVAL: begin
                    // invalidación post-reset: los 65.536 slots a valid=0
                    // (jamás reset global del array: mataría la URAM)
                    mem_wr(st_inval_cnt, {OW{1'b0}});
                    if (st_inval_cnt == NSLOT-1) st <= ST_W0;
                    else st_inval_cnt <= st_inval_cnt + 1;
                end
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
                        // cabecera restante tras w0: DW=64 ninguna word extra;
                        // DW=32 una sola (w1=msg_idx) — las words de ts del
                        // Anexo A se recortaron (fase3-uram criterio 1)
                        hrem <= 2'd1;
                        bi <= 0;
                        st <= ST_TS;
                    end
                end
                ST_TS: begin
                    // consume la word restante de la cabecera (DW=32: w1=idx,
                    // único resto tras el recorte del Anexo A — sin ts)
                    if (s_axis_tvalid) begin
                        if (DW == 32) m_idx <= s_axis_tdata[31:0];
                        if (hrem == 2'd1) st <= ST_BODY;
                        else hrem <= hrem - 1;
                    end
                end
                ST_BODY: begin
                    if (s_axis_tvalid) begin
                        body_acc[bi] <= s_axis_tdata;
                        // PREFETCH (fase3-uram): el grupo de hash del mensaje
                        // en curso se lee durante la recepción del cuerpo. La
                        // order_ref (bytes 0-7) se completa con la 2ª word a
                        // DW=32 (o la 1ª a DW=64); la newref del U con la 4ª
                        // (o la 2ª). El probe engine las recoge al arrancar.
                        if (DW == 32) begin
                            if (bi == 4'd1 && lt(m_type)) begin
                                pr_pending_old <= 1'b1;
                                pr_oref <= K'({body_acc[0], s_axis_tdata});
                                pr_need_empty <= (m_type == 8'h41 ||
                                                  m_type == 8'h46);
                            end
                            if (bi == 4'd3 && m_type == 8'h55) begin
                                pr_pending_new <= 1'b1;
                                pr_newref <= K'({body_acc[2], s_axis_tdata});
                            end
                        end else begin
                            if (bi == 4'd0 && lt(m_type)) begin
                                pr_pending_old <= 1'b1;
                                pr_oref <= K'(s_axis_tdata);
                                pr_need_empty <= (m_type == 8'h41 ||
                                                  m_type == 8'h46);
                            end
                            if (bi == 4'd1 && m_type == 8'h55) begin
                                pr_pending_new <= 1'b1;
                                pr_newref <= K'(s_axis_tdata);
                            end
                        end
                        if (s_axis_tlast) begin
                            // fin del burst (cuerpo): el prefetch pudo no
                            // acabar (cuerpo corto) -> ST_WAIT_PROBE. probe_
                            // inflight incluye el armado de ESTE ciclo (NB no
                            // visible): ningún mensaje escapa a ST_APPLY con
                            // un probe en vuelo o a punto de armarse
                            st <= probe_inflight ? ST_WAIT_PROBE : ST_APPLY;
                        end else if (nbody_w <= 1) begin
                            st <= probe_inflight ? ST_WAIT_PROBE : ST_APPLY;
                        end else begin
                            bi <= bi + 1;
                            nbody_w <= nbody_w - 1;
                        end
                    end
                end
                ST_WAIT_PROBE: begin
                    // espera del probe serializado (solo cuerpos cortos; el
                    // prefetch lo evita en el caso normal)
                    if (!pr_pending_old && !pr_pending_new && !pr_active)
                        st <= ST_APPLY;
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
                            apply_one(do_uadd, lv_en);
                            lv_uadd <= do_uadd;   // el U pide la mitad add tras la 1ª op
                            if (do_uadd || lv_en) st <= ST_LV2;
                            else if (m_type == 8'h41 || m_type == 8'h46 || m_type == 8'h45 ||
                                     m_type == 8'h43 || m_type == 8'h58 || m_type == 8'h44 ||
                                     m_type == 8'h55) st <= ST_EMIT;
                            else st <= ST_W0;
                        end
                    end
                end
                ST_LV2: begin
                    // etapa 2 del pipeline: decode por prioridad sobre los
                    // registros capturados en ST_APPLY/ST_UADD (visibles aquí,
                    // un ciclo después del launch); el resultado queda
                    // registrado y la etapa 3 lo consume un ciclo tarde
                    decode_lv2();
                    st <= ST_LV3;
                end
                ST_LV3: begin
                    // etapa 3: materializa la lista nueva según el decode y la
                    // escribe de una sola vez (única escritura del lado)
                    materialize_write();
                    st <= lv_uadd ? ST_UADD : ST_EMIT;
                end
                ST_UADD: begin
                    // mitad add del replace: la segunda operación de nivel ve
                    // el estado del ciclo anterior (la eliminación ya aplicada
                    // en la ST_LV3 previa)
                    launch_lv(u_side, u_price, u_shares);
                    mem_wr(u_nidx, entry_new(u_newref, u_side, u_price, u_shares));
                    lv_uadd <= 1'b0;
                    st <= ST_LV2;
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
    // pipeline de niveles (fase3-uram iter 3). launch_lv = etapa 1: captura
    // el lado en curso (lv_pr/lv_qt) y computa por slot los predicados
    // (lv_eq/lv_zer/lv_beat) y las sumas candidatas (lv_cand_newq) — rutas
    // cortas por slot, sin encadenar la pasada O(P). Se llama en ST_APPLY
    // (operaciones de A/F/E/C/X/D/U) y en ST_UADD (mitad add del replace).
    // ---------------------------------------------------------------
    task automatic launch_lv;
        input        ask;
        input [PXW-1:0] price;
        input signed [31:0] delta;
        integer i;
        integer base;
        begin
            base = m_loc_idx*2*P + (ask ? P : 0);
            lv_lprice <= price;
            lv_delta <= delta;
            lv_base <= base;
            for (i = 0; i < P; i = i + 1) begin
                lv_pr[i] <= lv_price[base+i];
                lv_qt[i] <= lv_qty[base+i];
                lv_eq[i] <= (lv_qty[base+i] != 0) && (lv_price[base+i] == price);
                lv_zer[i] <= (lv_qty[base+i] == 0);
                lv_beat[i] <= (lv_qty[base+i] != 0) &&
                              (ask ? (lv_price[base+i] > price)
                                   : (lv_price[base+i] < price));
                lv_cand_newq[i] <= $signed(33'(lv_qty[base+i])) + $signed(33'(delta));
            end
        end
    endtask

    // ---------------------------------------------------------------
    // etapa 3: materializa la lista nueva según el decode de la etapa 2 y la
    // escribe de una sola vez. Semántica idéntica a la pasada O(P) de fase 3:
    //   REMOVE -> barrido a la izquierda (el hueco de found se compacta)
    //   INSERT -> el elemento nuevo entra en lv2_ins (burbuja de inserción) y
    //             [lv2_ins..empty-1] se desplaza a la derecha
    //   UPDATE -> solo cambia la cantidad de lv2_found
    //   NONE   -> copia (errores: overflow, reduce sobre nivel ausente,
    //             cantidad que envuelve — jamás precio stale ni fantasma)
    // ---------------------------------------------------------------
    task automatic materialize_write;
        integer i;
        begin
            for (i = 0; i < P; i = i + 1) begin
                if (lv2_mode == LV_MODE_REMOVE) begin
                    wp[i] = (i < lv2_found) ? lv_pr[i]
                          : ((i < P-1) ? lv_pr[i+1] : PXW'(0));
                    wq[i] = (i < lv2_found) ? lv_qt[i]
                          : ((i < P-1) ? lv_qt[i+1] : QW'(0));
                end else if (lv2_mode == LV_MODE_INSERT) begin
                    wp[i] = (i <= lv2_empty) ? ((i < lv2_ins) ? lv_pr[i]
                          : ((i == lv2_ins) ? lv_lprice : lv_pr[i-1])) : lv_pr[i];
                    wq[i] = (i <= lv2_empty) ? ((i < lv2_ins) ? lv_qt[i]
                          : ((i == lv2_ins) ? QW'(lv_delta[31:0]) : lv_qt[i-1]))
                          : lv_qt[i];
                end else if (lv2_mode == LV_MODE_UPDATE) begin
                    wp[i] = lv_pr[i];
                    wq[i] = (i == lv2_found) ? QW'(lv2_newq[31:0]) : lv_qt[i];
                end else begin
                    wp[i] = lv_pr[i];
                    wq[i] = lv_qt[i];
                end
            end
            for (i = 0; i < P; i = i + 1) begin
                lv_price[lv_base+i] <= wp[i];
                lv_qty[lv_base+i]   <= wq[i];
            end
        end
    endtask

    // ---------------------------------------------------------------
    // etapa 2 del pipeline: decode por prioridad (encoders first-hot) sobre
    // los registros capturados en ST_APPLY/ST_UADD. El resultado queda
    // registrado en lv2_* (non-blocking) y la etapa 3 lo consume un ciclo
    // tarde; el pulso de error se muestra aquí (1 ciclo, como en fase 3).
    // Semántica idéntica a la pasada O(P) de fase 3:
    //   found  -> primer slot con el precio objetivo (nivel existente)
    //   empty  -> primer slot vacío (hueco de inserción)
    //   ins    -> burbuja de inserción: j = primer nivel ESTRICTAMENTE peor
    //             que el precio nuevo (lv_beat); si ninguno (elemento peor
    //             de todos), el elemento se queda en el hueco (j = empty).
    //             Los vencidos forman un sufijo por invariante de orden.
    // ---------------------------------------------------------------
    task automatic decode_lv2;
        integer i, fnd, emp, btx;
        reg lverr;
        begin
            fnd = -1; emp = -1; btx = -1; lverr = 1'b0;
            for (i = 0; i < P; i = i + 1) begin
                if (fnd == -1 && lv_eq[i]) fnd = i;
                if (emp == -1 && lv_zer[i]) emp = i;
                if (btx == -1 && lv_beat[i]) btx = i;
            end
            lv2_found <= fnd;
            lv2_empty <= emp;
            btx = (btx == -1) ? emp : btx;
            lv2_ins <= btx;
            if (fnd == -1 && emp == -1) begin
                // overflow de niveles (SEC-OV-01): la op se descarta
                lv2_mode <= LV_MODE_NONE;
                lverr = 1'b1;
            end else if (fnd == -1 && lv_delta[31]) begin
                // reduce sobre un nivel que no existe (orden en tabla sin
                // nivel por overflow previo): jamás una cantidad envuelta
                // (hallazgo G5)
                lv2_mode <= LV_MODE_NONE;
                lverr = 1'b1;
            end else if (fnd == -1) begin
                lv2_mode <= LV_MODE_INSERT;
            end else begin
                lv2_newq <= lv_cand_newq[fnd][31:0];
                if (lv_cand_newq[fnd][32]) begin
                    // la cantidad envolvería 32 bits: descarte (jamás phantom)
                    lv2_mode <= LV_MODE_NONE;
                    lverr = 1'b1;
                end else if (lv_cand_newq[fnd] == 0) begin
                    lv2_mode <= LV_MODE_REMOVE;   // nivel vacío no existe
                end else begin
                    lv2_mode <= LV_MODE_UPDATE;
                end
            end
            error <= lverr;
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

    task automatic apply_one(output logic out_uadd, output logic out_lv);
        reg [K-1:0] oref, newref;
        reg [31:0] shares, price;
        reg ask;
        reg [7:0] ev;
        reg do_emit;
        reg [33:0] rest;
        reg [QW-1:0] qty_old;
        begin
            do_emit = 1'b0;
            out_uadd = 1'b0;
            out_lv = 1'b0;
            // la tabla ya fue leída por la sonda (prefetch): los resultados
            // pr_found/pr_slot/pr_entry/pr_empty/pr_full son del run que
            // terminó ANTES de ST_APPLY (ST_WAIT_PROBE lo garantiza)
            case (m_type)
                8'h41, 8'h46: begin
                    oref = K'(b64(0)); ask = (pbody(8) == 8'h53);
                    shares = b32(9); price = b32(21);
                    if (pr_found || shares == 0) begin
                        error <= 1'b1;      // ref duplicada o cantidad inválida
                    end else if (pr_full) begin
                        error <= 1'b1;      // tabla llena (SEC-HASH-02)
                    end else begin
                        mem_wr(pr_empty, entry_new(oref, ask, price, shares));
                        launch_lv(ask, price, shares);
                        out_lv = 1'b1;
                        do_emit = 1'b1;
                    end
                end
                8'h45, 8'h43, 8'h58: begin
                    oref = K'(b64(0));
                    if (!pr_found) begin
                        anomaly_count <= anomaly_count + 1;
                    end else begin
                        // reduce desde la entrada capturada por la sonda
                        qty_old = e_qty(pr_entry[OW-1:OW-QW]);
                        rest = {2'b0, qty_old} - {2'b0, b32(8)};
                        if (rest[33]) error <= 1'b1;   // execute > restante
                        else if (rest == 0) begin
                            launch_lv(e_side(pr_entry[REFW+1]), e_price(pr_entry[REFW+PXW+1:REFW+2]),
                                      -$signed(qty_old));
                            mem_wr(pr_slot, {OW{1'b0}});   // valid=0
                            out_lv = 1'b1;
                            do_emit = 1'b1;
                        end else begin
                            mem_wr(pr_slot, {rest[31:0], e_price(pr_entry[REFW+PXW+1:REFW+2]),
                                             e_side(pr_entry[REFW+1]), e_ref(pr_entry[REFW:1]),
                                             1'b1});
                            launch_lv(e_side(pr_entry[REFW+1]), e_price(pr_entry[REFW+PXW+1:REFW+2]),
                                      -32'(b32(8)));
                            out_lv = 1'b1;
                            do_emit = 1'b1;
                        end
                    end
                end
                8'h44: begin
                    oref = K'(b64(0));
                    if (!pr_found) anomaly_count <= anomaly_count + 1;
                    else begin
                        launch_lv(e_side(pr_entry[REFW+1]), e_price(pr_entry[REFW+PXW+1:REFW+2]),
                                  -$signed(e_qty(pr_entry[OW-1:OW-QW])));
                        mem_wr(pr_slot, {OW{1'b0}});
                        out_lv = 1'b1;
                        do_emit = 1'b1;
                    end
                end
                8'h55: begin
                    oref = K'(b64(0)); newref = K'(b64(8));
                    shares = b32(16); price = b32(20);
                    if (!pr_found) anomaly_count <= anomaly_count + 1;
                    else if (shares == 0) error <= 1'b1;
                    else if (pr_new_found) error <= 1'b1;   // newref duplicada
                    else if (pr_new_full) error <= 1'b1;    // U atómico: la
                        // original sobrevive (la capacidad se chequeó en la
                        // sonda, ANTES del delete — hallazgo G5)
                    else begin
                        launch_lv(e_side(pr_entry[REFW+1]), e_price(pr_entry[REFW+PXW+1:REFW+2]),
                                  -$signed(e_qty(pr_entry[OW-1:OW-QW])));
                        mem_wr(pr_slot, {OW{1'b0}});
                        u_newref <= newref;
                        u_side <= e_side(pr_entry[REFW+1]);
                        u_price <= price;
                        u_shares <= shares;
                        u_nidx <= pr_new_empty;
                        out_lv = 1'b1;
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
