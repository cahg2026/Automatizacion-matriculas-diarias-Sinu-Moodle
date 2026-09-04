"""Etapa 4: ejecucion de la vinculacion en ISEF07. UNICO modulo que escribe.

Regla de negocio (dueno del proceso, 21/08/2026)
------------------------------------------------
Segun el estado de "Vinculado?":

    Vinculado? = False  ->  Vincular, ejecutar.
    Vinculado? = True   ->  Desvincular, ejecutar, esperar;
                            luego Vincular, ejecutar, esperar.

Es decir: lo que ya esta vinculado se **recicla** (se deshace y se vuelve a
hacer), no se deja como esta.

La unidad de trabajo es (cedula, materia) -- CORREGIDO el 03/09/2026
-------------------------------------------------------------------
    Por la 07 unicamente se debe procesar, por estudiante, el codigo de la
    materia que registre en el reporte. No otro, no todos, no algunos:
    unicamente el que registre en el reporte.
        -- dueno del proceso, 03/09/2026

Hasta esa fecha este modulo decia lo contrario: que la accion era "por
estudiante, no por materia", que alcanzaba todas las asignaturas del periodo de
golpe, y que por tanto bastaba UNA materia vinculada para reciclar al estudiante
completo. Venia de `references/vinculacion-moodle.md` y **era falso**. El
03/09/2026, en 5 estudiantes, eso desvinculo y revinculo **34 asignaturas
cuando correspondian 5**. La referencia ya esta corregida en su origen.

Lo que si esta medido: **sin acotar** la grilla, la accion alcanza todas las
asignaturas (1000000102 paso de 0 de 8 a 8 de 8 con una sola ejecucion). De ahi
que acotar Grupos por COD_MATERIA antes de ejecutar no sea cosmetico: es lo que
confina la accion. Y como que el filtro la confina de verdad lo afirma el dueno
del proceso pero NO esta verificado contra el sistema, cada escritura va seguida
de `_exigir_sin_desborde`, que relee la grilla completa y detiene todo si alguna
otra asignatura cambio. Sin esa guarda el codigo *pareceria* trabajar por
materia y seguiria haciendo el mismo dano, ahora invisible.

**El reciclado abre una ventana de riesgo.** Entre el desvincular y el vincular
el estudiante queda SIN vincular. Si el proceso se corta ahi (timeout, caida,
parada manual), el estudiante acaba peor que al empezar. De ahi:

- Se anota en `logs/ciclos_abiertos.jsonl` ANTES de desvincular y se cierra el
  apunte tras vincular. Un apunte sin cerrar es una materia que hay que revisar
  a mano, y sobrevive a que el proceso muera. El apunte lleva la materia: un
  ciclo abierto es de (cedula, materia), no del estudiante entero.
- El vincular posterior se reintenta antes de rendirse.
- Al terminar, el CLI enumera los ciclos que quedaron abiertos.

El check se confirma releyendo, no por el dialogo (03/09/2026)
--------------------------------------------------------------
Aclaracion del dueno del proceso: tras desvincular hay que **esperar la
confirmacion de la desvinculacion**, y tras vincular la del vinculado, antes de
pasar al siguiente estudiante.

El dialogo "Proceso terminado" de ISEF07 NO sirve para eso: dice que el proceso
corrio, no que la materia quedara vinculada. Asi que tras cada accion se vuelve
a leer la fila de ESA materia y se mira su check.

Y se **sondea**, no se lee una vez. Medido el 03/09/2026 con 1000000102 (2026C):
una lectura a los 17 s del dialogo dio la materia como no vinculada, y mas tarde
el check estaba puesto. Esa lectura unica produjo un falso negativo, dos
reintentos inutiles de 90 s y la conclusion equivocada de que el estudiante
habia perdido un vinculo.

De ahi salen tres desenlaces que antes no existian:

- **`AccionSeDesbordo`**: la accion toco otras asignaturas del estudiante. Es la
  guarda de arriba disparandose, y detiene TODA la corrida: significa que acotar
  la grilla no confina nada y que el supuesto central del modulo es falso.
- **`reciclado_incompleto`**: el desvincular no se reflejo. No es dano -- la
  materia sigue vinculada, que es el estado que se busca -- pero el reciclado no
  cumplio su proposito. Se avisa y se sigue: el vincular es idempotente.
- **`CheckNoConfirmado`**: se ejecuto el vincular y el check no aparecio, o
  ISEF07 no dejo ni lanzar la accion. Es el caso que el proceso resuelve
  abriendo **ISEF05 y PACF50** para validar el check en Moodle y anotando el
  resultado en el Sheet del dia. Queda apuntado en
  `logs/escalado_isef05_pacf50.jsonl`.

Un fallo de LECTURA no abre un ciclo. Se separa a proposito: el 01/09/2026 una
alarma falsa dijo que un estudiante podia estar desvinculado y sus 7 asignaturas
estaban intactas, y una alarma falsa en el unico aviso que de verdad importa es
peor que no tenerlo.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
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
    INTENTOS_HASTA_ESCALAR,
    MODULOS_DE_ESCALADO,
    SEG_EJECUCION_VINCULACION,
    TIMEOUT_EJECUCION_ISEF07_SEG,
    TIMEOUT_OPERACION_SINU_SEG,
    VERIFICAR_CHECK_VINCULADO,
)
from .lector_sinu import clic_smartclient
from .restricciones_sinu import exigir_modulo_escribible

log = logging.getLogger(__name__)

#: Registro persistente de ciclos desvincular->vincular a medio hacer.
RUTA_CICLOS_ABIERTOS = DIR_LOGS / "ciclos_abiertos.jsonl"

#: Reintentos del vincular que cierra un ciclo. Mas alto que en el resto del
#: proyecto a proposito: si esto falla, un estudiante queda desvinculado.
#: Es el mismo numero que `INTENTOS_HASTA_ESCALAR`, y no por casualidad: agotar
#: los intentos de vincular ES lo que manda el caso a ISEF05/PACF50.
REINTENTOS_VINCULAR_TRAS_DESVINCULAR = INTENTOS_HASTA_ESCALAR

#: Casos que hay que confirmar en ISEF05 y PACF50 y anotar en el Sheet. Se
#: escribe en disco por el mismo motivo que `ciclos_abiertos.jsonl`: tiene que
#: sobrevivir a que el proceso muera.
RUTA_ESCALADO = DIR_LOGS / "escalado_isef05_pacf50.jsonl"

#: ISEF07 ejecuto el vincular y el check "Vinculado?" no aparecio.
MOTIVO_SIN_CHECK = "vinculado-sin-check"

#: No se pudo releer la grilla, asi que no se sabe si el check esta o no.
MOTIVO_NO_VERIFICABLE = "check-no-verificable"

#: ISEF07 no dejo ni lanzar la accion.
MOTIVO_NO_PERMITE_VINCULAR = "isef07-no-permite-vincular"

#: Cuanto se sondea el check antes de darlo por ausente. MEDIDO el 03/09/2026:
#: una lectura a los 17 s del dialogo dio un falso negativo y el check aparecio
#: despues. Esperar de mas no cuesta nada -- si el check aparece antes, el
#: sondeo termina antes -- y un falso negativo cuesta 90 s de reintento inutil.
SEG_SONDEO_CHECK = 90

#: Pausa entre lecturas del sondeo. Cada lectura de la grilla cuesta ~15 s por
#: si misma, asi que no hace falta mas.
SEG_ENTRE_SONDEOS = 5

#: Tras cada escritura, releer la grilla COMPLETA y exigir que ninguna otra
#: asignatura haya cambiado.
#:
#: Existe porque el supuesto central del modulo no esta verificado: que acotar
#: Grupos por COD_MATERIA confine la accion lo afirma el dueno del proceso, pero
#: nadie lo ha comprobado contra el sistema. Lo que SI esta medido es que sin
#: acotar la accion alcanza todas las asignaturas.
#:
#: Cuesta una lectura de grilla (~15 s) por escritura. Se puede poner en False
#: cuando el confinamiento este confirmado en una corrida supervisada -- y no
#: antes: sin esta guarda, si el filtro no confinara nada, el codigo pareceria
#: trabajar por materia y haria el mismo dano de forma invisible.
COMPROBAR_DESBORDE = True


class TipoSecuencia(Enum):
    """Que hay que ejecutar sobre LA materia del reporte."""

    SOLO_VINCULAR = "vincular"
    """La materia no tenia el check "Vinculado?"."""

    RECICLAR = "desvincular+vincular"
    """La materia ya tenia el check: se deshace y se vuelve a hacer."""

    NADA = "nada"
    """La materia del reporte no aparece en la grilla del estudiante."""


class ErrorEjecucionSinu(RuntimeError):
    """La ejecucion en ISEF07 no se pudo completar."""


class CicloAbierto(ErrorEjecucionSinu):
    """Se desvinculo y no se pudo volver a vincular.

    Es el peor resultado posible de esta etapa: el estudiante queda desvinculado.
    Se distingue del resto de errores para que nunca se trate como un fallo mas.
    """


class CheckNoConfirmado(ErrorEjecucionSinu):
    """La accion corrio pero el check "Vinculado?" no quedo como debia.

    No es un fallo tecnico ni un ciclo abierto: es el caso que el dueno del
    proceso resuelve a mano abriendo ISEF05 y PACF50 para validar el check en
    Moodle, y anotando el resultado en el Sheet del dia. Se distingue del resto
    para que el CLI lo liste aparte y la corrida siga con los demas estudiantes.
    """


class AccionSeDesbordo(ErrorEjecucionSinu):
    """La accion cambio asignaturas fuera de la materia acotada.

    Es la guarda de `_exigir_sin_desborde`. No es un fallo recuperable: si el
    filtro de COD_MATERIA no confina la accion de ISEF07, entonces no hay forma
    de cumplir la regla del proceso con esta pantalla, y seguir procesando
    tocaria materias fuera del reporte en cada estudiante. El CLI detiene TODA
    la corrida al verla.
    """


@dataclass
class ResultadoEjecucion:
    """Lo que se hizo con UNA materia de un estudiante."""

    identificacion: str
    cod_periodo: str
    secuencia: TipoSecuencia

    cod_materia: str = ""
    num_grupo: str = ""
    """La materia del reporte sobre la que se actuo. La unidad de trabajo."""

    acciones_ejecutadas: list[str] = field(default_factory=list)
    simulado: bool = False
    segundos: float = 0.0
    ciclo_abierto: bool = False
    detalle: str = ""

    total_materias: int = 0
    vinculadas_antes: int = 0
    vinculadas_despues: int = 0
    """Contados releyendo la grilla, no deducidos del dialogo de fin."""

    materias_sin_check: list[str] = field(default_factory=list)
    """Asignaturas (COD/GRUPO) que quedaron sin el check "Vinculado?"."""

    requiere_escalado: bool = False
    """True si hay que confirmar el check en ISEF05/PACF50 y anotarlo en el Sheet."""

    reciclado_incompleto: bool = False
    """El desvincular no se reflejo en la grilla. No hay dano -- el estudiante
    sigue vinculado -- pero el reciclado no cumplio su proposito."""


# ---------------------------------------------------------------------------
# Decision (funcion pura, probada sin navegador)
# ---------------------------------------------------------------------------


def fila_de_materia(
    grupos: list[FilaGrupoSinu], cod_materia: str, num_grupo: str = ""
) -> FilaGrupoSinu | None:
    """La fila de UNA materia dentro de la grilla leida, o None si no esta.

    El grupo desempata: un estudiante puede tener la misma materia en dos
    grupos. Si se pasa vacio, basta con que coincida el codigo -- pero entonces
    se exige que no haya ambiguedad, porque elegir la fila equivocada es
    ejecutar sobre la matricula equivocada.
    """
    cod = (cod_materia or "").strip().upper()
    grupo = (num_grupo or "").strip()
    candidatas = [g for g in grupos if (g.cod_materia or "").strip().upper() == cod]
    if grupo:
        exactas = [g for g in candidatas if (g.num_grupo or "").strip() == grupo]
        if exactas:
            return exactas[0]
        # El codigo esta pero el grupo no: no se sustituye por otra fila.
        return None
    if len(candidatas) == 1:
        return candidatas[0]
    return None


def decidir_secuencia(fila: FilaGrupoSinu | None) -> TipoSecuencia:
    """Aplica la regla de negocio a UNA materia: la que registra el reporte.

    Regla del dueno del proceso (03/09/2026):

    > Por la 07 unicamente se debe procesar, por estudiante, el codigo de la
    > materia que registre en el reporte. No otro, no todos, no algunos.

    Antes esta funcion recibia TODAS las asignaturas del estudiante y reciclaba
    el estudiante completo si alguna estaba vinculada. Esa premisa venia de
    `references/vinculacion-moodle.md`, era falsa, y el 03/09/2026 hizo que se
    desvincularan y revincularan 34 asignaturas cuando correspondian 5. La
    referencia ya esta corregida en su origen; no volver a reintroducirlo.
    """
    if fila is None:
        return TipoSecuencia.NADA
    if fila.vinculado:
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


def _apuntar_ciclo(
    identificacion: str, cod_periodo: str, estado: str, materia: str = ""
) -> None:
    """Anota en disco el estado de un ciclo. Debe sobrevivir a que el proceso muera.

    La `materia` entra en la clave: desde el 03/09/2026 un ciclo es de
    (cedula, periodo, materia), no del estudiante entero. Sin ella, reciclar dos
    materias del mismo estudiante hacia que el cierre de la primera borrara el
    apunte abierto de la segunda -- y esa segunda es justo la que podia haber
    quedado desvinculada.
    """
    RUTA_CICLOS_ABIERTOS.parent.mkdir(parents=True, exist_ok=True)
    apunte = {
        "momento": datetime.now().isoformat(timespec="seconds"),
        "identificacion": identificacion,
        "cod_periodo": cod_periodo,
        "materia": materia,
        "estado": estado,
    }
    with RUTA_CICLOS_ABIERTOS.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(apunte, ensure_ascii=False) + "\n")
        fh.flush()


def _apuntar_escalado(
    identificacion: str,
    cod_periodo: str,
    motivo: str,
    materias: list[str],
) -> None:
    """Anota un caso que hay que confirmar en ISEF05/PACF50 y llevar al Sheet."""
    RUTA_ESCALADO.parent.mkdir(parents=True, exist_ok=True)
    apunte = {
        "momento": datetime.now().isoformat(timespec="seconds"),
        "identificacion": identificacion,
        "cod_periodo": cod_periodo,
        "motivo": motivo,
        "materias_sin_check": materias,
        "modulos_a_consultar": list(MODULOS_DE_ESCALADO),
        "resuelto": False,
    }
    with RUTA_ESCALADO.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(apunte, ensure_ascii=False) + "\n")
        fh.flush()


def escalados_pendientes() -> list[dict]:
    """Casos anotados para ISEF05/PACF50 que nadie ha marcado como resueltos."""
    if not RUTA_ESCALADO.is_file():
        return []
    pendientes = []
    for linea in RUTA_ESCALADO.read_text(encoding="utf-8").splitlines():
        if not linea.strip():
            continue
        try:
            apunte = json.loads(linea)
        except ValueError:
            continue
        if not apunte.get("resuelto"):
            pendientes.append(apunte)
    return pendientes


def materias_sin_check(grupos: list[FilaGrupoSinu]) -> list[str]:
    """Las asignaturas que NO tienen el check "Vinculado?", por COD/GRUPO."""
    return [g.shortname for g in grupos if not g.vinculado]


def ciclos_abiertos() -> list[dict]:
    """Ciclos que se abrieron y no se cerraron: materias a revisar a mano.

    La clave incluye la materia. Los apuntes viejos (sin ella) siguen leyendose:
    su materia vacia forma su propia clave, asi que un `cerrado` antiguo cierra
    lo que abrio un `desvinculando` antiguo, como siempre.
    """
    if not RUTA_CICLOS_ABIERTOS.is_file():
        return []

    estado: dict[tuple[str, str, str], dict] = {}
    for linea in RUTA_CICLOS_ABIERTOS.read_text(encoding="utf-8").splitlines():
        if not linea.strip():
            continue
        try:
            apunte = json.loads(linea)
        except ValueError:
            continue
        clave = (
            apunte.get("identificacion", ""),
            apunte.get("cod_periodo", ""),
            apunte.get("materia", ""),
        )
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
# Confirmacion del check (lo que el dialogo de fin NO dice)
# ---------------------------------------------------------------------------
# "Proceso terminado" confirma que el proceso CORRIO. Que la materia quedara
# vinculada es otra cosa, y es la que importa. Por eso tras cada accion se
# vuelve a leer la fila de ESA materia y se mira su check.
#
# Y se SONDEA, no se lee una vez. Medido el 03/09/2026 con 1000000102 (2026C):
# una lectura a los 17 s del dialogo dio la materia como no vinculada, y al
# volver a mirarla mas tarde el check estaba puesto. Esa lectura unica produjo
# un falso negativo, dos reintentos inutiles de 90 s y la conclusion equivocada
# de que el estudiante habia perdido un vinculo.


def _estado_de(grupos: list[FilaGrupoSinu]) -> dict[str, bool]:
    """{COD/GRUPO: vinculado}, para comparar dos lecturas de la misma grilla."""
    return {g.shortname: g.vinculado for g in grupos}


def _sondear_check(
    page: Page,
    releer_materia: Callable[[], list[FilaGrupoSinu]],
    *,
    cod_materia: str,
    num_grupo: str,
    esperado: bool,
    identificacion: str,
    cod_periodo: str,
) -> tuple[FilaGrupoSinu | None, bool]:
    """Relee la fila de la materia hasta que su check valga `esperado`.

    Devuelve (fila, confirmado). `confirmado` False significa que el plazo se
    agoto con el check en el estado contrario -- no que no se pudiera leer.

    Raises:
        ErrorEjecucionSinu: si la grilla no se pudo releer. No poder comprobar
            NO es lo mismo que estar bien, asi que nunca se devuelve
            "confirmado" por defecto.
    """
    limite = time.monotonic() + SEG_SONDEO_CHECK
    fila: FilaGrupoSinu | None = None
    intentos = 0
    while True:
        try:
            filas = releer_materia()
        except Exception as exc:  # noqa: BLE001 - cualquier fallo deja el estado sin verificar
            raise ErrorEjecucionSinu(
                f"No se pudo releer la materia {cod_materia} de {identificacion} "
                f"({cod_periodo}) para confirmar el check: {exc}"
            ) from exc

        intentos += 1
        fila = fila_de_materia(filas, cod_materia, num_grupo)
        if fila is not None and fila.vinculado is esperado:
            log.info(
                "%s / %s: check '%s' confirmado tras %d lectura(s).",
                identificacion,
                cod_materia,
                "vinculado" if esperado else "sin vincular",
                intentos,
            )
            return fila, True

        if time.monotonic() >= limite:
            return fila, False

        page.wait_for_timeout(_ms(SEG_ENTRE_SONDEOS))


def _exigir_sin_desborde(
    releer_todas: Callable[[], list[FilaGrupoSinu]],
    antes: dict[str, bool],
    *,
    cod_materia: str,
    num_grupo: str,
    identificacion: str,
    cod_periodo: str,
) -> None:
    """Comprueba que la accion NO toco ninguna otra asignatura del estudiante.

    Es la guarda del supuesto central de este modulo: que acotar la grilla
    Grupos por COD_MATERIA confina la accion a esa fila. El dueno del proceso
    lo afirma, pero **no esta verificado contra el sistema**: lo que si esta
    medido (03/09/2026) es que SIN acotar la accion alcanza todas las
    asignaturas -- 1000000102 paso de 0 de 8 a 8 de 8 con una sola ejecucion.

    Si el filtro no confinara nada, sin esta comprobacion el codigo *pareceria*
    trabajar por materia y seguiria reciclando el estudiante entero, que es peor
    que el estado anterior: el mismo dano, ahora invisible.

    Raises:
        AccionSeDesbordo: si alguna otra asignatura cambio de estado.
        ErrorEjecucionSinu: si no se pudo releer la grilla completa.
    """
    if not COMPROBAR_DESBORDE:
        return

    objetivo = f"{cod_materia}/{num_grupo}" if num_grupo else cod_materia
    try:
        despues = _estado_de(releer_todas())
    except Exception as exc:  # noqa: BLE001
        raise ErrorEjecucionSinu(
            f"No se pudo releer la grilla completa de {identificacion} "
            f"({cod_periodo}) para comprobar que la accion no se desbordo: {exc}"
        ) from exc

    cambiadas = [
        f"{clave}: {antes[clave]} -> {despues[clave]}"
        for clave in sorted(set(antes) & set(despues))
        if antes[clave] != despues[clave] and clave != objetivo
    ]
    if cambiadas:
        raise AccionSeDesbordo(
            f"LA ACCION SE DESBORDO. Se acoto la grilla a {objetivo} para "
            f"{identificacion} ({cod_periodo}) y ademas cambiaron "
            f"{len(cambiadas)} asignaturas que NADIE pidio tocar: "
            f"{'; '.join(cambiadas[:6])}. Es decir: el filtro de COD_MATERIA no "
            f"confina la accion de ISEF07. Se detiene TODO -- seguir procesaria "
            f"materias fuera del reporte en cada estudiante."
        )
    log.info(
        "%s / %s: sin desborde, ninguna otra asignatura cambio.",
        identificacion,
        objetivo,
    )


def _vincular_hasta_confirmar(
    page: Page,
    cfg: Config,
    *,
    releer_materia: Callable[[], list[FilaGrupoSinu]],
    cod_materia: str,
    num_grupo: str,
    identificacion: str,
    cod_periodo: str,
    resultado: ResultadoEjecucion,
) -> bool:
    """Vincula la materia y sondea su check, reintentando. True si quedo puesto.

    False significa que ISEF07 ejecuto el vincular y el check no aparecio: el
    caso que se escala a ISEF05/PACF50.

    Raises:
        ErrorEjecucionSinu: si ni un solo intento llego a ejecutarse, o si la
            grilla no se pudo releer.
    """
    ultimo: Exception | None = None

    for intento in range(1, INTENTOS_HASTA_ESCALAR + 1):
        try:
            _ejecutar_una(page, cfg, sesc.OPCION_VINCULAR)
            resultado.acciones_ejecutadas.append(sesc.OPCION_VINCULAR)
        except ErrorEjecucionSinu as exc:
            ultimo = exc
            log.error(
                "Fallo el vincular de %s / %s (%d/%d): %s",
                identificacion,
                cod_materia,
                intento,
                INTENTOS_HASTA_ESCALAR,
                exc,
            )
            page.wait_for_timeout(_ms(SEG_ENTRE_SONDEOS))
            continue

        if not VERIFICAR_CHECK_VINCULADO:
            return True

        _, confirmado = _sondear_check(
            page,
            releer_materia,
            cod_materia=cod_materia,
            num_grupo=num_grupo,
            esperado=True,
            identificacion=identificacion,
            cod_periodo=cod_periodo,
        )
        if confirmado:
            resultado.vinculadas_despues = 1
            return True

        log.error(
            "%s / %s: se ejecuto el vincular y el check sigue SIN aparecer tras "
            "%ss de sondeo (intento %d/%d).",
            identificacion,
            cod_materia,
            SEG_SONDEO_CHECK,
            intento,
            INTENTOS_HASTA_ESCALAR,
        )

    if ultimo is not None and not resultado.acciones_ejecutadas:
        # Nunca se llego a ejecutar nada, asi que no hay nada que comprobar.
        raise ultimo
    return False


# ---------------------------------------------------------------------------
# Orquestacion: UNA materia de UN estudiante
# ---------------------------------------------------------------------------


def ejecutar_materia(
    page: Page,
    cfg: Config,
    *,
    identificacion: str,
    cod_periodo: str,
    cod_materia: str,
    num_grupo: str = "",
    grupos: list[FilaGrupoSinu],
    releer_materia: Callable[[], list[FilaGrupoSinu]],
    releer_todas: Callable[[], list[FilaGrupoSinu]],
) -> ResultadoEjecucion:
    """Procesa **una** materia de un estudiante ya seleccionado en ISEF07.

    La unidad de trabajo es (cedula, materia), la que registra el reporte. Ni
    todas las asignaturas del estudiante ni ninguna otra: ver
    `decidir_secuencia` y la correccion del 03/09/2026 en
    `references/vinculacion-moodle.md`.

    Con `MODO_SIMULACION=true` no se toca nada: solo se informa de que se haria.

    Args:
        grupos: TODAS las asignaturas del estudiante, leidas antes de actuar. De
            aqui sale la fila de la materia y la foto contra la que se comprueba
            que la accion no se desbordo.
        releer_materia: relee la grilla **ya acotada** a `cod_materia`.
        releer_todas: relee la grilla **sin filtro**, para la guarda de desborde.

    Raises:
        AccionSeDesbordo: la accion toco otras asignaturas. Se detiene todo.
        CicloAbierto: se desvinculo y no se pudo volver a vincular.
        CheckNoConfirmado: se ejecuto el vincular y el check no aparecio, o
            ISEF07 no dejo vincular. Va a ISEF05/PACF50 y al Sheet.
        ErrorEjecucionSinu: cualquier otro fallo.
    """
    inicio = time.monotonic()
    objetivo = f"{cod_materia}/{num_grupo}" if num_grupo else cod_materia
    fila = fila_de_materia(grupos, cod_materia, num_grupo)
    secuencia = decidir_secuencia(fila)

    resultado = ResultadoEjecucion(
        identificacion=identificacion, cod_periodo=cod_periodo, secuencia=secuencia
    )
    resultado.cod_materia = cod_materia
    resultado.num_grupo = num_grupo
    resultado.total_materias = 1
    resultado.vinculadas_antes = 1 if (fila is not None and fila.vinculado) else 0

    if fila is None:
        # La materia del reporte no esta en la grilla del estudiante. No se
        # inventa nada: se para y se avisa, como con el estudiante ambiguo.
        resultado.detalle = (
            f"La materia {objetivo} que pide el reporte no aparece entre las "
            f"{len(grupos)} asignaturas de {identificacion} en {cod_periodo}. "
            "No se ejecuta nada."
        )
        log.error("%s", resultado.detalle)
        return resultado

    log.info(
        "%s / %s (%s): vinculado=%s -> %s",
        identificacion,
        objetivo,
        cod_periodo,
        fila.vinculado,
        secuencia.value,
    )

    if cfg.modo_simulacion:
        resultado.simulado = True
        resultado.acciones_ejecutadas = list(acciones_de(secuencia))
        resultado.detalle = (
            f"MODO_SIMULACION=true: no se ejecuto nada sobre {objetivo}. Se "
            "habria hecho " + " -> ".join(acciones_de(secuencia))
        )
        log.warning("[SIMULACION] %s", resultado.detalle)
        return resultado

    antes = _estado_de(grupos)

    if secuencia is TipoSecuencia.SOLO_VINCULAR:
        try:
            confirmado = _vincular_hasta_confirmar(
                page,
                cfg,
                releer_materia=releer_materia,
                cod_materia=cod_materia,
                num_grupo=num_grupo,
                identificacion=identificacion,
                cod_periodo=cod_periodo,
                resultado=resultado,
            )
        except AccionNoSeleccionada as exc:
            _apuntar_escalado(
                identificacion, cod_periodo, MOTIVO_NO_PERMITE_VINCULAR, [objetivo]
            )
            resultado.requiere_escalado = True
            raise CheckNoConfirmado(
                f"{identificacion} / {objetivo} ({cod_periodo}): ISEF07 no permitio "
                f"vincular ({exc}). Validar el check en "
                f"{'/'.join(MODULOS_DE_ESCALADO).upper()} y anotarlo en el Sheet."
            ) from exc

        _exigir_sin_desborde(
            releer_todas,
            antes,
            cod_materia=cod_materia,
            num_grupo=num_grupo,
            identificacion=identificacion,
            cod_periodo=cod_periodo,
        )
        resultado.segundos = round(time.monotonic() - inicio, 1)

        if not confirmado:
            resultado.materias_sin_check = [objetivo]
            resultado.requiere_escalado = True
            _apuntar_escalado(
                identificacion, cod_periodo, MOTIVO_SIN_CHECK, [objetivo]
            )
            raise CheckNoConfirmado(
                f"{identificacion} / {objetivo} ({cod_periodo}): se vinculo y el "
                f"check 'Vinculado?' no aparecio. Validar el check en "
                f"{'/'.join(MODULOS_DE_ESCALADO).upper()} y anotarlo en el Sheet."
            )
        return resultado

    # --- Reciclado de UNA materia: aqui esta la ventana de riesgo ---
    try:
        _ejecutar_una(
            page,
            cfg,
            sesc.OPCION_DESVINCULAR,
            antes_de_ejecutar=lambda: _apuntar_ciclo(
                identificacion, cod_periodo, "desvinculando", objetivo
            ),
        )
        resultado.acciones_ejecutadas.append(sesc.OPCION_DESVINCULAR)
    except AccionNoSeleccionada:
        raise
    except ErrorEjecucionSinu:
        resultado.ciclo_abierto = True
        raise

    # La comprobacion de desborde va AQUI, tras la primera escritura: si el
    # filtro no confina la accion, hay que enterarse antes de tocar a nadie mas.
    _exigir_sin_desborde(
        releer_todas,
        antes,
        cod_materia=cod_materia,
        num_grupo=num_grupo,
        identificacion=identificacion,
        cod_periodo=cod_periodo,
    )

    # Confirmar la DESVINCULACION antes de volver a vincular, como pide el
    # proceso. Un fallo aqui NO aborta: si no se refleja, la materia sigue
    # vinculada -- el estado que se busca -- y el vincular de abajo es
    # idempotente. Abortar dejaria el ciclo abierto por un problema de lectura.
    if VERIFICAR_CHECK_VINCULADO:
        try:
            _, desvinculada = _sondear_check(
                page,
                releer_materia,
                cod_materia=cod_materia,
                num_grupo=num_grupo,
                esperado=False,
                identificacion=identificacion,
                cod_periodo=cod_periodo,
            )
        except ErrorEjecucionSinu as exc:
            log.warning(
                "%s / %s: no se pudo confirmar la desvinculacion (%s). Se sigue "
                "con el vincular, que es lo que deja la materia como debe estar.",
                identificacion,
                objetivo,
                exc,
            )
        else:
            if not desvinculada:
                resultado.reciclado_incompleto = True
                log.warning(
                    "%s / %s: el desvincular no se reflejo, el check sigue puesto. "
                    "El reciclado no cumplio su proposito, pero la materia NO "
                    "queda peor. Se vincula igualmente.",
                    identificacion,
                    objetivo,
                )

    _apuntar_ciclo(
        identificacion, cod_periodo, "desvinculado-pendiente-vincular", objetivo
    )

    try:
        confirmado = _vincular_hasta_confirmar(
            page,
            cfg,
            releer_materia=releer_materia,
            cod_materia=cod_materia,
            num_grupo=num_grupo,
            identificacion=identificacion,
            cod_periodo=cod_periodo,
            resultado=resultado,
        )
    except ErrorEjecucionSinu as exc:
        resultado.ciclo_abierto = True
        resultado.requiere_escalado = True
        _apuntar_escalado(
            identificacion, cod_periodo, MOTIVO_NO_VERIFICABLE, [objetivo]
        )
        raise CicloAbierto(
            f"{identificacion} / {objetivo} ({cod_periodo}) PUEDE HABER QUEDADO "
            f"DESVINCULADA: se desvinculo y el vincular no se pudo completar ni "
            f"confirmar en {INTENTOS_HASTA_ESCALAR} intentos. Ultimo error: {exc}. "
            f"Hay que vincularla A MANO en ISEF07. Apuntado en "
            f"{RUTA_CICLOS_ABIERTOS}."
        ) from exc

    _exigir_sin_desborde(
        releer_todas,
        antes,
        cod_materia=cod_materia,
        num_grupo=num_grupo,
        identificacion=identificacion,
        cod_periodo=cod_periodo,
    )

    if not confirmado:
        # Se desvinculo y no se logro devolver el check: la materia esta PEOR
        # que al empezar (venia vinculada). El ciclo se queda abierto.
        resultado.ciclo_abierto = True
        resultado.materias_sin_check = [objetivo]
        resultado.requiere_escalado = True
        _apuntar_escalado(identificacion, cod_periodo, MOTIVO_SIN_CHECK, [objetivo])
        raise CicloAbierto(
            f"{identificacion} / {objetivo} ({cod_periodo}) QUEDO DESVINCULADA: "
            f"venia con check, se reciclo y el check no volvio tras "
            f"{INTENTOS_HASTA_ESCALAR} intentos. Hay que vincularla A MANO en "
            f"ISEF07 y validar el check en "
            f"{'/'.join(MODULOS_DE_ESCALADO).upper()}. Apuntado en "
            f"{RUTA_CICLOS_ABIERTOS}."
        )

    _apuntar_ciclo(identificacion, cod_periodo, "cerrado", objetivo)
    resultado.segundos = round(time.monotonic() - inicio, 1)
    return resultado
