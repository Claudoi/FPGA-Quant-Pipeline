# verify-report — fase0-golden-model (iteración 1)

> Régimen de gates A-G (skill verify) sobre `specs/fase0-golden-model/spec.md`.
> Un gate sin output pegado NO está pasado. Los dos días reales requeridos por
> los criterios 6 y 9 están documentados; los ficheros permanecen fuera de Git.

## Meta del atacante/diseño

¿Cómo podría este golden model mentir sin que nadie lo note? (1) Tabla de
layouts mal transcrita del PDF pero autoconsistente entre parser y tests;
(2) un book que descuenta dos veces o deja niveles vacíos; (3) vectores cuyo
layout binario no es el que el RTL leerá en fase 1; (4) un pcap que Wireshark
abre pero cuyo framing no reproduce el stream original.

## Gates

| Gate | Comando | Resultado | Veredicto |
|---|---|---|---|
| A. Simulación | `python3 -m unittest discover -s golden_model/tests -t .` | `Ran 29 tests in 0.010s — OK` | PASS |
| B. Compilación/lint | `python3 -m py_compile <9 fuentes + 6 tests>` | sin salida, exit 0 | PASS |
| C. Estilo/convenciones | revisión manual sobre lo tocado (campaña nueva) | type hints en APIs públicas, docstring de módulo en todos, stdlib pura | PASS |
| D. Cobertura | nivel 1: tabla spec↔tests (abajo); nivel 2: cobertura por tipo | 29 escenarios ↔ 29 tests; los 22 tipos ejercitados en PAR-01 (sintético) + conteo del día real (sección abajo) | PASS |
| E. Mutación | 5 mutantes manuales pactados en spec | 5/5 muertos (tabla abajo) | PASS |
| F. Completitud Gherkin | `grep` escenarios vs tests espejo + `specs/gherkin-espejos.json` | 29↔29 con regla de normalización documentada; entrada de manifiesto presente | PASS |
| G. Rigor por superficie | G0/G3 (abajo); **timing/Vivado: NO APLICA** (no hay RTL — pactado en spec) | sin datos reales commiteados; golden como fuente | PASS |

### Gate A — evidencia

```
$ python3 -m unittest discover -s golden_model/tests -t .
Ran 29 tests in 0.010s
OK
```

(Grade de la iteración 2 cazó este informe con «Ran 27»: quedó desactualizado
al añadirse SEC-08; corregido en la iteración 3 — números re-ejecutados.)

Rojos evidenciados durante TDD (build): `ModuleNotFoundError` por módulo en
cada loop (parser, book, vectors, pcap, datos) antes de implementar; 3 fallos
de oráculo corregidos en tests (cabecera E reutilizada en C, campo reserved de
H, locate por defecto en VEC-01) — nunca se suavizó un test para pasar.

### Gate E — mutantes (manual, pactado; en solitario)

| # | Mutante | Test que lo mata |
|---|---|---|
| M1 | `_emit`: `bid_px >= ask_px` → `>` (cruce con igualdad pasa) | `test_inv01` (caso libro cerrado añadido al detectar el hueco) |
| M2 | `_reduce`: `rest < 0` → `rest <= 0` | `test_lib03`, `test_lib04` |
| M3 | `_level_add`: no eliminar nivel a qty 0 | `test_lib03/04/05/06` |
| M4 | `write_record`: flag de cambio siempre 0 | `test_vec01` |
| M5 | parser: `declared != expected` → `<` | sobrevivió en la primera pasada → **test que faltaba**: caso simétrico añadido a `test_sec02` (mensaje más largo); re-ejecutado: muerto |

### Gate D nivel 1 — cruce spec↔tests

| Criterio spec | Tests |
|---|---|
| 1 (parser valida/itera) | test_par01/02/03, test_sec01/02/03 |
| 2 (book known-answer) | test_lib01..06 |
| 3 (invariantes) | test_inv01, test_sec04, test_sec05, test_sec08 |
| 4 (vectores layout/emisión) | test_vec01, test_vec02, test_vec04 |
| 5 (round-trip binario↔texto) | test_vec03 |
| 6 (run día real ≤ 2h) | sección «Día real» (abajo) |
| 7 (fetch + md5) | test_dat01, test_dat03, test_sec07 + brazo real (abajo) |
| 8 (pcap + round-trip) | test_pca01..04, test_sec06 |
| 9 (subset desde stats) | test_dat02 |
| 10 (stdlib pura) | comando grep (abajo) — propiedad estática sin escenario |

### Gate G0/G3 — evidencia

