"""Cerrojo del dia: ¿se actualizo hoy el tablero de Power BI?

Se ejecuta ANTES de exportar. Si el tablero es de otro dia, el reporte que se
descargaria es viejo, y vincular sobre datos viejos ensucia matriculas que ya
estaban correctas. Asi que no se exporta: se avisa y se para.

Solo LEE el tablero. No exporta, no descarga y no toca SINU.

Codigos de salida (los usa dia_completo.ps1 para ramificar):

    0   el tablero se actualizo HOY  -> seguir con el flujo
    3   el tablero es de otro dia    -> alerta enviada, no seguir
    4   no se pudo leer la fecha     -> alerta enviada, no seguir
    1   fallo tecnico (navegador, perfil, sesion)

El 3 y el 4 van aparte a proposito: no saber si esta actualizado NO es lo
mismo que saber que esta viejo. En el primer caso se reclama al departamento
de datos; en el segundo se mira si el tablero cambio de forma.

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


def _leer(cfg: Config, sin_cabeza: bool) -> Actualizacion:
    """Abre el informe, espera el lienzo y lee la fecha."""
    with sync_playwright() as pw:
        context, cerrar = abrir_contexto(pw, cfg, sin_cabeza)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page_informe, _ = _abrir_informe(context, page, cfg)
            # Sin esperar el lienzo se lee la pantalla de carga, y eso saldria
            # como "no hay fecha" en vez de "aun no ha cargado". Paso el primer
            # sondeo del 08/09/2026 y la captura fue lo que lo delato.
            _verificar_pagina(page_informe, cfg, [])
            page_informe.wait_for_timeout(MS_ASENTAR_LIENZO)
            return leer_actualizacion(page_informe, cfg)
        finally:
            cerrar()


def esperar_actualizacion(
    cfg: Config,
    sin_cabeza: bool,
    hoy: date,
    *,
    minutos_ventana: int,
    minutos_intervalo: int,
) -> tuple[Actualizacion | None, str]:
    """Reintenta la lectura hasta que el tablero sea de hoy, o se agote.

    Por que hay ventana y no una sola lectura: el 09/09/2026 a las 08:05 el
    tablero seguia diciendo 8/9/26, y el dia anterior a las 15:16 ya decia
    8/9/26. O sea que el refresco cae en algun momento de la manana, y puede
    ser DESPUES de las 9:00. Con una sola lectura, la tarea de las 9:00
    encontraria datos viejos todos los dias y mandaria una alerta diaria sin
    procesar nunca nada: la automatizacion quedaria inutil y la alerta se
    volveria ruido que nadie mira.

    Con ventana, "no esta actualizado" pasa a significar "no llego en el plazo
    que le damos", que es la lectura operativamente correcta.

    Devuelve (actualizacion, motivo_si_no_se_pudo_leer).
    """
    limite = time.monotonic() + minutos_ventana * 60
    intento = 0
    while True:
        intento += 1
        try:
            actualizacion = _leer(cfg, sin_cabeza)
        except ErrorFechaActualizacion as exc:
            # No poder leerla no se reintenta: significa que el tablero cambio
            # de forma, y esperar no lo arregla.
            return None, str(exc)

        if actualizacion.es_de(hoy):
            if intento > 1:
                print(f"   Llego en el intento {intento}.")
            return actualizacion, ""

        queda = limite - time.monotonic()
        if queda <= 0:
            return actualizacion, ""

        espera = min(minutos_intervalo * 60, queda)
        print(
            f"   Intento {intento}: {formatear(actualizacion, hoy)}. "
            f"Se reintenta en {espera / 60:.0f} min "
            f"(quedan {queda / 60:.0f} min de ventana)."
        )
        log.info(
            "Tablero aun de %s; reintento en %.0f min (ventana: %.0f min restantes)",
            actualizacion.fecha,
            espera / 60,
            queda / 60,
        )
        time.sleep(espera)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--visible", action="store_true", help="Navegador con ventana")
    p.add_argument(
        "--sin-avisar",
        action="store_true",
        help="Solo informa por consola; no manda ninguna notificacion.",
    )
    p.add_argument(
        "--esperar-minutos",
        type=int,
        default=None,
        help="Ventana de gracia: si el tablero aun es de ayer, reintenta hasta "
        "este total de minutos antes de dar la alerta. 0 = una sola lectura. "
        "Por defecto, CERROJO_ESPERA_MIN de config/.env.",
    )
    p.add_argument(
        "--intervalo-minutos",
        type=int,
        default=None,
        help="Cada cuantos minutos se reintenta dentro de la ventana.",
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

    ventana = args.esperar_minutos
    if ventana is None:
        ventana = cfg.cerrojo_espera_min
    intervalo = args.intervalo_minutos or cfg.cerrojo_intervalo_min
    sin_cabeza = False if args.visible else cfg.powerbi_headless

    if ventana > 0:
        print()
        print(f"Ventana de gracia: hasta {ventana} min, reintentando cada {intervalo}.")
        print("El tablero se refresca por la manana y puede tardar; sin ventana,")
        print("una tarea a las 9:00 alertaria todos los dias sin procesar nada.")

    try:
        actualizacion, ilegible = esperar_actualizacion(
            cfg,
            sin_cabeza,
            hoy,
            minutos_ventana=max(ventana, 0),
            minutos_intervalo=max(intervalo, 1),
        )
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
    print(f"Estado       : {formatear(actualizacion, hoy)}")

    # Criterio de exito: coincide exactamente con el dia en curso.
    if actualizacion.es_de(hoy):
        print()
        print("-> ACTUALIZADO HOY. El flujo puede continuar con la descarga.")
        return SALIDA_OK

    # Criterio de falla: la fecha es ANTERIOR al dia en curso.
    if actualizacion.es_anterior_a(hoy):
        print()
        print("-> NO ACTUALIZADO HOY. El flujo NO debe continuar.")
        print("   No se exporta ni se toca SINU: procesar datos de otro dia")
        print("   ensuciaria vinculaciones que ya estan correctas.")
        if not args.sin_avisar:
            r = notificaciones.enviar(
                notificaciones.aviso_tablero_desactualizado(
                    formatear(actualizacion, hoy), hoy=hoy
                ),
                cfg,
            )
            print(f"   Alerta: {r.resumen()}")
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
