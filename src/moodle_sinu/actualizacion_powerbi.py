"""Fecha de ultima actualizacion del tablero de Power BI.

Es el cerrojo que decide si el dia se procesa o se avisa: si el tablero no se
actualizo hoy, el reporte que se exportaria es el de ayer, y vincular sobre
datos viejos ensucia matriculas que ya estaban bien.

De donde sale el dato (comprobado sobre el tablero real el 08/09/2026, no
supuesto -- se sondeo con `scripts/sondear_actualizacion.py`):

  - El .xlsx exportado NO la trae. Su unica fila de pie lista los filtros
    aplicados; las 15 columnas son todas de datos.
  - Las tarjetas del tablero tampoco: solo hay 'MATRICULADO' y 'NO MATRICULADO'.
  - Si la trae la BARRA DE HERRAMIENTAS SUPERIOR de Power BI Service, a la
    derecha de "ValidacionMoodle |" y a la izquierda del buscador global. No
    esta en el lienzo del informe, que es por lo que ningun localizador de
    visuales lo ve. Cadena de ancestros medida:

        SPAN.data-updated          <- el texto: "Datos actualizados el 8/9/26"
         BUTTON.info-bar           <- de aqui sale la flecha: es un desplegable
          ARTIFACT-INFO
           DIV.topNavLeft
            HEADER
             TRIDENT-HEADER#header <- la barra principal

Por eso el localizador es `#header span.data-updated` y no el texto: la clase
es semantica y NO depende del idioma, mientras que buscar "Datos actualizados"
se rompe el dia que la interfaz salga en ingles. Se acota a `#header` para que
no pueda confundirse jamas con contenido del lienzo.

Ojo con el momento de leerlo: hay que esperar el lienzo (`_verificar_pagina`)
antes de mirar. Sobre la pantalla de carga de Power BI todo sale vacio, y eso
se leeria como "no hay fecha" en vez de "aun no ha cargado".
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime

log = logging.getLogger(__name__)

#: El texto tal como lo pinta el tablero, en es-CO. La etiqueta es obligatoria:
#: sin ella cualquier fecha suelta de la pagina valdria, y eso es justo el tipo
#: de falso positivo que no se puede permitir en un cerrojo.
RX_ACTUALIZADO = re.compile(
    r"datos\s+actualizados\s+el\s+(\d{1,2})/(\d{1,2})/(\d{2,4})",
    re.IGNORECASE,
)

#: Localizador principal: la clase es semantica y no depende del idioma.
#: Acotado a #header (la barra superior) para que no pueda casar con el lienzo.
CSS_DATO_ACTUALIZADO = "#header span.data-updated"

#: Respaldo por texto, si algun dia cambian las clases de Angular. Depende del
#: idioma, y por eso NO es el camino principal.
TEXTO_ANCLA = "Datos actualizados"

#: Umbral de los anos de dos cifras. '26' es 2026, no 1926.
SIGLO = 2000


class ErrorFechaActualizacion(RuntimeError):
    """No se pudo determinar cuando se actualizo el tablero.

    Se distingue de "el tablero esta viejo": no saberlo NO es lo mismo que
    saber que esta desactualizado, y el operador tiene que poder diferenciar
    un tablero de ayer de un cambio en el tablero que rompio la lectura.
    """


@dataclass(frozen=True)
class Actualizacion:
    """Lo que dice el tablero sobre su propia frescura."""

    fecha: date
    """Fecha de actualizacion, ya interpretada."""

    texto: str
    """El texto crudo del que salio. Va al log y a la notificacion: si algun
    dia la interpretacion falla, esto es lo que permite verlo."""

    def es_de(self, dia: date) -> bool:
        """True si el tablero se actualizo ese dia. El criterio de exito."""
        return self.fecha == dia

    def es_anterior_a(self, dia: date) -> bool:
        """True si el tablero es de un dia ANTERIOR. El criterio de falla.

        Se distingue de `not es_de(...)` porque una fecha posterior no es un
        tablero viejo: es una lectura girada (dia/mes leidos al reves), y esa
        se rechaza antes de llegar aqui.
        """
        return self.fecha < dia

    @property
    def dias_de_retraso(self) -> int:
        """Cuantos dias lleva el tablero sin actualizarse, contra hoy."""
        return (date.today() - self.fecha).days


def fecha_de_texto(texto: str, *, hoy: date | None = None) -> Actualizacion:
    """Interpreta 'Datos actualizados el 8/9/26'.

    El formato es DIA/MES/ANO: el navegador se abre con POWERBI_IDIOMA=es-CO
    (ver config), asi que Power BI pinta la fecha corta a la colombiana. Con
    en-US saldria mes primero y esto la leeria del reves.

    Por eso hay una guarda: una fecha futura no es una fecha de actualizacion.
    Si el dia y el mes se hubieran intercambiado, o el idioma del navegador
    cambiara, lo normal es caer en el futuro, y entonces se prefiere fallar a
    devolver un dato dado la vuelta.

    Raises:
        ErrorFechaActualizacion: si no aparece el texto, o la fecha no es una
            fecha valida, o cae en el futuro.
    """
    m = RX_ACTUALIZADO.search(texto or "")
    if m is None:
        raise ErrorFechaActualizacion(
            f"No se encontro '{TEXTO_ANCLA} el <d/m/aa>' en el tablero. "
            f"Si el tablero cambio, volver a sondear con "
            f"scripts/sondear_actualizacion.py."
        )

    dia, mes, ano = (int(g) for g in m.groups())
    if ano < 100:
        ano += SIGLO

    try:
        fecha = date(ano, mes, dia)
    except ValueError as exc:
        raise ErrorFechaActualizacion(
            f"'{m.group(0)}' no es una fecha valida leida como dia/mes/ano "
            f"({exc}). Comprobar POWERBI_IDIOMA."
        ) from exc

    referencia = hoy or date.today()
    if fecha > referencia:
        raise ErrorFechaActualizacion(
            f"El tablero dice haberse actualizado el {fecha:%d/%m/%Y}, que es "
            f"futuro respecto a hoy ({referencia:%d/%m/%Y}). Lo mas probable "
            f"es que la fecha venga en mes/dia (navegador en otro idioma): "
            f"revisar POWERBI_IDIOMA antes de fiarse del dato."
        )

    return Actualizacion(fecha=fecha, texto=m.group(0).strip())


def leer_actualizacion(page, cfg) -> Actualizacion:
    """Lee la fecha de actualizacion de un informe YA renderizado.

    Importante: llamar DESPUES de esperar el lienzo. Sobre la pantalla de carga
    el texto no existe todavia y esto lanzaria ErrorFechaActualizacion como si
    el tablero hubiera cambiado.

    Se intenta primero el nodo concreto (hay exactamente uno) y, si no
    aparece, se barre el texto de la pagina. El barrido es el respaldo, no el
    camino principal: la etiqueta del regex lo mantiene seguro, pero el nodo da
    mejores mensajes de error.
    """
    plazo = getattr(cfg, "timeout_operacion_seg", 30) * 1000

    # Tres capas, de la mas precisa a la mas tosca. Cada una es respaldo de la
    # anterior, no un camino alternativo: si la primera funciona no se usa
    # ninguna otra, y el log dice por cual entro.
    intentos = (
        ("clase del header", lambda: page.locator(CSS_DATO_ACTUALIZADO)),
        ("texto en el header", lambda: page.locator("#header").get_by_text(
            TEXTO_ANCLA, exact=False
        )),
        ("texto en la pagina", lambda: page.get_by_text(TEXTO_ANCLA, exact=False)),
    )

    for nombre, construir in intentos:
        try:
            loc = construir()
            if loc.count() == 0:
                log.debug("Sin coincidencias por %s.", nombre)
                continue
            loc.first.wait_for(state="visible", timeout=plazo)
            crudo = (loc.first.inner_text() or "").strip()
            resultado = fecha_de_texto(crudo)
            log.info(
                "Fecha de actualizacion del tablero (%s): %r", nombre, resultado.texto
            )
            return resultado
        except ErrorFechaActualizacion:
            # El nodo estaba pero su texto no se pudo interpretar. Eso NO se
            # arregla probando otro localizador: el tablero cambio de formato y
            # hay que decirlo, no seguir buscando hasta encontrar cualquier
            # fecha que encaje en la pagina.
            raise
        except Exception as exc:  # noqa: BLE001 - se pasa a la capa siguiente
            log.debug("Fallo el localizador por %s (%s).", nombre, exc)

    # Ultimo recurso: barrer el texto de la pagina. La etiqueta obligatoria del
    # regex es lo que lo mantiene seguro; sin ella cualquier fecha suelta valdria.
    try:
        cuerpo = page.locator("body").inner_text()
    except Exception as exc:  # noqa: BLE001
        raise ErrorFechaActualizacion(
            f"No se pudo leer el texto de la pagina del tablero: {exc}"
        ) from exc

    resultado = fecha_de_texto(cuerpo)
    log.warning(
        "Fecha de actualizacion leida por BARRIDO de la pagina (%r). Los "
        "localizadores del header fallaron: conviene volver a sondear con "
        "scripts/sondear_actualizacion.py.",
        resultado.texto,
    )
    return resultado


def formatear(actualizacion: Actualizacion | None, hoy: date | None = None) -> str:
    """Una linea para el log y para la notificacion."""
    referencia = hoy or date.today()
    if actualizacion is None:
        return "fecha de actualizacion del tablero: NO SE PUDO LEER"
    retraso = (referencia - actualizacion.fecha).days
    if retraso == 0:
        return f"tablero actualizado HOY ({actualizacion.fecha:%d/%m/%Y})"
    if retraso == 1:
        return f"tablero actualizado AYER ({actualizacion.fecha:%d/%m/%Y})"
    return (
        f"tablero actualizado el {actualizacion.fecha:%d/%m/%Y}, "
        f"hace {retraso} dias"
    )


def _hoy_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d")
