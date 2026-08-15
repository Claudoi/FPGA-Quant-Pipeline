# verify-report — fase1-parser-rtl — cierre de framing `tkeep`

> Evidencia vigente ejecutada el 2026-08-15 desde el commit base
> `22130e3fae758edaf674a3ceb9c45b38711a2f5b`, con builds limpios y
> `PATH=/Volumes/WD_Black/FPGA/.venv/bin:$PATH`. Sustituye la evidencia de la
> iteración cuyo driver concatenaba datagramas y no representaba los bytes
> válidos del último beat.

## Veredicto

**PASS funcional del delta de framing `s_axis_tkeep`.** El driver vigente
presenta cada payload MoldUDP64 como un burst AXI independiente, conserva
`(tdata,tkeep,tlast)` durante stalls y exige un handshake `tlast` por payload.
La reapertura técnica de los criterios 4, 5, 7, 8 y 10 queda cubierta por la
evidencia fresca inferior. La fase 1 no reclama cierre de timing físico: ese
gate no aplica a esta campaña.

No se usó una pasada sintética como sustituto del replay: el artefacto local
`/tmp/real_subset.pcap` existía, contenía 91 datagramas no vacíos y REP-02 se
ejecutó con `SKIP=0`.

## Entorno reproducido

```text
fecha: 2026-08-15T14:58:46+01:00
Python 3.11.14 (ejecutable: /Volumes/WD_Black/FPGA/.venv/bin/python3)
cocotb 2.0.1
Verilator 5.050 2026-07-01
GNU Make 3.81
verible-verilog-lint: no instalado
/tmp/real_subset.pcap: 129930 bytes, 91 paquetes, 91 payloads no vacíos,
                       3000 mensajes
```

La cabecera de cocotb informa Python 3.11.9 para el intérprete embebido de la
misma `.venv`; el comando de orquestación y los unittest se ejecutaron con
Python 3.11.14. Se registran ambos valores para no ocultar esa diferencia del
entorno.

## Gates A–G

| Gate | Evidencia fresca | Resultado |
|---|---|---|
| A — simulación | golden `37/37`; parser desde `make clean`: `TESTS=31 PASS=31 FAIL=0 SKIP=0`; REP-02 real: 91 paquetes y 17.937 words de 64 bits bit a bit | **PASS** |
| B — compilación | elaboración limpia de cocotb/Verilator y `verilator --lint-only --Wall --top-module itch_parser rtl/parser/itch_parser.sv`, exit 0, cero warnings | **PASS** |
| C — estilo | `verible-verilog-lint` no está instalado | **NO EJECUTADO** |
| D — cobertura | mapa literal de los criterios reabiertos a tests, incluido `SEC-FRM-04..08` y `REP-02`; cobertura instrumental no configurada | **PASS nivel 1** |
| E — mutación | `mutate_parser.py`: 19/19 mutantes compilables y muertos; 0 supervivientes, 0 mutantes rotos | **PASS** |
| F — completitud | script literal Gherkin↔tests: `IDs ITCH/fase 3 únicos y mapas a tests completos` | **PASS** |
| G — rigor/timing | pcap real fuera de Git, oráculo Python independiente y replay real ejecutado; timing físico no aplica a fase 1 | **PASS** |

## Gate A — salida fresca

```text
$ python3 -m unittest discover -s golden_model/tests -t .
Ran 37 tests in 0.016s
OK
exit 0

$ make -C verification/testbenches/parser clean
exit 0

$ make -C verification/testbenches/parser sim
REP-02 OK: 91 paquetes, 17937 words byte a byte
TESTS=31 PASS=31 FAIL=0 SKIP=0
exit 0
```

El assert del driver es literal:
`accepted_tlast == len(payloads)`. En REP-02 `len(payloads) == 91`; por tanto
la pasada verde observó **91 handshakes de entrada con `tlast`**, uno por cada
datagrama decapsulado. Los últimos beats se forman con un prefijo MSB contiguo
en `tkeep`; los lanes no válidos no se incorporan al parser.

Además del replay, la suite cubre:

- `SEC-FRM-04`: `count=0` y último beat parcial `tkeep=11110000`;
- `SEC-FRM-05`: dos datagramas no alineados, dos `tlast` aceptados;
- `SEC-FRM-06`: máscaras cero, con huecos, LSB y parcial sin `tlast`, con
  descarte y recuperación;
- `SEC-FRM-07`: cierre exacto `count↔tlast`, residuo y cierre tardío;
- `SEC-FRM-08`: estabilidad de `tdata`, `tkeep` y `tlast` bajo backpressure;
- `REP-02`: límites reales conservados y comparación byte a byte.

## Gates B y C — salida fresca

```text
$ verilator --lint-only --Wall --top-module itch_parser \
    rtl/parser/itch_parser.sv
Verilator 5.050; exit 0; cero warnings

$ if command -v verible-verilog-lint ...
Gate C NO EJECUTADO: verible-verilog-lint no instalado
exit 0
```

Gate C no se convierte en PASS por haber pasado `--Wall`.

## Gate D/F — mapa del contrato vigente

| ID | Test que lo pincha |
|---|---|
| SEC-FRM-04 | `test_sec_frm04_count_cero_valido`, `test_sec_frm04_count_cero_parcial_msb_y_recuperacion` |
| SEC-FRM-05 | `test_sec_frm05_datagramas_no_alineados_no_comparten_beat` |
| SEC-FRM-06 | `test_sec_frm06_*`, `test_axi_keep_orientacion_msb_lsb` |
| SEC-FRM-07 | `test_sec_frm07_count_tlast_cierre_exacto`, `test_sec_frm07_count_exacto_sin_tlast_da_error` |
| SEC-FRM-08 | `test_sec_frm08_fuente_estable_bajo_backpressure_entrada` |
| REP-02 | `test_rep02_replay_pcap_real_dia_local` |

El script literal verificó unicidad en Gherkin y presencia normalizada en los
tests. `specs/gherkin-espejos.json` ya era coherente; no se modificaron spec,
Gherkin ni espejos.

## Gate E — salida fresca

```text
$ python3 scripts/verify/mutate_parser.py
ALN-OFFBYONE ... COUNT-RESIDUAL: compiló=sí, MATADO
19/19 killed; 0 survivors; 0 errores de compilación del mutante
19/19 mutantes compilables y muertos. Gate E PASS.
exit 0
```

Los siete mutantes nuevos del contrato de bytes válidos/cierre de datagrama
(`KEEP-ALL-BYTES`, `KEEP-LSB-FIRST`, `KEEP-HOLES`,
`KEEP-PARTIAL-NONLAST`, `KEEP-NODRAIN`, `COUNT-NO-EOP` y
`COUNT-RESIDUAL`) compilaron y murieron. El runner restauró el RTL y eliminó
su build; `git diff -- rtl/parser/itch_parser.sv` quedó vacío.

## Límites

- La evidencia de replay depende de un pcap local no versionado; si falta en
  otra máquina, el test será `SKIP`, no PASS.
- No se ejecutó cobertura instrumental ni Verible.
- Esta campaña no mide WNS/TNS ni utilización y no pretende acreditar la
  frecuencia física de fase 3.
