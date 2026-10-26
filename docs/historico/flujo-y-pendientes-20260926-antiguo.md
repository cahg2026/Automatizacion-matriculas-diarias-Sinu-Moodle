# El flujo de proceso y lo que queda por resolver

**Fecha:** 26/09/2026, 18:15
**Para:** quien opere o mantenga la automatización Moodle–SINU.
**Método:** todo lo que aquí se afirma está medido contra los diarios de ejecución reales (`logs/resultados_etapa4*.jsonl`) o comprobado contra la pantalla de SINU ese mismo día. Donde algo **no** está medido, se dice.

---

## 0. Estado en este momento

| | |
|---|---|
| Corridas en marcha | **ninguna** |
| Navegadores del perfil de automatización | ninguno |
| **Ciclos abiertos** (estudiantes desvinculados a medias) | **0** |
| Cerrojo `MODO_SIMULACION` | `true` (cerrado) |
| Pruebas | **687 pasan** |
| Cambios sin commitear | sí, todos (nada en ninguna rama) |

**Reporte del día:** 269 filas, 254 procesables.

| | Filas |
|---|---:|
| Procesadas | 34 (13%) |
| Verdes (no se repiten al relanzar) | 12 |
| **Pendientes** | **220** |

La corrida se detuvo a las 15:52 por decisión del dueño del proceso, tras comprobar que iba a 2,3 min/fila con el 50% de las lecturas fallando.

---

## 1. El flujo, paso a paso

Lo dispara el Programador de tareas de Windows: `MoodleSinu-FlujoDiario`, **09:00 todos los días**, lanzando `dia_completo.py --ejecutar-de-verdad`.

Antes del paso 0 escribe `MODO_SIMULACION=false` en `config/.env` **y** en el entorno del proceso, y comprueba que los hijos lo van a leer así. Al terminar lo devuelve a `true` en un `finally`.

### PASO 0 — Perfil y sesión de Google · ~8 s
`probar_perfil.py` abre un navegador (Edge, headless, perfil `.playwright-perfil-msedge`), navega para comprobar que la sesión de Google responde de verdad, y cierra.

**Sin reintentos.** Código 5 (sesión caída) → el día se aborta aquí, a propósito: si la sesión no sirve, el paso 3 fallaría igual pero ya con el cerrojo de escritura abierto.

### PASO 1 — Cerrojo del tablero · 17 s … 90 min
`verificar_actualizacion.py` entra a Power BI, espera el lienzo (+4 s de asentamiento) y lee la fecha de actualización.

- Si no es de hoy: espera 15 min y **relee sobre el mismo navegador**. Hasta 90 min de ventana.
- Ventana agotada → alerta y sale con **código 0** (no rojo en el Programador: el día se resolvió como debía).
- No se puede *leer* la fecha → no reintenta. Significa que el tablero cambió de forma.

La ventana existe por un dato medido: el 09/09 a las 08:05 el tablero aún era de ayer. **El refresco cae por la mañana y puede ser después de las 9:00.**

### PASO 2 — Descarga de Power BI · 2 … 12 min
`exportar_reporte.py` entra al informe (plazo de render 120 s), exporta la tabla (plazo de descarga 300 s) y guarda en `data/raw/`.

**Hasta 5 intentos, 90 s entre uno y otro.** Cada intento abre un navegador nuevo y antes mata los Edge colgados del perfil.

Medido hoy tras el arreglo: **1 intento, 2 min 47 s hasta el Sheet.**

### PASO 3 — Fase 1 + subida a Drive · ~1 min 30 s
`subir_reporte.py --visible` valida el reporte (Fase 1: las naranjas quedan fuera), ordena A-Z por período, sube por *drop* y Drive lo convierte a Sheet.

**Tiene que ser visible:** Drive no tiene `input[type=file]`.

**2 intentos.** Si el intento fallido ya imprimió una URL de Sheet, **no se reintenta**: la subida sí ocurrió y un segundo intento dejaría dos Sheets del mismo día.

### PASO 4 — ISEF07 · el 95% del tiempo
`procesar_dia.py` lanza un subproceso `ejecutar_sinu.py` **por período**. Cada uno abre su navegador y hace su login de SINU.

Dentro de cada período:

1. Abre el Sheet del día (regla del 31/08: el Sheet antes que ISEF07).
2. Login de SINU, entra a ISEF07, fija el período.
3. **PASO 5.5 — verificación de grupos** (ver §2).
4. Procesa fila por fila.

