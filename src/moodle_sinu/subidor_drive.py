"""Etapa 2: subida del reporte a Google Drive por navegador (RPA).

Sustituye a la version con la API de Drive, descartada porque la organizacion
(cun.edu.co) no concede acceso a Google Cloud Console y por tanto no hay
`client_secret.json` posible.

Reutiliza el MISMO perfil persistente de Chromium que la etapa 1: la sesion de
Google que abre Drive es la que ya quedo autenticada alli, de modo que no hay
credenciales de Google en ninguna parte del proyecto.

Flujo
-----
1. Abrir la carpeta raiz por su id (`GOOGLE_CARPETA_RAIZ_ID`).
2. Entrar en la subcarpeta del mes en MAYUSCULAS, creandola si falta.
3. Leer los nombres ya presentes para deducir el consecutivo.
4. Subir el .xlsx ya coloreado por la Fase 1, con un nombre local saneado.
5. Comprobar que quedo como Google Sheet; convertirlo si no.
6. Renombrarlo a `REPORTE DD/MM/YYYY #N`.

Advertencia sobre los selectores
--------------------------------
Los de `selectores_drive.py` estan SIN VERIFICAR: la UI de Drive no expone
`data-testid` y no hay grabacion de la que sacarlos. Cada paso deja traza y, si
un selector no casa, se aborta con el nombre del paso en vez de seguir a ciegas.
"""

from __future__ import annotations

import logging
import shutil
import time
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from tempfile import mkdtemp

from playwright.sync_api import (
    BrowserContext,
    Error as ErrorPlaywright,
    Locator,
    Page,
    TimeoutError as ErrorTiempoPlaywright,
    sync_playwright,
)

from . import selectores_drive as sel
from .config import DIR_LOGS, Config
from .exportador_powerbi import contar_filas_datos
from .convencion_drive import (
    ReporteEnDrive,
    nombre_local_para_subir,
    nombre_mes,
    nombre_mes_anterior,
    nombre_reporte,
    reportes_desde_nombres,
    siguiente_consecutivo,
)
from .navegador import abrir_contexto

log = logging.getLogger(__name__)

#: Margen tras pintarse la lista, antes de interactuar con ella. Drive muestra
#: las filas mucho antes de responder a un clic derecho, asi que sin esto el
#: menu contextual no se abre y parece que el selector cambio.
SEG_ASENTAR_LISTA = 6.0


class ErrorSubidaDrive(RuntimeError):
    """La subida a Drive no se pudo completar."""


@dataclass
class ResultadoSubida:
    """Salida de la etapa 2."""

    nombre: str
    carpeta_mes: str
    consecutivo: int
    enlace: str | None = None
    convertido_a_sheet: bool = False
    """True si hubo que convertir el .xlsx a Sheet desde el editor."""

    pagina_sheet: Page | None = None
    """Pestana del Sheet, viva solo si el contexto lo aporta quien llama: si la
    funcion abre el suyo, lo cierra al terminar y la pestana muere con el."""

    url_sheet: str | None = None
    """URL del Sheet, obtenida abriendolo. Sin API de Drive no hay id de
    archivo: la unica via es abrirlo y leer la barra de direcciones."""

    segundos: float = 0.0
    advertencias: list[str] = field(default_factory=list)
    traza: Path | None = None
    capturas: list[Path] = field(default_factory=list)


def _ms(segundos: float) -> float:
    return segundos * 1000


def _visible(locator: Locator, timeout_seg: float) -> bool:
    """True si el locator llega a ser visible. Absorbe los fallos de la SPA."""
    try:
        locator.first.wait_for(state="visible", timeout=_ms(timeout_seg))
        return True
    except ErrorTiempoPlaywright:
        return False
    except ErrorPlaywright as exc:
        log.debug("Espera interrumpida por la navegacion de Drive: %s", exc)
        return False


def _exigir(locator: Locator, timeout_seg: float, descripcion: str) -> Locator:
    """Devuelve el locator o aborta nombrando el paso que fallo.

    Abortar con el nombre del paso es lo que hace depurable una etapa cuyos
    selectores no estan verificados.
    """
    if _visible(locator, timeout_seg):
        return locator.first
    raise ErrorSubidaDrive(
        f"No se encontro {descripcion}. La UI de Drive no expone test-ids "
        "estables, asi que este selector puede haber cambiado: volver a grabar "
        "con scripts/grabar_drive.ps1 y contrastar con selectores_drive.py."
    )


# ---------------------------------------------------------------------------
# Navegacion
# ---------------------------------------------------------------------------


def _abrir_carpeta(page: Page, id_carpeta: str, cfg: Config, descripcion: str) -> None:
    """Navega a una carpeta de Drive y espera a que la rejilla exista."""
    url = sel.URL_CARPETA.format(id=id_carpeta)
    log.info("Abriendo %s (%s)", descripcion, url)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=_ms(cfg.timeout_render_seg))
    except ErrorPlaywright as exc:
        raise ErrorSubidaDrive(f"No se pudo abrir {descripcion}: {exc}") from exc

    _verificar_sesion(page, id_carpeta)

    _esperar_lista(page, cfg, descripcion)


def es_pagina_de_error(titulo: str) -> bool:
    """True si el titulo de la pagina es una pagina de error de Drive.

    Se separa como funcion pura para poder probarla: es la deteccion que
    distingue "no hay sesion" de "el selector cambio", y quedarse sin ella
    convierte un fallo de sesion en un falso positivo de selector.
    """
    limpio = (titulo or "").strip().lower()
    return "404" in limpio or limpio.startswith("error")


