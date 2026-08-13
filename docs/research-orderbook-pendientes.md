# Investigación — fase2-orderbook: pendientes del order book RTL

> Documento vivo (build fase 2, iteración 1). Qué se sabe hoy, qué se probó y
> los pendientes para cerrar la fase 2. Usar con
> `specs/fase2-orderbook/spec.md` y `verify-report.md`.

## Estado global

| Área | Estado |
|---|---|
| RTL `orderbook.sv` | lint `--Wall` 0; **14/14 tests verdes** (iteración 3) |
| Tests | BBO-01, SEC-U, SEC-HZ-01/02, SEC-DC-01/02, SEC-AN, SEC-OV, SEC-CR, SEC-EM, MULTI-01, INV-U-01, REPLAY-01 (feed real), REPLAY-02 |
| Gate E (mutación) | **8/8 mutantes muertos** (`scripts/verify/mutate_orderbook.py`) |
| **CERRADO iteración 2** | Mapeo locate→índice (register-on-first-seen) |
| **CERRADO iteración 3** | **BUG-U** (replace atómico en 2 ciclos), K=19, P=32, tstate por símbolo, **REPLAY-01 bit a bit** |
| **PENDIENTE 2** | Profundidad de book (N niveles públicos), pipeline URAM optimizado (fase 3) |

## CERRADO — BUG-U: replace `U` con dos level_add en el mismo ciclo (iteración 3)

### Fix aplicado

El branch `U` de `apply_one` ya NO hace dos `level_add` en el mismo ciclo.
Ahora el delete se aplica en `ST_APPLY` (con `level_add` de `-o_qty` + `o_valid[oref] <= 0`)
y la add se aplica en el estado nuevo `ST_UADD` (ciclo siguiente), donde la
segunda `level_add` SÍ ve la eliminación (las escrituras `<=` del flanco anterior
son visibles). El routing `ST_APPLY → ST_UADD` usa la salida bloqueante
`out_uadd` de `apply_one` (visible en el mismo ciclo; un flag `<=` habría llegado
tarde). `emit_ok` se conserva entre ambos estados: el BBO del U se emite UNA vez,
con el estado final (atómico, sin ventana).

### Otros hallazgos cerrados en la misma iteración (REPLAY-01)

El feed real multi-símbolo expuso TRES divergencias más, todas corregidas:

1. **Truncado de `order_ref` a K=14 bits**: los refs del subset real van de 267
   a 372.297 (refs globales del día); con 2^14=16.384 entradas hay 4.443
   colisiones (2 refs con los mismos 14 bits bajos) → órdenes perdidas/confundidas
   (173 eventos de menos). Fix: **K=19** (2^19=524.288 ≥ max_ref del subset).
   La indexación directa exige `2^K > max_ref`, no `≥ peak_live`; se documenta el
   coste URAM (524.288 × ~66 bits ≈ 4,3 MB ≈ 120 URAM) para fase 3.
2. **Overflow de niveles con P=8**: el símbolo 6960 llega a **17 niveles ask**
   vivos (13 bid); con P=8 el RTL descartaba niveles (error silencioso de BBO).
   Fix: **P=32** (≥ máximo medido del subset; el overflow >P sigue señalizándose
   con `error`, SEC-OV).
3. **`trading_state` 4 bits global**: el golden guarda el trading state POR
   locate (8 bits, `'T'`=0x54 continuo); el RTL tenía un registro global de 4
   bits comparado contra `4'd0` → los crosses reales no se contaban. Fix:
   `tstate[NSYM-1:0]` de 8 bits por símbolo, comparado contra `8'h54`.
   Además el testbench pasaba `S`/`H` como int al golden (comparaba contra str
   `"Q"`/`"T"` → market hours y crosses NUNCA contaban, SEC-CR-01 vacuo):
   ahora se pasan como `chr()` y SEC-CR-01 pincha de verdad.

### Evidencia

- Rojo (tests añadidos/restaurados contra el RTL de la iteración 2):
  `SEC-CR-01` (cross 0 vs 1), `INV-U-01` (best bid stale 425800 vs 425700),
  `REPLAY-01` (got 30.556 vs exp 30.729).
- Verde: **14/14**, REPLAY-01 **30.729 eventos bit a bit** (anomaly 671, cross 0),
  8/8 mutantes muertos (añadidos U-DELETE-HALF y U-SKIP-ROUTE).

### Cómo reproducir

```bash
cd verification/testbenches/orderbook
export PATH="$PWD/../../../.venv/bin:$PATH"
make clean && make sim          # 14/14 (REPLAY-01 con /tmp/real_trading.pcap)
```

## CERRADO — mapeo locate → índice de símbolo (iteración 2)

El RTL indexa los niveles por `m_loc_idx` (register-on-first-seen):
- `loc_map[NSYM-1:0]` + `loc_cnt` + `m_loc_idx`.
- `loc_lookup()` — función pura que devuelve el índice existente o 31 si ausente.
- En ST_W0: si `loc_lookup == 31 && loc_cnt < NSYM`, se registra
  `loc_map[loc_cnt] <= locate`, `m_loc_idx <= loc_cnt`; si no,
  `m_loc_idx <= loc_lookup`.

La regresión de la iteración 1 NO era del mapeo (era la corrupción por
`re.sub` al limpiar displays). El mapeo reimplementado limpio pasa los 13
tests sintéticos y el feed real de 20 símbolos se procesa (el único fallo
restante es el BUG-U, independiente del mapeo).

## PENDIENTE 2 — profundidad y pipeline URAM

- La salida actual es BBO (1 nivel por lado). El maestro prevé N niveles
  públicos; se separa a una iteración de profundidad.
- El RTL procesa 1 mensaje/ciclo con lógica O(P) por nivel. La latencia de URAM
  (lectura registrada) no está modelada: el pipeline se optimiza en la
  iteración de profundidad (maestro: "diseño del pipeline alrededor de la
  latencia de URAM").

## Réplica de la regresión del mapeo (comandos)

```bash
cd verification/testbenches/orderbook
export PATH="$PWD/../../../.venv/bin:$PATH"
make clean && make sim          # 14/14 con mapeo locate→índice + U en 2 ciclos
# mutación del order book (gate E): 8/8 deben morir
python3 ../../../scripts/verify/mutate_orderbook.py
```