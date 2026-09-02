"""El Periodo del dia, leido del Google Sheet, y el cerrojo de secuencia.

La regla (dueno del proceso, 31/08/2026)
----------------------------------------
El Sheet del dia va PRIMERO. La pantalla ISEF07 se abre despues, y el valor con
el que se fija su filtro de Periodo sale de la **primera fila de datos** del
Sheet. Si ISEF07 se abriera antes de tener el Sheet cargado, el proceso se
detiene: sin fuente de origen no hay periodo que seleccionar, y fijar uno a
ojo significaria vincular matriculas del periodo equivocado.

De ahi que este modulo exponga dos cosas y no una: el lector (`leer_periodo`) y
el cerrojo (`exigir_sheet_listo`), que es lo que convierte "primero el Sheet" en
algo que falla ruidosamente en vez de depender del orden de las llamadas.

Por que no se raspa la cuadricula
---------------------------------
Google Sheets **pinta la cuadricula en un `<canvas>`**: las celdas no existen en
el DOM, asi que no hay nada que seleccionar con Playwright. Lo que si funciona
es pedir el documento en CSV por su URL de exportacion, con las cookies de la
misma pestana que ya esta abierta. Es el mismo documento y la misma sesion, pero
el valor llega como texto en vez de como pixeles.

Eso hace que la pestana abierta siga siendo un requisito de verdad y no un
adorno: de ella salen la URL (el id del documento y el gid de la hoja) y la
sesion de Google con la que se autoriza la descarga.
"""

from __future__ import annotations

import csv
import io
import logging
import re

from playwright.sync_api import Error as ErrorPlaywright, Page

from .config import Config
from .constantes import COL_COD_PERIODO

log = logging.getLogger(__name__)

#: URL de un documento de Sheets: .../spreadsheets/d/<id>/edit#gid=<gid>
RX_ID_SHEET = re.compile(r"/spreadsheets/d/([a-zA-Z0-9_-]+)")
RX_GID_SHEET = re.compile(r"[#&?]gid=(\d+)")

#: Sufijo de exportacion en CSV de UNA hoja del documento.
PLANTILLA_EXPORT_CSV = (
    "https://docs.google.com/spreadsheets/d/{id}/export?format=csv&gid={gid}"
)

#: Marcas de que lo devuelto es la pagina de login de Google y no el CSV. Pasa
#: cuando la sesion del perfil ha caducado.
_SENALES_LOGIN = ("accounts.google.com", "<!doctype html", "<html")


class ErrorPeriodoSheet(RuntimeError):
    """No se pudo obtener el periodo del Sheet. El mensaje dice por que."""


class ErrorSecuencia(ErrorPeriodoSheet):
    """Se intento abrir ISEF07 sin tener el Sheet listo.

    Es la regla de validacion del proceso, no un fallo tecnico: se separa para
    que quien llama pueda distinguir 'hay que reintentar' de 'hay que parar'.
    """


def exigir_sheet_listo(pagina_sheet: Page | None) -> Page:
    """Cerrojo de secuencia: el Sheet tiene que estar abierto ANTES que ISEF07.

    Returns:
        La misma pagina, ya comprobada, para poder encadenar.

    Raises:
        ErrorSecuencia: si no hay pestana, si se cerro, o si la que hay no es
            un documento de Sheets.
    """
    if pagina_sheet is None:
        raise ErrorSecuencia(
            "No hay pestana del Google Sheet del dia. El proceso se detiene: "
            "ISEF07 no puede abrirse antes que el Sheet, porque el filtro de "
            "Periodo se toma de su primera fila."
        )
    if pagina_sheet.is_closed():
        raise ErrorSecuencia(
            "La pestana del Google Sheet se cerro. El proceso se detiene: sin "
            "ella no hay fuente de origen para el Periodo."
        )
    url = pagina_sheet.url
    if not RX_ID_SHEET.search(url):
        raise ErrorSecuencia(
            f"La pestana que deberia tener el Sheet apunta a '{url[:90]}', que "
            "no es un documento de Google Sheets. El proceso se detiene."
        )
    log.info("Cerrojo de secuencia OK: el Sheet del dia esta abierto.")
    return pagina_sheet


def url_export_csv(url_sheet: str) -> str:
    """URL de exportacion en CSV de la hoja que se este viendo.

    El `gid` sale de la propia URL para no asumir que la hoja util es la
    primera: al convertir el .xlsx, Drive conserva el nombre de la hoja
    ('Export') pero no garantiza que su gid sea 0.
    """
    id_doc = RX_ID_SHEET.search(url_sheet)
    if not id_doc:
        raise ErrorPeriodoSheet(f"No se reconoce el id del Sheet en '{url_sheet[:90]}'.")
    gid = RX_GID_SHEET.search(url_sheet)
    return PLANTILLA_EXPORT_CSV.format(id=id_doc.group(1), gid=gid.group(1) if gid else "0")


def _descargar_csv(pagina_sheet: Page, cfg: Config) -> str:
    """Descarga el Sheet en CSV con las cookies de esa misma pestana."""
    url = url_export_csv(pagina_sheet.url)
    log.debug("Exportando el Sheet a CSV: %s", url)
    try:
        respuesta = pagina_sheet.request.get(url, timeout=cfg.timeout_operacion_seg * 1000)
    except ErrorPlaywright as exc:
        raise ErrorPeriodoSheet(f"No se pudo descargar el Sheet en CSV: {exc}") from exc

    if not respuesta.ok:
        raise ErrorPeriodoSheet(
            f"La exportacion del Sheet respondio HTTP {respuesta.status}. "
            "Si es 401/403, la sesion de Google del perfil caduco: abrir el "
            "navegador visible y volver a entrar."
        )

    texto = respuesta.text()
    cabeza = texto[:200].lower()
    if any(senal in cabeza for senal in _SENALES_LOGIN):
        raise ErrorPeriodoSheet(
            "La exportacion devolvio HTML en vez de CSV: casi siempre es la "
            "pagina de login de Google. La sesion del perfil caduco."
        )
    return texto


