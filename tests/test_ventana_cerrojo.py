"""La ventana de gracia del cerrojo del tablero.

Existe por lo que se midio el 09/09/2026: a las 08:05 el tablero aun decia
8/9/26, y el dia anterior a las 15:16 ya decia 8/9/26. El refresco cae en algun
momento de la manana y puede ser DESPUES de las 9:00. Con una sola lectura, la
tarea de las 9:00 alertaria todos los dias sin procesar nada, y la alerta se
volveria ruido que nadie mira.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from moodle_sinu.actualizacion_powerbi import (  # noqa: E402
    Actualizacion,
    ErrorFechaActualizacion,
)
from moodle_sinu.config import Config  # noqa: E402


def _cargar():
    ruta = RAIZ / "scripts" / "verificar_actualizacion.py"
    spec = importlib.util.spec_from_file_location("verificar_actualizacion", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


va = _cargar()

HOY = date(2026, 9, 9)
AYER = Actualizacion(fecha=date(2026, 9, 8), texto="Datos actualizados el 8/9/26")
DE_HOY = Actualizacion(fecha=date(2026, 9, 9), texto="Datos actualizados el 9/9/26")


class _Reloj:
    """Reloj y sueno simulados: las pruebas no esperan de verdad."""

    def __init__(self):
        self.ahora = 0.0
        self.dormido = []

    def monotonic(self):
        return self.ahora

    def sleep(self, segundos):
        self.dormido.append(segundos)
        self.ahora += segundos


def _preparar(monkeypatch, lecturas):
    """`lecturas` se consume una por intento; una excepcion se lanza."""
    reloj = _Reloj()
    monkeypatch.setattr(va.time, "monotonic", reloj.monotonic)
    monkeypatch.setattr(va.time, "sleep", reloj.sleep)
    pendientes = list(lecturas)

    def falso(cfg, sin_cabeza):
        valor = pendientes.pop(0)
        if isinstance(valor, Exception):
            raise valor
        return valor

    monkeypatch.setattr(va, "_leer", falso)
    return reloj, pendientes


class TestCuandoYaEstaAlDia:
    def test_una_sola_lectura_y_a_correr(self, monkeypatch):
        reloj, quedan = _preparar(monkeypatch, [DE_HOY])
        act, ilegible = va.esperar_actualizacion(
            Config(), True, HOY, minutos_ventana=90, minutos_intervalo=15
        )
        assert act is DE_HOY and ilegible == ""
        assert reloj.dormido == []  # no espero nada
        assert quedan == []


class TestCuandoLlegaTarde:
    def test_espera_y_lo_pilla_al_tercer_intento(self, monkeypatch):
        """El caso que motiva todo: el tablero llega a media manana."""
        reloj, _ = _preparar(monkeypatch, [AYER, AYER, DE_HOY])
        act, ilegible = va.esperar_actualizacion(
            Config(), True, HOY, minutos_ventana=90, minutos_intervalo=15
        )
        assert act is DE_HOY and ilegible == ""
        assert reloj.dormido == [900, 900]  # dos esperas de 15 min

    def test_no_se_pasa_de_la_ventana(self, monkeypatch):
        """La ultima espera se recorta para no exceder el plazo dado."""
        reloj, _ = _preparar(monkeypatch, [AYER, AYER, DE_HOY])
        va.esperar_actualizacion(
            Config(), True, HOY, minutos_ventana=20, minutos_intervalo=15
        )
        assert reloj.dormido == [900, 300]  # 15 min y luego solo los 5 que quedan
        assert sum(reloj.dormido) == 20 * 60


class TestCuandoNoLlega:
    def test_agotada_la_ventana_devuelve_el_tablero_viejo(self, monkeypatch):
        """Y entonces el CLI da la alerta critica y sale con 3."""
        reloj, _ = _preparar(monkeypatch, [AYER, AYER])
        act, ilegible = va.esperar_actualizacion(
            Config(), True, HOY, minutos_ventana=15, minutos_intervalo=15
        )
        assert act is AYER and ilegible == ""
        assert act.es_anterior_a(HOY)

    def test_ventana_cero_es_el_modo_estricto(self, monkeypatch):
        """Una sola lectura, sin esperar: el comportamiento de antes."""
        reloj, quedan = _preparar(monkeypatch, [AYER])
        act, _ = va.esperar_actualizacion(
            Config(), True, HOY, minutos_ventana=0, minutos_intervalo=15
        )
        assert act is AYER
        assert reloj.dormido == []
        assert quedan == []


class TestLoQueNoSeReintenta:
    def test_si_no_se_puede_leer_no_se_espera(self, monkeypatch):
        """Esperar no arregla que el tablero cambiara de forma, y reintentar
        durante 90 minutos solo retrasaria el aviso de que hay que sondearlo."""
        reloj, quedan = _preparar(
            monkeypatch,
            [ErrorFechaActualizacion("no aparece el texto"), DE_HOY],
        )
        act, ilegible = va.esperar_actualizacion(
            Config(), True, HOY, minutos_ventana=90, minutos_intervalo=15
        )
        assert act is None
        assert "no aparece el texto" in ilegible
        assert reloj.dormido == []
        assert len(quedan) == 1  # no gasto la segunda lectura


class TestValoresPorDefecto:
    def test_la_ventana_viene_de_la_config(self):
        c = Config()
        assert c.cerrojo_espera_min == 90
        assert c.cerrojo_intervalo_min == 15

    def test_noventa_minutos_cubren_hasta_las_diez_y_media(self):
        """Con la tarea a las 9:00. Es el razonamiento del valor por defecto."""
        assert 9 * 60 + Config().cerrojo_espera_min == 10 * 60 + 30
