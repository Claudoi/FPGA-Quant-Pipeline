# verify-report — fase1-parser-rtl — cierre de framing `tkeep`

> Evidencia vigente ejecutada el 2026-08-15 desde el commit base
> `22130e3fae758edaf674a3ceb9c45b38711a2f5b`, con builds limpios y
> `PATH=/Volumes/WD_Black/FPGA/.venv/bin:$PATH`. Sustituye la evidencia de la
> iteración cuyo driver concatenaba datagramas y no representaba los bytes
> válidos del último beat.

Fix Round 1 reejecutado el `2026-08-15T15:37:59+01:00` sobre
`785675bfcaf35937cf060fe0d0c4fc3bc0d6c52b`; las secciones de REP-02 y Gate F
inferiores contienen sus outputs nuevos.

## Veredicto

**PASS funcional del delta de framing `s_axis_tkeep`; fase 1 CERRADA (2026-08-19).** El driver vigente
presenta cada payload MoldUDP64 como un burst AXI independiente, conserva
`(tdata,tkeep,tlast)` durante stalls y exige un handshake `tlast` por payload.
REP-02 quedó cerrado el 2026-08-19 en WSL (cocotb 2.0.1 + Verilator 5.046,
Python 3.12): un subset reproducible de 5.200 paquetes del día real
2019-12-30 (251.375 mensajes) seleccionado desde el pcap **sin índices
manuales**, replay bit a bit (32/32) y el tramo de cuatro A/U consecutivos
(msgs 241733..241736, primera ventana deslizante en orden de captura) con
**9 stalls ≤ 24** y downstream siempre listo, salida bit a bit contra el
oráculo. El gate de timing físico no aplica a esta campaña.

No se usó una pasada sintética como sustituto del replay: el artefacto local
`/tmp/real_subset.pcap` (subset del BinaryFILE real `12302019.NASDAQ_ITCH50.gz`,
descargado con verificación de integridad por tamaño, 3.524.013.057 B = el
Content-Length del servidor; el endpoint `.md5sum` de emi.nasdaq.com ya no
se sirve — 404 — y se documenta el `--no-md5-verify` con warning) y REP-02 se
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
| A — simulación | parser desde `make clean`: `TESTS=32 PASS=32 FAIL=0 SKIP=0`; REP-02 real: 5.200 paquetes, 100.673 words y tramo A/U contractual (msgs 241733..241736) con 9 stalls ≤ 24, downstream listo | **PASS — REP-02 cerrado** |
| B — compilación | elaboración limpia de cocotb/Verilator y `verilator --lint-only --Wall --top-module itch_parser rtl/parser/itch_parser.sv`, exit 0, cero warnings | **PASS** |
| C — estilo | `verible-verilog-lint` no está instalado | **NO EJECUTADO** |
| D — cobertura | `SEC-FRM-04..08` cubiertos; REP-02 cubre oráculo/`tlast` y el tramo A/U contractual (primera ventana deslizante en orden de captura, sin índices manuales); cobertura instrumental no configurada | **PASS** |
| E — mutación | `mutate_parser.py`: 19/19 mutantes compilables y muertos; 0 supervivientes, 0 mutantes rotos | **PASS** |
| F — completitud | checker versionado: 12 IDs/3 campañas, unicidad de declaraciones Gherkin por campaña, presencia en spec/test AST/report y rutas del manifiesto; 14 negativos controlados | **PASS** |
| G — rigor/timing | pcap real fuera de Git, oráculo Python independiente y replay real ejecutado; el tramo contractual A/U de cuatro mensajes medido con `<=24` stalls | **PASS de rigor; REP-02 cerrado** |

## Gate A — salida fresca

```text
$ python3 -m unittest discover -s golden_model/tests -t .
Ran 37 tests in 0.016s
OK
exit 0

$ make -C verification/testbenches/parser clean
exit 0

$ make -C verification/testbenches/parser sim
REP-02 OK: 5200 paquetes, 100673 words byte a byte,
stalls de entrada con m_axis_tready=1: 107477
REP-02 line-rate OK: tramo A/U real (msgs 241733..241736, 4 mensajes), 9 stalls con downstream siempre listo, salida bit a bit
TESTS=32 PASS=32 FAIL=0 SKIP=0
exit 0
```

Re-ejecutado el 2026-08-19 en WSL (cocotb 2.0.1 + Verilator 5.046, Python
3.12, verilator 5.046) sobre el subset reproducible de **5.200 paquetes** del
día real 2019-12-30 (251.375 mensajes, 71 MB) extraído del pcap completo
(6.049.916 datagramas, 268.744.780 mensajes — el conteo del día real de
fase 0) sin índices manuales: primeras N paquetes en orden de captura.

