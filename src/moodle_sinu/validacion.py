"""Fase 1: pre-procesamiento, sanitizacion y marcado de calidad del reporte.

Se ejecuta ANTES de tocar SINU. Tres reglas, en este orden:

1. Espacios en cualquier campo   -> celda AZUL CLARO  (#ADD8E6), se sanea y continua
2. Campo obligatorio vacio       -> celda NARANJA     (#FFA500), la fila se omite
3. Duplicado con datos distintos -> fila  AMARILLO    (#FFFF00), la fila se omite

Los colores de la Fase 1 son a nivel de CELDA (reglas 1 y 2) o de FILA (regla 3).
Los colores de la Fase 2 (casos 1/2/3) son siempre a nivel de FILA, y se pintan
por debajo: una celda azul sigue viendose azul sobre una fila verde.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path

from .constantes import (
    CAMPOS_LLAVE_DUPLICADO,
    CAMPOS_OBLIGATORIOS,
    COLUMNAS_ESPERADAS,
    Color,
    Validacion,
)
from .lector_reporte import leer_reporte, tiene_anomalia_espacios
from .modelos import (
    FilaReporte,
    HallazgoCelda,
    MotivoVacio,
    ResultadoValidacion,
    TipoEspacio,
)

log = logging.getLogger(__name__)


def _motivo_vacio(crudo: str | None) -> MotivoVacio | None:
    """Por que un campo quedo vacio, o None si tiene contenido util."""
    if crudo is None:
        return MotivoVacio.CELDA_AUSENTE
    if crudo == "":
        return MotivoVacio.CADENA_VACIA
    if crudo.strip() == "":
        return MotivoVacio.SOLO_ESPACIOS
    return None


def _regla_1_espacios(fila: FilaReporte, letras: dict[str, str]) -> list[HallazgoCelda]:
    """Detecta espacios al inicio, al final o dobles internos en TODOS los campos."""
    hallazgos: list[HallazgoCelda] = []
    for campo in fila.crudos:
        crudo = fila.crudos[campo]
        if not crudo:
            continue
        inicio, final, doble = tiene_anomalia_espacios(crudo)
        if not (inicio or final or doble):
            continue
        tipos = [
            t.value
            for t, activo in (
                (TipoEspacio.INICIO, inicio),
                (TipoEspacio.FINAL, final),
                (TipoEspacio.DOBLE_INTERNO, doble),
            )
            if activo
        ]
        hallazgos.append(
            HallazgoCelda(
                fila=fila.fila,
                columna=letras.get(campo, "?"),
                campo=campo,
                color=Color.AZUL_CLARO,
                detalle="espacios: " + "+".join(tipos),
                valor_original=crudo,
                valor_saneado=fila.saneados.get(campo, ""),
            )
        )
    return hallazgos


def _regla_2_obligatorios(
    fila: FilaReporte, letras: dict[str, str]
) -> list[HallazgoCelda]:
    """Marca campos obligatorios vacios. Si hay alguno, la fila se omite."""
    hallazgos: list[HallazgoCelda] = []
    for campo in CAMPOS_OBLIGATORIOS:
        motivo = _motivo_vacio(fila.crudos.get(campo))
        if motivo is None:
            continue
        hallazgos.append(
            HallazgoCelda(
                fila=fila.fila,
                columna=letras.get(campo, "?"),
                campo=campo,
                color=Color.NARANJA,
                detalle=f"obligatorio vacio ({motivo.value})",
                valor_original=fila.crudos.get(campo),
                valor_saneado="",
            )
        )
    return hallazgos


def _regla_3_duplicados(
    filas: list[FilaReporte], letras: dict[str, str]
) -> tuple[list[HallazgoCelda], int, int]:
    """Marca duplicados de IDENTIFICACION + COD_MATERIA con datos distintos.

    La regla acordada aplica solo cuando la combinacion aparece mas de una vez
    *con datos distintos*. Los duplicados exactos (fila identica repetida) no
    los cubre la regla literal: se deduplican conservando la primera aparicion
    y se reportan aparte, para no ejecutar dos veces la misma vinculacion en
    SINU. Ese comportamiento se controla con `deduplicar_exactos`.

    Returns:
        (hallazgos, n_llaves_distintas, n_llaves_exactas)
    """
    por_llave: dict[tuple[str, ...], list[FilaReporte]] = defaultdict(list)
    for fila in filas:
        por_llave[fila.llave_duplicado].append(fila)

    hallazgos: list[HallazgoCelda] = []
    n_distintas = 0
    n_exactas = 0

    for llave, grupo in por_llave.items():
        if len(grupo) == 1:
            continue
        huellas = {f.huella for f in grupo}
        if len(huellas) > 1:
            # Duplicado con datos distintos -> amarillo, se omiten todas.
            n_distintas += 1
            for fila in grupo:
                fila.omitida = True
                fila.motivo_omision = "duplicado con datos distintos"
                fila.validacion_rpa = Validacion.DUPLICADO
                fila.color_fila = Color.AMARILLO
                for campo in CAMPOS_LLAVE_DUPLICADO:
                    hallazgos.append(
                        HallazgoCelda(
                            fila=fila.fila,
                            columna=letras.get(campo, "?"),
                            campo=campo,
                            color=Color.AMARILLO,
                            detalle=(
                                "duplicado con datos distintos "
                                f"({'+'.join(llave)}) x{len(grupo)}"
                            ),
                            valor_original=fila.crudos.get(campo),
                            valor_saneado=fila.saneados.get(campo, ""),
                        )
                    )
        else:
            # Duplicado exacto: se conserva la primera, el resto se omite.
            n_exactas += 1
            for fila in grupo[1:]:
                fila.omitida = True
                fila.motivo_omision = "duplicado exacto (se procesa la primera aparicion)"

    return hallazgos, n_distintas, n_exactas


def validar_reporte(
    ruta: str | Path,
    *,
    hoja: str | None = None,
    deduplicar_exactos: bool = True,
) -> ResultadoValidacion:
    """Ejecuta la Fase 1 completa sobre un reporte exportado de Power BI."""
    ruta = Path(ruta)
    filas, letras, nombre_hoja, pies, advertencias = leer_reporte(ruta, hoja=hoja)

    resultado = ResultadoValidacion(
        archivo=str(ruta),
        hoja=nombre_hoja,
        filas=filas,
        filas_pie_descartadas=pies,
        advertencias=list(advertencias),
    )

    # Reglas 1 y 2, fila por fila.
    for fila in filas:
        resultado.hallazgos.extend(_regla_1_espacios(fila, letras))

        vacios = _regla_2_obligatorios(fila, letras)
        if vacios:
            resultado.hallazgos.extend(vacios)
            fila.omitida = True
            campos = ", ".join(h.campo for h in vacios)
            fila.motivo_omision = f"campo obligatorio vacio: {campos}"
            fila.validacion_rpa = Validacion.DATO_INCOMPLETO

    # Regla 3 sobre las filas que siguen vivas: no tiene sentido evaluar
    # duplicidad de registros que ya quedaron fuera por datos incompletos,
    # y sus llaves podrian estar vacias y agruparse en falso.
    candidatas = [f for f in filas if not f.omitida]
    hallazgos_dup, n_distintas, n_exactas = _regla_3_duplicados(candidatas, letras)
    resultado.hallazgos.extend(hallazgos_dup)

    if not deduplicar_exactos:
        for fila in filas:
            if fila.motivo_omision and fila.motivo_omision.startswith("duplicado exacto"):
                fila.omitida = False
                fila.motivo_omision = None

    if n_exactas:
        accion = "deduplicados" if deduplicar_exactos else "procesados todos"
        resultado.advertencias.append(
            f"{n_exactas} llave(s) con duplicado exacto ({accion}). "
            "La regla amarilla literal solo cubre duplicados con datos distintos."
        )

    if pies:
        resultado.advertencias.append(
            f"Fila(s) de pie 'Filtros aplicados' descartada(s): {pies}."
        )

    faltantes_utiles = [c for c in COLUMNAS_ESPERADAS if c not in letras]
    if faltantes_utiles:  # pragma: no cover - lector ya lanza excepcion
        resultado.advertencias.append(f"Columnas faltantes: {faltantes_utiles}")

    log.info(
        "Fase 1 sobre %s: %s filas, %s procesables, %s omitidas, %s hallazgos",
        ruta.name,
        resultado.total_filas,
        len(resultado.procesables),
        len(resultado.omitidas),
        len(resultado.hallazgos),
    )
    return resultado
