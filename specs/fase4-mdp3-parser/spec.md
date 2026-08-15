# fase4-mdp3-parser (fase 4 del maestro — Stretch: port a CME MDP 3.0)

## Goal

Portar el parser del pipeline de ITCH a **CME MDP 3.0** (SBE — Simple Binary
Encoding): un parser RTL que decodifica el paquete MDP 3.0 (Binary Packet
Header + mensajes SBE con su framing) y emite registros normalizados
("Anexo M") para el subset de templates de libro (incremental book + snapshot),
con **passthrough crudo** del resto de templates, verificado **bit a bit contra
un golden model Python generado desde el schema XML oficial de CME**.

El maestro lo fija como capítulo final: *«portar tu pipeline de ITCH a MDP3
(aunque sea solo el parser SBE verificado con paquetes sintéticos generados
desde los schemas XML) demuestra generalidad de diseño y conocimiento del
protocolo del mayor mercado de futuros del mundo»*.

## Scope

**In scope:**

- **Golden model MDP3** (`golden_model/mdp3/`): loader del schema SBE XML
  (templates, campos con offsets, grupos repetitivos, tipos compuestos),
  decoder (paquete → mensajes → registros Anexo M), generator (corpus
  sintético SBE válido) y vectores.
- **Fetch del schema**: `scripts/fetch_mdp3_schema.py` (CME FTP por HTTPS,
  con **fallback al archivo oficial vía Wayback Machine** y md5 pinned
  fail-closed, porque cmegroup.com responde 403 al bot) →
  `data/mdp3/` (gitignored, regla G0: los schemas son spec, no
  datos de mercado, pero se mantienen fuera del repo igualmente). Schema
  pinned: `templates_FixBinary_v12.xml` (2021-03-10, id=1 version=12,
  byteOrder=littleEndian), md5 en el propio script.
- **RTL `rtl/parser/mdp3_parser.sv`** (nuevo, no toca `itch_parser.sv`):
  decodifica el paquete (MsgSeqNum u32 + SendingTime u64, 12 B), el framing
  por mensaje (MessageSize u16 + cabecera SBE 8 B: blockLength/templateId/
  schemaId/version) y el subset de templates; emite Anexo M por AXI-Stream.
  DW parametrizado (32 objetivo @ 322,265625 MHz; 64 en regresión).
- **Gaps de secuencia por canal**: contiguidad de MsgSeqNum (un canal por
  instancia) → `gap_detected` (misma semántica que MoldUDP64 en fase 1).
- **Verificación**: cocotb vs golden bit a bit (corpus sintético +
  invariantes) + mutación del parser MDP3 + regresión de fases 1-3.

**Out of scope (non-goals):**

- Port del order book a MDP3 (campaña 4b posterior; el Anexo M está diseñado
  para alimentarla).
- Arbitraje de feeds A/B, TCP recovery, demux multi-canal (config.xml):
  una instancia = un canal.
- Decodificar el campo a campo de templates no-libro (statistics, trades,
  instrument definitions, security status): passthrough crudo con su
  template_id (routing transparente).
- Datos reales de DataMine (de pago): el corpus es sintético, generado desde
  el schema. Si algún día se paga por pcaps, se re-alimenta el mismo banco
  (REPLAY-03 opcional, no bloqueante).
- iLink 3 (SBE de órdenes de cliente): solo market data.

**Radio medido (2026-08-14):** el RTL nuevo (`mdp3_parser.sv`) no consume
nada existente: se añade junto a `itch_parser.sv` (que no se toca). Solo
cambia `specs/gherkin-espejos.json` (área nueva). Los nombres de fichero y
área siguen la convención de fases 1-3.

