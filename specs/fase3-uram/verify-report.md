# verify-report — fase3-uram

> Régimen de gates de Atenea re-mapeado al flujo HDL. Sin verify-report,
> `/grade` da FAIL directo. Lo escribe `/verify` campaña a campaña.

## Iteración 1 — recorte del Anexo A de 32 bits (criterio 1, ANX-01/ANX-02)

### Meta del atacante/diseño

Cambio de contrato del Anexo A de 32 bits (edit explícito del criterio 1 de
fase 3, decidido por el owner): el layout pasa de
`w0={type,locate,len}, w1=idx, w2=ts[31:0], w3={ts[47:32],16'b0}, w4..=cuerpo`
a **`w0, w1=idx, w2..=cuerpo` — sin words de timestamp** (el book no las
consume; solo usa w1 para el sanity `m_idx`). Ganancia esperada ~2 ciclos/
mensaje + ~15 % de palabras del stream interno; la medición real dio más.

### Rojo con evidencia (TDD)

| Test | Rojo | Causa raíz |
|---|---|---|
| ANX-01 (parser) | `got(42) exp(34)` — 8 words de más en 4 mensajes | el RTL aún emitía w2/w3 de ts |
| ANX-02 (peor caso) | idem (42 vs 34) | idem |
| B32-01 (book) | `got=[] exp=[...]` — sin un solo evento BBO | `hrem=3` en ST_TS: el book comía la primera word del cuerpo como si fuera ts; con el layout recortado el desfase rompe todo |
| INV-B32-01 | `got=[(72164352,...)]` — garbage | idem (desalineación de cabecera) |

### Verde (evidencia)

```
** TESTS=2 PASS=2 FAIL=0 **   (uram sim-anx: ANX-01 corpus 75 words bit a bit +
                              feed real 31.400 msgs -> 197.452 words bit a bit; ANX-02 2 stalls <= 24)
** TESTS=5 PASS=5 FAIL=0 **   (phase3 sim)
** TESTS=8 PASS=8 FAIL=0 **   (phase3 sim-hash)
** TESTS=3 PASS=3 FAIL=0 **   (phase3 sim-depth)
** TESTS=2 PASS=2 FAIL=0 **   (phase3 sim-hard)
** TESTS=4 PASS=4 FAIL=0 **   (phase3 sim-parser)
** TESTS=2 PASS=2 FAIL=0 **   (phase3 sim-chain: CHAIN-01 bit a bit)
** TESTS=1 PASS=1 FAIL=0 **   (phase3 sim-lat: determinista, JSON regenerado)
** TESTS=14 PASS=14 FAIL=0 ** (fase 2)
** TESTS=19 PASS=19 FAIL=0 ** (fase 1)
** 32/32 OK **                (golden model)
```

Latencia re-medida con el layout recortado (`latency_dw32.json` regenerado por
SEC-LAT-01, 30.729 eventos, anomaly=671, cross=0):

| Métrica | Antes (QB=64) | Después del recorte | Δ |
|---|---|---|---|
| Media total | 42,40 ciclos | **34,835** (108,1 ns) | −18 % |
| p99 / p50 / min | 47 / 42 / 27 | **39 / 34 / 24** | −8 / −8 / −3 |
| A media | 45,39 | 37,67 | −17 % |
| D media | 39,86 | 32,41 | −19 % |
| U media | 40,66 | 37,49 | −8 % |
| X media | 40,66 | 33,20 | −18 % |

(* X era 40,66 (latencia.md pre-recorte, QB=64); el recorte elimina ~2 words/
mensaje de la cola → el drenaje acelera todos los tipos; la mejora supera la
estimación del plan.)

### Cambios

- `rtl/parser/itch_parser.sv`: ST_TS a DW=32 emite solo w1=msg_idx y pasa a
  ST_BODY; reg `hw` eliminada (era el contador de las 3 words de cabecera);
  comentario de cabecera con el layout recortado. DW=64 intacto.
- `rtl/orderbook/orderbook.sv`: `hrem` fijado a 1 (antes 3 a DW=32);
  ST_TS captura `m_idx` de la única word de cabecera a DW=32.
- `verification/testbenches/phase3/test_parser32.py`: `oracle_words32` sin las
  words de ts (layout recortado, docstring actualizado).
- `verification/testbenches/phase3/test_orderbook32.py`: `anexo_words32` sin
  las 2 words de ts (oráculo compartido por depth/hash/hard).
- `verification/testbenches/uram/` (área nueva de la campaña): `test_anx32.py`
  (espejos ANX-01/ANX-02, importan los oráculos — nunca los re-escriben) +
  Makefile con target `sim-anx`.
- `specs/fase3-optimizacion/spec.md` + gherkin P32-01: layout recortado
  (elimina la contradicción con el contrato nuevo; el campaign spec declara el
  edit explícito).

### Pendiente para iteraciones siguientes

- Criterios 2-8: memoria URAM (SEC-URAM-01), sonda serializada + prefetch
  (SEC-URAM-02), pipeline de niveles (SEC-URAM-03), latencia ≤ 45 (ya 34,8 —
  SEC-URAM-04), regresión con el RTL URAM (REG-01/CHAIN-01), synth (criterio 7).