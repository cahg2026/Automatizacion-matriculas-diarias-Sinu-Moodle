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
import time
from dataclasses import dataclass
from pathlib import Path

from .config import Config

log = logging.getLogger(__name__)

MODO_CHROME = "chrome"
MODO_PROYECTO = "proyecto"

#: Ejecutable de cada canal de Chromium, en Windows. Importa porque desde el
#: 24/09/2026 el canal de produccion es `msedge` y no `chrome`, y todo lo que en
#: este modulo buscaba "chrome.exe" dejo de encontrar nada ese dia.
#:
#: El chromium empaquetado con Playwright tambien se llama chrome.exe en
#: Windows: no es un descuido de esta tabla.
PROCESOS_POR_CANAL: dict[str, str] = {
    "chrome": "chrome.exe",
    "chrome-beta": "chrome.exe",
    "chromium": "chrome.exe",
    "msedge": "msedge.exe",
    "msedge-beta": "msedge.exe",
}

#: Canales que abren el Chrome personal del usuario. `NAVEGADOR_PERFIL=chrome`
#: solo tiene sentido con uno de estos: la carpeta 'User Data' de Chrome es de
#: Chrome, y abrirla con Edge es justo el "mezclar sobre un perfil" que el
#: propio .env avisa que lo degrada y mata el navegador al arrancar.
CANALES_DE_CHROME: frozenset[str] = frozenset({"chrome", "chrome-beta", "chromium"})

#: Canal que se asume cuando no se sabe cual es. Es el historico del proyecto.
CANAL_POR_DEFECTO = "chrome"


def proceso_de(canal: str | None) -> str:
    """El .exe del canal. Si el canal no se conoce, el de Chrome."""
    return PROCESOS_POR_CANAL.get((canal or "").strip().lower(), "chrome.exe")

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

    canal: str = CANAL_POR_DEFECTO
    """Canal con el que se va a abrir ESTE perfil ('chrome', 'msedge'...).

    Viaja con el perfil porque las dos cosas son inseparables: un perfil
    persistente pertenece al navegador que lo creo. Sin este dato,
    `exigir_disponible` no puede saber que proceso bloquea la carpeta -- y
    entre el 24/09/2026 (cambio a Edge) y hoy estuvo buscando 'chrome.exe'
    para un perfil que abre 'msedge.exe'."""

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


def navegador_esta_corriendo(canal: str | None = CANAL_POR_DEFECTO) -> bool:
    """True si hay algun proceso del navegador de ese canal.

    Se consulta con `tasklist` y no con psutil para no anadir dependencia. Si
    la consulta falla se devuelve False: es preferible intentarlo y que el
    driver de el error real, a bloquear una corrida por un fallo de tasklist.
    """
    exe = proceso_de(canal)
    try:
        salida = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {exe}", "/NH"],
            capture_output=True,
            text=True,
            timeout=20,
        ).stdout.lower()
    except (OSError, subprocess.SubprocessError) as exc:
        log.debug("No se pudo consultar tasklist (%s); se asume que no corre.", exc)
        return False
    return exe.lower() in salida


def chrome_esta_corriendo() -> bool:
    """True si hay algun chrome.exe. Nombre historico, lo usan cuatro scripts."""
    return navegador_esta_corriendo(CANAL_POR_DEFECTO)


