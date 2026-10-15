"""Cerrojo del dia: ¿se actualizo hoy el tablero de Power BI?

Se ejecuta ANTES de exportar. Si el tablero es de otro dia, el reporte que se
descargaria es viejo, y vincular sobre datos viejos ensucia matriculas que ya
estaban correctas. Asi que no se exporta: se sale y el orquestador pausa el dia.

Solo LEE el tablero. No exporta, no descarga y no toca SINU.

Codigos de salida (los usa dia_completo.py para ramificar):

    0   el tablero se actualizo HOY  -> seguir con el flujo
    3   el tablero es de otro dia    -> no seguir; el AVISO lo da el orquestador
    4   no se pudo leer la fecha     -> alerta enviada, no seguir
    1   fallo tecnico (navegador, perfil, sesion)

El 3 y el 4 van aparte a proposito: no saber si esta actualizado NO es lo
mismo que saber que esta viejo. En el primer caso se reclama al departamento
de datos; en el segundo se mira si el tablero cambio de forma.

Una sola lectura, sin ventana de espera (28/09/2026)
----------------------------------------------------
Hasta esta fecha, un tablero viejo se releia cada 15 min durante hasta 90 min,
con el navegador abierto. Se quito por decision del dueno del proceso: un
tablero de ayer PAUSA el dia en el acto (estado en `logs/estado/`, aviso y
evento en Calendar) y se relanza a mano cuando el departamento de datos lo
refresque. Esperar tenia sentido solo si el refresco llegaba solo; esperar a
ciegas bloqueaba la maquina hasta hora y media para, muchos dias, acabar igual.

Lo que SI se reintenta, y poco: la fecha ILEGIBLE. Una pantalla en blanco o un
lienzo a medio pintar es un tropiezo de carga, no un tablero viejo; dos
recargas con 10 s de pausa lo distinguen de un cambio de forma real.

Uso:
    python scripts\\verificar_actualizacion.py
    python scripts\\verificar_actualizacion.py --visible -v
    python scripts\\verificar_actualizacion.py --sin-avisar   # solo informar
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from playwright.sync_api import Error as ErrorPlaywright  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from moodle_sinu import notificaciones, registro  # noqa: E402
from moodle_sinu.actualizacion_powerbi import (  # noqa: E402
    Actualizacion,
    ErrorFechaActualizacion,
    formatear,
    leer_actualizacion,
)
from moodle_sinu.config import Config, asegurar_directorios  # noqa: E402
from moodle_sinu.exportador_powerbi import (  # noqa: E402
    _abrir_informe,
    _verificar_pagina,
)
from moodle_sinu.navegador import abrir_contexto  # noqa: E402

log = logging.getLogger("verificar_actualizacion")

SALIDA_OK = 0
SALIDA_FALLO_TECNICO = 1
SALIDA_DESACTUALIZADO = 3
SALIDA_ILEGIBLE = 4

#: Margen tras confirmar el lienzo. El cuadro de texto de la fecha no cuelga de
#: ningun visualContainer, asi que no hay un localizador de "visual cargado"
#: que esperar: se le da un momento a que el lienzo acabe de pintar.
MS_ASENTAR_LIENZO = 4000

#: Reintentos cuando la fecha NO SE PUEDE LEER (pantalla en blanco, lienzo a
#: medio pintar). Dos, rapidos: si tras dos recargas sigue sin leerse, lo mas
#: probable es que el tablero cambiara de forma, y esperar no lo arregla.
REINTENTOS_ILEGIBLE = 2

#: Pausa antes de cada recarga por fecha ilegible.
SEG_ESPERA_ILEGIBLE = 10


class _SesionTablero:
    """Un navegador abierto que sabe (re)leer la fecha del tablero.

    El contexto se abre UNA vez y cada relectura vuelve a navegar al informe
    sobre la misma pagina: es la recarga. Se re-navega en vez de `reload()` a
    proposito: es exactamente el mismo camino que la primera lectura, asi que no
    hay un segundo comportamiento que mantener ni que probar aparte.
    """

    def __init__(self, cfg: Config, sin_cabeza: bool) -> None:
        self._cfg = cfg
        self._pw = sync_playwright().start()
        self._context, self._cerrar = abrir_contexto(self._pw, cfg, sin_cabeza)
        self._page = (
            self._context.pages[0] if self._context.pages else self._context.new_page()
        )

    def leer(self) -> Actualizacion:
        """Navega al informe, espera el lienzo y lee la fecha."""
        page_informe, _ = _abrir_informe(self._context, self._page, self._cfg)
        # Sin esperar el lienzo se lee la pantalla de carga, y eso saldria
        # como "no hay fecha" en vez de "aun no ha cargado". Paso el primer
        # sondeo del 08/09/2026 y la captura fue lo que lo delato.
        _verificar_pagina(page_informe, self._cfg, [])
        page_informe.wait_for_timeout(MS_ASENTAR_LIENZO)
        return leer_actualizacion(page_informe, self._cfg)

    def cerrar(self) -> None:
        """Cierra el navegador y para Playwright. Tolera que ya este cerrado."""
        try:
            self._cerrar()
        finally:
            try:
                self._pw.stop()
            except Exception:  # noqa: BLE001 - cerrar no puede tumbar la corrida
                log.debug("Playwright ya estaba parado.", exc_info=True)


def _abrir_sesion(cfg: Config, sin_cabeza: bool) -> _SesionTablero:
    """Fabrica de sesiones. Existe para poder sustituirla en las pruebas."""
    return _SesionTablero(cfg, sin_cabeza)


def verificar_una_vez(
    cfg: Config,
    sin_cabeza: bool,
    *,
    reintentos_ilegible: int = REINTENTOS_ILEGIBLE,
    seg_espera_ilegible: float = SEG_ESPERA_ILEGIBLE,
    abrir_sesion=None,
) -> tuple[Actualizacion | None, str]:
    """Lee la fecha del tablero y devuelve en cuanto la tiene, sea la que sea.

    Una fecha legible -- de hoy o vieja -- se devuelve a la primera: decidir
    que hacer con ella es cosa de `main`, y una fecha vieja NO se relee.

    Solo la fecha ilegible se reintenta, `reintentos_ilegible` veces, con
    `seg_espera_ilegible` de pausa y una recarga del informe antes de cada una.

    El navegador se cierra al salir, pase lo que pase: dejarlo abierto en una
    tarea desatendida deja un Edge y un Python colgados, y el perfil persistente
    es uno solo -- con el ocupado, ninguna otra corrida del flujo puede arrancar.

    Args:
        abrir_sesion: fabrica de sesiones. Solo se sustituye en las pruebas.

    Devuelve (actualizacion, motivo_si_no_se_pudo_leer).
    """
    fabrica = abrir_sesion or _abrir_sesion
    sesion = fabrica(cfg, sin_cabeza)
    try:
        return _leer_con_reintentos(
            sesion,
            reintentos=max(reintentos_ilegible, 0),
            seg_espera=max(seg_espera_ilegible, 0),
        )
    finally:
        sesion.cerrar()


def _leer_con_reintentos(
    sesion, *, reintentos: int, seg_espera: float
) -> tuple[Actualizacion | None, str]:
    """Las lecturas sobre una sesion ya abierta.

    Aparte de `verificar_una_vez` para que el cierre del navegador viva en un
    `finally` que no pueda saltarse ninguna salida.
    """
    intentos = 1 + reintentos
    motivo = ""
    for intento in range(1, intentos + 1):
        try:
            actualizacion = sesion.leer()
        except ErrorFechaActualizacion as exc:
            motivo = str(exc)
            if intento == intentos:
                break
            print(
                f"   Intento {intento} de {intentos}: fecha ilegible ({motivo}). "
                f"Se recarga en {seg_espera:.0f} s."
            )
            log.warning(
                "Fecha ilegible en el intento %d de %d: %s", intento, intentos, motivo
            )
            time.sleep(seg_espera)
            continue

        if intento > 1:
            print(f"   Se pudo leer en el intento {intento}.")
        return actualizacion, ""

    return None, f"{motivo} (tras {intentos} intentos)"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--visible", action="store_true", help="Navegador con ventana")
    p.add_argument(
        "--sin-avisar",
        action="store_true",
        help="Solo informa por consola; no manda la alerta de fecha ilegible. "
        "(El aviso de tablero viejo lo da siempre el orquestador, no este script.)",
    )
    p.add_argument("--verbose", "-v", action="store_true", help="Log en DEBUG")
    args = p.parse_args(argv)

    asegurar_directorios()
    registro.configurar(
        logging.DEBUG if args.verbose else logging.INFO,
        etiqueta="verificar_actualizacion",
    )
    cfg = Config.desde_entorno()
    hoy = date.today()

    print("=" * 70)
    print(f"CERROJO DEL DIA - ¿se actualizo el tablero hoy {hoy:%d/%m/%Y}?")
    print("=" * 70)

    if not args.sin_avisar and not cfg.tiene_canal_de_aviso:
        # Se dice AHORA, no cuando haya que avisar: descubrir que no hay canal
        # en el momento de la alerta es descubrirlo tarde. No se aborta, porque
        # el respaldo en logs/avisos/ si deja constancia.
        print()
        print("AVISO: no hay canal de notificacion configurado.")
        print("       Las alertas solo quedaran en logs/avisos/.")
        print("       Configurar NOTIFICAR_WEBHOOK (Teams/Slack) en config/.env.")

    sin_cabeza = False if args.visible else cfg.powerbi_headless

    try:
        actualizacion, ilegible = verificar_una_vez(cfg, sin_cabeza)
        if ilegible:
            print()
            print(f"NO SE PUDO LEER la fecha de actualizacion: {ilegible}")
            if not args.sin_avisar:
                r = notificaciones.enviar(
                    notificaciones.aviso_no_se_pudo_leer(ilegible, hoy=hoy), cfg
                )
                print(f"Alerta: {r.resumen()}")
            return SALIDA_ILEGIBLE
    except (ErrorPlaywright, OSError, RuntimeError) as exc:
        # Fallo tecnico: ni se sabe la fecha ni se pudo mirar. No se manda la
        # alerta de "tablero viejo", que seria una conclusion inventada.
        log.exception("Fallo tecnico verificando la actualizacion")
        print()
        print(f"FALLO TECNICO: {exc}")
        return SALIDA_FALLO_TECNICO

    print()
    print(f"Tablero dice : {actualizacion.texto!r}")
    print(f"Interpretado : {actualizacion.fecha:%d/%m/%Y}")
    # dia_completo.py saca de esta linea el detalle de su aviso: no cambiarle
    # el rotulo sin cambiar `RX_ESTADO_TABLERO` alli.
    print(f"Estado       : {formatear(actualizacion, hoy)}")

    # Criterio de exito: coincide exactamente con el dia en curso.
    if actualizacion.es_de(hoy):
        print()
        print("-> ACTUALIZADO HOY. El flujo puede continuar con la descarga.")
        return SALIDA_OK

    # Criterio de falla: la fecha es ANTERIOR al dia en curso. Sin releer y sin
    # avisar desde aqui: el orquestador registra la pausa y da el aviso, asi que
    # avisar tambien aqui mandaria dos alertas y dos eventos por el mismo hecho.
    if actualizacion.es_anterior_a(hoy):
        print()
        print("-> NO ACTUALIZADO HOY. El flujo NO debe continuar.")
        print("   No se exporta ni se toca SINU: procesar datos de otro dia")
        print("   ensuciaria vinculaciones que ya estan correctas.")
        print("   No se relee: el dia se pausa y se relanza a mano cuando el")
        print("   tablero este al dia.")
        log.info("Tablero de %s, anterior a hoy: salida 3.", actualizacion.fecha)
        return SALIDA_DESACTUALIZADO

    # No queda otro caso: una fecha POSTERIOR a hoy no es un tablero viejo, y
    # `fecha_de_texto` ya la rechaza antes de llegar aqui. Si alguna vez se
    # llegara, seria un fallo del propio cerrojo y no puede pasar por "al dia".
    print()
    print(f"-> INCOHERENTE: el tablero dice {actualizacion.fecha:%d/%m/%Y}, que es")
    print(f"   posterior a hoy ({hoy:%d/%m/%Y}). No se continua.")
    if not args.sin_avisar:
        r = notificaciones.enviar(
            notificaciones.aviso_no_se_pudo_leer(
                f"fecha posterior a hoy: {actualizacion.texto!r}", hoy=hoy
            ),
            cfg,
        )
        print(f"   Alerta: {r.resumen()}")
    return SALIDA_ILEGIBLE


if __name__ == "__main__":
    raise SystemExit(main())
