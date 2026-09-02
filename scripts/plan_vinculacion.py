"""Muestra el plan de trabajo en SINU derivado de un reporte.

No toca SINU: solo traduce el reporte en la lista de operaciones de ISEF07,
agrupadas por periodo. Es el paso previo obligado antes de la etapa 3/4, y
cumple la convencion de la skill de negocio: antes de lanzar un lote largo, dar
el numero de registros y el tiempo estimado.

Sustituye a `scripts/extract_cedulas.py` de la skill: hace lo mismo (cedulas
unicas en orden de aparicion) pero sobre el reporte ya parseado, de modo que la
fila de pie 'Filtros aplicados:' no se cuela como una cedula.

Uso:
    python scripts/plan_vinculacion.py <ruta.xlsx> [--hoja Export]
                                       [--periodo 26V05] [--cedulas]
                                       [--csv ruta.csv] [-v]
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from pathlib import Path

# permite ejecutar el script sin instalar el paquete
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from moodle_sinu import registro  # noqa: E402
from moodle_sinu.config import asegurar_directorios  # noqa: E402
from moodle_sinu.lector_reporte import ErrorEstructuraReporte  # noqa: E402
from moodle_sinu.plan_vinculacion import (  # noqa: E402
    construir_plan,
    estimar_duracion,
    formatear_plan,
)
from moodle_sinu.validacion import validar_reporte  # noqa: E402

log = logging.getLogger("plan_vinculacion")


def _argumentos() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Plan de vinculacion en SINU (ISEF07)")
    p.add_argument("reporte", help="Ruta del .xlsx del reporte")
    p.add_argument("--hoja", default=None, help="Nombre de la hoja (por defecto, la primera)")
    p.add_argument(
        "--periodo",
        default=None,
        help="Mostrar solo este COD_PERIODO (el lote que se va a trabajar)",
    )
    p.add_argument(
        "--cedulas",
        action="store_true",
        help="Imprimir solo las cedulas, una por linea, sin el resumen "
        "(equivalente a extract_cedulas.py de la skill)",
    )
    p.add_argument("--csv", default=None, help="Volcar el plan completo a un CSV")
    p.add_argument("--verbose", "-v", action="store_true", help="Log en DEBUG")
    return p.parse_args()


def _volcar_csv(plan, ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(
            ["ORDEN", "COD_PERIODO", "IDENTIFICACION", "NOMBRE_COMPLETO",
             "N_MATERIAS", "MATERIAS", "FILAS_REPORTE"]
        )
        orden = 0
        for lote in plan.lotes:
            for op in lote.operaciones:
                orden += 1
                w.writerow([
                    orden,
                    op.cod_periodo,
                    op.identificacion,
                    op.nombre,
                    op.n_materias,
                    "|".join(op.materias),
                    "|".join(str(f) for f in op.filas),
                ])


def main() -> int:
    args = _argumentos()
    asegurar_directorios()
    if not args.cedulas:
        registro.configurar(
            logging.DEBUG if args.verbose else logging.WARNING, etiqueta="plan_sinu"
        )

    try:
        resultado = validar_reporte(Path(args.reporte), hoja=args.hoja)
    except (ErrorEstructuraReporte, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    plan = construir_plan(resultado)

    if args.periodo:
        plan.lotes = [l for l in plan.lotes if l.cod_periodo == args.periodo]
        if not plan.lotes:
            print(f"ERROR: no hay operaciones para el periodo '{args.periodo}'.",
                  file=sys.stderr)
            return 2

    if args.cedulas:
        # Salida estilo extract_cedulas.py: apta para canalizar.
        for lote in plan.lotes:
            for cedula in lote.cedulas:
                print(cedula)
        minimo, maximo = estimar_duracion(plan.n_operaciones)
        print(
            f"# operaciones: {plan.n_operaciones} | periodos: {plan.n_periodos} "
            f"| estimado: {minimo}-{maximo}s",
            file=sys.stderr,
        )
        return 0

    print(formatear_plan(plan))

    if args.csv:
        ruta = Path(args.csv)
        _volcar_csv(plan, ruta)
        print(f"\nPlan completo en: {ruta}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