def id_de_url(url: str) -> str | None:
    """Id de la carpeta que la URL de Drive esta mostrando, o None."""
    import re

    casa = re.search(r"/folders/([a-zA-Z0-9_-]+)", url or "")
    return casa.group(1) if casa else None


def _exigir_dentro_de(page: Page, id_esperado: str, paso: str) -> None:
    """Aborta si la UI no esta DENTRO de la carpeta esperada.

    Es la guarda que faltaba, y su ausencia costo tres incidentes reales el
    01/09/2026 sobre el Drive del usuario:

      - Se creo una carpeta 'SEPTIEMBRE' en 'Mi unidad' en vez de dentro de
        'REPORTES 2026'.
      - Se subio 'REPORTE 01-09-2026 #176' fuera de la carpeta del mes.
      - El flujo dio la subida por buena porque comprobaba "existe el archivo",
        no "el archivo esta EN ESTA carpeta".

    Toda accion que MODIFIQUE Drive -- crear carpeta, subir -- pasa por aqui
    antes. Que un fallo deje el Drive intacto no es un lujo: limpiar a mano lo
    que la automatizacion desparrama cuesta mas que la propia corrida.
    """
    actual = id_de_url(page.url)
    if actual == id_esperado:
        return
    raise ErrorSubidaDrive(
        f"Se iba a {paso} sin estar dentro de la carpeta destino. Se esperaba la "
        f"carpeta {id_esperado} y la UI muestra "
        f"{actual or 'una vista sin id de carpeta (posiblemente Mi unidad)'}. "
        "Se aborta ANTES de tocar nada para no dejar archivos ni carpetas "
        "sueltas en el Drive."
    )


def _abrir_menu_contextual(
    page: Page, fila: Locator, cfg: Config, que: str, item_esperado
) -> None:
    """Clic derecho sobre una fila, asegurando que el menu llegue a abrirse.

    El clic derecho justo despues de navegar no siempre abre el menu: Drive
    pinta la lista antes de tener los manejadores puestos, asi que el evento se
    pierde en silencio y lo que falla despues es la busqueda del item -- que se
    lee como "el selector cambio" y manda a depurar donde no esta el problema
    (comprobado el 01/09/2026 con el renombrado).

    Se espera a que aparezca el item concreto que se va a pulsar, no "algun
    menuitem": Drive deja items de otros menus en el DOM, asi que esperar
    cualquiera daba por abierto un menu que no lo estaba.
    """
    # Drive pinta la lista MUCHO antes de responder a un clic derecho. Con la
    # espera de `_abrir_carpeta` (que solo aguarda a que la lista sea visible)
    # el menu no se abria ni al segundo intento; con este margen se abre al
    # primero. Aislado el 01/09/2026 comparando contra un script que esperaba
    # 9 s tras navegar y si funcionaba.
    page.wait_for_timeout(_ms(SEG_ASENTAR_LISTA))

    # Clic derecho DIRECTO, sin seleccionar antes: comprobado el mismo dia,
    # anteponer un clic izquierdo impedia que el menu se abriera.
    for intento in (1, 2):
        try:
            fila.click(button="right")
        except ErrorPlaywright as exc:
            log.debug("Clic derecho fallido (intento %d): %s", intento, exc)
            page.wait_for_timeout(_ms(1.5))
            continue
        page.wait_for_timeout(_ms(1.5))
        if _visible(
            page.get_by_role("menuitem", name=item_esperado),
            cfg.timeout_operacion_seg / 3,
        ):
            return
        log.warning(
            "El menu contextual no aparecio al intento %d sobre %s; se reintenta.",
            intento,
            que,
        )
        page.keyboard.press("Escape")
        page.wait_for_timeout(_ms(1.5))

    raise ErrorSubidaDrive(
        f"El clic derecho sobre {que} no abrio el menu contextual tras dos "
        "intentos. Sin menu no hay forma de renombrar por interfaz."
    )


def _cualquier_rejilla(page: Page) -> Locator:
    """Localizador que casa con CUALQUIERA de los roles posibles.

    Solo sirve para ESPERAR a que la lista aparezca. Para leer filas hay que
    usar `_rejilla`, que desempata: ver ahi por que.
    """
    localizador = page.get_by_role(sel.ROLES_REJILLA[0])
    for rol in sel.ROLES_REJILLA[1:]:
        localizador = localizador.or_(page.get_by_role(rol))
    return localizador


def _rejilla(page: Page) -> Locator:
    """La lista de archivos, eligiendo el rol correcto cuando hay varios.

    Drive usa `grid` cuando la carpeta tiene contenido y `table` cuando esta
    vacia. Pero **no son excluyentes**: comprobado el 01/09/2026, la carpeta
    raiz expone `grid: 1` Y `table: 1` a la vez, donde el `table` no es la lista
    de archivos.

    De ahi que esto NO pueda ser un `or_(...).first`: en la raiz eso resolvia al
    `table` equivocado, `_buscar_fila` no encontraba 'SEPTIEMBRE' aunque estaba
    delante, y el flujo se creia obligado a crear una carpeta duplicada. Hay que
    preferir `grid` cuando exista y caer a `table` solo si no hay.
    """
    for rol in sel.ROLES_REJILLA:
        localizador = page.get_by_role(rol)
        try:
            if localizador.count():
                return localizador.first
        except ErrorPlaywright as exc:  # pragma: no cover - SPA navegando
            log.debug("No se pudo contar el rol '%s': %s", rol, exc)
    # Ninguno existe aun: se devuelve el preferido para que el mensaje de error
    # hable del rol normal y no del de respaldo.
    return page.get_by_role(sel.ROLES_REJILLA[0]).first


