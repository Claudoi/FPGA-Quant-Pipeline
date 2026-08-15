# orderbook.feature — order book engine: aplicación de mensajes y BBO

Espejo de «Criterios de aceptación» 1-8 de `spec.md` de fase2-orderbook.
La semántica de cada operación es EXACTAMENTE la de `golden_model/src/book.py`.

#language: es
Funcionalidad: Aplicación de mensajes Anexo A al order book y emisión de BBO
  Como pipeline de market data
  Quiero que el engine mantenga órdenes, niveles y BBO por símbolo
  Para que el BBO sea bit a bit idéntico al golden model

Escenario: BBO-01 — una secuencia de add/execute/cancel/delete produce el BBO del golden
  Dado un stream de registros Anexo A de tipos modificadores (A, F, E, C, X, D, U)
  Cuando el order book aplica cada mensaje
  Entonces el BBO emitido por símbolo es bit a bit idéntico al golden book.py
  Y la señal changed coincide con el evento del golden

Escenario: BBO-02 — un símbolo vacío queda aislado y un lado vacío emite (0,0)
  Dado un símbolo sin ninguna orden y otro símbolo con una orden bid
  Cuando el book procesa únicamente el mensaje del segundo símbolo
  Entonces el ask vacío del símbolo activo es (0,0)
  Y no se emite ningún evento para el símbolo que permanece vacío

Escenario: SEC-U-01 — el replace U es atómico sin ventana de inconsistencia
  Dado un símbolo con una orden viva y un BBO no vacío
  Cuando el book procesa un mensaje U (delete+add de un solo estado)
  Entonces el BBO emitido es el del estado final del U
  Y nunca se observa un BBO intermedio con la orden ausente

Escenario: SEC-HZ-01 — add seguido de execute sobre la misma orden (RAW)
  Dado un add A y a continuación un execute E sobre la misma order_ref
  Cuando el book procesa la secuencia
  Entonces el segundo mensaje ve el estado del primero
  Y el BBO resultante coincide con el golden

Escenario: SEC-HZ-02 — replace seguido de execute sobre la nueva referencia (RAW)
  Dado un U que crea una nueva ref y a continuación un E sobre esa ref
  Cuando el book procesa la secuencia
  Entonces el execute actúa sobre la orden reemplazada
  Y el BBO resultante coincide con el golden

Escenario: SEC-DC-01 — execute/cancel/delete no descuentan dos veces
  Dado una orden con cantidad conocida y un nivel con esa cantidad
  Cuando el book aplica un execute y luego un cancel sobre el resto
  Entonces la cantidad total descontada es exactamente la inicial
  Y el nivel queda consistente con el golden

Escenario: SEC-OV-01 — desbordamiento de cantidades se señaliza con error
  Dado un mensaje que reduciría una orden por debajo de su cantidad viva
  Cuando el book lo aplica y después recibe un add válido
  Entonces señaliza error durante al menos un ciclo
  Y no produce un BBO para la operación inválida ni envuelve silenciosamente
  Y procesa el add válido posterior

Escenario: SEC-AN-01 — operación sobre ref desconocida cuenta anomalía sin abortar
  Dado un execute/cancel/delete/replace cuya order_ref no está en el libro
  Cuando el book lo aplica
  Entonces incrementa anomaly_count
  Y continúa procesando el siguiente mensaje sin abortar el stream

Escenario: SEC-CR-01 — libro cruzado en trading continuo cuenta cross_events
  Dado un símbolo en trading continuo donde tras un mensaje bid >= ask
  Cuando el book aplica el mensaje
  Entonces incrementa cross_events
  Y no aborta el stream (equivale a strict_cross=False del golden)

Escenario: MULTI-01 — mensajes de distintos símbolos mantienen libros independientes
  Dado un stream con mensajes de 2 o más locates del subset intercalados
  Cuando el book aplica la secuencia
  Entonces cada símbolo conserva su propio BBO
  Y el BBO de cada símbolo coincide con el golden aplicado por separado

Escenario: REPLAY-01 — el BBO del feed real es idéntico al golden
  Dado el día local data/itch_sample/12302019… decapado (parser → book)
  Cuando el book procesa los mensajes del subset
  Entonces la secuencia de BBO es bit a bit idéntica al golden book.py

Escenario: REPLAY-02 — los vectores congelados de BBO se reproducen
  Dado un vector congelado de BBO en verification/vectors/bbo/
  Cuando el book procesa el feed sintético que lo originó
  Entonces su salida de BBO es bit a bit idéntica al vector congelado