**Changelog 2026-08-14 (edit de build con evidencia):** el schema oficial
`templates_FixBinary_v12.xml` (archivado de cmegroup.com vía Wayback, md5
verificado) corrige el contrato: **byte-order little-endian** (la spec decía
big-endian), **IDs del subset 46/47/52/53** (la spec esperaba los de la era
pre-event 27/30/32), **msg_size incluye el prefijo de 10 B** (evidencia
roq-cme `parser.cpp`), y **dos dimensionTypes de grupo** (`groupSize` 3 B /
`groupSize8Byte` 8 B). El Anexo M gana el record MBOFD (18 words) con
`record_type` en w7[23] y la tabla de derivación por template. Los criterios
1-9 y el gherkin no cambian de contenido (M3-SUB-01/02 ya eran genéricos).

## Constraints

- **Familia/part objetivo:** UltraScale+ (misma familia que fases 1-3);
  frecuencia 322,265625 MHz (DW=32) y 156,25 MHz (DW=64) — mismo régimen.
- **Régimen de entrada:** el datapath presenta una palabra por ciclo y solo
  cuenta backpressure cuando `s_axis_tvalid && !s_axis_tready`. El vector
  pactado M3-FRM-03 son 24 mensajes literales del template 47, cada uno con
  una entry (64 B derivados del XML); la racha máxima admitida es 16 ciclos.
  No se promete un feed infinito sin stalls: un record Anexo M MBOFD expande
  64 B de mensaje a 72 B de salida.
- **Schema = fuente única:** los offsets, blockLength, tipos compuestos y
  valores de enumeraciones del subset se derivan del schema XML
  (`templates_FixBinary.xml`, ftp.cmegroup.com) en el golden. **Ningún
  literal de offset/tag a mano en RTL ni en testbench** (regla de
  `messages.py` de las fases 0-3; violación = FAIL de la lente 6).
- **SBE:** little-endian (byteOrder del XML oficial de CME; confirmado por la
  implementación de referencia roq-cme, `little_endian_to_host`); cabecera de
  mensaje 8 B; grupos con dimensión de dos formas — `groupSize` = blockLength
  u16 + numInGroup u8 (3 B) y `groupSize8Byte` = blockLength u16 + 5 B de pad
  + numInGroup u8 (8 B, usada por NoOrderIDEntries). El RTL consume
  `msg_size` sin re-derivar alineación (los offsets viven en el XML y el
  golden los respeta tal cual).
- **Determinismo:** mismo stream → misma secuencia de Anexo M, bit a bit;
  sin pérdida ni doble cuenta, con y sin backpressure de salida.
- **Bytes válidos AXI:** la entrada incluye `s_axis_tkeep[DW/8-1:0]` con
  semántica AXI estándar. Todo beat no final usa todos los lanes; el último usa
  un prefijo MSB contiguo. Los lanes con `tkeep=0` no cuentan para `msg_size`.
  Máscaras con huecos, cero o parciales sin `tlast` pulsan `error` y descartan
  el paquete, drenándolo hasta `tlast` si el beat inválido no era final.
  Contrato completo:
  `docs/superpowers/specs/2026-08-15-axis-tkeep-framing-design.md`.
- **Framing confirmado:** paquete = MsgSeqNum(u32) + SendingTime(u64, ns
  desde epoch) = 12 B; cada mensaje = **MessageSize(u16) que INCLUYE los
  10 B de prefijo** (MessageSize + cabecera SBE de 8 B: blockLength/
  templateId/schemaId/version) + cuerpo (blockLength + grupos). Varios
  mensajes por paquete. La cabecera de mensaje y las dimensiones de grupo
  viven en el XML (`messageHeader`, `groupSize`, `groupSize8Byte`).

## Superficie y amenazas

**Puertos de `mdp3_parser`** (convención AXI-Stream de fase 1):

| Señal | Ancho | Descripción |
|---|---|---|
| `clk`, `rst_n` | 1 | reloj del datapath |
| `s_axis_tdata/tkeep/tvalid/tready/tlast` | DW/(DW/8)/1/1/1 | payload UDP decapado; `tkeep` marca bytes válidos del beat |
| `m_axis_tdata/tvalid/tready/tlast` | 32/1/1/1 | words de 32 bits del Anexo M; DW solo parametriza la entrada |
| `gap_detected` | 1 | pulso: MsgSeqNum != exp_seq (por canal) |
| `error` | 1 | pulso: mensaje/paquete incoherente (msg_size < 10, desborde de paquete) |

