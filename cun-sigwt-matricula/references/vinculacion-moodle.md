Documento de Especificación de Caso de Uso
ISEF07 – Vinculación Individual de Estudiantes a MOODLE
1. Información General y Alcance
Código de Actividad: ISEF07

Nombre de la Actividad: Vinculación individual de estudiantes a MOODLE

Pestañas del Módulo:

Grupos (Pestaña de trabajo activa para este flujo)

Traza (No utilizada en este procedimiento)

Propósito del Proceso: Vinculación (o desvinculación puntual) de estudiantes a sus cursos en Moodle, procesando cédula por cédula extraída y deduplicada desde el Excel de matrícula.

Entorno de Navegación: Instancia activa de Google Chrome utilizando la sesión persistente del usuario y navegación directa a través de la barra de Favoritos/Marcadores (sigwt.cun.edu.co/sgacampus/).

2. Insumos Requeridos
Navegador y Sesión Activa: Pestaña de Google Chrome con la sesión iniciada en el Sistema Académico SINU (sigwt.cun.edu.co/sgacampus/), con la actividad ISEF07 abierta desde los marcadores de favoritos.

Excel de Matrícula Académica: Archivo de trabajo proporcionado por el usuario (típicamente Matricula sin correo.xlsx o equivalente).

Hoja Filtrada por Periodo: El archivo debe incluir la hoja/pestaña previamente filtrada al periodo académico a trabajar (ej. 26V05).

⚠️ Atención: No utilizar la hoja "cruda" del Excel (la cual contiene múltiples periodos mezclados), sino la pestaña dedicada al periodo activo.

3. Extracción y Deduplicación de Cédulas (Python)
Dado que el Excel de matrícula genera una fila por cada asignatura inscrita y no por estudiante, se ejecuta el script en Python para extraer la lista deduplicada de números de identificación antes de iniciar el ciclo en SINU.

Bash
python3 scripts/extract_cedulas.py "<ruta_al_xlsx>" --sheet "<hoja_filtrada_al_periodo>" --column IDENTIFICACION
Entrada: Ruta del archivo .xlsx y nombre de la pestaña filtrada al periodo.

Procesamiento: Filtra y elimina cédulas duplicadas.

Salida: Lista única de números de identificación a procesar.

4. Procedimiento Operativo Detallado
Paso 0 — Configuración del Periodo (SOLO UNA VEZ AL INICIO)
En la esquina superior derecha de la interfaz de ISEF07, ubicar el campo Periodo (p. ej., 26V05).

Ingresar el código de periodo correspondiente a la hoja del Excel de trabajo.

Regla de Persistencia: Este ajuste se realiza una única vez antes de iniciar el primer estudiante. No debe volver a modificarse durante el ciclo.

Ciclo de Procesamiento por Cédula Única (Pasos 1 al 9)
[Paso 1: Filtrar Cédula] ──> [Paso 2: Validar 1 Fila] ──> [Paso 3: Seleccionar Fila]
         │
         ▼
[Paso 4: Omitir Check "Vinculado?"] ──> [Paso 5: Elegir Acción] ──> [Paso 6: Ejecutar Engranaje]
         │
         ▼
[Paso 7: Monitorear Progreso] ──> [Paso 8: Cerrar OK] ──> [Paso 9: Siguiente Cédula]
Filtrar el Estudiante:

En la grilla superior Estudiantes, hacer clic en el filtro de la columna "No. Identificación" (realizar triple-click para seleccionar y sobrescribir cualquier valor previo).

Escribir el número de cédula y presionar Enter.

Validar Resultado (1–2 segundos):

Confirmar que la grilla devuelva exactamente una (1) fila.

🔴 Parada de Seguridad: Si la búsqueda arroja 0 filas o más de 1 fila, detener el proceso de inmediato para esa cédula y avisar al usuario. No continuar con el estudiante.

Seleccionar la Fila:

