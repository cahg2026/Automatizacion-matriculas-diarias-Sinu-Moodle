"""Comprueba que la automatizacion puede abrir el perfil de Chrome configurado.

Contesta en segundos las tres preguntas que deciden si el flujo del dia va a
arrancar, sin tocar Drive ni SINU:

  1. Se puede abrir el perfil ahora mismo? (Chrome cerrado, carpeta correcta)
  2. Chrome acepta que lo automaticen con ese perfil?
  3. Estan dentro las cosas por las que se eligio: favoritos y sesiones.

Se hizo aparte porque el fallo tipico -- Chrome abierto -- aborta el flujo
entero despues de haber validado y ordenado el reporte. Vale mas descubrirlo
aqui, en diez segundos.

Uso:
    python scripts/probar_perfil.py [--visible] [--esperar N] [-v]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# permite ejecutar el script sin instalar el paquete
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from playwright.sync_api import (  # noqa: E402
    Error as ErrorPlaywright,
    sync_playwright,
)

from moodle_sinu import registro  # noqa: E402
from moodle_sinu.config import Config, asegurar_directorios  # noqa: E402
from moodle_sinu.navegador import abrir_contexto  # noqa: E402
from moodle_sinu.perfil_navegador import (  # noqa: E402
    ErrorPerfilNavegador,
    chrome_esta_corriendo,
    resolver,
)

log = logging.getLogger("probar_perfil")

#: Dominios cuya cookie de sesion hace falta para el flujo del dia.
DOMINIOS_CLAVE = ("google.com", "cun.edu.co")

#: Cookies que Google usa para la sesion. Su presencia distingue "hay sesion"
#: de "hay cookies": un simple `NID` o `CONSENT` aparece con solo cargar la
#: pagina de login y no significa nada.
COOKIES_DE_SESION_GOOGLE = (
    "SID",
    "HSID",
    "SSID",
    "APISID",
    "SAPISID",
    "__Secure-1PSID",
)


def _informar_cookies(context, momento: str) -> None:
    """Cuenta cookies por dominio y comprueba las de sesion de Google.

    Se mira el detalle porque el recuento total engana: con 33 cookies de
    google.com Drive seguia pidiendo elegir cuenta. Lo que importa es si estan
    las de sesion, y aun asi eso no garantiza que Drive cargue -- ver el
    selector de cuenta en el README.
    """
    cookies = context.cookies()
    print(f"[ok] Cookies {momento}: {len(cookies)}")
    for dominio in DOMINIOS_CLAVE:
        n = sum(1 for c in cookies if dominio in (c.get("domain") or ""))
        print(f"     sesion de {dominio:<14} {'si' if n else 'NO'} ({n} cookies)")
    nombres = {c["name"] for c in cookies if "google" in (c.get("domain") or "")}
    faltan = [n for n in COOKIES_DE_SESION_GOOGLE if n not in nombres]
    if faltan:
        print(f"     !! faltan cookies de sesion de Google: {', '.join(faltan)}")
    else:
        print("     cookies de sesion de Google: todas presentes")


def _argumentos() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Diagnostico del perfil de navegador")
    p.add_argument("--visible", action="store_true", help="Abrir con ventana")
    p.add_argument(
        "--esperar",
        type=int,
        default=0,
        help="Segundos a dejar el navegador abierto, para mirarlo o para "
        "entrar a mano en una cuenta",
    )
    p.add_argument(
        "--url",
        default=None,
        help="URL que se abre al arrancar. Con --visible --esperar sirve para "
        "iniciar sesion a mano una sola vez: la cookie queda en el perfil y "
        "las corridas siguientes ya no la piden.",
    )
    p.add_argument(
        "--iniciar-sesion",
        action="store_true",
        help="Atajo de --visible --url https://drive.google.com --esperar 300. "
        "Es el paso que hay que dar una vez tras sembrar el perfil: la sesion "
        "de Google es lo unico que la copia NO puede heredar, porque Chrome "
        "cifra las cookies contra su instalacion (App-Bound Encryption).",
    )
    p.add_argument("--verbose", "-v", action="store_true", help="Log en DEBUG")
    return p.parse_args()


def _contar_favoritos(perfil_ruta: Path, directorio: str | None) -> int | None:
    """Cuantos favoritos tiene el perfil, leyendo su archivo 'Bookmarks'.

    Es un JSON, no hay que abrir el navegador para contarlo. Devuelve None si
    el archivo no existe (perfil recien creado, o sin favoritos).

    Se mira tambien en 'Default': una carpeta de trabajo sembrada desde el
    perfil personal replica la estructura de 'User Data', con el perfil en su
    subcarpeta, mientras que un perfil creado por Playwright desde cero puede
    tener el archivo en la raiz.
    """
    import json

    candidatas = [
        perfil_ruta / (directorio or "") / "Bookmarks",
        perfil_ruta / "Default" / "Bookmarks",
        perfil_ruta / "Bookmarks",
    ]
    ruta = next((c for c in candidatas if c.is_file()), None)
    if ruta is None:
        return None
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.debug("No se pudo leer %s: %s", ruta, exc)
        return None

    total = 0

    def _recorrer(nodo) -> None:
        nonlocal total
        if isinstance(nodo, dict):
            if nodo.get("type") == "url":
                total += 1
            for hijo in nodo.get("children", []) or []:
                _recorrer(hijo)

    for raiz in (datos.get("roots") or {}).values():
        _recorrer(raiz)
    return total


def main() -> int:
    args = _argumentos()
    if args.iniciar_sesion:
        args.visible = True
        args.url = args.url or "https://drive.google.com"
        args.esperar = args.esperar or 300

    asegurar_directorios()
    registro.configurar(
        logging.DEBUG if args.verbose else logging.INFO, etiqueta="probar_perfil"
    )
    cfg = Config.desde_entorno()

    print("=== Perfil configurado ===")
    print(f"NAVEGADOR_PERFIL            : {cfg.navegador_perfil}")
    print(f"NAVEGADOR_PERFIL_DIRECTORIO : {cfg.navegador_perfil_directorio}")
    print(f"NAVEGADOR_CANAL             : {cfg.navegador_canal}")

    try:
        perfil = resolver(cfg)
    except ErrorPerfilNavegador as exc:
        print(f"\n[FALLO] {exc}")
        return 2

    print(f"Carpeta                     : {perfil.ruta}")
    print(f"Es el perfil personal       : {'si' if perfil.es_chrome_real else 'no'}")
    print(f"Existe                      : {'si' if perfil.ruta.is_dir() else 'no'}")
    print(f"Chrome corriendo ahora      : {'SI' if chrome_esta_corriendo() else 'no'}")

    favoritos = _contar_favoritos(
        perfil.ruta, perfil.directorio if perfil.es_chrome_real else None
    )
    print(
        "Favoritos en el perfil      : "
        + (str(favoritos) if favoritos is not None else "(sin archivo Bookmarks)")
    )
    print()

    sin_cabeza = not args.visible
    print("=== Intento de apertura ===")
    with sync_playwright() as pw:
        try:
            context, cerrar = abrir_contexto(pw, cfg, sin_cabeza)
        except ErrorPerfilNavegador as exc:
            print(f"\n[FALLO] {exc}")
            return 2
        except Exception as exc:  # noqa: BLE001 - el mensaje del driver es lo util
            print(f"\n[FALLO] Chrome no arranco con ese perfil:\n  {exc}")
            if perfil.es_chrome_real:
                print(
                    "\n  Las versiones recientes de Chrome pueden negarse a "
                    "automatizar el perfil personal.\n"
                    "  Si es el caso, poner NAVEGADOR_PERFIL=proyecto en "
                    "config/.env y autenticarse una vez con --visible."
                )
            return 1

        try:
            print("[ok] El navegador abrio con el perfil.")
            _informar_cookies(context, "en el perfil")
            if args.url or args.esperar:
                page = context.pages[0] if context.pages else context.new_page()
                if args.url:
                    page.goto(args.url, wait_until="domcontentloaded")
                    print(f"[ok] Abierto {args.url}")
                if args.esperar:
                    print(
                        f"\nVentana abierta hasta {args.esperar}s. Si hay que entrar "
                        "en alguna cuenta, es AHORA: la sesion se guarda en el\n"
                        "perfil y las corridas siguientes ya no la pediran.\n"
                        "Al terminar, CERRAR la ventana (o esperar el plazo).\n"
                    )
                    # Cerrar la ventana es la forma NATURAL de acabar, no un
                    # fallo: Playwright lanza TargetClosedError y sin capturarlo
                    # el script moria con un traceback justo antes de recontar
                    # las cookies, que es lo unico que se queria saber.
                    try:
                        page.wait_for_timeout(args.esperar * 1000)
                        print("[ok] Se agoto el plazo; se cierra el navegador.")
                    except ErrorPlaywright:
                        print("[ok] Ventana cerrada a mano.")
                    _informar_cookies(context, "al cerrar")
        finally:
            cerrar()

    print()
    print("Si las cookies clave salen en 'NO', iniciar sesion una sola vez:")
    print("  python scripts\\probar_perfil.py --iniciar-sesion")
    print("Las cookies del perfil personal NO se pueden copiar: Chrome las cifra")
    print("contra su instalacion (App-Bound Encryption). Los favoritos si viajan.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
