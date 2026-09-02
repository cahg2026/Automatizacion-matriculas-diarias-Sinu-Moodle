"""Configuracion de logging: consola + archivo por corrida en /logs."""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

from .config import DIR_LOGS

_FORMATO = "%(asctime)s %(levelname)-8s %(name)-28s %(message)s"


def configurar(nivel: int = logging.INFO, etiqueta: str = "fase1") -> Path:
    """Configura el logging raiz y devuelve la ruta del archivo de log."""
    DIR_LOGS.mkdir(parents=True, exist_ok=True)
    sello = datetime.now().strftime("%Y%m%d_%H%M%S")
    archivo = DIR_LOGS / f"{etiqueta}_{sello}.log"

    raiz = logging.getLogger()
    raiz.setLevel(nivel)
    for h in list(raiz.handlers):
        raiz.removeHandler(h)

    consola = logging.StreamHandler(sys.stderr)
    consola.setFormatter(logging.Formatter(_FORMATO))
    raiz.addHandler(consola)

    fichero = logging.FileHandler(archivo, encoding="utf-8")
    fichero.setFormatter(logging.Formatter(_FORMATO))
    raiz.addHandler(fichero)

    return archivo
