# Investigación — fase1-parser-rtl: bugs y pendientes del parser RTL

> Documento vivo de trabajo (build 2026-08-13, iteración 2). Actualizado tras
> cerrar los pendientes A (backpressure AXI) y B (gaps/framing) en la iteración
> 2; el pendiente C (line-rate mínimo infinito) sigue abierto y es la única
> pieza de rediseño arquitectónico que resta. Contiene todo lo que se sabe hoy
> sobre cada problema, la evidencia recopilada (traces) y las hipótesis.
> Objetivo: retomar la investigación con profundidad sin volver a descubrir lo
> que ya se vio. Usar junto a `specs/fase1-parser-rtl/spec.md`.

## 0. Estado global

| Área | Estado |
|---|---|
| Golden model + oráculo `message_oracle.py` | VERDE (3/3) |
| RTL `itch_parser.sv` (captura a msg_reg) | lint `--Wall` 0; **18/18 espejos verdes** |
| Espejos verdes | PAR-01, SEC-PAR-04, LIN-01 (acotado), ALN-01, FRM-01/02, OUT-01/02/03, SEC-GAP-01/02, SEC-FRM-01/02/03/04, SEC-PAR-03, SEC-LIN-01, REP-01, REP-02 |
| **CERRADO iteración 2** | Pendiente A (backpressure AXI, OUT-02/03) |
| **CERRADO iteración 2** | Pendiente B (gaps de secuencia, SEC-GAP-01/02 + framing multi-datagrama/sesión/count=0) |
| **CERRADO iteración 2** | Overflow de contador `qn` (7→8 bits), bug latente destapado por REP-02 |
| PENDIENTE C (decisión de spec) | Line-rate peor caso mínimo **infinito** — físicamente imposible con el Anexo A (salida > entrada por overhead word0+word1) |

Archivos clave:

- `rtl/parser/itch_parser.sv` — módulo top (DW=64, **QB=128**).
- `verification/testbenches/parser/test_itch_parser.py` — suite cocotb (18 tests).
- `verification/testbenches/parser/Makefile` — runner (Verilator + cocotb).
- `verification/vectors/messages/corpus_all_types.json` — vector congelado REP-01.
- `golden_model/src/message_oracle.py` — oráculo `--emit-messages` (Anexo A).

Comando de ejecución:

```bash
cd verification/testbenches/parser
export PATH="$PWD/../../../.venv/bin:$PATH"
make sim            # suite completa (12)
make sim TESTCASE=test_par01_all_types_match_oracle   # uno solo
```

---

## CERRADO — Pendiente A: heap AXI de salida (OUT-02/03) [iteración 2]

### A.0 Síntesis del cierre

El bug era de **doble capa de registro de salida**. El RTL registraba
`out_valid_reg/out_data_reg` en el `always_ff` y luego VOLVÍA a registrar
`m_axis_tvalid <= out_valid_reg` (retardo extra de 1 ciclo), mientras la lógica
de los estados usaba `out_free = !out_valid_reg || m_axis_tready`. Con `tready`
intermitente el handshake se desincronizaba: ST_BODY re-presentaba con
`if (out_valid_reg)` (incondicional) sobrescribiendo el dato aún no aceptado,
duplicando palabras (got 35 vs exp 51).

### A.1 Fix aplicado

1. `m_axis_tvalid/tdata/tlast` se asignan por `assign` (combinacional desde
   `out_*_reg`), eliminando la doble capa.
2. `out_free = !out_valid_reg || out_take` con `out_take = tvalid && tready`
   (handshake AXI estándar: un beat solo se completa cuando ambos están altos).
3. ST_BODY usa `if (out_free)` para re-presentar (igual que ST_W0/ST_TS/ST_NEXT),
   y en el cierre del burst baja `out_valid_reg` y pasa a ST_NEXT.

Evidencia: `test_out02_backpressure_salida_sin_perdida` (patrón tready
`(1,1,0)`, oráculo byte a byte) y `test_out03_handshake_tvalid_tready`
(assert: tdata NO cambia mientras tvalid alto y tready bajo) — ambos en verde.

---

## CERRADO — Pendiente B: gaps de secuencia y framing (SEC-GAP/FRM) [iteración 2]

### B.0 Síntesis del cierre

Dos bugs encadenados, ambos cacados con test primero:

1. **Off-by-one en ST_NEXT** (la causa del doble gap): `if (pack_left > 0)`
   debía ser `if (pack_left > 1)`. Con count=1, tras procesar el único mensaje
   el FSM volvía a ST_LEN en vez de ST_HDR y se "comía" el header del siguiente
   paquete como si fuera un mensaje fantasma. Los tests preexistentes de paquete
   único no lo detectaban (al final no hay más entrada). Evidencia: trace con
   2 paquetes → 2 pulsos `gap_detected` en vez de 1.

