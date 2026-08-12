

**Objetivo:** construir un proyecto que diferencie tu candidatura para entrar en quant finance (perfil FPGA / low-latency trading infrastructure), maximizando valor de CV, experiencia técnica real y material demostrable (repo + write-up + métricas).

**Fecha:** Agosto 2026 **Dispositivo objetivo:** AMD/Xilinx UltraScale+ (familia Zynq US+ o Virtex/Kintex US+)

---

## 0. Aclaraciones terminológicas previas (importante)

Antes de comparar opciones, dos precisiones que definen todo el proyecto:

### 0.1. Qué significa realmente "32 bits @ 322 MHz sin throttling"

- 32 bits × 322,265625 MHz = **10,3125 Gbps** → es exactamente el ancho de banda de **10G Ethernet**.
- 322,265625 MHz es el reloj estándar del datapath XGMII de 32 bits en 10GBASE-R.
- Por tanto, "procesar sin throttling a 32-bit/322 MHz" = **procesar un feed de mercado a line rate de 10G**, que es el listón estándar de la industria (Optiver, IMC, Jump Trading, HRT, Citadel Securities construyen exactamente esto).
- **Alternativa equivalente y más fácil de cerrar en timing:** datapath de **64 bits @ 156,25 MHz** (mismo throughput, 10,0 Gbps efectivos con XGMII de 64 bits). Es lo que entrega de forma nativa el core 10GBASE-R de Vivado. Cerrar timing a 322 MHz con datapath de 32 bits es notablemente más difícil y **no demuestra nada adicional a 10G**; sí sirve como ejercicio de optimización documentado a posteriori (queda mejor en el write-up: "cerré timing a 322 MHz en US+, así lo hice").

### 0.2. "Order book URAM" (lo que llamabas URX order book)

- Los bloques **URAM (UltraRAM)** de UltraScale+ son bloques de memoria on-chip de 288 Kb (4K × 72 bits), mucho más densos que BRAM.
- Son la memoria idónea para almacenar **estado de órdenes** (tabla hash indexada por order reference number) y **niveles de precio** en un order book hardware.
- Es decir: tu intuición era correcta — la arquitectura estándar de un order book FPGA usa URAM para el almacenamiento principal.

### 0.3. Conclusión estructural: las dos opciones NO compiten

- **Opción A (order book)** y **Opción B (parser line-rate)** son **etapas consecutivas del mismo pipeline**, no proyectos alternativos:

```
10G MAC → decap IP/UDP → framing (MoldUDP64) → parser de mensajes → order book engine (URAM) → salida BBO/top-of-book
```

- Un parser sin book es medio proyecto: a las firmas no les interesan mensajes decodificados, les interesa el **estado del libro derivado de ellos con baja latencia**.
- Un book sin parser a line rate es un proyecto de software disfrazado de FPGA.
- El proyecto ganador es **el pipeline completo**, construido por fases. Las "opciones" reales son: **qué exchange/protocolo elegir** y **hasta dónde llegar en cada fase**.

---

## 1. Opción A — Order book completo sobre FPGA

### 1.1. Descripción

Motor de order book en hardware: recibe mensajes de mercado ya parseados (add, execute, cancel, delete, replace), mantiene el estado completo del libro (órdenes vivas + niveles de precio agregados) y emite el **BBO** (best bid & offer) o los N mejores niveles por símbolo, con latencia determinista de nanosegundos.

### 1.2. Alcance técnico detallado

**Estructuras de datos en hardware:**

- **Tabla de órdenes:** hash table en URAM indexada por _order reference number_ (64 bits en ITCH). Cada entrada guarda: símbolo (o índice de símbolo), lado (bid/ask), precio, cantidad restante, puntero a nivel de precio.
    - Manejo de colisiones: open addressing con probing limitado, o cuckoo hashing (más avanzado, mejor peor caso).
    - Dimensionado: un día de Nasdaq puede tener cientos de millones de mensajes, pero órdenes _vivas simultáneas_ por símbolo son órdenes de magnitud menos; para un subconjunto de símbolos, cabe en URAM.
