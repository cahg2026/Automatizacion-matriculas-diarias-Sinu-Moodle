"""CLI de la Fase 1: valida un reporte .xlsx exportado de Power BI.

No toca SINU, ni Google, ni la red. Solo lee el archivo, aplica las tres
reglas de calidad y deja evidencia.

Uso:
    python scripts/validar_reporte.py <ruta.xlsx> [--salida ruta.xlsx]
                                      [--hoja Export] [--sin-color] [--sin-ordenar]
                                      [--no-deduplicar-exactos] [--csv-omitidas ruta.csv]
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from datetime import datetime
from pathlib import Path

# permite ejecutar el script sin instalar el paquete
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from moodle_sinu import registro  # noqa: E402
from moodle_sinu.config import DIR_PROCESADO, asegurar_directorios  # noqa: E402
from moodle_sinu.lector_reporte import ErrorEstructuraReporte  # noqa: E402
from moodle_sinu.orden_periodo import bloques_periodo  # noqa: E402
from moodle_sinu.resumen import formatear_resumen  # noqa: E402
from moodle_sinu.salida_excel import escribir_copia_coloreada  # noqa: E402
from moodle_sinu.validacion import validar_reporte  # noqa: E402

log = logging.getLogger("validar_reporte")


def _argumentos() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fase 1: validacion del reporte Moodle vs SINU")
    p.add_argument("reporte", help="Ruta del .xlsx exportado de Power BI")
    p.add_argument("--hoja", default=None, help="Nombre de la hoja (por defecto, la primera)")
    p.add_argument("--salida", default=None, help="Ruta del .xlsx coloreado de salida")
    p.add_argument("--sin-color", action="store_true", help="No generar el .xlsx coloreado")
    p.add_argument(
        "--sin-ordenar",
        action="store_true",
        help="No ordenar A-Z por COD_PERIODO; deja el orden original de Power BI. "
        "Por defecto se ordena, para que los periodos salgan en bloques continuos.",
    )
    p.add_argument(
        "--no-deduplicar-exactos",
        action="store_true",
        help="Procesar todas las apariciones de un duplicado exacto en vez de solo la primera",
    )
    p.add_argument("--csv-omitidas", default=None, help="Volcar las filas omitidas a un CSV")
    p.add_argument("--verbose", "-v", action="store_true", help="Log en DEBUG")
    return p.parse_args()


def _volcar_omitidas(resultado, ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["FILA", "IDENTIFICACION", "COD_MATERIA", "COD_PERIODO", "MOTIVO"])
        for f in resultado.omitidas:
            w.writerow([f.fila, f.identificacion, f.cod_materia, f.cod_periodo, f.motivo_omision])


def main() -> int:
    args = _argumentos()
    asegurar_directorios()
    archivo_log = registro.configurar(
        logging.DEBUG if args.verbose else logging.INFO, etiqueta="fase1"
    )

    entrada = Path(args.reporte)
    try:
        resultado = validar_reporte(
            entrada,
            hoja=args.hoja,
            deduplicar_exactos=not args.no_deduplicar_exactos,
        )
    except ErrorEstructuraReporte as exc:
        log.error("Estructura del reporte invalida: %s", exc)
        return 2
    except FileNotFoundError as exc:
        log.error("%s", exc)
        return 2

    # El resumen se imprime DESPUES de escribir la copia: si se ordeno, los
    # numeros de fila que cita son ya los del archivo generado, no los del
    # original. Citar unos numeros que no se pueden buscar en ningun archivo
    # seria peor que imprimirlos mas tarde.
    if not args.sin_color:
        if args.salida:
            destino = Path(args.salida)
        else:
            sello = datetime.now().strftime("%Y%m%d_%H%M%S")
            destino = DIR_PROCESADO / f"{entrada.stem}_validado_{sello}.xlsx"
        escribir_copia_coloreada(
            resultado, destino, ordenar_periodo=not args.sin_ordenar
        )
        print(f"Copia coloreada : {destino}")
        if not args.sin_ordenar:
            bloques = bloques_periodo(resultado)
            print(
                f"Orden A-Z por COD_PERIODO: {len({p for p, _ in bloques})} periodo(s) "
                f"en {len(bloques)} bloque(s) contiguo(s)"
            )
            for periodo, n in bloques:
                print(f"  {periodo:<14} {n} filas")

    print(formatear_resumen(resultado))

    if args.csv_omitidas:
        ruta_csv = Path(args.csv_omitidas)
        _volcar_omitidas(resultado, ruta_csv)
        print(f"CSV de omitidas : {ruta_csv}")

    print(f"Log de la corrida: {archivo_log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
