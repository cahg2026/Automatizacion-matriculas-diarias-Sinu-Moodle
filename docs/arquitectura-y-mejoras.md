# Arquitectura, puntos frágiles y propuestas

**Para:** quien mantenga o herede este proyecto.
**Fecha del análisis:** 16/09/2026, sobre `main` en `42eae4a` + los cambios de ese día.
**Método:** lectura del código y de los diarios de ejecución reales, no de la documentación. Donde una afirmación viene de una corrida concreta, se cita la fecha.

Este documento **no** repite la guía de instalación ([`EMPEZAR-AQUI.md`](../EMPEZAR-AQUI.md)) ni el manual de operación ([`README.md`](../README.md)). Habla de cómo está construido el sistema, dónde se rompe y qué conviene cambiar.

---

## 1. La arquitectura en una página

Cuatro capas, con una regla que se respeta bien: **cada una solo conoce a la de abajo.**

```
scripts/dia_completo.py        orquestador del día (subprocess)
        │
        ├── scripts/*.py       una etapa cada uno, CLI propio y cerrojos propios
        │       │
        │       └── src/moodle_sinu/lector_*.py, ejecutor_*.py, subidor_*.py
        │                   │        operaciones de dominio
        │                   │
        │                   └── src/moodle_sinu/selectores_*.py
        │                               el único sitio que sabe de DOM
        │
        └── src/moodle_sinu/restricciones_sinu.py
                    matriz de permisos, atravesada por todo acceso
```

Dos decisiones estructurales que merecen reconocerse porque son correctas y poco habituales:

- **`selectores_*.py` concentra todo el conocimiento del DOM.** En una automatización RPA esto es lo que separa un proyecto mantenible de uno desechable. Cada constante lleva la fecha en que se verificó contra la pantalla real y, muchas veces, el error que se cometió antes.
- **`restricciones_sinu.py` es un punto de paso obligatorio.** `exigir_modulo_legible` / `exigir_modulo_escribible` se invocan desde cada operación, no desde un sitio central que se pueda olvidar. `MODULOS_SOLO_LECTURA` se deriva de las otras dos listas, así que no pueden desincronizarse. Es una barrera de capacidades bien modelada.

### 1.1 Modelo de cuentas y sesiones

Importa tenerlo claro porque las dos mitades se comportan de forma muy distinta, y confundirlas lleva a conclusiones equivocadas sobre qué es frágil y qué se puede paralelizar.

| Sistema | Cuenta | Quién la tiene | Cómo se comporta |
|---|---|---|---|
| **Power BI** | `cunbre@cun.edu.co`, **del área y compartida** | Todo el equipo, ya guardada y abierta en sus equipos | Estable. No es el punto frágil |
| **SINU** | **Personal de cada operador** (`SINU_USUARIO` / `SINU_PASSWORD` en su propio `.env`) | Solo su dueño | Cada matrícula modificada queda **auditada a su nombre** |
| **Google** (Drive, Calendar) | **Personal de cada operador** | Solo su dueño | La más frágil: caduca sola y exige 2FA a mano (incidentes nº 8 y nº 12) |

Dos consecuencias:

- **Las credenciales de SINU no se comparten nunca.** No es una preferencia, es trazabilidad: usar la cuenta de otra persona le atribuye cambios que no hizo. `EMPEZAR-AQUI.md` lo dice de forma explícita en el paso 4.
- **La sesión compartida (Power BI) es la que menos problemas da**, precisamente porque todos la tienen viva. Los incidentes de sesión que han tumbado corridas —el nº 8 y el nº 12— fueron los de **Google**, que es personal y caduca. Cualquier trabajo de resiliencia sobre sesiones debe apuntar ahí, no a Power BI.

**Estado (event sourcing sin proyección):** tres diarios JSONL de solo-añadir en `logs/`.

| Diario | Qué guarda | Quién lo consume |
|---|---|---|
| `resultados_etapa4.jsonl` | Un apunte por unidad (cédula + materia) | `--saltar-hechas`, el coloreado del Sheet, `resumen_dia` |
| `ciclos_abiertos.jsonl` | Aperturas y cierres de reciclado | `ciclos_abiertos()`, que reproduce el archivo entero |
| `escalado_isef05_pacf50.jsonl` | Casos para validar a mano | `escalados_pendientes()` |

