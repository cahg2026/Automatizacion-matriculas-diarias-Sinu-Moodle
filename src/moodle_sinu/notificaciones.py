"""Avisos del flujo diario: tablero sin actualizar, y cierre con resumen.

Existe porque el flujo pasa a correr desatendido a las 9:00. Sin aviso, un
tablero de ayer o una corrida a medias no se descubren hasta que alguien mira,
y hoy (07/09/2026) se vio lo que eso cuesta: una interceptacion de TLS corto
tres periodos y nadie lo habria sabido.

Tres canales, los tres por configuracion:

  NOTIFICAR_CALENDAR  Un evento PUNTUAL en Google Calendar, por el navegador.
                      Activo por defecto: es el unico que no pide credenciales
                      nuevas, porque la sesion de Google ya vive en el perfil
                      de Chrome. Solo escribe en el instante del aviso; no
                      programa nada a futuro. Ver `aviso_calendar`.
  NOTIFICAR_WEBHOOK   URL de Teams o Slack. Una URL, sin contrasenas, y el
                      webhook ya lleva el destino dentro.
  NOTIFICAR_SMTP_*    Correo. Necesita servidor, usuario y contrasena.

Y un respaldo que SIEMPRE funciona: `logs/avisos/` con un archivo por aviso.
No sustituye a la notificacion -- nadie mira una carpeta a las 9:05 -- pero
garantiza que el aviso quede escrito aunque el canal falle, y que el motivo
del fallo quede junto a el.

Lo que este modulo NO hace: adivinar destinatarios. Si no hay canal
configurado lo dice y devuelve `enviado=False`; el que llama decide si eso es
motivo de fallo. Callarse seria peor que no avisar, porque parecería que aviso.
"""

from __future__ import annotations

import json
import logging
import smtplib
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime
from email.message import EmailMessage
from pathlib import Path

from .config import DIR_LOGS

log = logging.getLogger(__name__)

#: Un archivo por aviso. Es el respaldo, no el canal.
DIR_AVISOS = DIR_LOGS / "avisos"

#: Plazo de red. Corto a proposito: un aviso que tarda un minuto en fallar
#: retrasa el arranque del dia, y el respaldo en disco ya cubre el fallo.
SEG_TIMEOUT_RED = 20


#: Titulos de los eventos de Calendar, tal como los pidio el dueno del
#: proceso. Van SIN la fecha: el evento ya esta fechado por si mismo, y
#: repetirla en el titulo solo gasta el ancho de la notificacion del movil.
TITULO_CALENDAR_ALERTA = "⚠️ ALERTA: Tablero Power BI sin actualizar"
TITULO_CALENDAR_EXITO = "✅ ÉXITO: Flujo Moodle vs SINU completado"


@dataclass
class Aviso:
    """Un aviso ya redactado, listo para cualquier canal."""

    asunto: str
    cuerpo: str

    critico: bool = False
    """True si es una alerta que exige intervencion. Solo cambia la
    presentacion (color en Teams, prefijo), no el camino de envio."""

    titulo_calendar: str = ""
    """Titulo para el evento de Calendar. Si esta vacio se usa `asunto`.
    Existe porque en una notificacion de movil el titulo se corta, y ahi la
    fecha del asunto sobra."""

    @property
    def titulo_para_calendar(self) -> str:
        return self.titulo_calendar or self.asunto


@dataclass
class ResultadoEnvio:
    """Que paso con el aviso, canal por canal."""

    enviado: bool = False
    canales: list[str] = field(default_factory=list)
    fallos: list[str] = field(default_factory=list)
    respaldo: Path | None = None

    def resumen(self) -> str:
        partes = []
        if self.canales:
            partes.append("enviado por " + ", ".join(self.canales))
        if self.fallos:
            partes.append("fallos: " + "; ".join(self.fallos))
        if self.respaldo is not None:
            partes.append(f"copia en {self.respaldo.name}")
        return " | ".join(partes) or "sin canal configurado"


# ---------------------------------------------------------------------------
# Redaccion de los dos avisos del flujo
# ---------------------------------------------------------------------------


#: Texto exigido por el dueno del proceso, literal. Va como PRIMERA linea del
#: cuerpo para que se lea entero en la vista previa de Teams o del correo, que
#: es donde se decide si alguien abre el aviso o no.
TEXTO_CRITICO_DESACTUALIZADO = (
    "CRÍTICO: El tablero no se ha actualizado el día de hoy. La fecha de "
    "última actualización detectada en el reporte es anterior a la fecha actual."
)


