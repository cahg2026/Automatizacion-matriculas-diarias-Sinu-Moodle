"""Orden A-Z de la tabla por COD_PERIODO, dentro de la rutina de limpieza.

Por que existe
--------------
`plan_vinculacion` ya recorre los periodos de la A a la Z, pero ese orden solo
vivia en memoria: el .xlsx que se subia a Google Sheets conservaba el orden de
Power BI, que mezcla periodos linea por linea. El operador veia una tabla en un
orden y la automatizacion trabajaba en otro.

Peor: en ISEF07 el filtro de Periodo se fija una vez por sesion, asi que una
tabla con los periodos entremezclados obliga a cambiarlo constantemente. Dejar
la tabla ya agrupada hace que los bloques salgan continuos y ese cambio ocurra
una sola vez por periodo.

Que hace
--------
Reordena **solo las filas de datos** de la hoja, en el mismo conjunto de indices
que ya ocupaban. Las filas que no son datos -- el pie 'Filtros aplicados:' que
agrega Power BI, o cualquier fila en blanco -- se quedan exactamente donde
estaban.

Se mueve el contenido *y su estilo*, de modo que el marcado de la Fase 1 viaja
con su fila: una celda naranja sigue naranja despues de ordenar. Por eso este
paso va **despues** de pintar y **antes** de guardar.

Y como los numeros de fila son la identidad con la que el resto del proyecto
referencia registros (`clasificador_sinu` indexa por ellos, `plan_vinculacion`
los arrastra, el CSV de omitidas los imprime), al mover una fila se renumera
tambien el `ResultadoValidacion`. La invariante que se mantiene es: los numeros
de fila describen SIEMPRE el archivo que se acaba de escribir, que es el que el
operador va a mirar en Sheets.
"""

from __future__ import annotations

import logging
from copy import copy
from dataclasses import replace

from openpyxl.worksheet.worksheet import Worksheet

from .constantes import COL_COD_PERIODO
from .modelos import FilaReporte, ResultadoValidacion

log = logging.getLogger(__name__)

#: Atributos de estilo que viajan con la fila al moverla. `fill` es el que
#: importa (los colores de la Fase 1); el resto va para no degradar el formato
#: original de la exportacion.
_ATRIBUTOS_ESTILO: tuple[str, ...] = (
    "font",
    "fill",
    "border",
    "alignment",
    "number_format",
    "protection",
)


def clave_periodo(fila: FilaReporte) -> tuple[int, str]:
    """Clave de orden A-Z por COD_PERIODO, con los vacios al final.

    Se ordena por el valor **saneado** y en mayusculas, que es el mismo criterio
    con el que Google Sheets ordena A-Z, para que la tabla local y la subida
    coincidan. Las filas sin periodo van al final: no son ejecutables (no se
    puede fijar el filtro de Periodo en ISEF07) y estorbarian al principio.
    """
    periodo = fila.cod_periodo.strip().upper()
    return (1, "") if not periodo else (0, periodo)


def bloques_periodo(resultado: ResultadoValidacion) -> list[tuple[str, int]]:
    """Periodos y cuantas filas contiguas ocupa cada uno, en el orden actual.

    Sirve para comprobar el efecto del ordenado: si un periodo aparece dos
    veces en esta lista, el bloque quedo partido y el filtro de ISEF07 habria
    que cambiarlo de mas.
    """
    bloques: list[tuple[str, int]] = []
    for fila in sorted(resultado.filas, key=lambda f: f.fila):
        periodo = fila.cod_periodo.strip().upper() or "(sin periodo)"
        if bloques and bloques[-1][0] == periodo:
            bloques[-1] = (periodo, bloques[-1][1] + 1)
        else:
            bloques.append((periodo, 1))
    return bloques


def _instantanea(
    ws: Worksheet, num_fila: int, ultima_col: int
) -> list[tuple[object, dict[str, object]]]:
    """Valor y estilo de cada celda de una fila, para poder reescribirla."""
    instantanea: list[tuple[object, dict[str, object]]] = []
    for col in range(1, ultima_col + 1):
        celda = ws.cell(row=num_fila, column=col)
        estilo = {atributo: copy(getattr(celda, atributo)) for atributo in _ATRIBUTOS_ESTILO}
        instantanea.append((celda.value, estilo))
    return instantanea


def _volcar(
    ws: Worksheet, num_fila: int, instantanea: list[tuple[object, dict[str, object]]]
) -> None:
    for col, (valor, estilo) in enumerate(instantanea, start=1):
        celda = ws.cell(row=num_fila, column=col)
        celda.value = valor
        for atributo, valor_estilo in estilo.items():
            setattr(celda, atributo, valor_estilo)


def _renumerar(resultado: ResultadoValidacion, mapa: dict[int, int]) -> None:
    """Aplica el mapa fila_vieja -> fila_nueva al resultado de la Fase 1.

    `HallazgoCelda` es inmutable a proposito, asi que se reemplazan en vez de
    mutarse. Al terminar, filas y hallazgos quedan ordenados por numero de fila,
    que es como se leen en los informes.
    """
    for fila in resultado.filas:
        fila.fila = mapa[fila.fila]
    resultado.filas.sort(key=lambda f: f.fila)

    resultado.hallazgos[:] = [
        replace(h, fila=mapa[h.fila]) if h.fila in mapa else h
        for h in resultado.hallazgos
    ]
    resultado.hallazgos.sort(key=lambda h: (h.fila, h.columna))


def ordenar_hoja_por_periodo(
    ws: Worksheet,
    resultado: ResultadoValidacion,
    *,
    ultima_col: int,
) -> dict[int, int]:
    """Ordena A-Z por COD_PERIODO las filas de datos de `ws`, estilos incluidos.

    Args:
        ws: hoja de la copia que se va a guardar, **ya coloreada**.
        resultado: Fase 1 sobre esa misma hoja. Se renumera en el sitio.
        ultima_col: ultima columna con contenido, VALIDACION_RPA incluida.

    Returns:
        Mapa `fila_vieja -> fila_nueva` (1-based, como en el .xlsx).
    """
    if not resultado.filas:
        return {}

    # El conjunto de indices que ocupan los datos no cambia: solo se permuta
    # que fila va en cada uno. Asi el pie 'Filtros aplicados' y las filas en
    # blanco no se mueven ni hay que reservarles hueco.
    posiciones = sorted(f.fila for f in resultado.filas)
    # `sorted` es estable: dentro de un mismo periodo se conserva el orden de
    # aparicion en el reporte, que es lo que permite reanudar una corrida
    # interrumpida comparando contra el original.
    orden = sorted(resultado.filas, key=clave_periodo)
    mapa = {fila.fila: destino for fila, destino in zip(orden, posiciones)}

    movidas = sum(1 for origen, destino in mapa.items() if origen != destino)
    if movidas:
        # Se fotografia TODO antes de escribir nada: escribir sobre la marcha
        # pisaria filas que aun no se han leido.
        instantaneas = {
            fila.fila: _instantanea(ws, fila.fila, ultima_col) for fila in resultado.filas
        }
        for origen, destino in mapa.items():
            _volcar(ws, destino, instantaneas[origen])

    _renumerar(resultado, mapa)

    bloques = bloques_periodo(resultado)
    log.info(
        "Orden A-Z por %s: %s filas movidas, %s bloques contiguos (%s periodos distintos).",
        COL_COD_PERIODO,
        movidas,
        len(bloques),
        len({p for p, _ in bloques}),
    )
    for periodo, n in bloques:
        log.debug("  bloque %-12s %s filas", periodo, n)
    return mapa
