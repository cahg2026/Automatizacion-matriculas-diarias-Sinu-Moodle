"""Si la sesion de Google sirve, medido navegando y no contando cookies.

El 08/09/2026 esta distincion costo una corrida: el perfil tenia 88 cookies y
"todas las de sesion de Google presentes" mientras Google habia invalidado la
sesion del lado del servidor. El paso 0 dio el visto bueno, se exporto Power BI
y el fallo salio en el paso 3, ya con el cerrojo de escritura abierto.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from moodle_sinu.perfil_navegador import (  # noqa: E402
    SesionGoogle,
    comprobar_sesion_google,
    pide_iniciar_sesion,
)


class TestSesionViva:
    def test_drive_cargado_no_pide_nada(self):
        assert pide_iniciar_sesion("https://drive.google.com/drive/my-drive") is None

    def test_una_carpeta_de_drive_tampoco(self):
        assert (
            pide_iniciar_sesion(
                "https://drive.google.com/drive/folders/1CarpetaDeEjemplo0000000"
            )
            is None
        )

    def test_calendar_cargado_tampoco(self):
        assert pide_iniciar_sesion("https://calendar.google.com/calendar/u/0/r") is None

    def test_ni_una_url_vacia(self):
        assert pide_iniciar_sesion("") is None
        assert pide_iniciar_sesion(None) is None


class TestSesionCaida:
    def test_reverificacion_de_identidad(self):
        """El caso real del 08/09/2026, que tumbo la corrida en el paso 3."""
        motivo = pide_iniciar_sesion(
            "https://accounts.google.com/v3/signin/confirmidentifier?authuser=0"
            "&continue=https://calendar.google.com/calendar/render"
        )
        assert motivo is not None
        assert "REVERIFICAR" in motivo

    def test_selector_de_cuenta(self):
        """Distinto de "no hay sesion": la sesion existe, hay varias cuentas."""
        motivo = pide_iniciar_sesion(
            "https://accounts.google.com/v3/signin/accountchooser?..."
        )
        assert motivo is not None
        assert "ELEGIR CUENTA" in motivo

    def test_sin_sesion(self):
        motivo = pide_iniciar_sesion(
            "https://accounts.google.com/ServiceLogin?service=wise"
        )
        assert motivo is not None
        assert "INICIAR SESION" in motivo

    def test_los_tres_motivos_son_distintos(self):
        """Cada uno se arregla de otra forma; confundirlos manda a depurar
        donde no esta el problema."""
        motivos = {
            pide_iniciar_sesion("https://accounts.google.com/v3/signin/confirmidentifier"),
            pide_iniciar_sesion("https://accounts.google.com/v3/signin/accountchooser"),
            pide_iniciar_sesion("https://accounts.google.com/ServiceLogin"),
        }
        assert len(motivos) == 3

    def test_cualquier_pantalla_de_accounts_cuenta(self):
        """Aunque no se reconozca el subtipo, estar en accounts.google.com ya
        significa que no se pudo entrar."""
        motivo = pide_iniciar_sesion("https://accounts.google.com/algo/nuevo/2027")
        assert motivo is not None
        assert "accounts.google.com" in motivo


class TestElDatoQueSeDevuelve:
    def test_viva_se_lee_claro(self):
        assert "VIVA" in str(SesionGoogle(viva=True))

    def test_caida_lleva_el_motivo(self):
        s = SesionGoogle(viva=False, detalle="Google pide REVERIFICAR")
        assert "CAIDA" in str(s) and "REVERIFICAR" in str(s)

    def test_no_poder_comprobarlo_no_es_estar_caida(self):
        """Se marca como no viva para no dejar pasar el flujo, pero el detalle
        dice que es otra cosa: no saberlo no es lo mismo que saber que fallo."""
        s = SesionGoogle(viva=False, detalle="no se pudo comprobar (timeout)")
        assert not s.viva
        assert "no se pudo comprobar" in s.detalle


class _Pagina:
    def __init__(self, contexto):
        self.contexto = contexto
        self.url = "about:blank"

    def goto(self, destino, **_):
        respuesta = self.contexto.respuestas.pop(0)
        if isinstance(respuesta, Exception):
            raise respuesta
        self.url = respuesta

    def wait_for_timeout(self, _ms):
        pass

    def close(self):
        pass


class _Contexto:
    def __init__(self, *respuestas):
        self.respuestas = list(respuestas)
        self.paginas_abiertas = 0

    def new_page(self):
        self.paginas_abiertas += 1
        return _Pagina(self)


class TestGraciaAntesDeAbortar:
    """El 16/10/2026 un solo timeout de Drive a las 9:00 tumbo el dia con la
    sesion sana. No contestar se reintenta; pedir login no."""

    def test_un_timeout_y_luego_responde_es_viva(self):
        ctx = _Contexto(TimeoutError("Timeout 30000ms"), "https://drive.google.com/drive/my-drive")
        ses = comprobar_sesion_google(ctx, object(), gracia_seg=60, pausa_seg=0)
        assert ses.viva
        assert ctx.paginas_abiertas == 2

    def test_pedir_login_no_se_reintenta(self):
        ctx = _Contexto("https://accounts.google.com/ServiceLogin", "https://drive.google.com/drive/my-drive")
        ses = comprobar_sesion_google(ctx, object(), gracia_seg=60, pausa_seg=0)
        assert not ses.viva
        assert "INICIAR SESION" in ses.detalle
        assert ctx.paginas_abiertas == 1

    def test_si_nunca_contesta_se_rinde_al_agotar_la_gracia(self):
        ctx = _Contexto(*[TimeoutError("Timeout")] * 3)
        ses = comprobar_sesion_google(ctx, object(), gracia_seg=0, pausa_seg=0)
        assert not ses.viva
        assert "no se pudo comprobar" in ses.detalle
        assert ctx.paginas_abiertas == 1