```
$ git status --porcelain | grep -E "\.gz|\.pcap|\.bin"
(sin salida: ningún dato crudo ni artefacto binario en el árbol de git)

$ grep -RhE '^(import|from) ' golden_model/ scripts/ | grep -vE "^from \.+|golden_model|^from scripts" | sort -u
→ solo stdlib (argparse, csv, gzip, hashlib, io, json, shutil, socket,
  struct, subprocess, sys, tempfile, typing, unittest, urllib.request,
  collections, os, pathlib) — criterio 10 PASS
```

- Vectores de demo: solo sintéticos, generados por los propios tests.
- El golden model es la fuente de los vectores; no existe RTL del que copiar.

### Desviación de entorno e iteración 3 (hallazgos de grade → arreglos)

1. **Endpoint `.md5sum` 404** (probado con 12302019/01302019/07302019/S112825;
   FTP :21 no responde). Arreglo iteración 3: `fetch_itch.py` ahora aborta
   **fail closed** con error claro y exit 2 si el servidor no sirve el md5sum
   (`Md5NotAvailableError`); `--no-md5-verify` descarga avisando por stderr.
   Nuevo escenario DAT-03 + `test_dat03`.
2. **Brazo real del criterio 7, ejecutado** (grade lo cazó como no ejecutado):
   ```
   $ python3 scripts/fetch_itch.py 12302019.NASDAQ_ITCH50.gz --dest …/fetchtest
   ERROR: …: el servidor no sirve .md5sum; sin verificacion md5 no se
   descarga (fail closed). Usa --no-md5-verify para forzar.
   exit=2   (0 ficheros en destino)

   # y descarga íntegra + md5 verificado con urllib real (sin mock), vía file://:
   >>> fetch("mini.gz", …, base_url="file://…/fakeserver/", opener=urllib.request.urlopen)
   descargado y verificado md5: …/fetch_ok/mini.gz 3000000 bytes
   ```
   El día principal se descargó con curl paralelo por rangos (la descarga en
   serie se estancaba a ~350 KB/s); integridad: content-length exacto
   (3.524.013.057 B) + `gzip -t` íntegro.
3. **`.gitignore` no cubría subdirectorios de `data/itch_sample/`** (grade,
   lente 7): `out_vectors/vectors.bin` (577 MB) habría entrado en un
   `git add .`. Ahora `data/itch_sample/**` ignorado (salvo `.gitkeep`).

## Veredicto

**Listo para /grade (iteración 3).** Los 10 criterios con evidencia; gates
A-G en verde (G de timing declarado NO APLICA por spec). Desviación de
entorno resuelta con fail closed + evidencia real.

## Día real (criterios 6 y 9)

Fichero: `data/itch_sample/12302019.NASDAQ_ITCH50.gz` (3.524.013.057 B,
content-length exacto del servidor + `gzip -t` íntegro — el endpoint
`.md5sum` del servidor da 404, ver desviación de entorno arriba).

### Iteración 1 → hallazgo real (documentado en la iteración 2 del loop)

El primer run abortó en el mensaje 39.778.763 (`InvariantError: libro cruzado
en trading continuo`, locate 8876). Forense con el Book de producción:
el símbolo ZJZZT (símbolo de test de Nasdaq) quedó con bid == ask == 130000
tras una transición halt→trading; el bloqueo se resolvió 2 mensajes después.
**Los libros bloqueados transientes existen en datos reales** → corrección
explícita de spec (criterio 3): el cruce en trading continuo se cuenta y
reporta; el abort queda para el modo estricto de los tests sintéticos.
Nuevo escenario SEC-08 + `test_sec08`.

### Run del día completo (stats), tras la corrección

```
$ time python3 -m golden_model.scripts.run_golden \
    data/itch_sample/12302019.NASDAQ_ITCH50.gz --out data/itch_sample/out_day

{
  "anomalies": 0,
  "by_type": {"A": 117145568, "C": 99917, "D": 114360997, "E": 5722824,
              "F": 1485888, "H": 8966, "I": 4024315, "J": 34, "K": 3,
              "L": 215161, "P": 1218602, "Q": 17836, "R": 8906, "S": 6,
              "U": 21639067, "V": 1, "X": 2787676, "Y": 9013},
  "cross_events": 642,
  "messages": 268744780,
  "records": 0,
  "symbols": 8906
}
real  17m14.840s
```

- **268.744.780 mensajes en 17m14s** (≈260k msg/s) → criterio 6 (≤ 2 h): PASS
  con un factor 7 de margen.
- 0 anomalías (toda order ref conocida — día completo), 642 cross_events
  contados (0,0002 % de los mensajes modificadores), chequeos profundos
  (cada 1M mensajes + cierre) sin violaciones.
