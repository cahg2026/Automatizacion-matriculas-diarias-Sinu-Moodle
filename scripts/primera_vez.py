"""Asistente de puesta en marcha: de un clon recien hecho a una prueba real.

Para quien recibe el proyecto por primera vez. Lleva de la mano por todo lo que
NO viaja en el repositorio -- que es, a proposito, todo lo sensible -- y lo
verifica sobre el terreno en vez de darlo por supuesto.

    0. El entorno: Python, el venv, Playwright, Chromium
    1. config/.env: se crea desde la plantilla y se dice que falta rellenar
    2. El perfil de Chrome: se siembra si no existe
    3. La CA corporativa, si el antivirus intercepta el HTTPS
    4. Las sesiones: se abre cada sitio para entrar con LAS PROPIAS credenciales
       -- Power BI, SINU, Google (Drive y Calendar)
    5. Se comprueba cada sesion NAVEGANDO, no contando cookies
    6. Una corrida en simulacion, que no escribe nada

Por que verificar navegando y no por cookies: el 08/09/2026 el perfil tenia 88
cookies y "todas las de sesion de Google presentes" mientras Google habia
invalidado la sesion del lado del servidor. El paso 0 dio el visto bueno, se
exporto Power BI, se abrio el cerrojo de escritura, y el fallo salio en el paso
3. Una cookie presente dice que el navegador la guarda, no que el servidor la
acepte.

Cada cuenta es PERSONAL salvo Power BI: la de SINU identifica quien hace cada
vinculacion, y la de Google decide a que Drive y a que Calendar se escribe.

Uso:
    python scripts\\primera_vez.py            # el asistente completo
    python scripts\\primera_vez.py --revisar  # solo diagnostica, no abre nada
"""

from __future__ import annotations

import argparse
import importlib.util
import logging
import shutil
import ssl
import socket
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from moodle_sinu import registro  # noqa: E402
from moodle_sinu.config import (  # noqa: E402
    DIR_CONFIG,
    RUTA_CA_CORPORATIVA,
    RUTA_ENV,
    Config,
    asegurar_directorios,
)
from moodle_sinu.perfil_navegador import (  # noqa: E402
    chrome_esta_corriendo,
    pide_iniciar_sesion,
    resolver,
)

log = logging.getLogger("primera_vez")

RUTA_PLANTILLA = DIR_CONFIG / ".env.example"

#: Las claves sin las que el flujo no arranca. Las de aviso no entran: sin
#: ellas el flujo corre igual y solo pierde la notificacion.
CLAVES_IMPRESCINDIBLES = (
    ("POWERBI_USUARIO", "cuenta de Power BI (compartida del area)"),
    ("POWERBI_PASSWORD", "contrasena de Power BI (compartida del area)"),
    ("POWERBI_URL_INFORME", "URL del informe ValidacionMoodle"),
    ("SINU_USUARIO", "SU cuenta de SINU, con permiso sobre ISEF07"),
    ("SINU_PASSWORD", "contrasena de SU cuenta de SINU"),
    ("GOOGLE_CARPETA_RAIZ_ID", "id de la carpeta de Drive (de su URL)"),
)

SEG_ESPERA_LOGIN = 240


def titulo(texto: str) -> None:
    print()
    print("=" * 70)
    print(texto)
    print("=" * 70)


def _ok(texto: str) -> None:
    print(f"  [ok] {texto}")


def _falta(texto: str) -> None:
    print(f"  [!!] {texto}")


# ---------------------------------------------------------------------------
# 0. El entorno
# ---------------------------------------------------------------------------