def _esperar_lista(page: Page, cfg: Config, descripcion: str) -> None:
    """Espera la lista de archivos y explica el caso de la carpeta vacia."""
    if _visible(_cualquier_rejilla(page), cfg.timeout_render_seg):
        return
    raise ErrorSubidaDrive(
        f"No se encontro la lista de archivos de {descripcion}. Se probaron los "
        f"roles {list(sel.ROLES_REJILLA)}. La UI de Drive no expone test-ids "
        "estables, asi que este selector puede haber cambiado: volver a grabar "
        "con scripts/grabar_drive.ps1 y contrastar con selectores_drive.py."
    )


def es_selector_de_cuenta(url: str) -> bool:
    """True si Drive esta parado en el selector de cuenta de Google.

    Se distingue de "no hay sesion" porque el remedio es OTRO, y confundirlos
    manda a depurar donde no esta el problema. Comprobado el 01/09/2026: con
    las cookies de autenticacion presentes y validas (SID, HSID, SAPISID,
    __Secure-1PSID), Drive se quedaba en
    `accounts.google.com/v3/signin/accountchooser` con el titulo 'Google Drive:
    Acceso' y no se movia en 12 s. No falta la sesion: Google tiene varias
    cuentas y pide elegir. Fijar el indice con /u/0/ o /u/1/ no lo salta.
    """
    return "accountchooser" in (url or "").lower()


def _verificar_sesion(page: Page, id_carpeta: str) -> None:
    """Distingue "no hay sesion de Google" de "el selector cambio".

    Comprobado el 21/08/2026: ante una carpeta que la sesion no puede ver,
    Drive **no redirige al login** -- devuelve un 404 con titulo
    'Error 404 (No se ha encontrado)'. Sin esta comprobacion el flujo seguia
    adelante, no encontraba la rejilla y culpaba al selector, que es un
    diagnostico enganoso y manda a depurar donde no esta el problema.

    Raises:
        ErrorSubidaDrive: si no hay sesion o la carpeta no es accesible.
    """
    if es_selector_de_cuenta(page.url):
        raise ErrorSubidaDrive(
            "Drive se quedo en el SELECTOR DE CUENTA de Google. Ojo: esto NO "
            "significa que falte la sesion -- el perfil puede tener sus cookies "
            "de autenticacion perfectamente, y aun asi Google pide elegir cuenta "
            "cuando hay varias.\n"
            "  Remedio (una sola vez): abrir el perfil con ventana, elegir la "
            "cuenta que tiene acceso a la carpeta y esperar a que cargue. La "
            "eleccion queda guardada en el perfil.\n"
            "    python scripts\\probar_perfil.py --visible "
            "--url https://drive.google.com/drive/folders/<ID> --esperar 300\n"
            "  Fijar el indice de cuenta en la URL (/u/0/, /u/1/) NO lo salta: "
            "comprobado el 01/09/2026."
        )

    if "accounts.google.com" in page.url or "/signin" in page.url:
        raise ErrorSubidaDrive(
            "Drive redirigio al login: el perfil no tiene sesion de Google. "
            "Ejecutar una vez con --visible e iniciar sesion; queda guardada en "
            "POWERBI_PERFIL_NAVEGADOR."
        )

    titulo = (page.title() or "").strip()
    if es_pagina_de_error(titulo):
        raise ErrorSubidaDrive(
            f"Drive devolvio '{titulo}' para la carpeta {id_carpeta}. Con Drive "
            "un 404 significa una de dos cosas, y conviene descartarlas en este "
            "orden:\n"
            "  1. El perfil NO tiene sesion de Google iniciada (lo mas comun: "
            "el perfil se creo para Power BI). Drive responde 404 en vez de "
            "redirigir al login, asi que no lo parece.\n"
            "     -> ejecutar una vez con --visible e iniciar sesion.\n"
            "  2. GOOGLE_CARPETA_RAIZ_ID no existe o la cuenta no tiene acceso."
        )


def _obtener_filas(page: Page) -> list[tuple[str, Locator]]:
    rejilla = _rejilla(page)
    filas = rejilla.get_by_role(sel.ROL_FILA)
    resultado: list[tuple[str, Locator]] = []
    for i in range(filas.count()):
        fila = filas.nth(i)
        etiqueta = fila.get_attribute(sel.ATRIBUTO_ETIQUETA) or ""
        if not etiqueta.strip():
            etiqueta = (fila.inner_text() or "").strip().splitlines()
            etiqueta = etiqueta[0] if etiqueta else ""
        if etiqueta.strip():
            resultado.append((etiqueta.strip(), fila))
    return resultado

def _nombres_de_archivos(page: Page) -> list[str]:
    return [nombre for nombre, _ in _obtener_filas(page)]


def _buscar_fila(page: Page, nombre: str) -> Locator | None:
    """Fila cuyo nombre contiene el texto dado (comparacion laxa)."""
    buscado = nombre.strip().casefold()
    for etiqueta, fila in _obtener_filas(page):
        if buscado in etiqueta.casefold():
            return fila
    return None
    


