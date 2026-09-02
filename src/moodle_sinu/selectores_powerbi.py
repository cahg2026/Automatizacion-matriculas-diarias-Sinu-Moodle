"""Selectores reales de la UI de Power BI, extraidos de una grabacion de codegen.

Origen: `powerbi_grabado.py`, grabacion manual del 21/08/2026 sobre
app.powerbi.com con la interfaz en espanol. **Esa grabacion ya se borro**: traia
la contrasena en texto plano. Las referencias a numeros de linea de mas abajo
son historicas, para dejar constancia de que cada selector salio de la UI real y
no de una suposicion; el archivo no se puede volver a consultar.

Este modulo es la unica fuente de verdad de los selectores;
`exportador_powerbi.py` no debe llevar cadenas de UI embebidas. Para actualizarlo
hay que volver a grabar (ver README, "Volver a grabar el flujo").

Que se descarto de la grabacion y por que
-----------------------------------------
- `page.goto("https://login.microsoftonline.com/...oauth2/v2.0/authorize?...")`
  (linea 14): no es una accion, es la redireccion del SSO que codegen anota como
  navegacion. La URL lleva `nonce`, `state` y `code_challenge` de un solo uso;
  reproducirla invalida el login. Se llega ahi siguiendo el formulario.
- Los saltos entre areas de trabajo (lineas 22-38: "CUN Digital", "Academica",
  filtro, ordenar por "Nombre", administrador de cuentas, cerrar paneles) fueron
  navegacion exploratoria del operador, no pasos del proceso.
- La pestana de Google/captcha (lineas 51-53) es ajena al flujo.
- El clic sobre `mat-dialog-actions` (linea 46) cayo en el contenedor de botones
  del dialogo, no en un control: es un clic vacio. Ver OPCION_DISENO_ACTUAL.

Fragilidad conocida
-------------------
Power BI compone varios `data-testid` con la etiqueta **traducida** de la UI
(`navbar-label-item-áreas-de-trabajo`, `pbimenu-item.Exportar datos`). Si la
cuenta cambia de idioma, esos test-ids dejan de existir. Por eso cada uno se
acompana de una expresion regular de reserva basada en el rol accesible, y el
exportador prueba primero el selector grabado y luego la reserva.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------

#: Entrada del servicio. Redirige a /singleSignOn y de ahi al formulario.
#: Grabacion lineas 9-10.
URL_INICIO = "https://app.powerbi.com/"

#: Portada tras autenticarse. Grabacion linea 21.
URL_HOME = "https://app.powerbi.com/home?experience=power-bi"


# ---------------------------------------------------------------------------
# Inicio de sesion (app.powerbi.com -> login.microsoftonline.com)
# ---------------------------------------------------------------------------

#: Grabacion lineas 11-13. Campo de correo del formulario de Power BI.
PLACEHOLDER_CORREO = "Escriba el correo electrónico"
RX_PLACEHOLDER_CORREO = re.compile(r"correo electr|email", re.IGNORECASE)

#: Grabacion lineas 15-16. Ya en el formulario de Microsoft.
PLACEHOLDER_PASSWORD = "Contraseña"
RX_PLACEHOLDER_PASSWORD = re.compile(r"contrase|password", re.IGNORECASE)

#: Grabacion linea 17.
BOTON_INICIAR_SESION = "Iniciar sesión"
RX_BOTON_INICIAR_SESION = re.compile(r"iniciar sesi|sign in", re.IGNORECASE)

#: Grabacion lineas 18-19. Dialogo "¿Mantener la sesion iniciada?". Es opcional:
#: no aparece si el perfil del navegador ya trae la decision guardada.
CHECK_NO_VOLVER_A_MOSTRAR = "No volver a mostrar"
RX_CHECK_NO_VOLVER_A_MOSTRAR = re.compile(r"no volver a mostrar|don.t show", re.IGNORECASE)
BOTON_SI = "Sí"
RX_BOTON_SI = re.compile(r"^\s*(s[íi]|yes)\s*$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Navegacion hasta el informe
# ---------------------------------------------------------------------------

#: Grabacion lineas 22, 26, 28, 30, 33. Entrada "Areas de trabajo" de la barra
#: lateral. El test-id incorpora la etiqueta traducida y acentuada.
TESTID_NAVBAR_AREAS_TRABAJO = "navbar-label-item-áreas-de-trabajo"
RX_NAVBAR_AREAS_TRABAJO = re.compile(r"reas de trabajo|workspaces", re.IGNORECASE)

#: Grabacion lineas 23, 27, 34. El nombre del area de trabajo es configurable
#: (POWERBI_WORKSPACE), aqui solo queda el rol con el que se expone.
ROL_AREA_TRABAJO = "button"

#: Grabacion linea 25: `get_by_role("row", name="Seleccionar fila Informe")`
#: .get_by_test_id("item-name"). "Seleccionar fila" es el prefijo del nombre
#: accesible de la fila; el nombre del informe va detras.
TESTID_NOMBRE_ITEM = "item-name"
PREFIJO_FILA_LISTADO = "Seleccionar fila"


def rx_fila_informe(nombre_informe: str) -> re.Pattern[str]:
    """Fila del listado del area de trabajo que corresponde a un informe."""
    return re.compile(rf"{PREFIJO_FILA_LISTADO}.*{re.escape(nombre_informe)}", re.IGNORECASE)


#: Grabacion linea 39: la caja de busqueda esta anidada dentro de la barra.
TESTID_BARRA_BUSQUEDA = "global-search-bar"
TESTID_CAJA_BUSQUEDA = "tri-search-box"

#: Grabacion linea 41. El resultado se clico por el subtitulo
#: "del area de trabajo: CUN Digital". Se conserva como ultimo recurso: casa con
#: cualquier resultado del area, no necesariamente con el informe buscado.
TEXTO_RESULTADO_AREA = "del área de trabajo: CUN"


# ---------------------------------------------------------------------------
# Exportacion del visual
# ---------------------------------------------------------------------------

# La grabacion (linea 43) clicaba `get_by_label("MOODLE-VS-SINU-EST")`, que
# parecia ser el visual. La corrida del 21/08/2026 11:11 demostro que no: ese
# aria-label es el del LIENZO del informe,
#     <exploration aria-label="MOODLE-VS-SINU-EST" data-automation-type="exploration">
# es decir la pagina entera. Al clicarlo, el boton "..." que se encontraba
# despues era el del primer visual del DOM -- un grafico -- y la exportacion
# salio en "Datos resumidos" con una sola columna.
#
# El visual correcto se identifica por su descripcion de rol, no por su titulo:
#     <div class="visualContainer" role="group" aria-roledescription="Tabla"
#          aria-label="REPORTE ">
# Solo los visuales de tabla y matriz habilitan "Datos con diseno actual", asi
# que la descripcion de rol es a la vez el localizador y la precondicion.

#: Etiqueta accesible del lienzo del informe: sirve para confirmar que estamos
#: en la pagina esperada, no para localizar el visual.
TESTID_LIENZO = "exploration"
ATRIBUTO_AUTOMATIZACION = "data-automation-type"

#: Descripciones de rol de los visuales que admiten "Datos con diseno actual".
#: Dependen del idioma de la UI, de ahi las variantes en ingles.
ROLEDESC_TABULARES: tuple[str, ...] = ("Tabla", "Matriz", "Table", "Matrix")


def css_visual_tabular() -> str:
    """Selector CSS de los visuales de tabla/matriz de la pagina.

    El modificador `i` hace la comparacion insensible a mayusculas: Power BI ha
    usado tanto 'Tabla' como 'table' segun version. Aun asi el idioma se fija
    en el contexto del navegador (POWERBI_IDIOMA), porque no basta con cubrir
    variantes: hay test-ids que incorporan la etiqueta traducida.
    """
    return ", ".join(
        f'div.visualContainer[aria-roledescription="{r}" i]' for r in ROLEDESC_TABULARES
    )


#: Contenedor de cualquier visual, para diagnosticar cuando no hay ninguna tabla.
CSS_CONTENEDOR_VISUAL = "div.visualContainer"


# ---------------------------------------------------------------------------
# Tarjetas (VERIFICADO el 21/08/2026 sobre la traza de una corrida real)
# ---------------------------------------------------------------------------
# El numero que va en el nombre del reporte NO es un consecutivo: es el valor de
# la tarjeta "NO MATRICULADO" del tablero. Confirmado por el dueno del proceso
# el 24/08/2026.
#
# Las tarjetas se localizan igual que la tabla, por descripcion de rol, y traen
# nombre y valor en el MISMO aria-label:
#
#     aria-roledescription="Tarjeta"   aria-label="NO MATRICULADO 1323."
#     aria-roledescription="Tarjeta"   aria-label="MATRICULADO (En blanco)."
#
# Ese dia la tarjeta decia 1323 y el .xlsx exportado traia 1323 filas, lo que da
# una comprobacion cruzada barata: si no coinciden, algo fallo en la exportacion.

#: Descripciones de rol de los visuales de tipo tarjeta.
ROLEDESC_TARJETAS: tuple[str, ...] = ("Tarjeta", "Card")


def css_tarjetas() -> str:
    """Selector CSS de las tarjetas de la pagina."""
    return ", ".join(
        f'div.visualContainer[aria-roledescription="{r}" i]' for r in ROLEDESC_TARJETAS
    )


#: Nombre de la tarjeta que interesa. Se compara sin distinguir el separador
#: (el reporte usa NO_MATRICULADO con guion bajo; la tarjeta, con espacio).
RX_TARJETA_NO_MATRICULADO = re.compile(r"no[\s_]*matriculado", re.IGNORECASE)

#: Valor dentro del aria-label: digitos con posibles separadores de miles, y un
#: punto final que es puntuacion de la etiqueta, no parte del numero.
RX_VALOR_TARJETA = re.compile(r"(\d[\d., \s]*)")

#: Como Power BI anuncia una tarjeta sin dato.
RX_TARJETA_EN_BLANCO = re.compile(r"en blanco|blank", re.IGNORECASE)

#: Grabacion linea 44. El boton "..." solo se materializa con el puntero sobre
#: el visual, asi que el exportador hace hover antes de clicar.
TESTID_VISUAL_MAS_OPCIONES = "visual-more-options-btn"

#: Grabacion linea 45. El test-id se compone con la etiqueta traducida del item.
ETIQUETA_MENU_EXPORTAR = "Exportar datos"
TESTID_MENU_EXPORTAR = f"pbimenu-item.{ETIQUETA_MENU_EXPORTAR}"
RX_MENU_EXPORTAR = re.compile(r"exportar datos|export data", re.IGNORECASE)

#: Grabacion linea 46. Contenedor de acciones del dialogo de exportacion; sirve
#: para esperar a que el dialogo este montado.
TESTID_DIALOGO_ACCIONES = "mat-dialog-actions"

# Opcion "Datos con diseno actual". NO quedo en la grabacion, y la corrida del
# 21/08/2026 11:11 dejo claro su marcado real:
#     <pbi-radio-button class="pbi-radio-button exportTypeRadioButton-disabled"
#                       id="pbi-radio-button-3">
#       <label data-testid="pbi-radio-button-internal" class="... disabled"
#              for="pbi-radio-button-3-input">
#         <input type="radio" data-testid="pbi-radio-button" disabled
#                aria-label="Datos con diseno actual"
#                id="pbi-radio-button-3-input">
#
# Dos consecuencias para el codigo:
#  - El input nativo esta oculto (Power BI dibuja su propio circulo), asi que
#    tiene tamano cero y NO se puede esperar a que sea "visible" ni clicar; hay
#    que actuar sobre el <label for=...> y comprobar el estado en el input.
#  - Cuando el visual no es de tabla/matriz el input llega `disabled`. El
#    defecto es entonces "Datos resumidos", que exporta otra cosa.
RX_OPCION_DISENO_ACTUAL = re.compile(r"dise[nñ]o actual|current layout", re.IGNORECASE)

#: Grupo de radios del dialogo de exportacion.
TESTID_GRUPO_RADIOS = "pbi-radio-group"

#: Los inputs de radio del grupo. Comparten test-id, se distinguen por el
#: aria-label.
CSS_RADIO_EXPORTACION = 'input[type="radio"]'

#: Grabacion linea 48. Boton que confirma la descarga.
TESTID_BOTON_EXPORTAR = "export-btn"