El assert del driver es literal:
`accepted_tlast == len(payloads)`. En REP-02 `len(payloads) == 5200`; por tanto
la pasada verde observó **5.200 handshakes de entrada con `tlast`**, uno por cada
datagrama decapsulado. Los últimos beats se forman con un prefijo MSB contiguo
en `tkeep`; los lanes no válidos no se incorporan al parser. El mismo driver
contó **107.477 ciclos** con `s_axis_tvalid=1 && s_axis_tready=0` mientras
`m_axis_tready=1` durante el replay completo.

**Cierre contractual de REP-02**: el test `test_rep02_tramo_au_real_line_rate`
localiza en orden de captura, mediante el propio pcap y sin un índice manual,
la primera ventana deslizante de cuatro mensajes consecutivos de tipo A/U
(msgs 241733..241736), la procesa con el downstream siempre listo y cuenta
solo los stalls de los beats que cubren esa ventana: **9 stalls ≤ 24** y
salida bit a bit contra el oráculo. El total agregado del replay (107.477) no
sustituye esa medida; la ventana es la del contrato (LIN-01).

```text
$ python3 - <<'PY'
from scripts.binaryfile_to_pcap import iter_pcap_packets
hits = []
for packet_index, (_, messages, _) in enumerate(
        iter_pcap_packets('/tmp/real_subset.pcap')):
    for start in range(len(messages) - 3):
        kinds = bytes(message[0] for message in messages[start:start + 4])
        if all(kind in b'AU' for kind in kinds):
            hits.append((packet_index, start, kinds.decode()))
print(f'tramos_AU4={len(hits)} primero={hits[0] if hits else None}')
PY
tramos_AU4=1 primero=(3325, 40, 'AAAA')
exit 0
```

El subset de 5.200 paquetes del día real contiene la ventana contractual
(primera en orden de captura: paquete 3325, mensaje 40 → msgs 241733..241736
del replay plano), seleccionada por el propio test sin índices manuales. La
caracterización histórica con el pcap antiguo (91 datagramas, 0 ventanas)
quedó sustituida: ese artefacto no podía cerrar REP-02; el actual sí.

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
| REP-02 | `test_rep02_replay_pcap_real_dia_local`, `test_rep02_tramo_au_real_line_rate` |

El checker versionado verificó cada ID exactamente una vez en una declaración
real `Escenario:`/`Scenario:` de su propia campaña, presencia en `spec.md`,
función `test_*` ejecutable obtenida del AST y `verify-report.md`, además de
que el manifiesto no esté vacío y que todas sus rutas existan. Comentarios,
strings y nombres con el ID embebido no cuentan. `CHAIN-01` se comparte
intencionalmente entre las dos campañas de fase 3; la excepción URAM apunta
de forma explícita a `verification/testbenches/phase3/test_chain32.py`.

```text
$ python3 -m unittest -v scripts.verify.test_check_itch_gherkin
test_comprueba_el_espejo_externo_de_chain01_uram ... ok
test_detecta_ausencia_de_test_ordinario ... ok
test_detecta_cero_escenarios_para_un_id ... ok
test_detecta_id_ausente_de_spec ... ok
test_detecta_id_ausente_de_verify_report ... ok
test_detecta_id_gherkin_duplicado_en_su_campana ... ok
test_detecta_manifiesto_vacio ... ok
test_detecta_mapping_de_campana_incoherente ... ok
test_detecta_ruta_espejo_inexistente ... ok
test_detecta_ruta_gherkin_inexistente ... ok
test_ignora_async_test_comentado ... ok
test_ignora_id_solo_en_comentario_gherkin ... ok
test_ignora_string_que_parece_def_test ... ok
test_no_acepta_id_embebido_en_nombre_de_test ... ok
test_snapshot_sano_pasa ... ok
Ran 15 tests in 0.052s
OK

$ python3 scripts/verify/check_itch_gherkin.py
Gate F PASS: 12 IDs en 3 campañas; Gherkin único por campaña,
spec/test/verify-report presentes y rutas del manifiesto existentes
Espejo externo verificado: fase3-uram/CHAIN-01 ->
verification/testbenches/phase3/test_chain32.py
exit 0
```

## Gate E — salida fresca de Tarea 6, no repetida en el fix

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
- REP-02 quedó **CERRADO (2026-08-19)**: tramo A/U contractual medido sobre
  el subset de 5.200 paquetes del día real (primera ventana deslizante en
  orden de captura, msgs 241733..241736) con 9 stalls ≤ 24, downstream
  siempre listo y salida bit a bit.
- El endpoint `.md5sum` de emi.nasdaq.com ya no se sirve (404); la descarga
  se verificó por tamaño íntegro (3.524.013.057 B = Content-Length) y el
  conteo de mensajes del pcap (268.744.780 = el día de fase 0). Documentado
  con `--no-md5-verify` + warning (fail closed del script respetado).
- No se ejecutó cobertura instrumental ni Verible.
- Esta campaña no mide WNS/TNS ni utilización y no pretende acreditar la
  frecuencia física de fase 3.