**Por cada fila (cédula, materia):**

| Sub-paso | Plazo | Reintentos | Medido |
|---|---|---|---|
| Leer el estudiante | 120 s | 0 | **11 s sana**, 124 s atascada |
| Acotar la grilla a la materia | 30 s | 0 | ~5 s |
| Ejecutar en ISEF07 | 300 s | **1, y solo 1** | 58–125 s |
| Sondear el check | 90 s, relee cada 5 s | — | **419 de 419 confirmaron a la 1.ª lectura** |
| Guarda de desborde | ~18 s | muestreo: 5 primeras + 1 de cada 25 | |

**La regla de negocio, confirmada por el dueño del proceso el 26/09:**

```
Vinculado? SIN marcar  →  Vincular.                          (~43 s)
Vinculado? YA marcado  →  Desvincular, confirmar, Vincular.  (~95 s)
```

> **El check "Vinculado?" NO es de fiar.** Por eso lo que aparece vinculado hay que desvincularlo y volverlo a vincular. El reciclado es la reparación, no un desperdicio.

**Cortafuegos:** 3 lecturas seguidas vacías o fallidas → se detiene el lote y las filas restantes quedan **sin marcar** (un rojo falso es peor que un hueco).

**No se reabre SINU nunca** durante un reporte. Regla del 25/09.

### PASO 5 — Columna Q · ~1 min 10 s
`marcar_gestion.py` escribe la columna Q, saca copia fuera de OneDrive, abre navegador visible y reemplaza el Sheet. Si falla **no aborta**: el archivo local ya está escrito.

### PASO 6 — Cierre
Resumen, escalados, ciclos abiertos, y evento en Google Calendar (`NOTIFICAR_CALENDAR=true`, con invitado). Después `MODO_SIMULACION` vuelve a `true`.

---

## 2. La verificación por grupos

La palanca principal del proceso, y la regla que más veces se ha reformulado.

**Por qué existe:** un grupo que sale 120 veces en el reporte es **una pregunta, no 120**. Tener curso en MOODLE es propiedad del GRUPO — el *shortname* del curso es `COD_MATERIA/NUM_GRUPO` — no del estudiante.

**Medido sobre el reporte del 25/09** (515 filas procesables):

```
POS01/57ES6  120 filas   23% del reporte
POS01/55ES2   95              42% acumulado
POS01/55ES5   65              54%
POS01/55ES1   60              66%
TI001/55577   45              75%
POS01/55ES6   44              83%
... y 30 grupos de UNA sola fila
```

**Seis consultas deciden el 83% del día.**

Umbral actual: **10 filas** (`tabla_grupos.UMBRAL_VERIFICACION`, y `ejecutar_sinu` lo importa de ahí — un solo sitio).

### El orden, tal como lo fijó el dueño del proceso (26/09)

> No debes hacer las validaciones en la 05 y la 50 al tiempo. Primero haces una, verificar si sale o no sale y si tiene o no el check. Después de obtener el resultado, abres la siguiente.

> La 05 y la 50 es para verificar si tiene o no check y dejar eso plasmado en el reporte. **No es para procesar nada de vinculado o desvinculado.**

```
1. Pregunto a la 05  ──►  ¿SÍ tiene curso?  →  FIN. Se procesa por la 07.
                                                (la 50 ni se abre)
2. ¿No contestó, o dijo que NO?
       └──► AHORA se abre la 50, solo para esos grupos
              ├─ contesta      →  manda ella
              └─ no contesta   →  vale el NO de la 05, si lo hubo
3. ¿Ninguna contestó?  →  NO se descarta nada. Se procesa por la 07.
```

**Sin check → se marcan TODAS las filas de ese shortname de golpe**, como `NO TIENE CHECK EN MOODLE`, sin abrir SINU para ninguna.

**Garantía de solo-lectura:** `restricciones_sinu` mantiene `isef05` y `pacf50` fuera de `MODULOS_ESCRIBIBLES`. Un intento de ejecutar una acción allí aborta. **Solo ISEF07 escribe.**

**"No lo sé" nunca descarta.** El 25/09 se cerraron 68 filas de dos grupos SANOS como "validar a mano"; una se reparó después con un solo vincular en 44,8 s.

---

## 3. Por qué el día se alargó — el análisis

