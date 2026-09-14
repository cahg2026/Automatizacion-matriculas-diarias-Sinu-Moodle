"""Leer el estado de la tarea programada, sin depender del idioma de Windows.

`schtasks /Query /FO LIST /V` saca las etiquetas TRADUCIDAS ("Estado",
"Proxima ejecucion"...), asi que analizar esa salida ata el codigo al idioma
del equipo. En cambio `schtasks /Query /XML` devuelve el XML de la tarea, cuya
estructura es la misma en cualquier idioma.

Es la misma leccion que ya dio Power BI: los selectores en espanol funcionaban
hasta que Chromium headless arrancaba en ingles. Aqui se evita de raiz.

La "proxima ejecucion" no se lee: se CALCULA a partir del disparador. Windows
la expone tambien traducida y en formato local, y calcularla evita interpretar
fechas ambiguas -- el mismo problema de dia/mes que ya obligo a poner una
guarda en la lectura del tablero.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from xml.etree import ElementTree

log = logging.getLogger(__name__)

NOMBRE_TAREA = "MoodleSinu-FlujoDiario"

#: El espacio de nombres del XML del Programador de tareas.
NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}

#: 0 = lunes ... 4 = viernes.
ULTIMO_LABORABLE = 4


@dataclass(frozen=True)
class EstadoTarea:
    """Lo que hay registrado ahora mismo."""

    existe: bool = False
    habilitada: bool = False
    una_vez: bool = False
    """True si el disparador es de una sola ejecucion."""

    hora: str = ""
    """HH:MM del disparador."""

    escribe: bool = False
    """True si la tarea lleva --ejecutar-de-verdad. Es lo que decide si toca
    matriculas reales, asi que se muestra siempre."""

    proxima: datetime | None = None

    @property
    def encendida(self) -> bool:
        return self.existe and self.habilitada

    def resumen(self) -> str:
        if not self.existe:
            return "SIN PROGRAMAR"
        if not self.habilitada:
            return "APAGADA"
        return "ENCENDIDA - una sola vez" if self.una_vez else "ENCENDIDA - L a V"


def _schtasks(*argumentos: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["schtasks.exe", *argumentos],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def siguiente_laborable(momento: datetime) -> datetime:
    """Adelanta al siguiente dia laborable si cae en fin de semana."""
    while momento.weekday() > ULTIMO_LABORABLE:
        momento += timedelta(days=1)
    return momento


def calcular_proxima(
    hora: str, una_vez: bool, inicio: datetime | None, ahora: datetime | None = None
) -> datetime | None:
    """Cuando volvera a dispararse.

    Con `una_vez`, solo hay proxima si el momento programado aun no ha pasado:
    un disparador de una sola vez ya consumido no vuelve.
    """
    referencia = ahora or datetime.now()
    if una_vez:
        if inicio is None:
            return None
        return inicio if inicio > referencia else None

    try:
        h, m = (int(x) for x in hora.split(":"))
    except (ValueError, AttributeError):
        return None
    candidato = referencia.replace(hour=h, minute=m, second=0, microsecond=0)
    if candidato <= referencia:
        candidato += timedelta(days=1)
    return siguiente_laborable(candidato)


def interpretar_xml(xml: str, ahora: datetime | None = None) -> EstadoTarea:
    """Interpreta el XML que devuelve `schtasks /Query /XML`.

    Funcion pura para poder probarla sin tocar el Programador de tareas.
    """
    try:
        raiz = ElementTree.fromstring(xml.lstrip("﻿"))
    except ElementTree.ParseError as exc:
        log.warning("No se pudo interpretar el XML de la tarea: %s", exc)
        return EstadoTarea()

    def texto(ruta: str, defecto: str = "") -> str:
        nodo = raiz.find(ruta, NS)
        return (nodo.text or "").strip() if nodo is not None else defecto

    # `Settings/Enabled` es lo que apaga y enciende la tarea entera. El
    # `Enabled` del disparador es otro y no se toca aqui.
    habilitada = texto("t:Settings/t:Enabled", "true").lower() != "false"

    una_vez = raiz.find("t:Triggers/t:TimeTrigger", NS) is not None
    nodo_disp = raiz.find("t:Triggers/t:TimeTrigger", NS)
    if nodo_disp is None:
        nodo_disp = raiz.find("t:Triggers/t:CalendarTrigger", NS)

    inicio = None
    hora = ""
    if nodo_disp is not None:
        crudo = nodo_disp.find("t:StartBoundary", NS)
        if crudo is not None and crudo.text:
            try:
                inicio = datetime.fromisoformat(crudo.text.strip()[:19])
                hora = f"{inicio:%H:%M}"
            except ValueError:
                pass

    argumentos = texto("t:Actions/t:Exec/t:Arguments")
    return EstadoTarea(
        existe=True,
        habilitada=habilitada,
        una_vez=una_vez,
        hora=hora,
        escribe="--ejecutar-de-verdad" in argumentos,
        proxima=calcular_proxima(hora, una_vez, inicio, ahora),
    )


def leer_estado(nombre: str = NOMBRE_TAREA) -> EstadoTarea:
    """Estado actual de la tarea. `existe=False` si no esta registrada."""
    r = _schtasks("/Query", "/TN", nombre, "/XML", "ONE")
    if r.returncode != 0:
        return EstadoTarea()
    return interpretar_xml(r.stdout)


def encender(nombre: str = NOMBRE_TAREA) -> tuple[bool, str]:
    r = _schtasks("/Change", "/TN", nombre, "/ENABLE")
    return r.returncode == 0, (r.stderr or r.stdout).strip()


def apagar(nombre: str = NOMBRE_TAREA) -> tuple[bool, str]:
    r = _schtasks("/Change", "/TN", nombre, "/DISABLE")
    return r.returncode == 0, (r.stderr or r.stdout).strip()
