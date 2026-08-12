# language: es
Característica: Vectores de referencia para el RTL
  Los vectores son el contrato bit a bit contra el que se verificara el RTL
  en las fases 1-2: un registro binario de 40 bytes por mensaje modificador
  de los simbolos del subset, mas un volcado a texto para inspeccion.

  Escenario: VEC-01 un registro por mensaje modificador del subset con flag de cambio
    Dado un run sobre datos sinteticos con mensajes del subset y de otros simbolos
    Cuando se generan los vectores
    Entonces hay exactamente un registro por mensaje A/F/E/C/X/D/U de los simbolos del subset
    Y ningun registro corresponde a mensajes de otros tipos ni de otros simbolos
    Y el flag de cambio es 1 si y solo si el BBO difiere del registro anterior del mismo simbolo

  Escenario: VEC-02 layout binario fijo de 40 bytes por registro
    Dado un fichero de vectores generado
    Cuando se mide su tamano
    Entonces es multiplo exacto de 40 bytes
    Y cada registro decodificado con el layout del Anexo A produce campos validos

  Escenario: VEC-03 round trip binario a texto conserva campos
    Dado un fichero de vectores binario generado
    Cuando se vuelca a texto y se relee el binario
    Entonces cada linea de texto reproduce campo a campo su registro binario

  Escenario: VEC-04 indices de mensaje son globales y monotonicos
    Dado un fichero de vectores generado sobre un stream con mensajes de varios simbolos
    Cuando se recorren los registros
    Entonces msg_idx es estrictamente creciente
    Y msg_idx corresponde al indice del mensaje en el BinaryFILE original