def revisar_entorno() -> bool:
    titulo("PASO 0 - El entorno")
    todo_bien = True

    v = sys.version_info
    if (v.major, v.minor) >= (3, 11):
        _ok(f"Python {v.major}.{v.minor}.{v.micro}")
    else:
        _falta(f"Python {v.major}.{v.minor}: hace falta 3.11 o mas.")
        todo_bien = False

    if (RAIZ / ".venv" / "Scripts" / "python.exe").is_file():
        _ok("El entorno virtual .venv existe.")
    else:
        _falta("No hay .venv. Crearlo:  py -3.11 -m venv .venv")
        todo_bien = False

    # find_spec en vez de importar: comprueba lo mismo sin cargar el modulo ni
    # dejar un import sin usar que confunda a quien lea esto.
    if importlib.util.find_spec("playwright") is not None:
        _ok("Playwright instalado.")
    else:
        _falta("Falta Playwright:  .venv\\Scripts\\pip install -r requirements.txt")
        todo_bien = False

    # Chromium/Chrome: el canal por defecto es el Chrome instalado.
    if shutil.which("chrome") or Path(
        r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    ).is_file():
        _ok("Chrome instalado (NAVEGADOR_CANAL=chrome).")
    else:
        _falta(
            "No se encontro Chrome. O se instala, o se pone "
            "NAVEGADOR_CANAL=chromium y se ejecuta "
            ".venv\\Scripts\\playwright install chromium"
        )
        todo_bien = False

    return todo_bien


# ---------------------------------------------------------------------------
# 1. config/.env
# ---------------------------------------------------------------------------


def preparar_env(solo_revisar: bool) -> bool:
    titulo("PASO 1 - config/.env, sus credenciales")

    if not RUTA_PLANTILLA.is_file():
        _falta("No esta la plantilla config/.env.example. Clon incompleto?")
        return False

    if not RUTA_ENV.is_file():
        if solo_revisar:
            # Se informa igual de QUE hara falta. La primera version salia aqui
            # sin listar nada y luego decia "rellene las claves de arriba",
            # cuando arriba no habia ninguna.
            _falta(f"No existe {RUTA_ENV.name}; se creara desde la plantilla.")
            origen = RUTA_PLANTILLA
        else:
            shutil.copy2(RUTA_PLANTILLA, RUTA_ENV)
            _ok(f"Creado {RUTA_ENV} desde la plantilla.")
            origen = RUTA_ENV
    else:
        _ok(f"{RUTA_ENV.name} ya existe.")
        origen = RUTA_ENV

    texto = origen.read_text(encoding="utf-8")
    vacias = []
    for clave, para_que in CLAVES_IMPRESCINDIBLES:
        # La clave esta vacia si aparece como `CLAVE=` sin nada detras.
        for linea in texto.splitlines():
            if linea.strip().startswith(f"{clave}="):
                if not linea.split("=", 1)[1].strip():
                    vacias.append((clave, para_que))
                break
        else:
            vacias.append((clave, para_que))

    if not vacias:
        _ok("Las claves imprescindibles estan rellenas.")
        return True

    print()
    _falta(f"Faltan {len(vacias)} claves por rellenar en {RUTA_ENV}:")
    print()
    for clave, para_que in vacias:
        print(f"      {clave:<24} {para_que}")
    print()
    print("      Ojo: SINU_USUARIO y SINU_PASSWORD son SUYAS, no se comparten.")
    print("      Cada vinculacion queda registrada a nombre de quien la hace.")
    print()
    print("      Abrirlo con:  notepad config\\.env")
    return False


# ---------------------------------------------------------------------------
# 2. El perfil de Chrome
# ---------------------------------------------------------------------------


def revisar_perfil(cfg: Config) -> bool:
    titulo("PASO 2 - El perfil de Chrome")
    perfil = resolver(cfg)
    print(f"  Perfil configurado: {cfg.navegador_perfil}")
    print(f"  Carpeta           : {perfil.ruta}")

    if perfil.es_chrome_real:
        _falta(
            "Esta apuntando al perfil PERSONAL de Chrome. Chrome 136+ se niega a "
            "automatizarlo.\n"
            "      Poner NAVEGADOR_PERFIL=proyecto en config/.env."
        )
        return False

    if not perfil.ruta.exists():
        _falta("La carpeta del perfil no existe todavia.")
        print("      Se crea sola al abrir el navegador por primera vez, o con:")
        print("        python scripts\\sembrar_perfil.py")
        print("      (sembrarla copia los favoritos del Chrome personal)")
        return False

    _ok("La carpeta del perfil existe.")
    if chrome_esta_corriendo():
        print("  (Chrome esta abierto; con el perfil dedicado no estorba)")
    return True


