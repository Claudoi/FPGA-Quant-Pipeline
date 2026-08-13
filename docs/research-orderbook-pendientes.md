# Investigación — fase2-orderbook: pendientes del order book RTL

> Documento vivo (build fase 2, iteración 1). Qué se sabe hoy, qué se probó y
> los pendientes para cerrar la fase 2. Usar con
> `specs/fase2-orderbook/spec.md` y `verify-report.md`.

## Estado global

| Área | Estado |
|---|---|
| RTL `orderbook.sv` | lint `--Wall` 0; **13/13 tests verdes** |
| Tests | BBO-01, SEC-U, SEC-HZ-01/02, SEC-DC-01/02, SEC-AN, SEC-OV, SEC-CR, SEC-EM, MULTI-01, REPLAY-02 |
| Gate E (mutación) | 6/6 mutantes muertos (`scripts/verify/mutate_orderbook.py`) |
| **PENDIENTE 1** | REPLAY-01 (feed real multi-símbolo): requiere mapeo locate→índice |
| **PENDIENTE 2** | Profundidad de book (N niveles públicos), pipeline URAM optimizado |

## PENDIENTE 1 — mapeo locate → índice de símbolo (REPLAY-01)

El RTL actual indexa los niveles por `locate[4:0]` (0..19), suficiente para
hasta 20 símbolos si sus locate[4:0] no colisionan (verificado: `test_multi01`
con locates 393→9 y 13→13). Un día real de Nasdaq tiene **~2990 locates**
(medido en una ventana de 150K mensajes: 278 distintos), así que `[4:0]`
colisiona masivamente → el feed real no se puede replícar bit a bit con este
mapeo.

### Intento implementado y revertido (esta iteración)

Se implementó una tabla contenido-direccionable en el RTL:
- `loc_map[NSYM-1:0]` (ubicación del locate por índice), `loc_cnt`, `m_loc_idx`.
- `loc_lookup()` — función pura que devuelve el índice existente o 31 si ausente.
- En ST_W0: si `loc_lookup == 31 && loc_cnt < NSYM`, se registra `loc_map[loc_cnt]
  <= locate` y `m_loc_idx <= loc_cnt`; si no, `m_loc_idx <= loc_lookup`.

**Resultado**: regresión — rompió BBO-01/MULTI-01/CR-01 (de 12/12 a 7/13). Se
revertió al mapeo `[4:0]` (13/13 verde). 

**Hipótesis de la regresión** (a confirmar en la iteración 2):
1. **Lectura de la tabla en el mismo ciclo que la escritura**: `loc_lookup`
   lee `loc_map` que se escribe con `<=` en el mismo flanco de ST_W0 — el
   segundo mensaje del MISMO símbolo debería ver el mapa ya escrito, pero si el
   primer mensaje NO es el que registra (p. ej. un `S`/`H` que no modifica el
   book), el `m_loc_idx` del mensaje de datos inmediato posterior usa un valor
   stale del ciclo anterior.
2. El `emit_bbo`/`level_add` leen `m_loc_idx` que se asigna en ST_W0 con `<=`
   y se usa en ST_APPLY/ST_EMIT ciclos después — debería ser estable, pero
   puede haber un caso donde el registro del símbolo y su uso coinciden mal.

**Plan iteración 2**:
1. Aislar con un test mínimo: 2 mensajes del MISMO símbolo nuevo, verificar
   `m_loc_idx` en cada uno; luego 2 símbolos.
2. Factorizar el mapeo a señal combinacional `wire [4:0] cur_idx` calculada en
   ST_W0, evitando leer/escribir `loc_map` en el mismo ciclo.
3. Reescribir REPLAY-01 con el mapeo y el feed real de 1-2 símbolos (para
   comparar bit a bit contra `book.py`).

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