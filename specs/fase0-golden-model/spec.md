# fase0-golden-model (fase 0 del maestro)

## Goal

Construir la fuente única de verdad del proyecto: un parser Nasdaq TotalView-ITCH
5.0 + order book en **Python stdlib pura** que lee los BinaryFILE de
`emi.nasdaq.com`, mantiene el libro de TODO el mercado y emite los **vectores de
referencia** (BBO mensaje a mensaje, para un subset de símbolos) contra los que se
verificará el RTL en las fases 1-2. Incluye el tooling de datos:
`fetch_itch.py` (descarga + md5) y `binaryfile_to_pcap.py` (BinaryFILE → pcap
MoldUDP64/UDP/IP/Ethernet para el testbench). Sin esta campaña no existe «contra
qué verificar»; es el cimiento del ciclo entero.

## Scope

**In scope:**

- `golden_model/itch/messages.py` — tabla canónica de layouts ITCH 5.0 (fuente
  única: tipos, longitudes, campos; nada de literales de protocolo fuera de aquí).
- `golden_model/itch/parser.py` — iterador BinaryFILE → mensajes tipados.
  - Todos los tipos ITCH 5.0 **validados** (longitud exacta por tipo).
  - Cabecera común (tipo, Stock Locate, tracking, timestamp) decodificada en todos.
  - Campos completos solo en: `A, F, E, C, X, D, U` (libro), `R` (Stock
    Directory), `S` (System Event), `H` (Stock Trading Action — necesaria para
    condicionar la invariante bid<ask al estado de trading continuo).
  - Resto de tipos: contabilizados por tipo. Tipo desconocido o longitud
    incorrecta = **error duro** (excepción, no warning).
- `golden_model/src/book.py` — order book multi-símbolo: tabla de órdenes por
  order reference, niveles de precio agregados, BBO por símbolo. Semántica:
  - `U` (Replace) es **atómico**: delete + add producen UN solo estado resultante.
  - Lado vacío del BBO se representa `precio=0, qty=0`.
  - Operación sobre order reference desconocida (ventanas parciales): se cuenta
    como anomalía y se salta, no aborta.
- `golden_model/src/vectors.py` — escritor del formato binario canónico (Anexo A)
  + volcado a texto bajo demanda (`--text`).
- `golden_model/src/stats.py` — estadísticas del día: mensajes por tipo; por
  símbolo: mensajes, pico de órdenes vivas, pico de niveles (dimensionado URAM).
- `golden_model/scripts/run_golden.py` — CLI: BinaryFILE → vectores (subset) +
  stats + invariantes activas.
- `golden_model/scripts/select_subset.py` — ranking de símbolos por actividad;
  escribe `verification/vectors/subset_symbols.json` (commiteado, es config).
- `scripts/fetch_itch.py` — descarga de `emi.nasdaq.com/ITCH/` + verificación md5.
- `scripts/binaryfile_to_pcap.py` — BinaryFILE → pcap real (abrible en
  Wireshark/tcpdump): empaquetado hasta ~1400 B de payload UDP (configurable,
  `--msgs-per-packet 1` para tests dirigidos), sequence numbers sintéticos
  monotónicos desde 1, MAC/IP-multicast/puerto sintéticos fijos configurables.
- `golden_model/tests/` — tests espejo (stdlib `unittest`; ver regla de nombres
  en Verificación).
- Vectores pequeños **sintéticos** commiteados en `verification/vectors/`.

**Out of scope (non-goals):**

- RTL, cocotb, MAC 10G: fases 1+.
- numpy/pandas en el pipeline de generación (stdlib pura; numpy solo para
  análisis ad-hoc fuera del pipeline).
- Campos completos de `P, Q, B, I, N, M, T, O, Y, L, V, W, K, J` (se cuentan).
- Recovery/GLIMPSE/snapshot: los ficheros de muestra son días completos.
- Métricas de latencia (fase 2), histogramas por tipo (fase 2+).
- CI automatizado del run de día completo (se decide al tener cifras de runtime).
- Datos crudos o vectores grandes commiteados (van a `data/itch_sample/`,
  gitignored; solo vectores pequeños sintéticos en `verification/vectors/`).

