# verify-report — fase3-uram — regresión `tkeep` y Anexo A

> Evidencia vigente ejecutada el 2026-08-15 desde el commit base
> `22130e3fae758edaf674a3ceb9c45b38711a2f5b`, con builds limpios y
> `PATH=/Volumes/WD_Black/FPGA/.venv/bin:$PATH`. La historia de iteraciones
> anteriores permanece en Git; este documento contiene solo la evidencia que
> puede considerarse vigente para el loop de `tkeep`.

## Veredicto

**PASS funcional del delta de entrada y del Anexo A recortado. Fase 3/URAM NO
CERRADA.** Parser, cadena con book URAM y layout recortado se reejecutaron con
`s_axis_tkeep`; la campaña sigue abierta porque falta la evidencia física
Vivado de timing e inferencia/utilización.

`synth_check.py` es un guardarraíl estático. No sustituye WNS/TNS ni demuestra
que la memoria se haya inferido como URAM en el dispositivo objetivo.

## Gates A–G

| Gate | Evidencia fresca del loop `tkeep` | Resultado |
|---|---|---|
| A — simulación | ANX 3/3; parser32 5/5; chain ND=5 4/4; chain ND=3 4/4; latencia 1/1; `FAIL=0 SKIP=0` | **PASS para el delta `tkeep`** |
| B — compilación | lint `--Wall` de parser DW32 y cadena DW32 con orderbook URAM, exit 0 y cero warnings | **PASS** |
| C — estilo | `verible-verilog-lint` no instalado | **NO EJECUTADO** |
| D — cobertura | ANX-01/02, CHAIN-01 y P32-01/02 con mapas literales; cobertura instrumental no configurada | **PASS nivel 1** |
| E — mutación | frontera de entrada: 19/19 mutantes del parser compilables y muertos; mutación interna del orderbook no reejecutada en este brief | **PASS para el delta `tkeep`** |
| F — completitud | IDs únicos y presentes en Gherkin/tests; espejo URAM ya declarado | **PASS** |
| G — rigor/timing | golden independiente, datos fuera de Git y `synth_check.py` 22/22; sin Vivado WNS/TNS/utilización | **ABIERTO** |

El target `sim-uram` estructural no figura entre los comandos de esta tarea y
no se reejecutó en este loop. Sus números históricos no se presentan como
frescos. La evidencia vigente de integración sí elabora y simula el
`orderbook.sv` URAM dentro de `itch_chain`.

## Gate A — salida fresca

```text
$ make -C verification/testbenches/uram clean-all
$ make -C verification/testbenches/uram sim-anx
ANX-01 OK: 75 words de 32 bits bit a bit (10 mensajes)
ANX-01 OK (feed real): 31400 mensajes -> 197452 words bit a bit
ANX-02 OK: 2 stalls acotados, 4 mensajes, 34 words
TESTS=3 PASS=3 FAIL=0 SKIP=0
exit 0
```

ANX real usa los 31.400 mensajes del subset extraído de
`/tmp/real_trading.pcap` y los reconstruye en un payload; su driver exige un
handshake `tlast`. Por ello la pasada demuestra **1 `tlast`** para ese stream
filtrado, no los 3.222 límites originales del pcap.

La preservación de límites reales se ejercitó separadamente en P32-03:

```text
P32-03 OK: 91 paquetes, 26904 words de 32 bits bit a bit
accepted_tlast == len(payloads) == 91
```

La integración con el book URAM se ejercitó en las dos elaboraciones de la
cadena:

```text
chain ND=5: TESTS=4 PASS=4 FAIL=0 SKIP=0
chain ND=3: TESTS=4 PASS=4 FAIL=0 SKIP=0
CHAIN-01: 31400 mensajes -> 30729 eventos bit a bit
cross=0, anomaly=671, gaps=0
```

`test_chain_tkeep_datagramas_no_alineados_y_estabilidad` verificó además dos
datagramas sintéticos parciales, dos handshakes `tlast`, backpressure real de
entrada y estabilidad de `(tdata,tkeep,tlast)`.

## Latencia vigente de simulación

```text
$ make -C verification/testbenches/phase3 clean-all
$ make -C verification/testbenches/phase3 sim-lat
SEC-LAT-01 OK: 30729 eventos; dos ejecuciones idénticas
mean=44.318 ciclos; p50=44; p99=61; min=32; max=74
TESTS=1 PASS=1 FAIL=0 SKIP=0
exit 0
```

El umbral funcional de SEC-URAM-04 pasa en simulación. El periodo de 3,103 ns
usado para una conversión teórica a nanosegundos es el objetivo del XDC, no un
reloj físico medido.

## Gates B/C/G — salida fresca

```text
$ verilator --lint-only --Wall --top-module itch_parser -GDW=32 \
    rtl/parser/itch_parser.sv
exit 0; cero warnings

$ verilator --lint-only --Wall --top-module itch_chain -GDW=32 \
    rtl/itch_chain.sv rtl/parser/itch_parser.sv rtl/orderbook/orderbook.sv
exit 0; cero warnings

Gate C NO EJECUTADO: verible-verilog-lint no instalado

$ python3 scripts/verify/synth_check.py
22 PASS; 0 FAIL
synth_check: OK — tcl/constraints coherentes con el RTL y la spec
exit 0
```

Los checks estáticos confirmaron el patrón
`rd_data <= o_mem[rd_addr]`, la ausencia de lecturas `o_mem[pr_*]`, el periodo
de 3,103 ns, los puertos/delays y la generación de informes del Tcl. Ninguno
es un informe de implementación.

## Gates D/E/F

| ID | Test/evidencia vigente |
|---|---|
| ANX-01 | `test_anx_01_anexo_a_32_bits_recortado_es_bit_a_bit_contra_el_oraculo`, replay real ANX |
| ANX-02 | `test_anx_02_el_peor_caso_sigue_a_1_palabra_por_ciclo_con_el_layout_recortado` |
| CHAIN-01 | cadena ND=5 y ND=3, real + sintética + multi-datagrama `tkeep` |
| P32-01/02 | parser32, replay de 91 datagramas y régimen de stalls acotados |

```text
$ python3 scripts/verify/mutate_parser.py
19/19 killed; cada mutante compiló; 0 supervivientes; 0 mutantes rotos
19/19 mutantes compilables y muertos. Gate E PASS.
exit 0

$ python3 - <<'PY'  # script literal del brief
IDs ITCH/fase 3 únicos y mapas a tests completos
exit 0
```

No se modificaron specs, Gherkin ni `specs/gherkin-espejos.json`: el script
literal pasó a la primera. La mutación 19/19 acredita la frontera heredada
del parser; no se recicla como una ejecución ficticia de los mutantes internos
de la URAM/orderbook.

## Bloqueador físico

No hay run Vivado vigente que aporte:

- WNS/TNS post-route;
- endpoints sin constraint;
- inferencia y utilización URAM, BRAM, LUT y FF;
- DRC/metodología y adecuación de los delays I/O al wrapper real.

Hasta que esos artefactos existan y satisfagan el contrato, **fase 3/URAM
permanece NO CERRADA**, aunque `tkeep`, Anexo A y la latencia funcional de
simulación estén verdes.
