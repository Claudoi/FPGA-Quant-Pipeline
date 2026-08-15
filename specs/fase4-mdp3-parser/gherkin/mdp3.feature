# mdp3.feature — fase 4: parser CME MDP 3.0 (SBE) verificado contra golden del schema

Espejo de «Criterios de aceptación» 1-9 de `spec.md` de fase4-mdp3-parser.
La semántica de cada campo del subset se deriva del schema SBE XML oficial de
CME (`templates_FixBinary.xml`, ftp.cmegroup.com) — nunca de literales.

#language: es
Funcionalidad: Parser CME MDP 3.0 (SBE) a line-rate con Anexo M normalizado
  Como pipeline de market data a line-rate 10G
  Quiero decodificar el paquete MDP 3.0 y sus mensajes SBE
  Para portar el pipeline de ITCH al mayor mercado de futuros del mundo

  Escenario: M3-GEN-01 — el golden hace round-trip decode(encode(m)) == m
    Dado el schema SBE XML oficial de CME cargado
    Cuando el generator produce un mensaje del subset y el decoder lo lee
    Entonces los campos decodificados coinciden bit a bit con los generados
    Y el passthrough de un template no-subset preserva el cuerpo crudo

  Escenario: M3-GEN-02 — el loader deriva los tamaños esperados desde el XML
    Dado el schema cargado
    Cuando se calcula el tamaño esperado de cada mensaje del subset
    Entonces coincide con blockLength + grupos + padding root a 8 B del XML

  Escenario: M3-FRM-01 — el parser emite el Anexo M bit a bit vs el golden
    Dado un corpus sintético de paquetes MDP 3.0 (header 12 B + mensajes)
    Cuando el parser procesa el stream
    Entonces la secuencia de records (w0, w1, cuerpo) es bit a bit idéntica
    Y msg_seq_num, sending_time y msg_size de cada mensaje son correctos

  Escenario: M3-FRM-02 — mensajes que cruzan límites de palabra
    Dado un corpus cuyos mensajes terminan y empiezan en cualquier byte
    Cuando el parser los procesa a DW=32 y DW=64
    Entonces no se pierde ni se duplica ningún mensaje

  Escenario: M3-FRM-03 — peor caso a 1 palabra/ciclo sin backpressure (MBP)
    Dado un paquete de mensajes mínimos MBP del subset back-to-back
    Cuando el parser los procesa
    Entonces no hay backpressure sostenida de entrada
    Y la secuencia de salida es bit a bit idéntica al golden
    Y los mensajes MBOFD aplican backpressure inherente por expansión del
      Anexo M, documentada en el constraint Line-rate de la spec

  Escenario: M3-SUB-01 — el subset de libro se decodifica campo a campo
    Dado mensajes de los templates de libro (snapshot e incremental)
    Cuando el parser decodifica cada entry del grupo NoMDEntries
    Entonces el Anexo M contiene security_id, rpt_seq, update_action,
      entry_type, precio (mantissa+exponente), size, num_orders y price_level
      bit a bit iguales al golden

  Escenario: M3-SUB-02 — el precio compuesto y los grupos multi-entry
    Dado un mensaje con varios entries y precios con exponentes negativos
    Cuando el parser decodifica
    Entonces cada record lleva su mantissa y su exponente sin mezclarse
    Y hay un record por entry en el mismo orden del grupo

  Escenario: M3-PASS-01 — passthrough crudo de templates no-subset
    Dado mensajes de templates fuera del subset (definiciones, estados)
    Cuando el parser los procesa
    Entonces emite w0/w1 + cuerpo crudo bit a bit
    Y un schemaId o version desconocidos no abortan el flujo

  Escenario: M3-GAP-01 — gap de secuencia señalizado sin abortar
    Dado un canal con msg_seq_num saltando un valor
    Cuando el parser recibe el paquete
    Entonces señaliza gap_detected
    Y un canal nuevo (secuencia reiniciada) no cuenta como gap

  Escenario: M3-INV-01 — msg_size incoherente señaliza error
    Dado un mensaje cuyo tamaño es menor que la cabecera SBE o desborda el paquete
    Cuando el parser lo procesa
    Entonces señaliza error
    Y no se cuelga ni corrompe el resto del stream

  Escenario: M3-INV-02 — paquete truncado por tlast manejado
    Dado un payload UDP que termina en medio de un mensaje
    Cuando el parser recibe tlast de entrada
    Entonces señaliza error si el mensaje declarado no está completo
    Y espera el siguiente paquete sin estado corrupto

  Escenario: M3-INV-03 — grupo mal formado dentro del mensaje
    Dado un entry cuyo tamaño excede msg_size o un grupo con numInGroup 0
    Cuando el parser lo procesa
    Entonces señaliza error o emite record vacío según el contrato del golden
    Y no trunca silenciosamente los entries siguientes

  Escenario: M3-REG-01 — las fases 1-3 siguen verdes
    Dado el RTL nuevo añadido sin tocar lo existente
    Cuando se re-ejecutan las suites de fase 1, 2 y 3
    Entonces todos los tests siguen pasando sin cambios
    Y el mdp3_parser a DW=64 pasa su suite en regresión