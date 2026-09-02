"""Arranque del navegador, compartido por todas las etapas de RPA.

Vive aparte porque las lecciones de la etapa 1 valen igual para Drive y para
SINU, y repetirlas en cada modulo seria pedir que se olvide alguna:

- **El idioma se fija siempre.** Chromium headless pide la UI en ingles aunque
  la corrida con ventana la traiga en espanol. Todos los selectores del proyecto
  son en espanol, y algunos test-ids incorporan la etiqueta traducida, asi que
  sin fijar `locale` la misma configuracion funciona con ventana y falla
  desatendida (corrida del 21/08/2026 11:22).
- **Viewport amplio.** Los visuales y las listas largas se renderizan por
  demanda; a 1280x720 hay elementos que no llegan a existir.
- **Perfil persistente.** Es lo que hace viable la ejecucion diaria: el segundo
  factor se resuelve una vez y la sesion sobrevive entre corridas. La etapa 2
  reutiliza el MISMO perfil que la etapa 1, de modo que la sesion de Google que
  abre Drive es la que ya esta autenticada.
"""

from __future__ import annotations

import logging
from typing import Callable

from playwright.sync_api import BrowserContext, Error as ErrorPlaywright

from . import perfil_navegador
from .config import Config

log = logging.getLogger(__name__)

#: Viewport para las corridas SIN ventana. Suficiente para que las listas de
#: Drive y los visuales de Power BI rendericen sin depender del scroll.
#:
#: Solo se usa en headless, y a proposito. Medido el 21/08/2026 en la sesion
#: remota (pantalla real 1280x720 con escalado al 150%, dpr=1.5):
#:
#:   headless + viewport 1920            -> 1920x1080  (correcto)
#:   headless + no_viewport              -> 1898x926, pantalla falsa 800x600
#:   headless + no_viewport + maximized  ->  778x435  (rompe el renderizado)
#:   visible  + viewport 1920            -> 1920x1080 comprimido en 1280x720
#:   visible  + no_viewport + maximized  -> 1280x529  (proporcionado)
#:
#: De ahi el reparto: con ventana manda el tamano real de la ventana; sin
#: ventana no hay gestor de ventanas que maximizar, y maximizar contra la
#: pantalla ficticia de 800x600 deja un viewport diminuto.
VIEWPORT = {"width": 1920, "height": 1080}

#: Con ventana: que ocupe el monitor desde que abre.
ARG_MAXIMIZAR = "--start-maximized"

#: Argumentos para sesiones remotas (RDP). En escritorio remoto no hay GPU
#: utilizable y algunas paginas -- SINU entre ellas -- se quedan en blanco
#: porque el compositor no llega a pintar nada.
#:
#: Notas de cada uno:
#: - `--disable-gpu`: el que de verdad arregla el renderizado en RDP.
#: - `--disable-dev-shm-usage`: pensado para Linux/Docker, donde /dev/shm es
#:   diminuto. En Windows no hace nada; se deja por simetria con otros entornos.
#: - `--no-sandbox`: DESACTIVA EL SANDBOX de Chrome, que es una defensa real.
#:   En Windows no hace falta para arreglar el renderizado. Se incluye porque lo
#:   pidio el dueno del proceso, pero conviene quitarlo si no resulta necesario:
#:   este navegador se autentica en SINU y en Google.
ARGS_COMPAT_RDP: tuple[str, ...] = (
    "--disable-gpu",
    "--disable-dev-shm-usage",
    "--no-sandbox",
)

#: Argumentos de este subconjunto que no comprometen la seguridad. Es lo que
#: conviene usar si se puede prescindir de `--no-sandbox`.
ARGS_COMPAT_RDP_SIN_SANDBOX: tuple[str, ...] = (
    "--disable-gpu",
    "--disable-dev-shm-usage",
)

