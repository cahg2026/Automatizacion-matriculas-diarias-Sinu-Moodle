"""El primer disparo de la tarea diaria.

El 09/09/2026 la tarea se registro a las 08:12 con la hora en 09:00 y quedo
para el DIA SIGUIENTE: la version anterior ponia siempre manana "para no
programar una hora pasada". El dueno del proceso habria esperado a las 9:00 de
ese mismo dia y no habria pasado nada. Un fallo mudo, que solo salio al
comprobar NextRunTime.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))


def _cargar():
    ruta = RAIZ / "scripts" / "programar_9am.py"
    spec = importlib.util.spec_from_file_location("programar_9am", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


pg = _cargar()


class TestPrimerDisparo:
    def test_si_la_hora_no_ha_pasado_es_HOY(self):
        """El caso exacto del 09/09/2026: registrado a las 08:12 para las 9:00."""
        assert pg.primer_disparo("09:00", datetime(2026, 9, 9, 8, 12)) == datetime(
            2026, 9, 9, 9, 0
        )

    def test_si_la_hora_ya_paso_es_el_siguiente_laborable(self):
        # 09/09/2026 es miercoles -> jueves 10
        assert pg.primer_disparo("09:00", datetime(2026, 9, 9, 10, 30)) == datetime(
            2026, 9, 10, 9, 0
        )

    def test_justo_a_la_hora_pasa_al_siguiente(self):
        """Registrar a las 09:00:00 exactas no deja margen para arrancar."""
        assert pg.primer_disparo("09:00", datetime(2026, 9, 9, 9, 0)) == datetime(
            2026, 9, 10, 9, 0
        )

    def test_un_minuto_antes_todavia_es_hoy(self):
        assert pg.primer_disparo("09:00", datetime(2026, 9, 9, 8, 59)) == datetime(
            2026, 9, 9, 9, 0
        )

    def test_cruza_el_fin_de_mes(self):
        # 30/09/2026 es miercoles -> jueves 1 de octubre
        assert pg.primer_disparo("09:00", datetime(2026, 9, 30, 12, 0)) == datetime(
            2026, 10, 1, 9, 0
        )

    def test_respeta_los_minutos(self):
        assert pg.primer_disparo("09:30", datetime(2026, 9, 9, 8, 0)) == datetime(
            2026, 9, 9, 9, 30
        )


class TestSaltaElFinDeSemana:
    """El proceso es de gestion academica: en sabado y domingo no hay quien
    atienda una alerta, y el tablero tampoco se mueve."""

    def test_el_viernes_por_la_tarde_salta_al_lunes(self):
        # viernes 11/09/2026 a las 10:30 -> lunes 14
        d = pg.primer_disparo("09:00", datetime(2026, 9, 11, 10, 30))
        assert d == datetime(2026, 9, 14, 9, 0)
        assert d.strftime("%A") == "Monday"

    def test_el_sabado_salta_al_lunes(self):
        d = pg.primer_disparo("09:00", datetime(2026, 9, 12, 7, 0))
        assert d == datetime(2026, 9, 14, 9, 0)

    def test_el_domingo_salta_al_lunes(self):
        d = pg.primer_disparo("09:00", datetime(2026, 9, 13, 7, 0))
        assert d == datetime(2026, 9, 14, 9, 0)

    def test_el_viernes_por_la_manana_sigue_siendo_hoy(self):
        """No se salta un dia laborable que aun sirve."""
        d = pg.primer_disparo("09:00", datetime(2026, 9, 11, 8, 0))
        assert d == datetime(2026, 9, 11, 9, 0)
        assert d.strftime("%A") == "Friday"

    def test_el_primer_disparo_nunca_cae_en_fin_de_semana(self):
        """Se recorre una semana entera hora a hora."""
        from datetime import timedelta

        t = datetime(2026, 9, 7, 0, 0)  # lunes
        for _ in range(24 * 7):
            assert pg.primer_disparo("09:00", t).weekday() <= 4
            t += timedelta(hours=1)


class TestElXml:
    def test_es_semanal_de_lunes_a_viernes(self):
        xml = pg.construir_xml("09:00", simulacion=False, descripcion="x")
        assert "<ScheduleByWeek>" in xml
        assert "<WeeksInterval>1</WeeksInterval>" in xml
        for dia in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday"):
            assert f"<{dia} />" in xml
        assert "InteractiveToken" in xml
        assert "<StartWhenAvailable>true</StartWhenAvailable>" in xml

    def test_no_incluye_sabado_ni_domingo(self):
        xml = pg.construir_xml("09:00", simulacion=False, descripcion="x")
        assert "Saturday" not in xml
        assert "Sunday" not in xml

    def test_la_bateria_no_impide_arrancar(self):
        """El defecto de Windows perderia el dia en un portatil desenchufado."""
        xml = pg.construir_xml("09:00", simulacion=False, descripcion="x")
        assert "<DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>" in xml
        assert "<StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>" in xml

    def test_produccion_lleva_ejecutar_de_verdad(self):
        xml = pg.construir_xml("09:00", simulacion=False, descripcion="x")
        assert "--ejecutar-de-verdad" in xml

    def test_simulacion_no_lo_lleva(self):
        xml = pg.construir_xml("09:00", simulacion=True, descripcion="x")
        assert "--ejecutar-de-verdad" not in xml

    def test_el_limite_cubre_ventana_mas_dia(self):
        """90 min de ventana + ~4 h de dia no caben en 6 h con holgura."""
        assert pg.LIMITE_EJECUCION == "PT8H"
