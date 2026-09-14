"""Constantes del proceso en SINU (sigwt.cun.edu.co/sgacampus).

Extraidas de la skill de negocio `cun-sigwt-matricula` (SKILL.md y
references/vinculacion-moodle.md), que documenta el flujo tal como lo ejecuta a
mano el dueno del proceso. Son hechos del proceso, no preferencias: cambiarlos
sin volver a la referencia rompe la correspondencia con lo que se hace de verdad.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Actividades del sistema academico
# ---------------------------------------------------------------------------

# Los codigos van en MINUSCULA porque asi los expone el sistema. Comprobado el
# 24/08/2026 leyendo el menu de modulos de #home: 'isef07', 'pacf50', 'matf88'.
# Buscarlos en mayuscula fue lo que hizo fallar las primeras sondas.

#: Vinculacion individual de estudiantes a MOODLE, pestana "Grupos".
#: Es la actividad de las etapas 3 y 4.
ACTIVIDAD_VINCULACION = "isef07"

#: Integracion masiva con Moodle. Consultable para verificar los casos 2 y 3;
#: nunca escribible (ver restricciones_sinu).
ACTIVIDAD_INTEGRACION_MASIVA = "isef05"

#: Programacion de grupos. Consultable para verificar los casos 2 y 3.
ACTIVIDAD_PROGRAMACION_GRUPOS = "pacf50"

#: Consulta de estudiantes. Consultable para verificar el caso 3: alli se
#: comprueba que la materia no este activa y si tiene marca de pago.
#:
#: OJO: hasta el 24/08/2026 esto decia "ISEF88", codigo que NO EXISTE en el
#: sistema. Al leer el menu real de modulos se vio que el modulo es
#: 'matf88 Consulta de estudiantes'. Con el codigo inexistente esa verificacion
#: nunca habria podido ejecutarse.
ACTIVIDAD_MATRICULA = "matf88"

#: Vinculacion masiva de estudiantes a MOODLE. Aparece en el menu real y la
#: skill de negocio no lo mencionaba. Sin uso por ahora.
ACTIVIDAD_VINCULACION_MASIVA = "isef06"


# ---------------------------------------------------------------------------
# Grillas y controles de ISEF07
# ---------------------------------------------------------------------------

#: Grilla superior. Se filtra por la columna "No. Identificacion". Al
#: seleccionar la fila del estudiante se carga sola la grilla de Grupos con sus
#: asignaturas del periodo.
#:
#: Aqui decia "y NADA MAS: COD_MATERIA no es clave de busqueda aqui". Cierto
#: para ESTA grilla, pero se leyo como que la materia no era filtrable en
#: ninguna parte -- y la grilla GRUPOS si se filtra por ella. Ese filtro es lo
#: que permite cumplir la regla del proceso (tocar solo la materia del
#: reporte). Comprobado en produccion el 03/09/2026.
GRILLA_ESTUDIANTES = "Estudiantes"
COLUMNA_FILTRO_CEDULA = "No. Identificación"

#: Grilla inferior: las asignaturas matriculadas del estudiante seleccionado.
GRILLA_GRUPOS = "Grupos"

#: Opciones del desplegable "Accion a realizar".
ACCION_VINCULAR = "1 Vincular grupos matriculados"
ACCION_DESVINCULAR = "2 Desvincular grupos matriculados"

#: El desplegable suele conservar la ultima seleccion entre estudiantes, pero
#: tambien puede quedarse vacio. La referencia lo marca como error comun, asi
#: que hay que verificarlo en cada estudiante antes de ejecutar.
VERIFICAR_ACCION_CADA_ESTUDIANTE = True


# ---------------------------------------------------------------------------
# Tiempos observados
# ---------------------------------------------------------------------------
# El sistema es un ERP con grillas asincronas: una accion puede tardar de 1 a
# 40 segundos. Estos margenes vienen de la referencia y sirven para dimensionar
# los timeouts y para avisar al operador de cuanto va a durar un lote.

#: Filtrar por cedula y obtener la fila.
SEG_FILTRO_CEDULA = (1, 2)

#: "Vincular grupos matriculados": barra de progreso y contador de segundos.
#: Depende de cuantas asignaturas tenga el estudiante.
SEG_EJECUCION_VINCULACION = (15, 40)

#: Techo por operacion completa (filtrar + seleccionar + ejecutar + cerrar).
#: Holgado a proposito: el timeout de 30s del resto del proyecto se queda corto
#: frente a los 40s de la ejecucion.
TIMEOUT_OPERACION_SINU_SEG = 120


# ---------------------------------------------------------------------------
# Reglas del flujo
# ---------------------------------------------------------------------------

#: El filtro de Periodo (arriba a la derecha) se ajusta UNA SOLA VEZ al inicio
#: de la sesion, no por estudiante. De ahi que el trabajo se agrupe por periodo:
#: cada lote es una sesion con su periodo fijado.
PERIODO_SE_FIJA_UNA_VEZ = True

#: Numero de filas que debe devolver el filtro por cedula. Cero o mas de una
#: significa detenerse y avisar: son ajustes reales de matricula.
FILAS_ESPERADAS_POR_CEDULA = 1

#: Se comprueba el check "Vinculado?" DESPUES de cada accion, materia por
#: materia. No es una preferencia: es la unica forma de saber si la accion hizo
#: lo que dijo.
#:
#: Historia de este valor, porque estuvo en False y estaba mal:
#:
#: `references/vinculacion-moodle.md` dice "no verificar el check fila por
#: fila", y de ahi salio el False. Pero eso describe lo que la PERSONA se ahorra
#: cuando valida al final con un reporte aparte -- no lo que el robot puede
#: permitirse. El dialogo "Proceso terminado" de ISEF07 confirma que el proceso
#: CORRIO, no que la materia quedara vinculada: son cosas distintas, y la
#: segunda es la que importa.
#:
#: Aclaracion del dueno del proceso (03/09/2026): tras desvincular hay que
#: esperar la confirmacion de la desvinculacion, y tras vincular la del
#: vinculado, antes de pasar al siguiente. Y si vinculado no aparece el check
#: -- o ISEF07 no deja vincular -- se abre ISEF05 y PACF50 para validar el
#: check en Moodle y se registra en Google Sheets.
VERIFICAR_CHECK_VINCULADO = True

#: Intentos del vincular antes de dar el check por imposible y escalar. Cada
#: intento vuelve a leer la grilla: sin relectura no hay nada que reintentar.
INTENTOS_HASTA_ESCALAR = 3

#: Modulos que se consultan cuando el check no aparece. SOLO LECTURA -- la
#: matriz de `restricciones_sinu` lo sigue impidiendo escribir en ellos.
MODULOS_DE_ESCALADO = (ACTIVIDAD_INTEGRACION_MASIVA, ACTIVIDAD_PROGRAMACION_GRUPOS)


# ---------------------------------------------------------------------------
# Plazo de la EJECUCION en ISEF07 (MEDIDO el 01/09/2026)
# ---------------------------------------------------------------------------
# `TIMEOUT_OPERACION_SINU_SEG` (120 s) resulto demasiado corto para esperar el
# dialogo de "Proceso terminado", y con consecuencias graves: el reciclado que
# SI funciono tardo 124 s solo en el desvincular (17:18:57 -> 17:21:01). Es
# decir, el plazo estaba justo por debajo de la duracion real, asi que fallaba
# de forma intermitente -- y cada fallo tras el desvincular deja al estudiante
# DESVINCULADO.
#
# Coste medido de esa cota: 2 estudiantes con 13 asignaturas desvinculadas en
# los primeros 6 procesados. No es un timeout cualquiera; es el que decide si un
# reciclado se completa.
#
# Se fija con holhura sobre lo observado. Esperar de mas no cuesta nada: si el
# dialogo aparece antes, la espera termina antes.
TIMEOUT_EJECUCION_ISEF07_SEG = 300

#: Duracion observada de una accion, para estimaciones. La referencia decia
#: 15-40 s y lo medido el 01/09/2026 fue 60-125 s: el desvincular de 7 materias
#: tardo 124 s y el vincular posterior 58 s.
SEG_ACCION_OBSERVADO = (58, 125)