- **Niveles de precio:** por símbolo y lado, array/lista de niveles con precio y cantidad agregada.
    - Versión simple: array indexado por precio relativo al mid (price banding).
    - Versión avanzada: heap/árbol en hardware para top-N niveles.
- **Salida BBO:** registro por símbolo con best bid, best ask, cantidades; se emite evento cada vez que cambia.

**Operaciones a soportar (mapean 1:1 con mensajes ITCH):**

|Operación|Mensaje ITCH|Acción en el book|
|---|---|---|
|Add order|`A` / `F`|Insertar en tabla de órdenes, actualizar nivel de precio|
|Execute|`E` / `C`|Reducir cantidad; si llega a 0, eliminar orden y actualizar nivel|
|Cancel parcial|`X`|Reducir cantidad de la orden y del nivel|
|Delete|`D`|Eliminar orden, actualizar/eliminar nivel|
|Replace|`U`|Delete + Add atómico (nueva referencia, nuevo precio/cantidad)|
|Trade no visible|`P`|No toca el book (trades contra órdenes ocultas); útil para estadísticas|

**Retos de diseño reales (lo que da valor al write-up):**

- Pipeline hazards: dos mensajes consecutivos sobre la misma orden/nivel (read-after-write) → forwarding o stall selectivo.
- Latencia de URAM (lectura registrada, 1-2 ciclos) → diseño del pipeline alrededor de esa latencia.
- Replace atómico sin ventana de inconsistencia en el BBO.
- Multi-símbolo: partición de memoria y árbitro, o instancias paralelas.

### 1.3. Dificultad

- **Alta.** Es la parte más difícil del pipeline: estructuras de datos con estado, hazards, corrección funcional estricta.
- Requiere haber dominado antes el parser (la entrada del book son mensajes parseados).

### 1.4. Valor para CV

- **Máximo.** Es literalmente lo que construyen los equipos FPGA de las firmas de HFT. Un book funcional verificado contra datos reales con histograma de latencias es un proyecto excepcional para un perfil junior.

---

## 2. Opción B — Parser de exchange a line rate (32-bit @ 322 MHz / 10G)

### 2.1. Descripción

Decodificador hardware del protocolo de un exchange que procesa el feed a line rate de 10G sin backpressure: extrae de cada paquete los campos relevantes (tipo de mensaje, order ref, símbolo, precio, cantidad, timestamp) y los emite por una interfaz interna (AXI-Stream) hacia el consumidor (en el proyecto completo, el order book).

### 2.2. Alcance técnico detallado

**Capas del pipeline de recepción:**

1. **PHY/MAC 10G:** core 10GBASE-R + MAC (Vivado ofrece IP gratuita en muchas configuraciones; alternativa open source: cores de corundum o similar).
2. **Decapsulado Ethernet/IP/UDP:** validación de cabeceras, filtrado por puerto/multicast group. (Opcional: checksum UDP — los feeds reales suelen validarse aguas arriba; documenta la decisión.)
3. **Framing del protocolo de transporte del exchange:**
    - Nasdaq: **MoldUDP64** (session + sequence number + message count; cada mensaje lleva length de 2 bytes delante).
    - CME: paquete MDP con Binary Packet Header (sequence number + sending time) y mensajes SBE concatenados.
    - Cboe: **Sequenced Unit Header** (length, count, unit, sequence).
4. **Parser de mensajes:** máquina de estados que consume el stream (32 o 64 bits/ciclo), identifica el tipo de mensaje y extrae campos. Los mensajes pueden cruzar límites de palabra y de paquete → barrel shifter / alineador es la pieza clave.
5. **Gestión de secuencia:** detección de gaps por sequence number (mínimo: contarlos y señalizarlos; avanzado: recovery/arbitraje A/B).

