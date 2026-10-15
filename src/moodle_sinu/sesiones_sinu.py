"""Tres navegadores, cada uno con su sesion de SINU: el 1 en la 07, el 2 en la
05 y el 3 en la 50.

Decision del dueno del proceso (28/09/2026). Sustituye a la regla del 25/09
("todo en la misma sesion, cambiando de modulo").

Por que
-------
Con una sola sesion, verificar un grupo era salir de ISEF07 a ISEF05 o PACF50 y
volver, y cada cambio de modulo pasa por `#home` y repinta la aplicacion entera
de SmartClient. Eso es lo que deja los filtros como `<input disabled>`. El
28/09/2026 en 26ES5 se vio completo:

  - la verificacion previa de 4 grupos (165 de 176 filas) no obtuvo NINGUNA
    respuesta: en la 05 y en la 50 el campo de asignatura siguio deshabilitado
    los 120 s de espera, grupo tras grupo (~17 min);
  - al volver, la grilla de ISEF07 tampoco revivio: 3 lecturas vacias de 124 s
    y el lote se detuvo en la fila 4. 172 filas sin procesar.

Esperar mas no lo habria arreglado: se espero y el campo no se habilito. Lo que
lo arregla es no compartir la pantalla. Cada modulo tiene su navegador y no se
mueve de el: el de la 07 no sale nunca de ISEF07.

Navegadores y no pestanas
-------------------------
Dos pestanas del mismo navegador comparten cookies, y con ellas la sesion del
servidor: un login en la pestana de la 05 podria pisar la de la 07. Cada
navegador aparte (`navegador.abrir_navegador_aparte`) tiene sus cookies y hace
su propio login, asi que las tres sesiones son independientes.

Cada ISEF con sus tiempos
-------------------------
Nada de lo que pase en uno se da por hecho en otro: que la 07 vaya lenta o
falle no dice nada de la 05 ni de la 50, y al reves. Cada lector espera a su
propia pantalla con sus propios plazos, y fija el periodo de la fila que se
esta gestionando en cada consulta.

Los navegadores de la 05 y la 50 se abren la primera vez que hacen falta y se
reutilizan para todo el lote. Si uno no logra abrir sesion, no se da por
perdido: se vuelve a intentar la siguiente vez que haga falta, hasta
`MAX_APERTURAS` por lote.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from .acceso_sinu import ErrorAccesoSinu, abrir_y_acceder
from .config import Config

log = logging.getLogger(__name__)

MODULO_ISEF05 = "isef05"
MODULO_PACF50 = "pacf50"

#: Cuantas veces se intenta abrir la sesion de un modulo en un lote. Dos: un
#: login que falla puede ser del momento, pero cada intento cuesta hasta el
#: plazo de carga de SINU y no puede repetirse por cada grupo del lote.
MAX_APERTURAS = 2


@dataclass
class _Sesion:
    pagina: object
    cerrar: Callable[[], None]


class SesionesSinu:
    """El navegador de ISEF07 (ya abierto) y, bajo demanda, los de ISEF05 y PACF50."""

    def __init__(
        self,
        pw,
        cfg: Config,
        pagina_isef07,
        *,
        sin_cabeza: bool = True,
        abrir_navegador=None,
        acceder=None,
    ) -> None:
        self._pw = pw
        self._cfg = cfg
        self._sin_cabeza = sin_cabeza
        self.isef07 = pagina_isef07
        self._abrir_navegador = abrir_navegador or self._navegador_por_defecto
        self._acceder = acceder or abrir_y_acceder
        self._sesiones: dict[str, _Sesion] = {}
        #: Cuantas veces se reabrio SINU en el navegador de la 07 en este lote.
        self.reaperturas_07 = 0
        self._aperturas: dict[str, int] = {}
        self._ultimo_fallo: dict[str, str] = {}

    def _navegador_por_defecto(self):
        from .navegador import abrir_navegador_aparte

        return abrir_navegador_aparte(self._pw, self._cfg, self._sin_cabeza)

    def pagina(self, modulo: str):
        """La pagina del navegador de `modulo`, con su sesion. Lo abre si hace falta.

        Raises:
            ErrorAccesoSinu: si no se pudo abrir el navegador o entrar a SINU.
        """
        sesion = self._sesiones.get(modulo)
        if sesion is None:
            sesion = self._abrir(modulo)
        _al_frente(sesion.pagina)
        return sesion.pagina

    def _abrir(self, modulo: str) -> _Sesion:
        hechas = self._aperturas.get(modulo, 0)
        if hechas >= MAX_APERTURAS:
            raise ErrorAccesoSinu(
                f"la sesion de {modulo} no se pudo abrir en {hechas} intento(s) "
                f"este lote ({self._ultimo_fallo.get(modulo, 'sin detalle')})"
            )
        self._aperturas[modulo] = hechas + 1
        log.info(
            "Abriendo el navegador de %s (intento %d de %d).",
            modulo, hechas + 1, MAX_APERTURAS,
        )

        cerrar: Callable[[], None] = lambda: None  # noqa: E731
        try:
            context, cerrar = self._abrir_navegador()
            pagina = context.new_page()
            self._acceder(pagina, self._cfg)
        except Exception as exc:  # noqa: BLE001 - un fallo aqui es "no contesto"
            cerrar()
            self._ultimo_fallo[modulo] = str(exc).splitlines()[0][:160]
            log.warning(
                "No se pudo abrir la sesion de %s: %s", modulo, self._ultimo_fallo[modulo]
            )
            raise ErrorAccesoSinu(
                f"no se pudo abrir la sesion de {modulo}: {self._ultimo_fallo[modulo]}"
            ) from exc

        sesion = _Sesion(pagina=pagina, cerrar=cerrar)
        self._sesiones[modulo] = sesion
        log.info("Sesion de %s lista; queda abierta para todo el lote.", modulo)
        return sesion

    def isef05(self):
        return self.pagina(MODULO_ISEF05)

    def pacf50(self):
        return self.pagina(MODULO_PACF50)

    def volver_a_isef07(self):
        """Pone al frente el navegador de la 07. No navega: nunca salio de ISEF07."""
        _al_frente(self.isef07)
        return self.isef07

    @property
    def abiertas(self) -> tuple[str, ...]:
        return tuple(self._sesiones)

    def cerrar(self) -> None:
        """Cierra los navegadores de la 05 y la 50. El de la 07 no es suyo."""
        for sesion in self._sesiones.values():
            try:
                sesion.cerrar()
            except Exception:  # noqa: BLE001 - cerrar no puede tumbar el lote
                log.debug("El navegador ya estaba cerrado.", exc_info=True)
        self._sesiones.clear()


def _al_frente(pagina) -> None:
    """SmartClient pinta con temporizadores y los navegadores frenan los de las
    ventanas de fondo: la que se va a usar va al frente."""
    try:
        pagina.bring_to_front()
    except Exception as exc:  # noqa: BLE001 - no es critico
        log.debug("No se pudo traer la ventana al frente: %s", exc)
