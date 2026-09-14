"""Leer el estado de la tarea programada sin depender del idioma de Windows."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from moodle_sinu.tarea_programada import (  # noqa: E402
    EstadoTarea,
    calcular_proxima,
    interpretar_xml,
    siguiente_laborable,
)


def _xml(disparador: str, *, habilitada: str = "true", argumentos: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
{disparador}
  </Triggers>
  <Settings>
    <Enabled>{habilitada}</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>python.exe</Command>
      <Arguments>{argumentos}</Arguments>
    </Exec>
  </Actions>
</Task>
"""


SEMANAL = """    <CalendarTrigger>
      <StartBoundary>2026-09-15T09:00:00</StartBoundary>
      <ScheduleByWeek>
        <DaysOfWeek><Monday /><Friday /></DaysOfWeek>
        <WeeksInterval>1</WeeksInterval>
      </ScheduleByWeek>
    </CalendarTrigger>"""

UNA_VEZ = """    <TimeTrigger>
      <StartBoundary>2026-09-15T09:00:00</StartBoundary>
    </TimeTrigger>"""

REAL = "scripts/dia_completo.py --ejecutar-de-verdad"
ENSAYO = "scripts/dia_completo.py"


class TestInterpretarElXml:
    """Se lee el XML y no `/FO LIST /V`, cuyas etiquetas estan TRADUCIDAS.

    Es la misma leccion que dio Power BI: los selectores en espanol funcionaban
    hasta que Chromium headless arrancaba en ingles.
    """

    def test_tarea_semanal_encendida(self):
        e = interpretar_xml(_xml(SEMANAL, argumentos=REAL))
        assert e.existe and e.habilitada and not e.una_vez
        assert e.hora == "09:00"
        assert e.escribe
        assert e.resumen() == "ENCENDIDA - L a V"

    def test_tarea_de_una_sola_vez(self):
        e = interpretar_xml(_xml(UNA_VEZ, argumentos=REAL))
        assert e.una_vez
        assert e.resumen() == "ENCENDIDA - una sola vez"

    def test_tarea_apagada(self):
        e = interpretar_xml(_xml(SEMANAL, habilitada="false", argumentos=REAL))
        assert e.existe and not e.habilitada and not e.encendida
        assert e.resumen() == "APAGADA"

    def test_distingue_modo_real_de_ensayo(self):
        """Es la diferencia entre un ensayo y tocar matriculas de verdad, y el
        panel la muestra siempre para que no haya que recordarla."""
        assert interpretar_xml(_xml(SEMANAL, argumentos=REAL)).escribe
        assert not interpretar_xml(_xml(SEMANAL, argumentos=ENSAYO)).escribe

    def test_un_xml_ilegible_no_revienta(self):
        """Devuelve "no existe" en vez de lanzar: el panel tiene que abrirse
        igual para poder arreglar la situacion."""
        e = interpretar_xml("esto no es xml")
        assert not e.existe
        assert e.resumen() == "SIN PROGRAMAR"

    def test_sin_el_nodo_Enabled_se_asume_encendida(self):
        """Es el defecto de Windows cuando no se declara."""
        xml = _xml(SEMANAL, argumentos=REAL).replace(
            "<Enabled>true</Enabled>", ""
        )
        assert interpretar_xml(xml).habilitada


class TestProximaEjecucion:
    """Se CALCULA, no se lee: Windows la expone traducida y en formato local,
    y ya hubo que poner una guarda por el dia/mes al reves en el tablero."""

    def test_semanal_hoy_si_aun_no_paso(self):
        p = calcular_proxima("09:00", False, None, ahora=datetime(2026, 9, 15, 8, 0))
        assert p == datetime(2026, 9, 15, 9, 0)

    def test_semanal_manana_si_ya_paso(self):
        p = calcular_proxima("09:00", False, None, ahora=datetime(2026, 9, 15, 10, 0))
        assert p == datetime(2026, 9, 16, 9, 0)

    def test_semanal_salta_el_fin_de_semana(self):
        # viernes 11/09/2026 por la tarde -> lunes 14
        p = calcular_proxima("09:00", False, None, ahora=datetime(2026, 9, 11, 18, 0))
        assert p == datetime(2026, 9, 14, 9, 0)
        assert p.weekday() == 0

    def test_una_vez_pendiente(self):
        p = calcular_proxima(
            "09:00", True, datetime(2026, 9, 15, 9, 0), ahora=datetime(2026, 9, 14, 12, 0)
        )
        assert p == datetime(2026, 9, 15, 9, 0)

    def test_una_vez_ya_consumida_no_vuelve(self):
        """Un disparador de una sola vez gastado no tiene proxima. El panel lo
        dice: "no volvera a ejecutarse"."""
        p = calcular_proxima(
            "09:00", True, datetime(2026, 9, 15, 9, 0), ahora=datetime(2026, 9, 16, 9, 0)
        )
        assert p is None

    def test_hora_ilegible_no_revienta(self):
        assert calcular_proxima("", False, None) is None
        assert calcular_proxima("manana", False, None) is None


class TestSiguienteLaborable:
    def test_el_sabado_pasa_al_lunes(self):
        assert siguiente_laborable(datetime(2026, 9, 12, 9, 0)) == datetime(
            2026, 9, 14, 9, 0
        )

    def test_el_domingo_pasa_al_lunes(self):
        assert siguiente_laborable(datetime(2026, 9, 13, 9, 0)) == datetime(
            2026, 9, 14, 9, 0
        )

    def test_un_dia_laborable_no_se_mueve(self):
        assert siguiente_laborable(datetime(2026, 9, 15, 9, 0)) == datetime(
            2026, 9, 15, 9, 0
        )


class TestSinTarea:
    def test_el_estado_vacio_se_lee_claro(self):
        e = EstadoTarea()
        assert not e.existe and not e.encendida
        assert e.resumen() == "SIN PROGRAMAR"
