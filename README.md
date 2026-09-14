# Automatización — Validación Moodle vs. SINU

Automatización del proceso diario de validación y vinculación de estudiantes
matriculados a sus cursos en Moodle, a partir del reporte comparativo
Moodle vs. SINU de Power BI.

- **Documento de referencia:** `Plan_Automatizacion_Moodle_SINU.docx` (v1.0, 19/08/2026)
- **Python:** 3.11.9

## Estado por etapas

| # | Etapa | Estado |
|---|---|---|
| — | **Fase 1** — parser + validación del `.xlsx` | ✅ Implementada y probada |
| 1 | Exportación desde Power BI (Playwright) | ✅ Verificada end-to-end (21/08/2026), visible y headless |
| 2 | Subida del Sheet a Drive (RPA, sin API) | ✅ Verificada (03/09/2026) — **exige `--visible`**, ver *La subida no funciona sin ventana* |
| 3a | Plan de trabajo (cédulas por periodo) | ✅ Implementado |
| 3 | Clasificación de casos en SINU — **modo lectura** | ✅ Verificada (01/09/2026): lectura real de la grilla Grupos |
| 4 | Ejecución en ISEF07 (vincular / reciclar) | ✅ Verificada end-to-end (01/09/2026) — 3 cerrojos, `MODO_SIMULACION=false` |
| 4b | Confirmación del check tras cada acción | ✅ Implementada (03/09/2026) — se relee la grilla, no se cree al diálogo |
| 4c | Consulta automática de ISEF05/PACF50 + anotación en el Sheet | ⏳ **Falta** — los casos se detectan y se registran, resolverlos es manual |
| 5 | Escritura de colores + validación en el Sheet | ⏳ |
| 6 | Programación diaria (Task Scheduler) | ⏳ |

## Instalación

```powershell
# Python real (el alias de Microsoft Store no sirve). Ajustar a donde este
# instalado; si no lo esta: winget install Python.Python.3.11
$PY = "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"

& $PY -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium

Copy-Item config\.env.example config\.env   # y rellenar
```

## Puesta en marcha en un equipo nuevo

```powershell
git clone https://github.com/cahg2026/Automatizacion-matriculas-diarias-Sinu-Moodle.git
cd Automatizacion-matriculas-diarias-Sinu-Moodle

py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

.\.venv\Scripts\python.exe scripts\primera_vez.py
```

`scripts/primera_vez.py` es el asistente: recorre **todo lo que no viaja en el
repositorio** —que es, a propósito, todo lo sensible— y lo verifica sobre el
terreno en vez de darlo por supuesto.

| Paso | Qué comprueba |
|---|---|
| 0 | Python 3.11, el venv, Playwright, Chrome |
| 1 | Crea `config/.env` desde la plantilla y dice qué claves faltan |
| 2 | El perfil de Chrome dedicado |
| 3 | Si el antivirus intercepta el HTTPS, y cómo exportar su CA |
| 4 | Abre Power BI, SINU, Drive y Calendar para entrar con **sus** credenciales |
| 5 | Comprueba cada sesión **navegando**, no contando cookies |

`--revisar` solo diagnostica, sin crear nada ni abrir el navegador.

### Las cuentas: cuáles son suyas y cuál se comparte

| | |
|---|---|
| **SINU** | **suya.** Necesita permiso sobre ISEF07 |
| **Google** | **suya.** Decide a qué Drive y a qué Calendar se escribe |
| **Power BI** | compartida del área |

La de SINU es personal por una razón que conviene entender: **cada vinculación
queda registrada a nombre de quien la hace.** Usar la cuenta de otra persona
atribuiría a esa persona modificaciones de matrícula que no hizo.

Su cuenta de Google necesita además **permiso de escritura en la carpeta de
Drive** `REPORTES 2026`. Es un permiso que alguien tiene que conceder antes; el
código no puede resolverlo y la etapa 3 fallaría al subir el Sheet.

### Por qué se verifica navegando y no por cookies

El 08/09/2026 el perfil tenía 88 cookies y «todas las de sesión de Google
presentes» — mientras Google había invalidado la sesión del lado del servidor.
El paso 0 dio el visto bueno, se exportó Power BI, se abrió el cerrojo de
escritura, y el fallo salió en el paso 3.

**Una cookie presente dice que el navegador la guarda, no que el servidor la
acepte.** Lo único que lo dice es pedirle una página y mirar si redirige al
login. Eso es lo que hace el paso 5, y lo que hace `probar_perfil.py`.

### Si el antivirus intercepta el HTTPS

Con Kaspersky —y con cualquier antivirus que analice tráfico cifrado— pasa
esto: reemite los certificados con su propia CA y la deja en el almacén de
Windows. Chrome y Python la aceptan porque leen ese almacén; **Playwright no**,
porque su driver trae sus propias CAs. El síntoma es

```
self-signed certificate in certificate chain
```

al leer el Sheet, y el 07/09/2026 dejó 13 matrículas sin procesar en 3 periodos
mientras el navegador entraba a SINU sin problema.

Se resuelve una vez, exportando esa CA a `config/ca_kaspersky.pem`:

```powershell
$c = Get-ChildItem Cert:\LocalMachine\Root |
     Where-Object { $_.Subject -like '*Kaspersky*' } |
     Select-Object -First 1
$b = [Convert]::ToBase64String($c.RawData, 'InsertLineBreaks')
"-----BEGIN CERTIFICATE-----`n$b`n-----END CERTIFICATE-----" |
    Set-Content config\ca_kaspersky.pem -Encoding ascii
```

El proyecto la detecta sola al arrancar. **No se versiona** (`*.pem` está en el
`.gitignore`): cada equipo exporta la suya.

Se prefirió esto a `ignore_https_errors=True` porque añadir una raíz concreta
mantiene la validación del certificado, mientras que desactivarla la quita
entera y daría por buena cualquier interceptación, no solo la conocida.

### La primera prueba: en simulación

```powershell
.\.venv\Scripts\python.exe scripts\dia_completo.py
```

Sin `--ejecutar-de-verdad` recorre las seis etapas, entra a SINU, lee las
grillas y dice qué haría — **sin escribir nada**. Es el valor por defecto de la
plantilla (`MODO_SIMULACION=true`), así que un clon nuevo arranca seguro.

### Antes de que más de una persona procese de verdad

Separar cuentas resuelve el choque de sesiones en SINU, pero no basta: el
diario `logs/resultados_etapa4.jsonl` es **local a cada equipo**, así que
`--saltar-hechas` no sabe lo que hizo el otro.

El caso malo no es el trabajo duplicado. Es que uno recicle —desvincular y
volver a vincular— una matrícula que el otro acaba de dejar bien, y que un
fallo en esa ventana deje al estudiante desvinculado.

**El código sí lo guarda.** Lo único compartido entre equipos es Drive, y de
ahí sale la señal: si al subir el Sheet ya existe un reporte de hoy, es que el
flujo ya se ejecutó —aquí o en otro equipo— y la etapa 3 aborta:

```
Ya hay un reporte de 14/09/2026 en Drive: 'REPORTE 14/09/2026 #82'.
Eso significa que el flujo de hoy YA SE EJECUTO, en este equipo o
en el de otra persona.

Se aborta aqui, ANTES de tocar ninguna matricula en SINU.
```

Que salte ahí es lo que importa: **la etapa 3 va antes de la 4**, así que se
aborta sin haber tocado una sola matrícula.

Queda una ventana estrecha: si dos equipos llegan a la subida en el mismo
segundo, ninguno ve el reporte del otro. Con la tarea a las 9:00 en ambos, la
subida cae hacia las 9:05 y la coincidencia exacta es improbable, pero no
imposible. Para eliminarla haría falta un cerrojo de verdad; mientras tanto, lo
sensato sigue siendo **una sola persona con `--ejecutar-de-verdad` al día**, y
el resto en simulación.

## El día completo en un comando

```powershell
# El día, de verdad. Es el comando de todas las mañanas.
.\.venv\Scripts\python.exe scripts\dia_completo.py --ejecutar-de-verdad

# Ensayo: recorre todo y dice qué haría, sin escribir en SINU
.\.venv\Scripts\python.exe scripts\dia_completo.py

# Solo hasta dejar el Sheet subido, sin tocar SINU
.\.venv\Scripts\python.exe scripts\dia_completo.py --hasta-subir
```

`scripts/dia_completo.py` encadena las seis etapas. Su razón de ser es que **no
haya que copiar valores de una salida a la siguiente**: eso era lo que
convertía el proceso diario en algo manual y frágil.

