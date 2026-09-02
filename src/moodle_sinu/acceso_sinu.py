"""Apertura y acceso a SINU. Compartido por la grabacion y por la etapa 3.

Estrategia de carga
-------------------
SINU es una aplicacion SmartClient/GWT servida por Tomcat, y eso impone tres
cosas que se aprendieron a base de verlas:

1. **La URL necesita la barra final.** `/sgacampus` puede responder 404;
   `/sgacampus/` responde 200. Se normaliza siempre.
2. **La primera peticion de un perfil frio puede dar 404.** Comprobado el
   21/08/2026: el primer intento devolvio la pagina de error de Tomcat y el
   siguiente, ya con cookie de sesion, cargo las 500+ etiquetas. Por eso se
   reintenta con `reload()` en vez de darlo por perdido.
3. **No hay que esperar iframes.** SINU renderiza en el documento principal:
   sus unicos iframes son `__gwt_historyFrame` y `basf00`, de infraestructura y
   presentes desde el primer instante, asi que esperar "a que haya un iframe"
   se cumple de inmediato y no garantiza nada. Se espera a selectores reales de
   la aplicacion.

Los ids no sirven
-----------------
SmartClient genera los ids (`isc_3T`, `isc_2X`...) en cada carga. Los
selectores usan los `name` de los inputs y las clases CSS, que si son estables.
"""

from __future__ import annotations

import logging
import time

from playwright.sync_api import (
    Error as ErrorPlaywright,
    Page,
    TimeoutError as ErrorTiempoPlaywright,
)

from . import selectores_sinu as sel
from .config import Config

log = logging.getLogger(__name__)

#: Nodos por debajo de los cuales se considera que la pagina no pinto nada.
#: Un documento vacio ronda los 4-10. El umbral se mantiene bajo a proposito:
#: SmartClient construye la interfaz por pasos, y cuando aparece el primer
#: selector util solo hay unas 55 etiquetas (medido el 21/08/2026) aunque acabe
#: pasando de 500. Un umbral alto disparaba una recarga espuria en cada carga.
UMBRAL_NODOS_VACIA = 25

#: Espera antes de reintentar, para que Tomcat fije la cookie de sesion.
SEG_ANTES_DE_REINTENTAR = 2


class ErrorAccesoSinu(RuntimeError):
    """No se pudo abrir SINU o iniciar sesion."""


def url_con_barra(url: str) -> str:
    """Normaliza la URL de SINU para que acabe en '/'.

    `/sgacampus` sin barra puede devolver 404 en Tomcat. Es un detalle tonto que
    cuesta una sesion entera de depuracion, asi que se fuerza aqui y no se
    confia en como este escrito en config/.env.
    """
    limpia = (url or "").strip()
    if not limpia:
        return sel.URL_BASE
    return limpia if limpia.endswith("/") else limpia + "/"


def _medir(page: Page) -> int:
    """Numero de etiquetas del documento. 0 si no se puede medir."""
    try:
        return int(page.evaluate("() => document.querySelectorAll('*').length"))
    except ErrorPlaywright:
        return 0


def _esperar_senal_de_carga(page: Page, timeout_seg: float) -> str | None:
    """Espera a que aparezca algun selector real de la aplicacion.

    Devuelve el selector que caso, o None si ninguno aparecio.
    """
    limite = time.monotonic() + timeout_seg
    while time.monotonic() < limite:
        for css in sel.CSS_SENALES_DE_CARGA:
            try:
                if page.locator(css).count() and page.locator(css).first.is_visible():
                    return css
            except ErrorPlaywright:
                pass
        page.wait_for_timeout(500)
    return None


def abrir_sinu(page: Page, cfg: Config) -> None:
    """Abre SINU con la estrategia de carga completa.

    Raises:
        ErrorAccesoSinu: si tras el reintento la pagina sigue sin cargar.
    """
    url = url_con_barra(cfg.sinu_url)
    plazo = cfg.timeout_render_seg

    for intento in (1, 2):
        try:
            respuesta = page.goto(url, wait_until="domcontentloaded", timeout=plazo * 1000)
        except ErrorPlaywright as exc:
            if intento == 2:
                raise ErrorAccesoSinu(f"No se pudo abrir {url}: {exc}") from exc
            log.warning("Fallo la navegacion a %s (%s); se reintenta.", url, exc)
            page.wait_for_timeout(SEG_ANTES_DE_REINTENTAR * 1000)
            continue

        estado = respuesta.status if respuesta is not None else 0
        # Se espera la senal ANTES de medir: al terminar `domcontentloaded` la
        # interfaz aun no existe, y medir en ese instante daria "vacia" siempre.
        senal = _esperar_senal_de_carga(page, min(plazo, 30))
        nodos = _medir(page)

        vacia = nodos < UMBRAL_NODOS_VACIA
        if senal is not None and estado < 400 and not vacia:
            log.info(
                "SINU cargado (HTTP %s, %d etiquetas, senal '%s').", estado, nodos, senal
            )
            return

        if intento == 1:
            # Arranque en frio de Tomcat: la primera peticion puede devolver 404
            # y la segunda funcionar, una vez fijada la cookie de sesion.
            log.warning(
                "Primer intento sin exito (HTTP %s, %d etiquetas, senal=%s). "
                "Recargando en %ds para que Tomcat fije la sesion.",
                estado,
                nodos,
                senal,
                SEG_ANTES_DE_REINTENTAR,
            )
            page.wait_for_timeout(SEG_ANTES_DE_REINTENTAR * 1000)
            try:
                page.reload(wait_until="domcontentloaded", timeout=plazo * 1000)
            except ErrorPlaywright as exc:
                log.warning("El reload fallo (%s); se reintenta la navegacion.", exc)
            continue

        detalle = (
            f"HTTP {estado}, {nodos} etiquetas"
            + ("" if senal else ", ningun selector de la aplicacion aparecio")
        )
        raise ErrorAccesoSinu(
            f"SINU no cargo tras dos intentos en {url} ({detalle}).\n"
            "  Que descartar, en este orden:\n"
            "   1. Que la URL responda desde el navegador normal (VPN, red).\n"
            "   2. Que SINU_URL acabe en '/': sin barra Tomcat puede dar 404.\n"
            "   3. Si la ventana se ve en blanco pero el HTTP es 200, activar "
            "NAVEGADOR_COMPAT_RDP=true en config/.env."
        )


