"""Selectores de la interfaz web de Google Drive (etapa 2, via Playwright).

ESTADO: **SIN VERIFICAR**. A diferencia de los de Power BI, estos no salen de
una grabacion real: se dedujeron de la estructura conocida de la UI de Drive.
Hay que confirmarlos con una grabacion antes de confiar en ellos:

    .\\scripts\\grabar_drive.ps1

y luego contrastar lo grabado con este archivo, igual que se hizo en la etapa 1.

Por que esta etapa es mas fragil que la 1
-----------------------------------------
Power BI expone `data-testid` en casi todo. Drive **no**: su UI se apoya en
roles ARIA y en textos traducidos, sin identificadores estables. Consecuencias
practicas:

- Casi todo se localiza por rol + nombre accesible, es decir por texto en
  espanol. `POWERBI_IDIOMA` (que este modulo tambien usa, via `navegador.py`)
  es lo que hace que ese texto sea predecible.
- La lista de archivos es **virtualizada**: las filas fuera de pantalla no
  existen en el DOM. De ahi el viewport amplio y la lectura por filas visibles.
- Google cambia esta UI sin avisar. Cuando algo deje de casar, hay que volver a
  grabar; no hay forma de blindarlo.

Alternativa mas robusta para la conversion
------------------------------------------
En vez de convertir por menus, conviene activar UNA VEZ, a mano:

    Drive -> Configuracion -> General -> "Convertir los archivos subidos al
    formato del editor de Google Docs"

Con eso el .xlsx aterriza ya como Google Sheet y desaparece el paso mas fragil
de todo el flujo. `subidor_drive.py` comprueba el resultado y avisa si el
archivo siguio siendo .xlsx.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------

URL_CARPETA = "https://drive.google.com/drive/folders/{id}"

#: La UI de Drive es una SPA; conviene esperar a que la rejilla exista en vez de
#: fiarse de un `load` que ocurre mucho antes.
RX_URL_CARPETA = re.compile(r"drive\.google\.com/drive/folders/(?P<id>[\w-]+)")


# ---------------------------------------------------------------------------
# Estructura de la lista de archivos
# ---------------------------------------------------------------------------

#: Contenedor de la lista de archivos.
ROL_REJILLA = "grid"

#: Roles que puede tener ese contenedor, en orden de preferencia.
#:
#: NO es "por si acaso": Drive cambia el rol segun si la carpeta tiene
#: contenido. Comprobado el 01/09/2026 en la misma corrida y con la misma
#: sesion:
#:
#:   carpeta con 7 subcarpetas  -> grid: 1, table: 0
#:   carpeta VACIA (SEPTIEMBRE) -> grid: 0, table: 1
#:
#: Exigir solo 'grid' hacia que la etapa 2 agotase el plazo de 120 s y abortara
#: en cuanto la carpeta del mes estuviera vacia -- es decir, **el dia 1 de cada
#: mes**, que es justo cuando hay que crearla y subir el primer reporte.
ROLES_REJILLA: tuple[str, ...] = ("grid", "table")

#: Cada archivo o carpeta es una fila; su nombre accesible incluye el nombre del
#: archivo, por lo que sirve tanto para localizar como para leer.
ROL_FILA = "row"

#: Atributo del que se lee el nombre cuando la fila no expone texto util.
ATRIBUTO_ETIQUETA = "aria-label"

#: Cada fila lleva el id de Drive del elemento que representa. Verificado el
#: 24/08/2026: la fila de una carpeta trae data-id="1Yzi50qZ...". Sirve para
#: entrar navegando por URL en vez de con un doble clic, que resulto ser poco
#: fiable: en una prueba entro y en la siguiente no hizo nada.
ATRIBUTO_ID_FILA = "data-id"

#: Las carpetas se distinguen de los archivos por el tipo que anuncia la fila.
RX_TIPO_CARPETA = re.compile(r"carpeta|folder", re.IGNORECASE)

#: Un Google Sheet ya convertido frente a un .xlsx sin convertir. Es la
#: comprobacion que decide si la conversion hizo falta o no.
RX_TIPO_SHEET = re.compile(r"hoja de c[aá]lculo de google|google sheets", re.IGNORECASE)
RX_NOMBRE_XLSX = re.compile(r"\.xlsx$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Subida
# ---------------------------------------------------------------------------

#: Boton "Nuevo" de la barra lateral. En algunas versiones es "+ Nuevo".
RX_BOTON_NUEVO = re.compile(r"^\+?\s*nuevo$|^new$", re.IGNORECASE)

#: Item "Subir archivo" del menu de Nuevo.
RX_MENU_SUBIR_ARCHIVO = re.compile(r"subir archivo|file upload", re.IGNORECASE)

#: Item "Nueva carpeta", para crear la del mes cuando falta.
RX_MENU_NUEVA_CARPETA = re.compile(r"nueva carpeta|new folder", re.IGNORECASE)

#: Campo del dialogo de nueva carpeta y su boton de confirmacion.
RX_INPUT_NOMBRE_CARPETA = re.compile(r"nombre de la carpeta|folder name", re.IGNORECASE)
RX_BOTON_CREAR = re.compile(r"^crear$|^create$", re.IGNORECASE)

#: Aviso de subida terminada. Drive lo muestra en un panel de progreso.
RX_SUBIDA_COMPLETA = re.compile(
    r"1 carga completada|se complet[oó] la carga|upload complete", re.IGNORECASE
)


# ---------------------------------------------------------------------------
# Menu contextual de un archivo
# ---------------------------------------------------------------------------

RX_MENU_CAMBIAR_NOMBRE = re.compile(r"cambiar nombre|^renombrar|rename", re.IGNORECASE)
RX_MENU_ABRIR_CON = re.compile(r"abrir con|open with", re.IGNORECASE)
RX_ABRIR_CON_SHEETS = re.compile(r"hojas de c[aá]lculo de google|google sheets", re.IGNORECASE)

#: Dialogo de renombrado.
RX_BOTON_ACEPTAR = re.compile(r"^aceptar$|^ok$|^guardar$|^save$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Conversion desde el editor de Sheets
# ---------------------------------------------------------------------------

#: Menu "Archivo" del editor.
RX_MENU_ARCHIVO = re.compile(r"^archivo$|^file$", re.IGNORECASE)

#: "Guardar como Hojas de calculo de Google". Solo aparece cuando el archivo
#: abierto sigue siendo un .xlsx en modo de compatibilidad con Office.
RX_GUARDAR_COMO_SHEETS = re.compile(
    r"guardar como hojas de c[aá]lculo de google|save as google sheets", re.IGNORECASE
)
