"""Diagnostico: que sesiones tiene realmente el perfil persistente.

Ya NO forma parte del flujo de grabacion. Los scripts de grabacion usan
`scripts/grabar.py`, que abre el perfil directamente con
`launch_persistent_context`, asi que no hace falta exportar nada.

Se conserva porque responde a una pregunta que cuesta contestar de otro modo:
**a que servicios esta autenticado este perfil?** Fue lo que revelo, el
21/08/2026, que el perfil creado para Power BI no tenia sesion de Google: traia
12 cookies pero solo una de google.com ('NID', de preferencias). Drive no
redirige al login en ese caso -- devuelve un 404 -- asi que el sintoma era
enganoso.

Tambien sirve para alimentar `playwright codegen --load-storage`, que es la
unica via de sesion que admite el CLI (no acepta `--user-data-dir`).

El archivo generado ES UNA CREDENCIAL
-------------------------------------
Contiene cookies de sesion vivas: con el se entra a las cuentas sin contrasena.
Va a `config/estado_sesion.json`, que esta en .gitignore. Conviene regenerarlo
antes de cada grabacion y borrarlo despues.

Uso:
    python scripts/exportar_sesion.py --url https://drive.google.com/
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# permite ejecutar el script sin instalar el paquete
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from playwright.sync_api import sync_playwright  # noqa: E402

from moodle_sinu import registro  # noqa: E402
from moodle_sinu.config import DIR_CONFIG, Config, asegurar_directorios  # noqa: E402
from moodle_sinu.navegador import abrir_contexto  # noqa: E402

log = logging.getLogger("exportar_sesion")

RUTA_POR_DEFECTO = DIR_CONFIG / "estado_sesion.json"


def _argumentos() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Exporta la sesion del perfil para codegen")
    p.add_argument(
        "--url",
        default=None,
        help="URL a visitar antes de exportar, para que las cookies de ese "
        "dominio esten cargadas (p. ej. la carpeta de Drive)",
    )
    p.add_argument(
        "--salida",
        default=str(RUTA_POR_DEFECTO),
        help=f"Ruta del JSON de sesion (por defecto {RUTA_POR_DEFECTO})",
    )
    p.add_argument(
        "--visible",
        action="store_true",
        help="Abre el navegador con ventana. Necesario si hay que resolver un "
        "login o un segundo factor antes de exportar.",
    )
    p.add_argument(
        "--esperar",
        type=int,
        default=0,
        help="Segundos de espera antes de exportar, para resolver un login a mano",
    )
    p.add_argument("--verbose", "-v", action="store_true", help="Log en DEBUG")
    return p.parse_args()


#: Cookies que Google usa para autenticar. Si no hay ninguna, el estado
#: exportado no sirve para entrar: `NID` sola es de preferencias, no de sesion.
_COOKIES_AUTH_GOOGLE = {
    "SID", "HSID", "SSID", "APISID", "SAPISID",
    "__Secure-1PSID", "__Secure-3PSID", "LSID",
}


def _tiene_sesion_utilizable(destino: Path, url: str | None) -> bool:
    """Comprueba que lo exportado sirva de verdad para entrar.

    Comprobado el 21/08/2026: el perfil traia 12 cookies pero solo UNA de
    google.com ('NID', de preferencias). Un archivo de 3,8 KiB parecia correcto
    y no autenticaba nada. Sin esta comprobacion el fallo aparece mucho despues,
    como un 404 de Drive.
    """
    import json
    from urllib.parse import urlsplit

    datos = json.loads(destino.read_text(encoding="utf-8"))
    cookies = datos.get("cookies", [])
    por_dominio: dict[str, int] = {}
    for cookie in cookies:
        dominio = cookie.get("domain", "?")
        por_dominio[dominio] = por_dominio.get(dominio, 0) + 1

    print("Cookies por dominio:")
    for dominio, n in sorted(por_dominio.items(), key=lambda kv: -kv[1]):
        print(f"  {dominio:32} {n}")
    print()

    if not url:
        return True

    host = urlsplit(url).netloc.lower()
    if "google.com" not in host:
        return True

    nombres = {c.get("name") for c in cookies if "google" in c.get("domain", "")}
    if nombres & _COOKIES_AUTH_GOOGLE:
        log.info("El estado incluye cookies de sesion de Google.")
        return True

    log.error(
        "El estado NO incluye ninguna cookie de autenticacion de Google "
        "(%s). Las encontradas para google.com son %s, que no autentican.\n"
        "El perfil %s no tiene sesion de Google: probablemente se creo solo "
        "para Power BI.\n"
        "Como arreglarlo: ejecutar\n"
        "    python scripts/exportar_sesion.py --url %s --visible --esperar 120\n"
        "iniciar sesion en Google en la ventana que se abre, y dejar que "
        "termine. La sesion queda en el perfil y las siguientes veces ya no "
        "hara falta.",
        ", ".join(sorted(_COOKIES_AUTH_GOOGLE)),
        sorted(nombres) or "ninguna",
        Config.desde_entorno().powerbi_perfil_navegador,
        url,
    )
    return False


def main() -> int:
    args = _argumentos()
    asegurar_directorios()
    registro.configurar(
        logging.DEBUG if args.verbose else logging.INFO, etiqueta="exportar_sesion"
    )
    cfg = Config.desde_entorno()

    if not cfg.powerbi_perfil_navegador:
        log.error(
            "POWERBI_PERFIL_NAVEGADOR esta vacio: no hay perfil del que exportar "
            "la sesion. Configurarlo en config/.env y ejecutar una etapa con "
            "--visible para iniciar sesion."
        )
        return 2

    destino = Path(args.salida)
    destino.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        context, cerrar = abrir_contexto(pw, cfg, headless=not args.visible)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            if args.url:
                log.info("Visitando %s para cargar sus cookies", args.url)
                try:
                    page.goto(args.url, wait_until="domcontentloaded",
                              timeout=cfg.timeout_render_seg * 1000)
                except Exception as exc:  # noqa: BLE001 - informativo, no bloquea
                    log.warning("No se pudo abrir %s (%s); se exporta igual.", args.url, exc)

                if "accounts.google.com" in page.url or "signin" in page.url:
                    log.warning(
                        "La pagina redirigio al login: la sesion de ese dominio no "
                        "esta viva. Ejecutar con --visible --esperar 120 y entrar "
                        "a mano antes de que exporte."
                    )

            if args.esperar:
                log.info("Esperando %ss para que se resuelva el login a mano...", args.esperar)
                page.wait_for_timeout(args.esperar * 1000)

            context.storage_state(path=str(destino))
        finally:
            cerrar()

    tamano = destino.stat().st_size if destino.is_file() else 0
    if tamano == 0:
        log.error("El estado de sesion salio vacio: %s", destino)
        return 1

    if not _tiene_sesion_utilizable(destino, args.url):
        # Se borra: un estado inservible que --load-storage cargaria igualmente
        # es peor que no tener ninguno, porque el fallo aparece mas tarde y
        # disfrazado de otra cosa.
        destino.unlink(missing_ok=True)
        log.info("Se descarto %s por no autenticar.", destino)
        return 1

    print(f"Sesion exportada : {destino} ({tamano / 1024:.1f} KiB)")
    print("Es una CREDENCIAL: contiene cookies de sesion vivas.")
    print("Esta en .gitignore; borrarlo cuando termine la grabacion.")
    print()
    print("Ahora codegen puede arrancar ya autenticado:")
    print(f"  playwright codegen --load-storage {destino} <url>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
