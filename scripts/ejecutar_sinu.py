"""CLI de la etapa 4: ejecuta la vinculacion en ISEF07. ESCRIBE en el sistema.

Es el unico script del proyecto que modifica matriculas. Tres cerrojos, y hay
que abrir los tres:

1. `MODO_SIMULACION=false` en config/.env.
2. `--ejecutar-de-verdad` en la linea de comandos.
3. `--periodo`, porque el filtro de Periodo se fija una vez por sesion.

Sin los dos primeros el script recorre todo y dice lo que haria, sin tocar nada.

Regla de negocio (21/08/2026):
  Vinculado? = False -> Vincular.
  Vinculado? = True  -> Desvincular, y despues Vincular.

Ojo: la accion de ISEF07 es por ESTUDIANTE, no por materia. Si alguna materia
del estudiante esta vinculada, el reciclado pasa por todas.

Uso:
    python scripts/ejecutar_sinu.py <reporte.xlsx> --periodo 26V05
                                    [--limite N] [--ejecutar-de-verdad]
                                    [--visible] [--traza] [-v]
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

# permite ejecutar el script sin instalar el paquete
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from playwright.sync_api import sync_playwright  # noqa: E402

from moodle_sinu import registro  # noqa: E402
from moodle_sinu.acceso_sinu import ErrorAccesoSinu, abrir_y_acceder  # noqa: E402
from moodle_sinu.config import DIR_LOGS, Config, asegurar_directorios  # noqa: E402
from moodle_sinu.ejecutor_sinu import (  # noqa: E402
    RUTA_CICLOS_ABIERTOS,
    CicloAbierto,
    ErrorEjecucionSinu,
    TipoSecuencia,
    ciclos_abiertos,
    decidir_secuencia,
    ejecutar_estudiante,
    estimar_segundos,
)
from moodle_sinu.lector_reporte import ErrorEstructuraReporte  # noqa: E402
from moodle_sinu.constantes_sinu import ACTIVIDAD_VINCULACION  # noqa: E402
from moodle_sinu.lector_sinu import (  # noqa: E402
    ErrorLecturaSinu,
    EstudianteAmbiguo,
    entrar_en_modulo,
    fijar_periodo,
    leer_estudiante,
)
from moodle_sinu.navegador import abrir_contexto  # noqa: E402
from moodle_sinu.constantes import COL_COD_PERIODO, COL_IDENTIFICACION  # noqa: E402
from moodle_sinu.periodo_sheet import (  # noqa: E402
    ErrorPeriodoSheet,
    ErrorSecuencia,
    leer_filas,
    leer_periodo,
)
from moodle_sinu.plan_vinculacion import construir_plan  # noqa: E402
from moodle_sinu.restricciones_sinu import (  # noqa: E402
    ErrorRestriccionOperativa,
    resumen_permisos,
)
from moodle_sinu.validacion import validar_reporte  # noqa: E402

log = logging.getLogger("ejecutar_sinu")


def _argumentos() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Etapa 4: vinculacion en ISEF07 (ESCRIBE)")
    p.add_argument("reporte", help="Ruta del .xlsx del reporte")
    p.add_argument("--periodo", required=True, help="COD_PERIODO del lote a trabajar")
    p.add_argument(
        "--sheet-url",
        required=True,
        metavar="URL",
        help="URL del Google Sheet del dia. OBLIGATORIA: la regla del proceso "
        "(31/08/2026) exige que el Sheet este abierto ANTES de entrar en ISEF07, "
        "porque es la fuente de origen del Periodo. Sin el, el proceso se "
        "detiene en vez de trabajar a ciegas.",
    )
    p.add_argument("--limite", type=int, default=None, help="Solo los primeros N estudiantes")
    p.add_argument(
        "--cedula",
        action="append",
        default=None,
        metavar="IDENTIFICACION",
        help="Procesa SOLO estas cedulas del lote (se puede repetir). Sirve para "
        "empezar por un estudiante concreto -- p. ej. uno cuya secuencia sea "
        "'vincular', que no pasa por desvincular y por tanto no puede dejar a "
        "nadie desvinculado si algo falla -- y para reintentar casos suelto.",
    )
    p.add_argument(
        "--ejecutar-de-verdad",
        action="store_true",
        help="Confirma que se quiere modificar SINU. Sin esto no se toca nada, "
        "aunque MODO_SIMULACION sea false.",
    )
    p.add_argument("--visible", action="store_true", help="Navegador con ventana")
    p.add_argument("--traza", action="store_true", help="Traza de Playwright en logs/")
    p.add_argument("--verbose", "-v", action="store_true", help="Log en DEBUG")
    return p.parse_args()


def _avisar_ciclos_previos() -> bool:
    """Informa de reciclados a medio hacer de corridas anteriores."""
    pendientes = ciclos_abiertos()
    if not pendientes:
        return False
    print()
    print("!! ATENCION: hay reciclados SIN CERRAR de corridas anteriores.")
    print("   Esos estudiantes pueden estar DESVINCULADOS ahora mismo:")
    for apunte in pendientes[:20]:
        print(
            f"     {apunte.get('identificacion')} ({apunte.get('cod_periodo')}) "
            f"- {apunte.get('estado')} - {apunte.get('momento')}"
        )
    print(f"   Registro: {RUTA_CICLOS_ABIERTOS}")
    print("   Conviene revisarlos en ISEF07 antes de seguir.")
    print()
    return True


def main() -> int:
    args = _argumentos()
    asegurar_directorios()
    archivo_log = registro.configurar(
        logging.DEBUG if args.verbose else logging.INFO, etiqueta="etapa4_sinu"
    )
    cfg = Config.desde_entorno()
    entrada = Path(args.reporte)

    try:
        resultado = validar_reporte(entrada)
    except (ErrorEstructuraReporte, FileNotFoundError) as exc:
        log.error("%s", exc)
        return 2

    plan = construir_plan(resultado)
    lotes = [l for l in plan.lotes if l.cod_periodo == args.periodo]
    if not lotes:
        log.error(
            "No hay operaciones para '%s'. Disponibles: %s",
            args.periodo,
            ", ".join(l.cod_periodo for l in plan.lotes),
        )
        return 2

    lote = lotes[0]
    operaciones = lote.operaciones

    if args.cedula:
        pedidas = {c.strip() for c in args.cedula if c.strip()}
        operaciones = [o for o in operaciones if o.identificacion in pedidas]
        no_estan = pedidas - {o.identificacion for o in operaciones}
        if no_estan:
            log.error(
                "Estas cedulas no estan en el lote de '%s': %s. No se procesa "
                "ninguna: si la lista pedida no se puede cumplir entera, seguir "
                "con parte de ella no es lo que se pidio.",
                args.periodo,
                ", ".join(sorted(no_estan)),
            )
            return 2

    if args.limite:
        operaciones = operaciones[: args.limite]

    # Los tres cerrojos. La simulacion es el estado por defecto a proposito.
    de_verdad = args.ejecutar_de_verdad and not cfg.modo_simulacion
    cfg_efectiva = cfg if de_verdad else Config(**{**cfg.__dict__, "modo_simulacion": True})

    print(f"Periodo     : {lote.cod_periodo}")
    print(f"Estudiantes : {len(operaciones)} de {lote.n_estudiantes}")
    print(f"Modo        : {'EJECUCION REAL' if de_verdad else 'SIMULACION (no se toca nada)'}")
    if not de_verdad:
        motivos = []
        if cfg.modo_simulacion:
            motivos.append("MODO_SIMULACION=true en config/.env")
        if not args.ejecutar_de_verdad:
            motivos.append("falta --ejecutar-de-verdad")
        print(f"              ({'; '.join(motivos)})")
    print()
    print(resumen_permisos())
    log.info("%s", resumen_permisos())
    _avisar_ciclos_previos()

    por_fila = {f.fila: f for f in resultado.filas}
    sin_cabeza = False if args.visible else cfg.powerbi_headless
    sello = datetime.now().strftime("%Y%m%d_%H%M%S")

    hechos: list = []
    reciclados = 0
    abiertos: list[str] = []
    detenidos: list[tuple[str, str]] = []

    with sync_playwright() as pw:
        context, cerrar = abrir_contexto(pw, cfg, sin_cabeza)
        ruta_traza = None
        if args.traza:
            DIR_LOGS.mkdir(parents=True, exist_ok=True)
            ruta_traza = DIR_LOGS / f"traza_etapa4_{sello}.zip"
            context.tracing.start(screenshots=True, snapshots=True, sources=True)

        try:
            # --- PASO 1: el Sheet del dia, ANTES de tocar SINU ---------------
            # Regla del proceso (31/08/2026): el Sheet es la fuente de origen
            # del Periodo y tiene que estar abierto antes que ISEF07. Si no, el
            # proceso se detiene: fijar un periodo sin haberlo leido de su
            # fuente es lo que llevaria a vincular matriculas del periodo
            # equivocado.
            pagina_sheet = context.pages[0] if context.pages else context.new_page()
            pagina_sheet.goto(
                args.sheet_url,
                wait_until="domcontentloaded",
                timeout=cfg.timeout_render_seg * 1000,
            )
            pagina_sheet.wait_for_timeout(5000)
            try:
                periodo_sheet = leer_periodo(pagina_sheet, cfg)
                filas_sheet = leer_filas(pagina_sheet, cfg)
            except ErrorSecuencia as exc:
                log.error("PROCESO DETENIDO (regla de secuencia): %s", exc)
                return 1
            except ErrorPeriodoSheet as exc:
                log.error("No se pudo leer el Sheet: %s", exc)
                return 1

            print(f"Sheet abierto        : {pagina_sheet.url[:80]}")
            print(f"Periodo en el Sheet  : {periodo_sheet}")
            print(f"Filas en el Sheet    : {len(filas_sheet)}")

            # --- El lote sale del SHEET, no del .xlsx local ------------------
            # Es la fuente de verdad del proceso: si en el Sheet se corrige un
            # dato o se quita una fila, la automatizacion tiene que seguirlo. Se
            # contrasta contra el plan local y se avisa de las diferencias, que
            # son justo lo que interesa ver.
            del_sheet = [
                f.get(COL_IDENTIFICACION, "")
                for f in filas_sheet
                if f.get(COL_COD_PERIODO, "").strip().upper()
                == args.periodo.strip().upper()
                and f.get(COL_IDENTIFICACION, "").strip()
            ]
            en_sheet = list(dict.fromkeys(del_sheet))  # unicas, en orden
            en_plan = [o.identificacion for o in operaciones]

            solo_plan = [c for c in en_plan if c not in set(en_sheet)]
            solo_sheet = [c for c in en_sheet if c not in set(en_plan)]
            if solo_plan or solo_sheet:
                log.warning(
                    "El Sheet y el plan local no coinciden para '%s'. Solo en el "
                    "plan: %s. Solo en el Sheet: %s. MANDA EL SHEET.",
                    args.periodo,
                    solo_plan[:8] or "ninguna",
                    solo_sheet[:8] or "ninguna",
                )
            # Se conserva el orden del Sheet, que es el que ve el operador.
            orden = {c: i for i, c in enumerate(en_sheet)}
            operaciones = sorted(
                [o for o in operaciones if o.identificacion in orden],
                key=lambda o: orden[o.identificacion],
            )
            print(f"Estudiantes del lote : {len(operaciones)} (segun el Sheet)")
            if not operaciones:
                log.error(
                    "El Sheet no trae ningun estudiante procesable para '%s'.",
                    args.periodo,
                )
                return 2

            # El periodo pedido tiene que ser uno de los del Sheet. Se avisa si
            # no coincide con su primera fila -- puede ser legitimo (se procesa
            # un lote posterior), pero conviene verlo.
            if periodo_sheet.strip().upper() != args.periodo.strip().upper():
                log.warning(
                    "El Periodo pedido ('%s') no es el de la primera fila del "
                    "Sheet ('%s'). Es legitimo si se esta procesando un lote "
                    "posterior, pero conviene comprobar que el Sheet abierto es "
                    "el de hoy.",
                    args.periodo,
                    periodo_sheet,
                )

            # --- PASO 2: SINU en la pestana CONTIGUA -------------------------
            page = context.new_page()
            try:
                abrir_y_acceder(page, cfg)
            except ErrorAccesoSinu as exc:
                log.error("%s", exc)
                return 1

            # Faltaba ABRIR el modulo. Sin esto la corrida se quedaba en #home
            # (la lista de modulos) y ningun estudiante se podia leer: el filtro
            # de cedula no existe ahi. El sintoma enganaba, porque el Periodo SI
            # se fijaba -- su desplegable vive en la barra global y esta visible
            # tambien en el inicio. Comprobado el 01/09/2026: 14 de 14
            # estudiantes "no se pudo leer" por esto.
            try:
                entrar_en_modulo(
                    page, cfg, ACTIVIDAD_VINCULACION, f"procesar el lote {args.periodo}"
                )
            except (ErrorLecturaSinu, ErrorRestriccionOperativa) as exc:
                log.error("No se pudo abrir ISEF07: %s", exc)
                return 1

            fijar_periodo(page, cfg, lote.cod_periodo)

            for i, operacion in enumerate(operaciones, 1):
                cedula = operacion.identificacion
                try:
                    lectura = leer_estudiante(page, cfg, cedula)
                except (EstudianteAmbiguo, ErrorLecturaSinu) as exc:
                    detenidos.append((cedula, str(exc)))
                    log.error("%s: no se pudo leer, se omite. %s", cedula, exc)
                    continue

                secuencia = decidir_secuencia(lectura.grupos)
                minimo, maximo = estimar_segundos(secuencia)
                print(
                    f"[{i}/{len(operaciones)}] {cedula}: {len(lectura.grupos)} materias "
                    f"-> {secuencia.value} ({minimo}-{maximo}s)",
                    flush=True,
                )

                try:
                    r = ejecutar_estudiante(
                        page,
                        cfg_efectiva,
                        identificacion=cedula,
                        cod_periodo=lote.cod_periodo,
                        grupos=lectura.grupos,
                    )
                    hechos.append(r)
                    if r.secuencia is TipoSecuencia.RECICLAR and not r.simulado:
                        reciclados += 1
                except CicloAbierto as exc:
                    # Lo peor que puede pasar: el estudiante quedo desvinculado.
                    abiertos.append(cedula)
                    log.error("%s", exc)
                    print(f"    !! {exc}", flush=True)
                except ErrorEjecucionSinu as exc:
                    detenidos.append((cedula, str(exc)))
                    log.error("%s: %s", cedula, exc)
        except Exception:
            log.exception("Fallo inesperado durante la etapa 4")
            return 1
        finally:
            if ruta_traza is not None:
                context.tracing.stop(path=str(ruta_traza))
                log.info("Traza: playwright show-trace %s", ruta_traza)
            cerrar()

    print()
    print(f"Procesados        : {len(hechos)}/{len(operaciones)}")
    if de_verdad:
        print(f"  reciclados      : {reciclados} (desvincular + vincular)")
    if detenidos:
        print(f"Detenidos         : {len(detenidos)}")
        for cedula, motivo in detenidos[:10]:
            print(f"  {cedula}: {motivo[:90]}")
    if abiertos:
        print()
        print(f"!! {len(abiertos)} ESTUDIANTES QUEDARON DESVINCULADOS: {', '.join(abiertos)}")
        print("   Hay que vincularlos A MANO en ISEF07.")
        print(f"   Registro: {RUTA_CICLOS_ABIERTOS}")
    if _avisar_ciclos_previos():
        pass
    print()
    print(f"Log de la corrida: {archivo_log}")
    return 1 if abiertos else 0


if __name__ == "__main__":
    raise SystemExit(main())
