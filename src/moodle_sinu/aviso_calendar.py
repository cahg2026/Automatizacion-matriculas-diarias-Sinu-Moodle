"""Avisos como eventos PUNTUALES de Google Calendar, por el navegador.

Es el canal que no necesita credenciales nuevas: la sesion de Google ya vive en
el perfil de Chrome que usa la automatizacion (el mismo con el que entra a
Drive). Ni SMTP, ni contrasena de aplicacion, ni URL de webhook que pedir.

QUE HACE Y QUE NO HACE, porque es facil confundirlo:

  SI  -> crea UN evento suelto, en el instante en que ocurre el aviso, y solo
         en dos momentos: tablero sin actualizar, o flujo terminado.
  NO  -> no crea eventos recurrentes, no programa nada a futuro y no pone
         ningun "hacer el tablero" diario en la agenda.

  La tarea diaria de las 9:00 vive en el Programador de tareas de WINDOWS
  (ver scripts/programar_9am.py). Calendar no la conoce y no se toca para eso.

Como funciona: se abre la URL de creacion rapida, que llega al editor con todo
relleno, y se pulsa Guardar.

    https://calendar.google.com/calendar/render?action=TEMPLATE
        &text=<titulo>&details=<descripcion>&dates=<inicio>/<fin>
        &add=<invitados>&ctz=<zona>

Dos limites de esa URL que cambian lo que se puede prometer:

1. NO se puede fijar el recordatorio. Lo pone el calendario segun su
   configuracion por defecto, y un recordatorio cuyo momento ya paso NO se
   dispara. Por eso el evento se coloca unos minutos por delante
   (MINUTOS_POR_DELANTE): es el margen minimo para que el aviso llegue a la
   pantalla y al movil, no agenda futura. Si aun asi no salta, el arreglo esta
   en Calendar > Configuracion > Notificaciones de eventos, poniendo el aviso
   por defecto en "a la hora del evento". Eso es del usuario, no de aqui.

2. Lo que SI es fiable para avisar a OTRAS personas es el campo de invitados:
   al anadir correos, Google manda su propia invitacion. Ese es el camino de
   entrega de verdad, y no depende de nada nuestro.

Y una advertencia de fondo: este canal depende de un navegador y de una sesion
de Google viva, asi que es mas fragil que un webhook. Va bien como aviso a
personas; si el aviso tiene que llegar SIEMPRE, los dos canales conviven.
"""

from __future__ import annotations

import logging
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta

from .config import Config

log = logging.getLogger(__name__)

URL_PLANTILLA = "https://calendar.google.com/calendar/render"
#: La vista del dia. Se confirma AQUI y no en el buscador: el buscador no
#: indexa al instante lo que se acaba de guardar, y eso daba un falso negativo
#: sistematico (08/09/2026).
URL_VISTA_DIA = "https://calendar.google.com/calendar/u/0/r/day"

#: Margen para que el recordatorio por defecto tenga tiempo de dispararse. A la
#: hora exacta su disparador ya habria pasado y no saltaria nada. Son minutos,
#: no horas: el evento es de AHORA, no una cita futura.
MINUTOS_POR_DELANTE = 2

#: Duracion. Corta a proposito: es un aviso, no una reunion, y asi no ocupa
#: sitio visible en la agenda del dia.
MINUTOS_DURACION = 10

#: Zona horaria del proceso. Sin fijarla, Calendar usa la del calendario, que
#: podria no coincidir con la del equipo y desplazaria el aviso.
ZONA = "America/Bogota"

#: El boton de guardar, en los idiomas en que puede salir la interfaz.
TEXTOS_GUARDAR = ("Guardar", "Save")

#: El campo de minutos del recordatorio, dentro del editor.
#:
#: Aqui estaba el motivo de que el 09/09/2026 el evento se creara y NO avisara
#: a nadie: el editor viene con "10 minutos antes" por defecto, y el evento se
#: coloca 2 minutos por delante. El aviso quedaba 8 minutos en el PASADO, asi
#: que no se disparaba nunca. El evento existia y era invisible.
#:
#: La URL de creacion rapida no permite fijar el recordatorio, pero el editor
#: si: se pone a 0 ("a la hora del evento"), y entonces salta a los 2 minutos.
CSS_MINUTOS_AVISO = 'input[aria-label*="notificaci" i][type="number"]'
MINUTOS_AVISO = 0

#: Con invitados, Google pregunta antes de guardar:
#:   "Enviar invitaciones por correo electronico a los invitados que utilizan
#:    Google Calendar?  [Volver a editar] [No enviar] [Enviar]"
#: Sin responderlo el evento NO se guarda. Es lo que rompio el 10/09/2026 en
#: cuanto se anadio el primer invitado: el dia anterior, sin invitados, no
#: aparecia el dialogo y todo parecia funcionar.
#: Se responde "Enviar" a proposito: el correo a los invitados es el canal de
#: entrega mas fiable de este montaje, porque no depende de nada nuestro.
TEXTOS_ENVIAR_INVITACIONES = ("Enviar", "Send")

