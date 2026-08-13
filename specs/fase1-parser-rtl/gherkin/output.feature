# output.feature — interfaz AXI-Stream de salida

Espejo de «Criterios de aceptación» 1 y 5 de `spec.md`.

#language: es
Funcionalidad: Interfaz AXI-Stream de salida con backpressure
  Como pipeline de market data
  Quiero que la salida AXI-Stream respete tvalid/tready/tlast y pueda retenerse
  Para que el downstream (order book) pueda backpressurear sin pérdida

Escenario: OUT-01 — cada mensaje decodificado se emite como un burst con tlast al final
  Dado un stream de mensajes del subset de distintos tipos
  Cuando el RTL emite la salida
  Entonces cada registro comienza con tvalid alta y termina con tlast
  Y el número de palabras del burst coincide con el tipo del mensaje

#language: es
Escenario: OUT-02 — con tready bajo el parser retiene el stream sin pérdida ni duplicado
  Dado un downstream que intermitentemente baja tready
  Cuando el RTL procesa el stream
  Entonces la salida final contiene el mismo burst de registros que el oráculo
  Y ningún registro se pierde ni se duplica

#language: es
Escenario: OUT-03 — el handshake tvalid/tready solo avanza cuando ambos están altos
  Dado un downstream con tready no constante
  Cuando el RTL hace el handshake de salida
  Entonces los datos solo avanzan en ciclos con tvalid y tready altos
  Y los datos no cambian mientras tvalid está alto y tready bajo
