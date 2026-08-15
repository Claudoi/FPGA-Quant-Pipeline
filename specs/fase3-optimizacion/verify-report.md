# verify-report — fase3-optimizacion — regresión `tkeep` DW=32

> Evidencia vigente ejecutada el 2026-08-15 desde el commit base
> `22130e3fae758edaf674a3ceb9c45b38711a2f5b`, con builds limpios y
> `PATH=/Volumes/WD_Black/FPGA/.venv/bin:$PATH`. Sustituye como evidencia
> vigente las pasadas producidas antes de que el driver representara límites
> de datagrama mediante `s_axis_tkeep`.

## Veredicto

**PASS funcional del delta `tkeep` en parser y cadena DW=32. Fase 3 NO
CERRADA.** La frontera de framing reabierta queda verificada; el gate físico
continúa **ABIERTO** porque no existe un informe Vivado real con WNS, TNS,
endpoints restringidos y utilización LUT/FF/BRAM/URAM.

`synth_check.py` solo demuestra coherencia estática entre RTL, Tcl y XDC. La
latencia de 44,318 ciclos es una medición de simulación; convertirla usando el
periodo objetivo no acredita que el dispositivo alcance 322,265625 MHz.

## Entorno reproducido

```text
fecha: 2026-08-15T14:58:46+01:00
Python 3.11.14; cocotb 2.0.1
Verilator 5.050 2026-07-01; GNU Make 3.81
verible-verilog-lint: no instalado
vivado: no instalado
/tmp/real_subset.pcap: 91 paquetes, 3000 mensajes
/tmp/real_trading.pcap: 3222 paquetes, 150000 mensajes
```

## Gates A–G

| Gate | Evidencia fresca del loop `tkeep` | Resultado |
|---|---|---|
| A — simulación | golden 37/37; parser32 5/5; chain ND=5 4/4; chain ND=3 4/4; latencia 1/1; todos con `FAIL=0 SKIP=0` | **PASS** |
| B — compilación | lint `--Wall` de parser DW32 y `itch_chain` DW32 con dependencias, exit 0 y cero warnings | **PASS** |
| C — estilo | `verible-verilog-lint` no instalado | **NO EJECUTADO** |
| D — cobertura | P32-01/02, CHAIN-01 y DP-01 cubiertos; frontera `tkeep` multi-datagrama en parser/cadena; cobertura instrumental no configurada | **PASS nivel 1** |
| E — mutación | delta de entrada heredado del parser: 19/19 mutantes compilables y muertos; no se presenta la mutación histórica del order book como fresca | **PASS para el delta `tkeep`** |
| F — completitud | script literal de unicidad/presencia de IDs y espejos, exit 0 | **PASS** |
| G — rigor/timing | pcaps fuera de Git, golden independiente, `synth_check.py` 22/22 estático; sin Vivado WNS/TNS/utilización | **ABIERTO** |

## Gate A — salida fresca desde builds limpios

```text
$ make -C verification/testbenches/phase3 clean-all
$ make -C verification/testbenches/phase3 sim-parser
P32-03 OK: 91 paquetes, 26904 words de 32 bits bit a bit
TESTS=5 PASS=5 FAIL=0 SKIP=0
exit 0

$ make -C verification/testbenches/phase3 clean-all
$ make -C verification/testbenches/phase3 sim-chain
CHAIN-01: 31400 msgs / 20 símbolos contra golden
CHAIN-01 OK: 30729 eventos, cross=0, anomaly=671, gaps=0
TESTS=4 PASS=4 FAIL=0 SKIP=0
exit 0

$ make -C verification/testbenches/phase3 clean-all
$ make -C verification/testbenches/phase3 sim-chain-nd3
CHAIN-01 OK: 30729 eventos, cross=0, anomaly=671, gaps=0
TESTS=4 PASS=4 FAIL=0 SKIP=0
exit 0

$ make -C verification/testbenches/phase3 clean-all
$ make -C verification/testbenches/phase3 sim-lat
SEC-LAT-01 OK: 30729 eventos, dos ejecuciones idénticas
TESTS=1 PASS=1 FAIL=0 SKIP=0
exit 0
```

### Frontera real de `tlast`

- P32-03 conserva los 91 payloads reales de `/tmp/real_subset.pcap`; el
  assert `accepted_tlast == len(payloads)` verificó **91 handshakes `tlast`**.
- CHAIN-01 filtra el pcap de trading a 20 símbolos y reconstruye esos 31.400
  mensajes en **un** payload MoldUDP64 para el subset; su driver verificó
  **1 handshake `tlast`**. No se presenta ese único burst como preservación
  de los 3.222 límites originales del pcap.
- `test_chain_tkeep_datagramas_no_alineados_y_estabilidad` usa dos payloads
  sintéticos no múltiplos de cuatro, fuerza backpressure y verificó **2
  handshakes `tlast`**, `tkeep` y estabilidad de la fuente en la cadena.

Esta separación evita convertir el replay filtrado de cadena en una evidencia
que no produce: los límites reales los pinza P32-03; la integración
multi-datagrama la pinza el adversarial de cadena.

### Latencia de simulación

```text
eventos=30729; mean=44.318 ciclos; p50=44; p99=61; min=32; max=74
A mean=48.660; D mean=41.189; E mean=40.857;
U mean=55.408; X mean=39.402
```

El test hizo warm-up de invalidación URAM y dos ejecuciones idénticas sobre
el subset real. Es latencia desde el handshake de la word que contiene el
primer byte del mensaje hasta el evento BBO en simulación.

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

Los 22 checks incluyen periodo XDC de 3,103 ns, puertos/delays min-max,
lectura registrada de `o_mem` y comandos de informes/aborto del Tcl. No
ejecutan síntesis, place ni route.

## Gates D/E/F

| ID | Test/evidencia vigente |
|---|---|
| P32-01 | `test_p32_01_anexo_a_32_bits`, P32-03 real y validación `tkeep`/truncados |
| P32-02 | `test_p32_02_peor_caso_una_palabra_ciclo` |
| CHAIN-01 | `test_chain01_feed_real_bit_a_bit`, `test_chain02_sintetico_bit_a_bit` |
| DP-01 | `test_dp01_nd_parametrizado_llega_al_book`, ejecutado con ND=5 y ND=3 |

```text
$ python3 scripts/verify/mutate_parser.py
19/19 killed; cada mutante compiló; 0 supervivientes; 0 mutantes rotos
19/19 mutantes compilables y muertos. Gate E PASS.
exit 0

$ python3 - <<'PY'  # script literal del brief
IDs ITCH/fase 3 únicos y mapas a tests completos
exit 0
```

La mutación 19/19 cierra el delta compartido de framing. En este loop no se
ejecutó `mutate_orderbook.py`; sus resultados anteriores no se etiquetan como
frescos ni se usan para cerrar el gate físico.

## Bloqueador físico

No se encontraron `vivado`, `timing_impl.txt` ni `util_impl.txt` producidos
por un run vigente. Para cerrar fase 3 siguen siendo obligatorios, como mínimo:

- WNS y TNS post-route;
- endpoints sin constraint y clocking efectivo;
- utilización LUT/FF/BRAM/URAM e inferencia real de URAM;
- confirmación de que los budgets I/O del XDC corresponden al wrapper/PHY.

Hasta adjuntar esa evidencia, **fase 3 permanece NO CERRADA**.
