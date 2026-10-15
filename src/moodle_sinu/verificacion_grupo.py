"""Verificar si un grupo tiene curso en MOODLE: solo con la 50 (PACF50).

Regla del dueno del proceso (06/10/2026)
----------------------------------------
    Si una materia no tiene check en MOODLE en la 50, no va a existir en la 05.
    La 05 no nos impacta ni para bien ni para mal: se retira.

Hasta esta fecha se consultaba primero la 05 (ISEF05) y despues la 50, cada una
en su navegador. Pero desde el 28/09/2026 la 50 ya mandaba en todo lo que
importa -- es la que dice si el grupo EXISTE, y cuando contestaba su respuesta
prevalecia --, asi que la 05 solo anadia tiempo, un navegador mas y el riesgo
de dejar inerte la grilla de la 07 al volver (ver la memoria del 26/09/2026).

Que decide cada desenlace
-------------------------
La pregunta que importa es una sola: **¿se puede vincular este grupo?** Y solo
un "NO" con fundamento descarta filas. "No lo se" nunca descarta: el 25/09/2026
se cerraron 68 filas de dos grupos SANOS como "validar a mano", y una se reparo
despues con un solo vincular en 44,8 s.

Este modulo no abre navegadores ni sabe de Playwright: recibe la consulta como
funcion y devuelve el veredicto. Asi la regla se prueba entera sin SINU.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Callable

log = logging.getLogger(__name__)


class Fuente(str, Enum):
    """Quien dio la respuesta que se usa."""

    PACF50 = "pacf50"
    NINGUNA = "ninguna"


@dataclass(frozen=True)
class Veredicto:
    """Lo que se sabe del grupo tras preguntar."""

    objetivo: str
    tiene_curso: bool | None
    """True, False, o None cuando la 50 no pudo contestar."""

    fuente: Fuente
    detalle: str = ""
    consultadas: tuple[Fuente, ...] = ()
    """A quien se pregunto. Va al registro: si un dia hay que revisar un
    descarte, lo primero es saber quien lo dijo."""

    grupo_existe: bool | None = None
    """False si PACF50 dice que el grupo NO esta programado. None si no se sabe."""

    @property
    def grupo_inexistente(self) -> bool:
        return self.grupo_existe is False

    @property
    def descartar_grupo(self) -> bool:
        """Si hay que marcar TODAS sus filas sin procesar ninguna.

        Solo con un NO fundado: sin curso, o grupo inexistente en PACF50.
        `None` -- nadie contesto -- significa seguir procesando por ISEF07, que
        es la direccion segura.
        """
        return self.tiene_curso is False or self.grupo_inexistente

    def resumen(self) -> str:
        estado = {True: "SI tiene curso", False: "NO tiene curso", None: "sin respuesta"}
        preguntadas = "+".join(f.value for f in self.consultadas) or "ninguna"
        if self.grupo_inexistente:
            return (
                f"{self.objetivo}: el GRUPO NO EXISTE en SINU (segun "
                f"{self.fuente.value}; consultadas: {preguntadas})"
                + (f" -- {self.detalle}" if self.detalle else "")
            )
        return (
            f"{self.objetivo}: {estado[self.tiene_curso]} "
            f"(segun {self.fuente.value}; consultadas: {preguntadas})"
            + (f" -- {self.detalle}" if self.detalle else "")
        )


#: Lo que devuelve la consulta: (tiene_curso, detalle[, grupo_existe]).
#: tiene_curso None significa "no pude contestar", que NO es "no tiene curso".
#: grupo_existe False es "PACF50 no tiene ese grupo" (28/09/2026).
Respuesta = tuple  # (bool | None, str) o (bool | None, str, bool | None)


def _partes(respuesta) -> tuple[bool | None, str, bool | None]:
    tiene, detalle, *resto = respuesta
    return tiene, detalle, (resto[0] if resto else None)


def verificar(objetivo: str, consultar_pacf50: Callable[[], Respuesta]) -> Veredicto:
    """Pregunta a la 50 y decide.

    Lo que decide:
      - la 50 dice que el grupo NO EXISTE -> se descarta como grupo inexistente;
      - la 50 dice si hay o no curso -> manda eso;
      - la 50 no contesto -> no se descarta nada: se procesa por ISEF07.

    Args:
        consultar_pacf50: devuelve (tiene_curso, detalle[, grupo_existe]). No
            debe lanzar: un fallo se comunica como (None, motivo).
    """
    tiene, detalle, existe = _partes(consultar_pacf50())
    log.info("PACF50 sobre %s: %s, existe=%s (%s)", objetivo, tiene, existe, detalle)

    if existe is False:
        return Veredicto(
            objetivo=objetivo,
            tiene_curso=tiene,
            fuente=Fuente.PACF50,
            detalle=f"PACF50: {detalle}",
            consultadas=(Fuente.PACF50,),
            grupo_existe=False,
        )

    if tiene is not None:
        return Veredicto(
            objetivo=objetivo,
            tiene_curso=tiene,
            fuente=Fuente.PACF50,
            detalle=f"PACF50: {detalle}",
            consultadas=(Fuente.PACF50,),
            grupo_existe=existe,
        )

    # La 50 no pudo. No se descarta nada: se procesa por ISEF07 y se descubre
    # sobre la marcha, que es como se trabajaba antes de existir esto.
    return Veredicto(
        objetivo=objetivo,
        tiene_curso=None,
        fuente=Fuente.NINGUNA,
        detalle=f"PACF50: {detalle}",
        consultadas=(Fuente.PACF50,),
    )