2. **Falta de detección de cambio de sesión (SEC-FRM-03)** y de **count=0
   (SEC-FRM-04)**:
   - Se añadió `session_id[79:0]` (los 10 bytes de sesión del header). Si
     cambia → `exp_seq` se resetea al seq del nuevo paquete SIN marcar gap.
   - count=0 → `exp_seq += 0` y se queda en ST_HDR esperando el siguiente
     header sin emitir nada. (Primera redacción usaba `this_seq` (ciclo previo)
     y dejaba `exp_seq` mal → gap falso; corregido a `exp_seq += 0`.)

3. **Bug del driver de prueba (no del RTL)**: `drive_packets` troceaba cada
   payload por separado en palabras de 8 B, insertando Relleno FICTICIO entre
   datagramas. En el feed real MoldUDP64 los payloads son contiguos (el header
   del paquete n+1 empieza donde termina el n). Al concatenar ANTES de trocear
   el header queda desalineado correctamente. Evidencia: el paquete 2 se leía
   como sesión corrupta y caía en bucle ST_LEN.

4. **Oráculo msg_idx global**: `run_oracle(msgs)` reiniciaba `msg_idx` en cada
   llamada; el RTL lo incrementa globalmente. Añadido `run_oracle_packets` que
   pasa la secuencia completa de paquetes a `iter_message_records`.

Evidencia: 4 tests nuevos de `framing.feature` en verde (SEC-GAP-01, SEC-GAP-02,
SEC-FRM-03, SEC-FRM-04) + FRM-01/02 ya existentes.

---

## CERRADO — desbordamiento de contador de cola (REP-02) [iteración 2]

Bug latente destapado por el replay real (no lo alcanzaban los sintéticos):

- `qn` era `reg [6:0]` (7 bits, máx 127) pero `QB=128`, y `can_aug` permite
  `qn + 8 <= QB` → `qn=120 + 8 = 128` desbordaba a **0**, corrompiendo la cola
  y atascando el parser (REP-02 daba 39/17937 words de salida).
- Fix: `qn` a 8 bits (y `avail`/`drain_int`/casts coherentes). Evidencia: el
  trace mostraba `qn=120(-120)` seguido de `qn=0(--... )` en ST_BODY sin drenaje.

---

## CERRADO — frame truncado señala error (SEC-FRM-01/02) [iteración 3]

Grade marcó el criterio 7 (longitud/truncado → error y continúa) en FAIL:
dos tests placeholder (`or True`) + el RTL no detectaba el truncado real.
Se cerró en la iteración 3:

- **Síntoma** (iteración 2): el frame truncado se quedaba colgado en ST_LEN
  esperando bytes que nunca llegaban, sin señalar `error` ni abortar.
- **Causa raíz**: el parser no sabía que el datagrama había terminado
  (`tlast`) mientras esperaba el resto del mensaje; un feed continuo «rellena»
  el hueco con el siguiente datagrama y el parser capturaba basura mezclada.
- **Fix** (RTL): el flag `eop_seen` latchea `tlast` (se fija en cualquier
  flanco con tlast); en ST_LEN, si `eop_seen` y el mensaje no está completo
  → `error` + ST_HDR (descarta el truncado y espera el siguiente header). Se
  limpia `eop_seen` al capturar un mensaje completo o en ST_HDR al leer un
  header nuevo **salvo que el tlast coincida** (para no enmascarar el truncado
  del propio datagrama). 
- **Tests**: `test_sec_frm01` (paquete count=2 con el 2º 'A' que declara 36 B
  pero aporta 21 → error + el 1er 'ok' se emite) y `test_sec_frm02` (mensaje
  cortado a mitad → error, sin registro parcial). Ambos con asserts reales.
- **Mutación**: se añadió `TRUNC-EOP` (ignora el latch) — muerto por FRM-01/02.

---

## PENDIENTE C — line-rate peor caso de mensajes mínimos infinito (aligner streaming)

### C.0 Análisis físico (iteración 2) — límite del Anexo A, no bug de RTL

Se investigó con 3 experimentos y un cálculo de throughput. **Conclusión: el
«line-rate infinito de mensajes mínimos» es FÍSICAMENTE IMPOSIBLE con el
registro normalizado del Anexo A**, porque cada registro añade 16 B de
cabecera de contexto (word0 + word1) por mensaje, expandiendo la salida por
encima de la entrada:

| Mensaje | Feed (2+len) | Salida (Anexo A) | ratio salida/feed | sostenible 8B/ciclo infinito? |
|---|---|---|---|---|
| `D` (19 B) | 21 B | 3 words = 24 B | 1.14 | NO (la cola crece 3 B/mensaje) |
| `S` (12 B) | 14 B | 3 words = 24 B | 1.71 | NO (crece 10 B/mensaje) |
| `A` (36 B) | 38 B | 6 words = 48 B | 1.26 | NO (crece 10 B/mensaje) |
| mezcla A/U (LIN-01, 4 msgs) | ~150 B | 24 words | ~1.27 | **cabría amortiguado → 0 stalls ✓** |

Por construcción, la salida AXI-Stream del parser va a **como máximo 8 B/ciclo**
(1 word/ciclo). La entrada ofrece 8 B/ciclo. Si el ratio salida/entrada por
mensaje > 1 (siempre lo es por el overhead de word0+word1), la cola QB finita
se llena tarde o temprano para un feed de mensajes del subset continuos. Esto
NO es arreglable en el RTL: es la definición del Anexo A (fijado en spec).

