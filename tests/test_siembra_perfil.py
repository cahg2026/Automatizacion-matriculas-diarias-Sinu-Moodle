"""Tests de la siembra del perfil de trabajo desde el perfil personal.

Lo que se garantiza aqui es sobre todo que **refrescar la siembra sea seguro**.
La primera version copiaba el arbol entero menos las caches, y eso rompio una
corrida real el 01/09/2026: pisar archivos que llevan estado de sesion deja el
perfil descuadrado. Ahora se copia una lista blanca corta y se conserva lo que
el destino ya tenga.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from moodle_sinu.siembra_perfil import (  # noqa: E402
    ARCHIVO_ESTADO_GLOBAL,
    ARCHIVOS_CIFRADOS_INUTILES,
    ErrorSiembraPerfil,
    sembrar,
)


def perfil_falso(tmp_path: Path, *, directorio: str = "Default") -> Path:
    """Un 'User Data' con lo esencial, una credencial y una cache de relleno."""
    user_data = tmp_path / "User Data"
    perfil = user_data / directorio
    (perfil / "Network").mkdir(parents=True)
    (user_data / ARCHIVO_ESTADO_GLOBAL).write_text('{"os_crypt": {}}', encoding="utf-8")
    (perfil / "Bookmarks").write_text('{"roots": {"bar": {}}}', encoding="utf-8")
    (perfil / "Favicons").write_bytes(b"sqlite-falso")
    (perfil / "Preferences").write_text(
        json.dumps({"protection": {"macs": {"bookmarks": "abc"}}, "idioma": "es"}),
        encoding="utf-8",
    )
    (perfil / "Secure Preferences").write_text(
        json.dumps({"protection": {"macs": {}}, "super_mac": "xyz"}), encoding="utf-8"
    )
    (perfil / "Login Data").write_bytes(b"credenciales")
    (perfil / "Network" / "Cookies").write_bytes(b"cookies-del-personal")

    cache = perfil / "Cache"
    cache.mkdir()
    (cache / "data_0").write_bytes(b"x" * 4096)
    return user_data


# --------------------------------------------------------------------------
# Estructura y contenido
# --------------------------------------------------------------------------


def test_la_copia_imita_la_estructura_de_user_data(tmp_path):
    """Chrome recibe la carpeta como --user-data-dir: el perfil va dentro."""
    origen = perfil_falso(tmp_path)
    destino = tmp_path / "trabajo"
    sembrar(origen, destino)

    assert (destino / ARCHIVO_ESTADO_GLOBAL).is_file()
    assert (destino / "Default" / "Bookmarks").is_file()


def test_viajan_los_favoritos_y_sus_iconos(tmp_path):
    """Es lo unico que se busca del perfil personal."""
    origen = perfil_falso(tmp_path)
    destino = tmp_path / "trabajo"
    resultado = sembrar(origen, destino)

    assert resultado.claves_ausentes == []
    assert (destino / "Default" / "Bookmarks").is_file()
    assert (destino / "Default" / "Favicons").is_file()


def test_no_se_copia_nada_fuera_de_la_lista_blanca(tmp_path):
    """Ni caches, ni credenciales, ni cookies, ni historial."""
    origen = perfil_falso(tmp_path)
    destino = tmp_path / "trabajo"
    sembrar(origen, destino)

    assert not (destino / "Default" / "Cache").exists()
    assert not (destino / "Default" / "Login Data").exists()
    assert not (destino / "Default" / "Network" / "Cookies").exists()


def test_las_cookies_estan_en_la_lista_de_lo_que_nunca_se_copia():
    """Van cifradas contra la instalacion de Chrome (App-Bound Encryption):
    llegarian ilegibles, y pisarian la sesion viva del perfil de trabajo."""
    assert "Cookies" in ARCHIVOS_CIFRADOS_INUTILES
    assert "Login Data" in ARCHIVOS_CIFRADOS_INUTILES


# --------------------------------------------------------------------------
# Refrescar tiene que ser seguro: es el fallo del 01/09/2026
# --------------------------------------------------------------------------


def test_un_refresco_no_pisa_la_sesion_ni_las_preferencias(tmp_path):
    """El caso real: se sembro, se inicio sesion a mano, y se vuelve a sembrar
    para refrescar favoritos. Nada del estado de sesion puede moverse."""
    origen = perfil_falso(tmp_path)
    destino = tmp_path / "trabajo"
    sembrar(origen, destino)

    # El perfil gana su propio estado al entrar una vez a mano.
    cookies = destino / "Default" / "Network" / "Cookies"
    cookies.parent.mkdir(parents=True, exist_ok=True)
    cookies.write_bytes(b"sesion-de-verdad")
    (destino / "Default" / "Preferences").write_text(
        json.dumps({"cuenta": "la del trabajo"}), encoding="utf-8"
    )
    (destino / ARCHIVO_ESTADO_GLOBAL).write_text(
        json.dumps({"clave": "del trabajo"}), encoding="utf-8"
    )

    resultado = sembrar(origen, destino)

    assert cookies.read_bytes() == b"sesion-de-verdad"
    prefs = json.loads((destino / "Default" / "Preferences").read_text(encoding="utf-8"))
    assert prefs.get("cuenta") == "la del trabajo", "Preferences lleva la cuenta activa"
    assert "del trabajo" in (destino / ARCHIVO_ESTADO_GLOBAL).read_text(encoding="utf-8")
    assert "Preferences" in resultado.conservados


def test_un_refresco_si_actualiza_los_favoritos(tmp_path):
    """Conservar el estado de sesion no puede impedir el objetivo de refrescar."""
    origen = perfil_falso(tmp_path)
    destino = tmp_path / "trabajo"
    sembrar(origen, destino)

    (origen / "Default" / "Bookmarks").write_text(
        '{"roots": {"bar": {"nuevo": 1}}}', encoding="utf-8"
    )
    sembrar(origen, destino)

    guardado = (destino / "Default" / "Bookmarks").read_text(encoding="utf-8")
    assert "nuevo" in guardado


def test_el_local_state_viaja_solo_la_primera_vez(tmp_path):
    """Sobrescribirlo rotaria la clave y dejaria ilegibles las cookies vivas."""
    origen = perfil_falso(tmp_path)
    destino = tmp_path / "trabajo"
    sembrar(origen, destino)
    assert (destino / ARCHIVO_ESTADO_GLOBAL).read_text(encoding="utf-8") == '{"os_crypt": {}}'


# --------------------------------------------------------------------------
# Las firmas de Chrome
# --------------------------------------------------------------------------


def test_se_retiran_las_firmas_o_chrome_borraria_los_favoritos(tmp_path):
    """Comprobado el 31/08/2026 con Chrome 151: sin esto, al abrir el perfil
    movido Chrome toma los favoritos por manipulados, escribe un 'Bookmarks'
    vacio y deja el bueno en 'Bookmarks.bak' (46 favoritos -> 0)."""
    origen = perfil_falso(tmp_path)
    destino = tmp_path / "trabajo"
    resultado = sembrar(origen, destino)

    guardado = json.loads(
        (destino / "Default" / "Secure Preferences").read_text(encoding="utf-8")
    )
    assert "protection" not in guardado
    assert "super_mac" not in guardado
    assert "Secure Preferences:protection" in resultado.protecciones_retiradas


def test_retirar_las_firmas_no_toca_el_resto_de_preferencias(tmp_path):
    origen = perfil_falso(tmp_path)
    destino = tmp_path / "trabajo"
    sembrar(origen, destino)

    prefs = json.loads((destino / "Default" / "Preferences").read_text(encoding="utf-8"))
    assert "protection" not in prefs
    assert prefs["idioma"] == "es"


def test_las_firmas_se_retiran_tambien_en_un_refresco(tmp_path):
    """En un refresco no se copia Preferences, pero SI se le retiran las firmas:
    Chrome habia re-firmado los favoritos viejos, y los nuevos no casarian."""
    origen = perfil_falso(tmp_path)
    destino = tmp_path / "trabajo"
    sembrar(origen, destino)

    # Chrome vuelve a firmar por su cuenta al abrir el perfil.
    (destino / "Default" / "Preferences").write_text(
        json.dumps({"protection": {"macs": {"bookmarks": "re-firmado"}}, "cuenta": "x"}),
        encoding="utf-8",
    )
    resultado = sembrar(origen, destino)

    prefs = json.loads((destino / "Default" / "Preferences").read_text(encoding="utf-8"))
    assert "protection" not in prefs
    assert prefs["cuenta"] == "x", "se retira la firma, no el estado de sesion"
    assert "Preferences:protection" in resultado.protecciones_retiradas


# --------------------------------------------------------------------------
# Guardas
# --------------------------------------------------------------------------


def test_con_rehacer_se_borra_la_copia_anterior(tmp_path):
    origen = perfil_falso(tmp_path)
    destino = tmp_path / "trabajo"
    sembrar(origen, destino)
    (destino / "Default" / "viejo.txt").write_text("fuera", encoding="utf-8")

    sembrar(origen, destino, rehacer=True)
    assert not (destino / "Default" / "viejo.txt").exists()
    assert (destino / "Default" / "Bookmarks").is_file()


def test_un_perfil_inexistente_falla_con_instrucciones(tmp_path):
    origen = perfil_falso(tmp_path)
    with pytest.raises(ErrorSiembraPerfil, match="NAVEGADOR_PERFIL_DIRECTORIO"):
        sembrar(origen, tmp_path / "trabajo", directorio="Profile 9")


def test_no_se_puede_sembrar_sobre_el_propio_user_data(tmp_path):
    """Seria justo lo contrario de para lo que existe la copia."""
    origen = perfil_falso(tmp_path)
    with pytest.raises(ErrorSiembraPerfil, match="no puede ser el propio"):
        sembrar(origen, origen)


def test_un_archivo_bloqueado_se_anota_y_no_tumba_la_siembra(tmp_path, monkeypatch):
    """Chrome deja candados sueltos; morir por uno seria peor que seguir."""
    import shutil as _shutil

    from moodle_sinu import siembra_perfil

    origen = perfil_falso(tmp_path)
    real = _shutil.copy2

    def copia_falsa(src, dst, *a, **k):
        if Path(src).name == "Bookmarks":
            raise OSError("bloqueado por Chrome")
        return real(src, dst, *a, **k)

    monkeypatch.setattr(siembra_perfil.shutil, "copy2", copia_falsa)
    resultado = sembrar(origen, tmp_path / "trabajo")

    assert "Bookmarks" in resultado.omitidos_por_bloqueo
    assert "Bookmarks" in resultado.claves_ausentes
    # El resto si llego.
    assert (tmp_path / "trabajo" / "Default" / "Favicons").is_file()
