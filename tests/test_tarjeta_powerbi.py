"""Tests de la tarjeta 'NO MATRICULADO' de Power BI.

El numero que va tras '#' en el nombre del reporte es el valor de esa tarjeta,
NO un consecutivo (decision del dueno del proceso, 24/08/2026). El parseo es
una funcion pura porque un error aqui produce un nombre de archivo incorrecto
que nadie revisa.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from moodle_sinu import selectores_powerbi as sel  # noqa: E402
from moodle_sinu.exportador_powerbi import leer_valor_de_tarjeta  # noqa: E402


class TestParseoDeLaEtiqueta:
    def test_el_formato_real_observado(self):
        # Etiqueta exacta capturada en la traza del 21/08/2026.
        assert leer_valor_de_tarjeta("NO MATRICULADO 1323.") == 1323

    def test_el_valor_confirmado_de_hoy(self):
        assert leer_valor_de_tarjeta("NO MATRICULADO 131.") == 131

    def test_tolera_separador_de_miles(self):
        # En es-CO el separador es el punto; el punto final es puntuacion.
        assert leer_valor_de_tarjeta("NO MATRICULADO 1.323.") == 1323

    def test_tarjeta_en_blanco_es_none(self):
        # 'MATRICULADO (En blanco).' no es un cero: es ausencia de dato.
        assert leer_valor_de_tarjeta("MATRICULADO (En blanco).") is None

    def test_etiqueta_sin_numero_es_none(self):
        assert leer_valor_de_tarjeta("NO MATRICULADO") is None

    def test_vacio_es_none(self):
        assert leer_valor_de_tarjeta("") is None
        assert leer_valor_de_tarjeta(None) is None

    def test_el_orden_invertido_del_innerText(self):
        # El contenedor no lleva aria-label; su innerText pone el valor primero
        # y el nombre despues. El parseo no debe depender del orden.
        assert leer_valor_de_tarjeta("131 NO MATRICULADO") == 131

    def test_cero_se_lee_como_cero_no_como_none(self):
        # Un dia sin no-matriculados es un dato valido, distinto de "no se leyo".
        assert leer_valor_de_tarjeta("NO MATRICULADO 0.") == 0


class TestSelectoresDeTarjeta:
    def test_la_tarjeta_se_localiza_por_descripcion_de_rol(self):
        # Igual que el visual de tabla: es lo estable, no la posicion.
        css = sel.css_tarjetas()
        assert 'aria-roledescription="Tarjeta"' in css
        assert "div.visualContainer" in css

    def test_cubre_la_variante_en_ingles(self):
        assert '"Card"' in sel.css_tarjetas()

    def test_no_se_confunde_con_el_visual_de_tabla(self):
        assert "Tarjeta" not in sel.css_visual_tabular()
        assert "Tabla" not in sel.css_tarjetas()

    @pytest.mark.parametrize(
        "etiqueta", ["NO MATRICULADO 131.", "NO_MATRICULADO", "no matriculado 5."]
    )
    def test_reconoce_el_nombre_con_espacio_o_guion_bajo(self, etiqueta):
        # El reporte usa NO_MATRICULADO; la tarjeta, NO MATRICULADO.
        assert sel.RX_TARJETA_NO_MATRICULADO.search(etiqueta)

    def test_no_casa_con_la_tarjeta_de_matriculado(self):
        assert not sel.RX_TARJETA_NO_MATRICULADO.search("MATRICULADO (En blanco).")
