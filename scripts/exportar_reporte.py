"""CLI de la etapa 1: exporta el reporte Moodle vs SINU desde Power BI.

Solo descarga: no valida el archivo ni toca SINU ni Google. El .xlsx resultante
es la entrada de `scripts/validar_reporte.py`.

Uso:
    python scripts/exportar_reporte.py [--salida ruta.xlsx] [--visible]
                                       [--traza] [-v]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# permite ejecutar el script sin instalar el paquete
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from moodle_sinu import registro  # noqa: E402
from moodle_sinu.config import Config, asegurar_directorios  # noqa: E402
from moodle_sinu.exportador_powerbi import (  # noqa: E402
    ErrorExportacionPowerBI,
    exportar_reporte,
)

log = logging.getLogger("exportar_reporte")


def _argumentos() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Etapa 1: exportacion desde Power BI")
    p.add_argument("--salida", default=None, help="Ruta del .xlsx (por defecto data/raw/ con sello)")
    p.add_argument(
        "--visible",
        action="store_true",
        help="Abre el navegador con ventana. Obligatorio la primera vez si la cuenta exige MFA.",
    )
    p.add_argument(
        "--headless",
        action="store_true",
        help="Fuerza el modo sin ventana por encima de POWERBI_HEADLESS",
    )
    p.add_argument(
        "--traza",
        action="store_true",
        help="Guarda una traza de Playwright en logs/ para depurar selectores",
    )
    p.add_argument(
        "--captura",
        action="store_true",
        help="Guarda en logs/ una imagen del dialogo antes de confirmar la exportacion",
    )
    p.add_argument("--verbose", "-v", action="store_true", help="Log en DEBUG")
    return p.parse_args()


def main() -> int:
    args = _argumentos()
    asegurar_directorios()
    archivo_log = registro.configurar(
        logging.DEBUG if args.verbose else logging.INFO, etiqueta="etapa1_powerbi"
    )

    if args.visible and args.headless:
        log.error("--visible y --headless son incompatibles.")
        return 2

    headless = False if args.visible else (True if args.headless else None)

    try:
        resultado = exportar_reporte(
            Config.desde_entorno(),
            destino=Path(args.salida) if args.salida else None,
            headless=headless,
            con_traza=args.traza,
            con_captura=args.captura,
        )
    except ErrorExportacionPowerBI as exc:
        log.error("Exportacion fallida: %s", exc)
        print(f"Log de la corrida: {archivo_log}")
        return 1
    except Exception:
        # Red de seguridad: un fallo inesperado tiene que quedar en el log de la
        # corrida con su traza, no solo como traceback en la consola.
        log.exception("Fallo inesperado durante la exportacion")
        print(f"Log de la corrida: {archivo_log}")
        return 1

    print(f"Reporte descargado : {resultado.archivo}")
    print(f"Tamano             : {resultado.bytes / 1024:.1f} KiB")
    print(f"Nombre en Power BI : {resultado.nombre_sugerido}")
    print(f"Navegacion         : {resultado.ruta_navegacion}")
    print(f"NO MATRICULADO     : {resultado.no_matriculado if resultado.no_matriculado is not None else '(no leido)'}")
    print(f"Filas de datos     : {resultado.filas_datos}")
    print(f"Duracion           : {resultado.segundos}s")

    for aviso in resultado.advertencias:
        print(f"  ! {aviso}")
    if resultado.captura_dialogo:
        print(f"Captura del dialogo: {resultado.captura_dialogo}")
    if resultado.traza:
        print(f"Traza              : playwright show-trace {resultado.traza}")

    print(f"Log de la corrida  : {archivo_log}")
    print()
    print("Siguiente paso:")
    print(f"  python scripts/validar_reporte.py {resultado.archivo}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
