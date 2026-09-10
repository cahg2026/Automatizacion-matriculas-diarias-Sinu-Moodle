"""Grabador de flujos con perfil persistente y Chrome real.

Por que no se usa `playwright codegen` desde consola
----------------------------------------------------
El CLI **no acepta `--user-data-dir`**: eso es un parametro de
`launch_persistent_context` en la API, no del CLI (comprobado el 21/08/2026,
playwright 1.47). Y sin perfil, codegen abre un navegador aislado y en blanco,
sin ninguna sesion iniciada.

`--load-storage` era la alternativa por CLI, pero exporta solo cookies y
localStorage: no es el perfil. Aqui se usa el perfil de verdad.

Como graba
----------
`launch_persistent_context` abre el navegador con el perfil indicado y sus
sesiones vivas, y luego se activa el grabador de Playwright (el mismo que usa
codegen por dentro). Se accede por el canal interno del cliente porque la API
Python publica no lo expone: `_enableRecorder` solo existe en el driver JS. Si
esa via fallara, se cae a `page.pause()`, que abre el Inspector con su boton de
grabar; entonces el codigo se copia del Inspector en vez de escribirse solo.

Que perfil usar
---------------
- `--perfil proyecto` (por defecto): POWERBI_PERFIL_NAVEGADOR, el mismo de las
  etapas 1-3. Es el recomendado: aislado del Chrome personal, y lo que se grabe
  ahi corresponde a lo que vera la automatizacion.
- `--perfil chrome`: el perfil real de Chrome del usuario, con todas sus
  sesiones. Comodo, pero con dos avisos serios:
    1. **Chrome debe estar cerrado.** Chrome bloquea su carpeta de perfil
       mientras corre; con Chrome abierto esto falla o corrompe el perfil. El
       script lo comprueba y se niega a seguir.
    2. Las versiones recientes de Chrome restringen la automatizacion del perfil
       por defecto. Si se niega a arrancar, usar `--perfil proyecto`.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# permite ejecutar el script sin instalar el paquete
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from playwright.sync_api import sync_playwright  # noqa: E402

from moodle_sinu import perfil_navegador, registro  # noqa: E402
from moodle_sinu.config import Config, asegurar_directorios  # noqa: E402
from moodle_sinu.acceso_sinu import (  # noqa: E402
    ErrorAccesoSinu,
    abrir_sinu,
    iniciar_sesion,
    sesion_activa,
)
from moodle_sinu.navegador import (  # noqa: E402
    ARG_MAXIMIZAR,
    ARGS_A_IGNORAR,
    ARGS_COMPAT_RDP,
    ARGS_COMPAT_RDP_SIN_SANDBOX,
)

log = logging.getLogger("grabar")


# Las dos viven en `perfil_navegador`, que es de donde las toma tambien el
# arranque normal: la grabacion y la automatizacion tienen que coincidir en que
# perfil abren, o lo que se grabe no sera lo que vea el robot.
_perfil_chrome_real = perfil_navegador.perfil_chrome_real
_chrome_esta_corriendo = perfil_navegador.chrome_esta_corriendo


def _diagnosticar_pagina(page, respuesta, argumentos_chrome: tuple[str, ...]) -> None:
    """Comprueba que la pagina cargara de verdad, y explica que hacer si no.

    El sintoma reportado fue una ventana en blanco sin ningun error. Comprobado
    el 21/08/2026, la causa mas probable no era el renderizado sino la respuesta
    del servidor: la PRIMERA peticion a /sgacampus con el perfil frio devolvio
    'HTTP Status 404' de Tomcat, y a partir de la segunda -- ya con cookie de
    sesion -- respondio 200 y pinto las 535 etiquetas. Por eso se mira el
    estado HTTP y no solo si hay contenido: una pagina de error tiene texto de
    sobra y pasaria por buena.
    """
    if respuesta is not None and respuesta.status >= 400:
        log.error(
            "El servidor respondio HTTP %d en %s.\n"
            "  No es un problema de renderizado: la pagina no llego.\n"
            "  Con SINU, un 404 en la primera peticion de un perfil nuevo suele "
            "resolverse solo al reintentar (el ERP necesita crear la sesion).\n"
            "  Si persiste: comprobar la VPN y que la URL responda desde el "
            "navegador normal.",
            respuesta.status,
            respuesta.url[:90],
        )

    page.wait_for_timeout(3000)
    try:
        medida = page.evaluate(
            "() => ({ nodos: document.querySelectorAll('*').length,"
            " texto: (document.body ? document.body.innerText : '').trim().length })"
        )
    except Exception as exc:  # noqa: BLE001 - informativo
        log.warning("No se pudo medir el contenido de la pagina: %s", exc)
        return

    log.info(
        "Pagina cargada: %d nodos, %d caracteres de texto (%s)",
        medida["nodos"],
        medida["texto"],
        page.url[:70],
    )

    # Un documento vacio ronda los 4-10 nodos (html, head, body...).
    if medida["nodos"] > 30 or medida["texto"] > 40:
        return

    log.error(
        "La pagina parece EN BLANCO (%d nodos, %d caracteres).\n"
        "  Argumentos en uso: %s\n"
        "  Que probar, en este orden:\n"
        "   1. Si no se paso --disable-gpu, pasarlo: es el que arregla el\n"
        "      renderizado en escritorio remoto.\n"
        "   2. --canal chromium, para descartar que sea el Chrome instalado.\n"
        "   3. Comprobar que la URL responde desde el navegador normal: puede\n"
        "      ser la VPN o que el ERP exija una sesion previa.",
        medida["nodos"],
        medida["texto"],
        " ".join(argumentos_chrome) or "(ninguno)",
    )


def _argumentos() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("url", help="URL donde empezar a grabar")
    p.add_argument(
        "--salida",
        default=None,
        help="Archivo .py donde escribir la grabacion (por defecto, solo Inspector)",
    )
    p.add_argument(
        "--perfil",
        default=None,
        help="'chrome' (el perfil personal), 'proyecto' (POWERBI_PERFIL_NAVEGADOR) "
        "o una ruta explicita. Por defecto, el de NAVEGADOR_PERFIL en config/.env: "
        "grabar con un perfil distinto al que usa el robot es como grabar otra "
        "pantalla, porque cambian favoritos y sesiones.",
    )
    p.add_argument(
        "--canal",
        default="chrome",
        choices=["chrome", "chrome-beta", "msedge", "chromium"],
        help="Navegador a usar. 'chrome' abre el Chrome instalado, tal como lo "
        "ve el usuario (por defecto)",
    )
    p.add_argument("--idioma", default=None, help="Locale (por defecto, POWERBI_IDIOMA)")
    p.add_argument(
        "--con-sandbox",
        action="store_true",
        help="Mantiene el sandbox de Chrome: quita --no-sandbox y deja el resto "
        "de los argumentos de compatibilidad con RDP. Probar esto primero: "
        "--disable-gpu es lo que arregla el renderizado, no --no-sandbox.",
    )
    p.add_argument(
        "--sin-compat-rdp",
        action="store_true",
        help="No pasar ningun argumento de compatibilidad con RDP",
    )
    p.add_argument(
        "--sinu",
        action="store_true",
        help="La URL es SINU: aplica su estrategia de carga (barra final, "
        "reintento con reload si Tomcat responde 404, espera a un selector real) "
        "e inicia sesion con SINU_USUARIO/SINU_PASSWORD si estan en config/.env",
    )
    p.add_argument("--verbose", "-v", action="store_true", help="Log en DEBUG")
    return p.parse_args()


def _resolver_perfil(opcion: str | None, cfg: Config) -> tuple[Path, bool, str | None]:
    """Devuelve (carpeta, es_el_chrome_real, subdirectorio_del_perfil).

    Delega en `perfil_navegador` para que la grabacion abra EXACTAMENTE el
    mismo perfil que el flujo del dia. Sin `--perfil` manda NAVEGADOR_PERFIL.
    """
    if opcion is None:
        perfil = perfil_navegador.resolver(cfg)
    else:
        # Se reutiliza el resolutor pasandole la opcion como si viniera del
        # entorno, para no tener dos reglas distintas de resolucion.
        from dataclasses import replace as _replace

        perfil = perfil_navegador.resolver(_replace(cfg, navegador_perfil=opcion))

    try:
        perfil_navegador.exigir_disponible(perfil)
    except perfil_navegador.ErrorPerfilNavegador as exc:
        raise SystemExit(str(exc)) from exc
    return perfil.ruta, perfil.es_chrome_real, perfil.directorio


def main() -> int:
    args = _argumentos()
    asegurar_directorios()
    registro.configurar(logging.DEBUG if args.verbose else logging.INFO, etiqueta="grabar")
    cfg = Config.desde_entorno()

    # Comprueba y aborta con instrucciones si el perfil no se puede abrir ahora
    # (tipicamente, Chrome abierto bloqueando su carpeta).
    perfil, es_chrome_real, subdirectorio = _resolver_perfil(args.perfil, cfg)
    idioma = args.idioma or cfg.powerbi_idioma
    salida = Path(args.salida).resolve() if args.salida else None

    # Argumentos de compatibilidad con escritorio remoto: en RDP no hay GPU
    # utilizable y SINU se queda en blanco porque no llega a pintar nada.
    if args.sin_compat_rdp:
        argumentos_chrome: tuple[str, ...] = ()
    elif args.con_sandbox:
        argumentos_chrome = ARGS_COMPAT_RDP_SIN_SANDBOX
    else:
        argumentos_chrome = ARGS_COMPAT_RDP

    # El grabador siempre abre con ventana, asi que la ventana manda: sin
    # viewport fijo y maximizada. Con un viewport de 1920x1080 forzado en una
    # pantalla menor -- 1280x720 al 150% en la sesion remota -- la pagina se
    # comprime y la interfaz se ve diminuta.
    argumentos_chrome = argumentos_chrome + (ARG_MAXIMIZAR,)

    # Con el perfil personal hay que decirle a Chrome CUAL de sus perfiles
    # abrir: la carpeta que recibe Playwright es 'User Data', que los contiene
    # todos. Sin esto abriria 'Default' aunque el operador use otro.
    if subdirectorio:
        argumentos_chrome = argumentos_chrome + (f"--profile-directory={subdirectorio}",)

    if not es_chrome_real and args.canal != cfg.navegador_canal:
        log.warning(
            "El canal de la grabacion ('%s') no coincide con NAVEGADOR_CANAL "
            "('%s'), y comparten el perfil %s. Mezclar versiones de Chrome sobre "
            "un mismo perfil lo degrada y el navegador muere al arrancar. Usar "
            "el mismo canal, o un perfil aparte.",
            args.canal,
            cfg.navegador_canal,
            perfil,
        )

    print(f"Perfil   : {perfil}")
    print(f"Canal    : {args.canal}")
    print(f"Idioma   : {idioma}")
    print(f"URL      : {args.url}")
    print(f"Salida   : {salida or '(solo Inspector; copiar el codigo de ahi)'}")
    print(f"Args     : {' '.join(argumentos_chrome) or '(ninguno)'}")
    print(f"Ignorados: {' '.join(ARGS_A_IGNORAR)}")
    print()
    if "--no-sandbox" in argumentos_chrome:
        log.warning(
            "--no-sandbox desactiva el sandbox de Chrome. Si la pagina se ve "
            "bien sin el, usar --con-sandbox: el que arregla el renderizado en "
            "RDP es --disable-gpu."
        )

    with sync_playwright() as pw:
        try:
            context = pw.chromium.launch_persistent_context(
                str(perfil),
                channel=args.canal,
                headless=False,
                locale=idioma,
                # no_viewport en vez de viewport: son mutuamente excluyentes, y
                # con ventana el tamano correcto es el de la ventana.
                no_viewport=True,
                accept_downloads=True,
                # Sin esto, Chrome marca navigator.webdriver y muestra el aviso
                # de "controlado por software automatizado".
                ignore_default_args=list(ARGS_A_IGNORAR),
                args=list(argumentos_chrome),
            )
        except Exception as exc:  # noqa: BLE001 - el mensaje del driver es lo util
            log.error("No se pudo abrir el navegador con ese perfil: %s", exc)
            if es_chrome_real:
                log.error(
                    "Con el perfil real de Chrome esto suele ser por dos motivos: "
                    "Chrome sigue abierto, o la version de Chrome restringe la "
                    "automatizacion del perfil por defecto. Probar "
                    "--perfil proyecto."
                )
            return 1

        try:
            page = context.pages[0] if context.pages else context.new_page()
            if args.sinu:
                # Estrategia propia de SINU, compartida con la etapa 3.
                try:
                    abrir_sinu(page, cfg)
                    if sesion_activa(page):
                        print("Sesion de SINU ya activa en el perfil.")
                    else:
                        try:
                            iniciar_sesion(page, cfg)
                            print("Sesion de SINU iniciada con las credenciales guardadas.")
                        except ErrorAccesoSinu as exc:
                            log.warning("%s", exc)
                            print("Habra que entrar a mano en la ventana que se abrio.")
                except ErrorAccesoSinu as exc:
                    log.error("%s", exc)
                    return 1
            else:
                respuesta = page.goto(args.url, wait_until="domcontentloaded")
                _diagnosticar_pagina(page, respuesta, argumentos_chrome)

            grabando_a_archivo = False
            if salida is not None:
                # El grabador de Playwright, el mismo que usa codegen. Se llama
                # por el canal interno porque la API Python no lo expone: si una
                # actualizacion lo renombra, esto deja de funcionar y se cae al
                # Inspector, que es la via publica.
                try:
                    context._impl_obj._channel.send_no_reply(
                        "enableRecorder",
                        {
                            "language": "python",
                            "mode": "recording",
                            "outputFile": str(salida),
                        },
                    )
                    grabando_a_archivo = True
                    log.info("Grabador activo; se escribira en %s", salida)
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "El grabador interno no esta disponible (%s); se abre el "
                        "Inspector y habra que copiar el codigo de ahi.",
                        exc,
                    )

            if not grabando_a_archivo:
                print("Se abre el Inspector: pulsar 'Record' y copiar el codigo.")
                print("Cerrar el Inspector cuando termine.")
                page.pause()
            else:
                print("GRABANDO. Hacer el flujo en la ventana del navegador.")
                print("Al cerrar el navegador, la grabacion queda en el archivo.")
                print()
                # Se espera a que el usuario cierre el navegador.
                context.wait_for_event("close", timeout=0)
        except KeyboardInterrupt:
            print("\nInterrumpido.")
        finally:
            try:
                context.close()
            except Exception:  # noqa: BLE001 - ya estaba cerrado
                pass

    if salida is not None and salida.is_file():
        print()
        print(f"Grabacion en: {salida} ({salida.stat().st_size} bytes)")
        print("Esta en .gitignore. Extraer los selectores y borrarla.")
    elif salida is not None:
        print()
        print(f"No se escribio {salida}: no se registro ninguna accion.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
