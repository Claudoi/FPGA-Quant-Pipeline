# language: es
Característica: Envoltura BinaryFILE a pcap MoldUDP64
  binaryfile_to_pcap.py convierte los ficheros de muestra de Nasdaq en pcaps
  reales (Ethernet/IP/UDP/MoldUDP64) para alimentar los testbenches RTL.
  Su correccion se demuestra por round-trip byte a byte.

  Escenario: PCA-01 el pcap se abre con tcpdump sin errores
    Dado un BinaryFILE de entrada valido
    Cuando se genera el pcap y se ejecuta tcpdump -r sobre el
    Entonces tcpdump lo lee sin errores
    Y todos los datagramas son UDP hacia la IP y puerto configurados

  Escenario: PCA-02 empaquetado respeta el maximo de payload configurable
    Dado un BinaryFILE con mensajes de longitudes variadas
    Cuando se genera el pcap con el limite por defecto
    Entonces ningun datagrama supera 1400 bytes de payload UDP
    Y el campo message count de MoldUDP64 coincide con los mensajes del datagrama

  Escenario: PCA-03 sequence numbers monotonicos desde 1
    Dado un pcap generado
    Cuando se recorren los paquetes MoldUDP64 en orden
    Entonces el primer sequence number es 1
    Y cada paquete avanza la secuencia en su message count

  Escenario: PCA-04 round trip pcap a stream BinaryFILE identico
    Dado un BinaryFILE de entrada y el pcap generado a partir de el
    Cuando se extraen los payloads de mensajes de todos los paquetes en orden de secuencia
    Entonces el stream reconstruido es identico byte a byte al payload del BinaryFILE original

  Escenario: SEC-06 mensaje mayor que el payload maximo produce error claro
    Dado un BinaryFILE con un mensaje cuya longitud excede el payload UDP maximo
    Cuando se ejecuta la conversion
    Entonces aborta con un error que indica el indice del mensaje y su longitud