def cerrar_chrome_del_perfil(
    ruta_perfil: Path | str, canal: str | None = None
) -> int:
    """Mata los procesos del navegador que tengan ABIERTO ese perfil. Cuantos.

    Solo esos. Filtrar por la ruta del perfil en la linea de comandos es lo que
    hace la operacion segura: el navegador personal del operador no lleva
    `--user-data-dir=<perfil de la automatizacion>` y por tanto nunca entra en
    la lista. Un `taskkill /IM chrome.exe` cerraria las dos cosas.

    Hace falta entre reintentos de la etapa 2. Cuando el proceso principal
    revienta, Windows deja huerfanos los procesos hijos un rato; el perfil
    sigue bloqueado y el intento siguiente hereda el desastre. Se vio el
    23/09/2026: el reintento a mano de las 09:09 fallo ya al abrir el informe,
    no por la descarga, porque reuso el Chrome envenenado de las 09:01.

    **Esta funcion estuvo inerte desde el 24/09/2026.** Ese dia el canal paso a
    `msedge` (por los volcados de chrome.dll), y el filtro de aqui seguia siendo
    `Name='chrome.exe'`. Los huerfanos que hay que matar pasaron a llamarse
    `msedge.exe`, asi que la consulta devolvia siempre 0 y la limpieza entre
    reintentos dejo de existir sin que nada lo dijera: el sintoma de no hacer
    nada y el de no encontrar nada son el mismo. De ahi que ahora el canal entre
    por parametro y, si no se pasa, se busquen TODOS los nombres conocidos --
    que sigue siendo seguro, porque lo que acota es la ruta del perfil, no el
    nombre.

    Si PowerShell no esta o falla, se devuelve 0 y se sigue: es una limpieza
    oportunista, y perder un reintento es mejor que abortar el dia por no
    haber podido consultar la lista de procesos.
    """
    perfil = str(Path(ruta_perfil))
    if canal is None:
        nombres = sorted(set(PROCESOS_POR_CANAL.values()))
    else:
        nombres = [proceso_de(canal)]
    filtro = " or ".join(f"Name='{n}'" for n in nombres)
    guion = (
        "$p = $env:PERFIL_AUTOMATIZACION; "
        f'$v = @(Get-CimInstance Win32_Process -Filter "{filtro}" | '
        "Where-Object { $_.CommandLine -like \"*$p*\" }); "
        "foreach ($x in $v) { Stop-Process -Id $x.ProcessId -Force "
        "-ErrorAction SilentlyContinue }; "
        "$v.Count"
    )
    entorno = dict(os.environ, PERFIL_AUTOMATIZACION=perfil)
    try:
        salida = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", guion],
            capture_output=True,
            text=True,
            timeout=60,
            env=entorno,
        ).stdout.strip()
        cerrados = int(salida.splitlines()[-1]) if salida else 0
    except (OSError, subprocess.SubprocessError, ValueError, IndexError) as exc:
        log.debug("No se pudo cerrar el Chrome del perfil (%s); se sigue.", exc)
        return 0
    if cerrados:
        log.info(
            "Cerrados %d proceso(s) de %s del perfil %s.",
            cerrados,
            "/".join(nombres),
            perfil,
        )
    return cerrados


