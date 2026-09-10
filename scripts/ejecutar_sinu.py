"""CLI de la etapa 4: ejecuta la vinculacion en ISEF07. ESCRIBE en el sistema.

Es el unico script del proyecto que modifica matriculas. Tres cerrojos, y hay
que abrir los tres:

1. `MODO_SIMULACION=false` en config/.env.
2. `--ejecutar-de-verdad` en la linea de comandos.
3. `--periodo`, porque el filtro de Periodo se fija una vez por sesion.

Sin los dos primeros el script recorre todo y dice lo que haria, sin tocar nada.

Regla de negocio, sobre LA materia que registra el reporte:
  Vinculado? = False -> Vincular.
  Vinculado? = True  -> Desvincular, confirmar, y despues Vincular.

Unidad de trabajo: **(cedula, materia)**, una operacion por fila del reporte.
Antes del 03/09/2026 este script decia que la accion era "por ESTUDIANTE, no por
materia" y que el reciclado pasaba por todas sus asignaturas. Era falso, venia
de la referencia de negocio, y reciclo 34 asignaturas cuando correspondian 5.
Ahora la grilla Grupos se acota por COD_MATERIA antes de ejecutar, y tras cada
escritura se comprueba que ninguna otra asignatura cambio (`AccionSeDesbordo`).

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
    RUTA_ESCALADO,
    AccionSeDesbordo,
    CheckNoConfirmado,
    CicloAbierto,
    ErrorEjecucionSinu,
    TipoSecuencia,
    ciclos_abiertos,
    decidir_secuencia,
    ejecutar_materia,
    estimar_segundos,
    fila_de_materia,
)
from moodle_sinu.constantes_sinu import MODULOS_DE_ESCALADO  # noqa: E402
from moodle_sinu import diario_resultados as diario  # noqa: E402
from moodle_sinu.lector_reporte import ErrorEstructuraReporte  # noqa: E402
from moodle_sinu.constantes_sinu import ACTIVIDAD_VINCULACION  # noqa: E402
from moodle_sinu.lector_sinu import (  # noqa: E402
    ErrorLecturaSinu,
    EstudianteAmbiguo,
    entrar_en_modulo,
    fijar_periodo,
    filtrar_grupos_por_materia,
    leer_estudiante,
    limpiar_filtro_de_materia,
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
    p.add_argument(
        "--saltar-hechas",
        action="store_true",
        help="Omite las unidades (cedula, materia) que el diario de resultados ya "
        "tiene en VERDE. Es lo que hace reanudable una corrida interrumpida: sin "
        "esto, volver a lanzar un periodo recicla lo que ya estaba bien, y cada "
        "reciclado innecesario abre una ventana en la que la materia queda "
        "desvinculada.",
    )
    p.add_argument("--visible", action="store_true", help="Navegador con ventana")
    p.add_argument("--traza", action="store_true", help="Traza de Playwright en logs/")
    p.add_argument("--verbose", "-v", action="store_true", help="Log en DEBUG")
    return p.parse_args()


def _releer_todas(page, cfg, cedula: str):
    """La grilla Grupos SIN filtro de materia, para la guarda de desborde.

    El filtro de columna de SmartClient persiste, asi que hay que vaciarlo
    ANTES de volver a leer: si no, la "grilla completa" seguiria mostrando solo
    la materia acotada y la comprobacion de desborde no veria nada.
    """
    limpiar_filtro_de_materia(page, cfg)
    return leer_estudiante(page, cfg, cedula).grupos


def _anotar(operacion, veredicto, motivo: str, detalle: str = "", r=None) -> None:
    """Escribe el resultado de una unidad de trabajo en el diario.

    Se llama en TODOS los desenlaces, incluidos los que no tocan SINU (la
    materia que no esta, la fila sin COD_MATERIA). Si solo se anotaran los
    exitos, el Sheet no podria distinguir "salio mal" de "todavia no se hizo",
    que es justo la diferencia que el operador necesita ver.
    """
    diario.apuntar(
        identificacion=operacion.identificacion,
        cod_periodo=operacion.cod_periodo,
        cod_materia=operacion.cod_materia,
        num_grupo=operacion.num_grupo,
        fila=operacion.fila,
        veredicto=veredicto,
        motivo=motivo,
        detalle=detalle,
        acciones=list(r.acciones_ejecutadas) if r is not None else [],
        segundos=r.segundos if r is not None else 0.0,
    )


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

    if args.saltar_hechas:
        ya = {
            clave
            for clave, apunte in diario.ultimo_por_unidad().items()
            if apunte.get("veredicto") == diario.Veredicto.VERDE.value
        }
        antes_de_saltar = len(operaciones)
        operaciones = [
            o
            for o in operaciones
            if (o.cod_periodo, o.identificacion, o.objetivo) not in ya
        ]
        saltadas = antes_de_saltar - len(operaciones)
        if saltadas:
            log.info(
                "Se omiten %d unidad(es) ya en verde segun %s.",
                saltadas,
                diario.RUTA_RESULTADOS.name,
            )

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

    sin_cabeza = False if args.visible else cfg.powerbi_headless
    sello = datetime.now().strftime("%Y%m%d_%H%M%S")

    hechos: list = []
    reciclados = 0
    abiertos: list[str] = []
    detenidos: list[tuple[str, str]] = []
    #: Se ejecuto la accion y el check no quedo puesto, o ISEF07 no dejo
    #: vincular. Van aparte de `detenidos` porque el siguiente paso es distinto:
    #: consultar ISEF05/PACF50 y anotar el resultado en el Sheet, no reintentar.
    escalados: list[tuple[str, str]] = []

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

            try:
                fijar_periodo(page, cfg, lote.cod_periodo)
            except ErrorLecturaSinu as exc:
                # El periodo del reporte no existe en ISEF07 (paso el 03 y el
                # 04/09/2026 con '26P04'). No se toca nada -- se falla antes de
                # cualquier escritura -- pero SUS UNIDADES HAY QUE REGISTRARLAS
                # IGUAL: sin esto se quedaban fuera del diario, y una fila que
                # no esta en el diario no se pinta en el Sheet. El operador la
                # veria en blanco, indistinguible de "todavia no le toca".
                log.error("No se pudo fijar el periodo %s: %s", lote.cod_periodo, exc)
                for operacion in operaciones:
                    detenidos.append(
                        (operacion.identificacion, f"periodo {lote.cod_periodo}: {exc}")
                    )
                    _anotar(
                        operacion,
                        diario.Veredicto.ROJO,
                        diario.MOTIVO_NO_LEIDO,
                        f"el periodo {lote.cod_periodo} no existe en ISEF07",
                    )
                print()
                print(
                    f"!! El periodo '{lote.cod_periodo}' no existe en el desplegable "
                    f"de ISEF07. Sus {len(operaciones)} fila(s) quedan en ROJO."
                )
                print("   Hay que comprobar el dato en origen; no se toco nada.")
                return 2

            for i, operacion in enumerate(operaciones, 1):
                cedula = operacion.identificacion
                materia = operacion.cod_materia
                grupo = operacion.num_grupo
                objetivo = operacion.objetivo

                if not materia:
                    detenidos.append((cedula, "la fila del reporte no trae COD_MATERIA"))
                    log.error(
                        "%s (fila %s): sin COD_MATERIA, no se sabe que procesar.",
                        cedula,
                        operacion.fila,
                    )
                    _anotar(
                        operacion, diario.Veredicto.ROJO, diario.MOTIVO_NO_LEIDO,
                        "la fila del reporte no trae COD_MATERIA",
                    )
                    continue

                # La grilla COMPLETA: de aqui sale el check de la materia y la
                # foto contra la que se comprueba que la accion no se desborda.
                try:
                    lectura = leer_estudiante(page, cfg, cedula)
                except (EstudianteAmbiguo, ErrorLecturaSinu) as exc:
                    detenidos.append((cedula, str(exc)))
                    log.error("%s: no se pudo leer, se omite. %s", cedula, exc)
                    _anotar(
                        operacion, diario.Veredicto.ROJO, diario.MOTIVO_NO_LEIDO, str(exc)
                    )
                    continue

                secuencia = decidir_secuencia(
                    fila_de_materia(lectura.grupos, materia, grupo)
                )
                minimo, maximo = estimar_segundos(secuencia)
                print(
                    f"[{i}/{len(operaciones)}] {cedula} / {objetivo}: "
                    f"{len(lectura.grupos)} materias en la grilla, se toca 1 "
                    f"-> {secuencia.value} ({minimo}-{maximo}s)",
                    flush=True,
                )

                # Acotar la grilla a ESA materia. Es lo que confina la accion:
                # sin esto ISEF07 alcanza todas las asignaturas del periodo.
                if secuencia is not TipoSecuencia.NADA and not cfg_efectiva.modo_simulacion:
                    try:
                        filtrar_grupos_por_materia(page, cfg, materia)
                    except ErrorLecturaSinu as exc:
                        detenidos.append((cedula, f"no se pudo acotar a {objetivo}: {exc}"))
                        log.error(
                            "%s / %s: no se pudo acotar la grilla, NO se ejecuta. %s",
                            cedula,
                            objetivo,
                            exc,
                        )
                        _anotar(
                            operacion, diario.Veredicto.ROJO, diario.MOTIVO_NO_LEIDO,
                            f"no se pudo acotar la grilla: {exc}",
                        )
                        continue

                try:
                    r = ejecutar_materia(
                        page,
                        cfg_efectiva,
                        identificacion=cedula,
                        cod_periodo=lote.cod_periodo,
                        cod_materia=materia,
                        num_grupo=grupo,
                        grupos=lectura.grupos,
                        # Con la grilla ya acotada, releerla devuelve esa fila.
                        releer_materia=lambda m=materia: filtrar_grupos_por_materia(
                            page, cfg, m
                        ),
                        # Sin filtro: para la guarda de desborde.
                        releer_todas=lambda ced=cedula: _releer_todas(page, cfg, ced),
                    )
                    hechos.append(r)
                    if r.simulado:
                        pass  # en simulacion no se ensucia el diario
                    elif r.secuencia is TipoSecuencia.NADA:
                        # La materia del reporte no esta en la grilla. No es un
                        # fallo tecnico, pero para el Sheet es rojo: esa fila no
                        # se pudo gestionar.
                        _anotar(
                            operacion, diario.Veredicto.ROJO,
                            diario.MOTIVO_SIN_CORRESPONDENCIA, r.detalle, r,
                        )
                    else:
                        _anotar(
                            operacion, diario.Veredicto.VERDE, diario.MOTIVO_OK,
                            f"vinculada y confirmada; {len(r.acciones_ejecutadas)} accion(es)",
                            r,
                        )
                    if r.secuencia is TipoSecuencia.RECICLAR and not r.simulado:
                        reciclados += 1
                    if r.reciclado_incompleto:
                        print(
                            "    (aviso) el desvincular no se reflejo; el vincular "
                            "si quedo confirmado",
                            flush=True,
                        )
                except AccionSeDesbordo as exc:
                    _anotar(
                        operacion, diario.Veredicto.ROJO, diario.MOTIVO_DESBORDE, str(exc)
                    )
                    # El supuesto central falla: acotar la grilla no confina la
                    # accion. Seguir tocaria materias fuera del reporte en cada
                    # estudiante, asi que se corta la corrida entera.
                    log.error("%s", exc)
                    print()
                    print(f"!! {exc}", flush=True)
                    print(
                        "   Se detiene la corrida. Revisar con una pasada "
                        "supervisada antes de volver a ejecutar.",
                        flush=True,
                    )
                    return 2
                except CheckNoConfirmado as exc:
                    # Se ejecuto pero el check no aparecio, o ISEF07 no dejo
                    # vincular. No es un fallo tecnico: es el caso que se valida
                    # en ISEF05/PACF50 y se anota en el Sheet.
                    _anotar(
                        operacion, diario.Veredicto.ROJO,
                        diario.MOTIVO_CHECK_NO_CONFIRMADO, str(exc),
                        r=exc.resultado,
                    )
                    escalados.append((f"{cedula} / {objetivo}", str(exc)))
                    log.error("%s", exc)
                    print(f"    -> ESCALAR a {'/'.join(MODULOS_DE_ESCALADO).upper()}: {exc}", flush=True)
                except CicloAbierto as exc:
                    # Lo peor que puede pasar: el estudiante quedo desvinculado.
                    _anotar(
                        operacion, diario.Veredicto.ROJO,
                        diario.MOTIVO_CICLO_ABIERTO, str(exc),
                    )
                    abiertos.append(f"{cedula} / {objetivo}")
                    log.error("%s", exc)
                    print(f"    !! {exc}", flush=True)
                except ErrorEjecucionSinu as exc:
                    detenidos.append((cedula, str(exc)))
                    log.error("%s: %s", cedula, exc)
                    # No es un escalado: es que la automatizacion no pudo
                    # operar. Anotarlo como 'check-no-confirmado' mandaba a
                    # validar en ISEF05/PACF50 algo que ni se intento.
                    _anotar(
                        operacion, diario.Veredicto.ROJO,
                        diario.MOTIVO_FALLO_TECNICO, str(exc),
                        r=getattr(exc, "resultado", None),
                    )
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
    if escalados:
        print()
        print(
            f"-> {len(escalados)} ESTUDIANTES A VALIDAR EN "
            f"{'/'.join(MODULOS_DE_ESCALADO).upper()}:"
        )
        for cedula, motivo in escalados[:10]:
            print(f"   {cedula}: {motivo[:110]}")
        print(
            "   ISEF07 ejecuto la accion y el check 'Vinculado?' no quedo puesto "
            "(o no dejo vincular)."
        )
        print(
            f"   Hay que abrir {' y '.join(m.upper() for m in MODULOS_DE_ESCALADO)}, "
            "validar el check en Moodle y anotarlo en el Sheet del dia."
        )
        print(f"   Registro: {RUTA_ESCALADO}")
    if abiertos:
        print()
        print(f"!! {len(abiertos)} ESTUDIANTES QUEDARON DESVINCULADOS: {', '.join(abiertos)}")
        print("   Hay que vincularlos A MANO en ISEF07.")
        print(f"   Registro: {RUTA_CICLOS_ABIERTOS}")
    if _avisar_ciclos_previos():
        pass
    print()
    print(f"Log de la corrida: {archivo_log}")
    # Los escalados NO hacen fallar la corrida: son un desenlace previsto que
    # requiere una persona, no un error del robot. Los ciclos abiertos si.
    return 1 if abiertos else 0


if __name__ == "__main__":
    raise SystemExit(main())