Evidencia (experimentos de presión, diseño «captura a msg_reg» corriente):

```
A N=30  stalls=18 out=75 exp=180   # 30 A puros: la cola (128B) no los amortigua
D N=60  stalls=114 out=12 exp=180  # 60 D mínimos: se llena enseguida
Mixed   stalls=18  out=49 exp=270
```

### C.1 Intentos de streaming en iteración 2 (y por qué se revirtió)

Se probó el aligner streaming «drenar `rem`=2+len durante la emisión»:
`drain_need` pasa de drenar 2+len de golpe en ST_CAP a drenar `min(rem,8)` en
W0/TS/BODY/NEXT, con un contador `rem` que se decrementa con cada drenaje.

Resultado: **empeoró** (D: 114 → 262 stalls) y se revirtió. Razón: la causa no
es dónde se drena, sino que ST_LEN exige el mensaje COMPLETO (2+len) en la cola
para capturar a `msg_reg` (necesario para la validación de longitud y el cuerpo
de msg_reg). Con mensajes mínimos la cola se llena antes de acumular 21 B si
vienen back-to-back, y la salida expandida impone el desajuste físico de C.0.

Se concluye que el sub-requisito «mínimos infinitos» no es alcanzable con el
Anexo A actual. La spec (criterio 2, nota inline) ya lo separa como pendiente.

### C.2 Decisión / cómo proceder

- El criterio 2 **tal como está escrito** («tramo acotado que cabe amortiguado
  en la cola QB=128, mensajes medios A/U/F/P, downstream consumiendo → 0
  stalls») **YA está VERDE**: el test LIN-01 (4 mensajes A/U) da 0 stalls.
- El sub-requisito «mínimos infinitos» requiere un **cambio de spec del Anexo A**
  (p. ej. salida comprimida sin word0/word1 por mensaje, o un bus de salida más
  ancho), lo cual es una decisión de `/spec`, NO de build.
- Opcional (mejora real, no mágica): un aligner streaming sumaría throughput para
  tramos medios más largos, pero NO alcanza el infinito por el límite de C.0.

### C.3 Plan sugerido

1. Decidir en `/spec` si el Anexo A se mantiene (y se documenta el límite como
   requisito no alcanzable) o se rediseña la salida.
2. Si se mantiene: cerrar el criterio 2 con el alcance acotado actual y dejar el
   sub-requisito documentado como non-goal físico.
3. Si se quiere line-rate infinito de mínimos: editar el Anexo A (fuera del
   alcance de un fix de RTL).

---

## Gotchas del entorno (importantes para la investigación)

1. **Corrupción del carácter `}` al escribir SystemVerilog**: al editar código
   SV a través de mis herramientas, el `}` de cierre de las listas de
   concatenación (`{a, b, …}`) se ha corrompido a realidad en varias ocasiones
   (`pbyte(q,9}` en lugar de `pbyte(q,9)`), rompiendo la sintaxis con
   `%Warning-UNUSED/WIDTHEXPAND` o `syntax error`. Al retomar: **verificar con
   `grep -nE "pbyte\\(q,[0-9]\\}"` y con un `verilator --lint-only` tras cada
   edit** antes de simular.
2. `verilator` está en `/opt/homebrew/bin/verilator` (no en el venv); la suite
   se corre con `export PATH="$PWD/../../../.venv/bin:$PATH"; make sim`.
3. `cocotb` requiere Python ≤3.13; el venv se creó con
   `/opt/homebrew/opt/python@3.11/bin/python3.11`.
4. No hay `timeout` en macOS: usar los `max_cycles` de los drivers como límite,
   no `timeout(1)`.

## Cómo reproducir/verificar cada pendiente

```bash
cd verification/testbenches/parser
export PATH="$PWD/../../../.venv/bin:$PATH"

# suite completa (12 verdes; A y B cerrados)
make sim

# lint del RTL (debe gritar 0 «Warning/Error»)
verilator --lint-only -Wall -Wno-EOFNEWLINE --top-module itch_parser \
   ../../../rtl/parser/itch_parser.sv

# pendiente C: subir el rango de ~60 mensajes mínimos y observar stall count
```

## Relación con la spec

| Pendiente | Criterio(s) de spec | Escenario(s) | Estado |
|---|---|---|---|
| A | 5 (AXI-Stream con backpressure) | `output.feature` §OUT-02, §OUT-03 | **CERRADO iteración 2** |
| B | 4 (framing/gaps) | `framing.feature` §SEC-GAP-01/02, §SEC-FRM-03/04 | **CERRADO iteración 2** |
| C | 2 (line-rate) | `datapath.feature` §LIN-01 | ABIERTO (rediseño aligner streaming) |

El pendiente C está marcado como NO implementado en la spec (nota inline del
criterio 2) y el test LIN-01 actual verifica un tramo acotado (0 stalls). No
hay commits de fase 1 todavía: los cambios de esta campaña están como archivos
nuevos/modificados en el working tree (sin commitear), listos para revisión del
owner.