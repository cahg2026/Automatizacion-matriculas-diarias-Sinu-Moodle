"""CLI de la etapa 2: sube el reporte validado a Google Drive (RPA).

Sin APIs de Google: usa el mismo perfil de navegador persistente que la etapa 1,
de modo que la sesion de Google ya autenticada alli es la que abre Drive.

Toma un .xlsx, le aplica la Fase 1 (colores + VALIDACION_RPA) y sube el
resultado como Google Sheet con la convencion acordada:

    REPORTES 2026/AGOSTO/REPORTE 21/08/2026 #159

Uso:
    python scripts/subir_reporte.py <ruta.xlsx> [--ya-validado] [--visible]
                                    [--fecha AAAA-MM-DD] [--consecutivo N]
                                    [--traza] [-v]
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path

# permite ejecutar el script sin instalar el paquete
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from moodle_sinu import registro  # noqa: E402
from moodle_sinu.config import DIR_PROCESADO, Config, asegurar_directorios  # noqa: E402
from moodle_sinu.lector_reporte import ErrorEstructuraReporte  # noqa: E402
from moodle_sinu.orden_periodo import bloques_periodo  # noqa: E402
from moodle_sinu.resumen import formatear_resumen  # noqa: E402
from moodle_sinu.salida_excel import escribir_copia_coloreada  # noqa: E402
from moodle_sinu.subidor_drive import ErrorSubidaDrive, subir_reporte  # noqa: E402
from moodle_sinu.validacion import validar_reporte  # noqa: E402

log = logging.getLogger("subir_reporte")


def _argumentos() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Etapa 2: subida del reporte a Google Drive por navegador"
    )
    p.add_argument("reporte", help="Ruta del .xlsx (crudo de Power BI, o ya validado)")
    p.add_argument(
        "--ya-validado",
        action="store_true",
        help="El .xlsx ya trae los colores de la Fase 1; no volver a procesarlo",
    )
    p.add_argument("--fecha", default=None, help="Fecha del reporte en AAAA-MM-DD (por defecto hoy)")
    p.add_argument(
        "--no-matriculado",
        type=int,
        default=None,
        help="Valor de la tarjeta 'NO MATRICULADO' del tablero. Es el numero "
        "que va tras '#' en el nombre. Sin esto se usan las filas del .xlsx, "
        "que cuentan lo mismo.",
    )
    p.add_argument(
        "--consecutivo",
        type=int,
        default=None,
        help="Fuerza el numero del nombre, por encima de todo lo demas.",
    )
    p.add_argument(
        "--visible",
        action="store_true",
        help="Abre el navegador con ventana. Obligatorio la primera vez.",
    )
    p.add_argument(
        "--headless", action="store_true", help="Fuerza el modo sin ventana"
    )
    p.add_argument(
        "--traza",
        action="store_true",
        help="Guarda una traza de Playwright en logs/ (imprescindible mientras "
        "los selectores de Drive no esten verificados)",
    )
    p.add_argument(
        "--sin-abrir",
        action="store_true",
        help="No abrir el Sheet en una pestana al terminar (por defecto se abre: "
        "es lo que da su URL real y lo deja a la vista)",
    )
    p.add_argument("--verbose", "-v", action="store_true", help="Log en DEBUG")
    return p.parse_args()


def _fecha(texto: str | None) -> date:
    if not texto:
        return date.today()
    try:
        return datetime.strptime(texto, "%Y-%m-%d").date()
    except ValueError as exc:
        raise SystemExit(f"--fecha debe ser AAAA-MM-DD, no '{texto}': {exc}")


def _preparar_archivo(entrada: Path, ya_validado: bool) -> Path:
    """Devuelve la ruta del .xlsx coloreado que hay que subir."""
    if ya_validado:
        log.info("Se sube tal cual (--ya-validado): %s", entrada)
        return entrada

    resultado = validar_reporte(entrada)

    sello = datetime.now().strftime("%Y%m%d_%H%M%S")
    destino = DIR_PROCESADO / f"{entrada.stem}_validado_{sello}.xlsx"
    # Colorea y ordena A-Z por COD_PERIODO: lo que sube a Sheets ya va agrupado
    # por periodo, para no cambiar el filtro de ISEF07 linea por linea.
    escribir_copia_coloreada(resultado, destino)
    print(f"Copia coloreada : {destino}")

    bloques = bloques_periodo(resultado)
    print(
        f"Orden por periodo: {len({p for p, _ in bloques})} periodo(s) "
        f"en {len(bloques)} bloque(s) contiguo(s)"
    )
    for periodo, n in bloques:
        print(f"  {periodo:<14} {n} filas")

    # Despues de ordenar, para que los numeros de fila del resumen sean los de
    # la copia que se va a subir.
    print(formatear_resumen(resultado))
    print()
    return destino


def main() -> int:
    args = _argumentos()
    asegurar_directorios()
    archivo_log = registro.configurar(
        logging.DEBUG if args.verbose else logging.INFO, etiqueta="etapa2_drive"
    )

    if args.visible and args.headless:
        log.error("--visible y --headless son incompatibles.")
        return 2

    cfg = Config.desde_entorno()
    headless = False if args.visible else (True if args.headless else None)
    entrada = Path(args.reporte)
    if not entrada.is_file():
        log.error("No existe el archivo: %s", entrada)
        return 2

    try:
        subir = _preparar_archivo(entrada, args.ya_validado)
        resultado = subir_reporte(
            subir,
            cfg=cfg,
            fecha=_fecha(args.fecha),
            no_matriculado=args.no_matriculado,
            consecutivo=args.consecutivo,
            headless=headless,
            con_traza=args.traza,
            abrir_al_terminar=not args.sin_abrir,
        )
    except ErrorEstructuraReporte as exc:
        log.error("Estructura del reporte invalida: %s", exc)
        return 2
    except ErrorSubidaDrive as exc:
        log.error("Subida fallida: %s", exc)
        print(f"\nLog de la corrida: {archivo_log}")
        return 1
    except Exception:
        # Red de seguridad: que ningun fallo se quede solo en la consola.
        log.exception("Fallo inesperado durante la subida")
        print(f"\nLog de la corrida: {archivo_log}")
        return 1

    print(f"Subido          : {resultado.nombre}")
    print(f"Carpeta         : {cfg.google_carpeta_raiz}/{resultado.carpeta_mes}")
    print(f"NO MATRICULADO  : #{resultado.consecutivo}")
    print(f"Convertido a Sheet por menus: {'si' if resultado.convertido_a_sheet else 'no'}")
    print(f"Duracion        : {resultado.segundos}s")
    if resultado.url_sheet:
        print(f"Sheet           : {resultado.url_sheet}")
    for aviso in resultado.advertencias:
        print(f"  ! {aviso}")
    if resultado.traza:
        print(f"Traza           : playwright show-trace {resultado.traza}")
    print(f"Log de la corrida: {archivo_log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
