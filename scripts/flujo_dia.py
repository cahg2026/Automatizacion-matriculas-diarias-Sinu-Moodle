"""Flujo del dia con UN SOLO navegador compartido entre etapas.

Lo que resuelve
---------------
Cada CLI de etapa abre y cierra su propio navegador, asi que la pestana del
Google Sheet moria al terminar la etapa 2. Aqui el contexto lo posee este
script y se lo presta a las etapas, de modo que:

    pestana 1: el Google Sheet del dia, abierto y disponible como referencia
    pestana 2: SINU

Alcance actual: llega hasta dejar ISEF07 abierto con el Periodo del dia ya
fijado. **No procesa cedulas**: eso es la etapa 4, que escribe.

Cerrojo de secuencia (regla del 31/08/2026)
-------------------------------------------
El orden no es una casualidad de como estan escritas las llamadas, es una
regla que se comprueba:

    1. Sube el reporte y ABRE el Sheet del dia en una pestana.
    2. Lee el Periodo de la PRIMERA FILA de ese Sheet.
    3. Solo entonces abre SINU en la pestana contigua y entra en ISEF07,
       fijando ese Periodo.

Si el Sheet no esta abierto y legible, el proceso se DETIENE (`ErrorSecuencia`)
en vez de abrir ISEF07. Sin fuente de origen no hay periodo que seleccionar, y
fijar uno a ojo significaria vincular matriculas del periodo equivocado.

Orden de los periodos
---------------------
La rutina de limpieza deja el .xlsx ya ordenado A-Z por COD_PERIODO antes de
subirlo (ver `orden_periodo`), asi que la primera fila del Sheet es justo el
primer lote del plan. Los dos se contrastan: si no coinciden se avisa, porque
suele significar que la pestana abierta no es el reporte de hoy.

Lo que NO cambia
----------------
- El mes de la carpeta sigue saliendo de `date.today()`.
- El numero del nombre sigue siendo la tarjeta 'NO MATRICULADO'.

Uso:
    python scripts/flujo_dia.py <reporte.xlsx> [--ya-validado]
                                [--no-matriculado N] [--visible] [-v]
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path

# permite ejecutar el script sin instalar el paquete
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from playwright.sync_api import sync_playwright  # noqa: E402

from moodle_sinu import grabador, registro  # noqa: E402
from moodle_sinu.acceso_sinu import ErrorAccesoSinu, abrir_sinu, iniciar_sesion, sesion_activa  # noqa: E402
from moodle_sinu.config import DIR_PROCESADO, Config, asegurar_directorios  # noqa: E402
from moodle_sinu.constantes_sinu import ACTIVIDAD_VINCULACION  # noqa: E402
from moodle_sinu.lector_reporte import ErrorEstructuraReporte  # noqa: E402
from moodle_sinu.lector_sinu import (  # noqa: E402
    ErrorLecturaSinu,
    entrar_en_modulo,
    fijar_periodo,
)
from moodle_sinu.modelos import ResultadoValidacion  # noqa: E402
from moodle_sinu.navegador import abrir_contexto  # noqa: E402
from moodle_sinu.orden_periodo import bloques_periodo  # noqa: E402
from moodle_sinu.perfil_navegador import ErrorPerfilNavegador  # noqa: E402
from moodle_sinu.periodo_sheet import (  # noqa: E402
    ErrorPeriodoSheet,
    ErrorSecuencia,
    comprobar_contra_plan,
    leer_periodo,
)
from moodle_sinu.plan_vinculacion import construir_plan  # noqa: E402
from moodle_sinu.restricciones_sinu import ErrorRestriccionOperativa  # noqa: E402
from moodle_sinu.salida_excel import escribir_copia_coloreada  # noqa: E402
from moodle_sinu.subidor_drive import ErrorSubidaDrive, subir_reporte  # noqa: E402
from moodle_sinu.validacion import validar_reporte  # noqa: E402

log = logging.getLogger("flujo_dia")


def _argumentos() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Flujo del dia con navegador compartido")
    p.add_argument("reporte", help="Ruta del .xlsx del reporte del dia")
    p.add_argument(
        "--ya-validado",
        action="store_true",
        help="El .xlsx ya trae los colores de la Fase 1",
    )
    p.add_argument(
        "--no-matriculado",
        type=int,
        default=None,
        help="Valor de la tarjeta 'NO MATRICULADO' (lo da la etapa 1)",
    )
    p.add_argument(
        "--sheet-url",
        default=None,
        metavar="URL",
        help="URL de un Google Sheet YA subido. Salta la etapa 2 (Drive) y "
        "arranca desde ahi: abre el Sheet, lee el Periodo de su primera fila y "
        "entra en ISEF07. Es la via para trabajar cuando la subida automatica "
        "falla -- se sube a mano y el resto del flujo sigue siendo automatico.",
    )
    p.add_argument("--visible", action="store_true", help="Navegador con ventana")
    p.add_argument(
        "--esperar",
        type=int,
        default=0,
        help="Segundos a mantener el navegador abierto al final, para mirarlo",
    )
    p.add_argument(
        "--grabar",
        nargs="?",
        const="sinu_grabado.py",
        default=None,
        metavar="SALIDA.py",
        help="Al terminar, enciende el grabador de Playwright y espera a que se "
        "cierre el navegador. Graba ISEF07 **con el Sheet ya abierto en su "
        "pestana y el Periodo del dia fijado**, que es la pantalla real que se "
        "quiere automatizar. Implica --visible. Por defecto escribe en "
        "sinu_grabado.py (que esta en .gitignore).",
    )
    p.add_argument("--verbose", "-v", action="store_true", help="Log en DEBUG")
    return p.parse_args()


def _preparar(entrada: Path, ya_validado: bool) -> tuple[Path, ResultadoValidacion]:
    """Devuelve (archivo a subir, resultado de la Fase 1 sobre ese archivo).

    La Fase 1 se ejecuta UNA sola vez y su resultado se reutiliza para el plan.
    Antes se validaba dos veces -- la segunda sobre la copia ya coloreada -- y
    eso descuadraba el plan: esa copia trae la columna VALIDACION_RPA, cuyo
    texto difiere entre las apariciones de un duplicado exacto, asi que la
    segunda pasada las tomaba por 'duplicado con datos distintos' y las omitia.
    """
    resultado = validar_reporte(entrada)
    if ya_validado:
        # El .xlsx ya viene coloreado y ordenado de una corrida anterior: se
        # sube tal cual, y el resultado solo sirve para construir el plan.
        return entrada, resultado

    sello = datetime.now().strftime("%Y%m%d_%H%M%S")
    destino = DIR_PROCESADO / f"{entrada.stem}_validado_{sello}.xlsx"
    # Colorea y, como ultimo paso, ordena A-Z por COD_PERIODO. `resultado`
    # queda renumerado para que sus filas apunten a `destino`, que es el
    # archivo que se sube y el que vera el operador en Sheets.
    escribir_copia_coloreada(resultado, destino)
    log.info("Copia coloreada y ordenada por periodo: %s", destino)
    return destino, resultado


def main() -> int:
    args = _argumentos()
    asegurar_directorios()
    archivo_log = registro.configurar(
        logging.DEBUG if args.verbose else logging.INFO, etiqueta="flujo_dia"
    )
    cfg = Config.desde_entorno()
    entrada = Path(args.reporte)
    if not entrada.is_file():
        log.error("No existe el archivo: %s", entrada)
        return 2

    try:
        a_subir, resultado = _preparar(entrada, args.ya_validado)
    except ErrorEstructuraReporte as exc:
        log.error("%s", exc)
        return 2

    # Comprobacion del ordenado, antes de subir nada: cada periodo debe ocupar
    # UN bloque contiguo. Si aparece partido, la automatizacion tendria que
    # cambiar el filtro de Periodo de ISEF07 de mas.
    bloques = bloques_periodo(resultado)
    distintos = {periodo for periodo, _ in bloques}
    print(f"Periodos en la tabla ordenada: {len(distintos)} en {len(bloques)} bloque(s)")
    for periodo, n in bloques:
        print(f"  {periodo:<14} {n} filas")
    if len(bloques) != len(distintos):  # pragma: no cover - no deberia pasar
        log.warning("Hay periodos partidos en varios bloques; revisar el ordenado.")
    print()

    # --grabar implica ventana: no se puede grabar lo que no se ve.
    sin_cabeza = False if (args.visible or args.grabar) else cfg.powerbi_headless

    # El contexto es de este script: las etapas lo reciben y no lo cierran.
    with sync_playwright() as pw:
        try:
            context, cerrar = abrir_contexto(pw, cfg, sin_cabeza)
        except ErrorPerfilNavegador as exc:
            # Tipicamente: Chrome abierto bloqueando su perfil. El mensaje ya
            # trae las instrucciones, asi que se imprime tal cual.
            log.error("%s", exc)
            return 2
        try:
            if args.sheet_url:
                # El Sheet ya esta subido: se abre y se sigue. La etapa 2 (Drive)
                # es la parte del flujo con los selectores sin verificar, asi que
                # poder saltarla mantiene util todo lo demas cuando falla.
                log.info("Se salta la etapa 2: se usa el Sheet indicado.")
                pagina_sheet = context.new_page()
                pagina_sheet.goto(
                    args.sheet_url,
                    wait_until="domcontentloaded",
                    timeout=cfg.timeout_render_seg * 1000,
                )
                pagina_sheet.wait_for_timeout(5000)
                print(f"Sheet (indicado) : {pagina_sheet.url[:88]}")
            else:
                # --- Etapa 2: Drive -> Sheet -> renombrado -> pestana abierta ---
                try:
                    subida = subir_reporte(
                        a_subir,
                        cfg=cfg,
                        fecha=date.today(),
                        no_matriculado=args.no_matriculado,
                        context=context,
                    )
                except ErrorSubidaDrive as exc:
                    log.error("Etapa 2 fallida: %s", exc)
                    return 1

                pagina_sheet = subida.pagina_sheet
                print(f"Reporte en Drive : {subida.nombre}")
                print(f"Carpeta          : {cfg.google_carpeta_raiz}/{subida.carpeta_mes}")
                print(f"Sheet            : {subida.url_sheet or '(no se abrio)'}")

            # --- CERROJO DE SECUENCIA -------------------------------------
            # Nada de SINU hasta tener el Sheet abierto Y su periodo leido.
            # El orden importa: ISEF07 no se abre sin saber que Periodo fijar,
            # porque un periodo equivocado vincula matriculas que no tocan.
            plan = construir_plan(resultado)
            periodo_plan = plan.lotes[0].cod_periodo if plan.lotes else None
            try:
                periodo = leer_periodo(pagina_sheet, cfg)
            except ErrorSecuencia as exc:
                log.error("PROCESO DETENIDO (regla de secuencia): %s", exc)
                return 1
            except ErrorPeriodoSheet as exc:
                log.error("No se pudo leer el Periodo del Sheet: %s", exc)
                return 1

            print()
            print(f"Periodo (1a fila del Sheet): {periodo}")
            print(f"Periodo (plan local)       : {periodo_plan or '(sin lotes)'}")
            for aviso in comprobar_contra_plan(periodo, periodo_plan):
                log.warning("%s", aviso)
                print(f"  ! {aviso}")

            # --- SINU en la pestana CONTIGUA del MISMO contexto ------------
            pagina_sinu = context.new_page()
            try:
                abrir_sinu(pagina_sinu, cfg)
                if sesion_activa(pagina_sinu):
                    log.info("Ya habia sesion de SINU en el perfil.")
                else:
                    iniciar_sesion(pagina_sinu, cfg)
            except ErrorAccesoSinu as exc:
                log.error("No se pudo entrar en SINU: %s", exc)
                return 1

            # --- ISEF07 con el Periodo que dijo el Sheet ------------------
            isef07_listo = False
            try:
                entrar_en_modulo(
                    pagina_sinu, cfg, ACTIVIDAD_VINCULACION, "fijar el periodo del dia"
                )
                fijar_periodo(pagina_sinu, cfg, periodo)
                isef07_listo = True
                print(f"ISEF07 abierto con el Periodo '{periodo}' fijado.")
            except (ErrorLecturaSinu, ErrorRestriccionOperativa) as exc:
                log.error(
                    "No se pudo dejar ISEF07 listo con el periodo '%s': %s\n"
                    "  Los selectores de ISEF07 siguen SIN VERIFICAR.",
                    periodo,
                    exc,
                )
                if not args.grabar:
                    return 1
                # Con --grabar NO se aborta: grabar es justo como se arreglan
                # estos selectores, asi que abortar por no tenerlos deja el
                # problema sin salida. Se cede el mando al operador.
                log.warning(
                    "Se continua a la grabacion de todos modos: es la via para "
                    "obtener los selectores reales. Hay que llegar a ISEF07 y "
                    "fijar el Periodo '%s' A MANO en la ventana.",
                    periodo,
                )

            # --- Estado final, que es lo que hay que comprobar ---
            print()
            print("Pestanas abiertas:")
            for i, pagina in enumerate(context.pages, 1):
                if pagina.is_closed():
                    continue
                print(f"  {i}. {pagina.url[:88]}")
            print()
            print(f"Sheet sigue abierto: {not pagina_sheet.is_closed()}")
            print(f"SINU con sesion    : {sesion_activa(pagina_sinu)}")

            # El plan salio de la MISMA validacion con la que se escribio el
            # archivo, no de releerlo: sus numeros de fila ya apuntan al .xlsx
            # ordenado que acaba de subirse.
            if plan.lotes:
                print(
                    f"Periodos por procesar (A-Z): {plan.n_periodos}, "
                    f"el primero es '{plan.lotes[0].cod_periodo}' "
                    f"con {plan.lotes[0].n_estudiantes} estudiantes"
                )
            print()
            print(
                f"ISEF07 queda listo con el Periodo '{periodo}'. Procesar las "
                "cedulas es la etapa 4 (scripts/ejecutar_sinu.py), que ESCRIBE."
            )

            # --- Grabacion, con el Sheet abierto y el Periodo ya fijado ------
            if args.grabar:
                salida = Path(args.grabar).resolve()
                pagina_sinu.bring_to_front()
                if grabador.activar(context, salida):
                    print()
                    print("=" * 70)
                    print("GRABANDO ISEF07. El Sheet sigue en su pestana.")
                    print("=" * 70)
                    print("Que grabar (SOLO LECTURA):")
                    if not isef07_listo:
                        print("  0. Entrar en ISEF07 y fijar el Periodo "
                              f"'{periodo}' A MANO:")
                        print("     la automatizacion no pudo, y grabarlo es como")
                        print("     se obtienen los selectores que le faltan.")
                    print("  1. Triple-clic en el filtro 'No. Identificacion',")
                    print("     escribir una cedula, Enter.")
                    print("  2. Clic en la fila del estudiante (carga la grilla Grupos).")
                    print("  3. Recorrer 'Curso en moodle?' y 'Vinculado?'.")
                    print()
                    if isef07_listo:
                        print("  El Periodo YA esta fijado: no hace falta tocarlo.")
                    print("  NO tocar 'Accion a realizar' ni el icono de ejecutar:")
                    print("  eso es la etapa 4 y escribe en matriculas reales.")
                    print()
                    print("Al CERRAR el navegador, la grabacion queda en el archivo.")
                    print(f"Salida: {salida}")
                    context.wait_for_event("close", timeout=0)
                else:
                    print("Se abre el Inspector: pulsar 'Record' y copiar el codigo.")
                    pagina_sinu.pause()
            elif args.esperar:
                log.info("Manteniendo el navegador %ss.", args.esperar)
                pagina_sinu.wait_for_timeout(args.esperar * 1000)
        except Exception:
            log.exception("Fallo inesperado en el flujo del dia")
            return 1
        finally:
            cerrar()

    print(f"Log de la corrida: {archivo_log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
