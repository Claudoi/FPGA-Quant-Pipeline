# Contrato AXI de bytes válidos para framing UDP

**Fecha:** 2026-08-15

**Estado:** diseño aprobado; implementación pendiente

**Campañas afectadas:** fase 1 ITCH, integración de fase 3 y fase 4 MDP3

## Problema

Los parsers reciben payloads UDP ya decapsulados mediante
`s_axis_tdata/tvalid/tready/tlast`, pero la interfaz no indica cuántos bytes de
la última palabra son válidos. Los testbenches ITCH ocultaban esa ausencia
concatenando datagramas antes de formar palabras: una misma transferencia podía
contener el final del paquete N y el principio del N+1 mientras `tlast`
pretendía delimitar N. Esa transferencia no es representable en AXI-Stream,
donde `tlast` califica el beat completo.

Con palabras reales y relleno al final del burst, el parser ITCH conserva esos
bytes delante de la siguiente cabecera. En MDP3, el relleno puede satisfacer
falsamente `msg_size` cuando al mensaje truncado le faltan menos de `DW/8`
bytes. El pcap ITCH local que motivó la revisión contiene 91 payloads y ninguno
está alineado a 8 bytes, por lo que el borde es parte del flujo real.

## Decisión

Los tops de entrada de red adoptan `s_axis_tkeep[DW/8-1:0]` con semántica AXI
estándar. No se introduce un byte-count propio y no se cambia la interfaz
interna parser→order book.

Cada bit califica su lane convencional:

```text
s_axis_tkeep[k] == 1  =>  s_axis_tdata[8*k +: 8] es válido
```

El payload se presenta MSB-first. Por tanto, los bytes válidos de una palabra
parcial forman un prefijo desde el MSB. En DW=64, cuatro bytes válidos se
representan con `tkeep=8'b11110000`; en DW=32, con `tkeep=4'b1111` si la palabra
es completa o `4'b1100` si contiene dos bytes.

## Contrato de handshake

- Una transferencia ocurre solo con `s_axis_tvalid && s_axis_tready`.
- `s_axis_tdata`, `s_axis_tkeep` y `s_axis_tlast` permanecen estables durante
  cualquier ciclo de backpressure de entrada.
- Todo beat no final usa `tkeep={DW/8{1'b1}}`.
- El beat final usa un prefijo MSB contiguo de unos seguido de ceros.
- `tkeep==0`, una máscara con huecos o una palabra parcial sin `tlast` son
  framing inválido: pulso `error` y descarte del datagrama actual. Si el beat
  inválido lleva `tlast`, el parser puede aceptar un datagrama nuevo de
  inmediato; si no, drena entradas hasta aceptar el `tlast` que lo cierra.
- Los bytes con `tkeep=0` nunca se incorporan a la cola ni cuentan para
  `msg_size`, cabeceras o longitudes ITCH.
- Un productor que siempre entrega palabras completas puede fijar `tkeep` a
  todo unos; no se añade compatibilidad implícita con un puerto ausente.

## Cambios por componente

### `itch_parser`

- Añade `s_axis_tkeep` al puerto de entrada.
- Compacta en orden de stream únicamente los bytes marcados como válidos.
- Incrementa `qn` por el número de bytes válidos, no por `DW/8`.
- Latcha fin de paquete solo al aceptar un beat con `tlast`.
- Al completar el `count` exige el cierre del mismo datagrama; nunca reutiliza
  relleno para la cabecera siguiente.
- Ante truncado o máscara inválida descarta el paquete actual, preserva el
  `msg_idx` de mensajes ya cerrados y espera un datagrama nuevo.

El formato Anexo A y los puertos de salida no cambian.

### `itch_chain`

- Añade `s_axis_tkeep` a su entrada pública y lo conecta a `itch_parser`.
- No añade `tkeep` al enlace parser→order book: el Anexo A emite palabras
  completas y su relleno es parte definida del record normalizado.
- El XDC de fase 3 debe incluir delays min/max para `s_axis_tkeep[*]`.

### `mdp3_parser`

- Añade `s_axis_tkeep` al puerto de entrada.
- `qavail_eff` y los punteros avanzan por bytes válidos.
- Un `msg_size` no puede completarse con lanes cuyo `tkeep` está a cero.
- Si `tlast` llega antes de reunir el mensaje declarado, pulsa `error`, vacía el
  estado de captura del paquete y acepta un paquete posterior íntegro.

El schema, los buffers ping-pong, el límite `MAX_MSG`, el selector de templates
y el Anexo M no cambian en esta campaña. Sus hallazgos tienen loops separados.

## Drivers y oráculo

Los drivers producen una lista de beats `(data, keep, last)` por datagrama. Un
paquete se divide y rellena antes de comenzar el siguiente; nunca se concatenan
bytes a través de `tlast`.

El replay real conserva la lista de payloads que devuelve el decapsulador y
emite un burst por payload. La evidencia debe comprobar que el número de
handshakes con `tlast` coincide con el número de paquetes procesados.

Los helpers compartidos se reutilizan entre ITCH DW=64, parser DW=32 y cadena
DW=32. MDP3 puede conservar su helper de área si aplica exactamente el mismo
contrato de máscaras.

## Matriz roja obligatoria

| ID | Caso | Propiedad observable |
|---|---|---|
| AXI-KEEP-01 | Dos paquetes ITCH no alineados, DW=64 | dos `tlast`, headers y salida correctos |
| AXI-KEEP-02 | `count=0` de 20 B seguido de paquete válido | sin gap/error y sin padding en header |
| AXI-KEEP-03 | Cadena ITCH DW=32 con paquetes no alineados | BBO/depth bit a bit vs golden |
| AXI-KEEP-04 | Replay ITCH real | un burst por payload; salida bit a bit |
| AXI-KEEP-05 | MDP3 DW=32 truncado por 1..3 B | `error`, sin record parcial, recuperación |
| AXI-KEEP-06 | MDP3 DW=64 truncado por 1..7 B | misma propiedad |
| AXI-KEEP-07 | Máscara con huecos o parcial sin `tlast` | `error`, descarte y recuperación |
| AXI-KEEP-08 | Backpressure de entrada | data/keep/last estables hasta handshake |

Cada test debe observar primero un rojo causado por el puerto o por el
comportamiento ausente. Un error de compilación por puerto inexistente es rojo
válido solo para el primer test de interfaz; los tests funcionales posteriores
deben fallar por salida, error o recuperación incorrectos.

## Gates y cierre

La campaña no se cierra hasta ejecutar desde builds limpios:

1. parser ITCH DW=64;
2. parser ITCH DW=32;
3. cadena DW=32, incluida ND=3;
4. replay real si el pcap local está presente; en otro caso, SKIP explícito;
5. MDP3 DW=32 y DW=64;
6. lint Verilator `--Wall` de ambos parsers y `itch_chain`;
7. mutación del framing aplicable;
8. `synth_check.py` con el nuevo puerto cubierto por XDC;
9. completitud Gherkin y `git diff --check`.

Los verify-report deben pegar los outputs nuevos y sustituir, no acumular como
vigente, la evidencia obtenida con los drivers que concatenaban datagramas.

## Fuera de alcance

- Añadir MAC 10G o decap Ethernet/IP/UDP.
- Añadir `tkeep` a la salida normalizada de los parsers.
- Corregir `schemaId/version` o `MAX_MSG` de MDP3.
- Probar el backpressure de salida MDP3.
- Cerrar timing de fase 3 sin Vivado.
- Refactorizar el order book.
