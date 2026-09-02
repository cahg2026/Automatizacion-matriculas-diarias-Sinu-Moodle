"""Activacion del grabador de Playwright sobre un contexto ya abierto.

Vive aparte porque hacen falta dos formas de grabar y tienen que compartir el
mecanismo:

- `scripts/grabar.py`: abre un navegador solo para grabar.
- `scripts/flujo_dia.py --grabar`: graba al final del flujo del dia, con el
  Google Sheet ya abierto en su pestana y con ISEF07 cargado y su Periodo
  fijado. Es la unica forma de grabar la pantalla *tal como la encuentra la
  automatizacion*, en vez de partiendo de un navegador en blanco.

Se llama por el canal interno del cliente porque la API Python publica no lo
expone: `enableRecorder` solo existe en el driver JS. Si una actualizacion de
Playwright lo renombra, esto deja de funcionar y hay que caer al Inspector
(`page.pause()`), que es la via publica. De ahi que devuelva un booleano en vez
de lanzar: quien llama decide el plan B.
"""

from __future__ import annotations

import logging
from pathlib import Path

from playwright.sync_api import BrowserContext

log = logging.getLogger(__name__)


def activar(context: BrowserContext, salida: Path) -> bool:
    """Enciende el grabador y le dice donde escribir. True si quedo activo."""
    try:
        context._impl_obj._channel.send_no_reply(
            "enableRecorder",
            {
                "language": "python",
                "mode": "recording",
                "outputFile": str(salida),
            },
        )
    except Exception as exc:  # noqa: BLE001 - el mensaje del driver es lo util
        log.warning(
            "El grabador interno no esta disponible (%s); habra que usar el "
            "Inspector y copiar el codigo de ahi.",
            exc,
        )
        return False
    log.info("Grabador activo; se escribira en %s", salida)
    return True