**Anexo M** (registro normalizado por mensaje; un record por ENTRY para los
templates de libro; layout MSB-first por palabra, DW=32). Dos tipos de
record, distinguidos por `record_type` en w7[23]: **MBP** (13 words) y
**MBOFD** (18 words); el burst de cada record termina con `tlast` y el
consumidor sabe el largo por el propio tipo.

Record **MBP** (46 NoMDEntries, 52 NoMDEntries):

| Word | Contenido (subset decodificado) |
|---|---|
| w0 | `{template_id[15:0], msg_size[15:0]}` |
| w1 | `{schema_id[15:0], version[15:0]}` |
| w2, w3 | `transact_time[63:0]` (u64 ns) |
| w4 | `{match_event_indicator[7:0], 24'b0}` |
| w5 | `security_id[31:0]` |
| w6 | `rpt_seq[31:0]` |
| w7 | `{record_type[7:0]=0, md_update_action[7:0], md_entry_type[7:0], 16'b0}` |
| w8, w9 | `md_entry_px.mantissa[63:0]` (i64) |
| w10 | `{md_entry_px.exponent[7:0], 24'b0}` (i8) |
| w11 | `md_entry_size[31:0]` (i32) |
| w12 | `{num_orders[15:0], md_price_level[15:0]}` |

Record **MBOFD** (46 NoOrderIDEntries, 47 NoMDEntries, 53 NoMDEntries):

| Word | Contenido |
|---|---|
| w0-w6 | igual que MBP (misma semántica; la derivación por template fija qué campo alimenta cada word) |
| w7 | `{record_type[7:0]=1, action[7:0], md_entry_type[7:0], 16'b0}` (action: 279 en 47, 37708 en 46) |
| w8, w9 | `order_id[63:0]` (u64) |
| w10, w11 | `md_order_priority[63:0]` (u64NULL) |
| w12 | `{reference_id[7:0], 24'b0}` (9633; 0 si no aplica) |
| w13, w14 | `md_entry_px.mantissa[63:0]` (i64) |
| w15 | `{md_entry_px.exponent[7:0], 24'b0}` (i8; PRICE9 ⇒ -9 constante) |
| w16 | `md_display_qty[31:0]` (i32) |
| w17 | `32'b0` (reservado) |

Passthrough (resto de templates): `w0, w1` + cuerpo crudo byte a byte
(relleno 0 al final), sin decodificar. El burst termina con `tlast`
(convención fase 1); campos del subset ausentes en un template concreto →
0 (la tabla de derivación es la autoridad).

**Subset decodificado** (los IDs numéricos se derivan del schema; el schema
pinned es `templates_FixBinary_v12.xml`, 2021-03-10, que ya no usa los IDs de
la era pre-event 27/30/32):

- **46 = MDIncrementalRefreshBook** (X, combined MBP+MBOFD): root
  blockLength=11 (TransactTime 60, MatchEventIndicator 5799); grupo
  **NoMDEntries** (268, blockLength=32, MBP) con por entry: MDEntryPx (270,
  PRICENULL9 = mantissa i64 + exponent i8), MDEntrySize (271), SecurityID
  (48), RptSeq (83), NumberOfOrders (346), MDPriceLevel (1023), MDUpdateAction
  (279), MDEntryType (269), TradeableSize (37719); grupo **NoOrderIDEntries**
  (37705, blockLength=24, `groupSize8Byte`, MBOFD) con por entry: OrderID
  (37), MDOrderPriority (37707), MDDisplayQty (37706), ReferenceID (9633 →
  índice de la entry MBP del mismo mensaje), OrderUpdateAction (37708).