La pregunta era: *antes tardábamos 2-3 horas, ¿qué cambió?*

### El ritmo NO cambió

| Día | Filas | Min. de reloj | **min/fila** |
|---|---:|---:|---:|
| 04/09 | 117 | 239 | 2,05 |
| 21/09 | 205 | 355 | 1,73 |
| 23/09 | 116 | 295 | 2,55 |
| 25/09 | 443 | 756 | 1,71 |
| 26/09 | 34 | 67 | 1,96 |

**~2 min por fila, todo el mes.** El coste por acción tampoco: un reciclado costaba 94 s el 04/09 y 117 s hoy; un vincular simple, 49 s y 33 s. El lector de SINU no ha cambiado desde el 14/09.

### Lo que sí cambió

| | 04/09 | Hoy |
|---|---:|---:|
| Filas del reporte | 117 | 254 |
| **% que se recicla** | 72% | **89–98%** |
| % que queda verde | 86% | 35% |
| Lecturas fallidas | 1 | 12 |

Los días de 2-3 horas tenían **40-120 filas**. A los mismos 2 min/fila, 254 filas son ~8 h. **No se degradó el proceso: hay el triple de trabajo.**

### El dato que nadie había mirado

Comparando reportes crudos día contra día:

```
26/09   269 filas   →  247 son las MISMAS de ayer (92%)
```

Y no es de hoy: 93%, 89%, 88%, 78%, 77%, 81%, 92%. **El mismo trabajo vuelve cada día.**

Contrapeso importante: de las **687 filas que se dejaron VERDES** en todo el mes, solo **5 reaparecen hoy (1%)**. Es decir, lo que se confirma verde **sí se queda hecho**. Lo que vuelve son las filas que no llegaron a verde.

> **Esto no está explicado y es la pregunta más importante que queda abierta.** Si el 92% del reporte se repite pero lo verde no vuelve, entonces el reporte está lleno de filas que nunca llegan a procesarse — por lecturas fallidas, por grupos sin curso, o porque el día se corta antes de llegar a ellas.

---

## 4. Lo que se arregló el 26/09

| Arreglo | Evidencia |
|---|---|
| **Desmontaje del navegador** — `cerrar()` solo atrapaba `ErrorPlaywright`, pero un navegador muerto lanza un `Exception` pelado y, una capa arriba, salir del `with sync_playwright()` lanza `InvalidStateError`. Las dos escapaban **antes** de las líneas que validan el .xlsx y devuelven el resultado. | 5 intentos "fallidos" con **2 reportes buenos en disco** (269 filas, estructura válida). El 25/09 pasó igual a las 08:38. Tras el arreglo: **18 min y abortar → 2 min 47 s** |
| Aplicado a los 5 scripts críticos, incluido `ejecutar_sinu.py` (el único que escribe) | prueba parametrizada que falla si vuelve el `with` |
| **Cerrojo con un solo navegador** — la ventana de gracia abría hasta 7 Edge para leer 7 veces la misma celda | verificado en vivo, 1 arranque |
| **Paso 3 con reintento** sin duplicar el Sheet | 6 pruebas |
| **Filtro de ISEF05** espera a *editable* (120 s), no a *visible* (30 s) | los 4 grupos grandes de hoy fallaron con `Timeout 30000ms` sobre un campo visible y deshabilitado |
| **`lector_pacf50`** — la 50 estaba *"pendiente de documentar"* en `SKILL.md`; no existía lector | sondeada la pantalla real; verificado: `POS01/55ES2 → Moodle? = checked.gif` |
| **Verificación secuencial 05 → resultado → 50** | 11 pruebas |
| **`tabla_grupos.py`** — tabla dinámica por shortname sobre las filas procesables | 17 pruebas |
| Umbral de verificación a 10, en un solo sitio | cobertura 83% → 89% |

---

## 5. PENDIENTE — lo que no está resuelto

### 5.1 El ida y vuelta por `#home` · **sin solución**

Cambiar de módulo (07 → 05 → 07) navega por `#home`, y **cada paso destruye y repinta la aplicación entera** de SmartClient. Repintarla es lo que deja la grilla inerte: el filtro vuelve como `<input disabled>`.

Es la causa directa de `GrillaInerte`, del cortafuegos de las 3 lecturas vacías, de los 52 minutos del 25/09 contra una pantalla muerta.

**Lo que se intentó y NO funciona:**

