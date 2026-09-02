"""Convencion de nombres y carpetas del Drive de reportes.

Acordada con el dueno del proceso el 21/08/2026:

    REPORTES 2026/
      AGOSTO/                       <- mes en MAYUSCULAS y en espanol
        REPORTE 21/08/2026 #159
      SEPTIEMBRE/
        REPORTE 01/09/2026 #160

Este modulo es solo reglas de negocio: no sabe si el archivo llega por API o
por navegador. Sobrevivio al cambio de la etapa 2 de la API de Drive a RPA con
Playwright precisamente por estar separado del transporte.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

#: Nombres de mes en espanol y en mayusculas. Fijos a proposito:
#: `calendar.month_name` depende del locale del sistema, y el nombre de la
#: carpeta es parte de la convencion acordada, no una preferencia de la maquina.
MESES: tuple[str, ...] = (
    "ENERO",
    "FEBRERO",
    "MARZO",
    "ABRIL",
    "MAYO",
    "JUNIO",
    "JULIO",
    "AGOSTO",
    "SEPTIEMBRE",
    "OCTUBRE",
    "NOVIEMBRE",
    "DICIEMBRE",
)

#: `REPORTE DD/MM/YYYY #N`. Sirve para leer los nombres que ya hay en Drive y
#: sacar de ahi la fecha y el consecutivo.
RX_NOMBRE_REPORTE = re.compile(
    r"^REPORTE\s+(?P<dia>\d{2})/(?P<mes>\d{2})/(?P<anio>\d{4})\s+#(?P<consecutivo>\d+)\s*$"
)

#: Caracteres que Windows no admite en un nombre de archivo. La barra de la
#: convencion es legal en Drive -- que no es un sistema de archivos -- pero no
#: en local, asi que el archivo se sube con un nombre saneado y se renombra ya
#: dentro de Drive.
_ILEGALES_EN_LOCAL = re.compile(r'[<>:"/\\|?*]')


@dataclass(frozen=True)
class ReporteEnDrive:
    """Un reporte que ya esta en Drive."""

    nombre: str
    fecha: date
    consecutivo: int
    id: str | None = None
    enlace: str | None = None


def nombre_mes(fecha: date) -> str:
    """'AGOSTO' para una fecha de agosto."""
    return MESES[fecha.month - 1]


def nombre_mes_anterior(fecha: date) -> str:
    """Nombre del mes anterior, para el cambio de mes."""
    return MESES[(fecha.month - 2) % 12]


def nombre_reporte(fecha: date, consecutivo: int) -> str:
    """'REPORTE 21/08/2026 #159'."""
    return f"REPORTE {fecha:%d/%m/%Y} #{consecutivo}"


def nombre_local_para_subir(fecha: date, consecutivo: int) -> str:
    """Nombre del archivo temporal que se sube, con la barra saneada.

    Se parece al definitivo a proposito: si el renombrado dentro de Drive
    fallara, el archivo que queda sigue siendo reconocible en vez de llamarse
    'reporte_moodle_sinu_20260821_112723.xlsx'.
    """
    return _ILEGALES_EN_LOCAL.sub("-", nombre_reporte(fecha, consecutivo)) + ".xlsx"


def leer_nombre_reporte(nombre: str) -> tuple[date, int] | None:
    """Fecha y consecutivo de un nombre de reporte, o None si no encaja.

    Tolera el sufijo '.xlsx' porque en Drive un archivo sin convertir lo lleva.
    """
    limpio = nombre.strip()
    if limpio.lower().endswith(".xlsx"):
        limpio = limpio[: -len(".xlsx")]

    m = RX_NOMBRE_REPORTE.match(limpio)
    if not m:
        return None
    try:
        fecha = date(int(m.group("anio")), int(m.group("mes")), int(m.group("dia")))
    except ValueError:
        # 'REPORTE 31/02/2026 #1' casa el patron pero no es una fecha real.
        return None
    return fecha, int(m.group("consecutivo"))


def reportes_desde_nombres(nombres: list[str]) -> list[ReporteEnDrive]:
    """Filtra una lista de nombres de Drive y deja solo los reportes."""
    encontrados: list[ReporteEnDrive] = []
    for nombre in nombres:
        leido = leer_nombre_reporte(nombre)
        if leido is None:
            continue
        fecha, consecutivo = leido
        encontrados.append(
            ReporteEnDrive(nombre=nombre.strip(), fecha=fecha, consecutivo=consecutivo)
        )
    return encontrados


def siguiente_consecutivo(reportes: list[ReporteEnDrive]) -> int | None:
    """El mayor consecutivo + 1, o None si no hay ninguno de donde partir.

    Devolver None y no 1 es deliberado: si la lectura de Drive no encontro nada,
    lo mas probable es que la lectura haya fallado, no que el historico empiece
    hoy. Arrancar en #1 cuando el real es #159 produce un nombre incorrecto que
    nadie revisa. Quien llama debe pedir el numero explicitamente.
    """
    if not reportes:
        return None
    return max(r.consecutivo for r in reportes) + 1