def _entrar_en_carpeta_mes(
    page: Page, cfg: Config, fecha: date, advertencias: list[str]
) -> tuple[str, str]:
    """Entra en la carpeta del mes, creandola si falta.

    Returns:
        (nombre de la carpeta, id de la carpeta). El id no es un extra: es con
        lo que se comprueba despues que el archivo se sube DENTRO y no en 'Mi
        unidad'. Ver `_exigir_dentro_de`.
    """
    objetivo = nombre_mes(fecha)
    id_padre = id_de_url(page.url)
    fila = _buscar_fila(page, objetivo)

    if fila is None:
        log.info("La carpeta '%s' no existe; se crea.", objetivo)
        # Drive crea la carpeta donde la UI este mirando. Sin esta guarda, un
        # fallo de lectura de la lista hacia que 'SEPTIEMBRE' naciera en 'Mi
        # unidad' en vez de dentro de 'REPORTES 2026' (01/09/2026).
        if id_padre:
            _exigir_dentro_de(page, id_padre, f"crear la carpeta '{objetivo}'")
        _crear_carpeta(page, cfg, objetivo)
        fila = _buscar_fila(page, objetivo)
        if fila is None:
            raise ErrorSubidaDrive(
                f"Se creo la carpeta '{objetivo}' pero no aparece en la lista."
            )

    # Se entra navegando por URL con el id que la propia fila expone, no con un
    # doble clic. El doble clic resulto poco fiable (24/08/2026: entro en una
    # prueba y en la siguiente no hizo nada, dejando el flujo operando sobre la
    # raiz sin enterarse). Navegar por id es determinista.
    id_carpeta = fila.get_attribute(sel.ATRIBUTO_ID_FILA)
    if id_carpeta:
        _abrir_carpeta(page, id_carpeta, cfg, f"la carpeta del mes '{objetivo}'")
        log.info("Dentro de '%s' por URL (id %s).", objetivo, id_carpeta)
        return objetivo, id_carpeta

    # Reserva: si la fila no expone el id, queda el doble clic, ahora con una
    # espera que comprueba de verdad que se entro.
    log.warning(
        "La fila de '%s' no expone %s; se recurre al doble clic.",
        objetivo,
        sel.ATRIBUTO_ID_FILA,
    )
    url_antes = page.url
    fila.dblclick()
    _esperar_entrada_en_carpeta(page, cfg, objetivo, url_antes)

    # El id se lee de la URL a la que se llego: sin el no hay con que comprobar
    # que la subida va a la carpeta correcta, y subir a ciegas es lo que dejo
    # archivos sueltos en 'Mi unidad'.
    id_carpeta = id_de_url(page.url)
    if not id_carpeta:
        raise ErrorSubidaDrive(
            f"Se entro en '{objetivo}' pero la URL no expone el id de la carpeta "
            f"({page.url[:90]}). Sin id no se puede garantizar que el archivo se "
            "suba dentro, asi que se aborta en vez de arriesgarse."
        )
    return objetivo, id_carpeta


def _esperar_entrada_en_carpeta(
    page: Page, cfg: Config, objetivo: str, url_antes: str
) -> None:
    """Espera a que Drive haya entrado DE VERDAD en la carpeta.

    Antes se esperaba a que existiera "una rejilla", y la de la carpeta anterior
    ya estaba ahi: la comprobacion se cumplia al instante y el flujo seguia
    creyendo estar dentro cuando aun estaba fuera. Comprobado el 24/08/2026: el
    log decia "Dentro de la carpeta del mes 'AGOSTO'" mientras listaba la raiz,
    y de ahi salia el "Reportes en la carpeta del mes: 0" -- estaba contando
    carpetas, no reportes.

    La senal inequivoca es la URL: al entrar en una carpeta, Drive cambia el id
    de `/folders/<id>`. El titulo se usa como confirmacion adicional.

    Raises:
        ErrorSubidaDrive: si la navegacion no se completa.
    """
    limite = time.monotonic() + cfg.timeout_render_seg
    while time.monotonic() < limite:
        if page.url != url_antes:
            # La URL ya cambio; queda esperar a que pinte el contenido nuevo.
            try:
                page.wait_for_load_state("domcontentloaded", timeout=_ms(10))
            except ErrorPlaywright:
                pass
            titulo = (page.title() or "").strip()
            if objetivo.casefold() not in titulo.casefold():
                log.warning(
                    "Se entro en una carpeta pero el titulo es '%s' y se esperaba "
                    "'%s'. Se continua; revisar si el contenido no cuadra.",
                    titulo,
                    objetivo,
                )
            log.info("Dentro de la carpeta del mes '%s' (%s).", objetivo, page.url)
            return
        page.wait_for_timeout(500)

    raise ErrorSubidaDrive(
        f"El doble clic sobre '{objetivo}' no llego a abrir la carpeta: la URL "
        f"sigue siendo {url_antes}. Sin esto, todo lo que venga despues opera "
        "sobre la carpeta equivocada."
    )


def _crear_carpeta(page: Page, cfg: Config, nombre: str) -> None:
    """Nuevo -> Nueva carpeta -> nombre -> Crear."""
    _exigir(
        page.get_by_role("button", name=sel.RX_BOTON_NUEVO),
        cfg.timeout_operacion_seg,
        "el boton 'Nuevo' de Drive",
    ).click()
    _exigir(
        page.get_by_role("menuitem", name=sel.RX_MENU_NUEVA_CARPETA),
        cfg.timeout_operacion_seg,
        "el item 'Nueva carpeta'",
    ).click()

    # Mismo cuidado que en el renombrado: el campo se busca DENTRO del dialogo.
    # `page.get_by_role("textbox").first` resolvia al buscador de Drive
    # (`<input name="q">`), de modo que el nombre se escribia en la busqueda y
    # la carpeta se creaba con el nombre por defecto.
    campo = _campo_del_dialogo(page, cfg)
    campo.fill(nombre)

    escrito = (campo.input_value() or "").strip()
    if escrito != nombre:
        raise ErrorSubidaDrive(
            f"El campo del nombre de carpeta quedo con '{escrito}' y se esperaba "
            f"'{nombre}'. No se confirma para no crear una carpeta mal nombrada."
        )

    _exigir(
        page.get_by_role("button", name=sel.RX_BOTON_CREAR),
        cfg.timeout_operacion_seg,
        "el boton 'Crear' del dialogo de carpeta",
    ).click()
    # Dar tiempo a que la rejilla se refresque con la carpeta nueva.
    page.wait_for_timeout(_ms(2))


