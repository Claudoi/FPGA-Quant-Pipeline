# Pipeline URAM — tabla de órdenes (fase 3, criterio 9)

> Mapeo de la tabla de órdenes a URAM del VU9P (xcvu9p-flga2104-2L-e, 960 URAM
> de 288 Kb), patrón de lectura registrada y auditoría de complejidad.

## Entradas de la tabla

| Campo | Ancho (bits) |
|---|---|
| `o_valid` | 1 |
| `o_ref` (order_ref, K=20) | 20 |
| `o_side` (0=bid, 1=ask) | 1 |
| `o_price` (PXW) | 32 |
| `o_qty` (QW) | 32 |
| **Total** | **86** |

`NSLOT = 2^SLOT = 65.536` entradas → **65.536 × 86 = 5.636.096 bits**.

## Presupuesto de recursos

- URAM del VU9P: 288 Kb (4096×72) por bloque → `5.636.096 / 294.912 ≈ 19,1`
  → **≈ 20 URAM** para la tabla de órdenes (el "≈20" de la spec).
- Niveles del book: `NSYM×2×P = 1.280` niveles × 64 bits = 81.920 bits →
  **1 URAM** (288 Kb) con holgura (≈28 %).
- Total ≈ **21 URAM de 960** (≈2 % del VU9P) + FF/LUT para el FSM y la
  lógica de probing. La tabla cabe holgada; el cuello es el datapath de
  comparación de refs, no la memoria.

## Patrón de lectura registrada (target de síntesis)

La URAM se infiere SOLO con lecturas registradas (dirección registrada →
dato en el ciclo siguiente). El modelo de simulación actual resuelve el
lookup en combinacional (PROBE=8 lecturas paralelas en el mismo ciclo); la
adaptación a URAM documentada es:

1. **Un slot por ciclo**: el probe recorre el camino `h..h+PROBE-1`
   serializado a 1 lectura/ciclo (la URAM tiene 1 puerto de lectura).
2. **Prefetch durante ST_BODY**: la `order_ref` viaja en las primeras words
   del cuerpo; el `hash(ref)` se conoce antes de ST_APPLY, así que el primer
   read se emite durante la recepción del cuerpo y los PROBE−1 siguientes
   encadenan 1 por ciclo → el lookup acaba **antes o al entrar en ST_APPLY**
   (no añade latencia al peor caso de body ≥ 4 words; caso mínimo de 1 word
   de cuerpo: el primer read se emite en ST_APPLY y el resultado llega 1
   ciclo después, absorbible en ST_UADD/ST_EMIT).
3. **Comparación fuera de la URAM**: `o_ref == r` se compara en LUT tras la
   lectura registrada; el datapath de comparación (20 bits × 8 slots) es el
   coste LUT real del diseño (~miles de LUT, no crítico en VU9P).

Auditoría (guardarraíl del contrato sin gate nº 4): la simulación no puede
distinguir el patrón registrado del combinacional; la inferencia URAM la
confirma el synth del owner (criterio 10) sobre este diseño.

## Complejidad del mejor precio (sin O(P·P))

- `emit_bbo`: escaneo **O(P)** por lado (P=32 slots, primer slot con qty≠0).
- `level_add` (iteración 6): reordenamiento **O(P)** garantizado — en borrados
  compacta el hueco a la cola en una pasada; en inserts, burbuja de inserción
  de una pasada derecha→izquierda (comparación `ask ? lpr[slot] < lpr[slot-1]
  : lpr[slot] > lpr[slot-1]`, parada al llegar a posición); un cambio de
  cantidad no reordena (invariante: la lista ya está ordenada y a lo sumo UN
  elemento queda fuera de lugar). El precio stale de un nivel vaciado es
  estructuralmente imposible: la compactación lo barre en el mismo ciclo
  (antes de la iteración 6 este punto se afirmaba para una burbuja P×P — el
  refactor hace verdadera la afirmación O(P) de la spec).
- `lookup_ref`/`first_empty`: **O(PROBE=8)**.
- Top-N: **O(ND=5)** de empaquetado.
- No existe ninguna ruta con dos bucles anidados sobre P (ni P² ni P·ND²).

## Ciclo de latencia esperado

El lookup serializado no cambia el histograma de latencia wire→BBO del
criterio 8 (el prefetch lo oculta en la recepción del cuerpo); la primera
medición con URAM real la hará el synth/impl del owner.