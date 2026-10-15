"""Tabla dinamica del reporte por shortname. NO toca SINU ni el navegador.

Responde, antes de empezar el dia, a la pregunta que decide cuanto va a durar:
**cuantos grupos distintos hay y cuales arrastran a decenas de estudiantes.**

Medido sobre el reporte del 25/09/2026: 596 filas procesables son 120 grupos,
y SEIS de ellos son 429 filas -- el 72% del reporte. Tener curso en MOODLE es
propiedad del grupo, no del estudiante, asi que esos seis son seis preguntas a
ISEF05, no 429 pasadas por ISEF07.

Se lee solo: valida el reporte, construye el plan y cuenta. Por eso se puede
correr cuando se quiera, incluso con una corrida en marcha.

Uso:
    python scripts/tabla_grupos.py                        # el .xlsx mas nuevo
    python scripts/tabla_grupos.py <reporte.xlsx>
    python scripts/tabla_grupos.py --umbral 30
    python scripts/tabla_grupos.py --csv data/processed/grupos.csv
    python scripts/tabla_grupos.py --excluir              # solo los --excluir-grupo
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from moodle_sinu import tabla_grupos  # noqa: E402
from moodle_sinu.config import DIR_CRUDO  # noqa: E402
from moodle_sinu.lector_reporte import ErrorEstructuraReporte  # noqa: E402
from moodle_sinu.plan_vinculacion import construir_plan  # noqa: E402
from moodle_sinu.validacion import validar_reporte  # noqa: E402


def mas_reciente(carpeta: Path, patron: str = "*.xlsx") -> Path | None:
    """El .xlsx mas nuevo de la carpeta. Por fecha de modificacion, como en
    `dia_completo.py`: el formato de los logs cambia, la fecha del archivo no."""
    if not carpeta.is_dir():
        return None
    candidatos = sorted(
        carpeta.glob(patron), key=lambda p: p.stat().st_mtime, reverse=True
    )
    return candidatos[0] if candidatos else None


def _argumentos() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Tabla dinamica del reporte por COD_MATERIA/NUM_GRUPO"
    )
    p.add_argument(
        "reporte",
        nargs="?",
        default=None,
        help="Ruta del .xlsx. Si se omite, el mas reciente de data/raw.",
    )
    p.add_argument(
        "--umbral",
        type=int,
        default=tabla_grupos.UMBRAL_VERIFICACION,
        metavar="N",
        help=f"Filas a partir de las cuales un grupo se verifica ANTES de "
        f"procesar (por defecto {tabla_grupos.UMBRAL_VERIFICACION}).",
    )
    p.add_argument(
        "--tope",
        type=int,
        default=15,
        metavar="N",
        help="Cuantos grupos se listan en la tabla (por defecto 15).",
    )
    p.add_argument(
        "--csv",
        default="",
        metavar="RUTA",
        help="Escribe la tabla COMPLETA en CSV, para pegarla en el Sheet.",
    )
    p.add_argument(
        "--excluir",
        action="store_true",
        help="Imprime solo la lista de --excluir-grupo para ejecutar_sinu.py, "
        "sin la tabla. Para encadenarlo en un comando.",
    )
    return p.parse_args()


def main() -> int:
    args = _argumentos()

    entrada = Path(args.reporte) if args.reporte else mas_reciente(DIR_CRUDO)
    if entrada is None:
        print(f"ERROR: no hay ningun .xlsx en {DIR_CRUDO}.")
        return 2

    try:
        resultado = validar_reporte(entrada)
    except (ErrorEstructuraReporte, FileNotFoundError) as exc:
        print(f"ERROR: {exc}")
        return 2

    plan = construir_plan(resultado)
    operaciones = [op for lote in plan.lotes for op in lote.operaciones]
    # Las de `sin_periodo` entran tambien: tienen shortname y cuentan para el
    # tamano del grupo, aunque no sean ejecutables sin arreglar el periodo.
    operaciones += list(plan.sin_periodo)

    tabla = tabla_grupos.construir(operaciones)

    if args.excluir:
        # Solo la lista, para componer el comando sin copiar a mano.
        for g in tabla.a_verificar(args.umbral):
            print(f"--excluir-grupo {g.shortname}", end=" ")
        print()
        return 0

    print("=" * 74)
    print(f"TABLA DE GRUPOS - {entrada.name}")
    print("=" * 74)
    print(
        f"Reporte: {resultado.total_filas} filas, "
        f"{len(resultado.procesables)} procesables, "
        f"{plan.n_periodos} periodo(s)."
    )
    print()
    print(tabla_grupos.formatear(tabla, umbral=args.umbral, tope=args.tope))
    print()
    print("=" * 74)
    print("Verificar un grupo en ISEF05 cuesta ~40 s y responde por TODAS sus")
    print("filas: si no tiene curso en MOODLE, ninguna se puede vincular.")
    print("La cola de grupos de 1 fila NO compensa verificarla: preguntar cuesta")
    print("mas que procesarla y enterarse sobre la marcha.")

    if args.csv:
        destino = Path(args.csv)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(tabla_grupos.a_csv(tabla), encoding="utf-8")
        print()
        print(f"CSV completo ({tabla.n_grupos} grupos): {destino}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