# ---------------------------------------------------------------------------
# Consecutivo
# ---------------------------------------------------------------------------


def _leer_consecutivo(
    page: Page, cfg: Config, fecha: date, id_raiz: str, advertencias: list[str]
) -> list[ReporteEnDrive]:
    """Lee los reportes del mes actual y del anterior.

    No se recorren los doce meses: por la UI seria lento y fragil, y el
    consecutivo es monotono, asi que el mayor esta en el mes en curso o en el
    inmediatamente anterior. Si el historico tuviera un hueco de mas de un mes,
    hay que pasar --consecutivo a mano.
    """
    reportes = reportes_desde_nombres(_nombres_de_archivos(page))
    log.info("Reportes en la carpeta del mes: %d", len(reportes))

    anterior = nombre_mes_anterior(fecha)
    _abrir_carpeta(page, id_raiz, cfg, "la carpeta raiz")
    fila_anterior = _buscar_fila(page, anterior)
    if fila_anterior is not None:
        fila_anterior.dblclick()
        if _visible(_rejilla(page), cfg.timeout_render_seg):
            del_mes_anterior = reportes_desde_nombres(_nombres_de_archivos(page))
            log.info("Reportes en '%s': %d", anterior, len(del_mes_anterior))
            reportes.extend(del_mes_anterior)
    else:
        log.info("No hay carpeta '%s'; se omite.", anterior)
        advertencias.append(
            f"No se pudo revisar el mes anterior ('{anterior}') porque su carpeta "
            "no existe. Si el historico viene de mas atras, confirmar el "
            "consecutivo con --consecutivo."
        )
    return reportes


# ---------------------------------------------------------------------------
# Subida y conversion
# ---------------------------------------------------------------------------


def _subir_archivo(page: Page, cfg: Config, archivo: Path, id_carpeta: str) -> None:
    """Nuevo -> Subir archivo, resolviendo el dialogo del sistema.

    Se intercepta el selector de archivos con `expect_file_chooser` en vez de
    buscar el `input[type=file]` oculto de Drive: es la via soportada por
    Playwright y no depende del DOM interno.

    Drive sube a la carpeta que la UI este mostrando, asi que se exige estar
    dentro de la correcta ANTES de abrir el dialogo: es lo que evita dejar el
    archivo en 'Mi unidad'.
    """
    _exigir_dentro_de(page, id_carpeta, "subir el archivo")
    log.info("Subiendo %s a la carpeta %s", archivo.name, id_carpeta)

    # El menu se abre FUERA del `expect_file_chooser`, y dentro del bloque queda
    # solo el clic que de verdad abre el dialogo.
    #
    # No es cosmetico. Con los dos clics dentro del bloque, la subida no llegaba
    # a ocurrir: el dialogo se abria, `set_files` se entregaba sin error, y el
    # archivo no aparecia nunca (comprobado el 01/09/2026, dos corridas, 300 s de
    # espera y la carpeta vacia). Separandolos sube a la primera. La diferencia
    # se aislo con un A/B sobre la misma carpeta y el mismo archivo.
    _exigir(
        page.get_by_role("button", name=sel.RX_BOTON_NUEVO),
        cfg.timeout_operacion_seg,
        "el boton 'Nuevo' de Drive",
    ).click()
    page.wait_for_timeout(_ms(2))

    try:
        with page.expect_file_chooser(timeout=_ms(cfg.timeout_operacion_seg)) as info:
            _exigir(
                page.get_by_role("menuitem", name=sel.RX_MENU_SUBIR_ARCHIVO),
                cfg.timeout_operacion_seg,
                "el item 'Subir archivo'",
            ).click()
        info.value.set_files(str(archivo))
    except ErrorTiempoPlaywright as exc:
        raise ErrorSubidaDrive(
            f"No se abrio el selector de archivos al pulsar 'Subir archivo': {exc}"
        ) from exc

    _esperar_fin_de_subida(page, cfg, archivo, id_carpeta)


def _esperar_fin_de_subida(
    page: Page, cfg: Config, archivo: Path, id_carpeta: str
) -> None:
    """Espera el archivo y CONFIRMA que quedo guardado en esta carpeta.

    La fila aparece en cuanto Drive empieza a subir, asi que verla no prueba que
    la subida terminara. Comprobado el 01/09/2026: el log dijo 'El archivo ya
    figura en la carpeta', el navegador se cerro 27 s despues y la carpeta quedo
    VACIA -- la subida se habia abortado a medias y el flujo la dio por buena.

    De ahi los dos pasos: primero se espera la fila, y despues se **recarga la
    carpeta por su id** y se exige que el archivo siga ahi. Una fila que
    sobrevive a la recarga es una fila que Drive ya persistio.
    """
    base = archivo.stem
    limite = time.monotonic() + cfg.timeout_descarga_seg
    aparecio = False
    while time.monotonic() < limite:
        if _buscar_fila(page, base) is not None:
            log.info("El archivo aparece en la carpeta; queda confirmar que persiste.")
            aparecio = True
            break
        page.wait_for_timeout(_ms(2))

    if not aparecio:
        raise ErrorSubidaDrive(
            f"'{base}' no aparecio en la carpeta tras {cfg.timeout_descarga_seg}s. "
            "Revisar la traza para ver si la subida se quedo a medias."
        )

    # Confirmacion: recargar la carpeta por id y volver a buscar.
    _abrir_carpeta(page, id_carpeta, cfg, "la carpeta del mes (confirmacion)")
    if _buscar_fila(page, base) is None:
        raise ErrorSubidaDrive(
            f"'{base}' aparecio durante la subida pero NO esta en la carpeta "
            f"{id_carpeta} al recargarla. La subida se quedo a medias -- suele "
            "pasar si el navegador se cierra o se navega mientras sube. No "
            "toques la ventana de la automatizacion durante la subida."
        )
    log.info("Subida confirmada: '%s' persiste en la carpeta %s.", base, id_carpeta)