| Paso | Qué |
|---|---|
| 0 | Perfil de navegador y **sesión de Google, comprobada de verdad** |
| 1 | **Cerrojo**: ¿se actualizó el tablero HOY? Si no, avisa y **no exporta** |
| 2 | Power BI → `.xlsx` en `data\raw\` |
| 3 | Fase 1: calidad, orden A–Z por periodo, subida del Sheet |
| 4 | ISEF07: procesa las matrículas, periodo por periodo |
| 5 | Escribe la columna Q y sube el Sheet marcado |
| 6 | Cierre: ciclos a medias, escalados y aviso con métricas |

### Por qué es Python y no PowerShell

Hubo un `dia_completo.ps1`. El 08/09/2026 Kaspersky empezó a bloquearlo:

```
dia_completo.ps1: 1 Carácter: 1
Este script contiene elementos malintencionados y ha sido bloqueado
por el software antivirus.
FullyQualifiedErrorId : ScriptContainedMaliciousContent
```

El bloqueo es de AMSI y ocurre al **analizar** el archivo, antes de su primera
instrucción: no dejaba ni bitácora, así que el fallo era mudo — devolvía código
1 y cero salida. Se descubrió capturando `stderr`, que es donde AMSI escribe.

**No se reescribió el `.ps1` "para que no lo detecte".** Remodelar código hasta
esquivar una regla de antivirus es, en la forma, evasión de detección, y en el
fondo es adivinar contra una heurística opaca que puede cambiar cualquier día.
Se cambió de tecnología, que es lo que resuelve el problema.

La migración además dio tres cosas que el `.ps1` no podía:

- **La lógica del día entra en pytest.** Sus tres defectos del 07/09/2026 —la
  bitácora en UTF-16, la rotación del diario colocada antes de tiempo y el
  `--saltar-hechas` que no se pasaba nunca— vivían todos en la capa que no se
  podía probar. Ahora hay 19 pruebas sobre esa lógica.
- **`subprocess` recibe listas de argumentos**, así que no hay shell que
  reinterprete comillas. Con una ruta que tiene espacios *y* acentos, eso quita
  toda una clase de fallos.
- **La bitácora recoge stdout y stderr.** El `.ps1` perdía stderr, que es justo
  donde Python escribe sus logs.

Los dos `.ps1` quedan en `docs/retirado/` como referencia histórica, sin uso.

### Contar cookies no dice si la sesión sirve

El 08/09/2026 el paso 0 dio el visto bueno con la sesión de Google **muerta**.
El perfil tenía 88 cookies y las de sesión «todas presentes» — y Google las
había invalidado del lado del servidor. Resultado: se exportó Power BI, se
abrió el cerrojo de escritura, y el fallo salió en el paso 3 al subir el Sheet.

**Una cookie presente dice que el navegador la guarda, no que el servidor la
acepte.** Lo único que lo dice es pedirle una página.

Por eso `probar_perfil.py` ahora navega a Drive y mira si redirige:

| Salida | Significado |
|---|---|
| `0` | Drive respondió sin pedir login: la sesión sirve |
| `5` | la sesión no sirve → el flujo se detiene **en el paso 0** |

Y distingue tres motivos, porque cada uno se arregla de otra forma:

- **Reverificar identidad** (`confirmidentifier`) — «Demuestra que eres tú».
  Es el segundo factor; solo lo resuelve una persona. Fue el caso del 08/09.
- **Elegir cuenta** (`accountchooser`) — la sesión existe, hay varias cuentas.
  Fijar `/u/0/` no lo salta.
- **Sin sesión** (`signin`, `ServiceLogin`) — no hay sesión válida.

Se resuelve una vez, a mano, y queda guardada en el perfil:

```powershell
.\.venv\Scripts\python.exe scripts\probar_perfil.py --iniciar-sesion
```

`--sin-exigir-sesion` desactiva la comprobación, para diagnosticar el perfil en
sí sin que la sesión decida el resultado.

### El cerrojo del día: no procesar datos de ayer

Antes de exportar, `scripts/verificar_actualizacion.py` lee del tablero el
texto `Datos actualizados el 8/9/26` y lo compara con hoy.

De dónde sale ese dato **está medido, no supuesto** (se sondeó con
`scripts/sondear_actualizacion.py` el 08/09/2026):

- El `.xlsx` exportado **no** lo trae: su única fila de pie lista los filtros.
- Las tarjetas del tablero tampoco: solo hay `MATRICULADO` y `NO MATRICULADO`.
- Sí lo trae la **barra de herramientas superior** de Power BI Service, a la
  derecha de `ValidacionMoodle |` y a la izquierda del buscador global. **No
  está en el lienzo del informe**, y por eso ningún localizador de visuales lo
  ve. Cadena de ancestros medida:

```
SPAN.data-updated          ← el texto: "Datos actualizados el 8/9/26"
 └ BUTTON.info-bar         ← de aquí sale la flecha: es un desplegable
   └ ARTIFACT-INFO
     └ DIV.topNavLeft
       └ HEADER
         └ TRIDENT-HEADER#header   ← la barra principal
```

El localizador es **`#header span.data-updated`**, no el texto. La clase es
semántica y no depende del idioma; buscar «Datos actualizados» se rompería el
día que la interfaz saliera en inglés. Se acota a `#header` para que no pueda
confundirse nunca con contenido del lienzo.

Hay tres capas: la clase, luego el texto dentro de `#header`, y por último un
barrido de la página. El log dice por cuál entró — si algún día dice
«BARRIDO», es señal de que conviene volver a sondear. Una excepción importante:
si el nodo aparece pero su texto **no** se puede interpretar, se falla en vez de
seguir probando localizadores. Eso significa que el tablero cambió de formato, y
buscar hasta encontrar cualquier fecha que encaje sería peor que decirlo.

Hay que esperar el lienzo antes de mirar. Sobre la pantalla de carga de Power BI
todo sale vacío, y eso se leería como «no hay fecha» en vez de «aún no ha
cargado»: pasó en el primer sondeo, y lo delató la captura de pantalla.

La fecha se interpreta **día/mes/año** porque el navegador se abre con
`POWERBI_IDIOMA=es-CO`. Hay una guarda: si sale una fecha futura se falla en vez
de devolver un dato del revés, que es lo que ocurriría si el idioma cambiara.

Códigos de salida, y por qué son tres y no dos:

| | |
|---|---|
| `0` | coincide con hoy → seguir con la descarga |
| `3` | **anterior** a hoy → alerta crítica y parar |
| `4` | **no se pudo leer**, o fecha posterior a hoy → alerta distinta y parar |

El 3 y el 4 van aparte porque la acción de la persona difiere: en un caso se
reclama al departamento de datos; en el otro se mira si el tablero cambió de
forma. **No saberlo no es lo mismo que saber que está viejo.**

El criterio de falla es «**anterior** a hoy», no «distinto de hoy», y la
diferencia importa: una fecha *posterior* no es un tablero viejo, es una lectura
girada (día y mes al revés), y se rechaza como ilegible en vez de anunciarse
como retraso.

### Avisos

Dos canales, los dos por `config/.env`, y un respaldo que siempre funciona.

```
NOTIFICAR_WEBHOOK=https://<...>          # Teams o Slack. Recomendado.

NOTIFICAR_SMTP_SERVIDOR=smtp.office365.com
NOTIFICAR_SMTP_USUARIO=<cuenta>
NOTIFICAR_SMTP_PASSWORD=<contraseña de aplicación>
NOTIFICAR_DESTINATARIOS=alguien@cun.edu.co
```

El webhook es el camino corto: una URL, sin contraseñas que rotar, y el destino
va dentro. Con Microsoft 365, el correo exige una **contraseña de aplicación**:
la organización pide segundo factor y el SMTP plano no lo pasa.

**Para avisar a más personas sin montar nada**, se añaden como invitados del
evento de Calendar y Google manda su propia invitación:

```
NOTIFICAR_INVITADOS=alguien@cun.edu.co, otro@cun.edu.co
```

Es el camino de entrega más fiable que hay aquí: no depende de ningún servidor
nuestro. Aplica a los dos avisos, el de éxito y el de tablero sin actualizar.

Cuatro avisos:

| Evento | Asunto |
|---|---|
| Tablero sin actualizar | `⚠️ ALERTA: Tablero Power BI sin actualizar - <fecha>` |
| No se pudo leer la fecha | `⚠️ ALERTA: no se pudo leer la fecha del tablero - <fecha>` |
| Flujo terminado | `✅ ÉXITO: Flujo de procesamiento finalizado - <fecha>` |
| Flujo incompleto | `❌ FALLO: Flujo de procesamiento incompleto - <fecha>` |

El de fallo no estaba en el encargo y hace falta: sin él, en desatendido un
fallo a mitad se ve **exactamente igual** que un día sin novedades — silencio.

Dos decisiones del módulo que conviene conocer:

- **Sin canal configurado lo dice y devuelve «no enviado».** Callarse parecería
  que avisó, y eso es peor que no avisar.
- **Nunca lanza excepción.** Un aviso que revienta se llevaría por delante justo
  el flujo al que intenta avisar; los problemas van en el resultado.

Las métricas del aviso **no se pasan por parámetro**: `resumen_dia.py` las lee
del diario, así que cuentan lo que de verdad pasó. Y los rojos van agrupados por
materia y grupo, que es lo que convierte una lista de 15 personas en un
diagnóstico de 2 grupos — el 07/09/2026 fue exactamente así.

### Ejecución desatendida a las 9:00, de lunes a viernes

```powershell
# Estreno prudente: unos días recorriendo el flujo sin escribir en SINU
.\.venv\Scripts\python.exe scripts\programar_9am.py --simulacion

# Producción
.\.venv\Scripts\python.exe scripts\programar_9am.py

# Quitarla
.\.venv\Scripts\python.exe scripts\programar_9am.py --quitar
```

El disparador es **semanal con lunes a viernes**, no diario: el proceso es de
gestión académica y en fin de semana no hay quien atienda una alerta. En el
Programador se ve como `DaysOfWeek = 62`, que es la máscara exacta de L–V
(2+4+8+16+32), sin sábado ni domingo.

El **primer disparo** se calcula saltando el fin de semana: hoy si la hora aún
no ha pasado, y si no el siguiente día laborable. La primera versión ponía
siempre «mañana», y registrada un miércoles a las 08:12 para las 09:00 dejaba
la tarea para el jueves — se habría esperado a las 9:00 sin que pasara nada.

### El panel: encender y apagar con botones

Doble clic en **`Flujo diario.bat`**, en la raíz del proyecto.

```
┌──────────────────────────────────────────────┐
│  ENCENDIDA - L a V                           │
│  Próxima ejecución: martes 15/09/2026 a las 09:00
│  Modo REAL: modificará matrículas en SINU.   │
│  ──────────────────────────────────────────  │
│  Programación:                               │
│  [Todos los días (L-V)] [Solo mañana] [Apagar]
└──────────────────────────────────────────────┘
```

**La mitad de la ventana es el estado, no los botones**, y es deliberado: el
modo de fallo peligroso aquí no es que cueste apagarlo, es **creer que está
apagado cuando está encendido** — o al revés. Un botón que alterna a ciegas no
lo evita; ver el estado sí.

Por eso el **modo se muestra siempre**, y en ámbar cuando va a escribir. La
diferencia entre un ensayo y tocar matrículas de verdad no debería depender de
la memoria de nadie.

| Botón | Qué hace |
|---|---|
| **Todos los días (L-V)** | Disparador semanal, lunes a viernes |
| **Solo mañana** | Disparador de **una sola vez** |
| **Apagar** | Deshabilita la tarea sin borrarla |

