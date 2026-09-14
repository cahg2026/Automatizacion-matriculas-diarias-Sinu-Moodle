"""Carga de configuracion desde config/.env.

Ninguna credencial vive en el codigo. `config/.env` esta en .gitignore;
`config/.env.example` es la plantilla versionada.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

#: Raiz del proyecto (…/moodle-sinu-automation)
RAIZ = Path(__file__).resolve().parents[2]

DIR_CONFIG = RAIZ / "config"
DIR_DATOS = RAIZ / "data"
DIR_CRUDO = DIR_DATOS / "raw"
DIR_PROCESADO = DIR_DATOS / "processed"
DIR_LOGS = RAIZ / "logs"

RUTA_ENV = DIR_CONFIG / ".env"

#: Raiz de la CA que intercepta el HTTPS en esta maquina. Kaspersky Endpoint
#: Security analiza el trafico cifrado: reemite los certificados (se vio uno
#: para *.google.com firmado por su propia CA) y deja su raiz en el almacen de
#: Windows. Chrome y Python la aceptan porque leen ese almacen; Playwright NO,
#: porque su driver de Node trae su propio juego de CAs. El sintoma es
#: "self-signed certificate in certificate chain" en `page.request.get`, y el
#: 07/09/2026 dejo 13 matriculas sin procesar en 3 periodos: el navegador
#: entraba en SINU sin problema y solo fallaba la lectura del Sheet por CSV.
#: Se exporta desde PowerShell con:
#:   Get-ChildItem Cert:\LocalMachine\Root |
#:     Where-Object { $_.Subject -like "*Kaspersky*" }
RUTA_CA_CORPORATIVA = DIR_CONFIG / "ca_kaspersky.pem"


def confiar_en_ca_corporativa() -> Path | None:
    """Ensena a Playwright la CA corporativa, si esta a mano.

    Tiene que correr ANTES de `sync_playwright()`: el driver de Node lee
    NODE_EXTRA_CA_CERTS al arrancar. Por eso se invoca al importar este modulo,
    que es lo primero que carga cualquier script del proyecto.

    Se prefiere esto a `ignore_https_errors=True`: anadir una raiz concreta
    mantiene la validacion del certificado, mientras que desactivarla la quita
    entera y haria pasar por buena cualquier interceptacion, no solo la
    conocida.

    Devuelve la ruta usada, o None si no habia nada que hacer.
    """
    if os.environ.get("NODE_EXTRA_CA_CERTS"):
        return None  # alguien ya lo fijo a mano; no se pisa
    if not RUTA_CA_CORPORATIVA.is_file():
        return None  # otra maquina, o sin interceptacion: nada que anadir
    os.environ["NODE_EXTRA_CA_CERTS"] = str(RUTA_CA_CORPORATIVA)
    return RUTA_CA_CORPORATIVA


confiar_en_ca_corporativa()


def cargar_env(ruta: Path | None = None) -> None:
    """Carga config/.env si existe. No falla si aun no se ha creado."""
    destino = ruta or RUTA_ENV
    if destino.is_file():
        load_dotenv(destino, override=False)


def _bool(nombre: str, defecto: bool) -> bool:
    valor = os.getenv(nombre)
    if valor is None:
        return defecto
    return valor.strip().lower() in {"1", "true", "si", "sí", "yes", "y"}


def _ruta_opcional(nombre: str) -> Path | None:
    """Ruta desde el entorno, o None si la variable esta ausente o vacia."""
    valor = os.getenv(nombre, "").strip()
    return Path(valor) if valor else None


def _con_barra_final(url: str) -> str:
    """Asegura la barra final de una URL base."""
    limpia = (url or "").strip()
    return limpia if limpia.endswith("/") else limpia + "/"


def _texto_opcional(nombre: str) -> str | None:
    """Texto desde el entorno, o None si la variable esta ausente o vacia."""
    valor = os.getenv(nombre, "").strip()
    return valor or None


def _lista(nombre: str) -> tuple[str, ...]:
    """Lista separada por comas o punto y coma. Vacia si no hay nada.

    Se admiten los dos separadores porque los correos se copian de Outlook, que
    usa punto y coma.
    """
    crudo = os.getenv(nombre, "").replace(";", ",")
    return tuple(x.strip() for x in crudo.split(",") if x.strip())


@dataclass(frozen=True)
class Config:
    """Configuracion efectiva del proceso."""

    # --- Power BI (etapa 1, via Playwright) ---
    powerbi_usuario: str | None = None
    powerbi_password: str | None = None
    powerbi_url_informe: str | None = None
    powerbi_workspace: str = "CUN Digital"
    powerbi_informe: str = "ValidacionMoodle"
    powerbi_pagina: str = "MOODLE-VS-SINU-EST"

    powerbi_visual: str = "REPORTE"
    """Titulo del visual de tabla a exportar (aria-label del contenedor).

    NO es el nombre de la pagina: ese es POWERBI_PAGINA y corresponde al lienzo
    entero. Confundirlos hizo que la corrida del 21/08/2026 11:11 exportara un
    grafico en vez de la tabla. En el informe actual la tabla se llama
    'REPORTE ' (con espacio final, que se ignora al comparar).

    Solo desempata cuando la pagina tiene mas de un visual tabular; el
    localizador real es `aria-roledescription="Tabla"`. Dejarlo vacio toma el
    primer visual tabular que haya."""

    powerbi_termino_busqueda: str = "validacion"
    """Solo se usa si POWERBI_URL_INFORME esta vacio."""

    powerbi_headless: bool = True

    powerbi_idioma: str = "es-CO"
    """Idioma que se fuerza en el navegador (Accept-Language).

    Power BI traduce la interfaz segun este valor, y TODOS los selectores del
    proyecto son en espanol -- incluido el test-id 'pbimenu-item.Exportar
    datos', que se compone con la etiqueta traducida. Sin fijarlo, Chromium
    headless arranca en ingles y la corrida del 21/08/2026 11:22 fallo por eso
    mientras la misma corrida con ventana funcionaba."""
    navegador_canal: str = "chrome"
    """Canal de Chromium: 'chrome' abre el Chrome instalado; 'chromium' el
    empaquetado con Playwright.

    Tiene que ser el MISMO en toda la automatizacion y en la grabacion, porque
    comparten POWERBI_PERFIL_NAVEGADOR. Mezclar versiones sobre un perfil hace
    que Chrome intente 'degradarlo' y el navegador muera al arrancar
    (comprobado el 21/08/2026: el perfil quedo con Snapshots.CHROME_DELETE y
    'Target page, context or browser has been closed'). Si se cambia, hay que
    empezar con un perfil nuevo."""

    navegador_compat_rdp: bool = False
    """Argumentos de compatibilidad con escritorio remoto (--disable-gpu y
    companyia). Poner en true si alguna pagina sale en blanco por RDP. Incluye
    --no-sandbox, que desactiva el sandbox de Chrome: de ahi que no sea el
    valor por defecto."""

    powerbi_perfil_navegador: Path | None = None
    """Perfil persistente DEDICADO de Chromium. Si la cuenta exige MFA, permite
    resolverlo una vez en modo visible y reutilizar la sesion despues.

    Solo se usa cuando NAVEGADOR_PERFIL=proyecto."""

    navegador_perfil: str = "proyecto"
    """Que perfil abre la automatizacion: 'proyecto' (POWERBI_PERFIL_NAVEGADOR),
    'chrome' (el personal del usuario) o una ruta explicita.

    El dueno del proceso pidio el perfil personal (31/08/2026), para tener
    favoritos y sesiones. **Chrome no lo permite**: comprobado con Chrome 151,
    responde 'DevTools remote debugging requires a non-default data directory'
    y la conexion nunca llega. Desde Chrome 136 el navegador veta que se
    automatice su directorio de datos por defecto.

    El veto es al DIRECTORIO, no al contenido, asi que el valor por defecto es
    'proyecto' sobre una carpeta **sembrada** desde el perfil personal con
    `scripts/sembrar_perfil.py`: de ahi salen los 46 favoritos y los accesos
    directos. Ver `siembra_perfil` para que viaja y que no.

    'chrome' se conserva porque es lo correcto en versiones que si lo admitan;
    `scripts/probar_perfil.py` dice en diez segundos cual es el caso."""

    navegador_perfil_directorio: str = "Default"
    """Perfil concreto dentro de 'User Data' ('Default', 'Profile 1'...).
    Solo aplica con NAVEGADOR_PERFIL=chrome."""

    # --- SINU (etapa 3/4, via Playwright) ---
    sinu_url: str = "https://sigwt.cun.edu.co/sgacampus"
    sinu_usuario: str | None = None
    sinu_password: str | None = None

    # --- Google Drive (etapas 2 y 5, via navegador) ---
    # No hay credenciales de Google: la organizacion no concede acceso a Google
    # Cloud Console, asi que la etapa 2 usa RPA sobre la UI de Drive con el mismo
    # perfil persistente de la etapa 1. La sesion vive en ese perfil.
    google_carpeta_raiz: str = "REPORTES 2026"

    google_carpeta_raiz_id: str | None = None
    """Id de la carpeta raiz en Drive. Se prefiere al nombre: es inequivoco y
    no depende de que no haya dos carpetas homonimas."""


    # --- comportamiento ---
    modo_simulacion: bool = True
    """Si True, nunca se ejecuta 'Vincular grupos matriculados' en SINU."""

    deduplicar_exactos: bool = True
    timeout_operacion_seg: int = 30
    reintentos_login: int = 1

    timeout_render_seg: int = 120
    """Plazo para lo que Power BI renderiza en el servidor: el SSO y el visual
    del informe tardan bastante mas que el resto de la UI."""

    timeout_descarga_seg: int = 300
    """Plazo de la exportacion. Con ~1300 filas la generacion del .xlsx no es
    inmediata; el defecto de 30s de Playwright se queda corto."""

    # --- Avisos (flujo desatendido de las 9:00) ---
    notificar_webhook: str | None = None
    """URL de webhook entrante de Teams o Slack.

    Es el canal preferido: una sola URL, sin contrasenas que rotar, y el
    destino va dentro del propio webhook. Con esto configurado no hace falta
    nada de SMTP."""

    notificar_smtp_servidor: str | None = None
    notificar_smtp_puerto: int = 587
    """587 para STARTTLS, 465 para SSL directo. El modulo elige segun esto."""

    notificar_smtp_usuario: str | None = None
    notificar_smtp_password: str | None = None
    notificar_smtp_remitente: str | None = None
    """De donde sale el correo. Si esta vacio se usa el usuario."""

    notificar_destinatarios: tuple[str, ...] = ()
    """A quien se avisa. Sin esto NO se manda correo, aunque haya servidor:
    mandar un aviso a nadie es igual de inutil que no mandarlo, pero parece
    que si se hizo."""

    notificar_calendar: bool = True
    """Avisar creando UN evento puntual en Google Calendar, por el navegador.

    Activo por defecto porque es el unico canal que no pide credenciales
    nuevas: la sesion de Google ya vive en el perfil de Chrome. NO programa
    nada a futuro ni crea eventos recurrentes -- escribe solo en el instante
    en que ocurre el aviso. La tarea de las 9:00 es del Programador de
    Windows, no de Calendar."""

    notificar_invitados: tuple[str, ...] = ()
    """Correos que se anaden como invitados del evento. Google les manda su
    propia invitacion, que es como el aviso llega a otras personas sin montar
    un servidor de correo."""

    notificar_calendar_adelanto_min: int = 2
    """Minutos que se adelanta el evento para que el recordatorio por defecto
    tenga margen de dispararse. Un recordatorio cuyo momento ya paso no salta,
    asi que a 0 el aviso puede no llegar nunca a la pantalla."""

    # --- El cerrojo del tablero ---
    cerrojo_espera_min: int = 90
    """Ventana de gracia del cerrojo: cuantos minutos se reintenta la lectura
    antes de dar el tablero por desactualizado.

    NO es un adorno. El 09/09/2026 a las 08:05 el tablero aun decia 8/9/26, y
    el dia anterior a las 15:16 ya decia 8/9/26: el refresco cae en algun
    momento de la manana y puede ser DESPUES de las 9:00. Con una sola lectura,
    la tarea de las 9:00 encontraria datos viejos todos los dias y mandaria una
    alerta diaria sin procesar nunca nada -- la alerta se volveria ruido y la
    automatizacion, inutil.

    90 minutos cubre hasta las 10:30 con la tarea a las 9:00. Subirlo cuando se
    sepa la hora real del refresco; el log de cada corrida la deja anotada.
    0 = una sola lectura, el comportamiento estricto."""

    cerrojo_intervalo_min: int = 15
    """Cada cuantos minutos se reintenta dentro de la ventana. Cada reintento
    abre y cierra el navegador, asi que tampoco conviene bajarlo mucho."""

    @property
    def tiene_canal_de_aviso(self) -> bool:
        """Si hay por donde avisar. El flujo desatendido lo comprueba ANTES de
        arrancar: descubrir que no hay canal en el momento de tener que avisar
        es descubrirlo tarde."""
        return bool(
            self.notificar_calendar
            or self.notificar_webhook
            or (self.notificar_smtp_servidor and self.notificar_destinatarios)
        )

    @classmethod
    def desde_entorno(cls) -> Config:
        cargar_env()
        return cls(
            powerbi_usuario=os.getenv("POWERBI_USUARIO"),
            powerbi_password=os.getenv("POWERBI_PASSWORD"),
            powerbi_url_informe=os.getenv("POWERBI_URL_INFORME"),
            powerbi_workspace=os.getenv("POWERBI_WORKSPACE", "CUN Digital"),
            powerbi_informe=os.getenv("POWERBI_INFORME", "ValidacionMoodle"),
            powerbi_pagina=os.getenv("POWERBI_PAGINA", "MOODLE-VS-SINU-EST"),
            powerbi_visual=os.getenv("POWERBI_VISUAL", "REPORTE"),
            powerbi_termino_busqueda=os.getenv("POWERBI_TERMINO_BUSQUEDA", "validacion"),
            powerbi_headless=_bool("POWERBI_HEADLESS", True),
            powerbi_idioma=os.getenv("POWERBI_IDIOMA", "es-CO"),
            powerbi_perfil_navegador=_ruta_opcional("POWERBI_PERFIL_NAVEGADOR"),
            navegador_perfil=os.getenv("NAVEGADOR_PERFIL", "proyecto").strip() or "proyecto",
            navegador_perfil_directorio=(
                os.getenv("NAVEGADOR_PERFIL_DIRECTORIO", "Default").strip() or "Default"
            ),
            navegador_canal=os.getenv("NAVEGADOR_CANAL", "chrome"),
            navegador_compat_rdp=_bool("NAVEGADOR_COMPAT_RDP", False),
            # La barra final se fuerza aqui: sin ella Tomcat puede dar 404.
            sinu_url=_con_barra_final(
                os.getenv("SINU_URL", "https://sigwt.cun.edu.co/sgacampus")
            ),
            sinu_usuario=os.getenv("SINU_USUARIO"),
            sinu_password=os.getenv("SINU_PASSWORD"),
            google_carpeta_raiz=os.getenv("GOOGLE_CARPETA_RAIZ", "REPORTES 2026"),
            google_carpeta_raiz_id=_texto_opcional("GOOGLE_CARPETA_RAIZ_ID"),
            modo_simulacion=_bool("MODO_SIMULACION", True),
            deduplicar_exactos=_bool("DEDUPLICAR_EXACTOS", True),
            timeout_operacion_seg=int(os.getenv("TIMEOUT_OPERACION_SEG", "30")),
            reintentos_login=int(os.getenv("REINTENTOS_LOGIN", "1")),
            timeout_render_seg=int(os.getenv("TIMEOUT_RENDER_SEG", "120")),
            timeout_descarga_seg=int(os.getenv("TIMEOUT_DESCARGA_SEG", "300")),
            notificar_webhook=_texto_opcional("NOTIFICAR_WEBHOOK"),
            notificar_smtp_servidor=_texto_opcional("NOTIFICAR_SMTP_SERVIDOR"),
            notificar_smtp_puerto=int(os.getenv("NOTIFICAR_SMTP_PUERTO", "587")),
            notificar_smtp_usuario=_texto_opcional("NOTIFICAR_SMTP_USUARIO"),
            notificar_smtp_password=_texto_opcional("NOTIFICAR_SMTP_PASSWORD"),
            notificar_smtp_remitente=_texto_opcional("NOTIFICAR_SMTP_REMITENTE"),
            notificar_destinatarios=_lista("NOTIFICAR_DESTINATARIOS"),
            notificar_calendar=_bool("NOTIFICAR_CALENDAR", True),
            notificar_invitados=_lista("NOTIFICAR_INVITADOS"),
            notificar_calendar_adelanto_min=int(
                os.getenv("NOTIFICAR_CALENDAR_ADELANTO_MIN", "2")
            ),
            cerrojo_espera_min=int(os.getenv("CERROJO_ESPERA_MIN", "90")),
            cerrojo_intervalo_min=int(os.getenv("CERROJO_INTERVALO_MIN", "15")),
        )


def asegurar_directorios() -> None:
    for d in (DIR_CRUDO, DIR_PROCESADO, DIR_LOGS):
        d.mkdir(parents=True, exist_ok=True)