SEG_ASENTAR = 3.0


@dataclass
class ResultadoCalendar:
    creado: bool = False
    detalle: str = ""
    url: str = ""

    def resumen(self) -> str:
        estado = "evento creado" if self.creado else "NO se creo el evento"
        return f"{estado}{': ' + self.detalle if self.detalle else ''}"


def _marca(momento: datetime) -> str:
    """Formato que espera Calendar: 20260908T174500."""
    return momento.strftime("%Y%m%dT%H%M%S")


def construir_url(
    titulo: str,
    detalles: str,
    *,
    invitados: tuple[str, ...] = (),
    ahora: datetime | None = None,
    minutos_por_delante: int = MINUTOS_POR_DELANTE,
) -> str:
    """La URL de creacion rapida, con todo relleno.

    Sin `RRULE` ni nada parecido: el evento es unico. Que sea puntual no es un
    detalle de implementacion, es el requisito.
    """
    inicio = (ahora or datetime.now()) + timedelta(minutes=minutos_por_delante)
    fin = inicio + timedelta(minutes=MINUTOS_DURACION)

    parametros = {
        "action": "TEMPLATE",
        "text": titulo,
        "details": detalles,
        "dates": f"{_marca(inicio)}/{_marca(fin)}",
        "ctz": ZONA,
    }
    if invitados:
        # `add` es el campo de invitados. Google les manda su propia
        # invitacion, y eso hace que el aviso salga de esta maquina sin
        # configurar ningun servidor de correo.
        parametros["add"] = ",".join(invitados)

    consulta = urllib.parse.urlencode(parametros, quote_via=urllib.parse.quote)
    return f"{URL_PLANTILLA}?{consulta}"


def _fijar_recordatorio(page, minutos: int) -> bool:
    """Pone el recordatorio a `minutos` antes. True si lo consiguio.

    Sin esto el evento se crea con el defecto de Calendar (10 min antes) y,
    estando el evento 2 minutos por delante, el aviso cae en el pasado y no
    salta: exactamente lo que paso el 09/09/2026.

    No es critico si falla -- el evento se guarda igual y los invitados reciben
    su correo -- pero se avisa en el log, porque sin recordatorio el aviso en
    pantalla no llega.
    """
    try:
        campo = page.locator(CSS_MINUTOS_AVISO)
        if campo.count() == 0:
            log.warning(
                "No se encontro el campo de minutos del recordatorio; el evento "
                "se guardara con el defecto de Calendar y el aviso en pantalla "
                "puede no saltar."
            )
            return False
        antes = campo.first.input_value()
        campo.first.fill(str(minutos))
        log.info("Recordatorio del evento: %s -> %s minutos antes.", antes, minutos)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("No se pudo fijar el recordatorio (%s); se sigue igual.", exc)
        return False


