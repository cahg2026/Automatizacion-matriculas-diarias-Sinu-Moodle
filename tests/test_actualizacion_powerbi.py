"""La fecha de actualizacion del tablero, que es el cerrojo del dia."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from moodle_sinu.actualizacion_powerbi import (  # noqa: E402
    Actualizacion,
    ErrorFechaActualizacion,
    fecha_de_texto,
    formatear,
)

HOY = date(2026, 9, 8)


class TestLecturaDelTexto:
    def test_el_texto_real_del_tablero(self):
        """Tal como se sondeo el 08/09/2026."""
        a = fecha_de_texto("Datos actualizados el 8/9/26", hoy=HOY)
        assert a.fecha == date(2026, 9, 8)
        assert a.texto == "Datos actualizados el 8/9/26"

    def test_dia_y_mes_no_se_confunden(self):
        """8/9 es 8 de septiembre, no 9 de agosto: es-CO pone el dia primero."""
        a = fecha_de_texto("Datos actualizados el 8/9/26", hoy=HOY)
        assert (a.fecha.day, a.fecha.month) == (8, 9)

    def test_admite_dos_cifras_y_cuatro(self):
        assert fecha_de_texto("Datos actualizados el 01/09/2026", hoy=HOY).fecha == date(
            2026, 9, 1
        )
        assert fecha_de_texto("Datos actualizados el 1/9/26", hoy=HOY).fecha == date(
            2026, 9, 1
        )

    def test_no_le_importan_mayusculas_ni_espacios(self):
        a = fecha_de_texto("DATOS   ACTUALIZADOS  EL   8/9/26", hoy=HOY)
        assert a.fecha == date(2026, 9, 8)

    def test_lo_encuentra_dentro_de_mas_texto(self):
        cuerpo = "REPORTE\nMATRICULADO\nDatos actualizados el 8/9/26\nNO MATRICULADO 102"
        assert fecha_de_texto(cuerpo, hoy=HOY).fecha == date(2026, 9, 8)


class TestLoQueDebeFallar:
    def test_sin_el_texto_no_se_inventa_nada(self):
        with pytest.raises(ErrorFechaActualizacion, match="No se encontro"):
            fecha_de_texto("REPORTE\nNO MATRICULADO 102", hoy=HOY)

    def test_la_pantalla_de_carga_no_pasa_por_actualizada(self):
        """El fallo que costo el primer sondeo: leer antes de que cargue.

        La pagina de carga solo tiene el logo de Microsoft. Tiene que fallar,
        no devolver una fecha cualquiera.
        """
        with pytest.raises(ErrorFechaActualizacion):
            fecha_de_texto("Microsoft", hoy=HOY)

    def test_una_fecha_suelta_no_vale(self):
        """Sin la etiqueta no se acepta: es lo que hace seguro el barrido."""
        with pytest.raises(ErrorFechaActualizacion):
            fecha_de_texto("Corte al 8/9/26", hoy=HOY)

    def test_rechaza_el_futuro_por_si_cambio_el_idioma(self):
        """Con el navegador en en-US '9/12/26' seria 9 de diciembre leido al
        reves. Cae en el futuro y se prefiere fallar a dar el dato girado."""
        with pytest.raises(ErrorFechaActualizacion, match="futuro"):
            fecha_de_texto("Datos actualizados el 12/12/26", hoy=HOY)

    def test_rechaza_una_fecha_imposible(self):
        with pytest.raises(ErrorFechaActualizacion, match="no es una fecha valida"):
            fecha_de_texto("Datos actualizados el 31/02/26", hoy=HOY)


class TestDecisionDelDia:
    def test_actualizado_hoy_deja_pasar(self):
        a = fecha_de_texto("Datos actualizados el 8/9/26", hoy=HOY)
        assert a.es_de(HOY)

    def test_el_de_ayer_no_pasa(self):
        a = fecha_de_texto("Datos actualizados el 7/9/26", hoy=HOY)
        assert not a.es_de(HOY)

    def test_cuenta_el_retraso(self):
        a = Actualizacion(fecha=date(2026, 9, 4), texto="x")
        assert formatear(a, hoy=HOY) == (
            "tablero actualizado el 04/09/2026, hace 4 dias"
        )

    def test_texto_para_hoy_y_ayer(self):
        assert "HOY" in formatear(Actualizacion(date(2026, 9, 8), "x"), hoy=HOY)
        assert "AYER" in formatear(Actualizacion(date(2026, 9, 7), "x"), hoy=HOY)

    def test_no_saberlo_se_dice_distinto_de_estar_viejo(self):
        assert "NO SE PUDO LEER" in formatear(None, hoy=HOY)


class TestAnteriorNoEsLoMismoQueDistinto:
    """El criterio de falla es 'anterior a hoy', no 'distinto de hoy'.

    Una fecha posterior no es un tablero viejo: es una lectura girada
    (dia/mes al reves), y esa se rechaza antes, no se anuncia como retraso.
    """

    def test_ayer_es_anterior(self):
        a = fecha_de_texto("Datos actualizados el 7/9/26", hoy=HOY)
        assert a.es_anterior_a(HOY)
        assert not a.es_de(HOY)

    def test_hoy_no_es_anterior(self):
        a = fecha_de_texto("Datos actualizados el 8/9/26", hoy=HOY)
        assert not a.es_anterior_a(HOY)
        assert a.es_de(HOY)

    def test_hace_cuatro_dias_tambien_es_anterior(self):
        a = fecha_de_texto("Datos actualizados el 4/9/26", hoy=HOY)
        assert a.es_anterior_a(HOY)
        assert a.dias_de_retraso >= 0
