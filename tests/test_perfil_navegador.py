"""Tests de la eleccion del perfil de Chrome.

Lo que se fija aqui es sobre todo el cerrojo: con Chrome abierto, la
automatizacion tiene que negarse con instrucciones en vez de dejar que el
driver muera con un error opaco -- o, peor, dejar el perfil del usuario
inconsistente.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from moodle_sinu import perfil_navegador  # noqa: E402
from moodle_sinu.config import Config  # noqa: E402
from moodle_sinu.perfil_navegador import (  # noqa: E402
    ErrorPerfilNavegador,
    PerfilResuelto,
    exigir_disponible,
    resolver,
)


def _cfg(**cambios) -> Config:
    base = {"navegador_perfil": "chrome", "navegador_perfil_directorio": "Default"}
    base.update(cambios)
    return Config(**base)


def _perfil_chrome_falso(tmp_path: Path, *, directorio: str = "Default") -> Path:
    """Crea una carpeta 'User Data' con la pinta de un perfil real."""
    user_data = tmp_path / "User Data"
    (user_data / directorio).mkdir(parents=True)
    (user_data / directorio / "Preferences").write_text("{}", encoding="utf-8")
    return user_data


# --------------------------------------------------------------------------
# Resolucion
# --------------------------------------------------------------------------


def test_por_defecto_se_usa_el_perfil_de_trabajo():
    """No es preferencia: Chrome 136+ veta automatizar su directorio por
    defecto ('DevTools remote debugging requires a non-default data
    directory'), asi que 'chrome' no puede ser el valor por defecto aunque sea
    lo que se pidio. Se usa una copia sembrada desde el, que si funciona."""
    assert Config().navegador_perfil == "proyecto"


def test_el_modo_chrome_sigue_disponible():
    """Se conserva para versiones de Chrome que si lo admitan."""
    perfil = resolver(_cfg())
    assert perfil.es_chrome_real
    assert perfil.ruta.name == "User Data"


def test_el_modo_proyecto_usa_el_perfil_dedicado(tmp_path):
    perfil = resolver(_cfg(navegador_perfil="proyecto", powerbi_perfil_navegador=tmp_path))
    assert not perfil.es_chrome_real
    assert perfil.ruta == tmp_path


def test_el_modo_proyecto_sin_ruta_falla():
    with pytest.raises(ErrorPerfilNavegador, match="POWERBI_PERFIL_NAVEGADOR"):
        resolver(_cfg(navegador_perfil="proyecto", powerbi_perfil_navegador=None))


def test_una_ruta_explicita_se_toma_como_perfil_dedicado(tmp_path):
    perfil = resolver(_cfg(navegador_perfil=str(tmp_path)))
    assert perfil.ruta == tmp_path
    assert not perfil.es_chrome_real


def test_el_modo_no_distingue_mayusculas():
    assert resolver(_cfg(navegador_perfil="CHROME")).es_chrome_real


# --------------------------------------------------------------------------
# Argumentos de Chrome
# --------------------------------------------------------------------------


def test_el_perfil_personal_pasa_profile_directory():
    """La carpeta que recibe Playwright es 'User Data', que los contiene todos."""
    perfil = resolver(_cfg(navegador_perfil_directorio="Profile 1"))
    assert perfil.argumentos == ("--profile-directory=Profile 1",)


def test_el_perfil_dedicado_no_pasa_profile_directory(tmp_path):
    perfil = resolver(_cfg(navegador_perfil=str(tmp_path)))
    assert perfil.argumentos == ()


# --------------------------------------------------------------------------
# El cerrojo
# --------------------------------------------------------------------------


def test_con_chrome_abierto_el_perfil_personal_se_rechaza(tmp_path, monkeypatch):
    """Chrome bloquea la carpeta de su perfil mientras corre."""
    monkeypatch.setattr(perfil_navegador, "chrome_esta_corriendo", lambda: True)
    perfil = PerfilResuelto(
        ruta=_perfil_chrome_falso(tmp_path), es_chrome_real=True, directorio="Default"
    )
    with pytest.raises(ErrorPerfilNavegador) as exc:
        exigir_disponible(perfil)
    # El mensaje tiene que decir que hacer, no solo que fallo.
    assert "Cerrar Chrome" in str(exc.value)
    assert "NAVEGADOR_PERFIL=proyecto" in str(exc.value)


def test_con_chrome_cerrado_el_perfil_personal_pasa(tmp_path, monkeypatch):
    monkeypatch.setattr(perfil_navegador, "chrome_esta_corriendo", lambda: False)
    perfil = PerfilResuelto(
        ruta=_perfil_chrome_falso(tmp_path), es_chrome_real=True, directorio="Default"
    )
    exigir_disponible(perfil)  # no levanta


def test_un_perfil_personal_inexistente_se_rechaza(tmp_path, monkeypatch):
    monkeypatch.setattr(perfil_navegador, "chrome_esta_corriendo", lambda: False)
    perfil = PerfilResuelto(
        ruta=tmp_path / "no-existe", es_chrome_real=True, directorio="Default"
    )
    with pytest.raises(ErrorPerfilNavegador, match="No existe el perfil"):
        exigir_disponible(perfil)


def test_un_subdirectorio_inexistente_lista_los_disponibles(tmp_path, monkeypatch):
    monkeypatch.setattr(perfil_navegador, "chrome_esta_corriendo", lambda: False)
    user_data = _perfil_chrome_falso(tmp_path, directorio="Profile 3")
    perfil = PerfilResuelto(ruta=user_data, es_chrome_real=True, directorio="Default")
    with pytest.raises(ErrorPerfilNavegador) as exc:
        exigir_disponible(perfil)
    assert "Profile 3" in str(exc.value)


def test_el_perfil_dedicado_se_crea_y_no_exige_chrome_cerrado(tmp_path, monkeypatch):
    """Es la salida cuando no se puede cerrar Chrome."""
    monkeypatch.setattr(perfil_navegador, "chrome_esta_corriendo", lambda: True)
    destino = tmp_path / "perfil-nuevo"
    exigir_disponible(PerfilResuelto(ruta=destino, es_chrome_real=False))
    assert destino.is_dir()