def _convertir_a_sheet(
    page: Page, context: BrowserContext, cfg: Config, nombre_subido: str
) -> bool:
    """Convierte el .xlsx subido en Google Sheet. True si hizo falta convertir.

    Solo se recurre a esto cuando Drive no convirtio en la subida. Lo robusto es
    activar a mano, una vez, Configuracion -> General -> 'Convertir los archivos
    subidos al formato del editor de Google Docs': entonces este paso -- el mas
    fragil del flujo -- no se ejecuta nunca.
    """
    fila = _buscar_fila(page, nombre_subido)
    if fila is None:
        raise ErrorSubidaDrive(f"No se encuentra la fila de '{nombre_subido}'.")

    etiqueta = fila.get_attribute(sel.ATRIBUTO_ETIQUETA) or nombre_subido
    if not sel.RX_NOMBRE_XLSX.search(etiqueta):
        log.info("Drive ya lo convirtio a Sheet en la subida.")
        return False

    log.warning(
        "El archivo subio como .xlsx: hay que convertirlo por menus. Conviene "
        "activar la conversion automatica en Configuracion de Drive."
    )

    _abrir_menu_contextual(
        page, fila, cfg, f"la fila de '{nombre_subido}'", sel.RX_MENU_ABRIR_CON
    )
    _exigir(
        page.get_by_role("menuitem", name=sel.RX_MENU_ABRIR_CON),
        cfg.timeout_operacion_seg,
        "el item 'Abrir con' del menu contextual",
    ).hover()
    try:
        with context.expect_page(timeout=_ms(cfg.timeout_render_seg)) as info:
            _exigir(
                page.get_by_role("menuitem", name=sel.RX_ABRIR_CON_SHEETS),
                cfg.timeout_operacion_seg,
                "la opcion 'Hojas de calculo de Google' de 'Abrir con'",
            ).click()
        editor = info.value
    except ErrorTiempoPlaywright as exc:
        raise ErrorSubidaDrive(
            f"No se abrio el editor de Sheets para convertir: {exc}"
        ) from exc

    editor.wait_for_load_state("domcontentloaded")
    _exigir(
        editor.get_by_role("menuitem", name=sel.RX_MENU_ARCHIVO),
        cfg.timeout_render_seg,
        "el menu 'Archivo' del editor de Sheets",
    ).click()
    _exigir(
        editor.get_by_role("menuitem", name=sel.RX_GUARDAR_COMO_SHEETS),
        cfg.timeout_operacion_seg,
        "'Guardar como Hojas de calculo de Google'",
    ).click()
    editor.wait_for_timeout(_ms(5))
    editor.close()
    return True


def abrir_sheet(
    page: Page, context: BrowserContext, cfg: Config, nombre: str
) -> tuple[Page | None, str | None]:
    """Abre el Sheet recien creado en una pestana. Devuelve (pagina, url).

    Sirve para dos cosas a la vez:

    1. Es la unica forma de obtener la URL real del Sheet por RPA. Sin API no
       hay id de archivo: hay que abrirlo y leer la barra de direcciones.
    2. Deja el Sheet a la vista antes de conmutar a SINU, que es como trabaja el
       operador: el reporte del dia abierto en una pestana mientras se clasifica
       en el sistema academico.

    No aborta si falla: el archivo ya esta subido y renombrado, que es lo
    importante. Devuelve (None, None) y deja advertencia.
    """
    fila = _buscar_fila(page, nombre)
    if fila is None:
        log.warning("No se encontro '%s' para abrirlo; se omite la pestana.", nombre)
        return None, None

    try:
        with context.expect_page(timeout=_ms(cfg.timeout_render_seg)) as info:
            fila.dblclick()
        sheet = info.value
        sheet.wait_for_load_state("domcontentloaded")
        # El editor tarda en fijar la URL definitiva del documento.
        sheet.wait_for_timeout(_ms(3))
        log.info("Sheet abierto en una pestana: %s", sheet.url)
        return sheet, sheet.url
    except ErrorTiempoPlaywright:
        log.warning(
            "El doble clic sobre '%s' no abrio ninguna pestana. El archivo esta "
            "subido; solo falta la pestana.",
            nombre,
        )
        return None, None
    except ErrorPlaywright as exc:
        log.warning("No se pudo abrir el Sheet '%s': %s", nombre, exc)
        return None, None


def _renombrar(page: Page, cfg: Config, actual: str, definitivo: str) -> None:
    """Renombra el archivo al nombre de la convencion (con sus barras)."""
    fila = _buscar_fila(page, actual)
    if fila is None:
        raise ErrorSubidaDrive(f"No se encuentra '{actual}' para renombrarlo.")

    log.info("Renombrando a '%s'", definitivo)
    _abrir_menu_contextual(
        page, fila, cfg, f"la fila de '{actual}'", sel.RX_MENU_CAMBIAR_NOMBRE
    )
    _exigir(
        page.get_by_role("menuitem", name=sel.RX_MENU_CAMBIAR_NOMBRE),
        cfg.timeout_operacion_seg,
        "el item 'Cambiar nombre' del menu contextual",
    ).click()

    # El campo se busca DENTRO del dialogo. Comprobado en la traza del
    # 24/08/2026: `page.get_by_role("textbox").first` resolvia al BUSCADOR de
    # Drive (`<input name="q">`), que va antes en el DOM. El nombre se escribia
    # en la busqueda y el dialogo se confirmaba con el nombre sin tocar, asi que
    # el archivo se quedaba con el provisional aunque todos los clics dieran ok.
    campo = _campo_del_dialogo(page, cfg)
    campo.fill(definitivo)

    # Releer lo escrito: es lo que detecta que el texto fue a otra parte.
    escrito = (campo.input_value() or "").strip()
    if escrito != definitivo:
        raise ErrorSubidaDrive(
            f"El campo de renombrado quedo con '{escrito}' y se esperaba "
            f"'{definitivo}'. No se confirma el dialogo para no renombrar mal."
        )

    _exigir(
        page.get_by_role("button", name=sel.RX_BOTON_ACEPTAR),
        cfg.timeout_operacion_seg,
        "el boton de confirmacion del renombrado",
    ).click()

    _verificar_renombrado(page, cfg, actual, definitivo)


