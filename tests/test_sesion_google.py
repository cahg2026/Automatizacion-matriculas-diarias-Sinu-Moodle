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
    pide_iniciar_sesion,
)


class TestSesionViva:
    def test_drive_cargado_no_pide_nada(self):
        assert pide_iniciar_sesion("https://drive.google.com/drive/my-drive") is None

    def test_una_carpeta_de_drive_tampoco(self):
        assert (
            pide_iniciar_sesion(
                "https://drive.google.com/drive/folders/1P4tdPPMCtdZofHtGysBOiUz"
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
