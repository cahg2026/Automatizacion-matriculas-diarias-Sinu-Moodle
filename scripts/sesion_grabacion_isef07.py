"""Sesion de grabacion de ISEF07: deja el entorno listo y cede el mando.

Que monta antes de pausar
-------------------------
    pestana 1: el Google Sheet del dia
    pestana 2: SINU, con sesion, en ISEF07 y con el Periodo YA fijado y verificado

Y a partir de ahi el operador trabaja. La ejecucion se detiene en `page.pause()`,
que abre el Inspector de Playwright: ahi se ve el codigo generado EN VIVO, sin
depender de que el navegador se cierre bien.

Tres capturas a la vez, y no por exceso de celo
-----------------------------------------------
1. **Inspector** (`page.pause()`): codigo en vivo, se copia de la ventana.
2. **Captura propia** (`captura_dom`): cada clic y cada cambio, con el DOM del
   elemento y la pestana donde ocurrio, volcado a JSONL **en el momento**. Es la
   unica que sobrevive a que el navegador muera, y la unica que dice si un
   selector es ESTABLE o depende de un id que SmartClient regenera.
3. **Traza de Playwright**: instantaneas del DOM para revisar despues con
   `playwright show-trace`.

El 01/09/2026 una sesion de grabacion se perdio entera porque el grabador no
llego a escribir el archivo. Con 15 matriculas reales de por medio, repetir no
es una opcion aceptable: de ahi la redundancia.

OJO -- esto NO es una corrida en simulacion. Lo que el operador pulse en ISEF07
ocurre de verdad: es su trabajo del dia, y este script solo observa. Ni
`MODO_SIMULACION` ni `--ejecutar-de-verdad` intervienen aqui, porque no es la
automatizacion la que actua.

Uso:
    python scripts/sesion_grabacion_isef07.py --sheet-url URL --periodo 2026C
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

# permite ejecutar el script sin instalar el paquete
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from playwright.sync_api import sync_playwright  # noqa: E402

from moodle_sinu import registro  # noqa: E402
from moodle_sinu.acceso_sinu import ErrorAccesoSinu, abrir_y_acceder  # noqa: E402
from moodle_sinu.captura_dom import Capturador  # noqa: E402
from moodle_sinu.config import DIR_LOGS, Config, asegurar_directorios  # noqa: E402
from moodle_sinu.constantes_sinu import ACTIVIDAD_VINCULACION  # noqa: E402
from moodle_sinu.lector_sinu import (  # noqa: E402
    ErrorLecturaSinu,
    entrar_en_modulo,
    fijar_periodo,
    periodo_actual,
)
from moodle_sinu.navegador import abrir_contexto  # noqa: E402
from moodle_sinu.perfil_navegador import ErrorPerfilNavegador  # noqa: E402

log = logging.getLogger("sesion_grabacion")


def _argumentos() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Sesion de grabacion de ISEF07")
    p.add_argument("--sheet-url", required=True, help="URL del Google Sheet del dia")
    p.add_argument(
        "--periodo",
        required=True,
        help="COD_PERIODO a fijar antes de ceder el mando (p. ej. 2026C)",
    )
    p.add_argument(
        "--salida",
        default=None,
        help="JSONL de la captura propia (por defecto, logs/captura_<sello>.jsonl)",
    )
    p.add_argument(
        "--sin-traza",
        action="store_true",
        help="No guardar traza de Playwright (pesa, pero es la red de seguridad)",
    )
    p.add_argument("--verbose", "-v", action="store_true", help="Log en DEBUG")
    return p.parse_args()


def main() -> int:
    args = _argumentos()
    asegurar_directorios()
    archivo_log = registro.configurar(
        logging.DEBUG if args.verbose else logging.INFO, etiqueta="sesion_grabacion"
    )
    cfg = Config.desde_entorno()
    sello = datetime.now().strftime("%Y%m%d_%H%M%S")

    ruta_captura = Path(args.salida) if args.salida else DIR_LOGS / f"captura_{sello}.jsonl"
    ruta_traza = DIR_LOGS / f"traza_sesion_{sello}.zip"
    ruta_codigo = Path(f"isef07_grabado_{sello}.py").resolve()

    with sync_playwright() as pw:
        try:
            # Con ventana siempre: el operador tiene que ver lo que hace.
            context, cerrar = abrir_contexto(pw, cfg, False)
        except ErrorPerfilNavegador as exc:
            log.error("%s", exc)
            return 2

        capturador = Capturador(ruta_captura)
        traza_activa = False
        try:
            # 1. La captura propia se arma ANTES de navegar, para no perderse nada.
            capturador.vigilar_contexto(context)
            if not args.sin_traza:
                context.tracing.start(screenshots=True, snapshots=True, sources=True)
                traza_activa = True

            # 2. Pestana 1: el Sheet del dia.
            pagina_sheet = context.pages[0] if context.pages else context.new_page()
            capturador.vigilar(pagina_sheet)
            pagina_sheet.goto(
                args.sheet_url,
                wait_until="domcontentloaded",
                timeout=cfg.timeout_render_seg * 1000,
            )
            pagina_sheet.wait_for_timeout(5000)
            print(f"Pestana 1 (Sheet): {pagina_sheet.url[:88]}")

            # 3. Pestana 2: SINU -> ISEF07 -> Periodo fijado y verificado.
            pagina_sinu = context.new_page()
            capturador.vigilar(pagina_sinu)
            try:
                abrir_y_acceder(pagina_sinu, cfg)
                entrar_en_modulo(
                    pagina_sinu, cfg, ACTIVIDAD_VINCULACION, "sesion de grabacion"
                )
                pagina_sinu.wait_for_timeout(6000)
                fijar_periodo(pagina_sinu, cfg, args.periodo)
                print(f"Pestana 2 (SINU) : ISEF07, Periodo {periodo_actual(pagina_sinu)}")
            except (ErrorAccesoSinu, ErrorLecturaSinu) as exc:
                # No se aborta: el objetivo de la sesion es precisamente grabar
                # lo que la automatizacion aun no sabe hacer.
                log.warning(
                    "No se pudo dejar todo listo (%s). Se cede el mando igual: "
                    "hay que llegar a ISEF07 y fijar el Periodo '%s' a mano.",
                    exc,
                    args.periodo,
                )

            # OJO: aqui NO se llama a `grabador.activar`. Con el grabador ya
            # encendido (`enableRecorder` en modo 'recording'), `page.pause()`
            # **no bloquea**: vuelve al instante y la sesion termina sin que el
            # operador haya podido hacer nada (comprobado el 01/09/2026). Los dos
            # mecanismos no se combinan, asi que manda el Inspector -- que es el
            # que muestra el codigo en vivo -- y la captura propia hace el resto.
            print()
            print("=" * 72)
            print("ENTORNO LISTO. Se abre el Inspector de Playwright.")
            print("=" * 72)
            print("Las 15 matriculas se hacen normalmente, alternando pestanas.")
            print("Cada clic y cada cambio se anota al instante, con la pestana")
            print("en la que ocurrio, en:")
            print(f"  {ruta_captura}")
            print()
            print("Se registra: fila del estudiante, grilla Grupos, checkboxes y")
            print("sus atributos de estado, 'Accion a realizar' y el boton de")
            print("ejecutar -- que es lo que falta para blindar la etapa 4.")
            print()
            print("AVISO: lo que se pulse en ISEF07 ocurre DE VERDAD. Este script")
            print("solo observa; no hay simulacion que lo frene.")
            print()
            print("En el Inspector: pulsar 'Record' para ver el codigo en vivo.")
            print("La captura propia va sola, con o sin eso.")
            print()
            print("Al terminar las 15, pulsar 'Resume' en el Inspector (o cerrar")
            print("el navegador): entonces se cierran la traza y los archivos.")
            print("=" * 72)
            print()

            # 4. El mando pasa al operador. `pause()` abre el Inspector y NO
            #    vuelve hasta que se pulse 'Resume' o se cierre el navegador.
            pagina_sinu.pause()

            print("Sesion reanudada; se cierran los artefactos.")
        except Exception:
            log.exception("Fallo inesperado en la sesion de grabacion")
        finally:
            if traza_activa:
                try:
                    context.tracing.stop(path=str(ruta_traza))
                    print(f"Traza            : playwright show-trace {ruta_traza}")
                except Exception as exc:  # noqa: BLE001 - el navegador pudo morir
                    log.warning("No se pudo guardar la traza: %s", exc)
            n = capturador.n
            capturador.cerrar()
            cerrar()

            print()
            print(f"Interacciones capturadas: {n}")
            print(f"Captura propia   : {ruta_captura}")
            if ruta_codigo.is_file():
                print(f"Codigo del grabador: {ruta_codigo}")
            else:
                print("Codigo del grabador: no se escribio (para eso esta la captura)")
            print(f"Log de la corrida: {archivo_log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
