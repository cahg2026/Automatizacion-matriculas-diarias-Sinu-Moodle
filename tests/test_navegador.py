"""El cierre del navegador no puede tumbar una corrida ya terminada.

Medido el 26/09/2026, y costaba el dia entero.

Cuando el proceso del navegador se muere de golpe (el `0xC0000005` de siempre),
Playwright no levanta un `Error` suyo sino un **`Exception` pelado**:

    Exception: : Connection closed while reading from the driver

`cerrar()` solo atrapaba `ErrorPlaywright`, asi que ese escapaba desde el
`finally` de `exportar_reporte` -- que esta ANTES de las lineas que validan el
.xlsx y devuelven el resultado. La descarga habia funcionado, el archivo estaba
en disco y era valido, y el intento se contaba como fallido igual.

Lo comprobado ese dia: 5 intentos, 2 con reporte bueno en `data/raw/` (269
filas, estructura correcta), y el flujo abortado con "La exportacion de Power BI
fallo en los 5 intentos". El 25/09 habia pasado lo mismo a las 08:38.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from moodle_sinu import navegador  # noqa: E402
from moodle_sinu.config import Config  # noqa: E402


class _ContextoQueFallaAlCerrar:
    """Un contexto cuyo `close()` revienta, como el de un navegador muerto."""

    def __init__(self, excepcion):
        self.excepcion = excepcion
        self.intentos = 0

    def close(self, reason=None):
        self.intentos += 1
        raise self.excepcion


class _PwFalso:
    """Lo minimo de `sync_playwright()` que `abrir_contexto` toca."""

    def __init__(self, contexto):
        self.chromium = self
        self._contexto = contexto

    def launch_persistent_context(self, _ruta, **_kwargs):
        return self._contexto


def _cerrar_de(monkeypatch, tmp_path, excepcion):
    """Devuelve (funcion_cerrar, contexto) de un `abrir_contexto` simulado."""
    class _PerfilFalso:
        ruta = tmp_path / "perfil"
        argumentos: list = []
        descripcion = "perfil de prueba"
        es_chrome_real = False
        directorio = "Default"

    perfil = _PerfilFalso()
    monkeypatch.setattr(navegador.perfil_navegador, "resolver", lambda _cfg: perfil)
    monkeypatch.setattr(
        navegador.perfil_navegador, "exigir_disponible", lambda _p: None
    )
    contexto = _ContextoQueFallaAlCerrar(excepcion)
    _ctx, cerrar = navegador.abrir_contexto(_PwFalso(contexto), Config(), True)
    return cerrar, contexto


class TestCerrarNuncaTumbaLaCorrida:
    def test_el_exception_pelado_del_driver_no_escapa(self, monkeypatch, tmp_path):
        """EL caso del 26/09/2026. Playwright lo lanza como `Exception`, no como
        `playwright.Error`, y por eso se colaba."""
        cerrar, contexto = _cerrar_de(
            monkeypatch,
            tmp_path,
            Exception(": Connection closed while reading from the driver"),
        )
        cerrar()  # no debe lanzar
        assert contexto.intentos == 1

    def test_el_error_de_playwright_tampoco_escapa(self, monkeypatch, tmp_path):
        """El caso que ya estaba cubierto: el operador cierra la ventana."""
        from playwright.sync_api import Error as ErrorPlaywright

        cerrar, _ = _cerrar_de(
            monkeypatch, tmp_path, ErrorPlaywright("Target page has been closed")
        )
        cerrar()

    def test_un_oserror_al_cerrar_tampoco(self, monkeypatch, tmp_path):
        """Cerrar es limpieza. Si el trabajo ya esta hecho y escrito en disco,
        que la limpieza falle no puede tirarlo -- como mucho deja un proceso
        colgado, y de eso se encarga `limpiar_chrome_colgado` entre intentos."""
        cerrar, _ = _cerrar_de(monkeypatch, tmp_path, OSError("tuberia rota"))
        cerrar()

    def test_un_cierre_normal_si_cierra(self, monkeypatch, tmp_path):
        """Tolerar el fallo no puede convertirse en no cerrar nunca."""
        cerrados = []

        class _ContextoSano:
            def close(self, reason=None):
                cerrados.append(True)

        class _PerfilFalso:
            ruta = tmp_path / "perfil"
            argumentos: list = []
            descripcion = "perfil de prueba"
            es_chrome_real = False
            directorio = "Default"

        monkeypatch.setattr(
            navegador.perfil_navegador, "resolver", lambda _cfg: _PerfilFalso()
        )
        monkeypatch.setattr(
            navegador.perfil_navegador, "exigir_disponible", lambda _p: None
        )
        _ctx, cerrar = navegador.abrir_contexto(
            _PwFalso(_ContextoSano()), Config(), True
        )
        cerrar()
        assert cerrados == [True]

    def test_el_keyboardinterrupt_si_sube(self, monkeypatch, tmp_path):
        """Ctrl+C tiene que seguir parando el proceso. `except Exception` no lo
        atrapa (hereda de BaseException), y asi debe seguir siendo."""
        cerrar, _ = _cerrar_de(monkeypatch, tmp_path, KeyboardInterrupt())
        with pytest.raises(KeyboardInterrupt):
            cerrar()


class TestPararPlaywrightNuncaTumbaLaCorrida:
    """El mismo fallo, una capa mas arriba (26/09/2026).

    Con `cerrar()` ya blindado, el crash se mudo a SALIR del
    `with sync_playwright()`: su `__exit__` llama a `stop_sync()` y levanta
    `asyncio.exceptions.InvalidStateError: invalid state`. Como el `with`
    envuelve toda la etapa, saltaba antes de validar el .xlsx y devolver el
    resultado: descarga hecha, archivo valido en disco, intento fallido.
    """

    class _PwQueFallaAlParar:
        def __init__(self, excepcion):
            self.excepcion = excepcion
            self.intentos = 0

        def stop(self):
            self.intentos += 1
            raise self.excepcion

    def test_el_invalidstateerror_no_escapa(self):
        """EL caso medido, tal cual sale del traceback."""
        import asyncio

        pw = self._PwQueFallaAlParar(asyncio.InvalidStateError("invalid state"))
        navegador.parar_playwright(pw)  # no debe lanzar
        assert pw.intentos == 1

    def test_un_pw_sano_si_para(self):
        parados = []

        class _PwSano:
            def stop(self):
                parados.append(True)

        navegador.parar_playwright(_PwSano())
        assert parados == [True]

    def test_el_keyboardinterrupt_si_sube(self):
        pw = self._PwQueFallaAlParar(KeyboardInterrupt())
        with pytest.raises(KeyboardInterrupt):
            navegador.parar_playwright(pw)


#: Los que hacen trabajo que no se puede perder al desmontar el navegador:
#: descargan un .xlsx, escriben en SINU o reparan matriculas. Si el `with`
#: vuelve a colarse aqui, una corrida terminada se cuenta como fallida.
CRITICOS = (
    "src/moodle_sinu/exportador_powerbi.py",
    "scripts/ejecutar_sinu.py",
    "scripts/reparar_desvinculados.py",
    "scripts/clasificar_sinu.py",
    "src/moodle_sinu/aviso_calendar.py",
)


@pytest.mark.parametrize("relativa", CRITICOS)
def test_no_usan_el_with_de_playwright(relativa):
    """La guarda estructural: si alguien vuelve a poner `with sync_playwright()`
    en uno de estos, el fallo del 26/09/2026 vuelve entero y en silencio --
    porque solo se nota los dias en que el navegador se muere.

    Se comprobo primero en la exportacion y el 26/09 se descubrio que
    `ejecutar_sinu` -- el unico que ESCRIBE en SINU -- seguia con el `with`."""
    ruta = RAIZ / relativa
    # Solo lineas de CODIGO: los comentarios citan el `with` viejo a proposito,
    # para explicar por que ya no esta.
    codigo = [
        l for l in ruta.read_text(encoding="utf-8").splitlines()
        if not l.lstrip().startswith("#")
    ]
    assert not [l for l in codigo if "with sync_playwright()" in l], (
        f"{relativa} volvio al `with`: una corrida terminada se contaria como fallida"
    )
    assert [l for l in codigo if "sync_playwright().start()" in l]
    assert [l for l in codigo if "parar_playwright(pw)" in l]
