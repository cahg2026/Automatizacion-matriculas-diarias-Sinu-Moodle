"""Tests de la convencion de nombres y carpetas del Drive de reportes.

Esta convencion sobrevivio al cambio de la etapa 2 de la API de Drive a RPA con
Playwright: es logica de negocio y no sabe nada del transporte. Estos tests son
los mismos que validaban la version con API.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from moodle_sinu.convencion_drive import (  # noqa: E402
    MESES,
    ReporteEnDrive,
    leer_nombre_reporte,
    nombre_local_para_subir,
    nombre_mes,
    nombre_mes_anterior,
    nombre_reporte,
    reportes_desde_nombres,
    siguiente_consecutivo,
)


class TestMeses:
    def test_mes_en_mayusculas_y_espanol(self):
        assert nombre_mes(date(2026, 8, 21)) == "AGOSTO"
        assert nombre_mes(date(2026, 9, 1)) == "SEPTIEMBRE"

    def test_los_doce_meses_estan_en_mayusculas(self):
        assert len(MESES) == 12
        assert all(m == m.upper() and m.isalpha() for m in MESES)

    def test_no_depende_del_locale(self):
        # `calendar.month_name` cambiaria con el idioma del sistema; el nombre de
        # la carpeta es parte de la convencion, no una preferencia de la maquina.
        assert nombre_mes(date(2026, 1, 5)) == "ENERO"
        assert nombre_mes(date(2026, 12, 31)) == "DICIEMBRE"

    def test_mes_anterior(self):
        assert nombre_mes_anterior(date(2026, 8, 21)) == "JULIO"

    def test_mes_anterior_en_enero_es_diciembre(self):
        # El caso que se rompe si se resta sin cuidado.
        assert nombre_mes_anterior(date(2026, 1, 3)) == "DICIEMBRE"


class TestNombreReporte:
    def test_formato(self):
        assert nombre_reporte(date(2026, 8, 21), 159) == "REPORTE 21/08/2026 #159"

    def test_dia_y_mes_con_cero_delante(self):
        assert nombre_reporte(date(2026, 1, 5), 7) == "REPORTE 05/01/2026 #7"

    def test_ida_y_vuelta(self):
        nombre = nombre_reporte(date(2026, 8, 21), 159)
        assert leer_nombre_reporte(nombre) == (date(2026, 8, 21), 159)

    def test_se_lee_aunque_lleve_extension(self):
        # En Drive un archivo aun sin convertir aparece con '.xlsx'.
        assert leer_nombre_reporte("REPORTE 21/08/2026 #159.xlsx") == (
            date(2026, 8, 21),
            159,
        )

    @pytest.mark.parametrize(
        "nombre",
        [
            "REPORTE 21/08/2026",
            "REPORTE 21-08-2026 #159",
            "Reporte diario 21/08/2026 #159",
            "REPORTE 2026/08/21 #159",
            "REPORTE  #159",
            "",
        ],
    )
    def test_nombres_ajenos_no_se_leen_como_reporte(self, nombre):
        assert leer_nombre_reporte(nombre) is None

    def test_fecha_imposible_no_se_acepta(self):
        assert leer_nombre_reporte("REPORTE 31/02/2026 #1") is None


class TestNombreLocal:
    def test_la_barra_se_sanea_para_windows(self):
        # La barra es legal en Drive pero no en un nombre de archivo de Windows.
        local = nombre_local_para_subir(date(2026, 8, 21), 159)
        assert "/" not in local
        assert local == "REPORTE 21-08-2026 #159.xlsx"

    def test_sigue_siendo_reconocible(self):
        # Si el renombrado en Drive fallara, el archivo que queda tiene que
        # poder identificarse a simple vista.
        local = nombre_local_para_subir(date(2026, 8, 21), 159)
        assert "REPORTE" in local and "159" in local and "2026" in local

    def test_no_lleva_caracteres_ilegales_en_windows(self):
        local = nombre_local_para_subir(date(2026, 12, 31), 400)
        assert not set(local) & set('<>:"/\\|?*')


class TestConsecutivo:
    def _rep(self, n, dia=21):
        return ReporteEnDrive(
            nombre=nombre_reporte(date(2026, 8, dia), n),
            fecha=date(2026, 8, dia),
            consecutivo=n,
        )

    def test_sin_reportes_devuelve_none_no_uno(self):
        # Deliberado: una lista vacia significa casi siempre que la lectura de
        # Drive fallo, no que el historico empiece hoy. Arrancar en #1 cuando el
        # real es #159 daria un nombre incorrecto que nadie revisa.
        assert siguiente_consecutivo([]) is None

    def test_toma_el_mayor_mas_uno(self):
        assert siguiente_consecutivo([self._rep(158), self._rep(159, 20)]) == 160

    def test_no_depende_del_orden(self):
        assert siguiente_consecutivo([self._rep(159), self._rep(3, 1)]) == 160


class TestLecturaDeNombres:
    def test_filtra_lo_que_no_es_reporte(self):
        nombres = [
            "REPORTE 20/08/2026 #158",
            "AGOSTO",
            "Notas del equipo",
            "REPORTE 21/08/2026 #159.xlsx",
        ]
        encontrados = reportes_desde_nombres(nombres)
        assert {r.consecutivo for r in encontrados} == {158, 159}

    def test_lista_vacia(self):
        assert reportes_desde_nombres([]) == []

    def test_un_archivo_ajeno_no_altera_el_consecutivo(self):
        # Regresion: cualquier cosa que empiece por 'REPORTE' no cuenta.
        encontrados = reportes_desde_nombres(["REPORTE anual 2026", "REPORTE 20/08/2026 #158"])
        assert siguiente_consecutivo(encontrados) == 159