---

## 2. El catálogo real de incidentes

El encargo hablaba de 7. Contando los que están documentados en comentarios del código con fecha y consecuencia, son **al menos 12**. Vale la pena tenerlos juntos porque el patrón que forman es más informativo que cada uno por separado.

| # | Fecha | Incidente | Causa raíz | Dónde vivía |
|---|---|---|---|---|
| 1 | 01/09 | La grilla se leía cargando: «0 a 0 de 0» → «el estudiante no tiene asignaturas». 4 diagnósticos falsos | Falta de espera explícita | DOM |
| 2 | 01/09 | `unchecked_Disabled.gif` no estaba en la lista → 8 filas descartadas como ilegibles, justo las que había que vincular | Enumeración incompleta de un estado | DOM |
| 3 | 01/09 | Timeout de 120 s corto: el desvincular tardó **124 s** | Presupuesto de tiempo global para operaciones heterogéneas | Config |
| 4 | 03/09 | Se creía que `COD_MATERIA` no era filtrable → la acción se desbordó a **34 asignaturas** cuando el reporte pedía 5 | Afirmación falsa heredada de la documentación de negocio | Dominio |
| 5 | 02/09 | `config/.env.respaldo_*` llegó a GitHub **con contraseñas** | Patrón de `.gitignore` por nombre exacto | Repo |
| 6 | 07/09 | Tres defectos: bitácora en UTF-16, rotación del diario mal puesta, `--saltar-hechas` que no se pasaba | Capa de orquestación no cubierta por pruebas | Orquestación |
| 7 | 08/09 | Corrida entera «real» que **simuló en silencio**: `os.environ` heredaba `true` mientras el `.env` decía `false` | Estado cruzando frontera de proceso por dos vías | Orquestación |
| 8 | 08/09 | Sesión de Google caída con **todas** las cookies presentes → falló en el paso 3, con el cerrojo ya abierto | Comprobar presencia en vez de comprobar efecto | Sesión |
| 9 | 08/09 | Kaspersky (AMSI) bloqueó `dia_completo.ps1` **al analizarlo** → fallo mudo, sin bitácora | Tecnología del orquestador | Entorno |
| 10 | — | Drive no tiene `input[type=file]`; la subida va por *drop*. El headless fue una pista falsa | Supuesto sobre la UI | DOM |
| 11 | 09/09 | A las 08:05 el tablero aún era de ayer | Suposición sobre la hora de refresco | Negocio |
| 12 | 16/09 | Google pidió reverificar identidad (2FA) → la corrida de las 9:00 murió en el paso 0 | Dependencia de sesión humana | Sesión |

### Lo que dice el patrón

Ordenando por capa: **10 de 12 incidentes ocurrieron en la frontera con el mundo exterior** (DOM, sesión, entorno, orquestación entre procesos). Ninguno en la lógica de negocio pura.

Y esa es exactamente la capa que las 539 pruebas **no** cubren. El propio proyecto lo dice en [`dia_completo.py`](../scripts/dia_completo.py): *«Los tres defectos del 07/09/2026 vivían todos en la capa que no se podía probar.»*

> El diagnóstico central de este análisis: **la suite de pruebas es grande y sana, pero está apuntando donde no ocurren los fallos.**

Prueba de que sigue vigente: el 16/09, sondeando ISEF05, **volví a cometer el incidente nº 2** — interpreté `unchecked_Disabled.gif` como marcado, porque contiene la subcadena `checked_Disabled`. El proyecto ya había pagado ese error el 01/09 y lo tenía documentado; aun así no había nada que impidiera repetirlo, porque ninguna prueba toca esa capa.

---

## 3. Puntos frágiles

### 3.1 El cerrojo de escritura vive en el archivo de configuración

`fijar_simulacion()` **reescribe `config/.env`** para abrir y cerrar el permiso de escritura. Es decir: un archivo de configuración del usuario se usa como estado de ejecución mutable.

