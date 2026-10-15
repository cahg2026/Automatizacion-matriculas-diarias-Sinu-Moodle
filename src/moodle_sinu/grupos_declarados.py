"""Grupos que el dueno del proceso declaro, a mano, que NO EXISTEN en SINU.

Archivo: `config/grupos_no_existen.txt`. Una linea por grupo, en el formato en
que los pasa el dueno del proceso:

    MATERIA/GRUPO/PERIODO[/BLOQUE/UNIDAD/PENSUM]

por ejemplo `POS01/55ES1/26ES5/B1/EMPVI/EMVIR`. Solo cuentan los tres primeros
campos; el resto se conserva como referencia. Las lineas vacias y las que
empiezan por `#` se ignoran.

Por que existe (28/09/2026)
---------------------------
El dueno del proceso reviso a mano POS01/55ES1, 55ES2, 55ES5 y 55ES6 en 26ES5 y
pidio marcarlos en FUCSIA como GRUPO NO EXISTE EN SINU. La verificacion
automatica en PACF50 solo lo concluye si ve "No hay informacion para mostrar";
esto es para lo que ya se reviso a mano: esos grupos se marcan sin consultarlos
ni procesarlos.

Es una decision de una persona, y se registra como tal: la evidencia que queda
en el diario dice "declarado a mano", no "PACF50 dijo". Para deshacerla basta
quitar la linea y relanzar el periodo.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .config import DIR_CONFIG

log = logging.getLogger(__name__)

RUTA_GRUPOS_NO_EXISTEN = DIR_CONFIG / "grupos_no_existen.txt"


def leer(ruta: Path | None = None) -> dict[tuple[str, str], str]:
    """{(PERIODO, 'MATERIA/GRUPO'): linea original}. Vacio si no hay archivo."""
    ruta = ruta or RUTA_GRUPOS_NO_EXISTEN
    if not ruta.is_file():
        return {}
    declarados: dict[tuple[str, str], str] = {}
    for n, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), 1):
        limpia = linea.strip()
        if not limpia or limpia.startswith("#"):
            continue
        partes = [p.strip() for p in limpia.split("/")]
        if len(partes) < 3 or not all(partes[:3]):
            log.warning(
                "%s, linea %d: '%s' no es MATERIA/GRUPO/PERIODO; se ignora.",
                ruta.name, n, limpia,
            )
            continue
        materia, grupo, periodo = (p.upper() for p in partes[:3])
        declarados[(periodo, f"{materia}/{grupo}")] = limpia
    return declarados


def del_periodo(periodo: str, ruta: Path | None = None) -> dict[str, str]:
    """{'MATERIA/GRUPO': linea} declarados para `periodo`."""
    p = periodo.strip().upper()
    return {sn: linea for (per, sn), linea in leer(ruta).items() if per == p}
