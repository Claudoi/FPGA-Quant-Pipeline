# language: es
Característica: Datos de la campaña: descarga y estadisticas
  Los feeds reales jamas se commitean: se descargan con verificacion md5 a
  data/itch_sample/ (gitignored) y de ellos salen las estadisticas que fijan
  el subset de simbolos y el dimensionado de memoria del RTL.

  Escenario: DAT-01 descarga verificada con md5 correcto
    Dado el fichero del dia principal presente en el servidor
    Cuando se ejecuta fetch_itch.py
    Entonces el fichero queda en data/itch_sample/
    Y su md5 coincide con el publicado por Nasdaq

  Escenario: DAT-03 md5sum no servido aborta fail closed con error claro
    Dado un servidor que sirve el fichero pero cuyo endpoint md5sum responde 404
    Cuando se ejecuta fetch_itch.py sin flag de omision
    Entonces aborta con un error claro (sin traceback) y codigo de salida distinto de cero
    Y no queda un fichero usable como entrada de runs
    Y con --no-md5-verify descarga avisando en stderr que la integridad no quedo verificada por md5

  Escenario: SEC-07 md5 incorrecto aborta sin dejar fichero aparentemente valido
    Dado un fichero descargado corrompido a proposito
    Cuando se ejecuta la verificacion
    Entonces el script aborta con error de md5
    Y no queda un fichero usable como entrada de runs

  Escenario: DAT-02 estadisticas de dimensionado por simbolo
    Dado el BinaryFILE del dia principal
    Cuando termina un run completo
    Entonces se emite una tabla por simbolo con mensajes, pico de ordenes vivas y pico de niveles
    Y a partir de ella select_subset.py escribe verification/vectors/subset_symbols.json con el top 20 por pico de ordenes vivas