El `finally` de `dia_completo.py` lo cierra siempre ante excepciones, y eso está bien resuelto. Pero no cubre un `kill -9`, un corte de luz ni un reinicio de Windows por actualizaciones — y entonces **el `.env` queda en `false`**, con el permiso de escritura abierto para la siguiente ejecución, incluida la de las 9:00. El propio README registra que estuvo abierto seis días seguidos (01–07/09) cuando dependía de que alguien se acordara.

Es además el origen directo del incidente nº 7: el mismo valor viajaba por dos caminos (archivo y `os.environ`) que podían discrepar.

### 3.2 Nada marca los escalados como resueltos

`_apuntar_escalado()` escribe siempre `"resuelto": False`. `escalados_pendientes()` filtra por ese campo. **No existe ningún código que lo ponga en `True`** ([`ejecutor_sinu.py:367`](../src/moodle_sinu/ejecutor_sinu.py#L367)).

Consecuencia: la lista de pendientes crece de forma monótona y para siempre. Hoy `escalado_isef05_pacf50.jsonl` pesa 22 KB y contiene casos del 07/09 que ya no significan nada. Un operador que la mire no puede distinguir lo de hoy de lo de hace diez días, así que dejará de mirarla — y ese es el modo de fallo de cualquier alerta que no se puede cerrar.

### 3.3 Un navegador y un login de SINU por periodo

`procesar_dia.py` lanza un subproceso `ejecutar_sinu.py` por periodo ([`procesar_dia.py:173`](../scripts/procesar_dia.py#L173)). Cada uno abre su propio contexto de Playwright y vuelve a entrar en SINU.

En la corrida del 16/09 eso fueron **7 arranques de Chrome y 7 inicios de sesión** para 25 unidades de trabajo. Cuesta tiempo, pero sobre todo multiplica por siete la exposición a la clase de fallo nº 8 y nº 12: cada login es una oportunidad de que la sesión se caiga a mitad del día.

El aislamiento entre periodos tiene una razón buena (el filtro de Periodo se fija una vez por sesión) y **no hay que romperlo**. Pero el aislamiento que hace falta es el del *filtro*, no el del *proceso*.

### 3.4 Presupuestos de tiempo globales para operaciones muy distintas

`TIMEOUT_OPERACION_SEG=30`, `TIMEOUT_RENDER_SEG=120`, `TIMEOUT_DESCARGA_SEG=300`. Pero las operaciones reales del 16/09 fueron de **47 s a 362 s, con media de 159 s**.

Un único presupuesto no puede servir a la vez a un filtro de columna (1 s) y a un sondeo de check (270 s). El proyecto ya lo parcheó una vez tras el incidente nº 3, con una constante específica. La deuda es que sigue sin ser un concepto de primera clase.

### 3.5 Reintentar sin clasificar la causa

`INTENTOS_HASTA_ESCALAR = 3`, con 90 s de sondeo cada uno, se aplica igual a un fallo transitorio que a una imposibilidad estructural.

El caso `DTA32/55598` lo ilustra: 4 estudiantes × 3 intentos × 3 días, ~24 minutos por corrida, contra un grupo sin curso en Moodle donde vincular **nunca** iba a funcionar. La consulta a ISEF05 que se añadió el 16/09 resuelve esa causa concreta; el principio general —**clasificar antes de reintentar**— sigue sin estar modelado.

### 3.6 Los diarios se reproducen enteros, sin compactación ni versión de esquema

`ciclos_abiertos()` lee y reproduce `ciclos_abiertos.jsonl` completo en cada arranque para calcular el estado actual. El archivo va por 87 KB y solo crece. Es *event sourcing* sin *snapshot* y sin campo de versión: el día que cambie la forma de un apunte, los viejos no se podrán distinguir de los nuevos.

No es urgente. Es previsible.

---

## 4. Propuestas

Ordenadas por **valor / riesgo**, respetando la regla de no romper lo que funciona. Las tres primeras son aditivas: nada de lo que hoy funciona cambia de comportamiento.

### P1 — Pruebas de DOM sobre capturas reales ⭐ *la de mayor valor*

**Problema:** 10 de 12 incidentes en la capa sin pruebas.

**Propuesta:** guardar HTML real de las pantallas como *fixtures* y probar los lectores contra ellos.

La infraestructura ya existe y no se está aprovechando: `captura_dom.py` vuelca el DOM, las trazas de Playwright guardan instantáneas, y una sonda hace `page.content()` en una línea. Falta el paso de convertir eso en pruebas.

```
tests/fixtures/dom/
  isef07_grupos_8_asignaturas.html      el caso del 01/09 (unchecked_Disabled)
  isef07_grilla_cargando.html           el «0 a 0 de 0» del 01/09
  isef05_dta32_55598_sin_curso.html     el caso del 16/09
  isef05_aed31_55522_con_curso.html     el control del 16/09
```

Las funciones de lectura ya están casi preparadas: el grueso de `leer_filas_grupos` y de `consultar_grupo` es interpretar un diccionario que devuelve `page.evaluate`. Basta extraer esa interpretación a una función pura que reciba el diccionario, y probarla con los datos capturados.

Habría atrapado los incidentes 1, 2 y 10 — y mi repetición del nº 2 el 16/09.

**Riesgo:** ninguno. Solo se añaden pruebas.

### P2 — Cerrar el ciclo de los escalados

**Problema:** 3.2, la lista que solo crece.

**Propuesta:** dos piezas pequeñas.

1. Un comando `scripts/resolver_escalado.py --materia DTA32 --grupo 55598 --nota "curso creado en Moodle"` que añada un apunte `{"resuelto": true, ...}`. Encaja con el diseño de solo-añadir que ya tienen.
2. Que la consulta a ISEF05 del 16/09 **resuelva sola** los escalados cuya causa ya explicó: si ISEF05 dice que no hay curso, el caso deja de ser «pendiente de validar» y pasa a ser «pendiente de crear el curso», que es otra cosa y ya se marca como tal.

**Riesgo:** bajo. `escalados_pendientes()` no cambia de forma; solo empieza a poder devolver menos.

### P3 — Presupuestos de tiempo con nombre

**Problema:** 3.4.

**Propuesta:** sustituir los tres timeouts globales por un diccionario de presupuestos por operación, con los valores **medidos**, no estimados:

```python
PLAZOS = {
    "filtro_columna":    Plazo(esperado=2,   techo=30),
    "leer_grilla":       Plazo(esperado=15,  techo=60),
    "ejecutar_accion":   Plazo(esperado=40,  techo=180),   # medido: 124 s el 01/09
    "sondeo_check":      Plazo(esperado=90,  techo=300),
    "exportar_powerbi":  Plazo(esperado=120, techo=300),
}
```

El valor no es solo el techo: es que `esperado` permite **avisar cuando algo tarda el triple de lo normal sin llegar a fallar**, que es la señal temprana que hoy no existe.

**Riesgo:** medio — toca muchos sitios. Hacerlo por etapas, empezando por ISEF07, que es la que escribe.

### P4 — Una sesión de navegador para todo el día

**Problema:** 3.3, siete logins.

**Propuesta:** que `procesar_dia.py` abra **un** contexto y lo pase a la etapa 4 como función, no como subproceso; el filtro de Periodo se sigue fijando una vez por periodo dentro de esa sesión única.

El aislamiento real que hace falta —que un periodo no arrastre el estado del filtro de otro— lo da `fijar_periodo()`, que ya verifica el valor después de fijarlo. El aislamiento por proceso es un efecto secundario de cómo creció el código, no un requisito.

**Riesgo: el más alto de las cuatro, y por eso va la última.** El aislamiento por proceso también hace que un cuelgue de un periodo no se lleve los demás. Si se hace, debe conservarse esa propiedad con un `try/except` por periodo y una comprobación de sesión viva entre uno y otro. **No hacerlo si no hay tiempo de probarlo bien**: hoy funciona.

### P5 — Sacar el cerrojo del `.env`

**Problema:** 3.1.

**Propuesta:** los hijos ya reciben `--ejecutar-de-verdad` de forma explícita. El paso siguiente es que **la bandera explícita mande** y que `MODO_SIMULACION` del `.env` quede solo como valor por defecto para invocaciones manuales. Así `fijar_simulacion()` deja de necesitar reescribir el archivo, y desaparece la ventana en la que un corte de luz deja el permiso abierto.

**Riesgo:** alto si se hace mal, porque toca el mecanismo de seguridad central. **Recomendación: no tocarlo por ahora.** Se documenta aquí porque es deuda real y conviene que esté escrita, no porque haya que pagarla ya. Si algún día se hace, con una prueba que verifique que un hijo sin bandera **nunca** escribe, pase lo que pase en el `.env`.

### Lo que NO recomiendo

**Paralelizar el procesado de unidades.** Es el primer instinto al ver 66 minutos para 25 unidades, y aquí es un error. No por las personas —cada operador usa su propia cuenta de SINU, ver §1.1— sino por el estado global de la pantalla:

- **Dentro de una corrida hay una sola sesión de SINU autenticada, y el estado de ISEF07 es global a esa sesión.** El filtro de Periodo y el filtro de columna de la grilla Grupos no son de una unidad: son de la pantalla. Dos unidades en paralelo se pisarían el filtro, y acotar la grilla a `COD_MATERIA` es **justo lo que confina la acción a una asignatura**. Sin esa garantía vuelve el incidente nº 4: el desbordamiento a 34 asignaturas del 03/09.
- **La guarda de desborde dejaría de ser válida.** `AccionSeDesbordo` compara una foto de todas las asignaturas del estudiante antes y después de actuar. Si otro trabajador toca la misma sesión entre las dos lecturas, esa comparación mide ruido: saltaría sin motivo o, peor, dejaría pasar un desborde real.
- **Abrir varias sesiones simultáneas con el mismo usuario tampoco vale.** Es la misma cuenta personal entrando varias veces a la vez en un ERP; el propio flujo avisa de lo contrario en el paso 4: «NO uses SINU mientras corre: entra con la misma cuenta».

La regla de «una persona al día» es un asunto **distinto** y no tiene que ver con sesiones compartidas: los tres diarios viven en `logs/` de cada equipo, así que la máquina de un segundo operador no puede saber qué hizo ya la del primero.

La palanca correcta no es hacer más cosas a la vez, sino **dejar de hacer las imposibles** — que es lo que dio 24 minutos el 16/09, más de lo que daría cualquier paralelismo seguro.

---

## 5. Sobre el entorno y las dependencias

Esta parte del encargo **ya estaba hecha en el repositorio**, y bien. Se deja constancia de lo verificado el 16/09 en vez de rehacerlo:

- **Python 3.11** ya está fijado, en `requirements.txt`, en `EMPEZAR-AQUI.md` (3.11.9) y en el `py -3.11` del arranque. Es la elección correcta: Playwright 1.47 lo soporta de forma estable y 3.11 trae las mejoras de rendimiento y de trazas de excepción sin la exposición de una versión recién salida en un equipo corporativo con Kaspersky. **No cambiarlo.**
- **`requirements.txt` ya congela versiones exactas** (`==`) para las cuatro dependencias que hay: `openpyxl`, `playwright`, `python-dotenv`, `pytest`. **`pandas` no es una dependencia de este proyecto** y no aparece en ningún import; el `.xlsx` se maneja con `openpyxl` directamente.
- **`config/.env.example` ya existe** y documenta cada variable con el incidente que la motivó.
- **`.gitignore` ya cubre** `config/.env*` con excepción de la plantilla — precisamente por la fuga del 02/09.
- **`playwright install` no hace falta** con la configuración por defecto (`NAVEGADOR_CANAL=chrome` usa el Chrome instalado); está documentado en `README.md:37` y `primera_vez.py` solo lo sugiere como alternativa.
- **El certificado de Kaspersky** ya está resuelto: `config.py` exporta `NODE_EXTRA_CA_CERTS` al importarse, y `primera_vez.py` detecta la interceptación TLS midiendo el tamaño del certificado de Google y da el comando exacto de exportación.
- **El Programador de tareas** ya está cubierto por `programar_9am.py` y el panel de `Flujo diario.bat`.

Lo único que se corrigió el 16/09 fue la deriva del número de pruebas (532 → 539) en `EMPEZAR-AQUI.md` y `README.md`, y se reformuló para que el criterio sea «dice `passed` y no aparece `failed`», que no caduca.
