"""Consulta en ISEF05 si un grupo tiene curso creado en MOODLE.

Por que existe
--------------
Cuando ISEF07 ejecuta el vincular y el check "Vinculado?" no aparece, hasta
ahora el caso se anotaba para que una persona lo validara en ISEF05/PACF50. Eso
dejaba dos problemas:

  - El mismo grupo se reintentaba entero cada dia. `DTA32/55598` (26V05) fallo
    con sus cuatro estudiantes el 07, el 15 y el 16/09/2026: tres dias
    repitiendo, a ~360 s por estudiante, unos 24 minutos por corrida.
  - Cada estudiante recibia tres clics de "Vincular grupos matriculados" contra
    un grupo en el que vincular es imposible.

Medido en produccion el 16/09/2026, este es el dato que lo explica:

    26V05 DTA32 RESPONSABILIDAD SOCIAL EMPRESARIAL grupo 55598
      Cursos en moodle?  no     Usuarios en moodle?       no
      Vinculacion?       no     Curso Semilla en moodle?  no

    26V05 AED31 GESTION LOGISTICA grupo 55522   (verde ese mismo dia)
      Cursos en moodle?  SI     Usuarios en moodle?       SI
      Vinculacion?       SI     Curso Semilla en moodle?  SI

Sin curso en MOODLE no hay nada a lo que vincular, asi que el check no puede
aparecer por mucho que se reintente. La columna distingue los dos casos de
forma limpia, y responde en unos segundos.

Cuidado con este modulo
-----------------------
ISEF05 es "Integracion Masiva con MOODLE": su pantalla lleva un desplegable
'Actividad' y una casilla **'Borra la actividad seleccionada en MOODLE?'**, es
decir que desde ahi se pueden borrar cursos en bloque. Aqui solo se escribe en
las cajas de filtro de dos columnas y se mueve el scroll. No se selecciona
ninguna fila, no se toca el desplegable y no se pulsa ningun boton.
`restricciones_sinu` mantiene isef05 fuera de MODULOS_ESCRIBIBLES, asi que
cualquier intento de accion abortaria igualmente.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from playwright.sync_api import (
    Error as ErrorPlaywright,
    Page,
    TimeoutError as ErrorTiempoPlaywright,
)

from .config import Config
from .constantes_sinu import ACTIVIDAD_INTEGRACION_MASIVA
from .lector_sinu import (
    TOLERANCIA_FILA_PX,
    ErrorLecturaSinu,
    entrar_en_modulo,
    esperar_grilla_cargada,
    esperar_sin_cargas,
    fijar_periodo,
    # Internos del paquete, compartidos a proposito: la rejilla de ISEF05 esta
    # hecha con el mismo SmartClient que la de ISEF07, asi que el motor de
    # lectura por geometria es el mismo. Duplicarlo seria mantener dos copias
    # del unico codigo que sabe interpretar estas pantallas.
    _GUION_GRUPOS,
    _en_columna,
    _texto_en,
)
from . import selectores_sinu as sel
from .restricciones_sinu import exigir_modulo_legible

log = logging.getLogger(__name__)

#: Columnas de la rejilla "Grupos" de ISEF05, leidas de la pantalla real el
#: 16/09/2026. Las cuatro primeras son los checks; las dos ultimas identifican
#: la fila y sirven para comprobar que se leyo la que se pidio.
COL_CURSO = "Cursos en moodle?"
COL_USUARIOS = "Usuarios en moodle?"
COL_VINCULACION = "Vinculación en moodle?"
COL_SEMILLA = "Curso Semilla en moodle?"
COL_ASIGNATURA = "Código asignatura"
COL_GRUPO = "Grupo"

COLUMNAS: tuple[str, ...] = (
    COL_CURSO,
    COL_USUARIOS,
    COL_VINCULACION,
    COL_SEMILLA,
    COL_ASIGNATURA,
    COL_GRUPO,
)

#: Filtros de columna. Mismos nombres que en ISEF07, comprobado el 16/09/2026.
CSS_FILTRO_GRUPO = 'input[name="num_grupo"]'

#: Los cinco nombres de gif que el guion debe recoger. Es la MISMA lista que
#: usa `leer_filas_grupos` para ISEF07, y tiene que seguir siendolo: si SINU
#: introdujera un sexto estado, dejarlo fuera aqui haria que la columna se
#: leyera como ausente en vez de como ilegible.
ESTADOS_DE_CHECK: tuple[str, ...] = (
    sel.IMG_CHECK_MARCADO,
    sel.IMG_CHECK_DESMARCADO,
    sel.IMG_CHECK_MARCADO_BLOQUEADO,
    sel.IMG_CHECK_DESMARCADO_BLOQUEADO,
    sel.IMG_CHECK_SIN_DEFINIR,
)


class ErrorConsultaIsef05(ErrorLecturaSinu):
    """No se pudo averiguar el estado del grupo en ISEF05."""


@dataclass(frozen=True)
class GrupoEnMoodle:
    """Lo que ISEF05 dice de un grupo.

    Cada check es `True` (marcado), `False` (desmarcado) o `None` (ilegible).
    `None` NO se trata como `False` en ninguna decision: no saber y saber que no
    son cosas distintas, y confundirlas marcaria en rojo sin fundamento.
    """

    cod_periodo: str
    cod_materia: str
    num_grupo: str
    curso: bool | None
    usuarios: bool | None
    vinculacion: bool | None
    semilla: bool | None
    crudo: str = ""

    @property
    def objetivo(self) -> str:
        return f"{self.cod_materia}/{self.num_grupo}"

    @property
    def vincular_es_imposible(self) -> bool:
        """True solo si consta que el grupo NO tiene curso en MOODLE.

        Es la unica pregunta que decide saltar unidades, y por eso se responde
        con `is False` y no con `not curso`: con el check ilegible (`None`) la
        respuesta tiene que ser "no lo se", que aqui significa seguir
        procesando como hasta ahora.
        """
        return self.curso is False

    def resumen(self) -> str:
        def _m(v: bool | None) -> str:
            return {True: "si", False: "NO", None: "ilegible"}[v]

        return (
            f"{self.cod_periodo} {self.objetivo}: curso={_m(self.curso)} "
            f"usuarios={_m(self.usuarios)} vinculacion={_m(self.vinculacion)} "
            f"semilla={_m(self.semilla)}"
        )


def _devolver_scroll_al_origen(page: Page) -> int:
    """Devuelve las rejillas al extremo izquierdo. Devuelve cuantas movio.

    Hace falta y no es cosmetico: al filtrar por una columna, SmartClient
    desplaza la rejilla a la derecha para ensenarla, y las columnas de MOODLE
    se van fuera de la pantalla. Leyendo asi, el 16/09/2026 la sonda devolvio
    los checks de otras celdas -- con una fila que no existia.
    """
    return page.evaluate(
        """
        () => {
          let n = 0;
          for (const el of document.querySelectorAll('*')) {
            if (el.scrollWidth > el.clientWidth + 4 && el.scrollLeft > 0) {
              el.scrollLeft = 0;
              n++;
            }
          }
          return n;
        }
        """
    )


def _filtrar(page: Page, cfg: Config, css: str, valor: str, que: str) -> None:
    """Escribe en una caja de filtro de columna.

    `fill` y no clic + teclado: la capa `screenSpan` de SmartClient intercepta
    los clics de puntero. Es la misma razon por la que `filtrar_grupos_por_materia`
    lo hace asi en ISEF07.
    """
    caja = page.locator(css).first
    try:
        caja.wait_for(state="visible", timeout=cfg.timeout_operacion_seg * 1000)
        caja.fill(valor)
    except (ErrorPlaywright, ErrorTiempoPlaywright) as exc:
        raise ErrorConsultaIsef05(
            f"No se pudo escribir {que} ('{valor}') en el filtro '{css}' de "
            f"ISEF05: {exc}"
        ) from exc


def consultar_grupo(
    page: Page,
    cfg: Config,
    *,
    cod_periodo: str,
    cod_materia: str,
    num_grupo: str,
) -> GrupoEnMoodle:
    """Dice si un grupo tiene curso en MOODLE, segun ISEF05.

    Deja la pantalla en ISEF05 y con el filtro puesto: quien llame decide si
    vuelve a ISEF07. Consultar varios grupos seguidos es barato porque el
    modulo y el periodo ya estan donde tienen que estar.

    Raises:
        ErrorRestriccionOperativa: si isef05 saliera de la lista de legibles.
        ErrorConsultaIsef05: si la rejilla no se deja leer, si no aparece el
            grupo, o si la fila que vuelve no es la que se pidio.
    """
    objetivo = f"{cod_materia}/{num_grupo}"
    exigir_modulo_legible(
        ACTIVIDAD_INTEGRACION_MASIVA, f"consultar el curso en MOODLE de {objetivo}"
    )
    entrar_en_modulo(
        page,
        cfg,
        ACTIVIDAD_INTEGRACION_MASIVA,
        f"consultar el curso en MOODLE de {objetivo}",
    )
    fijar_periodo(page, cfg, cod_periodo)

    _filtrar(page, cfg, sel.CSS_FILTRO_MATERIA, cod_materia, "la asignatura")
    _filtrar(page, cfg, CSS_FILTRO_GRUPO, num_grupo, "el grupo")
    page.locator(CSS_FILTRO_GRUPO).first.press("Enter")
    esperar_sin_cargas(page, cfg)

    pie = esperar_grilla_cargada(page, cfg)
    if pie is not None:
        log.info("ISEF05 acotado a %s: %s a %s de %s.", objetivo, *pie)

    estados, y = _esperar_la_fila(
        page, cfg, cod_materia=cod_materia, num_grupo=num_grupo, objetivo=objetivo
    )

    resultado = GrupoEnMoodle(
        cod_periodo=cod_periodo,
        cod_materia=cod_materia,
        num_grupo=num_grupo,
        curso=sel.estado_de_imagen(estados.get(COL_CURSO)),
        usuarios=sel.estado_de_imagen(estados.get(COL_USUARIOS)),
        vinculacion=sel.estado_de_imagen(estados.get(COL_VINCULACION)),
        semilla=sel.estado_de_imagen(estados.get(COL_SEMILLA)),
        crudo=f"y={round(y)} {estados}",
    )
    log.info("ISEF05 dice: %s", resultado.resumen())
    return resultado


def _esperar_la_fila(
    page: Page,
    cfg: Config,
    *,
    cod_materia: str,
    num_grupo: str,
    objetivo: str,
) -> tuple[dict[str, str], float]:
    """Espera a que la rejilla muestre LA fila pedida, y la devuelve.

    Se identifica la fila por su contenido -- la asignatura y el grupo que se
    preguntaron -- y no por su posicion. Eso resuelve de una vez los tres
    problemas que aparecieron probandolo el 16/09/2026:

      - El filtro tarda en aplicarse. La primera consulta leyo la rejilla sin
        acotar ('1 a 10 de 34828') porque `esperar_sin_cargas` ya habia
        devuelto el control. Aqui se reintenta hasta que aparece la fila.
      - Debajo de la rejilla hay dos checks sueltos -- uno es
        'Borra la actividad seleccionada en MOODLE?' -- que caen dentro de la
        banda horizontal de una columna y entraban como filas de datos.
      - El filtro de SmartClient es 'Contiene', asi que pedir el grupo 5559
        tambien traeria el 55598. Exigir la coincidencia exacta lo descarta.

    Raises:
        ErrorConsultaIsef05: si al agotarse el plazo no hay una fila que sea
            exactamente la pedida.
    """
    limite = time.monotonic() + cfg.timeout_render_seg
    visto: list[str] = []

    while True:
        _devolver_scroll_al_origen(page)
        datos = page.evaluate(
            _GUION_GRUPOS,
            {
                "columnas": list(COLUMNAS),
                "estados": list(ESTADOS_DE_CHECK),
                "cssFiltroMateria": sel.CSS_FILTRO_MATERIA,
            },
        )
        cab = datos["cab"]
        faltan = [c for c in (COL_CURSO, COL_ASIGNATURA, COL_GRUPO) if c not in cab]
        if faltan:
            raise ErrorConsultaIsef05(
                f"En ISEF05 no aparecieron las columnas {faltan} al consultar "
                f"{objetivo}. Puede que la rejilla no cargara, o que la "
                "pantalla cambiara: hay que volver a inspeccionarla."
            )

        y_filtro = datos.get("yFiltro")
        por_fila: dict[float, dict[str, str]] = {}
        for c in datos["checks"]:
            destino = next(
                (n for n, caja in cab.items() if _en_columna(c["x"], caja)), None
            )
            if destino is None:
                continue
            clave = next(
                (y for y in por_fila if abs(y - c["y"]) <= TOLERANCIA_FILA_PX), c["y"]
            )
            por_fila.setdefault(clave, {})[destino] = c["estado"]

        visto = []
        for y, estados in sorted(por_fila.items()):
            if y_filtro is not None and abs(y - y_filtro) <= TOLERANCIA_FILA_PX:
                continue
            materia = _texto_en(datos["textos"], y, cab[COL_ASIGNATURA])
            grupo = _texto_en(datos["textos"], y, cab[COL_GRUPO])
            if not materia and not grupo:
                # Ni asignatura ni grupo: no es una fila de la rejilla. Son los
                # checks sueltos del panel de 'Actividad', que estan debajo.
                continue
            visto.append(f"{materia}/{grupo}")
            if materia.upper() == cod_materia.upper() and grupo == num_grupo:
                return estados, y

        if time.monotonic() >= limite:
            break
        page.wait_for_timeout(1000)

    raise ErrorConsultaIsef05(
        f"ISEF05 no mostro la fila de {objetivo} tras {cfg.timeout_render_seg}s. "
        f"Lo que si mostro: {visto or 'ninguna fila'}. Si la lista esta vacia, "
        "el grupo puede no existir en ese periodo; si trae otras, el filtro no "
        "acoto y no se interpreta a ciegas."
    )