«Solo mañana» **no es la tarea semanal desactivada**: es un disparador de una
sola ejecución. Así corre ese día y se queda quieta sola, sin que nadie tenga
que acordarse de apagarla — que es justo el descuido que dejó `MODO_SIMULACION`
abierto seis días (01–07/09/2026).

Lo mismo desde la consola, si se prefiere:

```powershell
.\.venv\Scripts\python.exe scripts\programar_9am.py            # L-V
.\.venv\Scripts\python.exe scripts\programar_9am.py --una-vez  # una sola vez
.\.venv\Scripts\python.exe scripts\programar_9am.py --quitar
```

#### El estado se lee del XML, no de la salida traducida

`schtasks /Query /FO LIST /V` saca las etiquetas **traducidas** («Estado»,
«Próxima ejecución»…), así que analizarlas ata el código al idioma del equipo.
`tarea_programada.py` lee `schtasks /Query /XML`, cuya estructura es igual en
cualquier idioma.

Es la misma lección que dio Power BI: los selectores en español funcionaban
hasta que Chromium headless arrancaba en inglés.

Y la próxima ejecución **se calcula**, no se lee: Windows la expone traducida y
en formato local, y este proyecto ya tuvo que poner una guarda por una fecha
día/mes interpretada al revés.


**Programador de tareas de Windows, no `schedule`/APScheduler.** Una tarea del
sistema sobrevive a reinicios, a cierres de sesión y a que se cierre la consola.
Un bucle de Python vive solo mientras viva su proceso, y basta un reinicio
nocturno para que el día siguiente no se procese y nadie se entere — que es el
fallo que todo este montaje pretende evitar.

Se registra por XML y no con `/TR`, porque el XML permite fijar los ajustes que
de verdad deciden si la tarea corre:

- **`StartWhenAvailable`** — si el equipo estaba apagado a las 9:00, corre en
  cuanto arranque. Sin esto el día se salta sin dejar rastro.
- **Batería** — el defecto de Windows es *no* arrancar sin corriente. En
  portátil eso perdería el día por estar desenchufado.
- **`InteractiveToken`** — el flujo necesita sesión interactiva: la subida a
  Drive falla sin ventana (comprobado el 03/09/2026) y Chrome usa el perfil de
  este usuario. Con «ejecutar aunque el usuario no haya iniciado sesión» el
  navegador no tiene escritorio y la subida se cae.

Por eso mismo: **el equipo tiene que estar encendido y con la sesión iniciada.**

## Uso — Fase 1

```powershell
.\.venv\Scripts\python.exe scripts\validar_reporte.py data\raw\ejemplo.xlsx
```

Opciones útiles:

| Flag | Efecto |
|---|---|
| `--salida ruta.xlsx` | Ruta de la copia coloreada |
| `--sin-color` | Solo el resumen, sin generar `.xlsx` |
| `--sin-ordenar` | No ordenar A–Z por `COD_PERIODO`; deja el orden de Power BI |
| `--csv-omitidas ruta.csv` | Volcado de las filas omitidas y su motivo |
| `--no-deduplicar-exactos` | Procesa todas las apariciones de un duplicado exacto |
| `-v` | Log en DEBUG |

Salidas: resumen en consola, copia coloreada en `data/processed/`,
log de la corrida en `logs/`.

### Orden A–Z por `COD_PERIODO`

La rutina de limpieza termina **ordenando la tabla completa** por la columna
`COD_PERIODO` de la A a la Z, después de pintar y antes de guardar. Es lo
último que pasa antes de subir el archivo a Google Sheets.

Por qué: en ISEF07 el filtro de **Periodo** se fija una vez por sesión. Power BI
exporta los periodos entremezclados, así que la automatización tendría que
cambiar ese filtro línea por línea. Con la tabla agrupada, cada periodo es un
**bloque continuo** y el filtro se toca una sola vez por bloque.

Detalles que importan:

- Se mueve el contenido **con su estilo**, así que el naranja, el azul y el
  amarillo de la Fase 1 viajan con su fila.
- El orden es **estable**: dentro de un mismo periodo se conserva el orden de
  aparición del reporte, que es lo que permite reanudar una corrida
  interrumpida.
- Las filas **sin periodo** van al final: no son ejecutables, porque no hay
  filtro de Periodo que fijar.
- La fila de pie `Filtros aplicados:` de Power BI **no se mueve**: no es un
  registro.
- Los números de fila del `ResultadoValidacion` se **renumeran**, de modo que
  siguen apuntando al archivo que se acaba de escribir — el mismo que verá el
  operador en Sheets. Por eso el resumen se imprime *después* de escribirlo.

El módulo es `orden_periodo.py`. `plan_vinculacion.py` sigue calculando su
propio orden A–Z sobre el `.xlsx` local, no releyendo el Sheet: es determinista,
se puede probar sin navegador y ahora coincide fila a fila con lo que se subió.

## Perfil de navegador

El objetivo (dueño del proceso, 31/08/2026) es que la automatización tenga lo
que tiene el usuario: **barra de favoritos** con los accesos a SINU y al Sheet,
contraseñas guardadas y cookies de sesión. Con un perfil limpio, cada corrida
empieza de cero.

### Por qué no se usa el perfil personal directamente

**Chrome no lo permite.** Comprobado el 31/08/2026 con Chrome 151:

```
DevTools remote debugging requires a non-default data directory.
Specify this using --user-data-dir.
```

Desde Chrome 136, el navegador veta la depuración remota —el canal por el que lo
manejan Playwright y Selenium— cuando `--user-data-dir` apunta a su directorio de
datos por defecto. El navegador arranca, pero nunca deja conectarse: la corrida
muere por *timeout* a los 180 s. No es configuración: es el navegador.

(Aparte, Chrome bloquea la carpeta de su perfil mientras está abierto, así que
ni siquiera sin ese veto se podría usar con Chrome en marcha.)

### Lo que sí funciona: sembrar una copia

El veto es al **directorio**, no al contenido. Una copia del perfil en otra
carpeta sí es automatizable:

```powershell
# Una sola vez, con CHROME CERRADO:
.\.venv\Scripts\python.exe scripts\sembrar_perfil.py --rehacer

# Y una sola vez, para la sesión de Google:
.\.venv\Scripts\python.exe scripts\probar_perfil.py --iniciar-sesion
```

```ini
NAVEGADOR_PERFIL=proyecto
POWERBI_PERFIL_NAVEGADOR=C:\Users\<usuario>\.playwright-perfil-powerbi
```

Medido sobre el perfil real: **1463 archivos, 100,7 MB, 46 favoritos**, sin
ningún archivo bloqueado. Las cachés no se copian (Chrome las regenera, y
copiarlas convertiría segundos en minutos y varios GB).

Y se gana algo que no estaba en el pedido: **las corridas diarias ya no
necesitan Chrome cerrado.** Solo la siembra lo exige. Después, el robot trabaja
sobre su copia mientras el operador navega tranquilamente — y el perfil de
diario deja de estar expuesto a que la automatización lo degrade.

### Dos trampas de Chrome que la siembra desactiva

**1. Chrome borraría los favoritos.** Firma `Bookmarks` con un MAC cuya semilla
incluye la *ruta del perfil*. Al mover la carpeta la firma no valida, Chrome lo
toma por manipulado y **resetea los favoritos**: escribe un `Bookmarks` vacío y
deja el bueno en `Bookmarks.bak`. Medido: 46 → 0 al primer arranque.

La siembra retira las firmas (`protection` de `Preferences` y `Secure
Preferences`); sin nada contra qué validar, Chrome acepta el contenido y lo
vuelve a firmar con la semilla del sitio nuevo. Verificado: los 46 favoritos
sobreviven al arranque.

**2. Un refresco borraría la sesión.** Las cookies del perfil personal van
cifradas con *App-Bound Encryption* (Chrome 127+): se copian byte a byte pero
llegan **inservibles**, porque la clave está ligada a la instalación y al
directorio de origen. Es una defensa deliberada contra el robo de sesiones
copiando perfiles, funciona como debe, y no se intenta rodear.

Lo peligroso no es que sean inútiles, sino que al **volver a sembrar** pisarían
las cookies buenas que el perfil de trabajo ya tuviera — obligando a
autenticarse otra vez, que es justo lo que la siembra evita. Por eso esos
archivos **no se copian nunca**, y `Local State` solo se copia si el destino no
tiene uno (sobrescribirlo rotaría la clave y dejaría ilegible lo que ya hubiera).

### Qué viaja y qué no

| | ¿Viaja? |
|---|---|
| Barra de favoritos | ✅ los 46 |
| Preferencias, historial | ✅ |
| **Cookies de sesión** | ❌ no se pueden copiar — se crean una vez |
| Contraseñas guardadas | ❌ mismo motivo |

**No hace falta rodear el cifrado.** El objetivo real era *no autenticarse en
cada ejecución*, y eso se cumple igual: se entra **una vez** en el perfil de
trabajo y la sesión se queda ahí. Verificado en un proceso nuevo: 68 cookies,
56 de Google. Es un coste único, no por corrida.

```powershell
.\.venv\Scripts\python.exe scripts\probar_perfil.py --iniciar-sesion
```

Abre Drive con ventana, espera 5 minutos a que se entre a mano y cuenta las
cookies al cerrar. SINU no necesita este paso: se autentica solo con
`SINU_USUARIO` / `SINU_PASSWORD` de `config/.env`.

### El selector de cuenta de Google

Tener las cookies de sesión **no basta**. Si la cuenta tiene varias identidades
de Google, Drive se queda parado en el selector de cuenta y no avanza:

```
accounts.google.com/v3/signin/accountchooser?continue=drive.google.com/...
título: "Google Drive: Acceso"
```

Verificado el 01/09/2026: las cookies de autenticación estaban todas presentes
y válidas (`SID`, `HSID`, `SSID`, `SAPISID`, `__Secure-1PSID`) y la URL no se
movió en 12 s. **No falta la sesión: falta elegir cuenta.** Fijar el índice en
la URL (`/u/0/`, `/u/1/`) tampoco lo salta.

