"""Tests del cerrojo de secuencia y de la lectura del Periodo desde el Sheet.

Fijan la regla del dueno del proceso (31/08/2026): el Sheet va primero, el
Periodo sale de su primera fila de datos, y si el Sheet no esta listo el
proceso se detiene en vez de abrir ISEF07 a ciegas.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from moodle_sinu.constantes import COLUMNAS_ESPERADAS, COL_VALIDACION_RPA  # noqa: E402
from moodle_sinu.periodo_sheet import (  # noqa: E402
    ErrorPeriodoSheet,
    ErrorSecuencia,
    comprobar_contra_plan,
    exigir_sheet_listo,
    periodo_de_csv,
    url_export_csv,
)

URL_SHEET = "https://docs.google.com/spreadsheets/d/1AbC_de-FGH123/edit#gid=846930886"


class PaginaFalsa:
    """Lo justo de `Page` que usa el cerrojo: `url` e `is_closed()`."""

    def __init__(self, url: str = URL_SHEET, cerrada: bool = False):
        self.url = url
        self._cerrada = cerrada

    def is_closed(self) -> bool:
        return self._cerrada


def csv_de(filas: list[list[str]], *, encabezado=None) -> str:
    cabecera = list(encabezado or (*COLUMNAS_ESPERADAS, COL_VALIDACION_RPA))
    lineas = [",".join(cabecera)]
    lineas.extend(",".join(f) for f in filas)
    return "\n".join(lineas) + "\n"


def fila_csv(periodo: str, cedula: str = "1000000101") -> list[str]:
    """Fila completa con el periodo en su columna y el resto relleno."""
    valores = ["x"] * (len(COLUMNAS_ESPERADAS) + 1)
    valores[COLUMNAS_ESPERADAS.index("IDENTIFICACION")] = cedula
    valores[COLUMNAS_ESPERADAS.index("COD_PERIODO")] = periodo
    return valores


# --------------------------------------------------------------------------
# Cerrojo de secuencia
# --------------------------------------------------------------------------


def test_sin_pestana_del_sheet_el_proceso_se_detiene():
    with pytest.raises(ErrorSecuencia, match="No hay pestana"):
        exigir_sheet_listo(None)


def test_con_la_pestana_cerrada_el_proceso_se_detiene():
    with pytest.raises(ErrorSecuencia, match="se cerro"):
        exigir_sheet_listo(PaginaFalsa(cerrada=True))


def test_si_la_pestana_no_es_un_sheet_el_proceso_se_detiene():
    """Abrir ISEF07 con la pestana equivocada es peor que no abrirla."""
    with pytest.raises(ErrorSecuencia, match="no es un documento"):
        exigir_sheet_listo(PaginaFalsa(url="https://sigwt.cun.edu.co/sgacampus/"))


def test_con_el_sheet_abierto_el_cerrojo_deja_pasar():
    pagina = PaginaFalsa()
    assert exigir_sheet_listo(pagina) is pagina


# --------------------------------------------------------------------------
# URL de exportacion
# --------------------------------------------------------------------------


def test_la_url_de_export_conserva_id_y_gid():
    """El gid importa: la hoja util no tiene por que ser la primera."""
    url = url_export_csv(URL_SHEET)
    assert "/d/1AbC_de-FGH123/export?format=csv" in url
    assert url.endswith("gid=846930886")


def test_sin_gid_en_la_url_se_asume_la_primera_hoja():
    assert url_export_csv("https://docs.google.com/spreadsheets/d/XYZ/edit").endswith(
        "gid=0"
    )


def test_una_url_que_no_es_un_sheet_falla():
    with pytest.raises(ErrorPeriodoSheet, match="no se reconoce el id|No se reconoce"):
        url_export_csv("https://sigwt.cun.edu.co/sgacampus/")


# --------------------------------------------------------------------------
# Lectura del periodo
# --------------------------------------------------------------------------


def test_lee_el_periodo_de_la_primera_fila():
    texto = csv_de([fila_csv("26A01"), fila_csv("26V05")])
    assert periodo_de_csv(texto) == "26A01"


def test_la_columna_se_busca_por_nombre_no_por_posicion():
    """La copia subida lleva VALIDACION_RPA de mas; la posicion no es estable."""
    encabezado = [COL_VALIDACION_RPA, *COLUMNAS_ESPERADAS]
    fila = ["OK"] + ["x"] * len(COLUMNAS_ESPERADAS)
    fila[1 + COLUMNAS_ESPERADAS.index("COD_PERIODO")] = "26I04"
    assert periodo_de_csv(csv_de([fila], encabezado=encabezado)) == "26I04"


def test_se_saltan_las_filas_en_blanco():
    texto = csv_de([[""] * (len(COLUMNAS_ESPERADAS) + 1), fila_csv("26V05")])
    assert periodo_de_csv(texto) == "26V05"


def test_si_falta_la_columna_de_periodo_se_detiene():
    encabezado = [c for c in COLUMNAS_ESPERADAS if c != "COD_PERIODO"]
    fila = ["x"] * len(encabezado)
    with pytest.raises(ErrorPeriodoSheet, match="no trae la columna"):
        periodo_de_csv(csv_de([fila], encabezado=encabezado))


def test_si_la_primera_fila_no_trae_periodo_se_detiene():
    """No se busca mas abajo: la primera fila ES la fuente, por el orden A-Z."""
    with pytest.raises(ErrorPeriodoSheet, match="fila 2"):
        periodo_de_csv(csv_de([fila_csv(""), fila_csv("26V05")]))


def test_un_sheet_sin_datos_se_detiene():
    with pytest.raises(ErrorPeriodoSheet, match="ninguna fila de datos"):
        periodo_de_csv(csv_de([]))


def test_un_sheet_vacio_del_todo_se_detiene():
    with pytest.raises(ErrorPeriodoSheet, match="vacio"):
        periodo_de_csv("")


# --------------------------------------------------------------------------
# Contraste con el plan local
# --------------------------------------------------------------------------


def test_si_sheet_y_plan_coinciden_no_hay_advertencias():
    assert comprobar_contra_plan("26V05", "26V05") == []


def test_la_comparacion_ignora_mayusculas_y_espacios():
    assert comprobar_contra_plan(" 26v05 ", "26V05") == []


def test_si_no_coinciden_se_advierte_pero_manda_el_sheet():
    avisos = comprobar_contra_plan("26A01", "26V05")
    assert len(avisos) == 1
    assert "26A01" in avisos[0] and "26V05" in avisos[0]


def test_un_plan_sin_lotes_se_advierte():
    assert comprobar_contra_plan("26V05", None) == [
        "El plan local no tiene lotes; no hay con que contrastar el Sheet."
    ]