**Radio medido:** no aplica — campaña inicial sobre árbol vacío
(`golden_model/{itch,src,scripts,tests}/` y `scripts/` no contienen fuentes;
verificado con `find` el 2026-08-12). No se renombra ni mueve nada existente.

## Constraints

- **Python stdlib pura** en `golden_model/` y `scripts/` (struct precompilado,
  memoryview, gzip, unittest). Dependencia nueva = edit explícito de esta spec.
  Decisión registrada: tests con `unittest` (stdlib), NO pytest.
- **Rendimiento:** día completo principal (ver Verificación) en **≤ 2 h** en la
  máquina del owner, medido con `time` sobre `run_golden.py`. Si no llega, se
  optimiza el hot loop antes de admitir dependencias.
- Universo: libro de **todo el mercado**; vectores solo para el subset de
  símbolos de `subset_symbols.json` (regla de selección: top 20 por **pico de
  órdenes vivas** entre los símbolos de alta actividad del día principal, N
  configurable; la elección final la confirma el owner con la tabla de stats).
- Determinismo: mismo BinaryFILE de entrada → mismos vectores bit a bit.
- Endianness: ITCH es big-endian en el cable; el fichero de vectores binario es
  little-endian nativo (Anexo A). No mezclar.

## Superficie y amenazas

- **Entradas nuevas:** BinaryFILE (`length u16be + payload`), fichero
  `.md5sum` de Nasdaq, CLI de los tres scripts (rutas, `--subset`,
  `--msgs-per-packet`, `--text`, `--out`).
- **Salidas nuevas:** vectores binarios `*.vec.bin` (layout Anexo A), volcado
  texto `*.vec.txt`, `subset_symbols.json`, stats CSV, pcap `*.pcap`.
- **Casos de abuso del dominio** (cada uno con su escenario `SEC-` en Gherkin):
  tipo desconocido (SEC-01), longitud incorrecta (SEC-02), mensaje truncado
  (SEC-03), operación sobre ref desconocida (SEC-04), libro cruzado en subasta
  (SEC-05), mensaje mayor que el payload UDP máximo (SEC-06), md5 incorrecto
  (SEC-07), libro bloqueado en trading continuo en datos reales (SEC-08),
  endpoint md5 caído (DAT-03).
- **Qué se arriesga del maestro:** si el golden model miente, TODO el ciclo
  verifica contra una referencia falsa (el 50 % del valor del proyecto es la
  corrección bit a bit). Los vectores binarios son además el contrato que
  consumirá cocotb: un layout ambiguo aquí es un bug en fase 1.

## Reuso

- No existe código previo que extender (campaña inicial). `Grep`/`find`
  confirman `golden_model/`, `scripts/` vacíos de fuentes.
- Se usa SOLO stdlib. Dependencias pactadas: **ninguna**. (`pytest` queda
  descartado a favor de `unittest`; `numpy` fuera del pipeline de generación.)

## Criterios de aceptación (Definition of Done)

1. [ ] El parser itera el día principal completo sin errores: todos los mensajes
   validados por longitud, cabecera común decodificada, conteo por tipo emitido;
   tipo desconocido / longitud incorrecta / truncado = error duro.
   — Gherkin: `parser.feature` §PAR-01, §PAR-02, §PAR-03, §SEC-01, §SEC-02, §SEC-03
2. [ ] El book produce el BBO correcto en los casos known-answer (add, execute
   parcial/total, cancel, delete, replace atómico, libro vacío), con expected
   escrito a mano.
   — Gherkin: `book.feature` §LIB-01…§LIB-06
3. [ ] Invariantes activas en todo run real, chequeadas por mensaje: qty > 0 en
   órdenes vivas y niveles; order references únicas; niveles consistentes con
   órdenes (chequeo profundo periódico + cierre). Violación = abort con mensaje
   que identifica el índice de mensaje. **Excepción (corrección de iteración 2,
   con evidencia):** el libro bloqueado/cruzado en trading continuo NO aborta:
   existe en datos reales (transiciones halt→trading; p.ej. símbolo ZJZZT,
   msg 39778763 del día principal, bid==ask==130000 durante 2 mensajes). El
   book cuenta esos eventos con su índice de mensaje y el resumen del run los
   reporta. El modo estricto (`strict_cross=True` / `--strict`) mantiene el
   abort y es el que ejercitan los tests sintéticos.
   — Gherkin: `book.feature` §INV-01, §SEC-04, §SEC-05, §SEC-08
