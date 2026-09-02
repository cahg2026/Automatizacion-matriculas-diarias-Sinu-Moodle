"""Etapa 4: ejecucion de la vinculacion en ISEF07. UNICO modulo que escribe.

Regla de negocio (dueno del proceso, 21/08/2026)
------------------------------------------------
Segun el estado de "Vinculado?":

    Vinculado? = False  ->  Vincular, ejecutar.
    Vinculado? = True   ->  Desvincular, ejecutar, esperar;
                            luego Vincular, ejecutar, esperar.

Es decir: lo que ya esta vinculado se **recicla** (se deshace y se vuelve a
hacer), no se deja como esta.

Dos avisos que el codigo tiene en cuenta
----------------------------------------
**La accion es por estudiante, no por materia.** "Vincular grupos matriculados"
actua sobre todas las asignaturas del periodo activo de golpe; la grilla Grupos
es informativa. Por eso la regla se aplica al estudiante: si ALGUNA de sus
materias esta vinculada, se recicla el estudiante completo. El estado final es
el que se busca -- todas vinculadas -- pero el desvincular pasa tambien por
materias que no lo necesitaban. No hay forma de hacerlo por materia con esta
pantalla.

**El reciclado abre una ventana de riesgo.** Entre el desvincular y el vincular
el estudiante queda SIN vincular. Si el proceso se corta ahi (timeout, caida,
parada manual), el estudiante acaba peor que al empezar. De ahi:

- Se anota en `logs/ciclos_abiertos.jsonl` ANTES de desvincular y se cierra el
  apunte tras vincular. Un apunte sin cerrar es un estudiante que hay que
  revisar a mano, y sobrevive a que el proceso muera.
- El vincular posterior se reintenta antes de rendirse.
- Al terminar, el CLI enumera los ciclos que quedaron abiertos.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path

from playwright.sync_api import (
    Error as ErrorPlaywright,
    Locator,
    Page,
    TimeoutError as ErrorTiempoPlaywright,
)

from . import selectores_sinu_escritura as sesc
from .clasificador_sinu import FilaGrupoSinu
from .config import DIR_LOGS, Config
from .constantes_sinu import (
    ACTIVIDAD_VINCULACION,
    SEG_EJECUCION_VINCULACION,
    TIMEOUT_EJECUCION_ISEF07_SEG,
    TIMEOUT_OPERACION_SINU_SEG,
)
from .lector_sinu import clic_smartclient
from .restricciones_sinu import exigir_modulo_escribible

log = logging.getLogger(__name__)

#: Registro persistente de ciclos desvincular->vincular a medio hacer.
RUTA_CICLOS_ABIERTOS = DIR_LOGS / "ciclos_abiertos.jsonl"

#: Reintentos del vincular que cierra un ciclo. Mas alto que en el resto del
#: proyecto a proposito: si esto falla, un estudiante queda desvinculado.
REINTENTOS_VINCULAR_TRAS_DESVINCULAR = 3


class TipoSecuencia(Enum):
    """Que hay que ejecutar para un estudiante."""

    SOLO_VINCULAR = "vincular"
    """Ninguna de sus materias estaba vinculada."""

    RECICLAR = "desvincular+vincular"
    """Alguna estaba vinculada: se deshace y se vuelve a hacer."""

    NADA = "nada"
    """No hay materias sobre las que actuar."""


class ErrorEjecucionSinu(RuntimeError):
    """La ejecucion en ISEF07 no se pudo completar."""


class CicloAbierto(ErrorEjecucionSinu):
    """Se desvinculo y no se pudo volver a vincular.

    Es el peor resultado posible de esta etapa: el estudiante queda desvinculado.
    Se distingue del resto de errores para que nunca se trate como un fallo mas.
    """


@dataclass
class ResultadoEjecucion:
    """Lo que se hizo con un estudiante."""

    identificacion: str
    cod_periodo: str
    secuencia: TipoSecuencia
    acciones_ejecutadas: list[str] = field(default_factory=list)
    simulado: bool = False
    segundos: float = 0.0
    ciclo_abierto: bool = False
    detalle: str = ""


# ---------------------------------------------------------------------------
# Decision (funcion pura, probada sin navegador)
# ---------------------------------------------------------------------------


def decidir_secuencia(grupos: list[FilaGrupoSinu]) -> TipoSecuencia:
    """Aplica la regla de negocio al conjunto de materias de un estudiante.

    La accion de ISEF07 es por estudiante, asi que la decision se toma sobre el
    conjunto: basta UNA materia vinculada para que haya que reciclar.
    """
    if not grupos:
        return TipoSecuencia.NADA
    if any(g.vinculado for g in grupos):
        return TipoSecuencia.RECICLAR
    return TipoSecuencia.SOLO_VINCULAR


def acciones_de(secuencia: TipoSecuencia) -> tuple[str, ...]:
    """Opciones del desplegable a ejecutar, en orden."""
    if secuencia is TipoSecuencia.SOLO_VINCULAR:
        return (sesc.OPCION_VINCULAR,)
    if secuencia is TipoSecuencia.RECICLAR:
        # El orden importa: primero deshacer, luego volver a hacer.
        return (sesc.OPCION_DESVINCULAR, sesc.OPCION_VINCULAR)
    return ()


def estimar_segundos(secuencia: TipoSecuencia) -> tuple[int, int]:
    """Margen de duracion de una secuencia, segun los tiempos de la referencia."""
    n = len(acciones_de(secuencia))
    return n * SEG_EJECUCION_VINCULACION[0], n * SEG_EJECUCION_VINCULACION[1]


# ---------------------------------------------------------------------------
# Registro de ciclos a medio hacer
# ---------------------------------------------------------------------------


def _apuntar_ciclo(identificacion: str, cod_periodo: str, estado: str) -> None:
    """Anota en disco el estado de un ciclo. Debe sobrevivir a que el proceso muera."""
    RUTA_CICLOS_ABIERTOS.parent.mkdir(parents=True, exist_ok=True)
    apunte = {
        "momento": datetime.now().isoformat(timespec="seconds"),
        "identificacion": identificacion,
        "cod_periodo": cod_periodo,
        "estado": estado,
    }
    with RUTA_CICLOS_ABIERTOS.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(apunte, ensure_ascii=False) + "\n")
        fh.flush()


def ciclos_abiertos() -> list[dict]:
    """Ciclos que se abrieron y no se cerraron: estudiantes a revisar a mano."""
    if not RUTA_CICLOS_ABIERTOS.is_file():
        return []

    estado: dict[tuple[str, str], dict] = {}
    for linea in RUTA_CICLOS_ABIERTOS.read_text(encoding="utf-8").splitlines():
        if not linea.strip():
            continue
        try:
            apunte = json.loads(linea)
        except ValueError:
            continue
        clave = (apunte.get("identificacion", ""), apunte.get("cod_periodo", ""))
        if apunte.get("estado") == "cerrado":
            estado.pop(clave, None)
        else:
            estado[clave] = apunte
    return list(estado.values())


# ---------------------------------------------------------------------------
# Controles de la interfaz
# ---------------------------------------------------------------------------


def _ms(segundos: float) -> float:
    return segundos * 1000


def _visible(locator: Locator, timeout_seg: float) -> bool:
    try:
        locator.first.wait_for(state="visible", timeout=_ms(timeout_seg))
        return True
    except (ErrorTiempoPlaywright, ErrorPlaywright):
        return False


def seleccionar_accion(page: Page, cfg: Config, opcion: str) -> None:
    """Elige una opcion del desplegable "Accion a realizar" y lo comprueba.

    Se verifica en cada estudiante porque la referencia marca como error comun
    que el desplegable se quede vacio entre uno y otro.

    Raises:
        ErrorEjecucionSinu: si no se puede dejar seleccionada la opcion.
    """
    esperado = sesc.RX_OPCION_DESVINCULAR if "esvincular" in opcion else sesc.RX_OPCION_VINCULAR

    candidatos = candidatos_desplegable_accion(page)
    if not candidatos:
        raise ErrorEjecucionSinu(
            "No se encontro ningun desplegable junto al icono de ejecutar. Si "
            "ISEF07 cambio esa zona, hay que volver a inspeccionarla."
        )

    # Se pulsa por coordenadas porque el desplegable arranca VACIO: no hay texto
    # por el que filtrarlo. Y se PRUEBAN los candidatos en orden, comprobando en
    # cada uno que la lista ofrezca la opcion buscada.
    #
    # Fiarse de un solo candidato fallo el 01/09/2026 en cuanto la grilla tenia
    # 7 asignaturas: el elegido abria una lista de seis celdas vacias -- era otro
    # control -- y el mensaje culpaba al texto de la opcion.
    opcion_lista = page.get_by_text(esperado)
    abierta = False
    for i, caja in enumerate(candidatos, 1):
        page.mouse.click(caja["x"] + caja["w"] / 2, caja["y"] + caja["h"] / 2)
        page.wait_for_timeout(_ms(2))
        if _visible(opcion_lista, cfg.timeout_operacion_seg / 6):
            log.debug("Desplegable de la accion: candidato %d (x=%s)", i, round(caja["x"]))
            abierta = True
            break
        vistas = [t.strip() for t in page.locator(sesc.CSS_OPCION_LISTA).all_inner_texts()]
        log.warning(
            "El candidato %d/%d (x=%s) no ofrece '%s'. Opciones que muestra: %s. "
            "Se prueba el siguiente.",
            i,
            len(candidatos),
            round(caja["x"]),
            opcion,
            [v for v in vistas if v][:4] or "ninguna con texto",
        )
        page.keyboard.press("Escape")
        page.wait_for_timeout(_ms(1))

    if not abierta:
        raise ErrorEjecucionSinu(
            f"Ninguno de los {len(candidatos)} desplegables junto al icono de "
            f"ejecutar ofrece la opcion '{opcion}'. Revisar la traza: o la zona "
            "de 'Accion a realizar' cambio, o el texto de la opcion ya no es ese."
        )

    # La lista desplegada es una capa flotante de SmartClient: el clic del
    # localizador se daba por hecho sin efecto (el desplegable seguia vacio) y la
    # comprobacion de mas abajo lo cazaba. Con un clic de raton en el centro de
    # la opcion si queda seleccionada, igual que al abrirlo.
    clic_smartclient(page, opcion_lista, f"la opcion '{opcion}'")
    page.wait_for_timeout(_ms(2))

    # Se le quita el foco al desplegable. Tras seleccionar queda como
    # `selectItemTextFocused` y el boton de ejecutar seguia deshabilitado; el
    # cambio de SmartClient no se consolida hasta que el control pierde el foco.
    page.keyboard.press("Tab")
    page.wait_for_timeout(_ms(1.5))

    # Comprobar que quedo puesta: ejecutar con la accion equivocada es
    # exactamente el fallo que no se puede permitir aqui.
    texto = leer_accion_seleccionada(page) or ""
    if not esperado.search(texto):
        raise ErrorEjecucionSinu(
            f"Se pidio '{opcion}' pero el desplegable muestra '{texto}'. No se "
            "ejecuta con una accion sin confirmar."
        )
    log.info("Accion seleccionada y confirmada: %s", texto)


#: Guion que localiza la etiqueta de la accion y el desplegable a su derecha.
#: Se hace en JS porque hace falta comparar geometrias, y el elemento correcto es
#: el MAS PEQUENO que contiene el texto: el mayor es un contenedor de 740x145 que
#: incluye la barra de progreso.
_GUION_ZONA_ACCION = """
(cfg) => {
  // Ancla por RELACION DE DOM, no por coordenadas.
  //
  // Las dos versiones geometricas anteriores (etiqueta como ancla, luego icono)
  // fallaron por lo mismo: el tamano de la ventana cambia la disposicion. Con
  // ventana real maximizada el candidato salia en x=516 y con viewport headless
  // de 1920x1080 en x=846, asi que un umbral en pixeles no puede acertar en los
  // dos casos (01/09/2026).
  //
  // Lo estable es el parentesco: el desplegable de la accion vive DENTRO del
  // mismo contenedor que su etiqueta. Medido: la etiqueta es un TD de 106 px y
  // su DIV padre, de 426 px, contiene tambien el desplegable.
  const esEtiqueta = (e) => {
    const t = (e.innerText||'').replace(/\\s+/g,' ').trim();
    return /^acci.n\\s+a\\s+realizar\\s*:?$/i.test(t);
  };

  // La etiqueta mas ajustada: el elemento cuyo texto es SOLO la etiqueta.
  let etiqueta = null, area = Infinity;
  for (const e of document.querySelectorAll('td, nobr, span, label, div')) {
    if (!esEtiqueta(e)) continue;
    const r = e.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    const a = r.width * r.height;
    if (a < area) { area = a; etiqueta = e; }
  }
  if (!etiqueta) return [];

  // Se sube por los ancestros hasta el primero que contenga un desplegable, y
  // se devuelven los que haya dentro de ese contenedor. Subir de uno en uno
  // evita salir a un contenedor tan grande que abarque media pantalla.
  const salida = [];
  let n = etiqueta.parentElement;
  for (let i = 0; i < 6 && n; i++) {
    const dentro = n.querySelectorAll(cfg.cssDesplegable);
    if (dentro.length) {
      for (const e of dentro) {
        const r = e.getBoundingClientRect();
        if (r.width === 0) continue;
        salida.push({x: r.x, y: r.y, w: r.width, h: r.height,
                     txt: (e.innerText||'').trim()});
      }
      if (salida.length) break;
    }
    n = n.parentElement;
  }
  salida.sort((a, b) => a.x - b.x);
  return salida;
}
"""


def candidatos_desplegable_accion(page: Page) -> list[dict]:
    """Desplegables que podrian ser el de 'Accion a realizar', de izq. a der.

    Se devuelven varios a proposito. Un unico candidato "el mas probable" se
    equivoco en cuanto cambio el alto de la grilla: abria una lista de seis
    celdas vacias. Probando por orden y comprobando que la lista ofrezca la
    opcion buscada, el acierto no depende de que la geometria sea perfecta.
    """
    try:
        return page.evaluate(
            _GUION_ZONA_ACCION,
            {
                "prefijoIcono": sesc.PREFIJO_ICONO_EJECUTAR,
                "cssDesplegable": sesc.CSS_TEXTO_SELECCION,
            },
        )
    except ErrorPlaywright as exc:  # pragma: no cover - la SPA repinta
        log.debug("No se pudo localizar la zona de accion: %s", exc)
        return []


def localizar_desplegable_accion(page: Page) -> dict | None:
    """El candidato mas probable, para diagnostico. Ver `candidatos_...`."""
    candidatos = candidatos_desplegable_accion(page)
    return candidatos[0] if candidatos else None


def leer_accion_seleccionada(page: Page) -> str | None:
    """Texto de la accion que el desplegable muestra ahora, o None.

    Se busca por CONTENIDO y no por posicion: tras seleccionar, el desplegable
    muestra el nombre de la accion, y eso lo identifica sin ambigüedad. Leerlo
    por geometria fallaba en cuanto la pantalla se repintaba.
    """
    try:
        return page.evaluate(
            """
            (css) => {
              for (const e of document.querySelectorAll(css)) {
                const t = (e.innerText||'').replace(/\\s+/g,' ').trim();
                if (/incular grupos matriculados/i.test(t)) return t;
              }
              return null;
            }
            """,
            sesc.CSS_TEXTO_SELECCION,
        )
    except ErrorPlaywright:  # pragma: no cover
        return None


def ejecutar_habilitado(page: Page) -> bool | None:
    """True si el boton de ejecutar esta pulsable. None si no se localiza.

    Se mira el NOMBRE DE LA IMAGEN, no la clase del contenedor. SmartClient
    marca cada boton deshabilitado con el sufijo `_Disabled` en su src, igual
    que hace con los checks de la grilla:

        icon_start.png            <- habilitado
        icon_pause_Disabled.png   <- deshabilitado
        icon_stop_Disabled.png    <- deshabilitado

    La clase `toolbarButtonDisabled` la lleva el CONTENEDOR del grupo de
    botones, asi que sigue presente incluso con el de arranque activo. Mirarla
    devolvia "deshabilitado" siempre y bloqueaba la etapa 4 sin motivo: el
    01/09/2026 seguia en False con la accion ya seleccionada y verificada.
    """
    icono = page.locator(f'img[src*="{sesc.PREFIJO_ICONO_EJECUTAR}"]')
    if not icono.count():
        return None
    try:
        src = icono.first.get_attribute("src") or ""
    except ErrorPlaywright:
        return None
    return sesc.SUFIJO_DESHABILITADO not in src.rsplit("/", 1)[-1]


def pulsar_ejecutar(page: Page, cfg: Config) -> None:
    """Pulsa el icono de ejecutar, comprobando antes que este habilitado.

    El icono se localiza por el NOMBRE DE SU IMAGEN (`icon_start.png`), que es
    estable. Sustituye a la descripcion posicional de la referencia ("el primero
    de tres, tipo engranaje"): verificado el 01/09/2026, no son engranajes sino
    un mando de reproduccion -- start, pause y stop -- y el de arranque es el
    primero, como decia, pero ahora no hay que contarlos.

    Raises:
        ErrorEjecucionSinu: si no se localiza el icono o esta deshabilitado.
    """
    icono = page.locator(sesc.CSS_ICONO_EJECUTAR)
    if not _visible(icono, cfg.timeout_operacion_seg):
        raise ErrorEjecucionSinu(
            f"No se localizo el icono de ejecutar ({sesc.CSS_ICONO_EJECUTAR}). "
            "Si ISEF07 cambio sus iconos, hay que volver a inspeccionar la zona "
            "de 'Accion a realizar' antes de ejecutar nada."
        )

    habilitado = ejecutar_habilitado(page)
    if habilitado is False:
        raise ErrorEjecucionSinu(
            "El boton de ejecutar esta DESHABILITADO "
            f"(clase '{sesc.CLASE_BOTON_DESHABILITADO}'). Suele significar que la "
            "accion no quedo seleccionada. No se pulsa: pulsarlo no haria nada y "
            "el estudiante se contaria como procesado sin estarlo."
        )

    icono.first.click()
    log.info("Ejecutar pulsado (icono localizado por %s).", sesc.IMG_ICONO_EJECUTAR)


def esperar_proceso_terminado(page: Page, cfg: Config) -> str:
    """Espera el dialogo de fin y lo cierra. Devuelve el texto que mostro.

    Raises:
        ErrorEjecucionSinu: si aparece un mensaje de error o no termina a tiempo.
    """
    # Plazo PROPIO, mas amplio que el general: esperar el dialogo de fin no es
    # como esperar un control de la interfaz. Ver TIMEOUT_EJECUCION_ISEF07_SEG.
    limite = time.monotonic() + TIMEOUT_EJECUCION_ISEF07_SEG
    while time.monotonic() < limite:
        dialogo = page.get_by_text(sesc.RX_PROCESO_TERMINADO)
        if dialogo.count():
            texto = (dialogo.first.inner_text() or "").strip()
            if sesc.RX_MENSAJE_ERROR.search(texto):
                raise ErrorEjecucionSinu(f"El proceso informo de un error: {texto[:200]}")
            ok = page.get_by_text(sesc.RX_BOTON_OK)
            if ok.count():
                ok.first.click()
            log.info("Proceso terminado: %s", texto[:120])
            return texto

        error = page.get_by_text(sesc.RX_MENSAJE_ERROR)
        if error.count() and error.first.is_visible():
            texto = (error.first.inner_text() or "").strip()
            raise ErrorEjecucionSinu(f"SINU mostro un error: {texto[:200]}")

        page.wait_for_timeout(2000)

    raise ErrorEjecucionSinu(
        f"El proceso no termino en {TIMEOUT_EJECUCION_ISEF07_SEG}s. No se asume "
        "que haya salido bien."
    )


class AccionNoSeleccionada(ErrorEjecucionSinu):
    """Fallo ANTES de pulsar ejecutar: la accion no llego a lanzarse.

    Se distingue del resto porque cambia lo que hay que hacer despues. Si no se
    pudo ni seleccionar la accion, la escritura **no ocurrio**, asi que no hay
    ciclo que revisar a mano. Confundirlo con un fallo posterior llenaba
    `ciclos_abiertos.jsonl` de alarmas falsas -- y una alarma falsa en el unico
    aviso que de verdad importa es peor que no tenerlo (comprobado el
    01/09/2026: el registro dijo que un estudiante podia estar desvinculado y
    sus 7 asignaturas estaban intactas).
    """


def _ejecutar_una(
    page: Page, cfg: Config, opcion: str, antes_de_ejecutar=None
) -> None:
    """Selecciona una accion, la ejecuta y espera su confirmacion.

    Args:
        antes_de_ejecutar: se llama justo ANTES de pulsar el boton, cuando la
            accion ya esta seleccionada y verificada. Es el momento exacto en
            que empieza la ventana de riesgo, y por tanto el sitio correcto para
            dejar constancia en disco.

    Raises:
        AccionNoSeleccionada: si se fallo antes de pulsar (no hubo escritura).
        ErrorEjecucionSinu: si se fallo al pulsar o esperando la confirmacion,
            donde el estado del sistema es incierto.
    """
    exigir_modulo_escribible(ACTIVIDAD_VINCULACION, opcion)
    try:
        seleccionar_accion(page, cfg, opcion)
    except ErrorEjecucionSinu as exc:
        raise AccionNoSeleccionada(str(exc)) from exc

    if antes_de_ejecutar is not None:
        antes_de_ejecutar()
    pulsar_ejecutar(page, cfg)
    esperar_proceso_terminado(page, cfg)


# ---------------------------------------------------------------------------
# Orquestacion por estudiante
# ---------------------------------------------------------------------------


def ejecutar_estudiante(
    page: Page,
    cfg: Config,
    *,
    identificacion: str,
    cod_periodo: str,
    grupos: list[FilaGrupoSinu],
) -> ResultadoEjecucion:
    """Aplica la regla de negocio a un estudiante ya seleccionado en ISEF07.

    Con `MODO_SIMULACION=true` no se toca nada: solo se informa de que se haria.

    Raises:
        CicloAbierto: si se desvinculo y no se logro volver a vincular.
        ErrorEjecucionSinu: cualquier otro fallo, antes de modificar nada o en
            una secuencia que no dejo al estudiante desvinculado.
    """
    inicio = time.monotonic()
    secuencia = decidir_secuencia(grupos)
    acciones = acciones_de(secuencia)
    resultado = ResultadoEjecucion(
        identificacion=identificacion, cod_periodo=cod_periodo, secuencia=secuencia
    )

    vinculadas = sum(1 for g in grupos if g.vinculado)
    log.info(
        "%s (%s): %d materias, %d ya vinculadas -> %s",
        identificacion,
        cod_periodo,
        len(grupos),
        vinculadas,
        secuencia.value,
    )

    if secuencia is TipoSecuencia.NADA:
        resultado.detalle = "Sin materias en la grilla: no hay nada que ejecutar."
        return resultado

    if cfg.modo_simulacion:
        resultado.simulado = True
        resultado.acciones_ejecutadas = list(acciones)
        resultado.detalle = (
            "MODO_SIMULACION=true: no se ejecuto nada. Se habria hecho "
            + " -> ".join(acciones)
        )
        log.warning("[SIMULACION] %s", resultado.detalle)
        return resultado

    if secuencia is TipoSecuencia.SOLO_VINCULAR:
        _ejecutar_una(page, cfg, sesc.OPCION_VINCULAR)
        resultado.acciones_ejecutadas.append(sesc.OPCION_VINCULAR)
        resultado.segundos = round(time.monotonic() - inicio, 1)
        return resultado

    # --- Reciclado: aqui esta la ventana de riesgo ---
    # El apunte se escribe justo antes de PULSAR, no antes de intentar la
    # seleccion. Asi existe si el proceso muere en el peor instante posible, y
    # NO se crea cuando el fallo fue anterior a cualquier escritura.
    try:
        _ejecutar_una(
            page,
            cfg,
            sesc.OPCION_DESVINCULAR,
            antes_de_ejecutar=lambda: _apuntar_ciclo(
                identificacion, cod_periodo, "desvinculando"
            ),
        )
        resultado.acciones_ejecutadas.append(sesc.OPCION_DESVINCULAR)
    except AccionNoSeleccionada:
        # No se llego a pulsar: el desvincular NO ocurrio y no hay nada que
        # revisar a mano. Se propaga como fallo del estudiante, sin ciclo.
        raise
    except ErrorEjecucionSinu:
        # Se pulso (o pudo pulsarse) y algo fallo despues: no se sabe si el
        # desvincular llego a aplicarse. El apunte queda ABIERTO a proposito.
        resultado.ciclo_abierto = True
        raise

    _apuntar_ciclo(identificacion, cod_periodo, "desvinculado-pendiente-vincular")
    ultimo: Exception | None = None
    for intento in range(1, REINTENTOS_VINCULAR_TRAS_DESVINCULAR + 1):
        try:
            _ejecutar_una(page, cfg, sesc.OPCION_VINCULAR)
            resultado.acciones_ejecutadas.append(sesc.OPCION_VINCULAR)
            _apuntar_ciclo(identificacion, cod_periodo, "cerrado")
            resultado.segundos = round(time.monotonic() - inicio, 1)
            return resultado
        except ErrorEjecucionSinu as exc:
            ultimo = exc
            log.error(
                "Fallo el vincular tras desvincular (%d/%d) para %s: %s",
                intento,
                REINTENTOS_VINCULAR_TRAS_DESVINCULAR,
                identificacion,
                exc,
            )
            page.wait_for_timeout(3000)

    resultado.ciclo_abierto = True
    raise CicloAbierto(
        f"ESTUDIANTE {identificacion} ({cod_periodo}) QUEDO DESVINCULADO: se "
        f"desvinculo y el vincular fallo {REINTENTOS_VINCULAR_TRAS_DESVINCULAR} "
        f"veces. Ultimo error: {ultimo}. Hay que vincularlo A MANO en ISEF07. "
        f"Apuntado en {RUTA_CICLOS_ABIERTOS}."
    )