**El requisito "sin throttling" implica:**

- Peor caso: mensajes mínimos back-to-back (en ITCH, mensajes de ~26-40 bytes) → el parser debe aceptar una palabra nueva **cada ciclo, sin excepciones**. Nada de FIFOs elásticos que oculten un parser lento.
- Esto obliga a un diseño totalmente pipelined: ahí está la diferencia entre "un parser que funciona en simulación" y "un parser de calidad industrial".

### 2.3. Dificultad

- **Media-alta.** Menos estado que el book, pero el line rate estricto + alineamiento de mensajes + timing closure es un reto serio para alguien sin experiencia previa en RTL. Es la fase de entrada correcta al proyecto.

### 2.4. Valor para CV

- **Alto pero incompleto en solitario.** "Parser ITCH a line rate" es un proyecto conocido y replicado en GitHub; lo que te diferencia es (a) el rigor de verificación con datos reales, (b) las métricas de latencia, y (c) continuar hasta el book.

---

## 3. Comparativa de exchanges / protocolos (la decisión que sí importa)

### 3.1. Nasdaq TotalView-ITCH 5.0 — **RECOMENDADO como objetivo inicial**

- **Spec:** pública y gratuita (nasdaqtrader.com, PDF "NQTVITCHspecification").
- **Protocolo:** binario, mensajes de longitud fija por tipo, identificados por un carácter ASCII (`S`, `R`, `A`, `F`, `E`, `C`, `X`, `D`, `U`, `P`...). Big-endian. **Ideal para una FSM hardware.** Transporte: MoldUDP64 (también con spec pública).
- **Datos reales:** **GRATIS.** Nasdaq publica ficheros de muestra de días completos de trading (orden a orden) en su servidor público `emi.nasdaq.com/ITCH/`.
    - **Matiz crítico:** esos ficheros NO son pcap estándar libpcap (no se abren en Wireshark). Siguen el formato **BinaryFILE** de Nasdaq: secuencia de mensajes con campo de longitud (2 bytes) + payload. Necesitarás un script Python que los envuelva en MoldUDP64/UDP/IP/Ethernet para alimentar tu testbench — ese script es en sí mismo un artefacto valioso del repo.
- **Complejidad del protocolo:** baja-media. Un book funcional necesita solo ~6-10 tipos de mensaje.
- **Por qué es el estándar de facto de los proyectos FPGA de order book:** spec pública + datos gratis + protocolo simple. Prácticamente todos los proyectos publicados usan ITCH.

### 3.2. CME MDP 3.0 — **RECOMENDADO como segundo objetivo (stretch)**

- **Spec:** pública (cmegroup.com, "Market Data Platform 3.0", codificación **SBE — Simple Binary Encoding**, con schemas XML de templates).
- **Protocolo:** más sofisticado: mensajes SBE definidos por templates versionados, feed incremental + snapshot para recovery, canales por producto, feeds duplicados A/B que hay que arbitrar. Técnicamente más impresionante que ITCH.
- **Datos reales:** **DE PAGO.** CME vende pcaps históricos vía su plataforma DataMine (agrupados por canales; p.ej. canal 310 = E-mini S&P). Conseguir incluso unos días de muestra implica trámite comercial y coste. No hay ficheros públicos de muestra comparables a los de Nasdaq.
- **Veredicto:** empezar aquí sería estrellarse contra el muro de los datos antes de escribir una línea de RTL. Pero **portar** tu pipeline de ITCH a MDP3 (aunque sea solo el parser SBE verificado con paquetes sintéticos generados desde los schemas XML) demuestra generalidad de diseño y conocimiento del protocolo del mayor mercado de futuros del mundo. Excelente capítulo final.

### 3.3. Cboe (BZX/EDGX...) Depth of Book — PITCH