- **47 = MDIncrementalRefreshOrderBook** (X, MBOFD only): root 11; grupo
  NoMDEntries (268, blockLength=40) con por entry: OrderID (37 u64NULL),
  MDOrderPriority (37707), MDEntryPx (270 PRICENULL9), MDDisplayQty (37706),
  SecurityID (48), MDUpdateAction (279), MDEntryType (269).
- **52 = SnapshotFullRefresh** (W, MBP): root blockLength=59 (incluye
  LastMsgSeqNumProcessed 369, TotNumReports 911, SecurityID 48, RptSeq 83,
  TransactTime 60, límites 1149/1148/1143); grupo NoMDEntries (268,
  blockLength=22, MBP) sin MDUpdateAction ni SecurityID/RptSeq por entry
  (viven en el root) y MDEntryType (269) genérico.
- **53 = SnapshotFullRefreshOrderBook** (W, MBOFD): root 28 (incluye
  SecurityID 48, NoChunks 37709, CurrentChunk 37710, TransactTime 60); grupo
  NoMDEntries (268, blockLength=29) con por entry: OrderID (37 u64),
  MDOrderPriority (37707), MDEntryPx (270 PRICE9 = mantissa i64, exponent
  constante -9), MDDisplayQty (37706 Int32), MDEntryType (269). Sin action
  (snapshot).
- El resto (admin 4/12/15/16, SecurityStatus 30, Volume 37, QuoteRequest 39,
  TradeSummary 48, statistics 49-51, instrument definitions 54-58, etc.):
  passthrough.

**Derivación del Anexo M por template** (qué campo alimenta cada word; el
golden y el RTL la aplican, y el bit a bit la verifica):

| Template | record_type (w7[23]) | w5 security_id | w6 rpt_seq | w7 action | px (w8-w10) | w11 size | w12 {num_orders, price_level} | w8-w9/w10-w11/w12/w16 (MBOFD) |
|---|---|---|---|---|---|---|---|---|
| 46 MBP | 0 | 48 entry | 83 entry | 279 entry | 270 entry | 271 entry | {346, 1023} | — |
| 46 MBOFD | 1 | 48 del MBP linkeado (ReferenceID) | 83 del MBP linkeado | 37708 entry | 270 del MBP linkeado | — (w16 = 37706 display_qty) | — | order_id 37, priority 37707, reference 9633 |
| 47 | 1 | 48 entry | 0 (ausente) | 279 entry | 270 entry | — (w16 = 37706) | — | order_id 37, priority 37707, reference 0 |
| 52 | 0 | 48 root | 83 root | 0 (sin action) | 270 entry | 271 entry | {346, 1023} | — |
| 53 | 1 | 48 root | 0 (ausente) | 0 (sin action) | 270 entry (PRICE9, exponent -9 const) | — (w16 = 37706) | — | order_id 37, priority 37707, reference 0 |

**Casos de abuso del dominio** (cada uno con escenario `SEC-`/`INV-`):

- **Mensaje mínimo back-to-back** (paquete lleno de mensajes mínimos) →
  peor caso line-rate. — M3-FRM-03.
- **Mensaje que cruza límites de palabra y de paquete** (payload UDP
  termina en medio de un mensaje SBE) → alineación y reanudación correctas,
  sin pérdida. — M3-FRM-02, M3-INV-02.
- **Truncado sub-word**: faltan entre 1 y `DW/8-1` bytes antes de `tlast`; los
  lanes inválidos no pueden completar `msg_size`. — M3-INV-02.
- **`tkeep` inválido**: máscara con huecos, cero o parcial sin `tlast` →
  `error`, descarte y recuperación. — M3-INV-04.
- **Gap de secuencia** (MsgSeqNum salta) → `gap_detected` sin abortar;
  canal nuevo (seq reiniciado) → reset del esperado. — M3-GAP-01.
- **`msg_size` incoherente** (menor que la cabecera SBE o desborda el
  paquete) → `error`, jamás cuelgue ni corrupción silenciosa. — M3-INV-01.