def resolver(cfg: Config) -> PerfilResuelto:
    """Decide el perfil a partir de la configuracion. No lo abre ni lo valida."""
    modo = (cfg.navegador_perfil or MODO_PROYECTO).strip()
    canal = (getattr(cfg, "navegador_canal", "") or CANAL_POR_DEFECTO).strip().lower()

    if modo.lower() == MODO_CHROME:
        # El perfil personal es el de CHROME. Abrirlo con Edge es exactamente lo
        # que el .env advierte que degrada un perfil y mata el navegador al
        # arrancar, y ademas seria sobre el navegador de diario del operador.
        # Se para aqui en vez de dejar que reviente a medio camino.
        if canal not in CANALES_DE_CHROME:
            raise ErrorPerfilNavegador(
                f"NAVEGADOR_PERFIL=chrome pide el perfil PERSONAL de Chrome, pero "
                f"NAVEGADOR_CANAL='{canal}' abriria otro navegador sobre esa misma "
                f"carpeta. Un perfil persistente pertenece al navegador que lo "
                f"creo: mezclarlos lo degrada y el navegador muere al arrancar.\n"
                f"  Opciones: NAVEGADOR_CANAL=chrome (y Chrome cerrado durante la "
                f"corrida), o NAVEGADOR_PERFIL=proyecto con un perfil dedicado de "
                f"'{canal}' en POWERBI_PERFIL_NAVEGADOR."
            )
        return PerfilResuelto(
            ruta=perfil_chrome_real(),
            es_chrome_real=True,
            directorio=cfg.navegador_perfil_directorio or DIRECTORIO_PERFIL_POR_DEFECTO,
            canal=canal,
        )

    if modo.lower() == MODO_PROYECTO:
        if not cfg.powerbi_perfil_navegador:
            raise ErrorPerfilNavegador(
                "NAVEGADOR_PERFIL=proyecto pero POWERBI_PERFIL_NAVEGADOR esta "
                "vacio en config/.env. Poner una ruta, o NAVEGADOR_PERFIL=chrome "
                "para usar el perfil personal."
            )
        return PerfilResuelto(
            ruta=Path(cfg.powerbi_perfil_navegador),
            es_chrome_real=False,
            canal=canal,
        )

    # Una ruta explicita. Se trata como perfil dedicado: la carpeta ES el perfil.
    return PerfilResuelto(ruta=Path(modo), es_chrome_real=False, canal=canal)


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

    if navegador_esta_corriendo(perfil.canal):
        exe = proceso_de(perfil.canal)
        raise ErrorPerfilNavegador(
            f"Chrome esta abierto ({exe}) y bloquea la carpeta de su perfil, asi "
            "que la automatizacion no puede usarla.\n"
            "  Cerrar Chrome POR COMPLETO -- incluidas las ventanas en segundo "
            "plano y el icono de la bandeja del sistema -- y repetir.\n"
            f"  Comprobacion: en PowerShell, `Get-Process {exe[:-4]}` no debe "
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


# ---------------------------------------------------------------------------
# La sesion de Google: viva o no, medido de verdad
# ---------------------------------------------------------------------------

#: Servicio contra el que se prueba. Drive es el que el flujo necesita de
#: verdad (la subida del Sheet), asi que es el que hay que comprobar.
URL_PRUEBA_SESION = "https://drive.google.com/drive/my-drive"

#: Estados en los que Google pide identificarse. Se distinguen porque el
#: remedio de cada uno es distinto, y confundirlos manda a depurar donde no
#: esta el problema.
SENALES_SESION = {
    "accountchooser": (
        "Google pide ELEGIR CUENTA. La sesion existe pero hay varias cuentas. "
        "Fijar el indice con /u/0/ no lo salta (comprobado el 01/09/2026)."
    ),
    "confirmidentifier": (
        "Google pide REVERIFICAR la identidad ('Demuestra que eres tu'). Es el "
        "segundo factor, y solo lo puede resolver una persona. Fue lo que "
        "tumbo la corrida del 08/09/2026 en el paso 3."
    ),
    "signin": "Google pide INICIAR SESION: el perfil no tiene sesion valida.",
    "servicelogin": "Google pide INICIAR SESION: el perfil no tiene sesion valida.",
}


@dataclass(frozen=True)
class SesionGoogle:
    """Si la sesion de Google sirve, medido navegando de verdad."""

    viva: bool
    detalle: str = ""
    url_final: str = ""

    def __str__(self) -> str:  # pragma: no cover - conveniencia
        return ("sesion de Google VIVA" if self.viva else f"sesion CAIDA: {self.detalle}")


def pide_iniciar_sesion(url: str) -> str | None:
    """Si `url` es una pantalla de identificacion, el motivo. None si no.

    Funcion pura para poder probarla: la decision de "hay sesion o no" se toma
    aqui, y navegar es solo como se consigue la URL.
    """
    bajo = (url or "").lower()
    if "accounts.google.com" not in bajo:
        return None
    for senal, motivo in SENALES_SESION.items():
        if senal in bajo:
            return motivo
    return "Google redirigio a accounts.google.com (pantalla de identificacion)."


def comprobar_sesion_google(
    context,
    cfg: Config,
    url: str | None = None,
    *,
    gracia_seg: float = 180,
    pausa_seg: float = 20,
) -> SesionGoogle:
    """Comprueba la sesion NAVEGANDO, no mirando cookies.

    Existe porque contar cookies engana, y el 08/09/2026 costo una corrida: el
    perfil tenia 88 cookies y "todas las de sesion de Google presentes",
    mientras Google habia invalidado la sesion del lado del SERVIDOR. El paso 0
    dio el visto bueno, se exporto Power BI, y el fallo salio en el paso 3, ya
    con el cerrojo de escritura abierto.

    La presencia de una cookie dice que el navegador la guarda. No dice que el
    servidor la siga aceptando. Lo unico que lo dice es pedirle una pagina.

    Una redireccion al login es definitiva y se devuelve al momento. Que Drive
    no conteste NO lo es: se reintenta durante `gracia_seg` (los mismos 180 s
    que `SEG_GRACIA_RED` en subidor_drive). El 16/10/2026 un
    unico timeout de 30 s a las 9:00 tumbo el dia entero con la sesion sana
    (la URL final seguia en my-drive y minutos despues Drive daba 200).
    """
    inicio = time.monotonic()
    intento = 1
    while True:
        ses = _comprobar_una_vez(context, cfg, url)
        if ses.viva or not ses.detalle.startswith("no se pudo comprobar"):
            return ses
        if time.monotonic() - inicio + pausa_seg >= gracia_seg:
            return ses
        log.warning(
            "Intento %d sin respuesta de Google; reintento en %.0f s (gracia %.0f s).",
            intento, pausa_seg, gracia_seg,
        )
        time.sleep(pausa_seg)
        intento += 1


def _comprobar_una_vez(context, cfg: Config, url: str | None = None) -> SesionGoogle:
    destino = url or URL_PRUEBA_SESION
    plazo = max(getattr(cfg, "timeout_operacion_seg", 30), 30) * 1000
    page = context.new_page()
    try:
        page.goto(destino, timeout=plazo, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        motivo = pide_iniciar_sesion(page.url)
        if motivo:
            log.error("Sesion de Google CAIDA: %s", motivo)
            return SesionGoogle(viva=False, detalle=motivo, url_final=page.url)
        log.info("Sesion de Google viva (%s respondio sin pedir login).", destino)
        return SesionGoogle(viva=True, url_final=page.url)
    except Exception as exc:  # noqa: BLE001
        # No saber NO es lo mismo que estar caida: se dice asi.
        log.warning("No se pudo comprobar la sesion de Google: %s", exc)
        return SesionGoogle(
            viva=False,
            detalle=f"no se pudo comprobar ({exc}); no es lo mismo que estar caida",
            url_final=destino,
        )
    finally:
        try:
            page.close()
        except Exception:  # noqa: BLE001
            pass