Se resuelve una sola vez, abriendo el perfil con ventana y eligiendo la cuenta
que tiene acceso a la carpeta:

```powershell
.\.venv\Scripts\python.exe scripts\probar_perfil.py --visible `
  --url https://drive.google.com/drive/folders/<ID> --esperar 300
```

`subidor_drive` distingue este caso de "no hay sesión" y da el remedio en el
mensaje: confundirlos manda a autenticarse otra vez, que no arregla nada.

### Diagnóstico

```powershell
.\.venv\Scripts\python.exe scripts\probar_perfil.py
```

En diez segundos, sin tocar Drive ni SINU: qué perfil está configurado, si
Chrome lo tiene bloqueado, cuántos favoritos hay dentro y qué cookies de sesión
sobreviven.

Los módulos son `perfil_navegador.py` (qué perfil, y si se puede abrir ahora) y
`siembra_perfil.py` (la copia). `grabar.py` comparte el primero: la grabación
abre **el mismo** perfil que el robot, o lo que se grabe no será lo que él vea.

`NAVEGADOR_PERFIL=chrome` se conserva por si una versión de Chrome vuelve a
admitirlo; `probar_perfil.py` dice cuál es el caso.

## Secuencia del día: el Sheet manda

El orden de apertura de pestañas es una regla que se comprueba, no una
casualidad de cómo están escritas las llamadas:

1. Se sube el reporte y **se abre el Sheet del día** en una pestaña.
2. Se lee el **Periodo de su primera fila de datos**.
3. **Solo entonces** se abre SINU en la pestaña contigua, se entra en ISEF07 y
   se fija ese Periodo.

Si el Sheet no está abierto y legible, el proceso **se detiene** en vez de abrir
ISEF07. Sin fuente de origen no hay periodo que seleccionar, y fijar uno a ojo
significaría vincular matrículas del periodo equivocado.

Como el `.xlsx` se ordena A–Z antes de subirlo, la primera fila del Sheet es
justo el primer lote del plan local. Los dos se contrastan y se avisa si no
coinciden: suele significar que la pestaña abierta es el reporte de ayer.

**Por qué no se raspa la cuadrícula:** Google Sheets pinta las celdas en un
`<canvas>`, así que no existen en el DOM y no hay nada que seleccionar. Lo que
sí funciona es pedir el documento en CSV por su URL de exportación, con las
cookies de esa misma pestaña. Es el mismo documento y la misma sesión, pero el
valor llega como texto en vez de como píxeles — y la pestaña abierta sigue
siendo un requisito real, porque de ella salen el id del documento, el `gid` de
la hoja y la sesión de Google que autoriza la descarga.

El módulo es `periodo_sheet.py`.

## Uso — Etapa 1 (exportación desde Power BI)

### Primera prueba (visual, supervisada)

```powershell
# Valida la configuracion sin abrir el navegador:
.\scripts\primera_prueba_powerbi.ps1 -SoloComprobar

# Prueba real: ventana visible, traza, captura del dialogo y perfil persistente
.\scripts\primera_prueba_powerbi.ps1
```

Requiere `POWERBI_PASSWORD` en `config/.env`. El script comprueba antes de
arrancar el `.venv`, las credenciales y el directorio del perfil, y avisa si
`POWERBI_URL_INFORME` está vacío. Deja tres artefactos en `logs/`: el log de la
corrida, `traza_powerbi_<sello>.zip` y `dialogo_exportacion_<sello>.png`.

Qué revisar al terminar:

1. La captura del diálogo — que **"Datos con diseño actual"** estuviera marcado.
2. Las líneas `!` del resumen: son pasos que no se pudieron confirmar.
3. Que el `.xlsx` traiga las 15 columnas y el pie `Filtros aplicados:`.
4. Copiar la URL del informe desde la barra de direcciones a
   `POWERBI_URL_INFORME`, para no depender de la navegación por la UI.

Después, `POWERBI_HEADLESS=true` para las corridas diarias.

### Corridas normales

```powershell
.\.venv\Scripts\python.exe scripts\exportar_reporte.py
```

| Flag | Efecto |
|---|---|
| `--salida ruta.xlsx` | Destino de la descarga (por defecto `data/raw/` con sello) |
| `--visible` | Abre el navegador con ventana |
| `--headless` | Fuerza modo sin ventana sobre `POWERBI_HEADLESS` |
| `--traza` | Traza de Playwright en `logs/` (`playwright show-trace <ruta>`) |
| `--captura` | Imagen del diálogo de exportación antes de confirmar |
| `-v` | Log en DEBUG |

La exportación es de **solo lectura**: no modifica nada en Power BI, así que
`MODO_SIMULACION` no la afecta.

### Selectores

Los selectores viven en [`selectores_powerbi.py`](src/moodle_sinu/selectores_powerbi.py),
extraídos de una grabación de `playwright codegen` sobre la UI real. Cada uno
lleva la línea de la grabación de la que salió y una expresión regular de
reserva; el exportador prueba el selector grabado y cae a la reserva dejando
advertencia en el log.

Fijar `POWERBI_URL_INFORME` en `config/.env` evita toda la navegación por la
UI: es el único camino que no depende del idioma ni del orden del listado.

### Tres cosas que costaron una corrida cada una

Documentadas aquí porque ninguna es evidente y las tres daban síntomas
engañosos. Cada una tiene tests de regresión en
[test_exportador_powerbi.py](tests/test_exportador_powerbi.py).

**1. `POWERBI_VISUAL` no es `POWERBI_PAGINA`.** `MOODLE-VS-SINU-EST` es el
`aria-label` del *lienzo* (`<exploration>`), o sea la página entera. Al clicarlo,
el botón `...` que se encontraba después era el del primer visual del DOM — un
gráfico — y salía un archivo de 7,7 KiB con una columna. El visual correcto es
la tabla, `aria-label="REPORTE "` (con espacio final), y se localiza por
`aria-roledescription="Tabla"`, no por título: es la propiedad que determina si
"Datos con diseño actual" estará habilitado. El botón `...` se busca **dentro**
del visual elegido.

**2. El idioma del navegador hay que fijarlo.** Con ventana, Chromium heredaba
el español del perfil; en headless pedía la UI en **inglés** (`More options`,
`Slicer`) y ningún selector casaba. Como algunos `data-testid` incorporan la
etiqueta traducida (`pbimenu-item.Exportar datos`), cubrir variantes no basta:
`POWERBI_IDIOMA` fija `Accept-Language` en el contexto. **No cambiarlo sin
revisar los selectores.**

**3. `net::ERR_ABORTED` no es un `TimeoutError`.** Tras el login, Power BI lanza
su propia redirección y cancela el `goto` en curso. Es un `playwright.Error`
genérico, así que escapaba del manejo de errores: traceback en consola y log de
la corrida **sin ninguna línea de error**. Ahora `_navegar()` lo tolera y
cualquier fallo del navegador queda registrado.

### Por qué la exportación se valida a sí misma

La corrida que exportó el archivo equivocado terminó con **código 0**. Un
fichero incorrecto que pasa por bueno es peor que un fallo, porque alimenta la
Fase 1 sin avisar. De ahí dos guardas que abortan en vez de advertir:

- Si **"Datos con diseño actual"** está deshabilitado — señal de que el visual
  no es de tabla/matriz — se aborta, en vez de exportar "Datos resumidos".
- Tras descargar, `verificar_estructura_descarga()` comprueba que las cabeceras
  son las 15 de `COLUMNAS_ESPERADAS`, en orden.

### Volver a grabar el flujo

```powershell
.\.venv\Scripts\python.exe -m playwright codegen https://app.powerbi.com/
```

`codegen` escribe **usuario y contraseña en texto plano** en el script
generado. `.gitignore` ya cubre `*_grabado.py` y `*_codegen.py`, pero el
archivo queda en disco: extraer los selectores, borrarlo y rotar la contraseña
usada durante la grabación.

## Etapa 2 — subida a Drive por navegador

**No se usan las APIs de Google.** La organización (`cun.edu.co`) no concede
acceso a Google Cloud Console, así que no hay `client_secret.json` posible. La
etapa 2 es RPA sobre la interfaz web de Drive, reutilizando el **mismo perfil
persistente de Chromium** que la etapa 1: la sesión de Google que abre Drive es
la que ya quedó autenticada allí. Consecuencia buena: no hay ninguna credencial
de Google en el proyecto.

### Configuración

Solo dos variables en `config/.env`:

```
GOOGLE_CARPETA_RAIZ=REPORTES 2026
GOOGLE_CARPETA_RAIZ_ID=<el id que aparece en la URL de la carpeta>
```

El id se lee de `https://drive.google.com/drive/folders/<ID>`.

La sesión de Google vive en `POWERBI_PERFIL_NAVEGADOR`. Si caduca, la etapa 2
aborta diciéndolo y se arregla ejecutando una vez con `--visible`.

### La subida no funciona sin ventana

**Comprobado el 03/09/2026** con dos corridas seguidas del mismo `flujo_dia.py`,
mismo archivo y misma carpeta, cambiando *solo* el modo del navegador:

| Modo | Resultado |
|---|---|
| `POWERBI_HEADLESS=true` (sin ventana) | `'REPORTE 03-09-2026 #198' no apareció en la carpeta tras 300s` |
| `--visible` | Subió, convirtió a Sheet y siguió hasta ISEF07 sin tocar nada más |

Lo engañoso es **cómo** falla: `expect_file_chooser` no da timeout y `set_files`
se entrega sin error, así que parece que la subida arrancó. Lo que no ocurre
nunca es que el archivo aparezca. Con ese síntoma es natural sospechar de los
selectores de Drive — y no son los selectores.

Ya había pasado el 01/09/2026 y se atribuyó a otra cosa: separar los dos clics
(abrir *"Nuevo"* fuera del bloque `expect_file_chooser`) sigue siendo necesario,
pero **no era la causa raíz** — la corrida que validó ese arreglo fue visible.

**Regla:** la etapa 2 se ejecuta con `--visible`. Las etapas 1 (Power BI) y 4
(SINU) sí funcionan sin ventana.

### Los selectores están SIN VERIFICAR

