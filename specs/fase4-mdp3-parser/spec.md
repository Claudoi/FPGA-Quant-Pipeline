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
- **Fetch del schema**: `scripts/fetch_mdp3_schema.py` (ftp CME, fail closed
  con md5) → `data/mdp3/` (gitignored, regla G0: los schemas son spec, no
  datos de mercado, pero se mantienen fuera del repo igualmente).
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

## Constraints

- **Familia/part objetivo:** UltraScale+ (misma familia que fases 1-3);
  frecuencia 322,265625 MHz (DW=32) y 156,25 MHz (DW=64) — mismo régimen.
- **Line-rate:** el datapath acepta **1 palabra/ciclo en el peor caso**
  (mensajes mínimos back-to-back) sin backpressure sostenida — igual régimen
  que fase 1 (el framing por `msg_size` hace el peor caso dependiente del
  tamaño mínimo de mensaje del subset, del schema).
- **Schema = fuente única:** los offsets, blockLength, tipos compuestos y
  valores de enumeraciones del subset se derivan del schema XML
  (`templates_FixBinary.xml`, ftp.cmegroup.com) en el golden. **Ningún
  literal de offset/tag a mano en RTL ni en testbench** (regla de
  `messages.py` de las fases 0-3; violación = FAIL de la lente 6).
- **SBE:** big-endian; cabecera de mensaje 8 B; grupos con dimensión
  (numInGroup u8, blockLength u16 del grupo); root padded a múltiplo de 8
  para los mensajes comunes (regla de alineación del schema; los offsets del
  XML ya la reflejan — el RTL consume `msg_size` sin re-derivar alineación).
- **Determinismo:** mismo stream → misma secuencia de Anexo M, bit a bit;
  sin pérdida ni doble cuenta, con y sin backpressure de salida.
- **Framing confirmado:** paquete = MsgSeqNum(u32) + SendingTime(u64, ns
  desde epoch) = 12 B; cada mensaje = MessageSize(u16) + cabecera SBE (8 B) +
  cuerpo (blockLength + grupos + var-data). Varios mensajes por paquete.

## Superficie y amenazas

**Puertos de `mdp3_parser`** (convención AXI-Stream de fase 1):

| Señal | Ancho | Descripción |
|---|---|---|
| `clk`, `rst_n` | 1 | reloj del datapath |
| `s_axis_tdata/tvalid/tready/tlast` | DW/1/1/1 | payload UDP decapado (entrada) |
| `m_axis_tdata/tvalid/tready/tlast` | DW/1/1/1 | Anexo M (salida) |
| `gap_detected` | 1 | pulso: MsgSeqNum != exp_seq (por canal) |
| `error` | 1 | pulso: mensaje/paquete incoherente (msg_size < 10, desborde de paquete) |

**Anexo M** (registro normalizado por mensaje; un record por ENTRY para los
templates de libro; layout MSB-first por palabra, DW=32):

| Word | Contenido (subset decodificado) |
|---|---|
| w0 | `{template_id[15:0], msg_size[15:0]}` |
| w1 | `{schema_id[15:0], version[15:0]}` |
| w2, w3 | `transact_time[63:0]` (u64 ns) |
| w4 | `{match_event_indicator[7:0], 24'b0}` |
| w5 | `security_id[31:0]` |
| w6 | `rpt_seq[31:0]` |
| w7 | `{md_update_action[7:0], md_entry_type[7:0], 16'b0}` |
| w8, w9 | `md_entry_px.mantissa[63:0]` (i64) |
| w10 | `{md_entry_px.exponent[7:0], 24'b0}` (i8) |
| w11 | `md_entry_size[31:0]` (i32) |
| w12 | `{num_orders[15:0], md_price_level[15:0]}` |

Passthrough (resto de templates): `w0, w1` + cuerpo crudo byte a byte
(relleno 0 al final), sin decodificar. El burst termina con `tlast`
(convención fase 1); campos del subset ausentes en un template concreto
(snapshot vs book) → 0.

**Subset decodificado** (por nombre y tag FIX del schema; los IDs numéricos
se derivan del schema, esperados: 27 = MDMarketDataSnapshotRefresh, 30 =
MDIncrementalRefreshBook, 32 = MDIncrementalRefreshOrderBook — todos con el
grupo NoMDEntries tag 268):

- `X` (Market Data Incremental Refresh) con los templates de libro: campos
  del mensaje (TransactTime 60, MatchEventIndicator 5799) + por entry del
  grupo 268: MDEntryPx (270, PRICE mantissa+exponente), MDEntrySize (271),
  SecurityID (48), RptSeq (83), NumberOfOrders (346), MDPriceLevel (1023),
  MDUpdateAction (279), MDEntryType (269).
- `W` (MDMarketDataSnapshotRefresh, tag 35-MsgType=W): mismos campos de
  entry (para 4b: recovery por snapshot).
