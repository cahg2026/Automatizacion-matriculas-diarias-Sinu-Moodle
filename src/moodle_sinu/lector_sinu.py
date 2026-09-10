"""Etapa 3: lectura de ISEF07 por navegador. SOLO LECTURA, sin excepciones.

Recorre un lote (un periodo) estudiante por estudiante y devuelve lo leido de la
grilla "Grupos". La clasificacion la hace `clasificador_sinu`, que es codigo puro
y probado aparte; aqui solo esta el trato con la interfaz.

Garantias de esta etapa
-----------------------
1. **No escribe.** No importa `restricciones_sinu` porque no lo necesita: no hay
   ni una llamada capaz de modificar el sistema. Tampoco importa los selectores
   del desplegable "Accion a realizar" ni del icono de ejecutar -- no existen en
   `selectores_sinu`.
2. **Cero o varias filas al filtrar por cedula -> se detiene ese estudiante.**
   La referencia lo marca como parada obligatoria: son ajustes reales de
   matricula y seguir con el estudiante equivocado es el peor resultado posible.
3. **Un check ilegible no es un check desmarcado.** Se marca la fila como
   PENDIENTE POR REVISAR en vez de inventar un caso.
4. **Espera activa.** Nunca se dispara un paso encima de una carga en curso.

Los selectores estan SIN VERIFICAR (ver `selectores_sinu`), asi que cada paso
aborta nombrandose.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field

from playwright.sync_api import (
    Error as ErrorPlaywright,
    Locator,
    Page,
    TimeoutError as ErrorTiempoPlaywright,
)

from . import selectores_sinu as sel
from .clasificador_sinu import FilaGrupoSinu
from .config import Config
from .constantes_sinu import (
    ACTIVIDAD_VINCULACION,
    FILAS_ESPERADAS_POR_CEDULA,
    TIMEOUT_OPERACION_SINU_SEG,
)
from .restricciones_sinu import exigir_modulo_legible

log = logging.getLogger(__name__)

#: Plazo para que la grilla EMPIECE a cargar tras pulsar la fila. Si en este
#: tiempo no aparece "Cargando datos", o ya estaba al dia o el clic no llego.
SEG_ESPERA_ARRANQUE_CARGA = 8.0


class ErrorLecturaSinu(RuntimeError):
    """No se pudo leer el estado de un estudiante en ISEF07."""


class EstudianteAmbiguo(ErrorLecturaSinu):
    """El filtro por cedula devolvio cero o mas de una fila.

    Se separa del resto porque no es un fallo tecnico sino la parada obligatoria
    que pide la referencia: hay que avisar y no seguir con ese estudiante.
    """


@dataclass
class LecturaEstudiante:
    """Lo que se pudo leer de un estudiante."""

    identificacion: str
    grupos: list[FilaGrupoSinu] = field(default_factory=list)
    ilegibles: list[str] = field(default_factory=list)
    """Filas de la grilla cuyos checks no se pudieron interpretar."""

    segundos: float = 0.0


def _ms(segundos: float) -> float:
    return segundos * 1000


def _visible(locator: Locator, timeout_seg: float) -> bool:
    try:
        locator.first.wait_for(state="visible", timeout=_ms(timeout_seg))
        return True
    except ErrorTiempoPlaywright:
        return False
    except ErrorPlaywright as exc:
        log.debug("Espera interrumpida: %s", exc)
        return False


def clic_smartclient(page: Page, objetivo: Locator, descripcion: str) -> None:
    """Clic de raton en el centro del elemento, como lo daria una persona.

    Por que no `locator.click()`: SmartClient mantiene una capa transparente que
    lo cubre todo (`isc_EH_screenSpan`, un blank.gif de 3200x2400) y con la que
    CAPTURA los eventos de raton para enrutarlos el mismo a sus widgets. No es
    un estorbo accidental: es su forma de funcionar.

    Playwright ve esa capa, concluye que "algo intercepta los eventos" y se
    niega a pulsar: el 01/09/2026 una corrida murio tras 48 reintentos. Pero un
    clic real en esas coordenadas es justo lo que hace el operador -- la capa lo
    recibe y SmartClient lo reparte.

    De ahi que aqui se use `mouse.click` sobre el centro del elemento en vez del
    clic con comprobaciones del localizador.
    """
    objetivo.first.scroll_into_view_if_needed(timeout=_ms(10))
    caja = objetivo.first.bounding_box()
    if not caja:
        raise ErrorLecturaSinu(
            f"No se pudo medir {descripcion} para pulsarlo (sin caja visible)."
        )
    page.mouse.click(caja["x"] + caja["width"] / 2, caja["y"] + caja["height"] / 2)


def _exigir(locator: Locator, timeout_seg: float, descripcion: str) -> Locator:
    if _visible(locator, timeout_seg):
        return locator.first
    raise ErrorLecturaSinu(
        f"No se encontro {descripcion}. Los selectores de ISEF07 estan sin "
        "verificar: grabar con scripts/grabar_sinu.ps1 y contrastar con "
        "selectores_sinu.py."
    )


#: Plazo para que un campo de filtro pase de deshabilitado a editable.
#:
#: SmartClient deshabilita sus controles mientras trabaja (les pone la clase
#: `textItemDisabled` y el atributo `disabled`). Estar VISIBLE no es estar
#: EDITABLE, y esa diferencia costo el periodo 2026D completo el 10/09/2026:
#: `_exigir` daba el campo por bueno al verlo, `fill` esperaba su plazo por
#: defecto de 30 s a que fuera editable, y reventaba con
#:
#:     Locator.fill: Timeout 30000ms exceeded
#:     locator resolved to <input disabled class="textItemDisabl...">
#:
#: 30 s es poco en un ERP cuyas acciones tardan 58-125 s medidos: es el mismo
#: error de calibracion que el timeout de 120 s frente a un desvincular de
#: 124 s (03/09/2026). 120 s da margen sin dejar la corrida colgada.
SEG_ESPERA_CAMPO_EDITABLE = 120.0

#: Cada cuanto se vuelve a mirar si el campo ya esta editable.
SEG_SONDEO_CAMPO = 1.0


def _exigir_editable(
    locator: Locator, descripcion: str, timeout_seg: float = SEG_ESPERA_CAMPO_EDITABLE
) -> Locator:
    """Espera a que el campo este EDITABLE, no solo visible.

    Se sondea en vez de delegar en el plazo de `fill` para poder decir en el
    error lo que de verdad paso -- "el campo sigue deshabilitado" -- en lugar
    de un timeout de Playwright que no explica nada y manda a buscar el fallo
    en los selectores, que estan bien.
    """
    campo = locator.first
    limite = time.monotonic() + timeout_seg
    while True:
        try:
            if campo.is_editable():
                return campo
        except ErrorPlaywright as exc:
            log.debug("No se pudo consultar %s: %s", descripcion, exc)
        if time.monotonic() >= limite:
            raise ErrorLecturaSinu(
                f"{descripcion} sigue DESHABILITADO tras {timeout_seg:.0f}s. "
                f"SmartClient deshabilita sus controles mientras trabaja, asi "
                f"que lo normal es que ISEF07 siguiera ocupado; no es un "
                f"problema de selectores. Si se repite, subir "
                f"SEG_ESPERA_CAMPO_EDITABLE."
            )
        time.sleep(SEG_SONDEO_CAMPO)


def esperar_sin_cargas(page: Page, cfg: Config, timeout_seg: float | None = None) -> None:
    """Espera a que no haya ninguna carga en curso.

    El sistema es un ERP con grillas asincronas: la referencia insiste en que un
    clic ejecutado no significa que la accion haya terminado. Sin esta espera,
    el paso siguiente se dispara sobre una grilla a medio cargar y lee datos del
    estudiante anterior -- el fallo mas peligroso posible aqui.
    """
    limite = time.monotonic() + (timeout_seg or TIMEOUT_OPERACION_SINU_SEG)
    indicador = page.locator(sel.CSS_INDICADOR_CARGA)
    while time.monotonic() < limite:
        try:
            if indicador.count() == 0 or not indicador.first.is_visible():
                return
        except ErrorPlaywright:
            return
        page.wait_for_timeout(_ms(0.5))
    log.warning(
        "Sigue habiendo un indicador de carga tras %ss; se continua con cautela.",
        timeout_seg or TIMEOUT_OPERACION_SINU_SEG,
    )


def esperar_grilla_cargada(page: Page, cfg: Config) -> tuple[int, int, int] | None:
    """Espera a que la grilla Grupos termine de traer datos.

    Es la espera que faltaba, y su ausencia costo cuatro diagnosticos
    equivocados el 01/09/2026: se leia la grilla MIENTRAS cargaba, salia vacia,
    y se concluia que el estudiante no tenia asignaturas. Una captura de
    pantalla lo dejo claro: decia "Cargando datos..." y el pie "0 a 0 de 0 en 0
    seg.". Segundos despues la misma pantalla mostraba la fila real.

    `esperar_sin_cargas` no lo cubre: el spinner de la grilla no es un
    `progressbar` ni lleva las clases habituales, es un TEXTO.

    La senal de "ya esta" es el pie de la grilla: "1 a 1 de 1 en 2.1 seg.".
    Sirve tambien para el caso legitimo de cero filas ("0 a 0 de 0"), que es lo
    que permite distinguirlo de "todavia cargando" -- justamente lo que antes se
    confundia.

    Returns:
        (desde, hasta, total) del pie, o None si no se pudo leer.
    """
    cargando = page.get_by_text(sel.TEXTO_CARGANDO_GRILLA, exact=False)
    ultimo = None

    # Primero se espera a que la carga ARRANQUE. Sin esto la funcion volvia al
    # instante leyendo el pie ANTERIOR: tras pulsar la fila, la grilla sigue
    # unos instantes con su estado viejo ("0 a 0 de 0") y sin spinner todavia,
    # asi que se daba por cargada antes de empezar. Ese falso "0 asignaturas"
    # aparecio el 01/09/2026 justo despues de arreglar la espera anterior.
    arranco = False
    limite_arranque = time.monotonic() + SEG_ESPERA_ARRANQUE_CARGA
    while time.monotonic() < limite_arranque:
        try:
            if cargando.count():
                arranco = True
                break
        except ErrorPlaywright:
            pass
        page.wait_for_timeout(_ms(0.3))

    if not arranco:
        log.debug(
            "La grilla no mostro 'Cargando datos' en %ss: puede que ya estuviera "
            "al dia, o que el clic no llegara a disparar la carga.",
            SEG_ESPERA_ARRANQUE_CARGA,
        )

    limite = time.monotonic() + cfg.timeout_render_seg
    while time.monotonic() < limite:
        try:
            if cargando.count():
                page.wait_for_timeout(_ms(1))
                continue
        except ErrorPlaywright:
            pass

        # Sin spinner: se busca el pie. Puede haber varios (una grilla cada uno);
        # se toma el ultimo, que es el de la grilla de abajo (Grupos).
        try:
            pies = page.get_by_text(sel.RX_PIE_GRILLA)
            n = pies.count()
        except ErrorPlaywright:
            n = 0
        if n:
            try:
                texto = pies.nth(n - 1).inner_text() or ""
            except ErrorPlaywright:
                texto = ""
            casa = sel.RX_PIE_GRILLA.search(texto)
            if casa:
                ultimo = tuple(int(g) for g in casa.groups())
                log.debug("Pie de la grilla Grupos: %s", ultimo)
                return ultimo  # type: ignore[return-value]
        page.wait_for_timeout(_ms(1))

    log.warning(
        "La grilla Grupos no confirmo su carga en %ss (ultimo pie leido: %s). "
        "Se continua, pero lo que se lea puede estar incompleto.",
        cfg.timeout_render_seg,
        ultimo,
    )
    return ultimo


def entrar_en_modulo(page: Page, cfg: Config, modulo: str, motivo: str) -> None:
    """Autoriza, navega y confirma la entrada en un modulo del sistema.

    Todo acceso pasa por aqui, de modo que la matriz de permisos se aplica en un
    solo sitio y queda en el log con que modulo se entro y para que.

    La navegacion es la comprobada el 24/08/2026: en `#home` hay una tabla con
    los modulos disponibles y se entra clicando la celda del codigo. Los codigos
    van en minuscula.

    Raises:
        ErrorRestriccionOperativa: si el modulo no es consultable.
        ErrorLecturaSinu: si no se llega a abrir.
    """
    exigir_modulo_legible(modulo, motivo)
    codigo = modulo.strip().lower()
    destino = sel.hash_de_modulo(codigo)

    if page.url.rstrip("/").endswith(destino):
        log.info("Ya estabamos en %s.", codigo)
        esperar_sin_cargas(page, cfg)
        return

    log.info("Acceso de LECTURA autorizado en %s (%s); abriendo.", codigo, motivo)
    celda = page.get_by_text(codigo, exact=True)
    if not _visible(celda, cfg.timeout_operacion_seg):
        raise ErrorLecturaSinu(
            f"No aparece '{codigo}' en el menu de modulos de #home. Puede que la "
            "cuenta no tenga acceso a ese modulo, o que no estemos en la "
            f"pantalla principal (URL actual: {page.url})."
        )
    celda.first.click()

    # La URL con el hash del modulo es la senal inequivoca de que se entro.
    limite = time.monotonic() + cfg.timeout_render_seg
    while time.monotonic() < limite:
        if page.url.rstrip("/").endswith(destino):
            break
        page.wait_for_timeout(500)
    else:
        raise ErrorLecturaSinu(
            f"Se clico '{codigo}' pero la URL sigue en {page.url}. El modulo no "
            "llego a abrirse."
        )

    esperar_sin_cargas(page, cfg)
    _confirmar_modulo_cargado(page, cfg, codigo)


def _confirmar_modulo_cargado(page: Page, cfg: Config, codigo: str) -> None:
    """Comprueba que la pantalla del modulo pinto lo que se espera.

    Solo se sabe que buscar para ISEF07, que es el unico que la automatizacion
    usa. Para el resto basta con la URL.
    """
    if codigo != ACTIVIDAD_VINCULACION:
        log.info("Modulo %s abierto.", codigo)
        return

    limite = time.monotonic() + cfg.timeout_render_seg
    while time.monotonic() < limite:
        hallados = [
            texto
            for texto in sel.TEXTOS_ISEF07_CARGADO
            if page.get_by_text(texto, exact=False).count()
        ]
        if len(hallados) >= 2:
            log.info("ISEF07 abierto; se reconocieron %s.", hallados)
            return
        page.wait_for_timeout(1000)

    raise ErrorLecturaSinu(
        f"Se entro en {codigo} pero no aparecieron sus columnas "
        f"({', '.join(sel.TEXTOS_ISEF07_CARGADO)}). No se sigue a ciegas."
    )


def RX_EXACTO(texto: str) -> re.Pattern[str]:
    """Regex que casa el texto completo de una celda, sin subcadenas.

    Hace falta porque '2026C' es subcadena de nada, pero '26I04' si podria
    aparecer dentro de otro codigo, y elegir la celda equivocada fija un periodo
    que no es el pedido.
    """
    return re.compile(r"^\s*" + re.escape(texto) + r"\s*$")


def localizar_desplegable_periodo(page: Page) -> Locator | None:
    """El desplegable de Periodo, o None si no se reconoce.

    ISEF07 tiene varios `.selectItemText` (empresa, LMS, idioma, 'Contiene', uno
    vacio y el periodo) y **ninguno expone `name` ni un id estable**: los ids los
    genera SmartClient (`isc_7O`) y cambian entre sesiones. Se desempata por el
    VALOR: solo el del periodo casa con un codigo tipo `26V05` o `2027A`.

    Comprobado el 01/09/2026 sobre la pantalla real: 6 desplegables, el del
    periodo en el indice 5 con valor '26V05'.
    """
    desplegables = page.locator(sel.CSS_DESPLEGABLE)
    for i in range(desplegables.count()):
        candidato = desplegables.nth(i)
        try:
            texto = (candidato.inner_text() or "").strip()
        except ErrorPlaywright:  # pragma: no cover - la SPA repinta
            continue
        if sel.RX_VALOR_PERIODO.match(texto):
            log.debug("Desplegable de Periodo en el indice %d (valor %r)", i, texto)
            return candidato
    return None


def periodo_actual(page: Page) -> str | None:
    """Valor que muestra el desplegable de Periodo ahora mismo."""
    campo = localizar_desplegable_periodo(page)
    if campo is None:
        return None
    try:
        return (campo.inner_text() or "").strip()
    except ErrorPlaywright:  # pragma: no cover
        return None


def fijar_periodo(page: Page, cfg: Config, cod_periodo: str) -> None:
    """Ajusta el filtro de Periodo. Se llama UNA VEZ por sesion, no por estudiante.

    El Periodo NO es un campo de texto: es un desplegable de SmartClient. La
    version anterior lo buscaba con `get_by_label` y fallaba siempre -- algo que
    `selectores_sinu` ya documentaba como verificado el 24/08/2026, pero que esta
    funcion nunca recogio. De ahi el 'No se encontro el campo de filtro Periodo'
    del 01/09/2026.

    Al terminar se COMPRUEBA que el desplegable muestre el periodo pedido. Sin
    esa comprobacion, un fallo silencioso dejaria la sesion trabajando sobre el
    periodo anterior, que es la peor forma de equivocarse: vincula matriculas
    reales del periodo que no toca.

    Raises:
        ErrorLecturaSinu: si no se localiza el desplegable o si el valor no
            queda fijado en el periodo pedido.
    """
    objetivo = cod_periodo.strip().upper()
    campo = localizar_desplegable_periodo(page)
    if campo is None:
        raise ErrorLecturaSinu(
            "No se reconocio el desplegable de 'Periodo'. Se buscaron los "
            f"'{sel.CSS_DESPLEGABLE}' cuyo valor casara con un codigo de periodo "
            f"({sel.RX_VALOR_PERIODO.pattern}). Si ISEF07 cambio, volver a "
            "inspeccionar la pantalla."
        )

    actual = (campo.inner_text() or "").strip()
    if actual.upper() == objetivo:
        log.info("El periodo ya estaba en %s; no se toca.", objetivo)
        return

    log.info("Fijando el periodo %s (estaba en %s)", objetivo, actual or "(vacio)")
    campo.click()
    page.wait_for_timeout(_ms(2))

    # La lista de periodos es LARGA (44 codigos el 01/09/2026) y SmartClient la
    # virtualiza: las opciones no existen en el DOM hasta que el scroller las
    # alcanza, asi que buscarlas de una vez devuelve cero. Se avanza con el
    # teclado, que es lo que mueve ese scroller, y se comprueba en cada vuelta.
    #
    # Teclear el codigo NO funciona: no filtra, y el Enter posterior deja el
    # desplegable en un estado en el que ni se reconoce (comprobado el mismo dia).
    def _ya_visible() -> Locator | None:
        candidata = page.locator(sel.CSS_CELDA).filter(has_text=RX_EXACTO(objetivo))
        return candidata.first if candidata.count() else None

    opcion = _ya_visible()

    if opcion is None:
        # Se rebobina al principio de la lista ANTES de recorrerla. Sin esto solo
        # se buscaba hacia abajo, y un periodo que ordene por encima del actual
        # no se alcanzaba nunca: '2026C' < '26V05' como cadenas, asi que fijar
        # 2026C funcionaba o no segun donde estuviera el filtro al empezar
        # (comprobado el 01/09/2026: funciono una vez y fallo la siguiente).
        page.keyboard.press("Home")
        page.wait_for_timeout(_ms(0.5))
        for _ in range(sel.PASOS_REBOBINADO_PERIODO):
            page.keyboard.press("ArrowUp")
        page.wait_for_timeout(_ms(0.7))

        for vuelta in range(sel.VUELTAS_LISTA_PERIODO):
            opcion = _ya_visible()
            if opcion is not None:
                log.debug("Opcion '%s' visible en la vuelta %d", objetivo, vuelta)
                break
            for _ in range(sel.PASOS_POR_VUELTA_PERIODO):
                page.keyboard.press("ArrowDown")
            page.wait_for_timeout(_ms(0.7))

    if opcion is None:
        page.keyboard.press("Escape")
        raise ErrorLecturaSinu(
            f"El periodo '{objetivo}' no aparecio en la lista de ISEF07 tras "
            f"recorrerla. O no es un periodo valido en el sistema, o la lista "
            "cambio de estructura. El reporte lo trae, asi que conviene "
            "comprobar el dato en origen antes de tocar matriculas."
        )

    opcion.click()
    esperar_sin_cargas(page, cfg)

    # La comprobacion es el punto de esta funcion, no un extra.
    quedo = periodo_actual(page)
    if (quedo or "").strip().upper() != objetivo:
        raise ErrorLecturaSinu(
            f"El filtro de Periodo no quedo en '{objetivo}': muestra "
            f"'{quedo or '(ilegible)'}'. Se aborta en vez de seguir, porque "
            "trabajar sobre el periodo equivocado vincula matriculas que no "
            "corresponden."
        )
    log.info("Periodo fijado y verificado: %s", quedo)


#: Tolerancia vertical para dar dos elementos por "de la misma fila", en px.
#: Las filas de la grilla van a ~25 px, asi que 9 no llega a solaparlas.
TOLERANCIA_FILA_PX = 9

#: Recoge de una vez encabezados, checks y textos con su geometria.
#:
#: Se hace en UN `evaluate` y no elemento por elemento porque la pantalla tiene
#: cientos de nodos: ir y venir por cada uno tardaba minutos por estudiante.
_GUION_GRUPOS = """
(cfg) => {
  const medio = (r) => ({x: r.x + r.width / 2, y: r.y + r.height / 2});

  const cab = {};
  for (const e of document.querySelectorAll('td, div, span, nobr')) {
    const t = (e.innerText || '').replace(/\\s+/g, ' ').trim();
    if (cfg.columnas.includes(t) && !cab[t]) {
      const r = e.getBoundingClientRect();
      if (r.width > 0) cab[t] = {x: r.x, w: r.width, y: r.y};
    }
  }

  // La fila de FILTRO se identifica por el input de codigo de asignatura que
  // vive en ella. Sin esto se colaba como una fila de datos con los dos checks
  // en 'unsetcheck.gif', y se leia como una asignatura ilegible.
  let yFiltro = null;
  const inp = document.querySelector(cfg.cssFiltroMateria);
  if (inp) {
    const r = inp.getBoundingClientRect();
    if (r.width > 0) yFiltro = medio(r).y;
  }

  const checks = [];
  for (const im of document.querySelectorAll('img')) {
    const hoja = (im.getAttribute('src') || '').split('/').pop().split('?')[0];
    if (!cfg.estados.includes(hoja)) continue;
    const r = im.getBoundingClientRect();
    if (r.width === 0) continue;
    checks.push(Object.assign({estado: hoja}, medio(r)));
  }

  const textos = [];
  for (const e of document.querySelectorAll('nobr')) {
    const t = (e.innerText || '').replace(/\\s+/g, ' ').trim();
    if (!t || t.length > 60) continue;
    const r = e.getBoundingClientRect();
    if (r.width === 0) continue;
    textos.push(Object.assign({t: t}, medio(r)));
  }

  return {cab: cab, yFiltro: yFiltro, checks: checks, textos: textos};
}
"""


def _en_columna(x: float, caja: dict) -> bool:
    """True si una x cae dentro de la columna descrita por el encabezado."""
    return caja["x"] <= x <= caja["x"] + max(caja["w"], 20)


def _texto_en(textos: list[dict], y: float, caja: dict) -> str:
    """Texto de la celda que cruza la fila `y` con la columna `caja`."""
    for it in textos:
        if abs(it["y"] - y) <= TOLERANCIA_FILA_PX and _en_columna(it["x"], caja):
            return it["t"]
    return ""


def leer_filas_grupos(page: Page) -> tuple[list[FilaGrupoSinu], list[str]]:
    """Lee la grilla Grupos por geometria. Devuelve (filas, ilegibles).

    Por que por geometria y no por roles o tablas: ISEF07 no expone
    `role="grid"`, y `role="row"` existe pero **no envuelve los checks**. Cada
    celda va en su propio `<tr>` de una mini-tabla, asi que el `<tr>` no es la
    fila. Lo unico fiable es cruzar la `y` de cada check con la `x` de los
    encabezados (todo verificado el 01/09/2026 sobre la pantalla real).

    Un check ilegible NO se lee como desmarcado: la fila entera se aparta a
    `ilegibles` para que acabe en PENDIENTE POR REVISAR.
    """
    datos = page.evaluate(
        _GUION_GRUPOS,
        {
            "columnas": list(sel.COLUMNAS_GRUPOS),
            "estados": [
                sel.IMG_CHECK_MARCADO,
                sel.IMG_CHECK_DESMARCADO,
                sel.IMG_CHECK_MARCADO_BLOQUEADO,
                sel.IMG_CHECK_DESMARCADO_BLOQUEADO,
                sel.IMG_CHECK_SIN_DEFINIR,
            ],
            "cssFiltroMateria": sel.CSS_FILTRO_MATERIA,
        },
    )

    cab = datos["cab"]
    faltan = [c for c in ("Curso en moodle?", "Vinculado?") if c not in cab]
    if faltan:
        raise ErrorLecturaSinu(
            f"No se localizaron los encabezados {faltan} de la grilla Grupos. "
            f"Se vieron: {sorted(cab)}. Sin ellos no se puede saber que check es "
            "cual, y adivinarlo invertiria el arbol de decision."
        )

    caja_curso = cab["Curso en moodle?"]
    caja_vinc = cab["Vinculado?"]
    caja_cod = cab.get("Código asignatura")
    caja_grupo = cab.get("Grupo")
    y_filtro = datos.get("yFiltro")

    # Se agrupan los checks por fila: cada `y` distinta es una fila.
    por_fila: dict[float, dict[str, str]] = {}
    for c in datos["checks"]:
        destino = None
        if _en_columna(c["x"], caja_curso):
            destino = "curso"
        elif _en_columna(c["x"], caja_vinc):
            destino = "vinculado"
        if destino is None:
            continue  # check de otra columna (Pago?, Cancela...)
        clave = next(
            (y for y in por_fila if abs(y - c["y"]) <= TOLERANCIA_FILA_PX), c["y"]
        )
        por_fila.setdefault(clave, {})[destino] = c["estado"]

    filas: list[FilaGrupoSinu] = []
    ilegibles: list[str] = []

    for y in sorted(por_fila):
        if y_filtro is not None and abs(y - y_filtro) <= TOLERANCIA_FILA_PX:
            log.debug("Fila de filtro descartada (y=%s).", round(y))
            continue

        estados = por_fila[y]
        materia = _texto_en(datos["textos"], y, caja_cod) if caja_cod else ""
        grupo = _texto_en(datos["textos"], y, caja_grupo) if caja_grupo else ""
        crudo = f"y={round(y)} materia={materia!r} grupo={grupo!r} {estados}"

        curso = sel.estado_de_imagen(estados.get("curso"))
        vinculado = sel.estado_de_imagen(estados.get("vinculado"))
        if curso is None or vinculado is None:
            ilegibles.append(crudo)
            log.warning("Checks ilegibles en la fila '%s'; se aparta.", crudo)
            continue

        filas.append(
            FilaGrupoSinu(
                cod_materia=materia,
                num_grupo=grupo,
                curso_en_moodle=curso,
                vinculado=vinculado,
                texto_crudo=crudo,
            )
        )

    return filas, ilegibles



class MateriaNoEncontrada(ErrorLecturaSinu):
    """El filtro por COD_MATERIA no dejo exactamente la materia buscada.

    Se separa del resto porque la respuesta correcta es la misma que ante un
    estudiante ambiguo: parar y avisar. Ejecutar con la grilla mostrando otra
    cosa es como ejecutar sobre el estudiante equivocado.
    """


def filtrar_grupos_por_materia(
    page: Page, cfg: Config, cod_materia: str
) -> list[FilaGrupoSinu]:
    """Acota la grilla Grupos a un COD_MATERIA. Devuelve las filas que quedan.

    Es el paso que **confina la accion de ISEF07 a una sola asignatura**, y por
    eso no es opcional. Sin el, "Vincular grupos matriculados" alcanza todas las
    asignaturas del estudiante en el periodo: el 03/09/2026 eso reciclo 34
    asignaturas cuando el reporte pedia 5.

    Se filtra por `input[name="cod_materia"]`, que convive con el de la cedula y
    tiene nombre estable (verificado el 24/08/2026). El comentario que decia que
    COD_MATERIA "no es clave de busqueda aqui" venia de la referencia de negocio
    y era falso; ver la correccion del 03/09/2026 en
    `references/vinculacion-moodle.md`.

    Raises:
        ErrorLecturaSinu: si el filtro no se puede localizar.
    """
    exigir_modulo_legible(
        ACTIVIDAD_VINCULACION, f"acotar la grilla Grupos a la materia {cod_materia}"
    )
    filtro = _exigir(
        page.locator(sel.CSS_FILTRO_MATERIA),
        cfg.timeout_operacion_seg,
        "el filtro de la columna de materia de la grilla Grupos",
    )
    # `fill` y no triple clic, por lo mismo que en el filtro de cedula: la capa
    # `isc_EH_screenSpan` de SmartClient intercepta los clics de puntero.
    filtro = _exigir_editable(filtro, "el filtro de la columna de materia")
    filtro.fill(cod_materia)
    filtro.press("Enter")
    esperar_sin_cargas(page, cfg)

    pie = esperar_grilla_cargada(page, cfg)
    if pie is not None:
        log.info("Grupos acotada a %s: %s a %s de %s.", cod_materia, *pie)

    filas, ilegibles = leer_filas_grupos(page)
    if ilegibles:
        raise MateriaNoEncontrada(
            f"Al acotar a {cod_materia} quedaron {len(ilegibles)} filas con checks "
            f"ilegibles: {ilegibles}. No se ejecuta a ciegas."
        )
    log.info("Grupos acotada a %s: %d fila(s).", cod_materia, len(filas))
    return filas


def limpiar_filtro_de_materia(page: Page, cfg: Config) -> None:
    """Vacia el filtro de materia para volver a ver la grilla completa.

    Hace falta para la comprobacion de desborde: hay que poder mirar TODAS las
    asignaturas del estudiante despues de actuar sobre una.
    """
    filtro = _exigir(
        page.locator(sel.CSS_FILTRO_MATERIA),
        cfg.timeout_operacion_seg,
        "el filtro de la columna de materia de la grilla Grupos",
    )
    filtro = _exigir_editable(filtro, "el filtro de materia (para vaciarlo)")
    filtro.fill("")
    filtro.press("Enter")
    esperar_sin_cargas(page, cfg)
    esperar_grilla_cargada(page, cfg)


def leer_estudiante(
    page: Page, cfg: Config, identificacion: str
) -> LecturaEstudiante:
    """Filtra por cedula y lee la grilla Grupos. No modifica nada.

    Raises:
        EstudianteAmbiguo: si el filtro devuelve cero o mas de una fila.
        ErrorLecturaSinu: si un paso no se puede localizar.
    """
    inicio = time.monotonic()
    # La lectura de ISEF07 pasa por la misma guarda que cualquier otro modulo:
    # el permiso no se da por supuesto en ningun sitio del flujo.
    exigir_modulo_legible(ACTIVIDAD_VINCULACION, f"leer la grilla Grupos de {identificacion}")
    log.info("Leyendo el estudiante %s", identificacion)

    # El filtro de cedula se localiza por su `name`, que es estable. Buscarlo
    # "dentro de la grilla Estudiantes" no era posible: esa grilla no existe
    # como elemento con rol (ver `leer_filas_grupos`).
    filtro = _exigir(
        page.locator(sel.CSS_FILTRO_CEDULA),
        cfg.timeout_operacion_seg,
        "el filtro de la columna 'No. Identificacion'",
    )
    # Se rellena con `fill`, SIN el triple clic de la referencia.
    #
    # El triple clic es un consejo para personas: selecciona el valor previo
    # antes de teclear. `fill` ya lo hace, y ademas no necesita eventos de
    # puntero -- que es lo que aqui importa: SmartClient mantiene una capa
    # `isc_EH_screenSpan` (un blank.gif de 3200x2400) que a veces se pone por
    # encima e intercepta los clics. Con triple clic la corrida moria tras 48
    # reintentos; con `fill` no se toca el raton (01/09/2026).
    #
    # NO se pulsa Escape antes. Se probo "por seguridad, para cerrar cualquier
    # desplegable" y fue contraproducente: SmartClient reaccionaba poniendo su
    # capa de eventos por encima, y entonces el clic siguiente se consideraba
    # interceptado. Quitarlo devolvio el comportamiento que ya funcionaba.
    # Visible NO es editable: SmartClient deshabilita el campo mientras trabaja.
    # Esperarlo aqui, con un plazo acorde al ERP, evita el timeout de 30 s de
    # `fill` que se llevo el periodo 2026D entero el 10/09/2026.
    filtro = _exigir_editable(filtro, "el filtro de 'No. Identificacion'")
    filtro.fill(identificacion)
    filtro.press("Enter")
    esperar_sin_cargas(page, cfg)

    # La cedula aparece exactamente una vez cuando el filtro acierta: es la
    # comprobacion de ambigüedad que pide la referencia, y a la vez el elemento
    # que hay que pulsar para que cargue Grupos.
    #
    # Se ESPERA a que aparezca en vez de contar tras una pausa fija: la grilla
    # Estudiantes tambien tarda en filtrar, y con un `wait_for_timeout(2)` daba
    # "0 filas" para cedulas que si existian. Es el mismo error que costo los
    # diagnosticos de la grilla Grupos, cometido dos veces el 01/09/2026.
    celda = page.get_by_text(identificacion, exact=True)
    _visible(celda, cfg.timeout_render_seg)
    encontradas = celda.count()
    if encontradas != FILAS_ESPERADAS_POR_CEDULA:
        raise EstudianteAmbiguo(
            f"El filtro por la cedula {identificacion} devolvio {encontradas} "
            f"filas y se esperaba exactamente {FILAS_ESPERADAS_POR_CEDULA}. Se "
            "detiene este estudiante: seguir con el equivocado seria peor que "
            "no hacer nada."
        )

    # El clic del localizador es el que SI selecciona la fila (comprobado leyendo
    # dos estudiantes completos). El clic de raton crudo tambien llega, pero
    # SmartClient no lo toma como seleccion: la fila no se resaltaba y Grupos
    # seguia con "No hay informacion para mostrar".
    #
    # Se conserva `clic_smartclient` como reserva para el caso en que la capa de
    # eventos si estorbe, que es cuando el clic del localizador da timeout.
    try:
        celda.first.click(timeout=_ms(cfg.timeout_operacion_seg))
    except ErrorPlaywright as exc:
        log.warning(
            "El clic sobre la fila de %s fue interceptado (%s); se reintenta con "
            "un clic de raton.",
            identificacion,
            str(exc).splitlines()[0][:80],
        )
        clic_smartclient(page, celda, f"la fila de la cedula {identificacion}")
    esperar_sin_cargas(page, cfg)

    # Sin esta espera se leia la grilla a medio cargar y salia vacia: cuatro
    # diagnosticos del 01/09/2026 culparon a los selectores por esto.
    pie = esperar_grilla_cargada(page, cfg)
    if pie is not None:
        log.info("Grilla Grupos cargada: %s a %s de %s.", *pie)

    lectura = LecturaEstudiante(identificacion=identificacion)
    lectura.grupos, lectura.ilegibles = leer_filas_grupos(page)
    lectura.segundos = round(time.monotonic() - inicio, 1)
    log.info(
        "%s: %d asignaturas leidas (%d ilegibles) en %ss",
        identificacion,
        len(lectura.grupos),
        len(lectura.ilegibles),
        lectura.segundos,
    )
    return lectura