def _campo_del_dialogo(page: Page, cfg: Config) -> Locator:
    """Campo de texto del dialogo de renombrado.

    Se acota al dialogo a proposito. Si Drive no expusiera `role="dialog"`, se
    recurre a descartar el buscador (`name="q"`), que es el textbox que se
    colaba.

    Raises:
        ErrorSubidaDrive: si no se encuentra un campo utilizable.
    """
    dialogo = page.get_by_role("dialog")
    if _visible(dialogo, cfg.timeout_operacion_seg):
        campo = dialogo.first.get_by_role("textbox")
        if _visible(campo, cfg.timeout_operacion_seg):
            return campo.first
        log.warning("El dialogo no expone un textbox; se busca fuera descartando el buscador.")

    fuera = page.locator('input[type="text"]:not([name="q"]), textarea:not([name="q"])')
    if _visible(fuera, cfg.timeout_operacion_seg):
        return fuera.first

    raise ErrorSubidaDrive(
        "No se encontro el campo de nombre del dialogo de renombrado. Ojo: NO "
        "vale el primer textbox de la pagina, que es el buscador de Drive."
    )


def _verificar_renombrado(page: Page, cfg: Config, actual: str, definitivo: str) -> None:
    """Comprueba que el archivo quedo con el nombre nuevo.

    Sin `wait_for_load_state("networkidle")`: Drive es una SPA con trafico de
    fondo continuo y nunca alcanza ese estado, de modo que esa espera agotaba
    los 30 s siempre. Se observa lo unico que importa -- que la fila aparezca
    con el nombre nuevo -- y, si no aparece, se recarga la carpeta por URL.

    Raises:
        ErrorSubidaDrive: si el nombre nuevo no llega a aparecer.
    """
    limite = time.monotonic() + cfg.timeout_operacion_seg
    while time.monotonic() < limite:
        if _buscar_fila(page, definitivo) is not None:
            log.info("Renombrado confirmado en la lista: '%s'.", definitivo)
            return
        page.wait_for_timeout(1000)

    # Segundo intento: recargar la carpeta navegando a su URL (no `reload()` +
    # networkidle) por si la rejilla no se refresco sola.
    log.warning("'%s' no aparecio aun; se recarga la carpeta.", definitivo)
    try:
        page.goto(page.url, wait_until="domcontentloaded", timeout=_ms(cfg.timeout_render_seg))
        _exigir(
            _rejilla(page),
            cfg.timeout_operacion_seg,
            "la lista de archivos tras recargar",
        )
        page.wait_for_timeout(_ms(3))
    except ErrorPlaywright as exc:
        log.warning("No se pudo recargar la carpeta: %s", exc)

    if _buscar_fila(page, definitivo) is not None:
        log.info("Renombrado confirmado tras recargar: '%s'.", definitivo)
        return

    sigue_el_provisional = _buscar_fila(page, actual) is not None
    raise ErrorSubidaDrive(
        f"El renombrado a '{definitivo}' NO se aplico"
        + (f": el archivo sigue como '{actual}'." if sigue_el_provisional else ".")
        + " No se da por bueno: un nombre provisional en Drive rompe la busqueda "
        "del reporte del dia."
    )

# ---------------------------------------------------------------------------
# Orquestacion
# ---------------------------------------------------------------------------