Hacer clic sobre la fila del estudiante en la grilla superior.

Esto activará automáticamente la carga de la grilla inferior Grupos con las asignaturas matriculadas para el periodo seleccionado.

Tratamiento de la Grilla Grupos:

No verificar el check "Vinculado?" fila por fila: El usuario validará el estado global mediante un reporte independiente al finalizar la jornada.

Elegir la Acción a Realizar:

En el desplegable "Acción a realizar" (ubicado debajo de la grilla Grupos), verificar y seleccionar:

1 Vincular grupos matriculados (Opción por defecto para vinculación).

(Nota: La opción "2 Desvincular grupos matriculados" solo se utilizará si existe una solicitud explícita para revertir el acceso).

Verificación: Confirmar que la selección no se haya blanqueado antes de ejecutar.

Ejecutar la Acción:

Hacer clic en el primer icono (el icono superior tipo engranaje, a la izquierda del desplegable de acción).

Monitorear y Esperar Resultado (15–40 segundos):

El sistema iniciará una barra de progreso con contador de segundos.

Tomar capturas de pantalla de control cada 5 a 10 segundos hasta la aparición del mensaje modal "Nota" / "Proceso terminado".

⚠️ Regla: No hacer clics adicionales en la pantalla mientras la barra de progreso esté en ejecución.

Cerrar Diálogo de Cierre:

Hacer clic en OK dentro de la ventana emergente.

Siguiente Cédula:

Repetir el flujo desde el Paso 1 con la siguiente cédula de la lista. El campo Periodo (Paso 0) permanece inalterado.

5. Árbol de Decisión e Integración con Casos Globales
Caso	Condición en ISEF07	Acción Operativa en SINU	Registro en Reporte Diario (Google Sheet)
Caso 1: Vinculación Exitosa	
Cédula encontrada.


Asignatura visible en grilla Grupos.

Seleccionar 1 Vincular grupos matriculados → Clic en Engranaje → Confirmar con OK.	
Fila en Verde Claro


Etiqueta: OK

Caso 2: Grupo sin Integración Moodle	Cédula encontrada, pero Curso en moodle? = ☐ (sin marcar).	No accionable. Realizar verificación cruzada en PACF50 e ISEF05 para confirmar falta de check.	
Fila en Rojo Claro


Etiqueta: NO TIENE CHECK EN MOODLE

Caso 3: Sin Matrícula Académica	La búsqueda por cédula arroja 0 resultados.	No accionable. Validar en ISEF05, PACF50 e ISEF88 (Consulta de estudiantes) ausencia de carga.	
Fila en Lila


Etiqueta: NO CUENTA CON MATRÍCULA

6. Control de Errores y Excepciones Operativas
Error / Incidencia	Detección	Protocolo de Solución
Inconsistencia de Resultados (0 o >1 filas)	La grilla Estudiantes no devuelve exactamente un registro.	Detener la ejecución de la cédula. Alertar al usuario y no hacer clic sobre ninguna fila.
Desplegable de Acción Blanqueado	El campo "Acción a realizar" vuelve a quedar vacío entre estudiantes.	Re-seleccionar manualmente 1 Vincular grupos matriculados antes de pulsar el engranaje.
Uso de Hoja Incorrecta del Excel	Cédulas no encontradas masivamente al filtrar en SINU.	Verificar que el script extract_cedulas.py haya sido ejecutado sobre la hoja filtrada por periodo y no sobre la hoja cruda.
Pérdida de Sesión en Chrome	Mensaje de timeout o redirección al login de SINU.	Reabrir la actividad ISEF07 utilizando el marcador guardado en la barra de Favoritos de Chrome y reanudar en la cédula pendiente.
Bloqueo en Barra de Progreso (>40s)	La barra de progreso no llega a 100% o la modal no emerge.	Evitar clics repetidos. Si supera los 60 segundos, capturar pantalla, refrescar el módulo desde Favoritos y verificar el estado del estudiante.
