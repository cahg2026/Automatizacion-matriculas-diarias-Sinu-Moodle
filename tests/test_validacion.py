"""Tests de la Fase 1: sanitizacion y las tres reglas de calidad."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from moodle_sinu.constantes import COLUMNAS_ESPERADAS, Color, Validacion  # noqa: E402
from moodle_sinu.lector_reporte import (  # noqa: E402
    ErrorEstructuraReporte,
    a_texto,
    sanear,
    tiene_anomalia_espacios,
)
from moodle_sinu.validacion import validar_reporte  # noqa: E402

# Fila base valida, en el orden de COLUMNAS_ESPERADAS.
FILA_OK = [
    "1000132628",                        # IDENTIFICACION
    "BOHORQUEZ ROMERO ALEJANDRA",        # NOMBRE_COMPLETO
    "ALEJANDRA.BOHORQUEZR@CUN.EDU.CO",   # CORREO
    "3142939689",                        # CELULAR
    "3142939689",                        # TELEFONO
    "IV001",                             # COD_UNIDAD
    "IN001",                             # COD_PENSUM
    "A1I01",                             # COD_MATERIA
    "806589",                            # ID_GRUPO
    "50609",                             # NUM_GRUPO
    "B4",                                # BLOQUE
    "PAGO",                              # PAGO
    "26I04",                             # COD_PERIODO
    "A1I01/50609/26I04/B4/IV001/IN001",  # LLAVE
    "NO_MATRICULADO",                    # VALIDACION
]


def escribir_xlsx(tmp_path: Path, filas: list[list], *, encabezados=None) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Export"
    ws.append(list(encabezados or COLUMNAS_ESPERADAS))
    for fila in filas:
        ws.append(fila)
    ruta = tmp_path / "reporte.xlsx"
    wb.save(ruta)
    wb.close()
    return ruta


def fila(**cambios) -> list:
    """Copia de FILA_OK con campos sobreescritos por nombre de columna."""
    valores = list(FILA_OK)
    for campo, valor in cambios.items():
        valores[COLUMNAS_ESPERADAS.index(campo)] = valor
    return valores


# ---------------------------------------------------------------------------
# utilidades
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "entrada,esperado",
    [
        ("  30101", "30101"),
        ("30101  ", "30101"),
        ("JUAN   PEREZ", "JUAN PEREZ"),
        ("  JUAN   PEREZ  ", "JUAN PEREZ"),
        ("A1I01", "A1I01"),
        ("", ""),
        (None, ""),
        ("   ", ""),
        ("\tA1I01\t", "A1I01"),
    ],
)
def test_sanear(entrada, esperado):
    assert sanear(entrada) == esperado


def test_a_texto_no_agrega_decimales():
    """Un NUM_GRUPO numerico no puede convertirse en '50609.0'."""
    assert a_texto(50609) == "50609"
    assert a_texto(50609.0) == "50609"
    assert a_texto(None) is None
    assert a_texto("50609") == "50609"


@pytest.mark.parametrize(
    "valor,esperado",
    [
        (" 30101", (True, False, False)),
        ("30101 ", (False, True, False)),
        (" 30101 ", (True, True, False)),
        ("JUAN  PEREZ", (False, False, True)),
        ("30101", (False, False, False)),
        ("", (False, False, False)),
        (None, (False, False, False)),
    ],
)
def test_tiene_anomalia_espacios(valor, esperado):
    assert tiene_anomalia_espacios(valor) == esperado


# ---------------------------------------------------------------------------
# estructura
# ---------------------------------------------------------------------------


def test_columna_faltante_lanza_error(tmp_path):
    encabezados = [c for c in COLUMNAS_ESPERADAS if c != "COD_MATERIA"]
    ruta = escribir_xlsx(tmp_path, [], encabezados=encabezados)
    with pytest.raises(ErrorEstructuraReporte, match="COD_MATERIA"):
        validar_reporte(ruta)


def test_descarta_fila_pie_filtros_aplicados(tmp_path):
    pie = [""] * len(COLUMNAS_ESPERADAS)
    pie[0] = "Filtros aplicados: \ncod_periodo no es 26I01\nVALIDACION no es MATRICULADO"
    ruta = escribir_xlsx(tmp_path, [fila(), pie])

    r = validar_reporte(ruta)

    assert r.total_filas == 1, "el pie no debe contarse como registro"
    assert r.filas_pie_descartadas == [3]
    assert not r.hallazgos, "el pie no debe generar hallazgos de calidad"


# ---------------------------------------------------------------------------
# regla 1: espacios
# ---------------------------------------------------------------------------


def test_regla_1_marca_azul_y_sanea(tmp_path):
    ruta = escribir_xlsx(tmp_path, [fila(NUM_GRUPO=" 30101")])
    r = validar_reporte(ruta)

    azules = r.hallazgos_por_color(Color.AZUL_CLARO)
    assert len(azules) == 1
    assert azules[0].campo == "NUM_GRUPO"
    assert azules[0].columna == "J"
    assert azules[0].valor_original == " 30101"
    assert azules[0].valor_saneado == "30101"
    assert "inicio" in azules[0].detalle

    # la fila NO se omite: el dato se corrige y sigue
    assert len(r.procesables) == 1
    assert r.filas[0].num_grupo == "30101"


def test_regla_1_doble_espacio_interno(tmp_path):
    ruta = escribir_xlsx(tmp_path, [fila(NOMBRE_COMPLETO="JUAN   PEREZ")])
    r = validar_reporte(ruta)

    azules = r.hallazgos_por_color(Color.AZUL_CLARO)
    assert len(azules) == 1
    assert "doble-interno" in azules[0].detalle
    assert r.filas[0].nombre == "JUAN PEREZ"
    assert len(r.procesables) == 1


def test_regla_1_evalua_todos_los_campos(tmp_path):
    ruta = escribir_xlsx(tmp_path, [fila(BLOQUE=" B4", COD_PENSUM="IN001 ")])
    r = validar_reporte(ruta)
    campos = {h.campo for h in r.hallazgos_por_color(Color.AZUL_CLARO)}
    assert campos == {"BLOQUE", "COD_PENSUM"}


def test_shortname_usa_valores_saneados(tmp_path):
    ruta = escribir_xlsx(tmp_path, [fila(COD_MATERIA=" A1I01 ", NUM_GRUPO=" 50609")])
    r = validar_reporte(ruta)
    assert r.filas[0].shortname == "A1I01/50609"


# ---------------------------------------------------------------------------
# regla 2: obligatorios vacios
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "campo", ["IDENTIFICACION", "NOMBRE_COMPLETO", "CORREO", "COD_MATERIA"]
)
def test_regla_2_obligatorio_vacio_omite_fila(tmp_path, campo):
    ruta = escribir_xlsx(tmp_path, [fila(**{campo: None})])
    r = validar_reporte(ruta)

    naranjas = r.hallazgos_por_color(Color.NARANJA)
    assert len(naranjas) == 1
    assert naranjas[0].campo == campo
    assert naranjas[0].color is Color.NARANJA

    assert r.procesables == []
    assert r.filas[0].omitida is True
    assert r.filas[0].validacion_rpa is Validacion.DATO_INCOMPLETO


def test_regla_2_solo_espacios_cuenta_como_vacio(tmp_path):
    ruta = escribir_xlsx(tmp_path, [fila(CORREO="   ")])
    r = validar_reporte(ruta)

    naranjas = r.hallazgos_por_color(Color.NARANJA)
    assert len(naranjas) == 1
    assert "solo-espacios" in naranjas[0].detalle
    assert r.procesables == []


def test_regla_2_campo_no_obligatorio_vacio_no_omite(tmp_path):
    """CELULAR y TELEFONO vacios no bloquean: no se usan en SINU."""
    ruta = escribir_xlsx(tmp_path, [fila(CELULAR=None, TELEFONO=None)])
    r = validar_reporte(ruta)

    assert r.hallazgos_por_color(Color.NARANJA) == []
    assert len(r.procesables) == 1


# ---------------------------------------------------------------------------
# regla 3: duplicados
# ---------------------------------------------------------------------------


def test_regla_3_duplicado_datos_distintos_marca_amarillo_y_omite(tmp_path):
    a = fila(NUM_GRUPO="50609")
    b = fila(NUM_GRUPO="50610")  # misma IDENTIFICACION + COD_MATERIA, dato distinto
    ruta = escribir_xlsx(tmp_path, [a, b])

    r = validar_reporte(ruta)

    assert r.procesables == []
    assert len(r.filas_afectadas(Color.AMARILLO)) == 2
    for f in r.filas:
        assert f.omitida is True
        assert f.validacion_rpa is Validacion.DUPLICADO
        assert f.color_fila is Color.AMARILLO


def test_regla_3_duplicado_exacto_se_deduplica(tmp_path):
    ruta = escribir_xlsx(tmp_path, [fila(), fila()])
    r = validar_reporte(ruta)

    assert r.hallazgos_por_color(Color.AMARILLO) == [], "exacto no es amarillo"
    assert len(r.procesables) == 1, "solo la primera aparicion va a SINU"
    assert r.filas[1].omitida is True
    assert "duplicado exacto" in r.filas[1].motivo_omision


def test_regla_3_duplicado_exacto_sin_deduplicar(tmp_path):
    ruta = escribir_xlsx(tmp_path, [fila(), fila()])
    r = validar_reporte(ruta, deduplicar_exactos=False)
    assert len(r.procesables) == 2


def test_regla_3_misma_materia_distinta_identificacion_no_es_duplicado(tmp_path):
    ruta = escribir_xlsx(
        tmp_path,
        [fila(), fila(IDENTIFICACION="1000148866", CORREO="OTRO@CUN.EDU.CO")],
    )
    r = validar_reporte(ruta)
    assert r.hallazgos_por_color(Color.AMARILLO) == []
    assert len(r.procesables) == 2


def test_regla_3_ignora_filas_ya_omitidas(tmp_path):
    """Dos filas sin CORREO no deben agruparse como duplicado entre si."""
    a = fila(CORREO=None, NUM_GRUPO="50609")
    b = fila(CORREO=None, NUM_GRUPO="50610")
    ruta = escribir_xlsx(tmp_path, [a, b])

    r = validar_reporte(ruta)

    assert r.hallazgos_por_color(Color.AMARILLO) == []
    for f in r.filas:
        assert f.validacion_rpa is Validacion.DATO_INCOMPLETO


# ---------------------------------------------------------------------------
# combinaciones
# ---------------------------------------------------------------------------


def test_espacios_y_obligatorio_vacio_en_la_misma_fila(tmp_path):
    ruta = escribir_xlsx(tmp_path, [fila(NUM_GRUPO=" 30101", CORREO=None)])
    r = validar_reporte(ruta)

    assert len(r.hallazgos_por_color(Color.AZUL_CLARO)) == 1
    assert len(r.hallazgos_por_color(Color.NARANJA)) == 1
    assert r.procesables == [], "el obligatorio vacio manda: la fila se omite"


def test_reporte_vacio_sin_filas(tmp_path):
    ruta = escribir_xlsx(tmp_path, [])
    r = validar_reporte(ruta)
    assert r.total_filas == 0
    assert r.procesables == []
    assert r.hallazgos == []