- **Entry mal formado dentro del mensaje** (grupo con numInGroup 0 o
  tamaño que excede `msg_size`) → `error`/anomalía, no truncado. — M3-INV-03.
- **Templates desconocidos** (schemaId/version fuera del subset) →
  passthrough crudo, nunca aborto. — M3-PASS-01.

**Qué se arriesga del maestro:** la **generalidad de diseño** (un pipeline
ITCH que no se porta a otro exchange = sospechoso), la **verificación sin
datos reales** (el corpus sintético desde el schema es el sustituto honesto
de DataMine) y el **line-rate** del datapath parametrizado.

## Reuso

- `rtl/parser/itch_parser.sv` — **no se toca**; `mdp3_parser.sv` comparte la
  convención AXI-Stream y de cola (QB) pero es módulo nuevo.
- `golden_model/itch/messages.py` — patrón de «fuente única de offsets»;
  el equivalente MDP3 es el schema XML (nada a mano).
- Testbenches fases 1-3: helpers de driver AXI-Stream (`_reset`, conducción
  de words, muestreo de pulsos) — **se importan**, no se copian (regla de
  partición del README de testbenches).
- `scripts/fetch_itch.py` — patrón fail-closed con md5 para
  `fetch_mdp3_schema.py`.
- Código nuevo que duplique la semántica del schema con literales (offsets,
  tags, valores de enum a mano en RTL/Python) = FAIL de la lente 6 de
  `/grade`.

## Criterios de aceptación (Definition of Done)

1. [x] **Golden MDP3**: loader del schema XML + decoder bit a bit + generator
     sintético con round-trip `decode(encode(m)) == m` para el subset y
     passthrough; tests Python espejo. El round-trip debe partir de vectores
     conocidos con valores no cero y demostrar campo a campo que se preservan
     root, composites —incluido `PRICE9.mantissa`— y grupos multi-entry; la
     igualdad de bytes tras re-encodear el propio decode no basta como oráculo.
     — Gherkin: `mdp3.feature` §M3-GEN-01, §M3-GEN-02
2. [ ] **Framing**: paquete (12 B) + mensajes (u16 size + cabecera SBE) →
     secuencia de Anexo M bit a bit vs golden; mensajes que cruzan límites
     de palabra; un burst AXI independiente por payload con `tkeep` correcto.
     — §M3-FRM-01, §M3-FRM-02
3. [x] **Régimen de entrada**: 24 mensajes literales template 47, de una
     entry y 64 B cada uno, se presentan a 1 palabra/ciclo; stalls reales
     (`tvalid && !tready`) con racha máxima <= 16. — §M3-FRM-03
4. [x] **Subset decodificado**: records de libro (46/47/52/53) bit a bit vs
     golden, incluido el precio compuesto (mantissa+exponente) y grupos
     multi-entry. — §M3-SUB-01, §M3-SUB-02
5. [x] **Passthrough**: templates no-subset → w0/w1 + cuerpo crudo bit a bit,
     sin abortar en schemaId/version desconocidos. — §M3-PASS-01
6. [x] **Gaps de secuencia**: `gap_detected` en saltos; reset al cambiar de
     canal (secuencia reiniciada). — §M3-GAP-01
7. [ ] **Robustez**: `msg_size` incoherente y grupos mal formados → `error`
     señalizado, sin cuelgue ni corrupción silenciosa; `tlast` de entrada
     truncado (incluidos 1..`DW/8-1` bytes ausentes) y máscaras `tkeep`
     inválidas manejados. — §M3-INV-01/02/03/04
8. [ ] **Regresión**: fases 1-3 verdes tras propagar `tkeep` por la entrada de
     `itch_chain`; DW=64 del mdp3_parser en regresión. — §M3-REG-01
9. [x] Lint `--Wall` limpio sobre `mdp3_parser.sv` (+ verible si se
     instala); checker XML↔localparams para IDs, offsets y blockLength del
     subset; espejos Gherkin 1:1. — §M3-SCH-01, gates B/C/F.