def periodo_de_csv(texto_csv: str, *, columna: str = COL_COD_PERIODO) -> str:
    """Periodo de la PRIMERA fila de datos del CSV.

    Se localiza la columna por su nombre en el encabezado y no por posicion:
    la copia que se sube lleva una columna anadida (VALIDACION_RPA) y el dia
    que Power BI reordene la vista, la posicion cambiaria sin avisar.

    Raises:
        ErrorPeriodoSheet: si falta el encabezado, la columna o los datos, o si
            el periodo de la primera fila viene vacio.
    """
    filas = list(csv.reader(io.StringIO(texto_csv)))
    if not filas:
        raise ErrorPeriodoSheet("El Sheet exportado esta vacio.")

    encabezado = [c.strip() for c in filas[0]]
    if columna not in encabezado:
        raise ErrorPeriodoSheet(
            f"El Sheet no trae la columna '{columna}'. Encabezado leido: "
            f"{encabezado[:16]}. Revisar que la pestana abierta sea la hoja de "
            "datos y no otra."
        )
    indice = encabezado.index(columna)

    for numero, fila in enumerate(filas[1:], start=2):
        if not any(c.strip() for c in fila):
            continue  # fila en blanco
        valor = fila[indice].strip() if indice < len(fila) else ""
        if not valor:
            raise ErrorPeriodoSheet(
                f"La primera fila de datos del Sheet (fila {numero}) no trae "
                f"'{columna}'. El proceso se detiene: no hay periodo con el que "
                "fijar el filtro de ISEF07."
            )
        log.info("Periodo leido de la fila %d del Sheet: '%s'", numero, valor)
        return valor

    raise ErrorPeriodoSheet("El Sheet no tiene ninguna fila de datos bajo el encabezado.")


def filas_de_csv(texto_csv: str) -> list[dict[str, str]]:
    """Todas las filas de datos del CSV, como diccionarios por nombre de columna.

    Se localizan las columnas por su nombre y no por posicion, por lo mismo que
    en `periodo_de_csv`: la copia subida lleva VALIDACION_RPA de mas.
    """
    filas_csv = list(csv.reader(io.StringIO(texto_csv)))
    if not filas_csv:
        raise ErrorPeriodoSheet("El Sheet exportado esta vacio.")

    encabezado = [c.strip() for c in filas_csv[0]]
    salida: list[dict[str, str]] = []
    for fila in filas_csv[1:]:
        if not any(c.strip() for c in fila):
            continue
        registro = {
            nombre: (fila[i].strip() if i < len(fila) else "")
            for i, nombre in enumerate(encabezado)
            if nombre
        }
        salida.append(registro)
    return salida


def leer_filas(pagina_sheet: Page | None, cfg: Config) -> list[dict[str, str]]:
    """Filas del Sheet abierto. Aplica el cerrojo de secuencia primero.

    Es lo que convierte al Sheet en la fuente de verdad de verdad. Antes la
    lista de estudiantes salia del .xlsx local y solo el Periodo del Sheet, asi
    que corregir un dato en el Sheet -- rellenar un CORREO, quitar una fila -- no
    tenia ningun efecto sobre lo que la automatizacion hacia. Eso contradecia la
    regla del proceso: los datos se toman del Sheet.

    Raises:
        ErrorSecuencia: si el Sheet no esta listo.
        ErrorPeriodoSheet: si no se pudo descargar o interpretar.
    """
    pagina = exigir_sheet_listo(pagina_sheet)
    filas = filas_de_csv(_descargar_csv(pagina, cfg))
    log.info("Leidas %d filas de datos del Sheet.", len(filas))
    return filas


def leer_periodo(pagina_sheet: Page | None, cfg: Config) -> str:
    """Periodo de la primera fila del Sheet abierto. Aplica el cerrojo primero.

    Raises:
        ErrorSecuencia: si el Sheet no esta listo (regla de validacion).
        ErrorPeriodoSheet: si esta listo pero no se pudo leer el periodo.
    """
    pagina = exigir_sheet_listo(pagina_sheet)
    return periodo_de_csv(_descargar_csv(pagina, cfg))


def comprobar_contra_plan(periodo_sheet: str, periodo_plan: str | None) -> list[str]:
    """Compara el periodo del Sheet con el que calculo el plan local.

    Los dos tienen que coincidir: el .xlsx se ordena A-Z antes de subirlo, asi
    que la primera fila del Sheet es el primer lote del plan. Que no coincidan
    significa que lo subido no es lo que se valido -- por ejemplo, que la
    pestana abierta sea el reporte de ayer -- y eso hay que verlo antes de
    tocar matriculas, no despues.

    Returns:
        Lista de advertencias. Vacia si todo cuadra.
    """
    if periodo_plan is None:
        return ["El plan local no tiene lotes; no hay con que contrastar el Sheet."]
    if periodo_sheet.strip().upper() != periodo_plan.strip().upper():
        return [
            f"El Periodo del Sheet ('{periodo_sheet}') NO coincide con el primer "
            f"lote del plan local ('{periodo_plan}'). Suele significar que la "
            "pestana abierta no es el reporte de hoy. Manda el Sheet, que es la "
            "fuente de origen, pero conviene comprobarlo antes de ejecutar."
        ]
    return []
