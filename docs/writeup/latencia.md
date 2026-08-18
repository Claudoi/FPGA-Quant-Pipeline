# Latencia wire→BBO — fase 3 (criterio 8)

> Evidencia derivada del feed real (subset de 20 símbolos, 2019-12-30),
> sin datos crudos: `verification/vectors/latency/latency_dw32.json`.

## Definición de la medición

- **Cadena**: `itch_chain` a DW=32 (parser 32 → book 32, 322,265625 MHz objetivo).
- **Wire**: handshake en `s_axis` de la word que cubre el primer byte del
  mensaje (el mensaje entra por el bus tal como llega del decap IP/UDP).
- **BBO**: handshake `bbo_tvalid`/`bbo_tready` del evento emitido por ese
  mensaje.
- **Latencia**: ciclos entre ambos handshakes, por tipo de mensaje. El evento
  j-ésimo del RTL corresponde al mensaje emisor j-ésimo del golden (garantizado
  por CHAIN-01, bit a bit).

## Conversión a ns

Reloj objetivo: **322,265625 MHz** → `1 ciclo = 3,1030 ns`.

## Resultados (subset, 31.400 mensajes → 30.729 eventos)

> Actualizado 2026-08-18: el JSON es la evidencia vigente de la re-ejecución
> de SEC-LAT-01 sobre la cadena con el fix de inferencia URAM (misma
> medición, mismo subset; ver `specs/fase3-optimizacion/verify-report.md`).
> Historia: iteración 6 (2026-08-14) — QB de la cadena 128 → 64; el backlog
> estacionario de la cola del parser dominaba la latencia (entrada a 4 B/c
> contra drenaje medio ~2,7 B/c → cola fijada en QB); con QB=64 el backlog
> se reduce de ~32 a ~16 palabras. El default del parser ya era 64; el de
> `itch_chain` (que lo sobrescribe al instanciarlo) era 128 y se alineó.

| Tipo | n | min (ciclos) | max | media | media (ns) | p50 | p99 |
|---|---|---|---|---|---|---|---|
| A | 12.742 | 32 | 74 | 45,39 | 140,8 | 46 | 50 |
| D | 12.368 | 35 | 46 | 39,86 | 123,7 | 41 | 45 |
| E | 14 | 40 | 45 | 43,71 | 135,6 | 44 | 45 |
| U | 686 | 40 | 50 | 45,05 | 139,8 | 46 | 47 |
| X | 4.919 | 36 | 47 | 40,66 | 126,2 | 42 | 43 |
| **Total** | **30.729** | **32** | **74** | **44,318** | **137,5** | **44** | **61** |

Histograma completo (sparse, ciclos) y por tipo: ver el JSON.

## Presupuesto de latencia e iter 7

- **Presupuesto original de la campaña**: media ≤ 214,9 ns (SEC-URAM-04
  original, fase3-uram). El umbral en ciclos se re-deriva por iteración:
  - iter 4: media ≤ 45 ciclos (139,6 ns);
  - **iter 7 (addendum)**: el pipeline de emisión A/B/C añade +2 ciclos al
    camino del evento → **media ≤ 48 ciclos (148,9 ns)**, todavía muy por
    debajo del presupuesto original de 214,9 ns. El umbral vive ahora en
    RTM-LAT-01 (`test_lat32.py`, target `sim-lat`); SEC-URAM-04 se enmendó
    en la spec (la campaña fase3-uram no se reabre).
- Con el pipeline A/B/C la media esperada pasa de ~44,3 a ~46,3 ciclos
  (margen ~1,7 ciclos sobre el umbral). La medida fresca debe re-ejecutarse
  en la máquina con cocotb (`make -C verification/testbenches/phase3 sim-lat`)
  y el JSON vigente se re-genera con esa pasada.

## Lectura

- El histograma es **determinista** (SEC-LAT-01 re-ejecuta el stream dos veces
  y exige histogramas idénticos; el JSON es la evidencia de esa ejecución).
- **Iteración 6**: p99 77 → **47 ciclos** (~239 → ~146 ns) y media 69,26 →
  **42,40 ciclos** (214,9 → 131,5 ns) — **~1,63×**, con la corrección bit a
  bit intacta (CHAIN-01, 30.729 eventos, 0 gaps). El pico sigue siendo el add
  A (mayor cuerpo); D/X los más cortos.
- **Re-ejecución 2026-08-18** (misma cadena, tras el fix de inferencia URAM):
  media **44,318 ciclos (137,5 ns)**, p50 44, p99 61 — la cola es más larga
  pero el cuerpo de la distribución se mantiene; el max 74 corresponde a los
  adds de arranque del día. El JSON de la evidencia es esta pasada.
- **Iter 7 (pipeline A/B/C)**: +2 ciclos en el camino del evento → media
  esperada ~46,3; umbral RTM-LAT-01 media ≤ 48 ciclos (148,9 ns), muy por
  debajo del presupuesto original de 214,9 ns.
- El valor mínimo absoluto (27 ciclos en iter 6; 32 en la pasada 2026-08-18)
  es el primer add del día sobre un símbolo recién registrado (camino de
  tabla corto, cola vacía).
- El recorte adicional del encabezado de 32 bits (w2/w3 de ts, que el book
  descarta) y la serialización URAM son las palancas de la próxima campaña
  (ver `docs/writeup/lecciones-aprendidas.md` secciones 4 y 7).
- La latencia se mide en simulación en ciclos; la conversión a ns usa el reloj
  objetivo (out of scope: wire-to-wire con hardware real).