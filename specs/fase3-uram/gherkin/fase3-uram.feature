# fase3-uram.feature — campaña URAM: tabla en URAM + sonda serializada +
# pipeline de niveles + recorte del Anexo A de 32 bits.

Espejo de «Criterios de aceptación» 1-8 de `spec.md` de fase3-uram.
La semántica de cada operación es EXACTAMENTE la de `golden_model/src/book.py`
y `golden_model/itch/messages.py` (fases 0-2) y de la fase 3 previa
(30.729 eventos BBO/depth bit a bit sobre el feed real del subset).

#language: es
Funcionalidad: Order book sobre URAM sintetizable a 322,265625 MHz
  Como pipeline de market data a line-rate 10G
  Quiero que la tabla de órdenes viva en URAM con lecturas registradas
  Para que el diseño cierre timing a 3,103 ns sin perder ni un bit de corrección

  Escenario: ANX-01 — el Anexo A de 32 bits recortado es bit a bit contra el oráculo
    Dado el corpus sintético de la fase 1
    Cuando el parser de 32 bits procesa cada mensaje
    Entonces las words de salida (w0 context, w1 idx, w2.. cuerpo, sin ts)
      coinciden bit a bit con el oráculo message_oracle actualizado
    Y el book de 32 bits consume el mismo layout sin desalinearse

  Escenario: ANX-02 — el peor caso sigue a 1 palabra/ciclo con el layout recortado
    Dado un flujo de mensajes mínimos back-to-back
    Cuando el parser de 32 bits los procesa con el layout recortado
    Entonces no hay backpressure sostenida de entrada
    Y los stalls del tramo probado quedan acotados (≤ 24, régimen LIN-01)

  Escenario: SEC-URAM-01 — la tabla se lee de forma registrada, nunca combinacional
    Dado un probe de la tabla de órdenes
    Cuando se emite una dirección de slot en el ciclo N
    Entonces el dato es válido exactamente en el ciclo N+1
    Y la sonda consume a lo sumo 1 slot por ciclo
    Y ninguna comparación de la sonda indexa o_mem directamente

  Escenario: SEC-URAM-02 — el prefetch del grupo de hash ocurre durante ST_BODY
    Dado un mensaje cuyo grupo de hash tiene PROBE+ refs colisionando (K=20)
    Cuando el book recibe el cuerpo del mensaje
    Entonces los slots del grupo se leen antes de entrar en ST_APPLY
    Y el lookup termina con la misma semántica que el hash de fase 3

  Escenario: SEC-URAM-03 — el pipeline de niveles no crea burbujas ni fantasmas
    Dado 33 adds que desbordan P=32 y un delete posterior sobre un nivel ausente
    Cuando el book procesa la secuencia
    Entonces jamás aparece un precio stale ni una cantidad envuelta
    Y cada operación de nivel consume a lo sumo 2 ciclos extra

  Escenario: REG-01 — la regresión completa sigue verde con el RTL nuevo
    Dado el RTL refactorizado (URAM + sonda serializada + pipeline + Anexo recortado)
    Cuando se re-ejecutan las suites de fase 1, fase 2 y fase 3
    Entonces todos los tests siguen pasando sin cambios
    Y las anomalías/cross del feed real se mantienen idénticos

  Escenario: CHAIN-01 — la cadena parser→book es bit a bit con el Anexo recortado
    Dado el feed real decapado (parser 32 → book 32, sin re-parseo)
    Cuando la cadena procesa el subset
    Entonces la secuencia de BBO y depth es bit a bit idéntica al golden book.py
    Y anomaly=671, cross=0 y gaps=0 (evidencia de fase 3)

  Escenario: SEC-URAM-04 — la latencia media se mantiene por debajo de 45 ciclos
    Dado la cadena parser→book a DW=32 sobre la secuencia fija de latencia
    Cuando se mide la latencia wire→BBO por tipo de mensaje
    Entonces la media total es ≤ 45 ciclos
    Y la re-ejecución produce el histograma idéntico (determinismo SEC-LAT-01)
