# parser.feature — decodificación de mensajes del subset + manejo de tipos y longitudes

Espejo funcional de «Criterios de aceptación» 1, 6, 7 de `spec.md`.

#language: es
Funcionalidad: Decodificación de mensajes ITCH del subset y manejo de tipos/longitudes
  Como pipeline de market data
  Quiero que el parser decodifique los 10 tipos del subset a registros normalizados
  y que valide tipos/longitudes sin romper el line rate
  Para alimentar byte a byte el order book (fase 2)

Escenario: PAR-01 — cada tipo del subset se decodifica a un registro byte a byte idéntico al golden
  Dado un mensaje del subset de tipo T de {S, R, A, F, E, C, X, D, U, P} en un pcap sintético
  Y el oráculo --emit-messages del golden model sobre el mismo pcap
  Cuando el RTL procesa el stream de entrada
  Entonces la salida del parser es byte a byte idéntica al oráculo para ese mensaje
  Y el registro emite tlast al final del burst y msg_type coincide

#language: es
Escenario: SEC-PAR-04 — un tipo fuera del subset se valida por longitud y se cuenta sin emitir registro
  Dado un pcap sintético que contiene un mensaje de tipo H (fuera del subset) entre mensajes del subset
  Cuando el RTL procesa el stream
  Entonces no emite ningún registro para el mensaje H
  Y cuenta el mensaje y continúa sin romper el line rate
  Y el contador de mensajes por tipo incluye H

#language: es
Escenario: SEC-PAR-03 — una longitud declarada incoherente cancela el mensaje con error y continúa
  Dado un stream de entrada que contiene un mensaje cuya longitud declarada no coincide con los bytes disponibles
  Cuando el RTL procesa el stream
  Entonces señaliza error y descarta el registro de ese mensaje
  Y continúa procesando el siguiente mensaje sin abortar el stream

#language: es
Escenario: SEC-FRM-01 — un frame truncado señaliza error y el parser continúa en el siguiente mensaje
  Dado un pcap sintético cuyo payload termina a mitad de un mensaje sin los bytes declarados
  Cuando el RTL procesa el stream
  Entonces señaliza error en el mensaje truncado
  Y continúa con el siguiente paquete/mensaje íntegro sin abortar

#language: es
Escenario: SEC-FRM-02 — un mensaje no puede partirse entre paquetes y se gestiona con firmeza
  Dado un stream donde tlast llega en medio de un mensaje (count inconsistente con el cierre del paquete)
  Cuando el RTL procesa el stream
  Entonces señaliza error y no emite un registro parcial
  Y reinicia el estado de parsing para el siguiente paquete
