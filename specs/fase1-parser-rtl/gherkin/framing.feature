# framing.feature — framing MoldUDP64, secuencia y detección de gaps

Espejo de «Criterios de aceptación» 4 de `spec.md`.

#language: es
Funcionalidad: Framing MoldUDP64 y detección de gaps de secuencia
  Como pipeline de market data
  Quiero que el parser valide sesión, seq y count y detecte gaps de secuencia
  Para manejar el feed real de MoldUDP64 sin perder mensajes

Escenario: FRM-01 — el parser extrae sesión, seq y count de cada payload MoldUDP64
  Dado un payload MoldUDP64 con una sesión, un sequence number y una cuenta de mensajes
  Cuando el RTL procesa la cabecera de framing
  Entonces extrae la sesión, el seq y el count correctamente
  Y emite los mensajes de ese paquete en orden

#language: es
Escenario: FRM-02 — el seq esperado avanza como seq_prev más count_prev
  Dado una secuencia de paquetes cuyos seq son consecutivos según el count previo
  Cuando el RTL procesa la secuencia
  Entonces el seq esperado del paquete n es seq del paquete n-1 más su count
  Y no señaliza ningún gap

#language: es
Escenario: SEC-GAP-01 — un hueco de secuencia se señaliza, se cuenta y el parsing continúa
  Dado una secuencia de paquetes donde seq_actual es mayor que el esperado
  Cuando el RTL procesa el paquete con hueco
  Entonces señaliza gap_detected y lo cuenta internamente
  Y continúa procesando los mensajes del paquete sin abortar

#language: es
Escenario: SEC-GAP-02 — un seq igual al esperado no señaliza gap
  Dado una secuencia de paquetes consecutivos sin huecos
  Cuando el RTL procesa cada paquete
  Entonces no señaliza ningún gap_detected

#language: es
Escenario: SEC-FRM-03 — un cambio de sesión resetea el seq esperado
  Dado un payload cuya sesión difiere del paquete anterior
  Cuando el RTL procesa el cambio de sesión
  Entonces reinicia el estado de secuencia esperada al primer seq de la nueva sesión
  Y no cuenta el reinicio como gap

#language: es
Escenario: SEC-FRM-04 — un paquete con count igual a cero es válido
  Dado una sesión nueva con seq 100 y cuenta de mensajes cero
  Y el payload de 20 bytes termina con cuatro lanes válidos en su último beat
  Cuando el siguiente paquete de la misma sesión llega en un burst nuevo también con seq 100
  Entonces no emite ningún registro y no señaliza error
  Y no señaliza gap porque el seq esperado avanzó por cero

#language: es
Escenario: SEC-FRM-05 — datagramas no alineados no comparten una palabra AXI
  Dado dos payloads MoldUDP64 consecutivos cuyas longitudes no son múltiplos de ocho
  Y cada payload usa su propio tlast y tkeep en la última palabra
  Cuando el RTL procesa ambos bursts
  Entonces extrae ambas cabeceras sin incorporar padding entre ellas
  Y la salida completa coincide byte a byte con el golden

#language: es
Escenario: SEC-FRM-06 — una máscara tkeep inválida se descarta con señal
  Dado un beat con tkeep cero, con huecos o parcial sin tlast
  Cuando el RTL acepta el beat y después recibe un paquete íntegro
  Entonces pulsa error y descarta el datagrama inválido
  Y procesa el paquete posterior sin estado ni cabecera corruptos
