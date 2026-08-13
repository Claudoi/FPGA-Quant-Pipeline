# Investigación — fase2-orderbook: pendientes del order book RTL

> Documento vivo (build fase 2, iteración 1). Qué se sabe hoy, qué se probó y
> los pendientes para cerrar la fase 2. Usar con
> `specs/fase2-orderbook/spec.md` y `verify-report.md`.

## Estado global

| Área | Estado |
|---|---|
| RTL `orderbook.sv` | lint `--Wall` 0; **13/13 tests verdes** (mapeo locate→índice en iteración 2) |
| Tests | BBO-01, SEC-U, SEC-HZ-01/02, SEC-DC-01/02, SEC-AN, SEC-OV, SEC-CR, SEC-EM, MULTI-01, REPLAY-02 |
| Gate E (mutación) | 6/6 mutantes muertos (`scripts/verify/mutate_orderbook.py`) |
| **CERRADO iteración 2** | Mapeo locate→índice (register-on-first-seen) — 13/13 sintéticos verde |
| **PENDIENTE 1** | **BUG-U**: replace con doble level_add en el mismo ciclo (REPLAY-01) |
| **PENDIENTE 2** | Profundidad de book (N niveles públicos), pipeline URAM optimizado |

## PENDIENTE 1 — BUG-U: replace `U` con dos level_add en el mismo ciclo

### Síntoma (iteración 2)

El feed real multi-símbolo (20 locates, 31400 mensajes) falla REPLAY-01:
`got(30261) exp(30729)` — 468 eventos de diferencia. El primer desajuste:

```
evento 769: got=(1101, (425800, 500, 426300, 1400), 0) exp=(1101, (425700, 500, 426300, 1400), 1)
mensaje: type=U loc=1101, orig=247097, new=247657, shares=500, price=425700
```

### Reproducción mínima (sintética)

```
A(1101, 247097, bid, 500, @425800)
A(1101, 246365, bid, 300, @425500)
U(1101, 247097→247657, 500, @425700)
exp: [(1101,(425800,500,0,0),1), (1101,(425800,500,0,0),0), (1101,(425700,500,0,0),1)]
got: [(1101,(425800,500,0,0),1), (1101,(425800,500,0,0),0), (1101,(425800,500,0,0),0)]
```

El `U` reemplaza la orden best-bid (425800) por una a 425700; el golden da
best bid 425700, el RTL sigue en 425800.

### Causa raíz

En `apply_one`, el branch `U` hace DOS llamadas a `level_add` en el MISMO
ciclo:
1. `level_add(o_side[oref], o_price[oref], -o_qty[oref])`  → elimina 425800
2. `level_add(o_side[oref], price, shares)`              → añade 425700

Cada `level_add` copia `lv_qty/lv_price` a variables locales (`lpr/lqt`),
aplica, y escribe de vuelta con `<=` (non-blocking). La segunda llamada lee
`lv_qty` ANTES de que la primera actualice (la escritura `<=` es visible el
ciclo siguiente), así que la segunda ve 425800 con qty 500 (no 0) y el nivel
resultante queda corrupto (425800 con qty residual, 425700 mal ordenado).

Esto es el MISMO patrón que se arregló en la iteración 1 dentro de una sola
`level_add` (variables locales), pero ahora son DOS `level_add` consecutivas
en `apply_one` que comparten el mismo flanco.

### Fix propuesto (iteración 3)

1. **Pipeline del U en 2 ciclos**: aplicar la eliminación de la orig en un
   ciclo y la adición de la nueva en el siguiente (o un `level_add` que acepte
   dos operaciones atómicas). Alternativa más simple: serializar las dos
   operaciones con un `apply_pending` flag que divida el APPLY del U en dos
   estados.
2. O: hacer `level_add` **combinacional puro** que devuelva el nuevo estado
   (no escriba `<=`), y que `apply_one` lo invoque dos veces encadenadas sobre
   la misma variable local, escribiendo `lv_*` UNA vez al final.
3. Revalidar REPLAY-01 con el feed real de 20 símbolos (31400 mensajes).

### Cómo reproducir

```bash
cd verification/testbenches/orderbook
export PATH="$PWD/../../../.venv/bin:$PATH"
# suite (REPLAY-01 omitido por BUG-U)
make clean && make sim
# para ver el bug: descomentar el cuerpo de test_replay01_feed_real_bbo
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
make clean && make sim          # 13/13 con mapeo [4:0]
# para reintentar el mapeo en iteración 2, ver la sección PENDIENTE 1
```