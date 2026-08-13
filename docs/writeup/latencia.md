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

| Tipo | n | min (ciclos) | max | media | media (ns) | p50 | p99 |
|---|---|---|---|---|---|---|---|
| A | 12.742 | 27 | 81 | 72,19 | 224,0 | 72 | 80 |
| D | 12.368 | 61 | 76 | 66,62 | 206,7 | 68 | 74 |
| E | 14 | 66 | 73 | 69,79 | 216,5 | 70 | 72 |
| U | 686 | 66 | 77 | 71,83 | 222,9 | 72 | 76 |
| X | 4.919 | 62 | 77 | 67,95 | 210,8 | 68 | 75 |
| **Total** | **30.729** | **27** | **81** | **69,26** | **214,9** | **68** | **77** |

Histograma completo (sparse, ciclos) y por tipo: ver el JSON.

## Lectura

- El histograma es **determinista** (SEC-LAT-01 re-ejecuta el stream dos veces
  y exige histogramas idénticos; el JSON es la evidencia de esa ejecución).
- p99 ≈ 77 ciclos ≈ 239 ns; el pico es el add A (mayor cuerpo + escritura de
  tabla); D/X son los más cortos (borrado directo sin probing largo).
- El valor mínimo absoluto (27 ciclos) es el primer add del día sobre un
  símbolo recién registrado (camino de tabla corto).
- La latencia se mide en simulación en ciclos; la conversión a ns usa el reloj
  objetivo (out of scope: wire-to-wire con hardware real).