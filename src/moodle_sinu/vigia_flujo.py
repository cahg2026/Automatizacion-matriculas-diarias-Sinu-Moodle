"""Que hacer cuando una etapa del dia deja de dar senales de vida.

Por que existe
--------------
El 14/10/2026 a las 09:28:38 el Edge de la automatizacion desaparecio a mitad
del lote 26PI6 (coincidio al segundo con el arranque de la sesion de Windows:
Edge personal y VS Code se abrieron en ese instante). `ejecutar_sinu.py` se
quedo esperando a un navegador que ya no existia, sin escribir una linea mas y
sin morir. El orquestador, que leia su salida con un `for linea in stdout`,
espero con el. Nadie aviso: el aviso solo salia al TERMINAR, y no termino.
Se descubrio a las 10:46, mirando a mano. Quedaban 27 filas por tocar.

El encargo del dueno del proceso, literal en lo esencial:

  1. Si el flujo lleva 30 minutos congelado, NO cerrarlo y avisar sin mas:
     validar por que se detuvo, solucionarlo y continuar con el cargue.
  2. Mandar un aviso al calendario con por que se detuvo, en que parte del
     flujo esta, cuanto lleva y cuanto le falta.

Este modulo tiene la parte que se puede probar sin procesos: leer de la salida
donde estaba la etapa, contar el avance contra el reporte y redactar el
diagnostico. Cortar y relanzar viven en `scripts/dia_completo.py`, que es
quien tiene los procesos en la mano.

Congelada NO es lenta
---------------------
Lo que se mide es el silencio, no la duracion. Un lote que falla estudiante
tras estudiante (26PI6, 2 minutos cada uno) escribe una linea cada 2 minutos y
NO esta congelado: esta trabajando, mal, pero trabajando. 30 minutos sin UNA
sola linea no pasa en ningun paso sano -- el mas lento, una lectura de ISEF07
con reintentos, no llega a 5.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: Minutos sin una sola linea de salida para dar una etapa por congelada.
MINUTOS_SIN_AVANCE = 30

#: Veces que el paso 4 se relanza solo tras congelarse. Dos: si el mismo
#: punto congela tres veces seguidas no es un tropiezo, es un fallo que un
#: relanzamiento no arregla, y seguir insistiendo solo quema la manana.
REANUDACIONES_MAX = 2

RX_PERIODO = re.compile(r"Lanzando la etapa 4 para (\S+)")
RX_ESTUDIANTE = re.compile(r"Leyendo el estudiante (\S+)")
#: Lineas de log con marca de tiempo: "2026-10-14 09:28:52,878 INFO ...".
RX_LINEA_LOG = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")


@dataclass
class Ubicacion:
    """Donde estaba la etapa cuando dejo de hablar."""

    periodo: str = ""
    estudiante: str = ""
    ultima_linea: str = ""

    def describir(self) -> str:
        partes = []
        if self.periodo:
            partes.append(f"periodo {self.periodo}")
        if self.estudiante:
            partes.append(f"estudiante {self.estudiante}")
        return ", ".join(partes)


def ubicar(salida: str) -> Ubicacion:
    """Saca de la salida de una etapa el ultimo periodo y estudiante tocados."""
    u = Ubicacion()
    for linea in salida.splitlines():
        m = RX_PERIODO.search(linea)
        if m:
            u.periodo = m.group(1)
            u.estudiante = ""
        m = RX_ESTUDIANTE.search(linea)
        if m:
            u.estudiante = m.group(1)
        if linea.strip():
            u.ultima_linea = linea.strip()
    return u


@dataclass
class Avance:
    """Cuanto lleva el dia y cuanto le falta, en unidades (cedula + materia)."""

    total: int = 0
    hechas: int = 0
    verdes: int = 0
    rojas: int = 0
    pendientes_por_periodo: dict[str, int] = field(default_factory=dict)

    @property
    def faltan(self) -> int:
        return max(0, self.total - self.hechas)

    def describir(self) -> str:
        if not self.total:
            return f"{self.hechas} unidades procesadas (total del reporte desconocido)"
        lineas = [
            f"Lleva : {self.hechas} de {self.total} "
            f"({self.verdes} verdes, {self.rojas} con incidencia)",
            f"Falta : {self.faltan}",
        ]
        if self.pendientes_por_periodo:
            lineas.append(
                "        "
                + ", ".join(
                    f"{p} ({n})" for p, n in self.pendientes_por_periodo.items()
                )
            )
        return "\n".join(lineas)


def contar_avance(
    filas_por_periodo: dict[str, int],
    hechas_por_periodo: dict[str, int],
    *,
    verdes: int = 0,
    rojas: int = 0,
) -> Avance:
    """Cruza lo que trae el reporte con lo que ya apunto el diario de hoy."""
    pendientes = {}
    for periodo, filas in filas_por_periodo.items():
        resto = filas - hechas_por_periodo.get(periodo, 0)
        if resto > 0:
            pendientes[periodo] = resto
    return Avance(
        total=sum(filas_por_periodo.values()),
        hechas=sum(
            min(n, filas_por_periodo.get(p, n)) for p, n in hechas_por_periodo.items()
        ),
        verdes=verdes,
        rojas=rojas,
        pendientes_por_periodo=pendientes,
    )


def diagnosticar(ubicacion: Ubicacion, navegador_vivo: bool | None) -> str:
    """El porque, en una frase que se pueda leer en el movil.

    `navegador_vivo` es lo que se comprobo ANTES de cortar nada: si el
    navegador del perfil de la automatizacion ya no existia, la etapa estaba
    esperando a un muerto (lo del 14/10/2026). None si no se pudo comprobar.
    """
    if navegador_vivo is False:
        causa = (
            "el navegador de la automatizacion se cerró y la etapa se quedó "
            "esperándolo"
        )
    elif navegador_vivo is True:
        causa = (
            "el navegador seguía abierto pero dejó de responder (SINU o la "
            "página se quedaron colgados)"
        )
    else:
        causa = "la etapa dejó de responder"
    donde = ubicacion.describir()
    texto = f"{MINUTOS_SIN_AVANCE} min sin avanzar: {causa}"
    if donde:
        texto += f". Iba por {donde}"
    if ubicacion.ultima_linea:
        texto += f'. Última línea: "{_sin_marca(ubicacion.ultima_linea)[:160]}"'
    return texto


def _sin_marca(linea: str) -> str:
    """Quita fecha, nivel y modulo de una linea de log: en el movil sobran."""
    if not RX_LINEA_LOG.match(linea):
        return linea
    partes = linea.split(None, 4)
    return partes[4] if len(partes) == 5 else linea