- Conteo por tipo coherente con el mercado real (A/D dominan; NOII `I`
  4,0M concentrado en apertura/cierre; `S`=6 eventos del sistema). Tipos no
  presentes ese día: B, N, O, W (sus validaciones se ejercitan en PAR-01).

### Selección del subset (criterio 9)

`verification/vectors/subset_symbols.json` (commiteado, es config) generado
con `select_subset.py` sobre las stats del día — top 20 por pico de órdenes
vivas:

| # | Símbolo | Msgs | Pico órdenes | Pico niveles |
|---|---|---|---|---|
| 1 | AMZN | 536.079 | 37.068 | 5.608 |
| 2 | AAPL | 1.519.865 | 27.110 | 5.320 |
| 3 | MSFT | 1.221.478 | 23.005 | 3.813 |
| 4 | TSLA | 545.564 | 17.482 | 3.558 |
| 5 | FB | 544.602 | 14.736 | 2.878 |
| … | CSCO, NVDA, AMD, NFLX, ROKU, MU, QQQ, INTC, BYND, SBUX, QCOM, GOOGL, KHC, GOOG, COST | | | |

Consecuencia para el RTL (fase 2): el top 20 suma ~250k órdenes vivas pico —
el dimensionado URAM del book RTL parte de esta tabla, no de una suposición.

### Run de vectores (subset)

```
$ time python3 -m golden_model.scripts.run_golden \
    data/itch_sample/12302019.NASDAQ_ITCH50.gz \
    --subset verification/vectors/subset_symbols.json \
    --out data/itch_sample/out_vectors --text

{ "messages": 268744780, "records": 14427667, "anomalies": 0,
  "cross_events": 642, "by_type": { ...idéntico al run de stats... } }
real  17m50.728s
```

- **14.427.667 registros** = `vectors.bin` 577.106.680 B (múltiplo exacto de
  40 B) + `vectors.txt` (volcado) — ambos runs ≤ 2 h: criterio 6 PASS.
- **Determinismo**: `by_type`, `anomalies`, `cross_events` idénticos entre
  los dos runs independientes del mismo fichero (Constraints de la spec).
- Verificación de los vectores reales (`iter_records` sobre los 14,4M):
  msg_idx estrictamente creciente en todo el fichero; primera/última línea
  del volcado texto idénticas campo a campo al primer/último registro binario:
  ```
  primero: msg 241819  (04:00:00.5 ET, pre-market) A SBUX   -> 0,0,971000,40  changed=1
  ultimo:  msg 268744735 (20:00:00.97 ET, cierre)  D NFLX   -> 0,0,0,0        changed=1
  ```
- Flag de cambio correcto en datos reales: mensajes consecutivos sobre el
  mismo símbolo con BBO idéntico llevan `changed=0` (msgs 241823/241831, TSLA).

### Regresión independiente del segundo día — 01302019 (2026-08-15)

Artefacto local ignorado:
`data/itch_sample/01302019.NASDAQ_ITCH50.gz`, 4.764.426.091 bytes. La integridad
del contenedor se volvió a comprobar antes de incorporar esta evidencia:

```text
$ time gzip -t data/itch_sample/01302019.NASDAQ_ITCH50.gz
11.71s user 0.42s system 65% cpu 18.528 total
```

Ejecución completa realizada durante la auditoría del 2026-08-15:

```text
$ python3 -m golden_model.scripts.run_golden \
    data/itch_sample/01302019.NASDAQ_ITCH50.gz --out /tmp/fpga-fase0-0130

{
  "anomalies": 0,
  "by_type": {
    "A": 162970455, "B": 116, "C": 158886, "D": 158273361,
    "E": 8096995, "F": 1725898, "H": 8805, "I": 3684511,
    "J": 62, "L": 193769, "P": 1326184, "Q": 17430,
    "R": 8714, "S": 6, "U": 27222746, "V": 1,
    "X": 4669874, "Y": 8821
  },
  "cross_events": 63,
  "messages": 368366634,
  "records": 0,
  "symbols": 8713
}
22:15.77 total
```

Resultado: **368.366.634 mensajes**, 8.713 símbolos, cero referencias de orden
anómalas y 63 estados cruzados/bloqueados transitorios contabilizados sin
abortar. Es una segunda jornada completa, no una muestra sintética ni un
replay parcial. Cierra el cabo del criterio 9 sin añadir el feed ni los CSV
generados al repositorio. Duración 22m15s, con 1h37m44s de margen frente al
umbral máximo de 2 horas.

Regresión Python posterior en la rama de cierre:

```text
$ python3 -m unittest discover -s golden_model/tests -t .
Ran 36 tests in 0.021s
OK
```
