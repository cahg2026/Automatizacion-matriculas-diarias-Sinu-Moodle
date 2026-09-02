"""Controles de ESCRITURA de ISEF07. Modulo aparte a proposito.

Estos selectores viven separados de `selectores_sinu.py` porque son los unicos
capaces de modificar matriculas. La etapa 3 (clasificacion) no importa este
modulo: no puede pulsar lo que no sabe localizar, y hay tests que lo comprueban
leyendo el codigo fuente.

ESTADO: **SIN VERIFICAR**. Derivados de
`cun-sigwt-matricula/references/vinculacion-moodle.md`, no de una grabacion. El
acceso a SINU (login) si esta verificado; estos controles no. Grabar con
`scripts/grabar_sinu.ps1` -- ese script avisa de NO tocarlos, asi que para la
etapa 4 hay que grabar una pasada aparte y consciente, sobre un estudiante de
prueba.

Recordatorio de la libreria: SINU es SmartClient y genera sus ids en cada carga
(`isc_3T`...). Nada de ids aqui.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Desplegable "Accion a realizar"
# ---------------------------------------------------------------------------
# Esta debajo de la grilla Grupos. La referencia advierte de dos cosas: suele
# conservar la ultima seleccion entre estudiantes, y a veces se queda vacio. Por
# eso se verifica en cada estudiante antes de ejecutar.

RX_ETIQUETA_ACCION = re.compile(r"acci[oó]n a realizar", re.IGNORECASE)

#: Textos exactos de las dos opciones, tal como los nombra la referencia.
OPCION_VINCULAR = "1 Vincular grupos matriculados"
OPCION_DESVINCULAR = "2 Desvincular grupos matriculados"

#: Reservas por si el numero o el espaciado cambian.
RX_OPCION_VINCULAR = re.compile(r"^\s*1?\s*vincular grupos matriculados", re.IGNORECASE)
RX_OPCION_DESVINCULAR = re.compile(
    r"^\s*2?\s*desvincular grupos matriculados", re.IGNORECASE
)

#: SmartClient pinta los desplegables como texto con una lista flotante.
#
#: OJO al comodin: al recibir el foco, SmartClient RENOMBRA la clase de
#: `selectItemText` a `selectItemTextFocused` -- no anade una segunda clase, la
#: cambia. Con el selector exacto `.selectItemText` el desplegable se volvia
#: invisible justo despues de seleccionar en el, y el 01/09/2026 eso llevo a
#: concluir que la seleccion no habia funcionado cuando si lo habia hecho.
CSS_TEXTO_SELECCION = '[class*="selectItemText"]'


# ---------------------------------------------------------------------------
# Boton de ejecutar
# ---------------------------------------------------------------------------
# La referencia lo describe como "el primer icono (el de mas arriba de tres,
# tipo engranaje) a la izquierda del desplegable". Es la descripcion mas fragil
# de todo el proyecto: posicional y sin texto.

#: Posicion del icono entre los tres, contando desde arriba (1-based).
POSICION_ICONO_EJECUTAR = 1
TOTAL_ICONOS = 3

RX_TITULO_EJECUTAR = re.compile(r"ejecutar|procesar|aplicar", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Dialogo de fin de proceso
# ---------------------------------------------------------------------------
# Tras ejecutar: barra de progreso y contador, entre 15 y 40 s segun cuantas
# asignaturas tenga el estudiante, y al final un dialogo "Nota" / "Proceso
# terminado" que hay que cerrar con OK.

RX_PROCESO_TERMINADO = re.compile(r"proceso terminado|proceso finalizado", re.IGNORECASE)
RX_DIALOGO_NOTA = re.compile(r"^nota$", re.IGNORECASE)
RX_BOTON_OK = re.compile(r"^\s*(ok|aceptar)\s*$", re.IGNORECASE)

#: Mensajes que indican que el proceso NO salio bien. Ante uno de estos hay que
#: detenerse, no reintentar a ciegas: son ajustes reales de matricula.
RX_MENSAJE_ERROR = re.compile(
    r"error|no se pudo|fallo|falló|sin permiso|no autorizado", re.IGNORECASE
)


# ===========================================================================
# VERIFICADO el 01/09/2026 sobre ISEF07, sin ejecutar nada
# ===========================================================================
# Se confirmo abriendo el desplegable y leyendo atributos: ninguna de las dos
# cosas escribe. Lo que sigue reemplaza a las descripciones de la referencia,
# que resultaron equivocadas en los dos controles.

# --- El desplegable ---
#
# Arranca VACIO ('\xa0'), no con la ultima seleccion. Eso rompia la localizacion
# anterior: filtraba los `.selectItemText` por `has_text=RX_OPCION_VINCULAR`, no
# encontraba ninguno y caia en `.first` de los NUEVE que hay en pantalla -- que
# es el de la empresa (CORPORACION UNIFICADA...). Habria seleccionado en el
# control equivocado.
#
# Se localiza por geometria: es el `.selectItemText` a la DERECHA de la etiqueta
# "Accion a realizar :" y a su misma altura. Medido: etiqueta en x=740 y=740
# (101x14 px), desplegable en x=846 y=736, ancho 298.
RX_ETIQUETA_ACCION_EXACTA = re.compile(r"acci[oó]n\s+a\s+realizar", re.IGNORECASE)

#: Margen vertical para dar la etiqueta y el desplegable por alineados.
TOLERANCIA_ALTURA_PX = 30

# --- Las opciones ---
#
# NO llevan el prefijo "1 " / "2 " que indicaba la referencia. Buscar el texto
# exacto con prefijo daba 0 resultados; sin prefijo, 2. Se corrigen las
# constantes y se conservan los patrones laxos, que ya funcionaban.
OPCION_VINCULAR = "Vincular grupos matriculados"
OPCION_DESVINCULAR = "Desvincular grupos matriculados"

# --- El boton de ejecutar ---
#
# No son "tres iconos tipo engranaje": son un mando de reproduccion, y cada uno
# se identifica por el NOMBRE DE SU IMAGEN, que es estable. Mucho mejor que la
# descripcion posicional de la referencia:
#
#     icon_start.png            x=711 y=740   <- ejecutar
#     icon_pause_Disabled.png   x=711 y=766
#     icon_stop_Disabled.png    x=711 y=792
IMG_ICONO_EJECUTAR = "icon_start.png"
IMG_ICONO_PAUSA = "icon_pause_Disabled.png"
IMG_ICONO_PARAR = "icon_stop_Disabled.png"

#: Clase del contenedor cuando el boton esta DESHABILITADO. Los tres la tenian
#: mientras no habia accion seleccionada. Sirve de guarda: pulsar un boton
#: deshabilitado no hace nada, y creer que se ejecuto cuando no se ejecuto es
#: peor que fallar -- el estudiante quedaria sin vincular y contado como hecho.
CLASE_BOTON_DESHABILITADO = "toolbarButtonDisabled"

#: Selector del icono de ejecutar por nombre de imagen.
CSS_ICONO_EJECUTAR = f'img[src*="{IMG_ICONO_EJECUTAR}"]'

#: Prefijo del icono de arranque y sufijo con el que SmartClient marca un boton
#: deshabilitado. Es el MISMO patron que usa para los checks de la grilla, y es
#: la senal fiable: la clase `CLASE_BOTON_DESHABILITADO` la lleva el contenedor
#: del grupo de botones, no cada boton, asi que esta presente incluso con el de
#: arranque activo (comprobado el 01/09/2026 -- mirarla bloqueaba la etapa 4).
PREFIJO_ICONO_EJECUTAR = "icon_start"
SUFIJO_DESHABILITADO = "_Disabled"

#: Celdas de la lista desplegada. VERIFICADO el 01/09/2026: las opciones son
#: `td` con clase `sinuPickListCellSelected` / `sinuPickListCellDark`, asi que el
#: prefijo `sinuPickListCell` las cubre todas.
#:
#: OJO al elegir por texto: "Vincular grupos matriculados" es SUBCADENA de
#: "Desvincular grupos matriculados". Cualquier busqueda laxa puede seleccionar
#: la accion DESTRUCTIVA creyendo elegir la benigna. Por eso los patrones
#: RX_OPCION_* van anclados con `^`.
CSS_OPCION_LISTA = "td[class*='sinuPickListCell']"
