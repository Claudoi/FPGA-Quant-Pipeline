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

> Actualizado 2026-08-14 (iteración 6): QB de la cadena 128 → 64. El backlog
> estacionario de la cola del parser dominaba la latencia (entrada a 4 B/c
> contra drenaje medio ~2,7 B/c → cola fijada en QB); con QB=64 el backlog
> se reduce de ~32 a ~16 palabras. El default del parser ya era 64; el de
> `itch_chain` (que lo sobrescribe al instanciarlo) era 128 y se alineó.

| Tipo | n | min (ciclos) | max | media | media (ns) | p50 | p99 |
|---|---|---|---|---|---|---|---|
| A | 12.742 | 27 | 51 | 45,39 | 140,8 | 46 | 50 |
| D | 12.368 | 35 | 46 | 39,86 | 123,7 | 41 | 45 |
| E | 14 | 40 | 45 | 43,71 | 135,6 | 44 | 45 |
| U | 686 | 40 | 50 | 45,05 | 139,8 | 46 | 47 |
| X | 4.919 | 36 | 47 | 40,66 | 126,2 | 42 | 43 |
| **Total** | **30.729** | **27** | **51** | **42,40** | **131,5** | **42** | **47** |

Histograma completo (sparse, ciclos) y por tipo: ver el JSON.

## Lectura

- El histograma es **determinista** (SEC-LAT-01 re-ejecuta el stream dos veces
  y exige histogramas idénticos; el JSON es la evidencia de esa ejecución).
- **Iteración 6**: p99 77 → **47 ciclos** (~239 → ~146 ns) y media 69,26 →
  **42,40 ciclos** (214,9 → 131,5 ns) — **~1,63×**, con la corrección bit a
  bit intacta (CHAIN-01, 30.729 eventos, 0 gaps). El pico sigue siendo el add
  A (mayor cuerpo); D/X los más cortos.
- El valor mínimo absoluto (27 ciclos) es el primer add del día sobre un
  símbolo recién registrado (camino de tabla corto, cola vacía).
- El recorte adicional del encabezado de 32 bits (w2/w3 de ts, que el book
  descarta) y la serialización URAM son las palancas de la próxima campaña
  (ver `revision-exhaustiva-2026-08-14.md`).
- La latencia se mide en simulación en ciclos; la conversión a ns usa el reloj
  objetivo (out of scope: wire-to-wire con hardware real).