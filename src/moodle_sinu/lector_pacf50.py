"""Consulta en PACF50 (Programacion de grupos) si un grupo esta en MOODLE.

Por que existe
--------------
Regla del dueno del proceso (26/09/2026):

    Si no te sale la 05, tienes que validarla por la 50. Y si no te sale por la
    50, pues la validas por la 05. Siempre se tienen que validar en ambas.

Hasta hoy solo existia `lector_isef05`, y el 26/09/2026 eso costo el dia: ISEF05
no contesto por los 4 grupos grandes -- 165 filas, el 94% del lote -- y, al no
haber segunda via, el robot se puso a procesarlas una a una por ISEF07.

`SKILL.md` marcaba PACF50 como *(pendiente de documentar)*. Lo que hay aqui sale
de sondear la pantalla real el 26/09/2026 (`scripts/sondear_pacf50.py`), no de
suponer.

La pantalla, tal como se midio
------------------------------
Son DOS rejillas encadenadas, y ese encadenamiento es el modelo de interaccion:

    1. Rejilla de ARRIBA: asignaturas. Filtro `cod_materia`, editable de entrada.
    2. Se PULSA la fila de la asignatura.
    3. Rejilla de ABAJO: sus grupos. Su filtro `num_grupo` nace DESHABILITADO y
       **solo se habilita tras el clic de arriba**.

Comprobado ese dia con POS01 en 26ES5:

    inicio       -> cod_materia=editable  num_grupo=DESHABILITADO
    tras filtrar -> cod_materia=editable  num_grupo=DESHABILITADO
    tras el clic -> num_grupo=editable, y abajo salen 55ES1, 55ES2, 55ES3

Saltarse el clic deja el filtro de grupo inerte para siempre; no es un problema
de espera, es que la rejilla de abajo aun no existe.

Columnas de MOODLE (cabecera de la rejilla de grupos, y=475):

    x=1641  'Moodle?'
    x=1731  'Enviado a Moodle?'
    x=1821  'Mas Informacion Moodle'

El vocabulario de imagenes de check es el MISMO que en ISEF05 y ISEF07
(`checked.gif`, `unchecked.gif`, y sus variantes `_Disabled`), asi que se
interpreta con `sel.estado_de_imagen` y no con una lista propia. Tener dos
listas es como nacio el incidente n.o 2.

Solo lectura
------------
`restricciones_sinu` mantiene pacf50 fuera de `MODULOS_ESCRIBIBLES`. Aqui solo
se escribe en cajas de filtro y se pulsa una fila para desplegar sus grupos.
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

from . import selectores_sinu as sel
from .config import Config
from .constantes_sinu import ACTIVIDAD_PROGRAMACION_GRUPOS
from .lector_sinu import (
    ErrorLecturaSinu,
    entrar_en_modulo,
    esperar_sin_cargas,
    fijar_periodo,
)
from .restricciones_sinu import exigir_modulo_legible

log = logging.getLogger(__name__)

#: Cabeceras de las columnas de MOODLE en la rejilla de grupos. Leidas de la
#: pantalla real el 26/09/2026.
COL_MOODLE = "Moodle?"
COL_ENVIADO = "Enviado a Moodle?"

#: Filtros. `cod_materia` es el de la rejilla de arriba; `num_grupo` el de la de
#: abajo, que NACE DESHABILITADO (ver el docstring del modulo).
CSS_FILTRO_MATERIA = 'input[name="cod_materia"]'
CSS_FILTRO_GRUPO = 'input[name="num_grupo"]'

#: Cuanto se espera a que un filtro acepte texto. Mismo criterio que en ISEF05
#: desde el 26/09/2026: se espera a EDITABLE, no a visible, y con holgura --
#: abrir un modulo es un trabajo en curso de verdad.
SEG_ESPERA_FILTRO = 120.0

#: Cuanto se espera a que la rejilla de grupos aparezca tras pulsar la
#: asignatura. Es lo que tarda SmartClient en montarla.
SEG_ESPERA_REJILLA_GRUPOS = 60.0


class ErrorConsultaPacf50(ErrorLecturaSinu):
    """No se pudo averiguar el estado del grupo en PACF50."""


@dataclass(frozen=True)
class GrupoEnPacf50:
    """Lo que PACF50 dice de un grupo.

    Cada check es `True` (marcado), `False` (desmarcado) o `None` (ilegible).
    `None` NO se trata como `False`: no saber y saber que no son cosas
    distintas, y confundirlas marcaria en rojo sin fundamento.
    """

    cod_periodo: str
    cod_materia: str
    num_grupo: str
    moodle: bool | None
    enviado: bool | None
    crudo: str = ""
    existe: bool | None = True
    """False solo con evidencia positiva de que el grupo NO esta programado:
    la asignatura aparecio, su rejilla de grupos cargo y acepto el filtro, y
    aun asi ninguna fila tiene ese numero de grupo (ver `consultar_grupo`)."""

    @property
    def objetivo(self) -> str:
        return f"{self.cod_materia}/{self.num_grupo}"

    @property
    def vincular_es_imposible(self) -> bool:
        """True solo si CONSTA que el grupo no esta en MOODLE.

        Se responde con `is False` y no con `not moodle`: con el check ilegible
        (`None`) la respuesta tiene que ser "no lo se", que aqui significa
        seguir procesando como hasta ahora.
        """
        return self.moodle is False

    def resumen(self) -> str:
        def _m(v: bool | None) -> str:
            return {True: "si", False: "NO", None: "ilegible"}[v]

        if self.existe is False:
            return (
                f"{self.cod_periodo} {self.objetivo}: el GRUPO NO EXISTE en "
                f"PACF50 (PACF50)"
            )
        return (
            f"{self.cod_periodo} {self.objetivo}: moodle={_m(self.moodle)} "
            f"enviado={_m(self.enviado)} (PACF50)"
        )


def _esperar_editable(page: Page, css: str, que: str, segundos: float) -> None:
    """Espera a que un filtro acepte texto. Visible NO es escribible.

    SmartClient pinta el filtro y lo deja `disabled` mientras la rejilla carga.
    Es el mismo fallo que el 26/09/2026 tumbo la verificacion previa en ISEF05:
    30 s esperando a "visible" sobre un campo que estaba ahi y deshabilitado.
    """
    caja = page.locator(css).first
    limite = time.monotonic() + segundos
    ultimo = "no aparecio"
    while time.monotonic() < limite:
        try:
            if caja.is_editable():
                return
            ultimo = "existe pero sigue DESHABILITADO"
        except (ErrorPlaywright, ErrorTiempoPlaywright) as exc:
            ultimo = str(exc).splitlines()[0]
        page.wait_for_timeout(1000)
    raise ErrorConsultaPacf50(
        f"En PACF50, {que} ('{css}') no acepta texto tras {segundos:.0f}s ({ultimo})."
    )


def _filtrar(page: Page, cfg: Config, css: str, valor: str, que: str) -> None:
    """Escribe en una caja de filtro y aplica con Enter.

    `fill` y no clic + teclado: la capa `screenSpan` de SmartClient intercepta
    los clics de puntero, igual que en ISEF05 y en ISEF07.
    """
    _esperar_editable(page, css, que, SEG_ESPERA_FILTRO)
    caja = page.locator(css).first
    try:
        caja.fill(valor)
        caja.press("Enter")
    except (ErrorPlaywright, ErrorTiempoPlaywright) as exc:
        raise ErrorConsultaPacf50(
            f"No se pudo filtrar {que} ('{valor}') en PACF50: {exc}"
        ) from exc
    esperar_sin_cargas(page, cfg)


#: Guion que localiza la fila de la asignatura en la rejilla de ARRIBA por
#: CONTENIDO: la celda de la asignatura y, en la misma banda horizontal, el
#: periodo, el programa y el pensum pedidos (los que esten informados). Hasta el
#: 28/09/2026 se pulsaba la primera celda "POS01" que hubiera, y una asignatura
#: puede ofertarse en varios programas o salir con otro periodo (en la captura
#: del dueno del proceso la fila decia 26ES3): la rejilla de grupos de esa otra
#: fila no tiene los grupos del reporte.
_GUION_FILA_ASIGNATURA = """
(cfg) => {
  const norm = (s) => (s||'').replace(/\\s+/g,' ').trim();
  const caja = (e) => { const r = e.getBoundingClientRect();
                        return (r.width > 0 && r.height > 0) ? r : null; };
  const celdas = [...document.querySelectorAll('td, div, span')];
  const conTexto = (t) => celdas.map(e => [e, caja(e)])
                                .filter(([e, r]) => r && norm(e.innerText) === t);
  for (const [e, r] of conTexto(cfg.materia)) {
    const cy = r.y + r.height / 2;
    const enFila = (t) => !t || conTexto(t).some(
      ([_, r2]) => Math.abs((r2.y + r2.height / 2) - cy) <= cfg.tolerancia);
    if (enFila(cfg.periodo) && enFila(cfg.unidad) && enFila(cfg.pensum)) {
      return {x: r.x + r.width / 2, y: cy};
    }
  }
  return null;
}
"""


def _desplegar_grupos(
    page: Page,
    cfg: Config,
    *,
    cod_periodo: str,
    cod_materia: str,
    cod_unidad: str = "",
    cod_pensum: str = "",
) -> None:
    """Pulsa la fila de la asignatura para que aparezca su rejilla de grupos.

    Sin esto el filtro `num_grupo` se queda DESHABILITADO para siempre: la
    rejilla de abajo no existe todavia. Medido el 26/09/2026 -- no es una
    cuestion de esperar mas.

    La fila tiene que ser la de la FILA DEL REPORTE: misma asignatura, mismo
    periodo y, si vienen, mismo programa (COD_UNIDAD) y pensum (COD_PENSUM).
    Si no aparece, no se pulsa otra: se dice "no lo se".
    """
    from .lector_sinu import TOLERANCIA_FILA_PX

    # Se SONDEA la aparicion de la fila, no se mira una vez. `esperar_sin_cargas`
    # devuelve el control antes de que SmartClient haya repintado la rejilla:
    # medido el 26/09/2026, mirar una sola vez daba "no muestra ninguna fila"
    # para una asignatura que aparecia cuatro segundos despues.
    buscada = {
        "materia": cod_materia,
        "periodo": cod_periodo,
        "unidad": cod_unidad,
        "pensum": cod_pensum,
        "tolerancia": TOLERANCIA_FILA_PX,
    }
    punto = None
    limite = time.monotonic() + SEG_ESPERA_REJILLA_GRUPOS
    while time.monotonic() < limite:
        try:
            punto = page.evaluate(_GUION_FILA_ASIGNATURA, buscada)
        except ErrorPlaywright:  # pragma: no cover - la SPA repinta
            punto = None
        if punto:
            break
        page.wait_for_timeout(1000)
    else:
        raise ErrorConsultaPacf50(
            f"PACF50 no muestra la fila de la asignatura '{cod_materia}' con "
            f"periodo {cod_periodo}"
            + (f", programa {cod_unidad}" if cod_unidad else "")
            + (f", pensum {cod_pensum}" if cod_pensum else "")
            + f" tras {SEG_ESPERA_REJILLA_GRUPOS:.0f}s. No se pulsa otra fila: "
            "sus grupos serian los de otra oferta."
        )

    try:
        page.mouse.click(punto["x"], punto["y"])
    except (ErrorPlaywright, ErrorTiempoPlaywright) as exc:
        raise ErrorConsultaPacf50(
            f"No se pudo seleccionar la asignatura '{cod_materia}' en PACF50: {exc}"
        ) from exc
    esperar_sin_cargas(page, cfg)
    _esperar_editable(
        page, CSS_FILTRO_GRUPO, "el filtro de grupo", SEG_ESPERA_REJILLA_GRUPOS
    )


def consultar_grupo(
    page: Page,
    cfg: Config,
    *,
    cod_periodo: str,
    cod_materia: str,
    num_grupo: str,
    cod_unidad: str = "",
    cod_pensum: str = "",
) -> GrupoEnPacf50:
    """Dice si un grupo EXISTE y si esta en MOODLE, segun PACF50.

    El periodo que se fija es el de la fila que se esta gestionando, y la fila
    de la asignatura que se pulsa es la de ese periodo, programa y pensum.

    Deja la pantalla en PACF50.

    Raises:
        ErrorRestriccionOperativa: si pacf50 saliera de la lista de legibles.
        ErrorConsultaPacf50: si no se pudo averiguar -- "no lo se".
    """
    objetivo = f"{cod_materia}/{num_grupo}"
    motivo = f"consultar el estado en MOODLE de {objetivo}"
    exigir_modulo_legible(ACTIVIDAD_PROGRAMACION_GRUPOS, motivo)
    entrar_en_modulo(page, cfg, ACTIVIDAD_PROGRAMACION_GRUPOS, motivo)
    fijar_periodo(page, cfg, cod_periodo)

    _filtrar(page, cfg, CSS_FILTRO_MATERIA, cod_materia, "la asignatura")
    _desplegar_grupos(
        page, cfg,
        cod_periodo=cod_periodo, cod_materia=cod_materia,
        cod_unidad=cod_unidad, cod_pensum=cod_pensum,
    )
    _filtrar(page, cfg, CSS_FILTRO_GRUPO, num_grupo, "el grupo")

    leida = _leer_fila_del_grupo(page, cfg, num_grupo=num_grupo, objetivo=objetivo)
    if leida is None:
        raise ErrorConsultaPacf50(
            f"PACF50 no mostro ni la fila de {objetivo} ni '{TEXTO_SIN_INFORMACION}' "
            "de forma estable. No se deduce nada: no saber NO es no tener curso."
        )
    if leida is SIN_INFORMACION:
        # Lo que el dueno del proceso comprueba a mano: con el grupo en el
        # filtro, la rejilla dice "No hay informacion para mostrar" y ya no
        # carga nada. El grupo no esta programado.
        resultado = GrupoEnPacf50(
            cod_periodo=cod_periodo,
            cod_materia=cod_materia,
            num_grupo=num_grupo,
            moodle=None,
            enviado=None,
            crudo=f"'{TEXTO_SIN_INFORMACION}' con el grupo filtrado",
            existe=False,
        )
        log.warning("PACF50 dice: %s", resultado.resumen())
        return resultado
    estados, y = leida

    resultado = GrupoEnPacf50(
        cod_periodo=cod_periodo,
        cod_materia=cod_materia,
        num_grupo=num_grupo,
        moodle=sel.estado_de_imagen(estados.get(COL_MOODLE)),
        enviado=sel.estado_de_imagen(estados.get(COL_ENVIADO)),
        crudo=f"y={round(y)} {estados}",
    )
    log.info("PACF50 dice: %s", resultado.resumen())
    return resultado


#: Guion que empareja cada cabecera de MOODLE con el check que cae bajo ella en
#: la fila del grupo pedido. Por GEOMETRIA, igual que en ISEF05 e ISEF07: en
#: estas rejillas no hay relacion de DOM entre cabecera y celda.
_GUION_FILA = """
(cfg) => {
  const norm = (s) => (s||'').replace(/\\s+/g,' ').trim();

  // Cabeceras de las columnas que interesan, con su banda horizontal.
  const cols = {};
  for (const e of document.querySelectorAll('td, div, span')) {
    const t = norm(e.innerText);
    if (!cfg.columnas.includes(t)) continue;
    const r = e.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    if (!cols[t] || r.y < cols[t].y) cols[t] = {x: r.x, w: r.width, y: r.y};
  }

  // La fila del grupo: la celda cuyo texto es EXACTAMENTE el grupo pedido.
  let fila = null;
  for (const e of document.querySelectorAll('td, div, span')) {
    if (norm(e.innerText) !== cfg.grupo) continue;
    const r = e.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    // Debajo de las cabeceras: si no, es el filtro o un titulo.
    const minY = Math.max(...Object.values(cols).map(c => c.y), 0);
    if (r.y <= minY) continue;
    if (fila === null || r.y < fila.y) fila = {y: r.y, h: r.height};
  }
  if (fila === null) return {fila: null};

  // El check de cada columna dentro de la banda vertical de esa fila.
  const estados = {};
  for (const [nombre, c] of Object.entries(cols)) {
    for (const img of document.querySelectorAll('img')) {
      const r = img.getBoundingClientRect();
      if (r.width === 0) continue;
      const centroY = r.y + r.height / 2;
      const centroX = r.x + r.width / 2;
      if (Math.abs(centroY - (fila.y + fila.h / 2)) > cfg.tolerancia) continue;
      if (centroX < c.x - 4 || centroX > c.x + c.w + 4) continue;
      estados[nombre] = (img.src || '').split('/').pop();
      break;
    }
  }
  return {fila: fila.y, estados};
}
"""


def _filtro_de_grupo_aplicado(page: Page, num_grupo: str) -> bool:
    """True si el filtro de grupo sigue EDITABLE y con el numero pedido.

    Es la evidencia de que la busqueda se hizo sobre una rejilla viva: si el
    filtro se deshabilito o perdio el texto, que la fila no apareciera no dice
    nada del grupo.
    """
    try:
        caja = page.locator(CSS_FILTRO_GRUPO).first
        return caja.is_editable() and caja.input_value().strip() == num_grupo.strip()
    except (ErrorPlaywright, ErrorTiempoPlaywright):
        return False


#: Lo que dice la rejilla de grupos cuando, con el grupo en el filtro, no hay
#: ninguna fila. Visto en la captura del dueno del proceso (28/09/2026) sobre
#: POS01 / 55ES1, con el pie "0 a 0 de 0 en 0 seg.".
TEXTO_SIN_INFORMACION = "No hay información para mostrar"

#: Cabecera de la columna de grupo en la rejilla de ABAJO. El mensaje de
#: "sin informacion" tiene que estar DEBAJO de ella: la rejilla de arriba
#: tambien lo dice cuando esta vacia, y eso no habla del grupo.
CABECERA_GRUPO = "No. Grupo"

#: Veces SEGUIDAS (una por segundo) que hay que ver la rejilla vacia y sin
#: carga para darlo por bueno. Una sola vez puede ser el instante entre que
#: SmartClient borra la rejilla y pinta el resultado.
LECTURAS_VACIAS_ESTABLES = 3

#: Si SINU sigue cargando (cursor de espera, "Cargando datos"), se espera mas
#: alla de `SEG_ESPERA_REJILLA_GRUPOS`, hasta este tope. Regla del dueno del
#: proceso: "si ves que el cursor esta cargando, debes esperar". Los tiempos
#: de SINU son relativos; lo que no se hace es esperar para siempre.
SEG_TOPE_MIENTRAS_CARGA = 180.0


class _SinInformacion:
    """Marca: la rejilla de grupos dice que no hay informacion para mostrar."""


SIN_INFORMACION = _SinInformacion()

#: Guion que dice si la rejilla de grupos esta VACIA (el mensaje, debajo de la
#: cabecera "No. Grupo") y si SINU esta CARGANDO algo (texto de carga, cursor de
#: espera o indicador de progreso visible).
_GUION_ESTADO_REJILLA = """
(cfg) => {
  const norm = (s) => (s||'').replace(/\\s+/g,' ').trim();
  const caja = (e) => { const r = e.getBoundingClientRect();
                        return (r.width > 0 && r.height > 0) ? r : null; };
  const celdas = [...document.querySelectorAll('td, div, span')];

  let cabecera = null;
  for (const e of celdas) {
    if (norm(e.innerText) !== cfg.cabecera) continue;
    const r = caja(e);
    if (r && (cabecera === null || r.y < cabecera)) cabecera = r.y;
  }
  let vacia = false;
  if (cabecera !== null) {
    for (const e of celdas) {
      if (norm(e.innerText) !== cfg.sinInfo) continue;
      const r = caja(e);
      if (r && r.y > cabecera) { vacia = true; break; }
    }
  }

  let cargando = false;
  for (const e of celdas) {
    const t = norm(e.innerText);
    if (t.length > 0 && t.length < 60 && t.includes(cfg.textoCarga) && caja(e)) {
      cargando = true; break;
    }
  }
  const esperaCursor = (c) => c === 'wait' || c === 'progress';
  if (esperaCursor(getComputedStyle(document.body).cursor) ||
      esperaCursor(getComputedStyle(document.documentElement).cursor)) {
    cargando = true;
  }
  for (const e of document.querySelectorAll(cfg.cssCarga)) {
    if (caja(e)) { cargando = true; break; }
  }
  return {cabecera, vacia, cargando};
}
"""


def _leer_fila_del_grupo(
    page: Page, cfg: Config, *, num_grupo: str, objetivo: str
):
    """Espera a que la rejilla de grupos CONTESTE y devuelve lo que dijo.

    Devuelve:
      - (checks, y) si aparece LA fila del grupo pedido;
      - `SIN_INFORMACION` si la rejilla dice "No hay informacion para mostrar"
        con el grupo en el filtro, SIN nada cargando, `LECTURAS_VACIAS_ESTABLES`
        veces seguidas;
      - None si en el plazo no se ve ni lo uno ni lo otro: "no lo se".

    La fila se identifica por CONTENIDO -- el grupo que se pregunto -- y no por
    posicion: el filtro de SmartClient es 'Contiene', asi que pedir 5559
    tambien traeria 55598.

    Mientras SINU este cargando se sigue esperando, aunque pase el plazo
    normal, hasta `SEG_TOPE_MIENTRAS_CARGA`: una rejilla vacia MIENTRAS carga
    no dice nada.
    """
    from .lector_sinu import TOLERANCIA_FILA_PX

    inicio = time.monotonic()
    limite = inicio + SEG_ESPERA_REJILLA_GRUPOS
    tope = inicio + SEG_TOPE_MIENTRAS_CARGA
    vacias_seguidas = 0
    ultimo: dict = {}
    while True:
        ahora = time.monotonic()
        try:
            r = page.evaluate(
                _GUION_FILA,
                {
                    "columnas": [COL_MOODLE, COL_ENVIADO],
                    "grupo": num_grupo,
                    "tolerancia": TOLERANCIA_FILA_PX,
                },
            )
            estado = page.evaluate(
                _GUION_ESTADO_REJILLA,
                {
                    "cabecera": CABECERA_GRUPO,
                    "sinInfo": TEXTO_SIN_INFORMACION,
                    "textoCarga": sel.TEXTO_CARGANDO_GRILLA,
                    "cssCarga": sel.CSS_INDICADOR_CARGA,
                },
            )
        except ErrorPlaywright as exc:  # pragma: no cover - la SPA repinta
            log.debug("PACF50 repinto mientras se leia (%s); se reintenta.", exc)
            if ahora >= tope:
                break
            page.wait_for_timeout(1000)
            continue

        if r.get("fila") is not None and r.get("estados"):
            return r["estados"], float(r["fila"])
        ultimo = {**r, **estado}

        if estado.get("cargando"):
            # Sigue cargando: ni vacia ni llena, todavia. Se espera.
            vacias_seguidas = 0
            if ahora >= tope:
                break
        elif estado.get("vacia") and _filtro_de_grupo_aplicado(page, num_grupo):
            vacias_seguidas += 1
            if vacias_seguidas >= LECTURAS_VACIAS_ESTABLES:
                log.info(
                    "PACF50: '%s' para %s, estable y sin carga, a los %.0fs.",
                    TEXTO_SIN_INFORMACION, objetivo, ahora - inicio,
                )
                return SIN_INFORMACION
            if ahora >= tope:
                break
        else:
            vacias_seguidas = 0
            if ahora >= limite:
                break
        page.wait_for_timeout(1000)

    log.info(
        "PACF50 no contesto por %s en %.0fs (ultimo vistazo: %s).",
        objetivo, time.monotonic() - inicio, ultimo,
    )
    return None
