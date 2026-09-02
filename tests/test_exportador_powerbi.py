"""Tests de la etapa 1 que no abren navegador.

Lo que depende de la UI real de Power BI no se puede probar aqui: se verifica
la composicion de selectores, la configuracion y las guardas previas al
arranque de Chromium.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest
from playwright.sync_api import Error as ErrorPlaywright
from playwright.sync_api import TimeoutError as ErrorTiempoPlaywright

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from moodle_sinu import config as config_mod  # noqa: E402
from moodle_sinu import selectores_powerbi as sel  # noqa: E402
from moodle_sinu.config import Config  # noqa: E402
from moodle_sinu.constantes import COLUMNAS_ESPERADAS  # noqa: E402
from moodle_sinu.exportador_powerbi import (  # noqa: E402
    ErrorExportacionPowerBI,
    verificar_estructura_descarga,
    _en_destino,
    _es_aborto_de_navegacion,
    _mismo_origen,
    exportar_reporte,
    ruta_destino_por_defecto,
    verificar_credenciales,
)


class TestSelectores:
    def test_testid_del_menu_se_compone_con_la_etiqueta_traducida(self):
        # Power BI construye el test-id con el texto del item; si cambia el
        # idioma de la cuenta, este selector deja de existir.
        assert sel.TESTID_MENU_EXPORTAR == "pbimenu-item.Exportar datos"

    def test_regex_de_fila_exige_prefijo_y_nombre_del_informe(self):
        rx = sel.rx_fila_informe("ValidacionMoodle")
        assert rx.search("Seleccionar fila Informe ValidacionMoodle")
        assert not rx.search("Seleccionar fila Informe OtroInforme")

    def test_regex_de_fila_escapa_el_nombre(self):
        # Un nombre con puntos no debe convertirse en comodin.
        rx = sel.rx_fila_informe("A.B")
        assert rx.search("Seleccionar fila A.B")
        assert not rx.search("Seleccionar fila AXB")

    @pytest.mark.parametrize(
        "texto",
        ["Datos con diseño actual", "Datos con diseno actual", "Data with current layout"],
    )
    def test_opcion_diseno_actual_tolera_acento_e_ingles(self, texto):
        assert sel.RX_OPCION_DISENO_ACTUAL.search(texto)

    def test_opcion_diseno_actual_no_casa_con_datos_resumidos(self):
        assert not sel.RX_OPCION_DISENO_ACTUAL.search("Datos resumidos")

    @pytest.mark.parametrize("texto", ["Sí", "si", "Yes"])
    def test_boton_si_casa_las_variantes(self, texto):
        assert sel.RX_BOTON_SI.match(texto)

    def test_boton_si_no_casa_frases_que_empiezan_por_si(self):
        # `exact=True` en el selector grabado; la reserva debe ser igual de
        # estricta para no confundirse con "Siguiente".
        assert not sel.RX_BOTON_SI.match("Siguiente")


class TestConfig:
    @pytest.fixture(autouse=True)
    def sin_env(self, monkeypatch, tmp_path):
        """Aisla del config/.env de la maquina.

        `cargar_env` rellena las variables ausentes desde el archivo, asi que
        sin esto un .env real haria fallar las pruebas de valores por defecto.
        """
        monkeypatch.setattr(config_mod, "RUTA_ENV", tmp_path / "no-existe.env")

    def test_visual_y_pagina_son_independientes(self, monkeypatch):
        # Antes el visual heredaba de la pagina; ver TestVisualTabular.
        monkeypatch.setenv("POWERBI_PAGINA", "OTRA-PAGINA")
        monkeypatch.setenv("POWERBI_VISUAL", "OTRA-TABLA")
        cfg = Config.desde_entorno()
        assert (cfg.powerbi_pagina, cfg.powerbi_visual) == ("OTRA-PAGINA", "OTRA-TABLA")

    def test_perfil_vacio_es_none(self, monkeypatch):
        monkeypatch.setenv("POWERBI_PERFIL_NAVEGADOR", "   ")
        assert Config.desde_entorno().powerbi_perfil_navegador is None

    def test_perfil_declarado_se_lee_como_ruta(self, monkeypatch, tmp_path):
        monkeypatch.setenv("POWERBI_PERFIL_NAVEGADOR", str(tmp_path))
        assert Config.desde_entorno().powerbi_perfil_navegador == tmp_path

    def test_headless_por_defecto(self, monkeypatch):
        monkeypatch.delenv("POWERBI_HEADLESS", raising=False)
        assert Config.desde_entorno().powerbi_headless is True

    def test_timeout_de_descarga_supera_el_de_operacion(self):
        # La generacion del .xlsx tarda mucho mas que cualquier clic.
        cfg = Config()
        assert cfg.timeout_descarga_seg > cfg.timeout_render_seg > cfg.timeout_operacion_seg


class TestGuardas:
    def test_faltan_credenciales_nombra_las_variables(self):
        with pytest.raises(ErrorExportacionPowerBI) as exc:
            verificar_credenciales(Config())
        assert "POWERBI_USUARIO" in str(exc.value)
        assert "POWERBI_PASSWORD" in str(exc.value)

    def test_solo_falta_el_password(self):
        cfg = Config(powerbi_usuario="alguien@cun.edu.co")
        with pytest.raises(ErrorExportacionPowerBI, match="POWERBI_PASSWORD"):
            verificar_credenciales(cfg)

    def test_credenciales_completas_no_lanzan(self):
        verificar_credenciales(Config(powerbi_usuario="a@b.co", powerbi_password="x"))

    def test_no_arranca_el_navegador_sin_credenciales(self, tmp_path):
        # Si esta guarda se rompe, el fallo tarda lo que tarde Chromium en
        # abrir en vez de ser inmediato.
        with pytest.raises(ErrorExportacionPowerBI, match="config/.env"):
            exportar_reporte(Config(), destino=tmp_path / "x.xlsx")

    def test_el_password_no_aparece_en_el_mensaje_de_error(self):
        cfg = Config(powerbi_usuario="a@b.co")
        with pytest.raises(ErrorExportacionPowerBI) as exc:
            verificar_credenciales(cfg)
        assert "a@b.co" not in str(exc.value)


class TestNavegacionTolerante:
    """Regresion de la corrida del 21/08/2026 10:54.

    Tras el login, Power BI arranca su propia redireccion y Chromium cancela
    nuestro `goto` con net::ERR_ABORTED. Es un `playwright.Error` generico, no
    un TimeoutError, asi que escapaba del manejo de errores: el proceso moria
    con traceback y el log de la corrida se quedaba sin ninguna linea de error.
    """

    def test_err_aborted_se_reconoce_como_aborto(self):
        exc = ErrorPlaywright(
            "net::ERR_ABORTED at https://app.powerbi.com/home?experience=power-bi"
        )
        assert _es_aborto_de_navegacion(exc)

    @pytest.mark.parametrize(
        "mensaje",
        [
            "net::ERR_NAME_NOT_RESOLVED at https://app.powerbi.com/",
            "net::ERR_CONNECTION_REFUSED",
            "Timeout 30000ms exceeded.",
        ],
    )
    def test_otros_fallos_de_red_no_son_abortos(self, mensaje):
        # Estos si deben abortar la exportacion: no se arreglan reintentando.
        assert not _es_aborto_de_navegacion(ErrorPlaywright(mensaje))

    def test_el_aborto_es_un_error_generico_no_un_timeout(self):
        # La razon de fondo del fallo: capturar solo TimeoutError no bastaba.
        exc = ErrorPlaywright("net::ERR_ABORTED at https://app.powerbi.com/home")
        assert not isinstance(exc, ErrorTiempoPlaywright)
        assert isinstance(exc, ErrorPlaywright)

    def test_timeout_de_playwright_es_subclase_de_error(self):
        # Por eso el `except ErrorTiempoPlaywright` va antes del generico.
        assert issubclass(ErrorTiempoPlaywright, ErrorPlaywright)

    def test_mismo_origen_ignora_la_ruta(self):
        assert _mismo_origen("https://app.powerbi.com/groups/me/list", "https://app.powerbi.com/home")

    def test_distinto_host_no_es_el_mismo_origen(self):
        assert not _mismo_origen("https://login.microsoftonline.com/x", "https://app.powerbi.com/home")

    def test_sin_exigir_ruta_cualquier_pagina_del_shell_vale(self):
        # El shell lleva la barra de busqueda global en todas sus paginas.
        assert _en_destino(
            "https://app.powerbi.com/groups/me/list",
            "https://app.powerbi.com/home?experience=power-bi",
            exigir_ruta=False,
        )

    def test_sin_exigir_ruta_sigue_rechazando_otro_host(self):
        # Quedarse en el SSO no es "haber llegado".
        assert not _en_destino(
            "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
            "https://app.powerbi.com/home?experience=power-bi",
            exigir_ruta=False,
        )

    def test_exigiendo_ruta_no_se_acepta_otro_informe(self):
        # Dar por bueno otro informe llevaria a exportar datos equivocados.
        assert not _en_destino(
            "https://app.powerbi.com/groups/g1/reports/OTRO/pagina",
            "https://app.powerbi.com/groups/g1/reports/BUENO/pagina",
            exigir_ruta=True,
        )

    def test_exigiendo_ruta_se_acepta_otra_seccion_del_mismo_informe(self):
        # Power BI reescribe el ultimo segmento al cargar el informe.
        assert _en_destino(
            "https://app.powerbi.com/groups/g1/reports/r1/ReportSection2",
            "https://app.powerbi.com/groups/g1/reports/r1/ReportSection",
            exigir_ruta=True,
        )

    def test_exigiendo_ruta_se_acepta_el_informe_sin_seccion(self):
        assert _en_destino(
            "https://app.powerbi.com/groups/g1/reports/r1",
            "https://app.powerbi.com/groups/g1/reports/r1/ReportSection",
            exigir_ruta=True,
        )

    def test_exigiendo_ruta_no_se_acepta_otro_informe_del_mismo_area(self):
        # La reescritura de seccion no puede servir de excusa para aceptar
        # un informe distinto: exportariamos datos equivocados.
        assert not _en_destino(
            "https://app.powerbi.com/groups/g1/reports/OTRO/ReportSection",
            "https://app.powerbi.com/groups/g1/reports/r1/ReportSection",
            exigir_ruta=True,
        )

    def test_exigiendo_ruta_la_query_no_cuenta(self):
        assert _en_destino(
            "https://app.powerbi.com/groups/g1/reports/r1/p1?experience=power-bi",
            "https://app.powerbi.com/groups/g1/reports/r1/p1",
            exigir_ruta=True,
        )

    def test_exigiendo_ruta_la_barra_final_no_cuenta(self):
        assert _en_destino(
            "https://app.powerbi.com/groups/g1/reports/r1/",
            "https://app.powerbi.com/groups/g1/reports/r1",
            exigir_ruta=True,
        )


class TestVisualTabular:
    """Regresion de la corrida del 21/08/2026 11:11.

    `POWERBI_VISUAL` heredaba de `POWERBI_PAGINA`, y 'MOODLE-VS-SINU-EST' es el
    aria-label del LIENZO (`<exploration>`), no de un visual. Se exporto un
    grafico en 'Datos resumidos': 7,7 KiB y una sola columna, con codigo 0.
    """

    def test_el_visual_ya_no_hereda_de_la_pagina(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config_mod, "RUTA_ENV", tmp_path / "no-existe.env")
        monkeypatch.setenv("POWERBI_PAGINA", "MOODLE-VS-SINU-EST")
        monkeypatch.delenv("POWERBI_VISUAL", raising=False)
        cfg = Config.desde_entorno()
        assert cfg.powerbi_visual != cfg.powerbi_pagina
        assert cfg.powerbi_visual == "REPORTE"

    def test_el_css_cubre_tabla_y_matriz(self):
        css = sel.css_visual_tabular()
        assert 'aria-roledescription="Tabla"' in css
        assert 'aria-roledescription="Matriz"' in css

    def test_el_css_exige_contenedor_de_visual(self):
        # Sin div.visualContainer se colarian los descendientes de la tabla.
        assert css_partes_todas_con_contenedor(sel.css_visual_tabular())

    def test_el_css_no_casa_el_lienzo(self):
        # El lienzo es <exploration>, no un div.visualContainer con roledesc.
        assert "exploration" not in sel.css_visual_tabular()


def css_partes_todas_con_contenedor(css: str) -> bool:
    return all(parte.strip().startswith("div.visualContainer") for parte in css.split(","))


class TestEstructuraDescarga:
    """El filtro que convierte 'descargo algo' en 'descargo el reporte'."""

    def _escribir(self, ruta: Path, filas: list[tuple]) -> Path:
        from openpyxl import Workbook

        wb = Workbook()
        for fila in filas:
            wb.active.append(fila)
        wb.save(ruta)
        return ruta

    def test_acepta_las_columnas_esperadas(self, tmp_path):
        ruta = self._escribir(tmp_path / "ok.xlsx", [COLUMNAS_ESPERADAS, ("1",) * 15])
        verificar_estructura_descarga(ruta)  # no lanza

    def test_tolera_espacios_en_las_cabeceras(self, tmp_path):
        con_espacios = tuple(f" {c} " for c in COLUMNAS_ESPERADAS)
        ruta = self._escribir(tmp_path / "esp.xlsx", [con_espacios])
        verificar_estructura_descarga(ruta)  # no lanza

    def test_rechaza_el_export_de_datos_resumidos(self, tmp_path):
        # Reproduce el archivo real que se colo: pie arriba y una columna.
        ruta = self._escribir(
            tmp_path / "resumidos.xlsx",
            [("Filtros aplicados: \ncod_periodo no es 26ES1, 26I01",), (None,), ("PERIODO",)],
        )
        with pytest.raises(ErrorExportacionPowerBI) as exc:
            verificar_estructura_descarga(ruta)
        mensaje = str(exc.value)
        assert "Datos" in mensaje and "resumidos" in mensaje
        assert "IDENTIFICACION" in mensaje  # dice que columna falta

    def test_rechaza_columnas_en_otro_orden(self, tmp_path):
        # El orden A..O importa: el parser de la Fase 1 lo da por sentado.
        invertidas = tuple(reversed(COLUMNAS_ESPERADAS))
        ruta = self._escribir(tmp_path / "orden.xlsx", [invertidas])
        with pytest.raises(ErrorExportacionPowerBI):
            verificar_estructura_descarga(ruta)

    def test_rechaza_una_columna_de_menos(self, tmp_path):
        ruta = self._escribir(tmp_path / "falta.xlsx", [COLUMNAS_ESPERADAS[:-1]])
        with pytest.raises(ErrorExportacionPowerBI, match="VALIDACION"):
            verificar_estructura_descarga(ruta)


class TestRutaDestino:
    def test_nombre_lleva_sello_temporal(self):
        ruta = ruta_destino_por_defecto(datetime(2026, 8, 21, 10, 25, 12))
        assert ruta.name == "reporte_moodle_sinu_20260821_102512.xlsx"

    def test_cae_en_data_raw(self):
        assert ruta_destino_por_defecto().parent.name == "raw"


class TestIdioma:
    """Regresion de la corrida del 21/08/2026 11:22.

    La misma configuracion funcionaba con ventana y fallaba en headless:
    Chromium headless pedia la UI en ingles ('More options', 'Slicer') y
    ningun selector en espanol casaba. El idioma se fija en el contexto.
    """

    def test_hay_un_idioma_por_defecto(self):
        assert Config().powerbi_idioma.startswith("es")

    def test_el_idioma_es_configurable(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config_mod, "RUTA_ENV", tmp_path / "no-existe.env")
        monkeypatch.setenv("POWERBI_IDIOMA", "es-ES")
        assert Config.desde_entorno().powerbi_idioma == "es-ES"

    def test_el_css_de_tabla_ignora_mayusculas(self):
        # Power BI ha usado 'Tabla' y 'table' segun version.
        assert '" i]' in sel.css_visual_tabular()

    def test_el_css_cubre_las_variantes_en_ingles(self):
        css = sel.css_visual_tabular()
        assert '"Table"' in css and '"Matrix"' in css
