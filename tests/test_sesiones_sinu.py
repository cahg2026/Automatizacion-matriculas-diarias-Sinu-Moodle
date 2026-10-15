"""Tres navegadores, cada uno con su sesion de SINU: la 07, la 05 y la 50."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from moodle_sinu import sesiones_sinu  # noqa: E402
from moodle_sinu.acceso_sinu import ErrorAccesoSinu  # noqa: E402
from moodle_sinu.sesiones_sinu import SesionesSinu  # noqa: E402


class _Pagina:
    def __init__(self, nombre):
        self.nombre = nombre
        self.al_frente = 0

    def bring_to_front(self):
        self.al_frente += 1


class _Navegadores:
    """Fabrica de navegadores falsos: cuenta cuantos se abren y se cierran."""

    def __init__(self):
        self.abiertos = []
        self.cerrados = []

    def __call__(self):
        n = len(self.abiertos) + 1
        nombre = f"nav{n}"
        self.abiertos.append(nombre)

        class _Contexto:
            def new_page(_self):
                return _Pagina(nombre)

        return _Contexto(), lambda: self.cerrados.append(nombre)


def _sesiones(acceder=None):
    navegadores = _Navegadores()
    logins = []

    def por_defecto(page, cfg):
        logins.append(page.nombre)
        return True

    s = SesionesSinu(
        object(), object(), _Pagina("07"),
        abrir_navegador=navegadores, acceder=acceder or por_defecto,
    )
    return s, navegadores, logins


class TestUnNavegadorPorModulo:
    def test_al_empezar_solo_existe_el_de_la_07(self):
        s, navegadores, logins = _sesiones()
        assert s.abiertas == ()
        assert navegadores.abiertos == [] and logins == []

    def test_la_05_y_la_50_tienen_cada_una_su_navegador_y_su_login(self):
        """Navegadores y no pestanas: dos pestanas comparten cookies, y un login
        en una podria pisar la sesion de la otra."""
        s, navegadores, logins = _sesiones()
        p05, p50 = s.isef05(), s.pacf50()
        assert (p05.nombre, p50.nombre) == ("nav1", "nav2")
        assert p05 is not s.isef07 and p50 is not s.isef07
        assert logins == ["nav1", "nav2"]

    def test_se_reutiliza_para_todo_el_lote(self):
        s, navegadores, logins = _sesiones()
        for _ in range(5):
            s.isef05()
        assert navegadores.abiertos == ["nav1"] and logins == ["nav1"]


class TestFallos:
    def test_un_login_fallido_se_vuelve_a_intentar_la_siguiente_vez(self):
        """No se da por perdido a la primera: puede ser del momento."""
        intentos = []

        def falla_la_primera(page, cfg):
            intentos.append(page.nombre)
            if len(intentos) == 1:
                raise ErrorAccesoSinu("no cargo")

        s, navegadores, _ = _sesiones(falla_la_primera)
        with pytest.raises(ErrorAccesoSinu):
            s.isef05()
        assert s.isef05().nombre == "nav2"
        assert navegadores.cerrados == ["nav1"]  # el fallido no queda abierto

    def test_con_tope_por_lote(self):
        intentos = []

        def falla(page, cfg):
            intentos.append(page.nombre)
            raise ErrorAccesoSinu("no cargo")

        s, _, _ = _sesiones(falla)
        for _ in range(5):
            with pytest.raises(ErrorAccesoSinu):
                s.isef05()
        assert len(intentos) == sesiones_sinu.MAX_APERTURAS

    def test_el_fallo_de_la_05_no_se_da_por_hecho_en_la_50(self):
        def solo_falla_la_05(page, cfg):
            if page.nombre == "nav1":
                raise ErrorAccesoSinu("no cargo")

        s, _, _ = _sesiones(solo_falla_la_05)
        with pytest.raises(ErrorAccesoSinu):
            s.isef05()
        assert s.pacf50().nombre == "nav2"


class TestFrenteYCierre:
    def test_el_que_se_usa_va_al_frente(self):
        s, _, _ = _sesiones()
        p05 = s.isef05()
        s.isef05()
        s.volver_a_isef07()
        assert p05.al_frente == 2
        assert s.isef07.al_frente == 1

    def test_cerrar_cierra_la_05_y_la_50_y_no_la_07(self):
        s, navegadores, _ = _sesiones()
        s.isef05(), s.pacf50()
        s.cerrar()
        assert navegadores.cerrados == ["nav1", "nav2"]
        assert s.abiertas == ()
