"""Tests de la lectura del estado de un check en la grilla Grupos.

Los nombres de imagen NO son convencion: se contaron sobre ISEF07 el
01/09/2026 recorriendo 11 estudiantes de tres periodos.

    checked.gif           19   marcado
    unchecked.gif         22   desmarcado
    checked_Disabled.gif  11   marcado y no editable
    unsetcheck.gif         7   sin definir
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from moodle_sinu.selectores_sinu import (  # noqa: E402
    IMG_CHECK_DESMARCADO,
    IMG_CHECK_MARCADO,
    IMG_CHECK_MARCADO_BLOQUEADO,
    IMG_CHECK_SIN_DEFINIR,
    estado_de_imagen,
)

BASE = "https://sigwt.cun.edu.co/sgacampus/isomorphic/skins/Enterprise/images/CheckboxItem/"


def test_marcado():
    assert estado_de_imagen(BASE + IMG_CHECK_MARCADO) is True


def test_desmarcado():
    assert estado_de_imagen(BASE + IMG_CHECK_DESMARCADO) is False


def test_marcado_bloqueado_sigue_siendo_marcado():
    """'Curso en moodle?' es informativo y se pinta deshabilitado. Leerlo como
    desmarcado invertiria el arbol de decision de la Fase 2."""
    assert estado_de_imagen(BASE + IMG_CHECK_MARCADO_BLOQUEADO) is True


def test_sin_definir_es_ilegible_no_desmarcado():
    """Regla del proyecto: un check ilegible NO es un check desmarcado."""
    assert estado_de_imagen(BASE + IMG_CHECK_SIN_DEFINIR) is None


def test_una_imagen_desconocida_es_ilegible():
    """Si SINU introduce un estado nuevo, no puede leerse como un 'no'."""
    assert estado_de_imagen(BASE + "estado_nuevo_de_sinu.gif") is None


def test_sin_src_es_ilegible():
    assert estado_de_imagen(None) is None
    assert estado_de_imagen("") is None


def test_se_ignora_la_cadena_de_consulta():
    """SmartClient anade sufijos de cache a los src."""
    assert estado_de_imagen(BASE + IMG_CHECK_MARCADO + "?v=12") is True


def test_se_ignora_la_ruta():
    """Solo cuenta el nombre del archivo: la carpeta de skin puede cambiar."""
    assert estado_de_imagen("/otra/ruta/" + IMG_CHECK_MARCADO) is True


def test_desmarcado_bloqueado_es_desmarcado():
    """Hallado el 01/09/2026 en el estudiante 1000000103: sus 8 asignaturas
    tenian 'Vinculado?' = unchecked_Disabled. Sin este nombre, las 8 filas se
    descartaban como ilegibles -- y son justo las que hay que vincular."""
    from moodle_sinu.selectores_sinu import IMG_CHECK_DESMARCADO_BLOQUEADO

    assert estado_de_imagen(BASE + IMG_CHECK_DESMARCADO_BLOQUEADO) is False


def test_el_sufijo_disabled_no_cambia_el_valor():
    """'_Disabled' dice si el control se puede pulsar, no que valor tiene."""
    from moodle_sinu.selectores_sinu import (
        IMG_CHECK_DESMARCADO_BLOQUEADO,
        IMG_CHECK_MARCADO_BLOQUEADO,
    )

    assert estado_de_imagen(BASE + IMG_CHECK_MARCADO_BLOQUEADO) is True
    assert estado_de_imagen(BASE + IMG_CHECK_DESMARCADO_BLOQUEADO) is False