def subir_reporte(
    archivo: Path,
    *,
    cfg: Config | None = None,
    fecha: date | None = None,
    no_matriculado: int | None = None,
    consecutivo: int | None = None,
    headless: bool | None = None,
    con_traza: bool = False,
    abrir_al_terminar: bool = True,
    context: BrowserContext | None = None,
) -> ResultadoSubida:
    """Sube el .xlsx validado a Drive con la convencion acordada.

    Args:
        archivo: el .xlsx **ya coloreado** por la Fase 1.
        cfg: configuracion efectiva.
        fecha: fecha del reporte; por defecto, hoy.
        consecutivo: fuerza el numero. Si se omite, se deduce de Drive y, si no
            se puede deducir, se aborta en vez de arrancar en #1.
        headless: fuerza el modo del navegador.
        con_traza: guarda traza de Playwright en `logs/`.
        context: contexto de navegador ya abierto. Si se pasa, esta funcion NO
            lo crea ni lo cierra: lo gestiona quien llama. Es lo que permite que
            la pestana del Sheet siga abierta al pasar a SINU, porque ambas
            etapas comparten el mismo navegador. Sin este argumento el
            comportamiento es el de siempre: se abre uno y se cierra al acabar.

    Raises:
        ErrorSubidaDrive: si falta configuracion, si un paso no se localiza, si
            ya hay reporte de esa fecha o si no se puede deducir el consecutivo.
    """
    cfg = cfg or Config.desde_entorno()
    archivo = Path(archivo)
    if not archivo.is_file():
        raise ErrorSubidaDrive(f"No existe el archivo a subir: {archivo}")
    if not cfg.google_carpeta_raiz_id:
        raise ErrorSubidaDrive(
            "Falta GOOGLE_CARPETA_RAIZ_ID en config/.env: es el id de la carpeta "
            "raiz en Drive, que se lee de su URL."
        )

    fecha = fecha or date.today()
    sin_cabeza = cfg.powerbi_headless if headless is None else headless
    advertencias: list[str] = []
    ruta_traza: Path | None = None
    url_sheet: str | None = None
    pagina_sheet: Page | None = None
    inicio = time.monotonic()
    sello = datetime.now().strftime("%Y%m%d_%H%M%S")

    # El contexto solo se crea (y se cierra) si no lo aporta quien llama. Se usa
    # ExitStack en vez de un `with sync_playwright()` fijo para no duplicar todo
    # el cuerpo de la funcion en dos ramas.
    contexto_propio = context is None
    with ExitStack() as pila:
        if contexto_propio:
            pw = pila.enter_context(sync_playwright())
            context, cerrar = abrir_contexto(pw, cfg, sin_cabeza)
            pila.callback(cerrar)
        else:
            log.info("Reutilizando el contexto de navegador de quien llama.")
        if con_traza:
            DIR_LOGS.mkdir(parents=True, exist_ok=True)
            ruta_traza = DIR_LOGS / f"traza_drive_{sello}.zip"
            context.tracing.start(screenshots=True, snapshots=True, sources=True)

        try:
            context.set_default_timeout(_ms(cfg.timeout_operacion_seg))
            page = context.pages[0] if context.pages else context.new_page()
            id_raiz = cfg.google_carpeta_raiz_id

            # 1-2. Raiz -> carpeta del mes.
            _abrir_carpeta(page, id_raiz, cfg, "la carpeta raiz")
            carpeta, _ = _entrar_en_carpeta_mes(page, cfg, fecha, advertencias)

            # 3. Consecutivo, leyendo mes actual y anterior.
            reportes = _leer_consecutivo(page, cfg, fecha, id_raiz, advertencias)
            del_dia = [r for r in reportes if r.fecha == fecha]
            if del_dia:
                raise ErrorSubidaDrive(
                    f"Ya hay un reporte de {fecha:%d/%m/%Y}: "
                    + ", ".join(f"'{r.nombre}'" for r in del_dia)
                    + ". Se aborta para no duplicar."
                )

            # El numero del nombre es el valor de la tarjeta 'NO MATRICULADO'
            # del tablero, NO un consecutivo (decision del 24/08/2026). Orden:
            # el que se pase explicitamente, si no el de la tarjeta, si no las
            # filas del propio .xlsx -- que cuentan lo mismo, porque la vista de
            # Power BI viene filtrada a VALIDACION != MATRICULADO.
            numero = consecutivo if consecutivo is not None else no_matriculado
            if numero is None:
                numero = contar_filas_datos(archivo)
                log.warning(
                    "Sin valor de 'NO MATRICULADO'; se usan las %d filas de datos "
                    "del .xlsx, que cuentan lo mismo. Conviene pasarlo explicito.",
                    numero,
                )
            if numero is None:
                raise ErrorSubidaDrive(
                    "No hay numero para el nombre del reporte: ni tarjeta "
                    "'NO MATRICULADO', ni filas legibles en el .xlsx."
                )
            log.info("Numero del reporte (NO MATRICULADO): #%d", numero)

            # 4. Subir con un nombre local saneado (la barra no es legal en Windows).
            provisional = nombre_local_para_subir(fecha, numero)
            temporal = Path(mkdtemp(prefix="subida-drive-")) / provisional
            shutil.copy2(archivo, temporal)
            try:
                _abrir_carpeta(page, id_raiz, cfg, "la carpeta raiz")
                _, id_mes = _entrar_en_carpeta_mes(page, cfg, fecha, advertencias)
                _subir_archivo(page, cfg, temporal, id_mes)

                # 5. Asegurar que quedo como Sheet.
                convertido = _convertir_a_sheet(page, context, cfg, temporal.stem)

                # 6. Nombre definitivo, ya con las barras.
                definitivo = nombre_reporte(fecha, numero)
                _renombrar(page, cfg, temporal.stem, definitivo)
            finally:
                shutil.rmtree(temporal.parent, ignore_errors=True)

            # 7. Abrir el Sheet: da su URL real y lo deja a la vista antes de
            #    conmutar a SINU.
            if abrir_al_terminar:
                pagina_sheet, url_sheet = abrir_sheet(page, context, cfg, definitivo)
                if url_sheet is None:
                    advertencias.append(
                        "No se pudo abrir el Sheet en una pestana; el archivo si "
                        "quedo subido y renombrado."
                    )

            enlace = url_sheet or page.url
        except ErrorSubidaDrive:
            raise
        except ErrorPlaywright as exc:
            raise ErrorSubidaDrive(f"Error de Playwright durante la subida: {exc}") from exc
        finally:
            if con_traza and ruta_traza is not None:
                context.tracing.stop(path=str(ruta_traza))
                log.info("Traza: playwright show-trace %s", ruta_traza)

    return ResultadoSubida(
        nombre=definitivo,
        carpeta_mes=carpeta,
        consecutivo=numero,
        enlace=enlace,
        convertido_a_sheet=convertido,
        url_sheet=url_sheet,
        # Solo se devuelve viva si el contexto sobrevive a esta funcion.
        pagina_sheet=pagina_sheet if not contexto_propio else None,
        segundos=round(time.monotonic() - inicio, 1),
        advertencias=advertencias,
        traza=ruta_traza,
    )