A diferencia de la etapa 1, [`selectores_drive.py`](src/moodle_sinu/selectores_drive.py)
no sale de una grabación real: se dedujo de la estructura conocida de la UI.
**Hay que confirmarlo grabando el flujo**, igual que se hizo con Power BI:

```powershell
.\scripts\grabar_drive.ps1
```

Abre `codegen` sobre la carpeta raíz con el perfil ya autenticado. Lo que hay
que grabar está impreso al arrancar.

Por qué esta etapa es intrínsecamente más frágil que la 1: Power BI expone
`data-testid` en casi todo; **Drive no**. Aquí casi todo se localiza por rol y
por texto en español — de ahí que `POWERBI_IDIOMA` importe también aquí — y la
lista de archivos es **virtualizada**, así que las filas fuera de pantalla no
existen en el DOM. Google cambia esta UI sin avisar; cuando algo deje de casar,
hay que volver a grabar.

### Un ajuste manual que elimina el paso más frágil

Conviene activar **una vez**, a mano:

> Drive → Configuración → General → *"Convertir los archivos subidos al formato
> del editor de Google Docs"*

Con eso el `.xlsx` aterriza ya como Google Sheet y la conversión por menús
—clic derecho → Abrir con → Sheets → Archivo → Guardar como— no se ejecuta
nunca. El módulo comprueba el resultado y avisa si tuvo que recurrir a ella.

### Convención en Drive

Acordada el 21/08/2026:

```
REPORTES 2026/                     id en GOOGLE_CARPETA_RAIZ_ID
  AGOSTO/                          mes en MAYÚSCULAS y en español
    REPORTE 21/08/2026 #159
  SEPTIEMBRE/
    REPORTE 01/09/2026 #160
```

- **Un Sheet nuevo por día**, con la fecha en el nombre: queda histórico completo.
- Se sube el `.xlsx` **ya coloreado y ordenado por la Fase 1**. Al convertirse a
  Sheet, el naranja, el azul y el amarillo viajan con él, junto a la columna
  `VALIDACION_RPA`, y los periodos llegan ya agrupados A–Z (ver *Orden A–Z por
  `COD_PERIODO`*). La etapa 5 solo añadirá los casos 1/2/3 de SINU.
- Los nombres de mes están **fijos en el código**, no salen de
  `calendar.month_name`: ese depende del locale de la máquina, y el nombre de la
  carpeta es parte de la convención.
- La **barra** del nombre es legal en Drive, que no es un sistema de archivos —
  pero no en Windows. Así que el archivo se sube como
  `REPORTE 21-08-2026 #159.xlsx` y **se renombra ya dentro de Drive**. El nombre
  provisional se parece al definitivo a propósito: si el renombrado fallara, lo
  que queda sigue siendo reconocible.
- El **consecutivo** se deduce leyendo la carpeta del mes y la del mes anterior.
  No se recorren los doce meses: por la UI sería lento y frágil, y el
  consecutivo es monótono. Si el histórico tuviera un hueco de más de un mes,
  hay que pasar `--consecutivo N`.

Si ya existe un reporte de esa fecha, la subida **aborta** en vez de duplicar.
Y si no se encuentra ningún reporte previo, **también aborta** en vez de
arrancar en `#1`: una lista vacía significa casi siempre que la lectura falló,
no que el histórico empiece hoy.

### Uso

```powershell
# Primera vez, mirando y con traza (los selectores no están verificados)
.\.venv\Scripts\python.exe scripts\subir_reporte.py data
aw
eporte.xlsx --visible --traza

# Después
.\.venv\Scripts\python.exe scripts\subir_reporte.py data
aw
eporte.xlsx
```

| Flag | Efecto |
|---|---|
| `--ya-validado` | El `.xlsx` ya trae los colores; no repetir la Fase 1 |
| `--fecha AAAA-MM-DD` | Fecha del reporte (por defecto, hoy) |
| `--consecutivo N` | Fuerza el número en vez de deducirlo de Drive |
| `--visible` / `--headless` | Modo del navegador |
| `--traza` | Traza de Playwright en `logs/` |
| `-v` | Log en DEBUG |

Cadena completa del día:

```powershell
.\.venv\Scripts\python.exe scripts\exportar_reporte.py
.\.venv\Scripts\python.exe scripts\subir_reporte.py data
aw\<el .xlsx recién bajado>
```

## Estructura del reporte de origen

Hoja `Export`, 15 columnas (A..O). Todas las celdas vienen como texto.

| Col | Campo | Obligatorio | Uso |
|---|---|---|---|
| A | `IDENTIFICACION` | ✅ | Clave de búsqueda en ISEF07 / ISEF88 |
| B | `NOMBRE_COMPLETO` | ✅ | — |
| C | `CORREO` | ✅ | — |
| D | `CELULAR` | | — |
| E | `TELEFONO` | | — |
| F | `COD_UNIDAD` | | Filtro en PACF50 / ISEF05 (Caso 2) |
| G | `COD_PENSUM` | | Filtro en PACF50 / ISEF05 (Caso 2) |
| H | `COD_MATERIA` | ✅ | Clave de búsqueda en ISEF07 |
| I | `ID_GRUPO` | | — |
| J | `NUM_GRUPO` | | Componente del `shortname` |
| K | `BLOQUE` | | — |
| L | `PAGO` | | — |
| M | `COD_PERIODO` | | Filtro "Periodo" en ISEF07 / ISEF88 |
| N | `LLAVE` | | `COD_MATERIA/NUM_GRUPO/COD_PERIODO/BLOQUE/COD_UNIDAD/COD_PENSUM` |
| O | `VALIDACION` | | Campo calculado por Power BI (`MATRICULADO` / `NO_MATRICULADO`) |

**Columna P `VALIDACION_RPA`** la agrega la automatización. La columna O **no se
sobrescribe**: es dato de origen con su propio vocabulario.

**`shortname`** es un campo *derivado*, no una columna: `COD_MATERIA/NUM_GRUPO`
(ej. `A1I01/50609`). Es la llave combinada del curso en Moodle.

### Fila de pie

La exportación "Datos con diseño actual" agrega al final una fila con
`Filtros aplicados: …` que **no es un registro** y se descarta antes de validar.
De ahí se lee que la vista por defecto ya filtra
`VALIDACION ≠ MATRICULADO`, `pago = PAGO` y una lista de exclusión de periodos.

## Etapa 4 — ejecución en ISEF07 (la única que escribe)

Regla de negocio (dueño del proceso, 21/08/2026), según `Vinculado?`:

| Estado | Secuencia |
|---|---|
| `False` (sin check) | **Vincular** → ejecutar |
| `True` (ya con check) | **Desvincular** → ejecutar → **Vincular** → ejecutar |

Es decir: lo ya vinculado se **recicla**, no se salta. Por eso
`CASO_1_YA_VINCULADO` pasó de *no requerir acción* a requerirla.

### Solo la materia del reporte — CORREGIDO el 03/09/2026

> Por la 07 únicamente se debe procesar, por estudiante, el código de la materia
> que registre en el reporte. No otro, no todos, no algunos: únicamente el que
> registre en el reporte.
>
> — dueño del proceso, 03/09/2026

Hasta esa fecha aquí decía lo contrario: que la acción era *"por estudiante, no
por materia"*, que alcanzaba todas las asignaturas del periodo a la vez, y que
por tanto **bastaba una materia vinculada para reciclar al estudiante completo**.

**Era falso.** Venía de una sola frase de
[`references/vinculacion-moodle.md`](cun-sigwt-matricula/references/vinculacion-moodle.md)
y se había copiado a ocho archivos. El 03/09/2026, en 5 estudiantes, hizo que se
desvincularan y revincularan **34 asignaturas cuando correspondían 5**:

| Cédula | Materia en el reporte | Asignaturas que tocó |
|---|---|---|
| 1000000009 | BMD01/20103 | 6 |
| 1000000108 | IED36/30101 | 5 |
| 1000000107 | IED36/30101 | 7 |
| 1000000104 | IED36/30101 | 8 |
| 1000000102 | IED36/30101 | 8 |

Ninguna quedó rota —se verificó una por una—, pero el reporte no vigila esas
materias, así que un fallo ahí habría pasado inadvertido. La referencia ya está
corregida en su origen, y hay un test centinela
(`test_la_premisa_falsa_no_ha_vuelto`) que falla si la frase reaparece como
regla.

**La unidad de trabajo es (cédula, materia):** una operación por fila del
reporte. Antes de ejecutar, la grilla *Grupos* se acota por `COD_MATERIA` — ese
paso es lo que confina la acción, y no es opcional.

### Y una guarda, porque el confinamiento no está verificado

Lo que **sí** está medido (03/09/2026) es que **sin acotar** la acción alcanza
todas las asignaturas: `1000000102` pasó de 0 de 8 a 8 de 8 con una sola
ejecución. Que acotar la grilla la confine lo afirma el dueño del proceso, pero
nadie lo ha comprobado contra el sistema.

Así que tras **cada** escritura se relee la grilla completa y se exige que
ninguna otra asignatura haya cambiado (`AccionSeDesbordo`, constante
`COMPROBAR_DESBORDE`). Si salta, se detiene la corrida entera con código 2.

Sin esa guarda el código *parecería* trabajar por materia y seguiría haciendo el
mismo daño, ahora invisible — que es peor que el estado anterior. Se puede apagar
cuando el confinamiento esté confirmado en una pasada supervisada, y no antes.

**El reciclado abre una ventana de riesgo.** Entre el desvincular y el vincular
el estudiante queda **sin vincular**. Si el proceso muere ahí, acaba peor que al
empezar. De ahí tres medidas:

- Se anota en `logs/ciclos_abiertos.jsonl` **antes** de desvincular y se cierra
  el apunte tras vincular. Un apunte sin cerrar es un estudiante a revisar a
  mano, y **sobrevive a que el proceso muera**.
- El vincular posterior se reintenta 3 veces (más que cualquier otra operación
  del proyecto: si esto falla, alguien queda desvinculado).
- `CicloAbierto` es una excepción aparte de `ErrorEjecucionSinu`, para que nunca
  se trate como "un fallo más". El CLI la reporta en primer plano y sale con
  código 1.
