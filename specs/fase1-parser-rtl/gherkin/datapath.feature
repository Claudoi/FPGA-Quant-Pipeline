# datapath.feature — line rate, alineación y datapath de 64-bit

Espejo de «Criterios de aceptación» 2 y 3 de `spec.md`.

#language: es
Funcionalidad: Datapath 64-bit a line rate con alineador de mensajes
  Como pipeline de market data
  Quiero que el datapath acepte una palabra por ciclo en el peor caso y alinee mensajes
  Para cumplir el requisito duro de line rate del documento maestro

Escenario: LIN-01 — el parser acota stalls en el tramo pactado con QB=64
  Dado una entrada de cuatro mensajes A/U back-to-back y QB igual a 64
  Cuando el downstream consume a tready alto
  Entonces la salida es bit a bit idéntica al golden
  Y el contador acumulado de ciclos de stall es menor o igual que 24

#language: es
Esquema del escenario: ALN-01 — el alineador decodifica correctamente cualquier desplazamiento dentro de la palabra
  Dado un mensaje de tipo <tipo> cuyo primer byte cae en el desplazamiento <offset> de la palabra de 64-bit
  Y cuya longitud cruza <cruce> el límite de palabra
  Cuando el RTL procesa el stream
  Entonces decodifica el mensaje y produce el registro correcto byte a byte
  Y no añade ciclos de stall frente a la alineación sin cruce

  Ejemplos:
    | tipo | offset | cruce |
    | A    | 0      | sí    |
    | A    | 1      | sí    |
    | A    | 2      | sí    |
    | A    | 3      | sí    |
    | A    | 4      | sí    |
    | A    | 5      | sí    |
    | A    | 6      | sí    |
    | A    | 7      | sí    |

#language: es
Escenario: SEC-LIN-01 — los mensajes fuera de subset no rompen el line rate
  Dado un mensaje H canónico fuera del subset entre dos mensajes A
  Cuando el downstream consume a tready alto
  Entonces la longitud de H se valida y el flujo continúa sin error
  Y solo emite registros para los mensajes del subset