# ---------------------------------------------------------------------------
# 3 y 4. Las sesiones
# ---------------------------------------------------------------------------


def _url_sinu(cfg: Config) -> str:
    return cfg.sinu_url


def _url_drive(cfg: Config) -> str:
    if cfg.google_carpeta_raiz_id:
        return f"https://drive.google.com/drive/folders/{cfg.google_carpeta_raiz_id}"
    return "https://drive.google.com/drive/my-drive"


def autenticar(cfg: Config, solo_revisar: bool) -> bool:
    titulo("PASO 4 - Sus sesiones en cada sitio")

    if solo_revisar:
        print("  (--revisar: no se abre el navegador)")
        return True

    from playwright.sync_api import sync_playwright

    from moodle_sinu.navegador import abrir_contexto

    destinos = [
        ("Power BI", cfg.powerbi_url_informe or "https://app.powerbi.com/"),
        ("SINU", _url_sinu(cfg)),
        ("Google Drive", _url_drive(cfg)),
        ("Google Calendar", "https://calendar.google.com/calendar/u/0/r"),
    ]

    print("  Se abrira una ventana por cada sitio. Entre con SUS credenciales.")
    print("  La sesion queda guardada en el perfil: solo hay que hacerlo una vez.")
    print(f"  Hay hasta {SEG_ESPERA_LOGIN}s por sitio; cerrar la ventana al acabar.")

    resultados: list[tuple[str, bool, str]] = []
    with sync_playwright() as pw:
        # Con ventana, obligatorio: hay que poder teclear la contrasena.
        contexto, cerrar = abrir_contexto(pw, cfg, headless=False)
        try:
            for nombre, url in destinos:
                print()
                print(f"  --- {nombre} ---")
                print(f"      {url}")
                page = contexto.new_page()
                try:
                    page.goto(url, timeout=60000, wait_until="domcontentloaded")
                    page.wait_for_timeout(3000)
                    print("      Entre ahora si se lo pide. Cierre la pestana al terminar.")
                    try:
                        page.wait_for_event("close", timeout=SEG_ESPERA_LOGIN * 1000)
                        print("      (pestana cerrada)")
                    except Exception:  # noqa: BLE001 - se agoto el plazo
                        print("      (se agoto el plazo; se continua)")
                except Exception as exc:  # noqa: BLE001
                    resultados.append((nombre, False, str(exc).splitlines()[0][:70]))
                    continue
                finally:
                    try:
                        page.close()
                    except Exception:  # noqa: BLE001
                        pass

            # --- La verificacion, navegando ---
            titulo("PASO 5 - Comprobar las sesiones de verdad")
            print("  No se cuentan cookies: se pide una pagina y se mira si")
            print("  redirige al login. Es la unica prueba que no enganna.")
            print()
            for nombre, url in destinos:
                page = contexto.new_page()
                try:
                    page.goto(url, timeout=60000, wait_until="domcontentloaded")
                    page.wait_for_timeout(4000)
                    motivo = pide_iniciar_sesion(page.url)
                    if motivo:
                        resultados.append((nombre, False, motivo))
                    elif "login" in page.url.lower() or "signin" in page.url.lower():
                        resultados.append((nombre, False, "redirigio a una pagina de login"))
                    else:
                        resultados.append((nombre, True, ""))
                except Exception as exc:  # noqa: BLE001
                    resultados.append((nombre, False, str(exc).splitlines()[0][:70]))
                finally:
                    try:
                        page.close()
                    except Exception:  # noqa: BLE001
                        pass
        finally:
            cerrar()

    print()
    todo_bien = True
    for nombre, bien, detalle in resultados:
        if bien:
            _ok(f"{nombre}: sesion viva.")
        else:
            _falta(f"{nombre}: {detalle}")
            todo_bien = False
    return todo_bien