- Al arrancar, el CLI avisa de reciclados sin cerrar de corridas anteriores.

### La confirmación del check: releer, no creerle al diálogo

Aclaración del dueño del proceso (03/09/2026), y es la regla que manda:

> Cuando se desvincula a un estudiante, se le debe vincular nuevamente, ya que
> ningún estudiante debe quedar desvinculado de ninguna de sus materias. […] Se
> desvincula y **se espera a que quede confirmada la desvinculación**. Una vez se
> tenga la confirmación, se vincula y **se espera a que quede vinculado** para
> proceder con el siguiente.

El diálogo *"Proceso terminado"* de ISEF07 **no** es esa confirmación: dice que
el proceso corrió, no que la materia quedara vinculada. Son cosas distintas y la
segunda es la que importa. Así que tras cada acción se vuelve a leer la grilla
Grupos y se cuentan los checks **materia por materia**.

Esto invalidó `VERIFICAR_CHECK_VINCULADO = False`, que venía de la referencia de
negocio (*"no verificar el check fila por fila"*). Esa frase describe lo que la
**persona** se ahorra cuando valida al final con un reporte aparte — no lo que
el robot puede permitirse.

| Desenlace | Qué significa | Qué hace el robot |
|---|---|---|
| Check confirmado | Todas las materias con `Vinculado?` | Cierra el ciclo y sigue |
| `reciclado_incompleto` | El desvincular no se reflejó | Avisa y vincula igual (idempotente). **No hay daño**: el estudiante sigue vinculado |
| `CheckNoConfirmado` | Se vinculó y el check no apareció, o ISEF07 no dejó vincular | **Escala** a ISEF05/PACF50. Cierra el ciclo o no, según lo de abajo |
| `CicloAbierto` | No se pudo vincular ni confirmar tras desvincular | Lo peor: puede estar desvinculado. Sale con código 1 |

Un fallo de **lectura** nunca abre un ciclo. Se separa a propósito: el
01/09/2026 una alarma falsa dijo que un estudiante podía estar desvinculado y
sus 7 asignaturas estaban intactas — y una alarma falsa en el único aviso que de
verdad importa es peor que no tenerlo.

### Una materia sin check no es siempre una urgencia

`ciclos_abiertos.jsonl` existe para **una** cosa: avisar de estudiantes que
quedaron *peor* que al empezar. Así que cuando el check no aparece hay que
distinguir dos situaciones, y la pregunta es una sola: **¿perdió el estudiante
algún vínculo que ya tenía?**

| Situación | Ciclo | Escalado |
|---|---|---|
| Falta una materia que **ya venía sin check** | Se **cierra** — el estudiante está como estaba | Sí |
| Falta una materia que **sí tenía check** al empezar | Queda **abierto** — hay que vincularla a mano | Sí |

Sin esa distinción el aviso se convierte en ruido permanente:
`reparar_desvinculados.py` recogería al estudiante en cada corrida para
reintentar un vínculo que ISEF07 no puede hacer.

**Comprobado en producción el 03/09/2026**, y el caso apareció en el 4.º
estudiante de 69: `1000000104` (2026C) empezó con 7 de 8 vinculadas y acabó con
7 de 8 — la que falta es `IED42/50101`, la misma. Con la primera versión de esta
comprobación habría quedado marcado como *"puede haber quedado desvinculado"*
para siempre. El escalado se registra en los dos casos: la materia sin check hay
que validarla en ISEF05/PACF50 igual; lo que cambia es si además hay una
urgencia de vinculación manual.

### El escalado a ISEF05 y PACF50

> Cuando en la 07 no se permite vincular, o si a pesar de haber vinculado este
> no tiene el check, se procede a abrir la 05 y la 50 para realizar la
> validación del check en Moodle y dejar registrada esta información en Google
> Sheets.

**Lo que está hecho:** el robot detecta el caso, reintenta el vincular
`INTENTOS_HASTA_ESCALAR` veces, y lo anota en
`logs/escalado_isef05_pacf50.jsonl` con la cédula, el periodo, el motivo y las
asignaturas concretas que quedaron sin check. Al final de la corrida el CLI los
lista aparte de los fallos, porque el siguiente paso es distinto: consultar, no
reintentar. Estos casos **no** hacen fallar la corrida (código 0): son un
desenlace previsto que necesita a una persona.

**Lo que falta (4c):** abrir ISEF05 y PACF50 automáticamente y escribir el
resultado en el Sheet. Hoy eso es manual. Los tres motivos que se registran:

| Motivo | Origen |
|---|---|
| `isef07-no-permite-vincular` | El desplegable de acción no se pudo dejar puesto |
| `vinculado-sin-check` | Se ejecutó el vincular y el check no apareció |
| `check-no-verificable` | No se pudo releer la grilla, así que no se sabe |

ISEF05 y PACF50 siguen siendo **solo lectura** en
[`restricciones_sinu.py`](src/moodle_sinu/restricciones_sinu.py). El escalado no
relaja esa barrera: se consultan, no se tocan.

### Tres cerrojos, hay que abrir los tres

1. `MODO_SIMULACION=false` en `config/.env`
2. `--ejecutar-de-verdad` en la línea de comandos
3. `--periodo` (el filtro se fija una vez por sesión)

Sin los dos primeros recorre todo y dice qué haría, sin tocar nada. Verificado
pasando `page=None`: en simulación no llega a tocar el navegador.

```powershell
# Ensayo: recorre y reporta, no modifica nada
.\.venv\Scripts\python.exe scripts\ejecutar_sinu.py data
aw
eporte.xlsx `
    --periodo 26V05 --limite 1 --visible --traza

# Real (requiere MODO_SIMULACION=false)
.\.venv\Scripts\python.exe scripts\ejecutar_sinu.py data
aw
eporte.xlsx `
    --periodo 26V05 --limite 1 --ejecutar-de-verdad --visible --traza
```

### Los controles de escritura están en un módulo aparte

[`selectores_sinu_escritura.py`](src/moodle_sinu/selectores_sinu_escritura.py)
contiene el desplegable *"Acción a realizar"* y el botón de ejecutar. La etapa 3
**no lo importa**, y hay tests que lo comprueban leyendo el código fuente: no
puede pulsar lo que no sabe localizar.

**Verificados en real el 01/09/2026**, no por grabación sino por uso: 12
estudiantes procesados en ISEF07, 12 ciclos cerrados. El que se temía frágil
—el botón de ejecutar, que la referencia describe como *"el primer icono (el de
más arriba de tres, tipo engranaje) a la izquierda del desplegable"*, posicional
y sin texto— acabó localizándose por su imagen (`icon_start.png`) y funcionó en
todas las corridas.

Lo que sigue **sin verificar** es la etapa 2 (Drive): esos selectores no se han
ejercitado contra la UI real.

Antes de cada ejecución se comprueba que el desplegable quedó con la acción
pedida, y se aborta si muestra otra: ejecutar con la acción equivocada es el
fallo que no se puede permitir aquí.

## Reglas de negocio de SINU (skill `cun-sigwt-matricula`)

Fuente: [`cun-sigwt-matricula/SKILL.md`](cun-sigwt-matricula/SKILL.md) y
[`references/vinculacion-moodle.md`](cun-sigwt-matricula/references/vinculacion-moodle.md).
Documentan el flujo tal como se ejecuta a mano, e introdujeron **tres
correcciones al diseño** que no se deducían del reporte.

### 1. La unidad de trabajo es (cédula, materia), no el estudiante

El reporte trae **una fila por asignatura matriculada**, y cada fila es una
operación: se acota la grilla *Grupos* a ese `COD_MATERIA` y se actúa solo sobre
él.

Esta regla decía justo lo contrario hasta el 03/09/2026 — que la unidad era el
estudiante, porque un solo *vincular* cubría todas sus asignaturas. Agrupar por
cédula era precisamente lo que hacía perder la materia de vista. Ver
*Solo la materia del reporte* en la etapa 4.

Coste del cambio: un estudiante con varias filas ahora cuesta una pasada por
fila. Sobre el reporte del 21/08/2026 eran **164 filas procesables → 84
operaciones** agrupando; sin agrupar son 164.

En ISEF07 la grilla *Estudiantes* se filtra **solo** por `No. Identificación`:
`COD_MATERIA` no es clave de búsqueda ahí, al contrario de lo que suponía
`CAMPOS_BUSQUEDA_SINU`.

### 2. El filtro de Periodo se fija una sola vez por sesión

No se toca entre estudiante y estudiante. Por eso el trabajo se agrupa por
`COD_PERIODO`: **cada periodo es una sesión de ISEF07**. La referencia marca
como error común trabajar con una hoja que mezcla periodos — y nuestro reporte
mezcla **15**.

### 3. Los tiempos son de ERP, no de web

Grillas asíncronas: 1-2 s para filtrar por cédula, **15-40 s** para ejecutar la
vinculación. El `TIMEOUT_OPERACION_SEG=30` del resto del proyecto se queda
corto; SINU usa el suyo (`TIMEOUT_OPERACION_SINU_SEG=120`). Y nunca se dispara
un paso encima de una carga en curso.

Todo esto vive en [`constantes_sinu.py`](src/moodle_sinu/constantes_sinu.py).

### El conflicto, resuelto

La referencia decía *"no verificar el check Vinculado? fila por fila"*, mientras
que el árbol de la Fase 2 clasifica los casos leyendo justamente ese check. El
dueño del proceso resolvió el 21/08/2026: **la prioridad es la precisión de la
clasificación, no la velocidad** — sí se leen los checks.

Y resulta que las dos fuentes no se contradecían: hablaban de unidades
distintas.

- **Navegar es por estudiante.** Un filtro por cédula en ISEF07; al seleccionar
  la fila, la grilla *Grupos* carga todas sus asignaturas. 84 búsquedas.
- **Clasificar es por asignatura.** Esa misma grilla trae una fila por
  asignatura con sus dos checks, así que de una búsqueda salen todas las
  clasificaciones del estudiante. 164 filas clasificadas.

