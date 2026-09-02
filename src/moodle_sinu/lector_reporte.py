"""Lectura del reporte .xlsx exportado de Power BI.

Responsabilidad unica: convertir el archivo en una lista de filas con valores
crudos y saneados. No aplica reglas de negocio ni marca colores; eso es de
`validacion.py`.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from .constantes import (
    COLUMNAS_ESPERADAS,
    MARCADOR_PIE_FILTROS,
)
from .modelos import FilaReporte

log = logging.getLogger(__name__)

#: Dos o mas espacios/tabs entre caracteres no-espacio.
_ESPACIOS_MULTIPLES = re.compile(r"\s{2,}")


class ErrorEstructuraReporte(RuntimeError):
    """El archivo no tiene la estructura esperada.

    Se lanza en vez de adivinar: un cambio de columnas en Power BI debe
    detener el proceso y alertar, no procesarse a ciegas.
    """


def a_texto(valor: object) -> str | None:
    """Normaliza una celda de openpyxl a texto, sin perder informacion.

    Devuelve None solo si la celda esta ausente o vacia. Los numeros se
    convierten sin notacion decimal espuria: openpyxl puede entregar 50609.0
    para una celda numerica, y '50609.0' no serviria como clave de busqueda
    en SINU.
    """
    if valor is None:
        return None
    if isinstance(valor, str):
        return valor
    if isinstance(valor, bool):
        return "VERDADERO" if valor else "FALSO"
    if isinstance(valor, int):
        return str(valor)
    if isinstance(valor, float):
        return str(int(valor)) if valor.is_integer() else repr(valor)
    return str(valor)


def sanear(valor: str | None) -> str:
    """Quita espacios de los bordes y colapsa espacios internos multiples.

    Es la funcion de sanitizacion de la Fase 1: se aplica al valor en memoria
    antes de enviarlo a SINU. El valor original se conserva aparte.
    """
    if valor is None:
        return ""
    return _ESPACIOS_MULTIPLES.sub(" ", valor).strip()


def tiene_anomalia_espacios(valor: str | None) -> tuple[bool, bool, bool]:
    """Devuelve (espacio_inicio, espacio_final, doble_interno)."""
    if not valor:
        return (False, False, False)
    inicio = bool(re.match(r"^\s", valor))
    final = bool(re.search(r"\s$", valor))
    doble = bool(re.search(r"\S\s{2,}\S", valor))
    return (inicio, final, doble)


def _es_fila_pie(valores: dict[str, str | None], primer_campo: str) -> bool:
    """True si la fila es el pie 'Filtros aplicados:' que agrega Power BI.

    Ese pie aparece al final de la exportacion "Datos con diseno actual":
    solo trae contenido en la primera columna y describe los filtros de la
    vista. No es un registro y debe descartarse antes de validar, o genera
    falsos positivos en las reglas de espacios y de campos obligatorios.
    """
    primero = valores.get(primer_campo)
    if primero is None or MARCADOR_PIE_FILTROS not in primero:
        return False
    resto_vacio = all(
        v is None or v.strip() == ""
        for campo, v in valores.items()
        if campo != primer_campo
    )
    return resto_vacio


def leer_reporte(
    ruta: str | Path,
    *,
    hoja: str | None = None,
) -> tuple[list[FilaReporte], dict[str, str], str, list[int], list[str]]:
    """Lee el reporte y devuelve las filas de datos.

    Returns:
        (filas, letras_por_campo, nombre_hoja, filas_pie_descartadas, advertencias)

    Raises:
        ErrorEstructuraReporte: si faltan columnas esperadas.
    """
    ruta = Path(ruta)
    if not ruta.is_file():
        raise FileNotFoundError(f"No existe el reporte: {ruta}")

    advertencias: list[str] = []
    # Modo normal (no read_only) a proposito: en read_only openpyxl entrega
    # EmptyCell para las celdas ausentes, y EmptyCell no expone .row ni
    # .column, que necesitamos para anclar los colores a la celda exacta.
    # Con volumenes de hasta unos miles de filas el costo es irrelevante.
    wb = load_workbook(ruta, data_only=True)
    try:
        ws = wb[hoja] if hoja else wb[wb.sheetnames[0]]
        nombre_hoja = ws.title
        if hoja is None and len(wb.sheetnames) > 1:
            advertencias.append(
                f"El archivo tiene {len(wb.sheetnames)} hojas "
                f"{wb.sheetnames}; se leyo '{nombre_hoja}'."
            )

        iterador = ws.iter_rows(values_only=False)

        # --- encabezado ---
        try:
            fila_encabezado = next(iterador)
        except StopIteration as exc:
            raise ErrorEstructuraReporte(f"El archivo esta vacio: {ruta}") from exc

        letras_por_campo: dict[str, str] = {}
        campos_por_indice: dict[int, str] = {}
        for celda in fila_encabezado:
            nombre = a_texto(celda.value)
            if nombre is None:
                continue
            nombre = nombre.strip()
            if not nombre:
                continue
            letra = get_column_letter(celda.column)
            letras_por_campo[nombre] = letra
            campos_por_indice[celda.column] = nombre

        faltantes = [c for c in COLUMNAS_ESPERADAS if c not in letras_por_campo]
        if faltantes:
            raise ErrorEstructuraReporte(
                "El reporte no trae las columnas esperadas. Faltan: "
                f"{faltantes}. Encontradas: {sorted(letras_por_campo)}. "
                "Revisar si cambio la vista de Power BI antes de continuar."
            )

        inesperadas = [c for c in letras_por_campo if c not in COLUMNAS_ESPERADAS]
        if inesperadas:
            advertencias.append(
                f"Columnas nuevas no contempladas en el mapeo: {inesperadas}. "
                "Se leen pero no participan en las reglas de negocio."
            )

        primer_campo = campos_por_indice[min(campos_por_indice)]

        # --- filas de datos ---
        filas: list[FilaReporte] = []
        pies: list[int] = []

        for celdas in iterador:
            if not celdas:
                continue
            num_fila = celdas[0].row

            crudos: dict[str, str | None] = {c: None for c in letras_por_campo}
            for celda in celdas:
                campo = campos_por_indice.get(celda.column)
                if campo is None:
                    continue
                crudos[campo] = a_texto(celda.value)

            if all(v is None or v.strip() == "" for v in crudos.values()):
                continue  # fila totalmente vacia

            if _es_fila_pie(crudos, primer_campo):
                pies.append(num_fila)
                log.debug("Fila %s descartada: pie 'Filtros aplicados'", num_fila)
                continue

            saneados = {campo: sanear(valor) for campo, valor in crudos.items()}
            filas.append(FilaReporte(fila=num_fila, crudos=crudos, saneados=saneados))

        return filas, letras_por_campo, nombre_hoja, pies, advertencias
    finally:
        wb.close()
