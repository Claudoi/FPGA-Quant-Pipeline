# language: es
Característica: Parser ITCH 5.0 sobre BinaryFILE
  El parser del golden model itera ficheros BinaryFILE de emi.nasdaq.com,
  valida todos los tipos de mensaje ITCH 5.0 por longitud, decodifica la
  cabecera común en todos y los campos completos del subset del libro
  (A/F/E/C/X/D/U) mas R, S y H. Es la puerta de entrada de todos los datos
  reales del proyecto.

  Escenario: PAR-01 iterar un BinaryFILE completo sin errores
    Dado el BinaryFILE del dia principal descargado y verificado con md5
    Cuando el parser itera el fichero completo
    Entonces consume todos los mensajes sin excepciones
    Y el ultimo mensaje procesado tiene indice igual al total menos uno

  Escenario: PAR-02 conteo por tipo de mensaje del dia real
    Dado el BinaryFILE del dia principal
    Cuando el parser itera el fichero completo
    Entonces emite una tabla de conteo por tipo de mensaje
    Y la suma de los conteos es igual al total de mensajes del fichero
    Y los tipos del subset del libro tienen conteos mayores que cero

  Esquema del escenario: PAR-03 decodifica campos completos del subset <tipo>
    Dado un mensaje sintetico de tipo <tipo> escrito como literal hex desde la spec PDF
    Cuando el parser lo decodifica
    Entonces cada campo extraido coincide con el valor esperado <campos>

    Ejemplos:
      | tipo | campos                                          |
      | A    | locate, tracking, timestamp, ref, lado, qty, symbol, precio |
      | F    | locate, tracking, timestamp, ref, lado, qty, symbol, precio, attribution |
      | E    | locate, tracking, timestamp, ref, qty_ejecutada, match_id   |
      | C    | locate, tracking, timestamp, ref, qty_ejecutada, match_id, printable, precio |
      | X    | locate, tracking, timestamp, ref, qty_cancelada             |
      | D    | locate, tracking, timestamp, ref                            |
      | U    | locate, tracking, timestamp, ref_original, ref_nueva, qty, precio |
      | R    | locate, tracking, timestamp, symbol, categoria de mercado   |
      | S    | tracking, timestamp, codigo de evento                       |
      | H    | locate, tracking, timestamp, estado de trading              |

  Escenario: SEC-01 tipo de mensaje desconocido es error duro
    Dado un stream BinaryFILE con un mensaje de tipo no definido en ITCH 5.0
    Cuando el parser lo alcanza
    Entonces lanza una excepcion que indica el tipo y el indice del mensaje

  Escenario: SEC-02 longitud incorrecta para el tipo es error duro
    Dado un stream BinaryFILE cuyo mensaje de tipo A declara una longitud distinta de la especificada
    Cuando el parser lo alcanza
    Entonces lanza una excepcion que indica la longitud declarada, la esperada y el indice del mensaje

  Escenario: SEC-03 mensaje truncado al final del fichero es error duro
    Dado un stream BinaryFILE cuyo ultimo mensaje declara mas bytes de los que quedan
    Cuando el parser lo alcanza
    Entonces lanza una excepcion de mensaje truncado con el indice del mensaje
