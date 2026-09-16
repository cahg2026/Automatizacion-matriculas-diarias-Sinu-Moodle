"""Tests de la consulta a ISEF05: tiene el grupo curso en MOODLE?

Los datos de referencia se midieron sobre la pantalla real el 16/09/2026:

    26V05 DTA32 grupo 55598   curso=no  usuarios=no  vinculacion=no  semilla=no
    26V05 AED31 grupo 55522   curso=si  usuarios=si  vinculacion=si  semilla=si

El primero llevaba fallando el 07, el 15 y el 16/09 con cuatro estudiantes; el
segundo salio verde el 16. Es la pareja que demuestra que la columna distingue
los dos casos, y por eso son los valores que se prueban aqui.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from moodle_sinu.lector_isef05 import GrupoEnMoodle  # noqa: E402


def _grupo(**cambios) -> GrupoEnMoodle:
    base = dict(
        cod_periodo="26V05",
        cod_materia="DTA32",
        num_grupo="55598",
        curso=False,
        usuarios=False,
        vinculacion=False,
        semilla=False,
    )
    return GrupoEnMoodle(**{**base, **cambios})


# ---------------------------------------------------------------------------
# La pregunta que decide saltar unidades
# ---------------------------------------------------------------------------


def test_sin_curso_vincular_es_imposible():
    """El caso medido: DTA32/55598 no tiene curso, asi que no hay que intentarlo."""
    assert _grupo().vincular_es_imposible is True


def test_con_curso_se_procesa_normal():
    """AED31/55522: tiene curso y salio verde el mismo dia."""
    assert _grupo(curso=True, usuarios=True).vincular_es_imposible is False


def test_check_ilegible_NO_es_lo_mismo_que_sin_curso():
    """La regla central de este modulo.

    `None` significa "no se pudo leer", no "no tiene". Tratarlo como un no
    marcaria unidades en rojo sin haberlo comprobado, y sin intentarlas
    siquiera -- que es peor que el problema que este modulo resuelve, porque
    falla en silencio y del lado que no toca.
    """
    assert _grupo(curso=None).vincular_es_imposible is False


def test_solo_manda_la_columna_del_curso():
    """Las otras tres columnas son informativas y no deciden nada.

    Un grupo con curso creado pero sin usuarios todavia sincronizados es un
    caso transitorio normal: ahi vincular puede funcionar, y saltarlo seria
    dejar trabajo sin hacer.
    """
    g = _grupo(curso=True, usuarios=False, vinculacion=False, semilla=False)
    assert g.vincular_es_imposible is False


# ---------------------------------------------------------------------------
# Identidad y presentacion
# ---------------------------------------------------------------------------


def test_objetivo_usa_el_formato_del_reporte():
    """'MATERIA/GRUPO' es la clave con la que el flujo indexa las unidades."""
    assert _grupo().objetivo == "DTA32/55598"


def test_resumen_distingue_los_tres_estados():
    texto = _grupo(curso=True, usuarios=False, vinculacion=None).resumen()
    assert "curso=si" in texto
    assert "usuarios=NO" in texto
    assert "vinculacion=ilegible" in texto


def test_resumen_lleva_periodo_y_objetivo():
    """El resumen acaba en el Sheet y en el aviso: tiene que bastarse solo."""
    texto = _grupo().resumen()
    assert "26V05" in texto
    assert "DTA32/55598" in texto
