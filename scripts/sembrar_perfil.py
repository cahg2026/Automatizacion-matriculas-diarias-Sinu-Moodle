"""Copia el perfil personal de Chrome al perfil de trabajo de la automatizacion.

Se ejecuta con CHROME CERRADO, y no a diario: solo la primera vez y cuando haya
que refrescar favoritos o sesiones.

Por que existe: Chrome 136+ se niega a que se automatice su directorio de datos
por defecto ("DevTools remote debugging requires a non-default data directory"),
asi que el perfil personal no se puede abrir tal cual. Una copia en otra carpeta
si, y lleva dentro los favoritos, las contrasenas y las cookies. Ver
`siembra_perfil` para el detalle.

Despues de sembrar, las corridas diarias ya NO necesitan Chrome cerrado: el
robot trabaja sobre su copia.

Uso:
    python scripts/sembrar_perfil.py [--rehacer] [--destino RUTA] [-v]
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
from moodle_sinu.perfil_navegador import (  # noqa: E402
    chrome_esta_corriendo,
    perfil_chrome_real,
)
from moodle_sinu.siembra_perfil import ErrorSiembraPerfil, sembrar  # noqa: E402

log = logging.getLogger("sembrar_perfil")


def _argumentos() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Copia el perfil personal de Chrome al perfil de trabajo"
    )
    p.add_argument(
        "--destino",
        default=None,
        help="Carpeta de trabajo (por defecto, POWERBI_PERFIL_NAVEGADOR)",
    )
    p.add_argument(
        "--rehacer",
        action="store_true",
        help="Borra la copia anterior antes de copiar. Sin esto se copia "
        "encima, que es lo que interesa para refrescar sesiones.",
    )
    p.add_argument(
        "--forzar",
        action="store_true",
        help="Sembrar aunque Chrome este abierto. NO recomendado: los archivos "
        "bloqueados -- cookies y contrasenas entre ellos -- se quedarian fuera.",
    )
    p.add_argument("--verbose", "-v", action="store_true", help="Log en DEBUG")
    return p.parse_args()


def main() -> int:
    args = _argumentos()
    asegurar_directorios()
    registro.configurar(
        logging.DEBUG if args.verbose else logging.INFO, etiqueta="sembrar_perfil"
    )
    cfg = Config.desde_entorno()

    destino = Path(args.destino) if args.destino else cfg.powerbi_perfil_navegador
    if not destino:
        log.error(
            "No hay destino: pasar --destino o rellenar POWERBI_PERFIL_NAVEGADOR "
            "en config/.env."
        )
        return 2

    origen = perfil_chrome_real()
    print(f"Origen  : {origen} [{cfg.navegador_perfil_directorio}]")
    print(f"Destino : {destino}")
    print()

    # Antes esto abortaba. Dejo de tener sentido al pasar a lista blanca: lo
    # unico que se copia son los favoritos y sus iconos, y Chrome escribe
    # 'Bookmarks' de forma atomica, asi que se puede leer con Chrome abierto.
    # 'Favicons' si es una base SQLite que Chrome bloquea; si no llega, se anota
    # y la barra sale sin iconos, que es un detalle cosmetico.
    if chrome_esta_corriendo():
        log.warning(
            "Chrome esta abierto. Los favoritos se copian igual; los iconos "
            "('Favicons') pueden quedarse fuera porque Chrome bloquea esa base. "
            "Cerrarlo si se quiere la copia completa."
        )

    try:
        resultado = sembrar(
            origen,
            Path(destino),
            directorio=cfg.navegador_perfil_directorio,
            rehacer=args.rehacer,
        )
    except ErrorSiembraPerfil as exc:
        log.error("%s", exc)
        return 2

    print(f"Archivos copiados : {resultado.archivos}")
    print(f"Tamano            : {resultado.megabytes:.1f} MB")
    if resultado.omitidos_por_bloqueo:
        muestra = ", ".join(sorted(set(resultado.omitidos_por_bloqueo))[:6])
        print(f"Bloqueados        : {len(resultado.omitidos_por_bloqueo)} ({muestra})")
    if resultado.conservados:
        print(f"Conservados       : {', '.join(sorted(set(resultado.conservados)))}")
        print("    Ya estaban en el destino y NO se pisaron: llevan el estado")
        print("    de sesion del perfil de trabajo.")
    if resultado.protecciones_retiradas:
        print(f"Firmas retiradas  : {len(resultado.protecciones_retiradas)}")
        print("    Sin esto Chrome tomaria los favoritos por manipulados y los")
        print("    borraria al abrir el perfil.")
    if resultado.claves_ausentes:
        print(f"  ! No llegaron    : {', '.join(resultado.claves_ausentes)}")
        print("    Sin esos archivos faltaran favoritos en la copia.")
    else:
        print("Favoritos y preferencias: copiados.")

    print()
    print("Siguiente paso, para ver que sobrevivio:")
    print("  python scripts\\probar_perfil.py")
    print()
    print("La sesion de Google NO viaja en la copia (Chrome la cifra contra su")
    print("instalacion). Se inicia UNA vez y se queda:")
    print("  python scripts\\probar_perfil.py --iniciar-sesion")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