def aviso_tablero_desactualizado(
    detalle: str, *, hoy: date | None = None, hora: str = "9:00 AM"
) -> Aviso:
    """Caso de falla: el tablero es de un dia ANTERIOR; el flujo no arranca."""
    dia = hoy or date.today()
    return Aviso(
        asunto=f"⚠️ ALERTA: Tablero Power BI sin actualizar - {dia:%d/%m/%Y}",
        titulo_calendar=TITULO_CALENDAR_ALERTA,
        cuerpo=(
            # Las dos primeras frases estan especificadas palabra por palabra
            # por el dueno del proceso, en dos encargos distintos. Se conservan
            # las dos literales: ninguna contradice a la otra, y reformular una
            # especificacion literal es perderla.
            f"{TEXTO_CRITICO_DESACTUALIZADO}\n"
            f"\n"
            f"El proceso de las {hora} detectó que el tablero de Power BI no ha "
            f"sido actualizado el día de hoy. El flujo se ha pausado para "
            f"gestión con el departamento encargado.\n"
            f"\n"
            f"Detalle: {detalle}\n"
            f"\n"
            f"No se exportó el reporte ni se tocó ninguna matrícula en SINU: "
            f"procesar con datos de otro día ensuciaría vinculaciones que ya "
            f"están correctas.\n"
            f"\n"
            f"Cuando el tablero esté actualizado, el flujo puede lanzarse a "
            f"mano con:\n"
            f"    .\\.venv\\Scripts\\python.exe scripts\\dia_completo.py "
            f"--ejecutar-de-verdad\n"
        ),
        critico=True,
    )


def aviso_no_se_pudo_leer(detalle: str, *, hoy: date | None = None) -> Aviso:
    """Variante del caso A: no se sabe si esta actualizado.

    Va aparte porque la accion del operador es distinta: no hay que reclamar
    datos al departamento, hay que mirar si el tablero cambio de forma.
    """
    dia = hoy or date.today()
    return Aviso(
        asunto=f"⚠️ ALERTA: no se pudo leer la fecha del tablero - {dia:%d/%m/%Y}",
        cuerpo=(
            f"El flujo se detuvo antes de exportar porque NO pudo determinar "
            f"cuándo se actualizó el tablero. Ojo: esto no es lo mismo que un "
            f"tablero viejo -- es que la comprobación en sí no funcionó.\n"
            f"\n"
            f"Detalle: {detalle}\n"
            f"\n"
            f"Lo más probable es que el tablero cambiara de forma. Para verlo:\n"
            f"    python scripts\\sondear_actualizacion.py --visible\n"
        ),
        critico=True,
    )


def aviso_exito(resumen: str, *, hoy: date | None = None) -> Aviso:
    """Caso B: el flujo termino. `resumen` son las metricas del dia."""
    dia = hoy or date.today()
    return Aviso(
        asunto=f"✅ ÉXITO: Flujo de procesamiento finalizado - {dia:%d/%m/%Y}",
        titulo_calendar=TITULO_CALENDAR_EXITO,
        cuerpo=(
            f"El flujo se completó correctamente.\n"
            f"\n"
            f"Resumen de resultados:\n"
            f"{resumen}\n"
        ),
    )


def aviso_fallo(resumen: str, *, hoy: date | None = None) -> Aviso:
    """El flujo arranco y no termino bien.

    No estaba en el encargo, y hace falta: sin el, un fallo a mitad en modo
    desatendido se ve exactamente igual que un dia sin novedades.
    """
    dia = hoy or date.today()
    return Aviso(
        asunto=f"❌ FALLO: Flujo de procesamiento incompleto - {dia:%d/%m/%Y}",
        cuerpo=(
            f"El flujo arrancó pero no terminó bien. Lo hecho hasta el fallo "
            f"queda marcado en el Sheet del día.\n"
            f"\n"
            f"Resumen:\n"
            f"{resumen}\n"
        ),
        critico=True,
    )


# ---------------------------------------------------------------------------
# Canales
# ---------------------------------------------------------------------------


def _cuerpo_teams(aviso: Aviso) -> dict:
    """Payload que entienden tanto Teams como Slack.

    Teams (webhook clasico) usa `title`/`text`/`themeColor`; Slack usa `text`.
    Mandar los tres campos sirve para los dos sin detectar cual es.
    """
    return {
        "title": aviso.asunto,
        "text": f"**{aviso.asunto}**\n\n{aviso.cuerpo}",
        "themeColor": "D93025" if aviso.critico else "1E8E3E",
    }


