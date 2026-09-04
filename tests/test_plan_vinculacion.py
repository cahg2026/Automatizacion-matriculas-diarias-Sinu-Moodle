"""Tests del plan de vinculacion en SINU.

Fijan las dos reglas del proceso que no se deducen del reporte: la unidad de
trabajo es **(cedula, materia)** -- una operacion por fila -- y el periodo se
fija una vez por sesion (de ahi la agrupacion por lotes).

La primera cambio el 03/09/2026. Antes la unidad era el estudiante, porque se
creia que ISEF07 vinculaba todas sus asignaturas de golpe; esa premisa venia de
la referencia de negocio, era falsa, y agrupar por cedula era justo lo que hacia
perder la materia de vista.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from moodle_sinu.constantes import (  # noqa: E402
    COL_COD_MATERIA,
    COL_COD_PERIODO,
    COL_IDENTIFICACION,
    COL_NOMBRE_COMPLETO,
)
from moodle_sinu.modelos import FilaReporte, ResultadoValidacion  # noqa: E402
from moodle_sinu.plan_vinculacion import (  # noqa: E402
    construir_plan,
    estimar_duracion,
    extraer_cedulas,
    formatear_plan,
)


def _fila(n, cedula, periodo="26V05", materia="A1I01", nombre="ALUMNO X", omitida=False):
    saneados = {
        COL_IDENTIFICACION: cedula,
        COL_NOMBRE_COMPLETO: nombre,
        COL_COD_MATERIA: materia,
        COL_COD_PERIODO: periodo,
    }
    return FilaReporte(
        fila=n, crudos=dict(saneados), saneados=saneados, omitida=omitida
    )


def _resultado(filas):
    return ResultadoValidacion(archivo="x.xlsx", hoja="Export", filas=filas)


class TestExtraerCedulas:
    def test_unicas_en_orden_de_aparicion(self):
        filas = [_fila(2, "111"), _fila(3, "222"), _fila(4, "111"), _fila(5, "333")]
        assert extraer_cedulas(filas) == ["111", "222", "333"]

    def test_ignora_cedulas_vacias(self):
        filas = [_fila(2, "111"), _fila(3, "")]
        assert extraer_cedulas(filas) == ["111"]

    def test_el_orden_no_es_alfabetico(self):
        # La referencia pide conservar el orden de aparicion: permite reanudar
        # una corrida interrumpida comparando contra el reporte.
        filas = [_fila(2, "999"), _fila(3, "111")]
        assert extraer_cedulas(filas) == ["999", "111"]


class TestUnidadDeTrabajo:
    """La unidad es (cedula, materia): una operacion por fila del reporte."""

    def test_un_estudiante_con_varias_materias_son_varias_operaciones(self):
        """La correccion del 03/09/2026.

        Antes esto era UNA operacion, porque se creia que un solo vincular
        cubria las tres asignaturas. Cuesta el triple, y toca exactamente lo
        que el reporte pide.
        """
        filas = [
            _fila(2, "111", materia="A1I01"),
            _fila(3, "111", materia="B2J02"),
            _fila(4, "111", materia="C3K03"),
        ]
        plan = construir_plan(_resultado(filas))
        assert plan.n_operaciones == 3
        assert plan.n_filas_cubiertas == 3
        operaciones = plan.lotes[0].operaciones
        assert [o.cod_materia for o in operaciones] == ["A1I01", "B2J02", "C3K03"]
        assert [o.fila for o in operaciones] == [2, 3, 4]
        assert all(o.n_materias == 1 for o in operaciones)

    def test_las_filas_omitidas_no_entran(self):
        filas = [_fila(2, "111"), _fila(3, "222", omitida=True)]
        plan = construir_plan(_resultado(filas))
        assert plan.cedulas_unicas == ["111"]

    def test_el_mismo_estudiante_en_dos_periodos_son_dos_operaciones(self):
        # Cada periodo es una sesion con su filtro fijado, asi que hay que
        # pasar por el estudiante una vez en cada una.
        filas = [_fila(2, "111", periodo="26V05"), _fila(3, "111", periodo="26I04")]
        plan = construir_plan(_resultado(filas))
        assert plan.n_operaciones == 2
        assert plan.cedulas_unicas == ["111"]  # un solo estudiante distinto


class TestAgrupacionPorPeriodo:
    def test_un_lote_por_periodo(self):
        filas = [
            _fila(2, "111", periodo="26V05"),
            _fila(3, "222", periodo="26V05"),
            _fila(4, "333", periodo="26I04"),
        ]
        plan = construir_plan(_resultado(filas))
        assert plan.n_periodos == 2
        assert {l.cod_periodo for l in plan.lotes} == {"26V05", "26I04"}

    def test_los_lotes_van_en_orden_alfabetico(self):
        # Decision del 24/08/2026: A-Z por COD_PERIODO, el mismo orden que deja
        # el Google Sheet al ordenar esa columna. Antes iban por tamano.
        filas = [
            _fila(2, "111", periodo="26V05"),
            _fila(3, "222", periodo="2026C"),
            _fila(4, "333", periodo="26I04"),
        ]
        plan = construir_plan(_resultado(filas))
        assert [l.cod_periodo for l in plan.lotes] == ["2026C", "26I04", "26V05"]

    def test_el_tamano_del_lote_ya_no_altera_el_orden(self):
        # Regresion: el lote grande va despues si su codigo es posterior.
        filas = [
            _fila(2, "111", periodo="ZZZ"),
            _fila(3, "222", periodo="ZZZ"),
            _fila(4, "333", periodo="AAA"),
        ]
        plan = construir_plan(_resultado(filas))
        assert [l.cod_periodo for l in plan.lotes] == ["AAA", "ZZZ"]

    def test_el_primer_lote_es_el_periodo_actual(self):
        # La automatizacion toma el primer grupo como "periodo actual".
        filas = [_fila(2, "111", periodo="26V05"), _fila(3, "222", periodo="2026C")]
        plan = construir_plan(_resultado(filas))
        assert plan.lotes[0].cod_periodo == "2026C"

    def test_dentro_del_lote_se_conserva_el_orden_del_reporte(self):
        filas = [
            _fila(2, "999"),
            _fila(3, "111"),
            _fila(4, "555"),
        ]
        plan = construir_plan(_resultado(filas))
        assert plan.lotes[0].cedulas == ["999", "111", "555"]

    def test_sin_periodo_queda_fuera_del_plan_automatico(self):
        # Sin COD_PERIODO no se puede fijar el filtro: no es ejecutable.
        filas = [_fila(2, "111", periodo=""), _fila(3, "222", periodo="26V05")]
        plan = construir_plan(_resultado(filas))
        assert len(plan.sin_periodo) == 1
        assert plan.sin_periodo[0].identificacion == "111"
        assert plan.n_operaciones == 1  # solo la que si tiene periodo

    def test_las_operaciones_sin_periodo_se_avisan_en_el_resumen(self):
        filas = [_fila(2, "111", periodo=""), _fila(3, "222", periodo="26V05")]
        texto = formatear_plan(construir_plan(_resultado(filas)))
        assert "SIN COD_PERIODO" in texto


class TestEstimacion:
    def test_crece_con_el_numero_de_operaciones(self):
        assert estimar_duracion(2) > estimar_duracion(1)

    def test_el_maximo_supera_al_minimo(self):
        minimo, maximo = estimar_duracion(10)
        assert maximo > minimo

    def test_refleja_los_tiempos_de_la_referencia(self):
        # 1-2s de filtro + 15-40s de ejecucion por estudiante.
        minimo, maximo = estimar_duracion(1)
        assert (minimo, maximo) == (16, 42)

    def test_sin_operaciones_es_cero(self):
        assert estimar_duracion(0) == (0, 0)


class TestResumen:
    def test_menciona_las_operaciones_y_los_periodos(self):
        filas = [_fila(2, "111"), _fila(3, "222", periodo="26I04")]
        texto = formatear_plan(construir_plan(_resultado(filas)))
        assert "26V05" in texto and "26I04" in texto
        assert "ISEF07" in texto

    def test_avisa_de_los_estudiantes_con_varias_materias(self):
        filas = [_fila(2, "111", materia="A"), _fila(3, "111", materia="B")]
        texto = formatear_plan(construir_plan(_resultado(filas)))
        assert "mas de una asignatura" in texto.lower()
        # Y deja claro que son operaciones separadas, no una sola pasada.
        assert "aparte" in texto.lower()

    def test_plan_vacio_no_revienta(self):
        texto = formatear_plan(construir_plan(_resultado([])))
        assert "0" in texto


class TestPieDelReporte:
    """El fallo del script original de la skill.

    `extract_cedulas.py` lee la columna en crudo, asi que sobre una exportacion
    de Power BI se traga la fila de pie 'Filtros aplicados:' como si fuera una
    cedula (comprobado el 21/08/2026: 237 'cedulas', una de ellas 'pago es
    PAGO'). Nuestro parser la descarta antes, de modo que no puede pasar.
    """

    def test_el_pie_nunca_llega_al_plan(self, tmp_path):
        from openpyxl import Workbook

        from moodle_sinu.constantes import COLUMNAS_ESPERADAS, MARCADOR_PIE_FILTROS
        from moodle_sinu.validacion import validar_reporte

        ruta = tmp_path / "con_pie.xlsx"
        wb = Workbook()
        ws = wb.active
        ws.append(list(COLUMNAS_ESPERADAS))
        fila = ["1000132628", "ALUMNO UNO", "a@cun.edu.co", "", "", "IV001",
                "IN001", "A1I01", "806589", "50609", "B4", "PAGO", "26I04",
                "llave", "NO_MATRICULADO"]
        ws.append(fila)
        ws.append([f"{MARCADOR_PIE_FILTROS} pago es PAGO"])
        wb.save(ruta)

        plan = construir_plan(validar_reporte(ruta))
        assert plan.cedulas_unicas == ["1000132628"]
        assert not any("PAGO" in c for c in plan.cedulas_unicas)
