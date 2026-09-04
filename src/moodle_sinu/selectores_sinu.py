"""Selectores de ISEF07 en el sistema academico (sigwt.cun.edu.co/sgacampus).

ESTADO: **SIN VERIFICAR**. Como los de Drive, no salen de una grabacion: se
derivaron de la descripcion del flujo en
`cun-sigwt-matricula/references/vinculacion-moodle.md`. Hay que confirmarlos:

    .\\scripts\\grabar_sinu.ps1

Solo lectura
------------
Este modulo declara a proposito **unicamente** los selectores necesarios para
LEER. Los controles de escritura -- el desplegable "Accion a realizar" y el
icono de ejecutar -- no estan aqui: la etapa 3 no puede pulsar lo que no sabe
localizar. Cuando se implemente la etapa 4 se anadiran en un modulo aparte, y
tendra que pasar por `restricciones_sinu.exigir_modulo_escribible()`.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Acceso al sistema (VERIFICADO el 21/08/2026 sobre la pagina real)
# ---------------------------------------------------------------------------
# A diferencia del resto de este modulo, estos selectores SI se comprobaron
# contra el DOM de https://sigwt.cun.edu.co/sgacampus/.
#
# Lo primero que hay que saber: SINU es una aplicacion **SmartClient/GWT**, y
# sus ids (`isc_3T`, `isc_3W`, `isc_2X`...) los genera la libreria en cada
# carga. NO SIRVEN como selectores. Lo estable son los atributos `name` de los
# inputs y las clases CSS de los controles.

#: La URL necesita la barra final. Sin ella el servidor puede responder 404.
URL_BASE = "https://sigwt.cun.edu.co/sgacampus/"

#: Campos del formulario de acceso, por `name` (estable).
CSS_USUARIO = 'input[name="userName"]'
CSS_PASSWORD = 'input[name="password"]'

#: Campos ocultos que el formulario envia junto a las credenciales. No se
#: rellenan a mano; se documentan para no confundirlos con controles.
CSS_OCULTOS = ('input[name="auth"]', 'input[name="perfil"]')

#: El boton de enviar NO es un <button> ni un <input type=submit>: SmartClient
#: lo pinta como `<td class="button">Entrar</td>`.
TEXTO_BOTON_ENTRAR = "Entrar"
CSS_BOTON = "td.button"

#: Cabecera del panel de acceso. Sirve para saber que estamos en el login.
TEXTO_PANEL_ACCESO = "Acceso al sistema"

#: Casilla "No cerrar sesion": mantiene la sesion viva en el perfil, que es
#: justo lo que interesa con un perfil persistente.
TEXTO_NO_CERRAR_SESION = "No cerrar sesión"
RX_NO_CERRAR_SESION = re.compile(r"no cerrar sesi[oó]n", re.IGNORECASE)

#: "Salir" es la senal de sesion: aparece como `toolbarButtonDisabled` mientras
#: no hay sesion, y se habilita al entrar. Es mas fiable que buscar un menu.
TEXTO_SALIR = "Salir"
CLASE_DESHABILITADO = "toolbarButtonDisabled"

#: Enlaces del login que NO hay que pulsar por accidente.
TEXTOS_A_EVITAR = ("Cambiar clave", "¿Olvidó su clave?")

#: Selectores que confirman que la aplicacion pinto algo. SINU renderiza en el
#: documento principal: sus unicos iframes son `__gwt_historyFrame` y `basf00`,
#: ambos de infraestructura y presentes desde el principio, de modo que esperar
#: "a que haya un iframe" no dice nada. Por eso se espera a estos.
CSS_SENALES_DE_CARGA = (
    'input[name="userName"]',  # pantalla de acceso
    "td.sinuTitle",  # cabecera "Sistema academico"
    ".toolbarButtonDisabled",  # barra de herramientas ya pintada
    "td.button",
)

#: Iframes de infraestructura de GWT. Se listan para dejar claro que NO son la
#: interfaz y que no hay que esperarlos.
IDS_IFRAMES_INFRAESTRUCTURA = ("__gwt_historyFrame", "basf00")


# ---------------------------------------------------------------------------
# Menu de modulos (VERIFICADO el 24/08/2026 sobre la pantalla real)
# ---------------------------------------------------------------------------
# En `#home` hay una tabla con los 30 modulos a los que la cuenta tiene acceso,
# cada fila con su codigo y su descripcion:
#
#     isef05  Integracion Masiva con MOODLE
#     isef07  Vinculacion individual de estudiantes a MOODLE
#     pacf50  Programacion de grupos
#     matf88  Consulta de estudiantes
#
# Se entra clicando la celda del CODIGO. No hay buscador ni menu desplegable:
# `cod_enc_opcion` y el desplegable `LMS` (que es el selector de PERFIL, no de
# modulo) fueron dos hipotesis que se probaron y no sirven.
#
# Los codigos van en MINUSCULA. Buscarlos en mayuscula fue lo que hizo fallar
# las primeras sondas.

#: Al abrir un modulo, la URL pasa a `.../sgacampus/#<codigo>`. Es la senal
#: inequivoca de que se entro, igual que en Drive lo es el id de la carpeta.
def hash_de_modulo(codigo: str) -> str:
    return "#" + codigo.strip().lower()


#: Textos que solo existen dentro de ISEF07 ya cargado. Sirven para confirmar
#: que la pantalla es la que se espera y no una a medio pintar.
TEXTOS_ISEF07_CARGADO: tuple[str, ...] = (
    "Vinculado?",
    "Curso en moodle?",
    "Estudiantes",
    "Grupos",
)


# ---------------------------------------------------------------------------
# Filtro de Periodo (arriba a la derecha)
# ---------------------------------------------------------------------------
# Se ajusta UNA SOLA VEZ al inicio de la sesion, no por estudiante. De ahi que
# la etapa 3 procese un periodo completo por sesion.

# VERIFICADO el 24/08/2026: el Periodo NO es un campo de texto, es un
# desplegable de SmartClient que se pinta como `.selectItemText` con el valor
# dentro (p. ej. "26V05"). Buscarlo con get_by_label fallaba siempre.
RX_CAMPO_PERIODO = re.compile(r"periodo", re.IGNORECASE)

#: Etiqueta que precede al desplegable.
TEXTO_ETIQUETA_PERIODO = "Periodo"

#: Los desplegables de SmartClient. En ISEF07 conviven varios (empresa, LMS,
#: idioma, "Contiene", periodo), asi que hay que elegir por su valor actual:
#: el del periodo es el que casa con un codigo tipo 26V05 / 2026C.
#: OJO: al enfocarse, SmartClient RENOMBRA la clase a `selectItemTextFocused`.
#: De ahi el comodin: con `.selectItemText` exacto el control desaparece del
#: localizador en cuanto tiene el foco (comprobado el 01/09/2026).
CSS_DESPLEGABLE = '[class*="selectItemText"]'
RX_VALOR_PERIODO = re.compile(r"^\s*\d{2}[A-Z]{1,2}\d{1,2}\s*$|^\s*\d{4}[A-Z]\s*$")


# ---------------------------------------------------------------------------
# Grilla "Estudiantes" (arriba)
# ---------------------------------------------------------------------------
# La grilla ESTUDIANTES se filtra por la columna de identificacion.
#
# OJO, esto decia que "COD_MATERIA no es clave de busqueda en esta pantalla" y
# era FALSO. La grilla GRUPOS (abajo) si se filtra por `cod_materia`, y ese
# filtro es el que confina la accion de ISEF07 a una sola asignatura.
# COMPROBADO en produccion el 03/09/2026: "Grupos acotada a IED36: 1 a 1 de 1",
# y tras desvincular y vincular ninguna otra asignatura del estudiante cambio.
# Ver `filtrar_grupos_por_materia` en lector_sinu.

RX_COLUMNA_IDENTIFICACION = re.compile(r"no\.?\s*identificaci[oó]n", re.IGNORECASE)

# VERIFICADO el 24/08/2026: los filtros de columna SI son inputs, y con nombres
# estables. El de la cedula es `num_identificacion`. Junto a el conviven
# `nom_largo`, `dir_email`, `cod_unidad`, `cod_materia`, `num_grupo`...
CSS_FILTRO_CEDULA = 'input[name="num_identificacion"]'
CSS_FILTRO_MATERIA = 'input[name="cod_materia"]'
CSS_FILTRO_GRUPO = 'input[name="num_grupo"]' 

#: El filtro de columna suele ser un input dentro del encabezado. La referencia
#: menciona triple-clic para seleccionar cualquier valor previo antes de escribir.
CLICS_PARA_SELECCIONAR_FILTRO = 3

RX_GRILLA_ESTUDIANTES = re.compile(r"estudiantes", re.IGNORECASE)

# VERIFICADO el 24/08/2026: ISEF07 NO expone `role="grid"` -- hay 0. Lo que hay
# son 129 `<table>` anidadas, como es tipico de SmartClient. Localizar las
# grillas por rol no funciona; hay que hacerlo por el input de filtro que
# contienen, que si tiene nombre estable.
CSS_TABLA = "table"


# ---------------------------------------------------------------------------
# Grilla "Grupos" (abajo)
# ---------------------------------------------------------------------------
# Carga sola al seleccionar el estudiante. Trae una fila por asignatura
# matriculada en el periodo activo: es la fuente de la clasificacion.

RX_GRILLA_GRUPOS = re.compile(r"grupos", re.IGNORECASE)

#: Encabezados de las columnas que hay que leer. Los dos checks son el nucleo
#: del arbol de decision de la Fase 2.
RX_COL_CURSO_EN_MOODLE = re.compile(r"curso\s+en\s+moodle", re.IGNORECASE)
RX_COL_VINCULADO = re.compile(r"vinculado", re.IGNORECASE)
# VERIFICADO el 01/09/2026 sobre una captura de la pantalla real: la columna se
# llama "Codigo asignatura", NO "Cod. Materia". El patron anterior exigia la
# palabra 'materia' y por tanto no casaba nunca, asi que `_indices_de_columnas`
# daba la columna por ausente y la lectura abortaba con "no se identificaron las
# columnas". Se aceptan las dos formas.
RX_COL_COD_MATERIA = re.compile(
    r"c[oó]d(igo)?\.?\s*(materia|asignatura)|^\s*materia\s*$", re.IGNORECASE
)
RX_COL_NUM_GRUPO = re.compile(r"n[uú]m(ero)?\.?\s*grupo|grupo", re.IGNORECASE)

#: Un check dentro de una celda de grilla. Se lee su estado, no se pulsa.
CSS_CHECKBOX = 'input[type="checkbox"], [role="checkbox"]'

#: Atributos de los que se puede leer el estado de un check, en orden de
#: fiabilidad. `interpretar_check` normaliza lo que devuelvan.
ATRIBUTOS_ESTADO_CHECK = ("aria-checked", "checked", "data-checked", "title")


# ---------------------------------------------------------------------------
# Dialogos
# ---------------------------------------------------------------------------

#: "Nota" / "Proceso terminado" al final de una ejecucion. La etapa 3 no
#: ejecuta nada, pero puede encontrarselo si queda abierto de una sesion previa.
RX_DIALOGO_NOTA = re.compile(r"nota|proceso terminado", re.IGNORECASE)
RX_BOTON_OK = re.compile(r"^ok$|^aceptar$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Senales de carga
# ---------------------------------------------------------------------------
# El sistema es un ERP con grillas asincronas: una accion puede tardar de 1 a 40
# segundos. Nunca se dispara un paso encima de una carga en curso.

RX_INDICADOR_CARGA = re.compile(
    r"cargando|procesando|espere|loading|progreso", re.IGNORECASE
)
CSS_INDICADOR_CARGA = '[role="progressbar"], .loading, .spinner, .ui-widget-overlay'


# ---------------------------------------------------------------------------
# Recorrido de la lista de periodos (VERIFICADO el 01/09/2026)
# ---------------------------------------------------------------------------
# La lista trae 44 codigos y SmartClient la virtualiza: las opciones no existen
# en el DOM hasta que el scroller las alcanza. Se avanza con el teclado, porque
# es lo que mueve ese scroller, y se comprueba en cada vuelta.

#: Celda que contiene una opcion de la lista desplegada.
CSS_CELDA = "td"

#: Vueltas de busqueda antes de darse por vencido. Con 44 codigos y 12 pasos por
#: vuelta, 14 vueltas cubren la lista entera de sobra.
VUELTAS_LISTA_PERIODO = 14

#: Pulsaciones de ArrowDown por vuelta.
PASOS_POR_VUELTA_PERIODO = 12

#: Pulsaciones de ArrowUp para rebobinar la lista al principio antes de
#: recorrerla. Mas que los 44 codigos que hay, para no depender del punto de
#: partida: buscar solo hacia abajo hacia inalcanzable cualquier periodo que
#: ordene por encima del que ya estuviera fijado.
PASOS_REBOBINADO_PERIODO = 60


# ---------------------------------------------------------------------------
# Los checks de la grilla Grupos (VERIFICADO el 01/09/2026)
# ---------------------------------------------------------------------------
# Hallazgo que invalida `CSS_CHECKBOX`: SmartClient NO usa <input type=checkbox>
# ni role="checkbox". Medido sobre ISEF07 con un estudiante seleccionado:
#
#     input[type=checkbox] : 0
#     [role=checkbox]      : 0
#     img                  : 223   <- aqui estan los checks
#
# Cada check es un <img> y su ESTADO esta en el nombre del archivo del src.
# Por eso `ATRIBUTOS_ESTADO_CHECK` (aria-checked, checked, data-checked, title)
# no servia: ninguno existe en un <img>.

#: Los checks son imagenes.
CSS_CHECK_IMG = "img"

#: Nombre de archivo del src segun el estado. Todos CONTADOS sobre la pantalla
#: real el 01/09/2026, recorriendo 11 estudiantes de tres periodos:
#:
#:     checked.gif           19   marcado
#:     unchecked.gif         22   desmarcado
#:     checked_Disabled.gif  11   marcado y NO editable
#:     unsetcheck.gif         7   sin definir
#:
#: Ninguno se dio por convencion: el primer intento anoto 'checked.gif' como
#: "esperado por convencion de SmartClient, pendiente de confirmar", y se
#: confirmo antes de usarlo. Adivinar nombres de selector es lo que costo la
#: manana del 01/09.
IMG_CHECK_MARCADO = "checked.gif"
IMG_CHECK_DESMARCADO = "unchecked.gif"
IMG_CHECK_MARCADO_BLOQUEADO = "checked_Disabled.gif"
IMG_CHECK_SIN_DEFINIR = "unsetcheck.gif"

#: Cuarta variante, encontrada el 01/09/2026 leyendo al estudiante 1000000103:
#: sus 8 asignaturas tenian 'Curso en moodle?' = checked_Disabled y
#: 'Vinculado?' = unchecked_Disabled. Sin este nombre en la lista, las 8 filas
#: se descartaban como ILEGIBLES -- y es justo el caso que hay que vincular
#: (curso si, vinculado no). El robot habria saltado a ese estudiante en
#: silencio, que es peor que fallar.
IMG_CHECK_DESMARCADO_BLOQUEADO = "unchecked_Disabled.gif"

#: Imagenes que significan "marcado", editable o no. Un check bloqueado sigue
#: siendo un SI: 'Curso en moodle?' es informativo y se pinta deshabilitado,
#: mientras 'Vinculado?' es el accionable. Leerlo como desmarcado invertiria el
#: arbol de decision de la Fase 2.
IMG_MARCADO: frozenset[str] = frozenset(
    {IMG_CHECK_MARCADO, IMG_CHECK_MARCADO_BLOQUEADO}
)

#: Imagenes que significan "desmarcado", editable o no. El sufijo '_Disabled'
#: dice si el control se puede pulsar, NO que valor tiene: son dos ejes
#: distintos y confundirlos descarta filas buenas.
IMG_DESMARCADO: frozenset[str] = frozenset(
    {IMG_CHECK_DESMARCADO, IMG_CHECK_DESMARCADO_BLOQUEADO}
)

#: 'unsetcheck.gif' es un TERCER estado, no un desmarcado. Encaja con la regla
#: del proyecto: "un check ilegible no es un check desmarcado" -> la fila va a
#: PENDIENTE POR REVISAR en vez de inventar un caso. Tratarlo como desmarcado
#: haria que el robot vinculara a quien no debe.
IMG_ESTADOS_NO_CONCLUYENTES: frozenset[str] = frozenset({IMG_CHECK_SIN_DEFINIR})


def estado_de_imagen(src: str | None) -> bool | None:
    """Interpreta el src de un check: True marcado, False desmarcado, None ilegible.

    None NO es "desmarcado": es "no se sabe", y quien llama debe mandar la fila a
    PENDIENTE POR REVISAR. Cubre tanto 'unsetcheck.gif' como cualquier imagen
    nueva que SINU introduzca -- un nombre desconocido nunca debe interpretarse
    como un no.
    """
    if not src:
        return None
    hoja = src.rsplit("/", 1)[-1].split("?", 1)[0]
    if hoja in IMG_MARCADO:
        return True
    if hoja in IMG_DESMARCADO:
        return False
    return None


# ---------------------------------------------------------------------------
# Filas de las grillas (VERIFICADO el 01/09/2026)
# ---------------------------------------------------------------------------
# Matiz importante frente a la nota del 24/08: role="grid" da 0, pero
# **role="row" SI funciona** -- 76 filas en ISEF07. Es decir, no hay que
# localizar "la grilla" para llegar a las filas: se puede ir directo a ellas y
# desempatar por su contenido.
#
# De ahi que `_localizar_grilla` (que busca role="grid" con role="table" de
# reserva) no pueda funcionar: ninguno de los dos existe.
ROL_FILA_SINU = "row"


# ---------------------------------------------------------------------------
# La grilla Grupos termina de cargar (VERIFICADO el 01/09/2026, por captura)
# ---------------------------------------------------------------------------
# El fallo que esto arregla: se leia la grilla MIENTRAS cargaba. La captura de
# pantalla mostraba "Cargando datos..." y el pie "0 a 0 de 0 en 0 seg.", y el
# codigo concluia que el estudiante no tenia asignaturas. Cuatro sondeos
# distintos dieron "grilla vacia" por esta razon, no por un selector malo.
#
# `CSS_INDICADOR_CARGA` no lo detecta: el spinner de la grilla no es un
# progressbar ni tiene las clases habituales, es un texto.

#: Texto que SmartClient muestra dentro de la grilla mientras trae los datos.
TEXTO_CARGANDO_GRILLA = "Cargando datos"

#: Pie de la grilla cuando YA termino: "1 a 1 de 1 en 2.1 seg." Es la senal
#: fiable de "cargada", y sirve tambien para el caso legitimo de 0 filas
#: ("0 a 0 de 0"), que hay que poder distinguir de "todavia cargando".
RX_PIE_GRILLA = re.compile(r"(\d+)\s+a\s+(\d+)\s+de\s+(\d+)")

#: Encabezados reales de la grilla Grupos, en su orden, leidos de la captura:
#:
#:   Curso en moodle? | Vinculado? | Codigo asignatura | Nombre de la asignatura
#:   | Grupo | Subgrup | Pago? | Cancela...
#:
#: Se guardan para poder comprobar que la pantalla es la esperada antes de
#: fiarse de las posiciones.
COLUMNAS_GRUPOS: tuple[str, ...] = (
    "Curso en moodle?",
    "Vinculado?",
    "Código asignatura",
    "Nombre de la asignatura",
    "Grupo",
)