## Verificación

| Criterio | Cómo se prueba |
|---|---|
| 1 | `python3 -m unittest` (área del golden MDP3, espejos) + round-trip |
| 2 | cocotb `testbenches/mdp3`: corpus sintético → Anexo M bit a bit vs golden; words con mensaje partido y un burst por paquete |
| 3 | cocotb: 24 mensajes literales template 47 de 64 B; medir solo ciclos `tvalid && !tready`, racha <= 16 |
| 4 | cocotb: records de 46/47/52/53 vs golden; precio compuesto y multi-entry |
| 5 | cocotb: corpus de templates no-subset (d/f/otras X) crudo bit a bit |
| 6 | cocotb: secuencia con salto y reinicio de canal → pulsos de gap correctos |
| 7 | cocotb: `msg_size` inválido, numInGroup 0, truncados por 1..`DW/8-1` bytes y `tkeep` inválido con recuperación |
| 8 | `make sim` en `testbenches/{parser,orderbook,phase3}` con el contrato `tkeep` propagado |
| 9 | `verilator --lint-only -Wall` + checker schema v12↔RTL + `specs/gherkin-espejos.json` |

Régimen completo: skill `verify` (gates A-G). Gate E: runner de mutación
nuevo `scripts/verify/mutate_mdp3.py` (flips: template lookup off-by-one,
msg_size sin comprobar contra paquete, seq sin comparar, grupo con
numInGroup mal contado, passthrough sin bytes, precio con mantissa/
exponente intercambiados). Gate F: espejos `mdp3.feature` ↔
`verification/testbenches/mdp3`. Gate G: G0 (schema y corpus sintético en
vectores/derivados; sin datos de mercado reales jamás).

**Contratos sin gate** — invariantes que pueden romperse con suite y lint en
verde:

1. **Significado de `msg_size`** (¿incluye la cabecera SBE de 8 B o solo el
   cuerpo?): **resuelto por evidencia** — roq-cme `parser.cpp`:
   `length = message_size.length - (2 + MessageHeader::encodedLength())`
   ⇒ msg_size incluye los 10 B de prefijo. El M3-GEN-01 lo pincha con el
   round-trip semántico de vectores conocidos y el tamaño literal esperado.
2. **Alineación root a 8 B**: el RTL consume `msg_size` y no re-deriva la
   alineación (no le importa); el golden la aplica al generar (los blockLength
   de los templates de libro vienen del XML: 11/11/59/28). Si el golden la
   aplicara mal, el bit a bit con el decoder propio no lo detectaría →
   escenario M3-GEN-02 pincha el layout con tamaños esperados desde el XML.
3. **Grupos anidados / doble grupo**: el template 46 lleva DOS grupos
   decodificados (NoMDEntries MBP y NoOrderIDEntries MBOFD con dimensionType
   `groupSize8Byte`, 8 B); el resto de grupos de otros templates (var-data de
   passthrough, p. ej. instrument definitions) no se decodifican (crudo) → el
   riesgo es solo del golden, que debe respetar los dimensionTypes del XML.
4. **Multi-entry → multi-record**: la decisión de emitir un record por entry
   (no uno por mensaje) es contrato; si el book 4b esperara otra cosa, se
   cambia aquí, no en el RTL.
5. **Referencia cruzada del 46** (ReferenceID → entry MBP del mismo mensaje):
   el px/security/rpt_seq del record MBOFD del 46 se resuelven por índice
   dentro del mensaje; fuera de rango ⇒ `error` (anomalía, no corrupción).

## Loop

Stop limit: **4 iteraciones**. Cadencia sugerida: iter 1 (golden MDP3:
loader+decoder+generator, espejos Python) → iter 2 (RTL framing + Anexo M
bit a bit, line-rate) → iter 3 (subset + passthrough + gaps + robustez +
regresión) → iter 4 (mutación, gates, grade). Al agotar el límite con
criterios en FAIL, escala al owner.
