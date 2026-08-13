# replay.feature — replay de pcaps reales y vectores congelados

Espejo de «Criterios de aceptación» 8 de `spec.md`.

#language: es
Funcionalidad: Replay de pcaps y oráculo híbrido
  Como pipeline de market data
  Quiero verificar el parser contra datos reales (replay) y vectores congelados
  Para cerciorar la corrección byte a byte frente al feed verdadero

Escenario: REP-01 — el RTL reproduce los vectores congelados commiteados byte a byte
  Dado un vector congelado de mensajes en verification/vectors/messages/
  Cuando el parser procesa el pcap sintético que lo originó
  Entonces su salida es byte a byte idéntica al vector congelado

#language: es
Escenario: REP-02 — el RTL sobre un pcap del día real coincide byte a byte con el oráculo --emit-messages
  Dado un pcap generado del día real con binaryfile_to_pcap.py (local, no commiteado)
  Y el oráculo --emit-messages del golden model sobre ese mismo pcap
  Cuando el RTL procesa el stream de entrada
  Entonces la salida de los mensajes del subset es byte a byte idéntica al oráculo
  Y el line rate se mantiene en los tramos de back-to-back reales