- **Pestañas separadas.** Una pestaña nueva sobre el mismo contexto muestra el **formulario de login**. `sessionStorage` y `localStorage` están vacíos y hay 78 cookies compartidas: SINU guarda la sesión **en memoria de la aplicación**. Una pestaña nueva es una sesión nueva.
- **Mover `location.hash`.** Desde `#home`, poner `#pacf50` deja la pantalla con los campos del menú y ninguno de la rejilla. El hash solo cambia la URL.

> **Aviso sobre una medición errónea:** durante esta sesión se afirmó que el cambio por hash *sí* funcionaba, con tiempos y todo. **Era un falso positivo**: se dio por bueno porque aparecía el campo `cod_materia`, que existe en las dos pantallas. El módulo que se construyó sobre esa medición (`sesion_modulos.py`) fue **borrado**. Si alguien lee esto y ve la idea atractiva, que la vuelva a medir con un campo que solo exista en una de las dos pantallas.

### 5.2 El plazo de 120 s en ISEF05 · **sin medir**

Se subió de 30 s a 120 s para arreglar el fallo de hoy, **pero no se ha medido cuánto tarda la 05 cuando sí contesta**.

Riesgo introducido: si la 05 no responde, 4 grupos × 120 s = **8 min** antes de pasar a la 50, y otro tanto allí. En el peor caso la verificación cuesta más de lo que ahorra.

Evidencia: la prueba en seco de las 18:05 se agotó a los **400 s** con la verificación de 4 grupos aún en curso.

**Qué hace falta:** cronometrar la 05 sobre los grupos de un reporte real, y fijar el plazo con ese dato.

### 5.3 El 35% de las lecturas de ISEF07 falla · **sin diagnosticar**

Hoy: 12 de 34 filas en `no-se-pudo-leer`. De 38 lecturas, **8 se atascaron 124 s cada una** (el plazo de 120 s agotándose) y 30 fueron sanas a 11 s.

**El 74% del tiempo de lectura se va en lecturas que no devuelven nada.** Escalado a 254 filas serían ~53 lecturas atascadas ≈ **1,8 h tiradas**.

No se ha investigado por qué el filtro de cédula se queda deshabilitado.

### 5.4 El cortafuegos no salta cuando debería

Exige **3 lecturas vacías seguidas**. Hoy se alternaban con lecturas buenas, así que nunca llegó a 3 y el lote siguió gastando tiempo a 2,3 min/fila. Habría que contar por ventana (p. ej. 5 de las últimas 10) y no por racha.

### 5.5 La tabla de grupos no está en la Fase 1

Pedido expreso: que al limpiar el reporte —donde se marcan campos vacíos y espacios— salga ya el reparto por shortname.

Hoy `tabla_grupos.py` existe y funciona, pero **hay que llamarlo a mano**. No está integrado en la Fase 1 ni en la salida del paso 3.

### 5.6 Un grupo que PACF50 no encuentra

`61117/55529` (26P05) no aparece en PACF50: *"no mostró la fila en 60 s"*. Devuelve "no lo sé", que es la dirección segura, pero **no se sabe si es que el grupo no está, si el período es distinto, o si el lector falla con ese formato de código**.

### 5.7 Nada de esto está commiteado

Todos los cambios están en el árbol de trabajo. **No hay rama, no hay commit.** Si la máquina se reinicia, se pierden.

---

## 6. Lo que yo haría, en este orden

1. **Commitear lo de hoy** en una rama. Es lo único irreversible de la lista.
2. **Medir la 05** (§5.2) — una corrida corta de solo lectura. Sin ese dato, la palanca principal puede costar más de lo que ahorra.
3. **Diagnosticar las lecturas atascadas** (§5.3) — ~1,8 h por reporte.
4. **Integrar la tabla de grupos en la Fase 1** (§5.5) — barato, y da visibilidad antes de arrancar.
5. **El ida y vuelta por `#home`** (§5.1) — el de más valor y el único sin camino conocido.

**Lo que no hay que esperar:** que 254 filas con reciclado obligatorio quepan en 2 horas. A los ~2 min/fila medidos todo el mes, y siendo esos 2 minutos lo que tarda SINU en ejecutar *desvincular* + *vincular*, un reporte de 254 filas es un día largo. Las palancas reales son **descartar grupos enteros** (§2) y **dejar de perder tiempo en lecturas que fallan** (§5.3).