#: Playwright anade `--enable-automation` por defecto, que marca
#: `navigator.webdriver` y muestra el aviso de "controlado por software
#: automatizado". Ignorarlo hace que la pagina se vea como en un navegador
#: normal, que es lo que espera un ERP como SINU.
ARGS_A_IGNORAR: tuple[str, ...] = ("--enable-automation",)


def abrir_contexto(
    pw,
    cfg: Config,
    headless: bool,
) -> tuple[BrowserContext, Callable[[], None]]:
    """Crea el contexto del navegador. Devuelve (contexto, funcion_de_cierre)."""
    argumentos: list[str] = []

    # La compatibilidad con RDP se activa por configuracion y no por defecto: la
    # etapa 1 esta verificada sin estos argumentos, y `--no-sandbox` no es algo
    # que deba colarse de tapadillo en todas las corridas.
    if cfg.navegador_compat_rdp:
        argumentos.extend(ARGS_COMPAT_RDP)
        log.warning(
            "Compatibilidad RDP activa: %s. Incluye --no-sandbox, que desactiva "
            "el sandbox de Chrome.",
            " ".join(ARGS_COMPAT_RDP),
        )

    # Se separan porque `channel`, `args` e `ignore_default_args` son de LANZAR
    # el navegador, mientras que el viewport y el locale son del CONTEXTO.
    # Mezclarlos rompe la rama sin perfil, donde `new_context` no acepta canal.
    del_navegador: dict = {
        # El canal tiene que coincidir con el que use la grabacion: el perfil es
        # el mismo, y mezclar versiones de Chrome sobre un perfil lo degrada y
        # mata el navegador al arrancar.
        "channel": cfg.navegador_canal,
        "ignore_default_args": list(ARGS_A_IGNORAR),
    }
    del_contexto: dict = {
        "accept_downloads": True,
        "locale": cfg.powerbi_idioma,
    }

    # `viewport` y `no_viewport` son mutuamente excluyentes: pasar los dos es un
    # error de Playwright, no una preferencia.
    if headless:
        del_contexto["viewport"] = VIEWPORT
        log.info("Sin ventana: viewport fijo %dx%d", VIEWPORT["width"], VIEWPORT["height"])
    else:
        # Con ventana manda el tamano real: forzar 1920x1080 en una pantalla
        # menor comprime la pagina y la interfaz se ve diminuta.
        del_contexto["no_viewport"] = True
        argumentos.append(ARG_MAXIMIZAR)
        log.info("Con ventana: sin viewport fijo y maximizada (%s).", ARG_MAXIMIZAR)

    log.info(
        "Navegador: canal '%s', idioma %s", cfg.navegador_canal, cfg.powerbi_idioma
    )

    # El perfil SIEMPRE es persistente: sin el no hay credenciales guardadas, ni
    # cookies de sesion, ni barra de favoritos, y cada corrida vuelve a
    # empezar de cero. `resolver` decide cual y `exigir_disponible` aborta con
    # instrucciones si no se puede abrir ahora (tipicamente, Chrome abierto).
    perfil = perfil_navegador.resolver(cfg)
    perfil_navegador.exigir_disponible(perfil)
    argumentos.extend(perfil.argumentos)
    del_navegador["args"] = argumentos

    log.info("Usando perfil persistente %s", perfil.descripcion)
    context = pw.chromium.launch_persistent_context(
        str(perfil.ruta), headless=headless, **del_navegador, **del_contexto
    )

    def cerrar() -> None:
        """Cierra el contexto tolerando que ya lo hayan cerrado.

        Con ventana, el operador cierra el navegador cuando termina -- es la
        forma natural de acabar una grabacion. Entonces `context.close()` lanza
        `TargetClosedError`, y al venir de un `finally` sepultaba el resultado
        real de la corrida bajo un traceback que no aportaba nada.
        """
        try:
            context.close()
        except ErrorPlaywright as exc:
            log.debug("El contexto ya estaba cerrado: %s", exc)

    return context, cerrar