4. [ ] El escritor de vectores emite un registro por mensaje modificador
   (`A/F/E/C/X/D/U`) de los símbolos del subset, con índice de mensaje global
   monotónico, layout de 40 B del Anexo A y flag de cambio correcto.
   — Gherkin: `vectores.feature` §VEC-01, §VEC-02, §VEC-04
5. [ ] Round-trip: el volcado texto reproduce campo a campo el binario; el lector
   propio relee lo escrito sin pérdida.
   — Gherkin: `vectores.feature` §VEC-03
6. [ ] Run real del día principal: vectores + stats generados, invariantes sin
   violaciones, runtime ≤ 2 h (output de `time` pegado en el verify-report).
   — Gherkin: `parser.feature` §PAR-01, §PAR-02; `datos.feature` §DAT-02
7. [ ] `fetch_itch.py` descarga y verifica md5; md5 incorrecto aborta sin dejar
   fichero aparentemente válido. Si el servidor no sirve el `.md5sum` (hoy da
   404), aborta **fail closed** con error claro y exit != 0 (sin traceback);
   `--no-md5-verify` permite la descarga avisando por stderr (corrección de
   iteración 3, hallazgo de grade: el 404 llegaba como traceback no manejado).
   — Gherkin: `datos.feature` §DAT-01, §DAT-03, §SEC-07
8. [ ] `binaryfile_to_pcap.py`: pcap abrible con `tcpdump -r` sin errores;
   payload ≤ límite configurado; seq monotónico desde 1; **round-trip**:
   extrayendo los payloads MoldUDP64 del pcap se reconstruye el stream
   BinaryFILE original byte a byte.
   — Gherkin: `pcap.feature` §PCA-01…§PCA-04, §SEC-06
9. [ ] `subset_symbols.json` generado desde stats del día principal, con la tabla
   de ranking que lo justifica (artefacto para el write-up y dimensionado URAM).
   — Gherkin: `datos.feature` §DAT-02
10. [ ] Stdlib pura: `grep` de imports de `golden_model/` y `scripts/` muestra
    solo módulos stdlib (comando en Verificación).
    — Sin escenario Gherkin (propiedad estática, no comportamiento).

## Verificación

| Criterio | Cómo se prueba |
|---|---|
| 1, 2, 3, 4, 5 | `python3 -m unittest discover -s golden_model/tests -v` — tests espejo con título normalizado (regla: nombre del escenario en minúsculas, espacios→`_`, sin tildes ni puntuación, prefijo `test_`; ej. §SEC-01 → `test_sec01_tipo_de_mensaje_desconocido_es_error_duro`) |
| 6 | `time python3 golden_model/scripts/run_golden.py data/itch_sample/12302019.NASDAQ_ITCH50.gz --subset verification/vectors/subset_symbols.json --out data/itch_sample/out/` (exit 0, sin violaciones, runtime pegado) |
| 7 | `python3 scripts/fetch_itch.py <fichero>` sobre descarga íntegra vía `file://` (urllib real), fichero corrompido a propósito, y endpoint md5 404 (fail closed) |
| 8 | `python3 scripts/binaryfile_to_pcap.py <in> <out>.pcap` + `tcpdump -r <out>.pcap` + test espejo del round-trip |
| 9 | `cat verification/vectors/subset_symbols.json` + tabla de stats en el verify-report |
| 10 | `grep -RhE '^(import\|from) ' golden_model/ scripts/ \| sort -u` → solo stdlib |