- **Spec:** pública (Cboe publica las specs de Multicast PITCH y del Sequenced Unit Header).
- **Protocolo:** binario, conceptualmente similar a ITCH (add/execute/cancel por order id), little-endian en la versión multicast. Complejidad comparable a ITCH.
- **Datos reales:** las capturas de muestra del feed de profundidad son **mucho más difíciles de conseguir** que las de Nasdaq; no existe un repositorio público equivalente a `emi.nasdaq.com`.
- **Veredicto:** sin ventaja frente a ITCH y con peor acceso a datos. Descartado como objetivo inicial; válido como port adicional si algún día consigues capturas.

### 3.4. NYSE (XDP / Integrated Feed)

- **Spec:** pública (XDP Integrated Feed Client Specification).
- **Datos reales:** NYSE ha publicado datos de muestra descargables con relativa facilidad.
- **Veredicto:** alternativa razonable a ITCH, pero el ecosistema de proyectos, herramientas y referencias alrededor de ITCH es mucho mayor. Segunda opción si quisieras diferenciarte del "proyecto ITCH típico"; no lo recomiendo como primer objetivo porque pierdes la red de seguridad de referencias existentes.

### 3.5. Tabla resumen

|Criterio|Nasdaq ITCH 5.0|CME MDP 3.0|Cboe PITCH|NYSE XDP|
|---|---|---|---|---|
|Spec pública|✅|✅|✅|✅|
|Datos reales gratis|✅ (emi.nasdaq.com)|❌ (DataMine, pago)|⚠️ difícil|⚠️ muestra descargable|
|Complejidad protocolo|Baja-media|Alta (SBE, recovery, A/B)|Baja-media|Media|
|Adecuación a FSM hardware|Excelente|Buena (SBE es regular)|Excelente|Buena|
|Referencias/proyectos existentes|Muchísimas|Pocas|Pocas|Pocas|
|Prestigio del protocolo|Alto|Muy alto (futuros)|Alto|Alto|
|**Rol en el proyecto**|**Fase principal**|**Stretch final**|Descartado|Alternativa/port|

---

## 4. Recomendación final: proyecto combinado por fases

**Un solo proyecto: "Line-rate ITCH 5.0 parser + URAM order book en UltraScale+", con port a CME MDP3 como fase stretch.**

### Fase 0 — Modelo dorado en Python (1-2 semanas de trabajo real)

- Parser ITCH + order book en Python puro leyendo los ficheros de `emi.nasdaq.com`.
- Objetivos: aprender el protocolo al detalle, generar los vectores de referencia (estado del book y BBO mensaje a mensaje) contra los que se verificará el RTL.
- Entregable: `golden_model/` + script `binaryfile_to_pcap.py` (envuelve BinaryFILE en MoldUDP64/UDP para el testbench).

### Fase 1 — Parser RTL a line rate (1-2 meses)

- Datapath **64 bits @ 156,25 MHz** (el que entrega el core 10GBASE-R nativo de Vivado). Subset de mensajes: `S, R, A, F, E, C, X, D, U, P`.
- AXI-Stream de salida con mensajes normalizados.
- Requisito duro: aceptar una palabra por ciclo sin excepción (peor caso: mensajes mínimos back-to-back).
- Verificación: cocotb (o testbench SystemVerilog) reproduciendo los pcaps reales y comparando byte a byte contra el golden model.

### Fase 2 — Order book engine (2-3 meses)

- Tabla de órdenes en URAM (hash por order ref), niveles de precio, salida BBO.
- Empezar con un puñado de símbolos; escalar después.
- Verificación: mismo replay, comparando el BBO del RTL contra el del golden model en cada mensaje.
- Métricas: histograma de latencia wire-to-book-update en ciclos/ns.

### Fase 3 — Optimización y cierre (1 mes)