def sesion_activa(page: Page) -> bool:
    """True si ya hay sesion iniciada.

    Se mira el boton "Salir": SINU lo pinta con la clase
    `toolbarButtonDisabled` mientras no hay sesion, y lo habilita al entrar. Es
    mas fiable que buscar un menu, que depende del perfil del usuario.
    """
    try:
        salir = page.get_by_text(sel.TEXTO_SALIR, exact=True)
        if not salir.count():
            # Sin barra de herramientas: o no cargo, o estamos en el login.
            return False
        clases = salir.first.get_attribute("class") or ""
        return sel.CLASE_DESHABILITADO not in clases
    except ErrorPlaywright as exc:
        log.debug("No se pudo leer el estado de sesion: %s", exc)
        return False


def iniciar_sesion(page: Page, cfg: Config) -> bool:
    """Inicia sesion en SINU con las credenciales de config/.env.

    Devuelve True si hizo login, False si ya habia sesion. Marca "No cerrar
    sesion" para que la sesion quede en el perfil persistente y las corridas
    siguientes no tengan que repetirla.

    Raises:
        ErrorAccesoSinu: si faltan credenciales o el acceso no se completa.
    """
    if sesion_activa(page):
        log.info("Ya habia sesion de SINU en el perfil; no se vuelve a entrar.")
        return False

    faltan = [
        nombre
        for nombre, valor in (("SINU_USUARIO", cfg.sinu_usuario), ("SINU_PASSWORD", cfg.sinu_password))
        if not valor
    ]
    if faltan:
        raise ErrorAccesoSinu(
            f"Falta {' y '.join(faltan)} en config/.env. La pantalla de acceso de "
            "SINU esta abierta pero no hay credenciales guardadas con las que "
            "entrar."
        )

    usuario = page.locator(sel.CSS_USUARIO)
    clave = page.locator(sel.CSS_PASSWORD)
    if not usuario.count() or not clave.count():
        raise ErrorAccesoSinu(
            "No se encontro el formulario de acceso "
            f"({sel.CSS_USUARIO} / {sel.CSS_PASSWORD}). Si la pagina cargo, "
            "puede que ya haya sesion o que el login haya cambiado."
        )

    log.info("Entrando en SINU como %s", cfg.sinu_usuario)
    usuario.first.fill(cfg.sinu_usuario)
    clave.first.fill(cfg.sinu_password)
    _marcar_no_cerrar_sesion(page)

    # El boton es un <td class="button">Entrar</td>, no un <button>.
    boton = page.locator(sel.CSS_BOTON).filter(has_text=sel.TEXTO_BOTON_ENTRAR)
    if boton.count():
        boton.first.click()
    else:
        log.warning("No se encontro el boton '%s'; se envia con Enter.", sel.TEXTO_BOTON_ENTRAR)
        clave.first.press("Enter")

    limite = time.monotonic() + cfg.timeout_render_seg
    while time.monotonic() < limite:
        if sesion_activa(page):
            log.info("Sesion de SINU iniciada.")
            return True
        page.wait_for_timeout(1000)

    raise ErrorAccesoSinu(
        "Se enviaron las credenciales pero la sesion no quedo activa "
        f"tras {cfg.timeout_render_seg}s. Revisar SINU_USUARIO y SINU_PASSWORD, "
        "y si la pantalla muestra algun mensaje de error."
    )


def _marcar_no_cerrar_sesion(page: Page) -> None:
    """Marca "No cerrar sesion" si esta disponible. No es critico."""
    try:
        casilla = page.get_by_text(sel.RX_NO_CERRAR_SESION)
        if casilla.count():
            casilla.first.click()
            log.info("Marcado '%s': la sesion quedara en el perfil.", sel.TEXTO_NO_CERRAR_SESION)
    except (ErrorPlaywright, ErrorTiempoPlaywright) as exc:
        log.debug("No se pudo marcar 'No cerrar sesion': %s", exc)


def abrir_y_acceder(page: Page, cfg: Config) -> bool:
    """Abre SINU y deja la sesion lista. Devuelve True si tuvo que entrar."""
    abrir_sinu(page, cfg)
    return iniciar_sesion(page, cfg)
