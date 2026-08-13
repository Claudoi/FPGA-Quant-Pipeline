# datapath.feature — line rate, alineación y datapath de 64-bit

Espejo de «Criterios de aceptación» 2 y 3 de `spec.md`.

#language: es
Funcionalidad: Datapath 64-bit a line rate con alineador de mensajes
  Como pipeline de market data
  Quiero que el datapath acepte una palabra por ciclo en el peor caso y alinee mensajes
  Para cumplir el requisito duro de line rate del documento maestro

Escenario: LIN-01 — el parser acepta 1 palabra/ciclo con mensajes mínimos back-to-back sin stall
  Dado una entrada de mensajes mínimos back-to-back (D 19 B, X 23 B, S 12 B)
  Cuando el downstream consume a tready alto
  Entonces el RTL acepta una palabra de entrada por ciclo
  Y el contador de ciclos de stall es cero en todo el test

#language: es
Esquema del escenario: ALN-01 — el alineador decodifica correctamente cualquier desplazamiento dentro de la palabra
  Dado un mensaje de tipo <tipo> cuyo primer byte cae en el desplazamiento <offset> de la palabra de 64-bit
  Y cuya longitud cruza <cruce> el límite de palabra
  Cuando el RTL procesa el stream
  Entonces decodifica el mensaje y produce el registro correcto byte a byte
  Y no añade ciclos de stall frente a la alineación sin cruce

  Ejemplos:
    | tipo | offset | cruce |
    | D    | 0      | no    |
    | D    | 1      | sí    |
    | X    | 3      | sí    |
    | S    | 5      | no    |
    | D    | 6      | sí    |
    | A    | 7      | sí    |
    | A    | 2      | sí    |
    | A    | 4      | sí    |
    | E    | 1      | sí    |

#language: es
Escenario: SEC-LIN-01 — los mensajes fuera de subset no rompen el line rate
  Dado un stream con mensajes del subset y de otros tipos intercalados
  Cuando el downstream consume a tready alto
  Entonces el parser mantiene 1 palabra/ciclo sin stall interno
  Y solo emite registros para los mensajes del subset
