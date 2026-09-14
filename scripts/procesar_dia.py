"""Recorre TODOS los periodos del dia llamando a la etapa 4 en cada uno.

Por que existe: `ejecutar_sinu.py` trabaja UN periodo por corrida, porque el
filtro de Periodo de ISEF07 se fija una vez por sesion. Con 12 periodos en el
lote de hoy eso son 12 invocaciones, y hacerlas a mano invita a saltarse una.

Orden A-Z de COD_PERIODO, el mismo en el que quedo ordenado el Sheet: asi lo que
el operador ve en la hoja y lo que el robot recorre coinciden.

Lo que NO hace, a proposito
---------------------------
No relaja ningun cerrojo. Cada periodo pasa por `ejecutar_sinu.py` con sus tres
condiciones (MODO_SIMULACION, --ejecutar-de-verdad, --periodo) y su exigencia de
--sheet-url. Este script solo evita repetir el comando doce veces.

Las filas que la Fase 1 marco en NARANJA (campo obligatorio vacio) no se
procesan: no entran en el plan, asi que tampoco llegan aqui.

Uso:
    python scripts/procesar_dia.py <reporte.xlsx> --sheet-url URL
                                   [--ejecutar-de-verdad] [--desde PERIODO]
                                   [--solo PERIODO ...] [--traza] [-v]
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from moodle_sinu import registro  # noqa: E402
from moodle_sinu.config import asegurar_directorios  # noqa: E402
from moodle_sinu.lector_reporte import ErrorEstructuraReporte  # noqa: E402
from moodle_sinu.plan_vinculacion import construir_plan  # noqa: E402
from moodle_sinu.validacion import validar_reporte  # noqa: E402

log = logging.getLogger("procesar_dia")

CLI_ETAPA4 = RAIZ / "scripts" / "ejecutar_sinu.py"


def _argumentos() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Procesa todos los periodos del dia")
    p.add_argument("reporte", help="Ruta del .xlsx del reporte")
    p.add_argument("--sheet-url", required=True, help="URL del Google Sheet del dia")
    p.add_argument(
        "--ejecutar-de-verdad",
        action="store_true",
        help="Se pasa tal cual a la etapa 4. Sin esto, todo va en simulacion.",
    )
    p.add_argument(
        "--desde",
        default=None,
        metavar="PERIODO",
        help="Empieza en este periodo y sigue con los siguientes (A-Z). Sirve "
        "para reanudar una corrida interrumpida sin repetir lo ya hecho.",
    )
    p.add_argument(
        "--solo",
        action="append",
        default=None,
        metavar="PERIODO",
        help="Procesa unicamente estos periodos (se puede repetir).",
    )
    p.add_argument(
        "--saltar",
        action="append",
        default=None,
        metavar="PERIODO",
        help="Omite estos periodos (se puede repetir). Util para los ya hechos.",
    )
    p.add_argument(
        "--saltar-hechas",
        action="store_true",
        help="Se pasa tal cual a la etapa 4: omite lo que el diario ya tiene en "
        "verde. Recomendado al reanudar una corrida interrumpida.",
    )
    p.add_argument("--traza", action="store_true", help="Traza por periodo")
    p.add_argument("--verbose", "-v", action="store_true", help="Log en DEBUG")
    return p.parse_args()


def main() -> int:
    args = _argumentos()
    asegurar_directorios()
    archivo_log = registro.configurar(
        logging.DEBUG if args.verbose else logging.INFO, etiqueta="procesar_dia"
    )

    entrada = Path(args.reporte)
    try:
        resultado = validar_reporte(entrada)
    except (ErrorEstructuraReporte, FileNotFoundError) as exc:
        log.error("%s", exc)
        return 2

    plan = construir_plan(resultado)
    periodos = [l.cod_periodo for l in plan.lotes]  # ya vienen A-Z

    if args.solo:
        pedidos = {s.strip().upper() for s in args.solo}
        periodos = [p for p in periodos if p.upper() in pedidos]
    if args.saltar:
        fuera = {s.strip().upper() for s in args.saltar}
        periodos = [p for p in periodos if p.upper() not in fuera]
    if args.desde:
        desde = args.desde.strip().upper()
        indice = next((i for i, p in enumerate(periodos) if p.upper() == desde), None)
        if indice is None:
            log.error(
                "'%s' no esta entre los periodos a procesar: %s",
                args.desde,
                ", ".join(periodos),
            )
            return 2
        periodos = periodos[indice:]

    if not periodos:
        log.error("No queda ningun periodo por procesar con esos filtros.")
        return 2

    por_periodo = {l.cod_periodo: l.n_estudiantes for l in plan.lotes}
    total = sum(por_periodo[p] for p in periodos)

    print("=" * 70)
    print("PROCESO DEL DIA - {0}".format(datetime.now().strftime("%d/%m/%Y %H:%M")))
    print("=" * 70)
    print("Modo      : {0}".format(
        "EJECUCION REAL" if args.ejecutar_de_verdad else "SIMULACION"))
    print("Periodos  : {0}".format(len(periodos)))
    print("Operaciones: {0}".format(total))
    print()
    for p in periodos:
        print("   {0:<8} {1} estudiantes".format(p, por_periodo[p]))
    print()
    print("Las filas naranjas (campo obligatorio vacio) no entran: de {0} filas "
          "del reporte solo {1} son procesables.".format(
              resultado.total_filas, len(resultado.procesables)))
    print("=" * 70)
    print()

    inicio = time.monotonic()
    resumen: list[tuple[str, int]] = []

    for i, periodo in enumerate(periodos, 1):
        print()
        print("### [{0}/{1}] PERIODO {2} ({3} estudiantes) ###".format(
            i, len(periodos), periodo, por_periodo[periodo]))
        orden = [
            sys.executable,
            str(CLI_ETAPA4),
            str(entrada),
            "--periodo", periodo,
            "--sheet-url", args.sheet_url,
        ]
        if args.ejecutar_de_verdad:
            orden.append("--ejecutar-de-verdad")
        if args.saltar_hechas:
            orden.append("--saltar-hechas")
        if args.traza:
            orden.append("--traza")
        if args.verbose:
            orden.append("-v")

        log.info("Lanzando la etapa 4 para %s", periodo)
        proceso = subprocess.run(orden, cwd=str(RAIZ))
        resumen.append((periodo, proceso.returncode))
        if proceso.returncode != 0:
            # No se aborta el dia entero por un periodo: los demas son
            # independientes y detenerlos dejaria trabajo sin hacer sin motivo.
            # Queda en el resumen final para revisarlo.
            log.error(
                "El periodo %s termino con codigo %d. Se continua con el "
                "siguiente; queda anotado en el resumen.",
                periodo,
                proceso.returncode,
            )

    minutos = (time.monotonic() - inicio) / 60
    print()
    print("=" * 70)
    print("RESUMEN DEL DIA  ({0:.0f} minutos)".format(minutos))
    print("=" * 70)
    for periodo, codigo in resumen:
        print("   {0:<8} {1}".format(periodo, "OK" if codigo == 0 else f"FALLO ({codigo})"))
    fallidos = [p for p, c in resumen if c != 0]
    print()
    if fallidos:
        print("Periodos con fallo: {0}".format(", ".join(fallidos)))
        print("Se pueden reintentar con --solo, sin repetir los demas.")
    else:
        print("Todos los periodos terminaron sin error.")
    print()
    print("IMPORTANTE: revisar los reciclados sin cerrar en "
          "logs/ciclos_abiertos.jsonl antes de dar el dia por bueno.")
    print("Log de la corrida: {0}".format(archivo_log))
    return 1 if fallidos else 0


if __name__ == "__main__":
    raise SystemExit(main())
