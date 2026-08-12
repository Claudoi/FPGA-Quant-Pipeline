# language: es
Característica: Order book del golden model
  El book mantiene por simbolo la tabla de ordenes vivas (por order
  reference), los niveles de precio agregados y el BBO. Es la semantica de
  referencia que el RTL de la fase 2 debera reproducir bit a bit.

  Escenario: LIB-01 add order crea nivel y actualiza BBO
    Dado un libro vacio para el simbolo de prueba
    Cuando llega un mensaje A de compra a precio 1000000 y cantidad 100
    Entonces el BBO del simbolo es bid 1000000 x100, ask 0 x0
    Y el flag de cambio del registro emitido es 1

  Escenario: LIB-02 execute parcial reduce cantidad sin mover el BBO en precio
    Dado un libro con una orden de compra de 100 a precio 1000000 como mejor bid
    Cuando llega un mensaje E de 40 sobre esa orden
    Entonces el BBO es bid 1000000 x60
    Y la orden sigue viva con cantidad restante 60

  Escenario: LIB-03 execute total elimina la orden y retrae el BBO
    Dado un libro con una unica orden de compra de 100 a precio 1000000
    Cuando llega un mensaje E de 100 sobre esa orden
    Entonces la orden deja de existir
    Y el BBO pasa a bid 0 x0

  Escenario: LIB-04 cancel y delete mantienen niveles consistentes
    Dado un libro con dos ordenes de venta al mismo precio 2000000 por 50 y 70
    Cuando llega un X de 30 sobre la primera y un D sobre la segunda
    Entonces el nivel ask 2000000 queda con cantidad 20
    Y tras un X de 20 sobre la primera el nivel 2000000 desaparece

  Escenario: LIB-05 replace es atomico y emite un solo estado resultante
    Dado un libro con una orden de compra de 100 a precio 1000000 como mejor bid
    Cuando llega un mensaje U que la reemplaza por precio 990000 y cantidad 200
    Entonces el BBO resultante es bid 990000 x200
    Y solo se emite un registro para el mensaje U
    Y la referencia original deja de existir y la nueva queda viva

  Escenario: LIB-06 libro vacio emite BBO cero
    Dado un libro cuyas ordenes han sido todas eliminadas
    Cuando se emite el registro del ultimo mensaje modificador
    Entonces bid y ask valen precio 0 y cantidad 0

  Escenario: SEC-04 operacion sobre order reference desconocida se cuenta como anomalia
    Dado un libro en curso
    Cuando llega un E, X, D o U sobre una referencia inexistente
    Entonces la operacion se salta sin modificar el libro
    Y el contador de anomalias se incrementa
    Y el run no aborta

  Escenario: SEC-05 libro cruzado en estado de subasta no dispara la invariante
    Dado un simbolo en estado de trading distinto de continuo segun mensajes S y H
    Cuando el mejor bid supera al mejor ask por ordenes cruzadas en subasta
    Entonces el run continua sin violacion de invariante
    Y el BBO se emite tal cual

  Escenario: INV-01 invariantes del libro se chequean mensaje a mensaje
    Dado un run con invariantes activas en modo estricto
    Cuando cualquier mensaje dejara cantidades no positivas, referencias duplicadas, niveles inconsistentes o libro cerrado/cruzado en trading continuo
    Entonces el run aborta indicando la invariante violada y el indice del mensaje

  Escenario: SEC-08 libro bloqueado en trading continuo en datos reales se cuenta, no aborta
    Dado un libro en modo por defecto (no estricto)
    Y un simbolo cuyo libro quedo bloqueado durante un halt y reanudo trading
    Cuando llega el siguiente mensaje modificador de ese simbolo
    Entonces el run no aborta
    Y el evento de cruce se cuenta con su indice de mensaje
