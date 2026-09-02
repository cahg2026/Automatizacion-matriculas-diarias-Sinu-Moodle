"""Tests del acceso a SINU que no abren navegador.

Los selectores del login SI estan verificados contra el DOM real
(21/08/2026), a diferencia del resto de `selectores_sinu`. Estos tests fijan lo
que se aprendio de esa inspeccion.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from moodle_sinu import selectores_sinu as sel  # noqa: E402
from moodle_sinu import config as config_mod  # noqa: E402
from moodle_sinu.acceso_sinu import UMBRAL_NODOS_VACIA, url_con_barra  # noqa: E402
from moodle_sinu.config import Config  # noqa: E402


class TestBarraFinal:
    """Sin la barra final Tomcat puede responder 404."""

    def test_se_anade_si_falta(self):
        assert url_con_barra("https://sigwt.cun.edu.co/sgacampus") == (
            "https://sigwt.cun.edu.co/sgacampus/"
        )

    def test_no_se_duplica(self):
        assert url_con_barra("https://sigwt.cun.edu.co/sgacampus/") == (
            "https://sigwt.cun.edu.co/sgacampus/"
        )

    def test_ignora_espacios(self):
        assert url_con_barra("  https://x/y  ") == "https://x/y/"

    def test_vacia_cae_en_la_url_base(self):
        assert url_con_barra("") == sel.URL_BASE
        assert sel.URL_BASE.endswith("/")

    def test_la_config_normaliza(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config_mod, "RUTA_ENV", tmp_path / "no-existe.env")
        monkeypatch.setenv("SINU_URL", "https://sigwt.cun.edu.co/sgacampus")
        assert Config.desde_entorno().sinu_url.endswith("/")


class TestSelectoresDelLogin:
    """Verificados contra el DOM real el 21/08/2026."""

    def test_los_campos_se_localizan_por_name_no_por_id(self):
        # SmartClient genera los ids (isc_3T, isc_3W...) en cada carga: usarlos
        # como selector es garantia de fallo intermitente.
        assert 'name="userName"' in sel.CSS_USUARIO
        assert 'name="password"' in sel.CSS_PASSWORD
        for css in (sel.CSS_USUARIO, sel.CSS_PASSWORD):
            assert "isc_" not in css

    def test_ningun_selector_del_modulo_usa_ids_de_smartclient(self):
        sospechosos = [
            (n, v) for n, v in vars(sel).items()
            if isinstance(v, str) and "isc_" in v and not n.startswith("__")
        ]
        assert not sospechosos, sospechosos

    def test_el_boton_entrar_no_es_un_button(self):
        # Es un <td class="button">Entrar</td>: buscar 'button' por rol falla.
        assert sel.CSS_BOTON == "td.button"
        assert sel.TEXTO_BOTON_ENTRAR == "Entrar"

    def test_la_senal_de_sesion_es_el_boton_salir(self):
        assert sel.TEXTO_SALIR == "Salir"
        assert sel.CLASE_DESHABILITADO == "toolbarButtonDisabled"

    def test_las_senales_de_carga_incluyen_el_formulario(self):
        assert sel.CSS_USUARIO in sel.CSS_SENALES_DE_CARGA

    def test_no_se_espera_ningun_iframe(self):
        # SINU renderiza en el documento principal: sus dos iframes son de
        # infraestructura de GWT y existen desde el primer instante, asi que
        # esperarlos no garantiza nada.
        assert not any("iframe" in s.lower() for s in sel.CSS_SENALES_DE_CARGA)
        assert "__gwt_historyFrame" in sel.IDS_IFRAMES_INFRAESTRUCTURA

    def test_los_enlaces_peligrosos_estan_identificados(self):
        # 'Cambiar clave' junto al boton de entrar: pulsarlo por error seria malo.
        assert "Cambiar clave" in sel.TEXTOS_A_EVITAR


class TestUmbralDeVacia:
    def test_es_bajo_para_no_recargar_de_mas(self):
        # Al aparecer el primer selector util hay ~55 etiquetas aunque la
        # interfaz acabe pasando de 500. Un umbral alto recargaba siempre.
        assert UMBRAL_NODOS_VACIA < 55

    def test_pero_detecta_un_documento_vacio(self):
        # Un documento en blanco ronda las 4-10 etiquetas.
        assert UMBRAL_NODOS_VACIA > 10


class TestVentanaYViewport:
    """Regresion de las mediciones del 21/08/2026 en la sesion remota.

    La pantalla real es 1280x720 con escalado al 150% (dpr=1.5). Forzar un
    viewport de 1920x1080 ahi comprime la pagina y la interfaz se ve diminuta.
    Pero en headless no hay gestor de ventanas: --start-maximized maximiza
    contra una pantalla ficticia de 800x600 y deja el viewport en 778x435, que
    rompe el renderizado de los visuales de Power BI.
    """

    def _opciones(self, headless: bool) -> dict:
        """Reproduce la decision de `abrir_contexto` sin abrir navegador."""
        from moodle_sinu.navegador import ARG_MAXIMIZAR, VIEWPORT

        if headless:
            return {"viewport": VIEWPORT}
        return {"no_viewport": True, "arg": ARG_MAXIMIZAR}

    def test_headless_usa_viewport_fijo(self):
        assert self._opciones(headless=True)["viewport"]["width"] == 1920

    def test_con_ventana_no_usa_viewport(self):
        assert self._opciones(headless=False)["no_viewport"] is True

    def test_viewport_y_no_viewport_no_coinciden_nunca(self):
        # Playwright rechaza recibir los dos: no es una preferencia, es un error.
        for headless in (True, False):
            o = self._opciones(headless)
            assert not ("viewport" in o and "no_viewport" in o)

    def test_maximizar_solo_con_ventana(self):
        from moodle_sinu.navegador import ARG_MAXIMIZAR

        assert ARG_MAXIMIZAR not in str(self._opciones(headless=True))
        assert ARG_MAXIMIZAR in str(self._opciones(headless=False))


class TestCanalUnico:
    """El canal debe ser el mismo en automatizacion y grabacion.

    Comprueban un fallo real del 21/08/2026: la automatizacion abria el perfil
    con el Chromium 129 empaquetado y la grabacion con Chrome 150. Chrome
    detecta el 'downgrade', intenta mover el perfil a *.CHROME_DELETE y el
    navegador muere con 'Target page, context or browser has been closed'.
    """

    def test_hay_un_canal_por_defecto(self):
        assert Config().navegador_canal == "chrome"

    def test_es_configurable(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config_mod, "RUTA_ENV", tmp_path / "no-existe.env")
        monkeypatch.setenv("NAVEGADOR_CANAL", "chromium")
        assert Config.desde_entorno().navegador_canal == "chromium"

    def test_el_grabador_usa_el_mismo_por_defecto(self):
        # El default de --canal en grabar.py debe coincidir con el de Config,
        # porque comparten POWERBI_PERFIL_NAVEGADOR.
        fuente = (Path(__file__).resolve().parents[1] / "scripts" / "grabar.py").read_text(
            encoding="utf-8"
        )
        assert '"--canal",\n        default="chrome"' in fuente
        assert Config().navegador_canal == "chrome"
