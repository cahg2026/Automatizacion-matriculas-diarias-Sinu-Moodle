"""CLI de la etapa 3: clasifica los casos leyendo ISEF07. SOLO LECTURA.

No escribe nada en el sistema academico. No toca el desplegable "Accion a
realizar" ni el icono de ejecutar: la vinculacion es la etapa 4, que esta
bloqueada por MODO_SIMULACION hasta que esta clasificacion se valide contra
revision manual.

Se trabaja **un periodo por corrida**, porque el filtro de Periodo de ISEF07 se
fija una sola vez por sesion. Ver el reparto con:

    python scripts/plan_vinculacion.py <reporte.xlsx>

La referencia del proceso da por hecho que el operador ya tiene ISEF07 abierto.
Este script no inventa el login ni la navegacion por menus: comprueba que las
grillas esten ahi y, si no, lo dice.

Uso:
    python scripts/clasificar_sinu.py <reporte.xlsx> --periodo 26V05
                                      [--limite N] [--visible] [--traza] [-v]
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
from moodle_sinu.clasificador_sinu import (  # noqa: E402
    aplicar_a_filas,
    clasificar_estudiante,
    marcar_pendiente_revisar,
)
from moodle_sinu.config import (  # noqa: E402
    DIR_LOGS,
    DIR_PROCESADO,
    Config,
    asegurar_directorios,
)
from moodle_sinu.lector_reporte import ErrorEstructuraReporte  # noqa: E402
from moodle_sinu.constantes_sinu import ACTIVIDAD_VINCULACION  # noqa: E402
from moodle_sinu.lector_sinu import (  # noqa: E402
    ErrorLecturaSinu,
    EstudianteAmbiguo,
    entrar_en_modulo,
    fijar_periodo,
    leer_estudiante,
)
from moodle_sinu.navegador import abrir_contexto  # noqa: E402
from moodle_sinu.plan_vinculacion import construir_plan, estimar_duracion  # noqa: E402
from moodle_sinu.restricciones_sinu import resumen_permisos  # noqa: E402
from moodle_sinu.salida_excel import escribir_copia_coloreada  # noqa: E402
from moodle_sinu.validacion import validar_reporte  # noqa: E402

log = logging.getLogger("clasificar_sinu")


def _argumentos() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Etapa 3: clasificacion de casos en ISEF07 (solo lectura)"
    )
    p.add_argument("reporte", help="Ruta del .xlsx del reporte")
    p.add_argument(
        "--periodo",
        required=False,
        default=None,
        help="COD_PERIODO del lote a trabajar. Obligatorio: el filtro de "
        "Periodo se fija una vez por sesion.",
    )
    p.add_argument(
        "--limite",
        type=int,
        default=None,
        help="Procesar solo los primeros N estudiantes (para la primera prueba)",
    )
    p.add_argument("--salida", default=None, help="Ruta del .xlsx clasificado")
    p.add_argument("--visible", action="store_true", help="Navegador con ventana")
    p.add_argument("--headless", action="store_true", help="Fuerza modo sin ventana")
    p.add_argument("--traza", action="store_true", help="Traza de Playwright en logs/")
    p.add_argument("--verbose", "-v", action="store_true", help="Log en DEBUG")
    return p.parse_args()


def main() -> int:
    args = _argumentos()
    asegurar_directorios()
    archivo_log = registro.configurar(
        logging.DEBUG if args.verbose else logging.INFO, etiqueta="etapa3_sinu"
    )
    if args.visible and args.headless:
        log.error("--visible y --headless son incompatibles.")
        return 2

    cfg = Config.desde_entorno()
    entrada = Path(args.reporte)

    try:
        resultado = validar_reporte(entrada)
    except (ErrorEstructuraReporte, FileNotFoundError) as exc:
        log.error("%s", exc)
        return 2

    plan = construir_plan(resultado)
    if args.periodo is None:
        lotes_a_procesar = plan.lotes
    else:
        lotes_a_procesar = [l for l in plan.lotes if l.cod_periodo == args.periodo]

    if not lotes_a_procesar:
        if args.periodo:
            log.error("No hay operaciones para el periodo '%s'. Periodos disponibles: %s", args.periodo, [l.cod_periodo for l in plan.lotes])
        else:
            log.error("No hay operaciones disponibles en el reporte para ningun periodo.")
        return 1

    for lote_actual in lotes_a_procesar:
        lote = lote_actual
        p_actual = lote_actual.cod_periodo
        log.info("Procesando bloque del periodo: %s (%d estudiantes)", p_actual, lote_actual.n_filas)

        operaciones = lote.operaciones[: args.limite] if args.limite else lote.operaciones
        minimo, maximo = estimar_duracion(len(operaciones))

        print(f"Periodo           : {lote.cod_periodo}")
        print(f"Estudiantes       : {len(operaciones)} de {lote.n_estudiantes}")
        print(f"Filas a clasificar: {sum(len(o.filas) for o in operaciones)}")
        print(f"Estimado          : entre {minimo // 60}m y {maximo // 60}m")
        print("Modo              : SOLO LECTURA (no se ejecuta ninguna vinculacion)")
        print()
        log.info("%s", resumen_permisos())
        print(resumen_permisos())
        print()

        por_fila = {f.fila: f for f in resultado.filas}
        headless = False if args.visible else (True if args.headless else None)
        sin_cabeza = cfg.powerbi_headless if headless is None else headless
        sello = datetime.now().strftime("%Y%m%d_%H%M%S")

        leidos = 0
        pendientes_verificar: dict[str, list[str]] = {}
        detenidos: list[tuple[str, str]] = []
        conteo: dict[str, int] = {}

        with sync_playwright() as pw:
            context, cerrar = abrir_contexto(pw, cfg, sin_cabeza)

            # 1. Pestaña principal para SINU
            page = context.pages[0] if context.pages else context.new_page()

            # 2. Pestaña secundaria para Google Sheets si existe la URL
            url_sheets = getattr(cfg, "drive_reporte_url", None) or getattr(cfg, "url_drive", None)
            if url_sheets:
                page_sheets = context.new_page()
                page_sheets.goto(url_sheets)
                log.info("Google Sheets abierto dinamicamente: %s", url_sheets)

            ruta_traza = None
            if args.traza:
                DIR_LOGS.mkdir(parents=True, exist_ok=True)
                ruta_traza = DIR_LOGS / f"traza_sinu_{sello}.zip"
                context.tracing.start(screenshots=True, snapshots=True, sources=True)

            try:
                if abrir_y_acceder(page, cfg):
                    log.info("Se inicio sesion en SINU para esta corrida.")
                # Desde #home hay que abrir el modulo: sin esto, el filtro de
                # Periodo que viene despues busca un campo que no esta en pantalla.
                entrar_en_modulo(
                    page, cfg, ACTIVIDAD_VINCULACION, "clasificar estudiantes"
                )
            except (ErrorAccesoSinu, ErrorLecturaSinu) as exc:
                log.error("%s", exc)
                return 1

            try:
                # El filtro de Periodo: UNA sola vez para todo el lote.
                fijar_periodo(page, cfg, lote.cod_periodo)

                for i, operacion in enumerate(operaciones, 1):
                    print(f"[{i}/{len(operaciones)}] {operacion.identificacion}", flush=True)
                    filas_op = [por_fila[n] for n in operacion.filas if n in por_fila]
                    try:
                        lectura = leer_estudiante(page, cfg, operacion.identificacion)
                    except EstudianteAmbiguo as exc:
                        detenidos.append((operacion.identificacion, str(exc)))
                        for fila in filas_op:
                            marcar_pendiente_revisar(fila, str(exc))
                        continue
                    except ErrorLecturaSinu as exc:
                        detenidos.append((operacion.identificacion, str(exc)))
                        for fila in filas_op:
                            marcar_pendiente_revisar(fila, str(exc))
                        continue

                    clasificacion = clasificar_estudiante(
                        filas_op,
                        lectura.grupos,
                        identificacion=operacion.identificacion,
                        cod_periodo=lote.cod_periodo,
                    )
                    aplicar_a_filas(filas_op, clasificacion)
                    leidos += 1

                    for fila in filas_op:
                        etiqueta = (
                            fila.validacion_rpa.value if fila.validacion_rpa else "sin clasificar"
                        )
                        conteo[etiqueta] = conteo.get(etiqueta, 0) + 1

                    for fila in filas_op:
                        c = clasificacion.clasificaciones.get(fila.fila)
                        if c and c.modulos_a_verificar:
                            pendientes_verificar.setdefault(
                                ", ".join(c.modulos_a_verificar), []
                            ).append(f"fila {fila.fila} ({fila.shortname})")

                    for aviso in clasificacion.advertencias:
                        log.warning("%s", aviso)
                    for crudo in lectura.ilegibles:
                        log.warning(
                            "%s: fila con checks ilegibles, no clasificada: %s",
                            operacion.identificacion,
                            crudo[:100],
                        )
            except Exception:
                log.exception("Fallo inesperado durante la clasificacion")
                return 1
            finally:
                if ruta_traza is not None:
                    context.tracing.stop(path=str(ruta_traza))
                    log.info("Traza: playwright show-trace %s", ruta_traza)
                cerrar()

        destino = (
            Path(args.salida)
            if args.salida
            else DIR_PROCESADO / f"{entrada.stem}_clasificado_{lote.cod_periodo}_{sello}.xlsx"
        )
        escribir_copia_coloreada(resultado, destino)

        print()
        print(f"Estudiantes leidos : {leidos}/{len(operaciones)}")
        for etiqueta, n in sorted(conteo.items(), key=lambda kv: -kv[1]):
            print(f"  {etiqueta:<34} {n}")
        if pendientes_verificar:
            print()
            print("Confirmacion pendiente en modulos de SOLO LECTURA:")
            for modulos, filas_afectadas in sorted(pendientes_verificar.items()):
                print(f"  consultar {modulos}: {len(filas_afectadas)} filas")
            print("  (la navegacion a esos modulos esta pendiente de grabacion;")
            print("   por ahora es una confirmacion manual)")

        if detenidos:
            print()
            print(f"Detenidos ({len(detenidos)}) — quedan PENDIENTE POR REVISAR:")
            for cedula, motivo in detenidos[:10]:
                print(f"  {cedula}: {motivo[:100]}")
        print()
        print(f"Reporte clasificado: {destino}")
        print(f"Log de la corrida  : {archivo_log}")
        print()
        print("La etapa 4 (ejecutar la vinculacion) sigue bloqueada por")
        print(f"MODO_SIMULACION={str(cfg.modo_simulacion).lower()}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())