- El resto (d/f/otras X): passthrough.

**Casos de abuso del dominio** (cada uno con escenario `SEC-`/`INV-`):

- **Mensaje mínimo back-to-back** (paquete lleno de mensajes mínimos) →
  peor caso line-rate. — M3-FRM-03.
- **Mensaje que cruza límites de palabra y de paquete** (payload UDP
  termina en medio de un mensaje SBE) → alineación y reanudación correctas,
  sin pérdida. — M3-FRM-02, M3-INV-02.
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

1. [ ] **Golden MDP3**: loader del schema XML + decoder bit a bit + generator
     sintético con round-trip `decode(encode(m)) == m` para el subset y
     passthrough; tests Python espejo.
     — Gherkin: `mdp3.feature` §M3-GEN-01, §M3-GEN-02
2. [ ] **Framing**: paquete (12 B) + mensajes (u16 size + cabecera SBE) →
     secuencia de Anexo M bit a bit vs golden; mensajes que cruzan límites
     de palabra. — §M3-FRM-01, §M3-FRM-02
3. [ ] **Line-rate**: mensajes mínimos back-to-back aceptados a
     1 palabra/ciclo sin backpressure sostenida. — §M3-FRM-03
4. [ ] **Subset decodificado**: records de libro (27/30/32) bit a bit vs
     golden, incluido el precio compuesto (mantissa+exponente) y grupos
     multi-entry. — §M3-SUB-01, §M3-SUB-02
5. [ ] **Passthrough**: templates no-subset → w0/w1 + cuerpo crudo bit a bit,
     sin abortar en schemaId/version desconocidos. — §M3-PASS-01
6. [ ] **Gaps de secuencia**: `gap_detected` en saltos; reset al cambiar de
     canal (secuencia reiniciada). — §M3-GAP-01
7. [ ] **Robustez**: `msg_size` incoherente y grupos mal formados → `error`
     señalizado, sin cuelgue ni corrupción silenciosa; `tlast` de entrada
     truncado (paquete cortado) manejado. — §M3-INV-01/02/03
8. [ ] **Regresión**: fases 1-3 verdes sin tocar (el RTL nuevo no se conecta
     a nada existente); DW=64 del mdp3_parser en regresión. — §M3-REG-01
9. [ ] Lint `--Wall` limpio sobre `mdp3_parser.sv` (+ verible si se
     instala); espejos Gherkin 1:1. — Gates B/C/F.

## Verificación

| Criterio | Cómo se prueba |
|---|---|
| 1 | `python3 -m unittest` (área del golden MDP3, espejos) + round-trip |
| 2 | cocotb `testbenches/mdp3`: corpus sintético → Anexo M bit a bit vs golden; words con mensaje partido |
| 3 | cocotb: paquete de mensajes mínimos back-to-back; medir palabra/ciclo sin `tready=0` sostenido |
| 4 | cocotb: records de 27/30/32 vs golden; precio compuesto y multi-entry |
| 5 | cocotb: corpus de templates no-subset (d/f/otras X) crudo bit a bit |
| 6 | cocotb: secuencia con salto y reinicio de canal → pulsos de gap correctos |
| 7 | cocotb: `msg_size` inválido (0, 1..9, > paquete), numInGroup 0, paquete truncado por `tlast` |
| 8 | `make sim` en `testbenches/{parser,orderbook,phase3}` sin cambios |
| 9 | `verilator --lint-only -Wall` + `specs/gherkin-espejos.json` |

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
   cuerpo?). Guardarraíl: el golden y el RTL derivan ambos del MISMO corpus
   generado (round-trip M3-GEN-01); el acuerdo se verifica contra el schema
   y ejemplos de paquete al cargar (check del loader: tamaño esperado vs
   blockLength+grupos+padding del XML).
2. **Alineación root a 8 B**: el RTL consume `msg_size` y no re-deriva la
   alineación (no le importa); el golden la aplica al generar. Si el golden
   la aplicara mal, el bit a bit con el decoder propio no lo detectaría →
   escenario M3-GEN-02 pincha el layout con tamaños esperados desde el XML.
3. **Grupos anidados** (var-data dentro de grupos, p. ej. en passthrough):
   el RTL no los decodifica (crudo) → el riesgo es solo del golden.
4. **Multi-entry → multi-record**: la decisión de emitir un record por
   entry (no uno por mensaje) es contrato; si el book 4b esperara otra
   cosa, se cambia aquí, no en el RTL.

## Loop

Stop limit: **4 iteraciones**. Cadencia sugerida: iter 1 (golden MDP3:
loader+decoder+generator, espejos Python) → iter 2 (RTL framing + Anexo M
bit a bit, line-rate) → iter 3 (subset + passthrough + gaps + robustez +
regresión) → iter 4 (mutación, gates, grade). Al agotar el límite con
criterios en FAIL, escala al owner.