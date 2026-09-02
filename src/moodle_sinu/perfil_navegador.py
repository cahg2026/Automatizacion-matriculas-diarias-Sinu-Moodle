"""Que perfil de Chrome usa la automatizacion, y si se puede abrir ahora mismo.

El problema que resuelve
------------------------
Hasta el 31/08/2026 el proyecto abria un perfil DEDICADO
(`POWERBI_PERFIL_NAVEGADOR`). Ese perfil vivia en el disco `F:`, que
desaparecio al mover el proyecto, asi que la automatizacion empezo a levantar
una instancia limpia: sin sesiones, sin contrasenas guardadas y **sin barra de
favoritos**, que es de donde el operador saca los accesos directos a SINU y al
Sheet del dia. De ahi la decision del dueno del proceso (31/08/2026): usar el
**perfil personal de Chrome**.

El precio, que no es negociable
-------------------------------
Chrome **bloquea la carpeta de su perfil mientras corre**. No es una politica
del proyecto: es un candado del propio navegador. Abrir esa carpeta desde
Playwright con Chrome abierto falla, y en el peor caso deja el perfil
inconsistente. Por eso aqui se comprueba ANTES de lanzar nada y se aborta con
instrucciones, en vez de dejar que el driver muera con un error opaco.

Ademas, las versiones recientes de Chrome restringen automatizar el perfil por
defecto. Si esta maquina resulta ser una de esas, `scripts/probar_perfil.py` lo
dice en diez segundos y queda el modo `proyecto` como salida.

Los tres modos
--------------
- `chrome`   : el perfil personal (`%LOCALAPPDATA%\\Google\\Chrome\\User Data`).
               Trae credenciales, cookies y favoritos. Exige Chrome cerrado.
- `proyecto` : el perfil dedicado de `POWERBI_PERFIL_NAVEGADOR`. No exige nada,
               pero hay que autenticarse la primera vez.
- una ruta   : cualquier otra carpeta de perfil.
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import Config

log = logging.getLogger(__name__)

MODO_CHROME = "chrome"
MODO_PROYECTO = "proyecto"

#: Subcarpeta del perfil dentro de 'User Data'. Chrome guarda cada perfil en la
#: suya: 'Default' es el primero, y los demas son 'Profile 1', 'Profile 2'...
#: Se pasa como argumento porque `launch_persistent_context` recibe la carpeta
#: 'User Data' entera, no el perfil concreto.
DIRECTORIO_PERFIL_POR_DEFECTO = "Default"


class ErrorPerfilNavegador(RuntimeError):
    """No se puede usar el perfil pedido. El mensaje explica que hacer."""


@dataclass(frozen=True)
class PerfilResuelto:
    """El perfil que se va a abrir, ya decidido."""

    ruta: Path
    """Carpeta que recibe `launch_persistent_context`. Con el perfil personal
    es la carpeta 'User Data', no la del perfil concreto."""

    es_chrome_real: bool
    """True si es el perfil personal del usuario. Implica Chrome cerrado y que
    lo que se haga aqui afecta a su navegador de diario."""

    directorio: str | None = None
    """Perfil dentro de 'User Data' ('Default', 'Profile 1'...). None cuando la
    carpeta ya es el perfil, que es el caso del modo `proyecto`."""

    @property
    def argumentos(self) -> tuple[str, ...]:
        """Argumentos de Chrome que hacen falta para este perfil."""
        if self.directorio:
            return (f"--profile-directory={self.directorio}",)
        return ()

    @property
    def descripcion(self) -> str:
        if self.es_chrome_real:
            return f"{self.ruta} [{self.directorio}] (perfil PERSONAL de Chrome)"
        return f"{self.ruta} (perfil dedicado de la automatizacion)"


def perfil_chrome_real() -> Path:
    """Carpeta 'User Data' de Chrome en Windows."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Google" / "Chrome" / "User Data"