def _confirmar_invitaciones(page, plazo_ms: int) -> None:
    """Responde "Enviar" al dialogo de invitaciones, si aparece.

    Con invitados, Google pregunta si mandar los correos ANTES de guardar. Sin
    responder, el evento no se guarda: el 10/09/2026 el flujo entero termino
    bien y el aviso no llego a nadie porque el dialogo se quedo abierto.

    Si no hay invitados el dialogo no sale, y esto no hace nada.
    """
    try:
        dialogo = page.get_by_role("dialog")
        if dialogo.count() == 0:
            return
        for texto in TEXTOS_ENVIAR_INVITACIONES:
            boton = dialogo.first.get_by_role("button", name=texto, exact=True)
            if boton.count() == 0:
                continue
            boton.first.click(timeout=plazo_ms)
            log.info("Dialogo de invitaciones: pulsado %r.", texto)
            page.wait_for_timeout(int(SEG_ASENTAR * 1000))
            return
        log.warning(
            "Aparecio un dialogo tras guardar y no se encontro el boton de "
            "enviar: %r",
            (dialogo.first.inner_text() or "")[:160],
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("No se pudo responder al dialogo de invitaciones: %s", exc)


def _pulsar_guardar(page, plazo_ms: int) -> bool:
    """Pulsa Guardar en el editor. True si lo encontro y lo pulso."""
    for texto in TEXTOS_GUARDAR:
        boton = page.get_by_role("button", name=texto, exact=False)
        try:
            if boton.count() > 0:
                boton.first.wait_for(state="visible", timeout=plazo_ms)
                boton.first.click()
                log.info("Pulsado %r en el editor de Calendar.", texto)
                return True
        except Exception as exc:  # noqa: BLE001 - se prueba el otro idioma
            log.debug("No se pudo pulsar %r: %s", texto, exc)
    return False


def _confirmar(page, titulo: str, plazo_ms: int) -> bool:
    """Comprueba que el evento existe DE VERDAD, en la VISTA DEL DIA.

    No basta con que el editor se cierre. Es la leccion de la subida a Drive
    del 01/09/2026: creerle al dialogo llevo a dar por subido un archivo que no
    estaba.

    Pero ojo con COMO se confirma. La primera version preguntaba al BUSCADOR de
    Calendar, y daba un falso negativo sistematico: el 08/09/2026 el evento se
    creo correctamente y la busqueda decia que no existia, porque Google no
    indexa al instante lo que se acaba de guardar. Tal cual, el flujo habria
    informado "aviso NO enviado" todos los dias funcionando bien -- el error
    espejo del de Drive, una verificacion que miente al otro lado.

    La vista del dia lee el calendario directamente y no depende del indice.
    """
    # Se busca por un trozo distintivo y no por el titulo entero: los emoji
    # pueden renderizarse de otra forma en la rejilla del dia.
    aguja = titulo.split(":", 1)[-1].strip()[:40] or titulo
    try:
        page.goto(URL_VISTA_DIA, timeout=plazo_ms)
        page.wait_for_timeout(int(SEG_ASENTAR * 1000))
        texto = page.locator("body").inner_text()
        encontrado = aguja in texto
        log.info(
            "Confirmacion en la vista del dia de %r: %s",
            aguja,
            "aparece" if encontrado else "NO aparece",
        )
        return encontrado
    except Exception as exc:  # noqa: BLE001
        log.warning("No se pudo confirmar el evento en Calendar: %s", exc)
        return False


def crear_evento(
    titulo: str,
    detalles: str,
    cfg: Config,
    *,
    contexto=None,
) -> ResultadoCalendar:
    """Crea UN evento puntual de aviso. Nunca lanza.

    Si `contexto` viene dado se reutiliza, para no abrir un segundo navegador
    cuando el que llama ya tiene uno.
    """
    url = construir_url(
        titulo,
        detalles,
        invitados=cfg.notificar_invitados,
        minutos_por_delante=cfg.notificar_calendar_adelanto_min,
    )
    plazo = max(cfg.timeout_operacion_seg, 30) * 1000

    def _trabajo(ctx) -> ResultadoCalendar:
        page = ctx.new_page()
        try:
            page.goto(url, timeout=plazo)
            page.wait_for_timeout(int(SEG_ASENTAR * 1000))

            if "accounts.google.com" in page.url:
                return ResultadoCalendar(
                    detalle=(
                        "Calendar pidio iniciar sesion. Resolverlo una vez con "
                        "python scripts/probar_perfil.py --iniciar-sesion"
                    ),
                    url=url,
                )

            # El recordatorio, ANTES de guardar: es lo que hace que el aviso
            # llegue a la pantalla y al movil.
            _fijar_recordatorio(page, MINUTOS_AVISO)

            if not _pulsar_guardar(page, plazo):
                return ResultadoCalendar(
                    detalle=(
                        "no se encontro el boton de guardar; el evento quedo SIN "
                        "crear (la interfaz de Calendar pudo cambiar)"
                    ),
                    url=url,
                )

            page.wait_for_timeout(int(SEG_ASENTAR * 1000))
            # Con invitados, Google pregunta si manda los correos y NO guarda
            # hasta que se responde.
            _confirmar_invitaciones(page, plazo)
            page.wait_for_timeout(int(SEG_ASENTAR * 1000))
            if _confirmar(page, titulo, plazo):
                extra = (
                    f", {len(cfg.notificar_invitados)} invitado(s)"
                    if cfg.notificar_invitados
                    else ""
                )
                return ResultadoCalendar(
                    creado=True, detalle=f"confirmado en Calendar{extra}", url=url
                )
            return ResultadoCalendar(
                detalle="se pulso guardar pero el evento no aparece al buscarlo",
                url=url,
            )
        finally:
            try:
                page.close()
            except Exception:  # noqa: BLE001
                pass

    try:
        if contexto is not None:
            return _trabajo(contexto)

        # Import local: este modulo lo cargan scripts que no abren navegador.
        from playwright.sync_api import sync_playwright

        from .navegador import abrir_contexto

        with sync_playwright() as pw:
            # Con ventana: el aviso tiene que verse, y en esta suite headless ya
            # engano una vez con la subida a Drive.
            ctx, cerrar = abrir_contexto(pw, cfg, headless=False)
            try:
                return _trabajo(ctx)
            finally:
                cerrar()
    except Exception as exc:  # noqa: BLE001
        # Un aviso que revienta se llevaria por delante justo el flujo al que
        # intenta avisar.
        log.exception("Fallo creando el evento de Calendar")
        return ResultadoCalendar(detalle=f"error: {exc}", url=url)
