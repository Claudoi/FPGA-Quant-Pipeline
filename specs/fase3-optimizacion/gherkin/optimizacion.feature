# optimizacion.feature — fase 3: variante 32-bit @ 322 MHz, URAM con hash, top-N

Espejo de «Criterios de aceptación» 1-11 de `spec.md` de fase3-optimizacion.
La semántica de cada operación es EXACTAMENTE la de `golden_model/src/book.py`
y `golden_model/itch/messages.py` (fases 0-2).

#language: es
Funcionalidad: Pipeline 32-bit @ 322 MHz con tabla URAM hashada y top-N público
  Como pipeline de market data a line-rate 10G
  Quiero que el parser y el book funcionen a datapath de 32 bits
  Para que el diseño cierre timing a 322,265625 MHz con la tabla en URAM

  Escenario: P32-01 — el parser a DW=32 emite el Anexo A de 32 bits bit a bit
    Dado el corpus sintético de la fase 1
    Cuando el parser de 32 bits procesa cada mensaje
    Entonces las words de salida (w0 context, w1 idx, w2.. cuerpo, sin ts —
      layout recortado de fase3-uram) coinciden bit a bit con el oráculo message_oracle

  Escenario: P32-02 — el parser a DW=32 acepta el peor caso a 1 palabra/ciclo
    Dado un flujo de mensajes mínimos back-to-back
    Cuando el parser de 32 bits los procesa
    Entonces no hay backpressure sostenida de entrada
    Y no se pierde ningún mensaje

  Escenario: B32-01 — el book a DW=32 emite el BBO del golden bit a bit
    Dado el corpus sintético de la fase 2 (A/F/E/C/X/D/U/S/H)
    Cuando el book de 32 bits aplica cada mensaje
    Entonces el BBO emitido por símbolo es bit a bit idéntico al golden book.py

  Escenario: B32-02 — el book a DW=32 reproduce el feed real del subset
    Dado el pcap del día local decapado (20 símbolos)
    Cuando el book de 32 bits procesa los mensajes del subset
    Entonces la secuencia de BBO es bit a bit idéntica al golden book.py

  Escenario: REG-01 — la regresión de 64 bits sigue verde tras parametrizar
    Dado el RTL extendido con DW parametrizado (default 64)
    Cuando se re-ejecutan las suites de fase 1 y fase 2
    Entonces todos los tests siguen pasando sin cambios

  Escenario: CHAIN-01 — la cadena parser→book a DW=32 es bit a bit
    Dado el feed real decapado (parser 32 → book 32, sin re-parseo)
    Cuando la cadena procesa el subset
    Entonces la secuencia de BBO es bit a bit idéntica al golden book.py

  Escenario: SEC-HASH-01 — el probe agotado cuenta anomalía sin abortar
    Dado una order_ref cuyo slot es el mismo tras PROBE pasos
    Cuando el book busca esa ref
    Entonces cuenta anomaly_count
    Y continúa procesando el siguiente mensaje

  Escenario: SEC-HASH-02 — la tabla de órdenes llena se señaliza con error
    Dado que todos los slots están ocupados
    Cuando llega un add de una ref nueva
    Entonces señaliza error
    Y no sobrescribe ni envuelve silenciosamente

  Escenario: SEC-HASH-03 — colisiones de hash de símbolos distintos se resuelven
    Dado dos refs de símbolos distintos con el mismo slot base
    Cuando el book las procesa
    Entonces cada operación actúa sobre su propia orden
    Y el BBO de cada símbolo coincide con el golden

  Escenario: SEC-NSYM-01 — el símbolo 21 señala error sin índice fuera de rango
    Dado un locate fuera del subset de NSYM=20
    Cuando llega un mensaje de ese símbolo
    Entonces señaliza error
    Y el índice interno del símbolo permanece menor que NSYM en todo ciclo
    Y no corrompe los niveles de los símbolos registrados

  Escenario: SEC-BP-01 — el BBO se retiene bajo backpressure sin perderse
    Dado un consumidor que baja bbo_tready después de observar bbo_tvalid
    Cuando mantiene el stall durante dos ciclos completos
    Entonces bbo_tvalid y el payload permanecen estables hasta que tready sube
    Y se entrega exactamente una vez, sin pérdida ni duplicado

  Escenario: SEC-DP-01 — depth de un símbolo vacío es todo ceros
    Dado un símbolo sin ninguna orden
    Cuando el book emite su depth
    Entonces depth_tdata es 0 en todos los niveles

  Escenario: DP-01 — el top-N público es bit a bit igual a los niveles del golden
    Dado un símbolo con ND niveles o más por lado
    Cuando el book emite un evento de ese símbolo
    Entonces depth_tdata contiene los ND mejores niveles por lado, mejor primero
    Y una elaboración de itch_chain con ND=3 produce exactamente 384 bits
    Y coincide bit a bit con los niveles ordenados del golden book.py

  Escenario: SEC-LAT-01 — la latencia por tipo es determinista y reproducible
    Dado la cadena parser→book a DW=32 sobre una secuencia fija
    Cuando se mide la latencia wire→BBO por tipo de mensaje
    Entonces la re-ejecución produce el histograma idéntico

  # --- iteración 7 (2026-08-18): retiming del escaneo de niveles ----------
  # Addendum iteración 7 de spec.md. El ST_EMIT de un solo ciclo se divide en
  # ST_EMIT_A (captura) / ST_EMIT_B (selección+changed+depth) / ST_EMIT_C
  # (handshake) — +2 ciclos en el camino del evento, latencia re-derivada.

  Escenario: RTM-01 — el escaneo de niveles del BBO/depth está registrado en etapas
    Dado el book con ST_EMIT pipelined (etapas A/B/C)
    Cuando se procesa un evento de update
    Entonces la captura de niveles del símbolo es un registro (verificada con sonda interna)
    Y el find-first por lado opera sobre la captura, no sobre los arrays de niveles
    Y el payload emitido es bit a bit idéntico al golden book.py

  Escenario: RTM-02 — el BBO del evento pipelined es consistente con la captura
    Dado un símbolo con niveles en los slots 0..k-1 y vacíos después (invariante
      de lista ordenada: el mejor nivel vive en el primer slot no vacío)
    Cuando el book emite un evento de ese símbolo por el pipeline A/B/C
    Entonces el BBO es el primer nivel no vacío de la captura (slot 0 si hay niveles)
    Y los ND primeros niveles de la captura coinciden con depth_tdata
    Y un símbolo sin niveles emite BBO a cero, changed a 0 y depth a cero

  Escenario: RTM-03 — changed se calcula sobre la captura y no se pierde
    Dado dos eventos consecutivos idénticos para el mismo símbolo
    Cuando el segundo se emite
    Entonces bbo_changed vale 0 en el segundo
    Y un evento con cambio distinto vale 1

  Escenario: RTM-04 — el handshake de salida retiene el evento pipelined
    Dado un consumidor que baja bbo_tready tras observar bbo_tvalid
    Cuando el evento proviene del pipeline de etapas A/B/C
    Entonces bbo_tvalid y el payload permanecen estables hasta que tready sube
    Y se entrega exactamente una vez, sin pérdida ni duplicado

  Escenario: RTM-LAT-01 — la latencia re-medida cumple el umbral re-derivado
    Dado la cadena parser→book a DW=32 sobre la secuencia fija de latencia
    Cuando se mide la latencia wire→BBO por tipo de mensaje tras el pipeline
    Entonces la media total es ≤ 48 ciclos
    Y la re-ejecución produce el histograma idéntico

  Escenario: RTM-REG-01 — la regresión de 64 bits sigue verde con el pipeline
    Dado el book pipelined con DW=64 (default)
    Cuando se re-ejecutan las suites de fase 1 y fase 2
    Entonces todos los tests siguen pasando sin cambios