def chrome_esta_corriendo() -> bool:
    """True si hay algun proceso chrome.exe.

    Se consulta con `tasklist` y no con psutil para no anadir dependencia. Si
    la consulta falla se devuelve False: es preferible intentarlo y que el
    driver de el error real, a bloquear una corrida por un fallo de tasklist.
    """
    try:
        salida = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq chrome.exe", "/NH"],
            capture_output=True,
            text=True,
            timeout=20,
        ).stdout.lower()
    except (OSError, subprocess.SubprocessError) as exc:
        log.debug("No se pudo consultar tasklist (%s); se asume que no corre.", exc)
        return False
    return "chrome.exe" in salida


def resolver(cfg: Config) -> PerfilResuelto:
    """Decide el perfil a partir de la configuracion. No lo abre ni lo valida."""
    modo = (cfg.navegador_perfil or MODO_PROYECTO).strip()

    if modo.lower() == MODO_CHROME:
        return PerfilResuelto(
            ruta=perfil_chrome_real(),
            es_chrome_real=True,
            directorio=cfg.navegador_perfil_directorio or DIRECTORIO_PERFIL_POR_DEFECTO,
        )

    if modo.lower() == MODO_PROYECTO:
        if not cfg.powerbi_perfil_navegador:
            raise ErrorPerfilNavegador(
                "NAVEGADOR_PERFIL=proyecto pero POWERBI_PERFIL_NAVEGADOR esta "
                "vacio en config/.env. Poner una ruta, o NAVEGADOR_PERFIL=chrome "
                "para usar el perfil personal."
            )
        return PerfilResuelto(ruta=Path(cfg.powerbi_perfil_navegador), es_chrome_real=False)

    # Una ruta explicita. Se trata como perfil dedicado: la carpeta ES el perfil.
    return PerfilResuelto(ruta=Path(modo), es_chrome_real=False)


def exigir_disponible(perfil: PerfilResuelto) -> None:
    """Comprueba que el perfil se puede abrir AHORA. Aborta explicando si no.

    Raises:
        ErrorPerfilNavegador: si el perfil personal no existe o Chrome lo tiene
            bloqueado. Nunca por el perfil dedicado, que se crea si falta.
    """
    if not perfil.es_chrome_real:
        perfil.ruta.mkdir(parents=True, exist_ok=True)
        return

    if not perfil.ruta.is_dir():
        raise ErrorPerfilNavegador(
            f"No existe el perfil de Chrome en {perfil.ruta}. Comprobar que "
            "Chrome esta instalado para este usuario, o usar "
            "NAVEGADOR_PERFIL=proyecto."
        )

    carpeta = perfil.ruta / (perfil.directorio or DIRECTORIO_PERFIL_POR_DEFECTO)
    if not carpeta.is_dir():
        disponibles = sorted(
            p.name for p in perfil.ruta.iterdir() if p.is_dir() and (p / "Preferences").is_file()
        )
        raise ErrorPerfilNavegador(
            f"El perfil '{perfil.directorio}' no existe en {perfil.ruta}. "
            f"Perfiles disponibles: {disponibles or '(ninguno)'}. "
            "Ajustar NAVEGADOR_PERFIL_DIRECTORIO en config/.env."
        )

    if chrome_esta_corriendo():
        raise ErrorPerfilNavegador(
            "Chrome esta abierto y bloquea la carpeta de su perfil, asi que la "
            "automatizacion no puede usarla.\n"
            "  Cerrar Chrome POR COMPLETO -- incluidas las ventanas en segundo "
            "plano y el icono de la bandeja del sistema -- y repetir.\n"
            "  Comprobacion: en PowerShell, `Get-Process chrome` no debe "
            "devolver nada.\n"
            "  Alternativa sin cerrar nada: NAVEGADOR_PERFIL=proyecto en "
            "config/.env, que usa un perfil dedicado (hay que autenticarse la "
            "primera vez, y la sesion queda guardada para las siguientes)."
        )

    log.warning(
        "Se va a abrir el perfil PERSONAL de Chrome (%s). Lo que haga la "
        "automatizacion afecta al navegador de diario del usuario.",
        carpeta,
    )