Precisión completa al coste de navegación del enfoque por estudiante.

### Matriz de permisos: lectura y escritura son permisos distintos

Decisión del dueño del proceso, sin excepciones:

| Módulo | Lectura / consulta | Escritura / procesamiento |
|---|---|---|
| ISEF07 | ✅ | ✅ **único** |
| ISEF05 | ✅ | ⛔ |
| PACF50 | ✅ | ⛔ |
| ISEF88 | ✅ | ⛔ |

El robot **puede entrar y navegar** en los cuatro para verificar matrículas,
consultar grillas y revisar checks. Lo que no puede es pulsar nada que
*procese, vincule, desvincule, guarde o modifique* fuera de ISEF07: esos tres
funcionan en modo "solo ver".

Implementado como **barrera, no como nota**, en
[`restricciones_sinu.py`](src/moodle_sinu/restricciones_sinu.py), con **dos
listas blancas y dos guardas**:

- `exigir_modulo_legible()` — antes de entrar o navegar en un módulo.
- `exigir_modulo_escribible()` — antes de ejecutar cualquier acción.

Detalles que importan:

- **`MODULOS_SOLO_LECTURA` es derivado**, no escrito a mano
  (`LEGIBLES - ESCRIBIBLES`): las dos listas no pueden desincronizarse.
- **Ambas son listas blancas.** Un módulo no reconocido se bloquea en las dos,
  así que añadir módulos al sistema no abre agujeros por omisión. Entrar donde
  nadie autorizó es navegar por datos académicos sin permiso, no solo un riesgo
  de escritura.
- Un `assert` de importación rechaza un módulo escribible que no sea legible:
  sería un error de modelado.
- `resumen_permisos()` deja la matriz efectiva **en el log de cada corrida**,
  para poder auditar después con qué permisos corrió el robot sin fiarse de lo
  que diga este README.

La etapa 3 añade una garantía estructural encima: los selectores del desplegable
*"Acción a realizar"* y del icono de ejecutar **no están declarados** en
`selectores_sinu.py`. No puede pulsar lo que no sabe localizar. Hay tests que lo
comprueban leyendo el código fuente.

### Qué se consulta para confirmar cada caso

El árbol declara, por caso, qué módulos hay que consultar — todo de solo lectura:

| Caso | Consultar |
|---|---|
| 1 y 1-ya | nada |
| 2 (sin check en Moodle) | ISEF05, PACF50 |
| 3 (sin registro) | ISEF05, PACF50, ISEF88 |

Está en `MODULOS_VERIFICACION_POR_CASO`, y un `assert` comprueba que el árbol
no pida consultar nada fuera de la lista de lectura. La etapa 3 reporta al final
cuántas filas quedan pendientes de confirmar y en qué módulos.

**La navegación a esos tres módulos está pendiente de grabación.** Hoy la etapa
3 clasifica con lo que lee de ISEF07 y *dice* qué habría que confirmar; no
fabrica selectores para tres módulos más sin ninguna base. El permiso ya está
concedido en la barrera, así que implementarlo es añadir los selectores cuando
tengamos la grabación.

### Un cuarto estado que el árbol no cubría

Leer los checks obliga a encontrarse con `Curso en moodle? ✓` **y**
`Vinculado? ✓`: ya estaba vinculado de antes. El árbol documentado no lo
contemplaba. Se clasifica como `Caso.CASO_1_YA_VINCULADO`, verde igual que el
Caso 1 pero con etiqueta propia `YA VINCULADO`, y **no requiere acción**:
mezclarlo con `OK` inflaría el recuento de vinculaciones hechas por el robot.

Solo `Caso.CASO_1_VINCULADO` dispara acción en la etapa 4 (`CASOS_CON_ACCION`).

## Uso — Etapa 3 (clasificación, solo lectura)

Se trabaja **un periodo por corrida**: el filtro de Periodo de ISEF07 se fija
una sola vez por sesión. El reparto sale del plan (etapa 3a).

```powershell
# Primera prueba: pocos estudiantes, mirando, con traza
.\.venv\Scripts\python.exe scripts\clasificar_sinu.py data
aw
eporte.xlsx `
    --periodo 26V05 --limite 3 --visible --traza
```

| Flag | Efecto |
|---|---|
| `--periodo` | **Obligatorio.** El lote a trabajar |
| `--limite N` | Solo los primeros N estudiantes |
| `--salida` | Ruta del `.xlsx` clasificado |
| `--visible` / `--headless` | Modo del navegador |
| `--traza` | Traza de Playwright en `logs/` |

Da por hecho que **ISEF07 ya está abierto** en la sesión del perfil, como en el
proceso manual: no inventa el login ni la navegación por menús con selectores no
verificados. Si las grillas no están, lo dice y para.

Dos paradas obligatorias, heredadas de la referencia:

- **Cero o más de una fila** al filtrar por cédula → se detiene ese estudiante y
  sus filas quedan `PENDIENTE POR REVISAR`. Seguir con el estudiante equivocado
  es el peor resultado posible.
- **Check ilegible** → no se clasifica. Un check ilegible **no** es un check
  desmarcado; confundirlos convertiría un dato ausente en un Caso 2, y el
  reporte afirmaría algo que no se comprobó.

Los selectores de ISEF07 están **sin verificar**. Grabar con:

```powershell
.\scripts\grabar_sinu.ps1
```

### Acceso a SINU: lo que sí está verificado

Inspeccioné la página real el 21/08/2026, así que **estos selectores no son
conjetura** (a diferencia de los de las grillas de ISEF07):

| Qué | Selector real |
|---|---|
| Usuario | `input[name="userName"]` |
| Contraseña | `input[name="password"]` |
| Botón entrar | `td.button` con texto `Entrar` — **no** es un `<button>` |
| ¿Hay sesión? | `Salir` sin la clase `toolbarButtonDisabled` |
| Mantener sesión | casilla `No cerrar sesión` |

Tres hallazgos que cambian cómo hay que escribir los selectores:

**SINU es SmartClient/GWT y genera sus ids en cada carga** (`isc_3T`, `isc_2X`…).
Usarlos como selector garantiza fallos intermitentes. Lo estable son los `name`
de los inputs y las clases CSS. Hay un test que recorre el módulo de selectores
y falla si alguno contiene `isc_`.

**No renderiza en un iframe.** Sus dos únicos iframes son `__gwt_historyFrame` y
`basf00`, de infraestructura de GWT, y existen desde el primer instante — así
que esperar "a que haya un iframe" se cumple de inmediato y no garantiza nada.
La espera es a selectores reales de la aplicación.

**El 404 del arranque en frío es real.** Reproducido:

```
Primer intento sin exito (HTTP 404, 15 etiquetas, senal=None).
Recargando en 2s para que Tomcat fije la sesion.
SINU cargado (HTTP 200, 504 etiquetas, senal 'input[name="userName"]').
```

Eso es la pantalla en blanco: no es renderizado, es que la página no llegó. La
estrategia de [`acceso_sinu.py`](src/moodle_sinu/acceso_sinu.py) lo cubre: URL
con barra final, `wait_until="domcontentloaded"`, y si el estado es ≥400 o el
documento está vacío, `reload()` a los 2 s.

### Entrar con las credenciales guardadas

Con `SINU_USUARIO` y `SINU_PASSWORD` en `config/.env`, tanto la etapa 3 como la
grabación entran solas: rellenan el formulario, marcan *"No cerrar sesión"* y la
sesión queda en `POWERBI_PERFIL_NAVEGADOR` para las corridas siguientes.

Efecto secundario útil: como entra el código y no la persona, **la contraseña no
acaba escrita en el script que genera codegen** — que es exactamente cómo se
filtró la de Power BI.

## Cómo se graban los flujos

`playwright codegen` desde consola **no sirve** para este proyecto: no acepta
`--user-data-dir`, así que abre un navegador aislado y en blanco, sin ninguna
sesión iniciada. (`--load-storage` es lo único que admite, y exporta solo
cookies: no es el perfil.)

Por eso los scripts de grabación delegan en
[`scripts/grabar.py`](scripts/grabar.py), que usa `launch_persistent_context`
con `channel="chrome"`: abre el **Chrome instalado**, con el perfil y las
sesiones que el usuario ya tiene. Verificado el 21/08/2026 — `channel="chrome"`
da Chrome 150, frente a Chromium 129 del empaquetado.

La grabación a archivo se activa por el grabador interno de Playwright (el mismo
que usa `codegen` por dentro). Se llama por el canal interno del cliente porque
la API Python no lo expone; si una actualización lo renombra, el script cae al
Inspector y entonces el código se copia de ahí.

| Perfil | Cuándo |
|---|---|
| `-Perfil proyecto` (por defecto) | `POWERBI_PERFIL_NAVEGADOR`, el mismo de las etapas 1-3. Recomendado: aislado del Chrome personal, y lo que se graba corresponde a lo que verá la automatización. |
| `-Perfil chrome` | El perfil real del usuario, con todas sus sesiones. **Exige Chrome cerrado**: Chrome bloquea su carpeta de perfil mientras corre. El script lo comprueba y se niega a seguir. |

Si `-Perfil chrome` no arranca, puede ser porque las versiones recientes de
Chrome restringen la automatización del perfil por defecto. En ese caso,
`-Perfil proyecto`.

### La sesión de Google no estaba donde suponíamos

Comprobado el 21/08/2026 con
[`scripts/exportar_sesion.py`](scripts/exportar_sesion.py), que sirve de
diagnóstico: el perfil de `POWERBI_PERFIL_NAVEGADOR` tenía 12 cookies pero solo
**una** de `google.com` (`NID`, de preferencias) — ninguna de autenticación. Se
creó para Power BI y nunca inició sesión en Google.

El síntoma era engañoso: ante una carpeta que la sesión no puede ver, Drive
**no redirige al login, devuelve un 404**. La etapa 2 lo detecta ahora de forma
explícita y lo dice, en vez de culpar al selector.

Para Drive hay dos caminos: iniciar sesión una vez en el perfil del proyecto
(con `--visible`), o grabar con `-Perfil chrome` y Chrome cerrado.

## Uso — Plan de vinculación (etapa 3a)

Traduce el reporte en la lista de operaciones de ISEF07, agrupadas por periodo.
No toca SINU. Cumple la convención de la skill: antes de un lote largo, dar el
número de registros y el tiempo estimado.

```powershell
.\.venv\Scripts\python.exe scripts\plan_vinculacion.py data
aw
eporte.xlsx
```

| Flag | Efecto |
|---|---|
| `--periodo 26V05` | Solo ese lote (el que se va a trabajar en la sesión) |
| `--cedulas` | Solo las cédulas, una por línea — equivale a `extract_cedulas.py` |
| `--csv ruta.csv` | Vuelca el plan completo (orden, periodo, cédula, materias, filas) |
| `--hoja` | Nombre de la hoja |

### Sobre `extract_cedulas.py` de la skill

Su función está integrada en
[`plan_vinculacion.py`](src/moodle_sinu/plan_vinculacion.py) en lugar de copiar
el script, porque el original **no es seguro sobre nuestra exportación de Power
BI**: lee la columna en crudo y se traga la fila de pie `Filtros aplicados:`
como si fuera una cédula. Comprobado el 21/08/2026 — devolvía 237 cédulas, una
de ellas `pago es PAGO`. Nuestro parser descarta ese pie y además normaliza los
numéricos, así que `50609.0` no se cuela como texto.

El script original se conserva sin tocar en `cun-sigwt-matricula/scripts/` como
referencia.

## Reglas de validación

Precedencia de color: el **caso** (Fase 2) pinta el fondo de la **fila**; las
reglas de calidad (Fase 1) pintan **celdas** que se superponen. Una celda azul
sigue distinguiéndose sobre una fila verde.

### Fase 1 — antes de tocar SINU

| Regla | Condición | Alcance | Color | `VALIDACION_RPA` | ¿Va a SINU? |
|---|---|---|---|---|---|
| 1 | Espacios al inicio, al final o dobles internos | Celda | 🔵 `#ADD8E6` | — | Sí, con valor saneado |
| 2 | Campo obligatorio vacío | Celda | 🟠 `#FFA500` | `DATO INCOMPLETO - NO PROCESADO` | **No** |
| 3 | `IDENTIFICACION + COD_MATERIA` repetido **con datos distintos** | Fila | 🟡 `#FFFF00` | `DUPLICADO - VALIDAR ORIGEN` | **No** |