def _enviar_webhook(url: str, aviso: Aviso) -> None:
    datos = json.dumps(_cuerpo_teams(aviso)).encode("utf-8")
    peticion = urllib.request.Request(
        url,
        data=datos,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(peticion, timeout=SEG_TIMEOUT_RED) as r:
        if r.status >= 300:
            raise RuntimeError(f"el webhook respondio {r.status}")


def _enviar_smtp(cfg, aviso: Aviso) -> None:
    msg = EmailMessage()
    msg["Subject"] = aviso.asunto
    msg["From"] = cfg.notificar_smtp_remitente or cfg.notificar_smtp_usuario
    msg["To"] = ", ".join(cfg.notificar_destinatarios)
    msg.set_content(aviso.cuerpo)

    contexto = ssl.create_default_context()
    if cfg.notificar_smtp_puerto == 465:
        with smtplib.SMTP_SSL(
            cfg.notificar_smtp_servidor,
            cfg.notificar_smtp_puerto,
            timeout=SEG_TIMEOUT_RED,
            context=contexto,
        ) as s:
            if cfg.notificar_smtp_usuario:
                s.login(cfg.notificar_smtp_usuario, cfg.notificar_smtp_password or "")
            s.send_message(msg)
        return

    with smtplib.SMTP(
        cfg.notificar_smtp_servidor,
        cfg.notificar_smtp_puerto,
        timeout=SEG_TIMEOUT_RED,
    ) as s:
        s.starttls(context=contexto)
        if cfg.notificar_smtp_usuario:
            s.login(cfg.notificar_smtp_usuario, cfg.notificar_smtp_password or "")
        s.send_message(msg)


def _guardar_respaldo(aviso: Aviso, resultado: ResultadoEnvio) -> Path:
    DIR_AVISOS.mkdir(parents=True, exist_ok=True)
    sello = datetime.now().strftime("%Y%m%d_%H%M%S")
    clase = "alerta" if aviso.critico else "aviso"
    destino = DIR_AVISOS / f"{clase}_{sello}.txt"
    destino.write_text(
        f"{aviso.asunto}\n"
        f"{'=' * len(aviso.asunto)}\n"
        f"\n"
        f"{aviso.cuerpo}\n"
        f"\n"
        f"--- envio ---\n"
        f"{resultado.resumen()}\n",
        encoding="utf-8",
    )
    return destino


def enviar(aviso: Aviso, cfg) -> ResultadoEnvio:
    """Manda el aviso por los canales configurados y deja copia en disco.

    Nunca lanza: un aviso que revienta se llevaria por delante el flujo al que
    intenta avisar. Los problemas van en `ResultadoEnvio.fallos`, y el que
    llama decide.
    """
    r = ResultadoEnvio()

    if cfg.notificar_calendar:
        # Import local: arrastra Playwright, y este modulo lo cargan scripts
        # que no abren navegador.
        from .aviso_calendar import crear_evento

        rc = crear_evento(aviso.titulo_para_calendar, aviso.cuerpo, cfg)
        if rc.creado:
            r.canales.append("calendar")
            r.enviado = True
        else:
            r.fallos.append(f"calendar: {rc.detalle}")

    if cfg.notificar_webhook:
        try:
            _enviar_webhook(cfg.notificar_webhook, aviso)
            r.canales.append("webhook")
            r.enviado = True
        except (urllib.error.URLError, OSError, RuntimeError) as exc:
            r.fallos.append(f"webhook: {exc}")
            log.error("No se pudo avisar por webhook: %s", exc)

    if cfg.notificar_smtp_servidor and cfg.notificar_destinatarios:
        try:
            _enviar_smtp(cfg, aviso)
            r.canales.append("smtp")
            r.enviado = True
        except (smtplib.SMTPException, OSError) as exc:
            r.fallos.append(f"smtp: {exc}")
            log.error("No se pudo avisar por correo: %s", exc)

    if not cfg.tiene_canal_de_aviso:
        r.fallos.append(
            "no hay canal configurado (NOTIFICAR_CALENDAR, NOTIFICAR_WEBHOOK "
            "o NOTIFICAR_SMTP_SERVIDOR)"
        )

    try:
        r.respaldo = _guardar_respaldo(aviso, r)
    except OSError as exc:  # noqa: BLE001
        r.fallos.append(f"respaldo en disco: {exc}")

    nivel = logging.ERROR if aviso.critico else logging.INFO
    log.log(nivel, "%s -- %s", aviso.asunto, r.resumen())
    return r
