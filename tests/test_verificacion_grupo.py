"""Verificar un grupo solo con la 50 (PACF50).

Regla del dueno del proceso (06/10/2026):

    Si una materia no tiene check en MOODLE en la 50, no va a existir en la 05.
    La 05 no nos impacta ni para bien ni para mal: se retira.
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from moodle_sinu.verificacion_grupo import Fuente, verificar  # noqa: E402


class _Consulta:
    """Una consulta simulada que cuenta sus llamadas."""

    def __init__(self, respuesta):
        self.respuesta = respuesta
        self.llamadas = 0

    def __call__(self):
        self.llamadas += 1
        return self.respuesta


def test_la_05_ya_no_existe_como_fuente():
    assert {f.value for f in Fuente} == {"pacf50", "ninguna"}


def test_se_pregunta_una_sola_vez():
    c50 = _Consulta((True, "moodle=si"))
    verificar("A/1", c50)
    assert c50.llamadas == 1


class TestQueSeDescartaYQueNo:
    def test_la_50_dice_que_SI(self):
        v = verificar("POS01/55ES2", _Consulta((True, "moodle=si", True)))
        assert v.tiene_curso is True
        assert v.descartar_grupo is False
        assert v.fuente is Fuente.PACF50
        assert v.consultadas == (Fuente.PACF50,)

    def test_la_50_dice_que_NO(self):
        v = verificar("DTA32/55598", _Consulta((False, "moodle=NO")))
        assert v.tiene_curso is False
        assert v.descartar_grupo is True
        assert v.fuente is Fuente.PACF50

    def test_si_la_50_no_contesta_NO_se_descarta(self):
        """No saber NO es no tener. El 25/09/2026 se cerraron 68 filas de dos
        grupos SANOS como 'validar a mano'; una se reparo con un solo vincular
        en 44,8 s."""
        v = verificar("POS01/57ES6", _Consulta((None, "no cargo")))
        assert v.tiene_curso is None
        assert v.descartar_grupo is False
        assert v.fuente is Fuente.NINGUNA


class TestGrupoQueNoExiste:
    """POS01/55ES1, 55ES2, 55ES5 y 55ES6 en 26ES5: en la 50, buscando por
    numero de grupo, no existen (28/09/2026)."""

    def test_se_descarta(self):
        v = verificar("POS01/55ES1", _Consulta((None, "no existe", False)))
        assert v.grupo_inexistente
        assert v.descartar_grupo
        assert v.fuente is Fuente.PACF50

    def test_el_resumen_lo_dice(self):
        v = verificar("POS01/55ES1", _Consulta((None, "no existe", False)))
        assert "NO EXISTE" in v.resumen()

    def test_que_la_50_no_conteste_NO_es_que_no_exista(self):
        """Solo un False explicito de la 50 descarta."""
        v = verificar("POS01/55ES1", _Consulta((None, "no cargo", None)))
        assert not v.grupo_inexistente
        assert not v.descartar_grupo


def test_el_resumen_dice_quien_lo_dijo():
    v = verificar("POS01/55ES2", _Consulta((False, "moodle=NO")))
    assert "pacf50" in v.resumen()
    assert "isef05" not in v.resumen()
    assert "PACF50" in v.detalle
