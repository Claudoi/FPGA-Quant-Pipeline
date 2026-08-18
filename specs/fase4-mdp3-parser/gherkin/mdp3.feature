# mdp3.feature — fase 4: parser CME MDP 3.0 (SBE) verificado contra golden del schema

Espejo de «Criterios de aceptación» 1-10 de `spec.md` de fase4-mdp3-parser.
La semántica de cada campo del subset se deriva del schema SBE XML oficial de
CME (`templates_FixBinary.xml`, ftp.cmegroup.com), no de una segunda tabla
manual en el testbench.

#language: es
Funcionalidad: Parser CME MDP 3.0 (SBE) a line-rate con Anexo M normalizado
  Como pipeline de market data a line-rate 10G
  Quiero decodificar el paquete MDP 3.0 y sus mensajes SBE
  Para portar el pipeline de ITCH al mayor mercado de futuros del mundo

  Escenario: M3-GEN-01 — el golden hace round-trip decode(encode(m)) == m
    Dado el schema SBE XML oficial de CME cargado
    Y vectores conocidos del subset con root, precios y grupos de valores no cero
    Cuando el encoder produce cada mensaje y el decoder lo lee
    Entonces cada campo observable decodificado coincide con su valor conocido
    Y PRICE9.mantissa y todos los entries de grupos multi-entry se preservan
    Y el passthrough de un template no-subset preserva el cuerpo crudo

  Escenario: M3-GEN-02 — el loader deriva los tamaños esperados desde el XML
    Dado el schema cargado
    Cuando se calcula el tamaño esperado de cada mensaje del subset
    Entonces coincide con blockLength + grupos + padding root a 8 B del XML

  Escenario: M3-GEN-03 — schemaId y version proceden del XML pinned
    Dado el schema oficial con id 1 y version 12
    Cuando el loader lo carga y el encoder crea un mensaje sin overrides
    Entonces la cabecera SBE contiene schemaId 1 y version 12

  Escenario: M3-FRM-01 — el parser emite el Anexo M bit a bit vs el golden
    Dado un corpus sintético de paquetes MDP 3.0 (header 12 B + mensajes)
    Cuando el parser procesa el stream
    Entonces la secuencia de records (w0, w1, cuerpo) es bit a bit idéntica
    Y msg_seq_num, sending_time y msg_size de cada mensaje son correctos

  Escenario: M3-FRM-02 — mensajes que cruzan límites de palabra
    Dado un corpus cuyos mensajes terminan y empiezan en cualquier byte
    Y cada payload UDP se presenta como un burst con tkeep y tlast propios
    Cuando el parser los procesa a DW=32 y DW=64
    Entonces no se pierde ni se duplica ningún mensaje

  Escenario: M3-FRM-03 — peor caso a 1 palabra/ciclo sin backpressure
    Dado un paquete con 24 mensajes literales template 47 de una entry y 64 B
    Cuando se presentan a una palabra válida por ciclo
    Entonces la racha de ciclos valid sin ready es como máximo 16
    Y la secuencia de salida es bit a bit idéntica al golden

  Escenario: M3-FRM-04 — el cierre exacto del paquete no deja residuo ambiguo
    Dado un paquete de exactamente 12 bytes y otro con un byte residual tras el header
    Cuando el parser recibe cada uno con su tkeep y tlast exactos
    Entonces el paquete vacío no emite records ni error
    Y el residual pulsa error y permite procesar el siguiente paquete íntegro

  Escenario: M3-SUB-01 — el subset de libro se decodifica campo a campo
    Dado mensajes de los templates de libro (snapshot e incremental)
    Cuando el parser decodifica cada entry del grupo NoMDEntries
    Entonces el Anexo M contiene security_id, rpt_seq, update_action,
      entry_type, precio (mantissa+exponente), size, num_orders y price_level
      bit a bit iguales al golden

  Escenario: M3-FRM-05 — el framing consume s_axis_tkeep byte a byte
    Dado un paquete presentado con tkeep MSB-contiguo y el último beat
      parcial declarando solo sus bytes reales
    Cuando el parser procesa el stream
    Entonces el Anexo M es bit a bit idéntico al golden
    Y un mensaje cuya longitud declarada solo se completaría con lanes
      tkeep=0 no se completa: pulsa error, no emite record parcial
    Y el siguiente paquete íntegro se recupera bit a bit
    Y un beat con tkeep=0 completo en medio del burst se consume sin aportar
      bytes ni trabarse

  Escenario: M3-SUB-02 — el precio compuesto y los grupos multi-entry
    Dado un mensaje con varios entries y precios con exponentes negativos
    Cuando el parser decodifica
    Entonces cada record lleva su mantissa y su exponente sin mezclarse
    Y hay un record por entry en el mismo orden del grupo

  Escenario: M3-PASS-01 — passthrough crudo de templates no-subset
    Dado mensajes fuera del subset y cada template 46, 47, 52 y 53 con schemaId o version no soportados
    Cuando el parser los procesa
    Entonces emite w0/w1 + cuerpo crudo bit a bit
    Y un schemaId o version desconocidos no abortan el flujo

  Escenario: M3-PASS-02 — el máximo de mensaje es explícito y recuperable
    Dado un mensaje passthrough válido con msg_size 256 y otro que declara 257 bytes
    Cuando cada uno llega en su propio paquete seguido de un paquete íntegro
    Entonces el mensaje de 256 bytes se preserva bit a bit
    Y el de 257 pulsa error, no emite record parcial y permite la recuperación

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
    Dado un payload UDP al que le faltan entre 1 y DW/8 menos 1 bytes de un mensaje
    Cuando el parser recibe tlast de entrada
    Entonces señaliza error si el mensaje declarado no está completo
    Y espera el siguiente paquete sin estado corrupto

  Escenario: M3-INV-03 — grupo mal formado dentro del mensaje
    Dado un entry cuyo tamaño excede msg_size o un grupo con numInGroup 0
    Cuando el parser lo procesa
    Entonces señaliza error o emite record vacío según el contrato del golden
    Y no trunca silenciosamente los entries siguientes

  Escenario: M3-INV-04 — una máscara tkeep inválida se descarta con señal
    Dado un beat con tkeep cero, con huecos o parcial sin tlast
    Cuando el parser lo acepta y después recibe un paquete íntegro
    Entonces señaliza error y descarta el paquete inválido
    Y procesa el paquete posterior sin pérdida ni estado corrupto

  Escenario: M3-SCH-01 — los localparams RTL coinciden con el schema v12
    Dado el schema SBE XML oficial de CME y el RTL especializado
    Cuando se contrastan IDs, offsets, dimensiones y blockLength del subset
    Entonces cada literal estructural del RTL coincide con el valor del XML

  Escenario: M3-REG-01 — las fases 1-3 siguen verdes
    Dado s_axis_tkeep propagado por itch_parser e itch_chain sin cambiar el enlace al book
    Cuando se re-ejecutan las suites de fase 1, 2 y 3
    Entonces todos los tests siguen pasando sin cambios
    Y el mdp3_parser a DW=64 pasa su suite en regresión

  Escenario: M3-BP-01 — la salida se retiene estable durante backpressure
    Dado un record presentado con m_axis_tvalid y m_axis_tready bajo
    Cuando el consumidor mantiene el stall durante al menos dos ciclos
    Entonces la tupla m_axis_tdata, m_axis_tvalid y m_axis_tlast permanece estable
    Y m_axis_tvalid sigue activo hasta entregar el record exactamente una vez

  Escenario: M3-BP-02 — la entrada permanece estable mientras el parser no acepta
    Dado un burst válido presentado a DW=32 o DW=64
    Cuando s_axis_tvalid está activo y s_axis_tready permanece bajo
    Entonces s_axis_tdata, s_axis_tkeep y s_axis_tlast permanecen estables
    Y el beat se contabiliza una sola vez cuando ocurre el handshake
