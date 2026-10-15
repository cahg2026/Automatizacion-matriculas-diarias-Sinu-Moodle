"""Grupos declarados a mano como inexistentes en SINU (config/grupos_no_existen.txt)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from moodle_sinu import grupos_declarados as gd  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]


def _archivo(tmp_path, texto):
    ruta = tmp_path / "grupos_no_existen.txt"
    ruta.write_text(texto, encoding="utf-8")
    return ruta


def test_el_formato_del_dueno_del_proceso(tmp_path):
    ruta = _archivo(tmp_path, "POS01/55ES1/26ES5/B1/EMPVI/EMVIR\n")
    assert gd.leer(ruta) == {("26ES5", "POS01/55ES1"): "POS01/55ES1/26ES5/B1/EMPVI/EMVIR"}


def test_comentarios_y_vacias_se_ignoran(tmp_path):
    ruta = _archivo(tmp_path, "# nota\n\n   \nPOS01/55ES2/26ES5\n")
    assert list(gd.leer(ruta)) == [("26ES5", "POS01/55ES2")]


def test_una_linea_incompleta_no_cuenta(tmp_path):
    ruta = _archivo(tmp_path, "POS01/55ES2\nPOS01//26ES5\n")
    assert gd.leer(ruta) == {}


def test_se_filtra_por_periodo(tmp_path):
    ruta = _archivo(tmp_path, "POS01/55ES1/26ES5\nTI001/55577/26V05\n")
    assert list(gd.del_periodo("26es5", ruta)) == ["POS01/55ES1"]
    assert gd.del_periodo("2026D", ruta) == {}


def test_sin_archivo_no_hay_nada(tmp_path):
    assert gd.leer(tmp_path / "no-existe.txt") == {}


def test_el_archivo_del_proyecto_trae_los_cuatro_grupos_de_26ES5():
    """La declaracion del 28/09/2026, tal cual se paso."""
    declarados = gd.del_periodo("26ES5", RAIZ / "config" / "grupos_no_existen.txt")
    assert sorted(declarados) == [
        "POS01/55ES1", "POS01/55ES2", "POS01/55ES5", "POS01/55ES6",
    ]
