"""El cerrojo del tablero: una sola lectura, sin ventana de espera.

Hasta el 28/09/2026 un tablero viejo se releia cada 15 min durante hasta 90
min. Ahora una fecha legible -- de hoy o vieja -- se devuelve a la primera, y
solo la fecha ILEGIBLE (pantalla en blanco, lienzo a medio pintar) tiene dos
reintentos rapidos con 10 s de pausa y recarga.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

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

AYER = Actualizacion(fecha=date(2026, 9, 8), texto="Datos actualizados el 8/9/26")
DE_HOY = Actualizacion(fecha=date(2026, 9, 9), texto="Datos actualizados el 9/9/26")


class _SesionFalsa:
    """Una sesion de tablero simulada. Cuenta aperturas, lecturas y cierres."""

    aperturas = 0

    def __init__(self, lecturas):
        self.pendientes = list(lecturas)
        self.leidas = 0
        self.cerrada = False
        type(self).aperturas += 1

    def leer(self):
        self.leidas += 1
        valor = self.pendientes.pop(0)
        if isinstance(valor, Exception):
            raise valor
        return valor

    def cerrar(self):
        self.cerrada = True


@pytest.fixture
def dormido(monkeypatch):
    """Las pruebas no esperan de verdad: se anota cuanto se habria dormido."""
    anotado: list[float] = []
    monkeypatch.setattr(va.time, "sleep", anotado.append)
    return anotado


def _sesion(monkeypatch, lecturas) -> _SesionFalsa:
    _SesionFalsa.aperturas = 0
    sesion = _SesionFalsa(lecturas)
    monkeypatch.setattr(va, "_abrir_sesion", lambda cfg, sin_cabeza: sesion)
    return sesion


def _ilegible(texto="no aparece el texto"):
    return ErrorFechaActualizacion(texto)


class TestUnaSolaLectura:
    def test_de_hoy_sale_a_la_primera(self, monkeypatch, dormido):
        sesion = _sesion(monkeypatch, [DE_HOY])
        act, ilegible = va.verificar_una_vez(Config(), True)
        assert act is DE_HOY and ilegible == ""
        assert dormido == []
        assert sesion.leidas == 1

    def test_vieja_sale_a_la_primera_sin_releer(self, monkeypatch, dormido):
        """Lo que cambio el 28/09/2026: un tablero viejo NO se espera."""
        sesion = _sesion(monkeypatch, [AYER, DE_HOY])
        act, ilegible = va.verificar_una_vez(Config(), True)
        assert act is AYER and ilegible == ""
        assert dormido == []
        assert sesion.leidas == 1  # la segunda lectura ni se intenta


class TestFechaIlegible:
    def test_se_recupera_en_el_primer_reintento(self, monkeypatch, dormido):
        sesion = _sesion(monkeypatch, [_ilegible(), DE_HOY])
        act, ilegible = va.verificar_una_vez(Config(), True)
        assert act is DE_HOY and ilegible == ""
        assert dormido == [10]
        assert sesion.leidas == 2

    def test_tras_una_recarga_puede_salir_vieja(self, monkeypatch, dormido):
        """Legible y vieja tras reintentar: se devuelve, y `main` saldra con 3."""
        _sesion(monkeypatch, [_ilegible(), _ilegible(), AYER])
        act, ilegible = va.verificar_una_vez(Config(), True)
        assert act is AYER and ilegible == ""
        assert dormido == [10, 10]

    def test_como_mucho_dos_reintentos(self, monkeypatch, dormido):
        sesion = _sesion(
            monkeypatch, [_ilegible(), _ilegible(), _ilegible("cambio de forma"), DE_HOY]
        )
        act, ilegible = va.verificar_una_vez(Config(), True)
        assert act is None
        assert "cambio de forma" in ilegible and "3 intentos" in ilegible
        assert sesion.leidas == 3  # 1 + 2 reintentos; la cuarta no se gasta
        assert dormido == [10, 10]  # no se duerme tras el ultimo

    def test_sin_reintentos_no_se_espera(self, monkeypatch, dormido):
        _sesion(monkeypatch, [_ilegible()])
        act, _ = va.verificar_una_vez(Config(), True, reintentos_ilegible=0)
        assert act is None
        assert dormido == []

    def test_los_valores_pedidos(self):
        assert va.REINTENTOS_ILEGIBLE == 2
        assert va.SEG_ESPERA_ILEGIBLE == 10


class TestUnSoloNavegador:
    """El perfil persistente es uno solo: un Edge colgado impide la siguiente
    corrida. El navegador se abre una vez y se cierra por cualquier salida."""

    def test_los_reintentos_reusan_el_navegador(self, monkeypatch, dormido):
        sesion = _sesion(monkeypatch, [_ilegible(), _ilegible(), DE_HOY])
        va.verificar_una_vez(Config(), True)
        assert sesion.leidas == 3
        assert _SesionFalsa.aperturas == 1

    @pytest.mark.parametrize(
        "lecturas",
        [[DE_HOY], [AYER], [_ilegible(), _ilegible(), _ilegible()]],
        ids=["de-hoy", "vieja", "ilegible"],
    )
    def test_se_cierra_en_cada_salida(self, monkeypatch, dormido, lecturas):
        sesion = _sesion(monkeypatch, lecturas)
        va.verificar_una_vez(Config(), True)
        assert sesion.cerrada

    def test_se_cierra_aunque_la_lectura_reviente(self, monkeypatch, dormido):
        """Un fallo tecnico sube al CLI como SALIDA_FALLO_TECNICO, sin
        reintentar: no es una fecha ilegible."""
        sesion = _sesion(monkeypatch, [RuntimeError("el navegador murio"), DE_HOY])
        with pytest.raises(RuntimeError):
            va.verificar_una_vez(Config(), True)
        assert sesion.cerrada
        assert sesion.leidas == 1
        assert dormido == []


class TestCodigosDeSalida:
    @pytest.fixture
    def cli(self, monkeypatch):
        """`main` sin navegador, sin logs y registrando los avisos."""
        avisos = []
        monkeypatch.setattr(va, "asegurar_directorios", lambda: None)
        monkeypatch.setattr(va.registro, "configurar", lambda *a, **k: None)
        monkeypatch.setattr(
            va.Config, "desde_entorno", classmethod(lambda cls: Config())
        )
        def falso_enviar(aviso, cfg):
            avisos.append(aviso)
            return va.notificaciones.ResultadoEnvio(enviado=True)

        monkeypatch.setattr(va.notificaciones, "enviar", falso_enviar)

        def con_lectura(resultado):
            monkeypatch.setattr(
                va, "verificar_una_vez", lambda cfg, sin_cabeza: resultado
            )

        return con_lectura, avisos

    def test_de_hoy_es_0(self, cli):
        con_lectura, avisos = cli
        hoy = date.today()
        con_lectura((Actualizacion(fecha=hoy, texto="hoy"), ""))
        assert va.main([]) == va.SALIDA_OK
        assert avisos == []

    def test_vieja_es_3_y_no_avisa_desde_aqui(self, cli):
        """El aviso del tablero viejo lo da el orquestador. Si el cerrojo
        tambien avisara, llegarian dos alertas y dos eventos de Calendar."""
        con_lectura, avisos = cli
        ayer = date.today() - timedelta(days=1)
        con_lectura((Actualizacion(fecha=ayer, texto="ayer"), ""))
        assert va.main([]) == va.SALIDA_DESACTUALIZADO
        assert avisos == []

    def test_vieja_imprime_la_linea_que_lee_el_orquestador(self, cli, capsys):
        con_lectura, _ = cli
        ayer = date.today() - timedelta(days=1)
        con_lectura((Actualizacion(fecha=ayer, texto="ayer"), ""))
        va.main([])
        assert any(
            l.startswith("Estado       :") for l in capsys.readouterr().out.splitlines()
        )

    def test_ilegible_es_4_y_si_avisa(self, cli):
        con_lectura, avisos = cli
        con_lectura((None, "no aparece el texto (tras 3 intentos)"))
        assert va.main([]) == va.SALIDA_ILEGIBLE
        assert len(avisos) == 1

    def test_ilegible_con_sin_avisar_no_avisa(self, cli):
        con_lectura, avisos = cli
        con_lectura((None, "no aparece el texto"))
        assert va.main(["--sin-avisar"]) == va.SALIDA_ILEGIBLE
        assert avisos == []

    def test_ya_no_hay_opciones_de_ventana(self, cli):
        con_lectura, _ = cli
        con_lectura((None, "x"))
        with pytest.raises(SystemExit):
            va.main(["--esperar-minutos", "90"])