- **Aquí sí:** variante 32-bit @ 322,265625 MHz con informe de cierre de timing en el dispositivo US+ objetivo. Documentar las técnicas usadas (retiming, pipelining de rutas críticas, floorplanning si hace falta). Esto como capítulo de optimización queda **mejor** que como punto de partida.
- Informe de utilización (LUT/FF/BRAM/URAM) y de timing.

### Fase 4 — Stretch (opcional, orden de valor para CV)

1. Parser SBE de CME MDP3 verificado con paquetes sintéticos desde los schemas XML (+ pcaps de DataMine si algún día pagas por ellos).
2. Interfaz host AXI/PCIe para volcar el BBO a software.
3. Write-up técnico publicado (blog/GitHub Pages) con benchmarks de latencia.

### Hardware físico: opcional, no bloqueante

- Todo el proyecto es demostrable **sin placa**: simulación con datos reales + cierre de timing en Vivado apuntando al part US+ es ya un proyecto muy fuerte.
- Si más adelante quieres demo física: Alveo U50 de segunda mano, ZCU106, o placas US+ usadas del mercado de minería reconvertidas. Decisión para el final, no para el principio.

### Estimación honesta de esfuerzo total

- **4-7 meses** de trabajo constante en paralelo con tus estudios, partiendo sin experiencia RTL. El write-up documentando la curva de aprendizaje es la mitad de la señal que envía el proyecto.

---

## 5. Entregables finales para el CV

1. Repo público: RTL + golden model + testbench + scripts de datos + CI de simulación.
2. Informe de timing/utilización en UltraScale+ (156 MHz y variante 322 MHz).
3. Histogramas de latencia por tipo de mensaje (wire-in → BBO out).
4. Write-up técnico: decisiones de arquitectura, hazards del book, cierre de timing.
5. (Stretch) Capítulo CME MDP3/SBE.

**Frase de CV objetivo:** _"Diseñé y verifiqué un pipeline FPGA (UltraScale+) que decodifica Nasdaq TotalView-ITCH 5.0 a line rate de 10G y mantiene un order book en URAM con latencia determinista de X ns, verificado contra días completos de datos reales de mercado."_

---

## 6. Riesgos y errores comunes a evitar

- **Empezar por CME:** te quedas sin datos reales antes de empezar. Primero ITCH.
- **Empezar por 32-bit @ 322 MHz:** dificultad de timing gratuita sin valor añadido a 10G; hazlo como optimización final.
- **Parser sin book:** proyecto a medias, y además el más replicado en GitHub.
- **Book sin verificación contra golden model:** un book "que parece funcionar" no vale nada; la corrección bit a bit contra datos reales es el 50% del valor.
- **Soportar todos los tipos de mensaje ITCH desde el día 1:** el subset de ~10 tipos basta para un book funcional; el resto se añade después.
- **Comprar placa el primer día:** gasto prematuro; la simulación + timing closure ya es demostrable.
- **Ignorar los sequence numbers:** detectar gaps de MoldUDP64, aunque solo sea contarlos, es lo que separa un juguete de un diseño consciente del mundo real.

---

## 7. Recursos clave

- **Spec ITCH 5.0:** nasdaqtrader.com → Technical Support → Specifications → "NQTVITCHspecification.pdf".
- **Spec MoldUDP64:** nasdaqtrader.com (mismo repositorio de specs).
- **Datos de muestra ITCH:** `emi.nasdaq.com/ITCH/` (ficheros `*.NASDAQ_ITCH50.gz`, formato BinaryFILE).
- **Spec CME MDP 3.0 + schemas SBE:** cmegroup.com → Market Data → MDP 3.0; SBE en la web de FIX Trading Community.
- **Spec Cboe PITCH:** cboe.com → US Equities → Technical Specifications.
- **Spec NYSE XDP:** nyse.com → Market Data → documentación técnica de Integrated Feed.
- **Herramientas:** Vivado (WebPACK cubre bastantes parts US+), cocotb + Verilator/Questa para verificación, Python para golden model y tooling de datos.