La celda conserva el valor **original** como evidencia; el valor **saneado**
(`.strip()` + colapso de espacios internos) es el que se envía a SINU.

Los duplicados **exactos** no los cubre la regla 3 literal: se procesa la
primera aparición y se omiten las demás (`DEDUPLICAR_EXACTOS=true`).

### Fase 2 — árbol de decisión en SINU

| Caso | Condición en ISEF07 | Verificación | Acción | Color | `VALIDACION_RPA` |
|---|---|---|---|---|---|
| 1 | `Curso en moodle?` ✓ y `Vinculado?` ☐ | — | "Vincular grupos matriculados" | 🟢 `#90EE90` | `OK` |
| 1-ya | `Curso en moodle?` ✓ y `Vinculado?` ✓ | — | Ninguna (ya estaba) | 🟢 `#90EE90` | `YA VINCULADO` |
| 2 | `Curso en moodle?` ☐ | PACF50 + ISEF05 | Ninguna | 🔴 `#FFC7CE` | `NO TIENE CHECK EN MOODLE` |
| 3 | Sin registro | ISEF05, PACF50, ISEF88 | Ninguna | 🟣 `#E6E6FA` | `NO CUENTA CON MATRÍCULA` |
| — | Fallo de selector / interfaz | — | Se detiene esa fila | — | `PENDIENTE POR REVISAR` |

## Estructura del proyecto

```
moodle-sinu-automation/
├─ config/
│  ├─ .env.example        # plantilla versionada
│  └─ .env                # credenciales reales (NO en Git)
├─ src/moodle_sinu/
│  ├─ constantes.py       # columnas, colores, etiquetas, reglas de negocio
│  ├─ modelos.py          # FilaReporte, HallazgoCelda, ResultadoValidacion
│  ├─ config.py           # carga de config/.env
│  ├─ registro.py         # logging a consola + logs/
│  ├─ lector_reporte.py   # parser del .xlsx
│  ├─ validacion.py       # Fase 1: las tres reglas
│  ├─ resumen.py          # resumen legible
│  ├─ orden_periodo.py    # orden A-Z por COD_PERIODO, con estilos y renumerado
│  ├─ salida_excel.py     # copia coloreada + ordenada (lo que se sube)
│  ├─ perfil_navegador.py # que perfil de Chrome se abre, y si se puede ahora
│  ├─ siembra_perfil.py   # copia del perfil personal (Chrome veta el original)
│  ├─ periodo_sheet.py    # Periodo de la 1a fila del Sheet + cerrojo de secuencia
│  ├─ selectores_powerbi.py   # selectores reales de la UI de Power BI
│  ├─ exportador_powerbi.py   # Etapa 1: descarga del reporte (Playwright)
│  ├─ navegador.py        # arranque de Chromium, compartido por las etapas RPA
│  ├─ convencion_drive.py # nombres y carpetas del Drive de reportes
│  ├─ selectores_drive.py # selectores de la UI de Drive (SIN VERIFICAR)
│  ├─ subidor_drive.py    # Etapa 2: subida por navegador
│  ├─ constantes_sinu.py  # reglas de ISEF07 (de la skill de negocio)
│  ├─ acceso_sinu.py     # apertura y login de SINU (verificado)
│  ├─ restricciones_sinu.py # barrera: solo ISEF07 es escribible
│  ├─ plan_vinculacion.py # Etapa 3a: cédulas por periodo -> operaciones
│  ├─ selectores_sinu.py  # selectores de ISEF07 (SIN VERIFICAR, solo lectura)
│  ├─ lector_sinu.py      # Etapa 3: lectura de la grilla Grupos
│  ├─ clasificador_sinu.py # Etapa 3: árbol de decisión (función pura)
│  ├─ selectores_sinu_escritura.py # controles de escritura (aparte)
│  └─ ejecutor_sinu.py    # Etapa 4: vincular / reciclar
├─ scripts/
│  ├─ exportar_reporte.py # CLI de la etapa 1
│  ├─ primera_prueba_powerbi.ps1  # arranque supervisado de la etapa 1
│  ├─ grabar.py           # grabador: perfil persistente + Chrome real
│  ├─ grabar_drive.ps1    # graba el flujo de Drive para sacar selectores
│  ├─ exportar_sesion.py  # diagnóstico: qué sesiones tiene el perfil
│  ├─ plan_vinculacion.py # CLI del plan de trabajo en SINU
│  ├─ clasificar_sinu.py  # CLI de la etapa 3
│  ├─ ejecutar_sinu.py    # CLI de la etapa 4 (ESCRIBE)
│  ├─ grabar_sinu.ps1     # graba el flujo de ISEF07
│  ├─ subir_reporte.py    # CLI de la etapa 2
│  ├─ flujo_dia.py        # Fase 1 -> Sheet -> Periodo -> ISEF07, un navegador
│  ├─ probar_perfil.py    # diagnostico del perfil + login unico de Google
│  ├─ sembrar_perfil.py   # copia el perfil personal al de trabajo
│  └─ validar_reporte.py  # CLI de la Fase 1
├─ data/raw/              # .xlsx descargados (NO en Git)
├─ data/processed/        # salidas coloreadas (NO en Git)
├─ logs/                  # una corrida = un archivo
├─ cun-sigwt-matricula/   # skill de negocio: reglas de SINU (referencia)
└─ tests/
```

## Seguridad

- Credenciales solo en `config/.env`, ignorado por Git. **No hay credenciales
  de Google**: la sesión de Drive vive en el perfil del navegador.
- El patrón de `.gitignore` es `config/.env*` con `!config/.env.example`, **no**
  el nombre exacto `config/.env`. La razón: el 02/09/2026 un
  `config/.env.respaldo_20260901` se coló en el primer commit y llegó a GitHub
  con las contraseñas dentro, porque el patrón estrecho no lo cubría. Cualquier
  respaldo del `.env` queda ahora ignorado por construcción.
- `data/` y `logs/` están ignorados: contienen datos personales de estudiantes.
- `MODO_SIMULACION=true` en la **plantilla**, para que una copia recién hecha no
  pueda escribir sin que alguien lo decida. En **esta** máquina está en `false`
  desde el 01/09/2026: la etapa 4 ya ejecuta de verdad. Siguen haciendo falta
  `--ejecutar-de-verdad` y `--periodo`.
- Las grabaciones de `playwright codegen` (`*_grabado.py`) llevan credenciales
  en texto plano. Se borran tras extraer los selectores y se rota la contraseña
  usada.
- `POWERBI_PERFIL_NAVEGADOR` apunta **fuera del repo**: guarda cookies de
  sesión de la cuenta.

## Notas del entorno

- El `python` del PATH es el stub de Microsoft Store y **no funciona**. Hay que
  usar el `python.exe` de una instalación real.
- **El proyecto se movió del disco `F:` a OneDrive/Escritorio y `F:` ya no
  existe.** El `.venv` que viajó con él está muerto: su `pyvenv.cfg` apunta a
  `F:\...\Python311` y no trae `Scripts\python.exe`. Hay que rehacerlo desde
  cero (ver *Instalación*) tras instalar Python; borrar el `.venv` viejo antes,
  o `python -m venv` no lo reparará.
- `.venv\`, el perfil de navegador y `config\estado_sesion.json` **no deberían
  vivir dentro de OneDrive**: la sincronización bloquea archivos mientras
  Chromium los tiene abiertos. `POWERBI_PERFIL_NAVEGADOR` ya apunta fuera del
  repo, a `C:\Users\<usuario>\.playwright-perfil-powerbi`.
- Hay un proxy TLS corporativo que rompe algunas descargas de `pip`
  (`self-signed certificate in certificate chain`). No afectó la instalación
  de `requirements.txt` ni de Chromium, pero puede reaparecer en las llamadas
  a las APIs de Google.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```