Régimen completo: skill `verify`. Para esta campaña: gate A = unittest verde;
B/C = `python3 -m py_compile` de lo tocado + convenciones (type hints en APIs,
docstrings de módulo); D = tabla spec↔tests + cobertura por tipo de mensaje del
día real; E = **mutación manual pactada**: 5 mutantes sobre `book.py`/`parser.py`
(flip `<`→`<=` en BBO, ±1 en qty, no eliminar nivel a qty 0, flag de cambio
invertido, length check relajado) — cada uno debe morir con un test;
F = espejos Gherkin (esta campaña mapea a `golden_model/tests`, declarado en
`specs/gherkin-espejos.json`); G = G0+G3 (datos reales fuera del repo, golden
como fuente); **gate G de timing/Vivado: NO APLICA** (no hay RTL en fase 0, se
declara NO EJECUTADO con esta justificación).

**Contratos sin gate** — lo que puede romperse con suite y lint en verde:

1. **Tabla de layouts autoconsistente pero mal transcrita.** Parser y packer de
   tests comparten `messages.py`: si la tabla está mal copiada del PDF, los tests
   pasan igualmente. Guardarraíl: los vectores sintéticos de los tests son
   **literales hex escritos a mano desde el PDF de la spec** (oráculo
   independiente), nunca generados por el propio código; y el conteo por tipo del
   día real debe cuadrar con órdenes de magnitud conocidos (se pega en el
   verify-report).
2. **Layout del registro binario (Anexo A) vs. el futuro lector cocotb.** Nada en
   fase 0 fuerza al RTL a leerlo bien. Guardarraíl: round-trip writer↔reader↔texto
   en tests + layout fijado byte a byte en esta spec (cambiarlo = edit de spec).
3. **Semántica heredada por el RTL** (replace atómico, lado vacío = 0/0, flag de
   cambio): la define el golden y la consumen las fases 1-2; sus specs deben
   referenciar este contrato, no redefinirlo.

## Loop

Stop limit: **5 iteraciones**. Cadencia: encadenar build→verify→grade mientras
quede cola; al agotar el límite con criterios en FAIL, escala al owner.

---

## Anexo A — layout del registro de vectores (canónico, 40 bytes, little-endian)

| Offset | Tamaño | Campo | Descripción |
|---|---|---|---|
| 0 | 8 | `msg_idx` u64 | Índice global del mensaje en el BinaryFILE (0-based) |
| 8 | 8 | `ts_ns` u64 | Timestamp del mensaje (ns desde medianoche, del campo ITCH) |
| 16 | 4 | `bid_px` u32 | Mejor bid (precio ITCH entero, ×10⁴); 0 si lado vacío |
| 20 | 4 | `bid_qty` u32 | Cantidad agregada en mejor bid; 0 si lado vacío |
| 24 | 4 | `ask_px` u32 | Mejor ask; 0 si lado vacío |
| 28 | 4 | `ask_qty` u32 | Cantidad agregada en mejor ask; 0 si lado vacío |
| 32 | 2 | `locate` u16 | Stock Locate Code |
| 34 | 1 | `msg_type` u8 | Tipo ITCH ASCII (`A,F,E,C,X,D,U`) |
| 35 | 1 | `flags` u8 | bit0 = BBO cambió respecto al registro anterior del símbolo |
| 36 | 4 | `reserved` u32 | 0 (futura profundidad/versión) |

`struct` Python: `"<QQIIIIHBBI"`. Un registro por mensaje modificador de cada
símbolo del subset. Sin cabecera de fichero (el layout es el contrato; el
nombre de fichero lleva día + hash del subset).

## Anexo B — datos de la campaña

- **Día principal:** `12302019.NASDAQ_ITCH50.gz` (~3,5 GB gz — el v5.0 más
  pequeño del servidor a 2026-08). **Día de regresión:** `01302019.NASDAQ_ITCH50.gz`
  (~4,8 GB gz). Si dejaran de estar disponibles: el v5.0 más pequeño disponible,
  con edit explícito de este anexo.
- Los crudos y los vectores generados viven en `data/itch_sample/` (gitignored).
- Los ficheros NO son pcap: son BinaryFILE (`length u16be + payload`), sin
  sequence numbers — los seq de MoldUDP64 del pcap son sintéticos, y la detección
  de gaps se probará en fases RTL con secuencias fabricadas, no con este replay.