# ---------------------------------------------------------------------------
# 5. La CA corporativa
# ---------------------------------------------------------------------------


def revisar_ca() -> bool:
    titulo("PASO 3 - El antivirus y el HTTPS")

    if RUTA_CA_CORPORATIVA.is_file():
        _ok(f"Ya esta {RUTA_CA_CORPORATIVA.name}; Playwright confiara en el.")
        return True

    # Se mira quien firma de verdad el certificado de Google.
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with socket.create_connection(("drive.google.com", 443), timeout=10) as s:
            with ctx.wrap_socket(s, server_hostname="drive.google.com") as t:
                der = t.getpeercert(binary_form=True)
        intercepta = len(der) > 3000  # un certificado reemitido es mucho mayor
    except Exception as exc:  # noqa: BLE001
        print(f"  No se pudo comprobar: {exc}")
        return True

    if not intercepta:
        _ok("No parece haber interceptacion de HTTPS. Nada que hacer.")
        return True

    _falta("Parece que un antivirus reemite los certificados (interceptacion TLS).")
    print()
    print("      Chrome y Python lo aceptan porque leen el almacen de Windows;")
    print("      Playwright NO, porque su driver trae sus propias CAs. El sintoma")
    print("      es 'self-signed certificate in certificate chain' al leer el Sheet.")
    print()
    print("      Exportar la CA, una sola vez, desde PowerShell:")
    print()
    print("        $c = Get-ChildItem Cert:\\LocalMachine\\Root |")
    print("             Where-Object { $_.Subject -like '*Kaspersky*' } |")
    print("             Select-Object -First 1")
    print("        $b = [Convert]::ToBase64String($c.RawData, 'InsertLineBreaks')")
    print('        "-----BEGIN CERTIFICATE-----`n$b`n-----END CERTIFICATE-----" |')
    print("            Set-Content config\\ca_kaspersky.pem -Encoding ascii")
    print()
    print("      (si el antivirus no es Kaspersky, cambiar el nombre en el filtro)")
    return False


# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--revisar",
        action="store_true",
        help="Solo diagnostica: no crea el .env ni abre el navegador.",
    )
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args(argv)

    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(errors="replace")
        except AttributeError:  # pragma: no cover
            pass

    asegurar_directorios()
    registro.configurar(
        logging.DEBUG if args.verbose else logging.WARNING, etiqueta="primera_vez"
    )

    titulo("PUESTA EN MARCHA - Moodle vs SINU")
    print("  Este asistente comprueba todo lo que NO viaja en el repositorio.")
    print("  Nada de lo que haga aqui escribe en SINU.")

    pasos: list[tuple[str, bool]] = []
    pasos.append(("entorno", revisar_entorno()))

    env_ok = preparar_env(args.revisar)
    pasos.append(("config/.env", env_ok))

    if not env_ok:
        titulo("FALTA RELLENAR config/.env")
        print("  Rellene las claves de arriba y vuelva a ejecutar:")
        print("    python scripts\\primera_vez.py")
        return 1

    cfg = Config.desde_entorno()
    pasos.append(("perfil", revisar_perfil(cfg)))
    pasos.append(("CA corporativa", revisar_ca()))
    pasos.append(("sesiones", autenticar(cfg, args.revisar)))

    titulo("RESUMEN")
    for nombre, bien in pasos:
        print(f"  {'OK  ' if bien else 'FALTA'}  {nombre}")

    if all(bien for _, bien in pasos):
        print()
        print("  Todo listo. La prueba que NO escribe nada:")
        print()
        print("    .venv\\Scripts\\python.exe scripts\\dia_completo.py")
        print()
        print("  Recorre las seis etapas, entra a SINU, lee las grillas y dice")
        print("  que haria. Para escribir de verdad hace falta anadir")
        print("  --ejecutar-de-verdad, y conviene acordarlo antes con el equipo:")
        print("  dos personas procesando el mismo dia se pisan las matriculas.")
        return 0

    print()
    print("  Resuelva lo marcado y vuelva a ejecutar este asistente.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
