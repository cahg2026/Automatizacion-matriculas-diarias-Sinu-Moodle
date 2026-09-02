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
        )


def asegurar_directorios() -> None:
    for d in (DIR_CRUDO, DIR_PROCESADO, DIR_LOGS):
        d.mkdir(parents=True, exist_ok=True)
