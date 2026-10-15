"""El marcado morado: las unidades que quedaron A MEDIAS en SINU.

Rojo y morado no son lo mismo y por eso existe este marcado: rojo es "se
intento y no se pudo, SINU quedo como estaba"; morado es "se dejo el ciclo a
medias y el estudiante quedo desvinculado".

Morado y no naranja porque el naranja ya era "campo obligatorio vacio" de la
Fase 1, y tampoco lila, que es "sin matricula academica".
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from openpyxl import Workbook

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from moodle_sinu.constantes import (  # noqa: E402
    COL_COD_MATERIA,
    COL_COD_PERIODO,
    COL_IDENTIFICACION,
    COL_NUM_GRUPO,
    COL_VALIDACION_RPA,
    Color,
)


def _cargar():
    ruta = RAIZ / "scripts" / "marcar_validacion_manual.py"
    spec = importlib.util.spec_from_file_location("marcar_validacion_manual", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


mv = _cargar()


def _libro(filas):
    """Una hoja con los encabezados reales del reporte."""
    wb = Workbook()
    ws = wb.active
    cabecera = [
        COL_IDENTIFICACION,
        COL_COD_MATERIA,
        COL_NUM_GRUPO,
        COL_COD_PERIODO,
        COL_VALIDACION_RPA,
    ]
    ws.append(cabecera)
    for f in filas:
        ws.append(f)
    return ws


def _escribir_libro_ciclos(tmp_path, apuntes):
    ruta = tmp_path / "ciclos_abiertos.jsonl"
    ruta.write_text(
        "\n".join(json.dumps(a, ensure_ascii=False) for a in apuntes) + "\n",
        encoding="utf-8",
    )
    return ruta


class TestCiclosAbiertos:
    def test_un_ciclo_cerrado_no_sale(self, tmp_path):
        ruta = _escribir_libro_ciclos(
            tmp_path,
            [
                {"momento": "2026-09-23T10:00", "identificacion": "1", "cod_periodo": "26ES5", "materia": "ESP168/55ES2", "estado": "desvinculando"},
                {"momento": "2026-09-23T10:01", "identificacion": "1", "cod_periodo": "26ES5", "materia": "ESP168/55ES2", "estado": "cerrado"},
            ],
        )
        assert mv.ciclos_abiertos(ruta, dir_logs=tmp_path) == []

    def test_manda_el_ultimo_apunte_no_el_estado_suelto(self, tmp_path):
        """El libro es append-only: filtrar por estado sin agrupar daria por
        abierto un ciclo que se cerro tres lineas mas abajo."""
        ruta = _escribir_libro_ciclos(
            tmp_path,
            [
                {"momento": "2026-09-23T10:00", "identificacion": "1", "cod_periodo": "26ES5", "materia": "ESP168/55ES2", "estado": "desvinculando"},
                {"momento": "2026-09-23T10:01", "identificacion": "1", "cod_periodo": "26ES5", "materia": "ESP168/55ES2", "estado": "desvinculado-pendiente-vincular"},
                {"momento": "2026-09-23T10:02", "identificacion": "1", "cod_periodo": "26ES5", "materia": "ESP168/55ES2", "estado": "cerrado"},
            ],
        )
        assert mv.ciclos_abiertos(ruta, dir_logs=tmp_path) == []

    def test_el_que_quedo_a_medias_si_sale(self, tmp_path):
        ruta = _escribir_libro_ciclos(
            tmp_path,
            [
                {"momento": "2026-09-23T10:00", "identificacion": "1000000001", "cod_periodo": "26ES5", "materia": "ESP168/55ES2", "estado": "desvinculado-pendiente-vincular"},
            ],
        )
        abiertos = mv.ciclos_abiertos(ruta, dir_logs=tmp_path)
        assert len(abiertos) == 1
        assert abiertos[0]["identificacion"] == "1000000001"

    def test_los_apuntes_viejos_sin_materia_no_se_pierden(self, tmp_path):
        """25 de los 984 apuntes del 23/09/2026 no traian 'materia'. Perder un
        aviso por un cambio de formato seria lo contrario de para lo que existe
        este libro."""
        ruta = _escribir_libro_ciclos(
            tmp_path,
            [{"momento": "2026-09-21T12:43", "identificacion": "30000003", "cod_periodo": "26ES5", "estado": "desvinculando"}],
        )
        assert len(mv.ciclos_abiertos(ruta, dir_logs=tmp_path)) == 1

    def test_una_linea_corrupta_no_tumba_el_resto(self, tmp_path):
        ruta = tmp_path / "c.jsonl"
        ruta.write_text(
            '{"momento": "2026-09-23T10:00", "identificacion": "1", "cod_periodo": "26ES5", "materia": "A/1", "estado": "desvinculando"}\n'
            "{ esto no es json\n",
            encoding="utf-8",
        )
        assert len(mv.ciclos_abiertos(ruta, dir_logs=tmp_path)) == 1

    def test_sin_libro_devuelve_vacio(self, tmp_path):
        assert mv.ciclos_abiertos(tmp_path / "no_existe.jsonl", dir_logs=tmp_path) == []

    def test_salen_del_mas_viejo_al_mas_nuevo(self, tmp_path):
        ruta = _escribir_libro_ciclos(
            tmp_path,
            [
                {"momento": "2026-09-23T15:02", "identificacion": "2", "cod_periodo": "26ES5", "materia": "B/1", "estado": "desvinculando"},
                {"momento": "2026-09-21T12:43", "identificacion": "1", "cod_periodo": "26ES5", "materia": "A/1", "estado": "desvinculando"},
            ],
        )
        assert [d["identificacion"] for d in mv.ciclos_abiertos(ruta, dir_logs=tmp_path)] == ["1", "2"]


class TestLaPaleta:
    def test_ningun_color_repite_valor(self):
        """La guarda de esta conversacion: el morado nacio porque el naranja
        ya era 'campo obligatorio vacio' y el lila 'sin matricula academica'.
        Reusar un color no rompe ninguna prueba, solo hace ilegible el reporte
        para quien lo valida, asi que la unicidad se comprueba aqui."""
        valores = [c.value for c in Color]
        assert len(valores) == len(set(valores))

    def test_el_morado_no_se_confunde_con_el_lila(self):
        assert Color.MORADO.value != Color.LILA.value


class TestMarcar:
    def test_pinta_morado_y_deja_el_motivo(self):
        ws = _libro([["1000000001", "ESP168", "55ES2", "26ES5", "REVISAR - fallo-tecnico"]])
        pintadas, no_ubicadas = mv.marcar(
            ws,
            [{"momento": "2026-09-23T15:02:42", "identificacion": "1000000001", "cod_periodo": "26ES5", "materia": "ESP168/55ES2", "estado": "desvinculado-pendiente-vincular"}],
        )
        assert (pintadas, no_ubicadas) == (1, [])
        assert Color.MORADO.value in ws.cell(row=2, column=1).fill.start_color.rgb
        texto = ws.cell(row=2, column=5).value
        assert "VALIDAR A MANO" in texto
        assert "desvinculado-pendiente-vincular" in texto

    def test_pisa_el_REVISAR_del_paso_5(self):
        """Morado manda sobre rojo: dice mas y es mas urgente."""
        ws = _libro([["1", "ESP168", "55ES2", "26ES5", "REVISAR - fallo-tecnico"]])
        mv.marcar(ws, [{"momento": "2026-09-23T15:02", "identificacion": "1", "cod_periodo": "26ES5", "materia": "ESP168/55ES2", "estado": "desvinculando"}])
        assert "REVISAR" not in ws.cell(row=2, column=5).value

    def test_no_toca_las_demas_filas(self):
        ws = _libro([
            ["111", "MAT01", "55ES2", "26ES5", "VINCULADA Y VALIDADA"],
            ["222", "ESP168", "55ES2", "26ES5", "REVISAR"],
        ])
        mv.marcar(ws, [{"momento": "2026-09-23T15:02", "identificacion": "222", "cod_periodo": "26ES5", "materia": "ESP168/55ES2", "estado": "desvinculando"}])
        assert ws.cell(row=2, column=5).value == "VINCULADA Y VALIDADA"

    def test_un_ciclo_de_otro_dia_que_no_esta_en_el_reporte_se_reporta(self):
        """No se adivina: si la unidad no esta en ESTE reporte se dice, porque
        un ciclo abierto puede venir de una corrida de otro dia."""
        ws = _libro([["111", "MAT01", "55ES2", "26ES5", ""]])
        pintadas, no_ubicadas = mv.marcar(
            ws,
            [{"momento": "2026-09-21T12:43", "identificacion": "30000003", "cod_periodo": "26ES5", "materia": "ESPS28/55ES1", "estado": "desvinculando"}],
        )
        assert pintadas == 0
        assert len(no_ubicadas) == 1
        assert "30000003" in no_ubicadas[0]

    def test_no_pinta_la_fila_de_otra_materia_de_la_misma_cedula(self):
        """La guarda que importa: la misma cedula tiene varias materias, y
        pintar la equivocada es del mismo tipo de error que operar sobre la
        matricula equivocada."""
        ws = _libro([
            ["1000000001", "MAT01", "55ES2", "26ES5", ""],
            ["1000000001", "ESP168", "55ES2", "26ES5", ""],
        ])
        pintadas, _ = mv.marcar(
            ws,
            [{"momento": "2026-09-23T15:02", "identificacion": "1000000001", "cod_periodo": "26ES5", "materia": "ESP168/55ES2", "estado": "desvinculando"}],
        )
        assert pintadas == 1
        assert ws.cell(row=2, column=5).value in (None, "")
        assert "VALIDAR A MANO" in ws.cell(row=3, column=5).value

    def test_crea_la_columna_si_el_reporte_no_la_trae(self):
        wb = Workbook()
        ws = wb.active
        ws.append([COL_IDENTIFICACION, COL_COD_MATERIA, COL_COD_PERIODO])
        ws.append(["1", "ESP168", "26ES5"])
        mv.marcar(ws, [{"momento": "2026-09-23T15:02", "identificacion": "1", "cod_periodo": "26ES5", "materia": "ESP168/55ES2", "estado": "desvinculando"}])
        cabeceras = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]
        assert COL_VALIDACION_RPA in cabeceras


class TestElCruceConElDiario:
    """El filtro que hace util al script.

    El libro de ciclos miente por exceso: cuando un ciclo se repara con un
    'vincular' suelto, nadie vuelve a escribir el 'cerrado' y el apunte se
    queda abierto para siempre. El 23/09/2026 el libro daba 4 ciclos abiertos
    y solo 1 era real.
    """

    def _diario(self, tmp_path, apuntes, nombre="resultados_etapa4.jsonl"):
        (tmp_path / nombre).write_text(
            "\n".join(json.dumps(a, ensure_ascii=False) for a in apuntes) + "\n",
            encoding="utf-8",
        )

    def test_un_verde_posterior_cierra_el_ciclo(self, tmp_path):
        """Caso 1000000001: el libro lo da por abierto a las 15:02 y el diario
        lo tiene verde a las 15:21. El estudiante esta perfecto."""
        ruta = _escribir_libro_ciclos(
            tmp_path,
            [{"momento": "2026-09-23T15:02:42", "identificacion": "1000000001", "cod_periodo": "26ES5", "materia": "ESP168/55ES2", "estado": "desvinculado-pendiente-vincular"}],
        )
        self._diario(
            tmp_path,
            [{"momento": "2026-09-23T15:21:00", "identificacion": "1000000001", "cod_periodo": "26ES5", "objetivo": "ESP168/55ES2", "veredicto": "verde"}],
        )
        assert mv.ciclos_abiertos(ruta, dir_logs=tmp_path) == []

    def test_el_verde_vale_aunque_sea_de_otro_dia(self, tmp_path):
        """Caso 30000001: ciclo abierto el 21/09, reparado el 22/09. Mirar solo
        el diario vivo lo habria marcado dos dias despues de estar sano."""
        ruta = _escribir_libro_ciclos(
            tmp_path,
            [{"momento": "2026-09-21T14:57", "identificacion": "30000001", "cod_periodo": "26V05", "materia": "61102/55582", "estado": "desvinculando"}],
        )
        self._diario(
            tmp_path,
            [{"momento": "2026-09-22T10:16", "identificacion": "30000001", "cod_periodo": "26V05", "objetivo": "61102/55582", "veredicto": "verde"}],
            nombre="resultados_etapa4_20260922.jsonl",
        )
        assert mv.ciclos_abiertos(ruta, dir_logs=tmp_path) == []

    def test_un_rojo_posterior_NO_cierra_el_ciclo(self, tmp_path):
        """Caso 30000003: hay apuntes posteriores, pero en rojo. Sigue roto."""
        ruta = _escribir_libro_ciclos(
            tmp_path,
            [{"momento": "2026-09-21T12:43", "identificacion": "30000003", "cod_periodo": "26ES5", "materia": "ESPS28/55ES1", "estado": "desvinculando"}],
        )
        self._diario(
            tmp_path,
            [{"momento": "2026-09-21T14:12", "identificacion": "30000003", "cod_periodo": "26ES5", "objetivo": "ESPS28/55ES1", "veredicto": "rojo"}],
        )
        assert len(mv.ciclos_abiertos(ruta, dir_logs=tmp_path)) == 1

    def test_un_verde_ANTERIOR_no_cierra_nada(self, tmp_path):
        """El orden importa: estar verde ayer no arregla un ciclo roto hoy."""
        ruta = _escribir_libro_ciclos(
            tmp_path,
            [{"momento": "2026-09-23T15:02", "identificacion": "1", "cod_periodo": "26ES5", "materia": "A/1", "estado": "desvinculado-pendiente-vincular"}],
        )
        self._diario(
            tmp_path,
            [{"momento": "2026-09-22T09:00", "identificacion": "1", "cod_periodo": "26ES5", "objetivo": "A/1", "veredicto": "verde"}],
        )
        assert len(mv.ciclos_abiertos(ruta, dir_logs=tmp_path)) == 1

    def test_el_verde_de_OTRA_materia_no_cierra_este_ciclo(self, tmp_path):
        """La misma cedula tiene varias materias; el verde de una no dice nada
        de la otra."""
        ruta = _escribir_libro_ciclos(
            tmp_path,
            [{"momento": "2026-09-23T15:02", "identificacion": "1", "cod_periodo": "26ES5", "materia": "ESP168/55ES2", "estado": "desvinculado-pendiente-vincular"}],
        )
        self._diario(
            tmp_path,
            [{"momento": "2026-09-23T15:30", "identificacion": "1", "cod_periodo": "26ES5", "objetivo": "MAT01/55ES2", "veredicto": "verde"}],
        )
        assert len(mv.ciclos_abiertos(ruta, dir_logs=tmp_path)) == 1

    def test_el_escenario_real_del_23_09(self, tmp_path):
        """Los 4 del libro, tal cual estaban. Solo 30000003 es real."""
        ruta = _escribir_libro_ciclos(
            tmp_path,
            [
                {"momento": "2026-09-21T12:43", "identificacion": "30000003", "cod_periodo": "26ES5", "materia": "ESPS28/55ES1", "estado": "desvinculando"},
                {"momento": "2026-09-21T14:57", "identificacion": "30000001", "cod_periodo": "26V05", "materia": "61102/55582", "estado": "desvinculando"},
                {"momento": "2026-09-23T15:02", "identificacion": "1000000001", "cod_periodo": "26ES5", "materia": "ESP168/55ES2", "estado": "desvinculado-pendiente-vincular"},
                {"momento": "2026-09-23T16:30", "identificacion": "1000000002", "cod_periodo": "26ES5", "materia": "ESP168/55ES2", "estado": "desvinculado-pendiente-vincular"},
            ],
        )
        self._diario(
            tmp_path,
            [
                {"momento": "2026-09-21T14:12", "identificacion": "30000003", "cod_periodo": "26ES5", "objetivo": "ESPS28/55ES1", "veredicto": "rojo"},
                {"momento": "2026-09-22T10:16", "identificacion": "30000001", "cod_periodo": "26V05", "objetivo": "61102/55582", "veredicto": "verde"},
                {"momento": "2026-09-23T15:21", "identificacion": "1000000001", "cod_periodo": "26ES5", "objetivo": "ESP168/55ES2", "veredicto": "verde"},
                {"momento": "2026-09-23T16:31", "identificacion": "1000000002", "cod_periodo": "26ES5", "objetivo": "ESP168/55ES2", "veredicto": "verde"},
            ],
        )
        abiertos = mv.ciclos_abiertos(ruta, dir_logs=tmp_path)
        assert [d["identificacion"] for d in abiertos] == ["30000003"]
