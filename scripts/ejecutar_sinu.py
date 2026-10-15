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
import time
from datetime import date, datetime
from pathlib import Path

# permite ejecutar el script sin instalar el paquete
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from playwright.sync_api import Error as ErrorPlaywright, sync_playwright  # noqa: E402

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
    reiniciar_muestreo_desborde,
    decidir_secuencia,
    ejecutar_materia,
    estimar_segundos,
    fila_de_materia,
)
from moodle_sinu.constantes_sinu import MODULOS_DE_ESCALADO  # noqa: E402
from moodle_sinu.tabla_grupos import UMBRAL_VERIFICACION  # noqa: E402
from moodle_sinu import diario_resultados as diario  # noqa: E402
from moodle_sinu.lector_reporte import ErrorEstructuraReporte  # noqa: E402
from moodle_sinu.lector_pacf50 import consultar_grupo as consultar_pacf50  # noqa: E402
from moodle_sinu.verificacion_grupo import Respuesta, Veredicto, verificar  # noqa: E402
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
from moodle_sinu import grupos_declarados  # noqa: E402
from moodle_sinu import selectores_sinu as sel  # noqa: E402
from moodle_sinu.sesiones_sinu import (  # noqa: E402
    MODULO_PACF50,
    SesionesSinu,
)
from moodle_sinu.navegador import abrir_contexto, parar_playwright  # noqa: E402
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

#: Lecturas seguidas SIN RESULTADO -- vacias o fallidas -- que se toleran antes
#: de dar la pantalla por muerta y detener el lote.
#:
#: Cuentan las dos cosas porque el 25/09/2026 el mismo problema dio dos sintomas
#: distintos: por la manana, 29 estudiantes seguidos leidos con "0 asignaturas";
#: por la tarde, 26 seguidos con "el filtro de 'No. Identificacion' sigue
#: DESHABILITADO tras 120s". Vigilar solo el primero dejo pasar el segundo.
#:
#: Tres, y no una: un estudiante sin asignaturas en el periodo existe de verdad,
#: y una lectura puede fallar por su cuenta. Tres seguidas ya no es casualidad.
#:
#: Al llegar aqui se PARA -- no se reabre SINU. Regla del dueno del proceso
#: (25/09/2026): todo el reporte va en la misma sesion. Y las filas que quedan se
#: dejan sin marcar: de ellas no se sabe nada, y un rojo falso es peor que un
#: hueco. Los 26 rojos de esa tarde decian "no tiene esa matricula" sobre
#: estudiantes que la tenian.
VACIAS_PARA_PARAR = 3

#: A partir de cuantas filas un grupo se verifica en PACF50 ANTES de procesarlo
#: (en ISEF05 hasta el 06/10/2026).
#:
#: Regla del dueno del proceso (25/09/2026):
#:
#:   > Si ves que un grupo sale ciento veinte veces en un reporte en el que nos
#:   > estamos demorando diez horas, no tiene sentido que hagas las ciento
#:   > veinte. Lo primero que tienes que hacer es entrar a verificar eso.
#:
#: Es la economia del reporte, medida ese dia: 515 filas procesables son solo
#: **45 grupos distintos**, y estan concentradisimas.
#:
#:     POS01/57ES6  120 filas   23% del reporte
#:     POS01/55ES2   95              42% acumulado
#:     POS01/55ES5   65              54%
#:     POS01/55ES1   60              66%
#:     TI001/55577   45              75%
#:     POS01/55ES6   44              83%
#:     ... y 30 grupos de UNA sola fila
#:
#: Seis consultas deciden el 83% del dia. Tener curso en MOODLE es propiedad del
#: GRUPO -- el shortname del curso es 'COD_MATERIA/NUM_GRUPO' --, asi que la
#: pregunta se hace una vez y vale para sus 120 filas.
#:
#: Esto NO es volver a la consulta previa que habia hasta el 25/09. Aquella
#: preguntaba por los 45 grupos, incluidos los 30 de una fila, y pagaba el precio
#: siempre. Esta pregunta solo por los que mueven el dia.
#:
#: El valor vive en `tabla_grupos` y se importa: es el mismo numero que usa la
#: tabla dinamica que el operador mira antes de empezar, y si los dos sitios
#: discreparan, el informe prometeria un plan distinto del que se ejecuta.
FILAS_PARA_VERIFICAR_GRUPO = UMBRAL_VERIFICACION


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
    p.add_argument(
        "--excluir-grupo",
        action="append",
        default=None,
        metavar="MATERIA/GRUPO",
        help="No procesa las filas de este grupo (se puede repetir). Para cuando "
        "un grupo concentra tantas filas que no compensa procesarlo -- la "
        "decision es del dueno del proceso, no del codigo. Las filas excluidas "
        "no se tocan y no se anotan: quedan como estaban.",
    )
    p.add_argument(
        "--sin-consultar-pacf50",
        action="store_true",
        help="No verifica grupos en PACF50, ni antes del lote ni cuando una fila "
        "falla. El lote se procesa entero por ISEF07. Para cuando la 50 no "
        "responda. (ISEF05 ya no se consulta: retirada el 06/10/2026.)",
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


def _volver_al_navegador_07(
    sesiones: SesionesSinu, cfg, desde: str, cod_periodo: str = ""
) -> None:
    """Pone al frente el navegador de ISEF07 y exige que su grilla siga viva.

    Si no responde, se REABRE SINU en ese navegador (hasta `MAX_REAPERTURAS_07`
    por lote) y se sigue. Pasado el tope tampoco se para: se avisa y el lote
    continua (regla del 28/09/2026: terminar el reporte).

    Desde el 28/09/2026 la 07 NO navega: tiene su propio navegador y nunca sale
    de ISEF07, asi que no hay `#home` que repinte nada. La comprobacion se
    conserva porque no esta medido si SINU admite tres sesiones del mismo
    usuario a la vez: si abrir la de la 05 o la 50 cerrara la de la 07, se sabe
    aqui en `SEG_COMPROBAR_GRILLA_VIVA` segundos, y no tras tres lecturas vacias
    de 124 s cada una.

    Raises:
        GrillaInerte: si el filtro de cedula no acepta texto.
    """
    page = sesiones.volver_a_isef07()
    if _grilla_viva(page, cfg):
        return
    print(
        f"!! Tras verificar {desde}, la grilla de ISEF07 no responde "
        f"({SEG_COMPROBAR_GRILLA_VIVA:.0f}s).",
        flush=True,
    )
    if not cod_periodo:
        raise GrillaInerte(f"Tras verificar {desde}, la grilla de ISEF07 no responde.")
    if sesiones.reaperturas_07 >= MAX_REAPERTURAS_07:
        print(
            f"   Ya se reabrio SINU {sesiones.reaperturas_07} vez/veces en este lote; "
            "se sigue sin reabrir.",
            flush=True,
        )
        return
    sesiones.reaperturas_07 += 1
    print(
        f"   Se reabre SINU en el navegador de la 07 "
        f"({sesiones.reaperturas_07} de {MAX_REAPERTURAS_07}) y se sigue.",
        flush=True,
    )
    _reabrir_07(page, cfg, cod_periodo)


def _consultar(sesiones: SesionesSinu, cfg, modulo: str, consulta, **kw) -> Respuesta:
    """Una consulta de solo lectura en el navegador de `modulo`.

    Devuelve (tiene_curso, detalle, grupo_existe). Un fallo al ABRIR la sesion
    de ese modulo es un "no contesto", igual que un fallo de la consulta: no
    saber NO es no tener curso, y nunca descarta. Y es de ESE modulo: no dice
    nada de los otros dos.

    Se cronometra cada consulta y queda en el log, por modulo: los tiempos de la
    07, la 05 y la 50 son distintos y relativos, y los plazos de cada lector se
    ajustan con lo medido, no con lo supuesto.
    """
    objetivo = f"{kw.get('cod_materia')}/{kw.get('num_grupo')}"
    t0 = time.monotonic()
    try:
        r = consulta(sesiones.pagina(modulo), cfg, **kw)
        seg = time.monotonic() - t0
        log.info(
            "%s contesto por %s (%s) en %.1fs: %s",
            modulo.upper(), objetivo, kw.get("cod_periodo"), seg, r.resumen(),
        )
        return (not r.vincular_es_imposible, r.resumen(), getattr(r, "existe", None))
    except (ErrorAccesoSinu, ErrorLecturaSinu, ErrorRestriccionOperativa, ErrorPlaywright) as exc:
        # ErrorPlaywright: el 30/09/2026 un clic de la 05 sobre el Periodo lo
        # tapo una capa modal de SmartClient y el TimeoutError crudo tumbo el
        # lote entero de 26P05 sin llegar a la 07. Es un "no contesto" mas.
        seg = time.monotonic() - t0
        log.warning(
            "%s NO contesto por %s (%s) tras %.1fs: %s",
            modulo.upper(), objetivo, kw.get("cod_periodo"), seg, exc,
        )
        return (None, f"no contesto en {seg:.0f}s: {str(exc)[:120]}", None)


def _verificar_grupos_en_lote(
    sesiones: SesionesSinu,
    cfg,
    *,
    cod_periodo: str,
    grupos: list[tuple[str, int]],
    ofertas: dict[str, tuple[str, str]] | None = None,
) -> dict[str, Veredicto]:
    """Verifica VARIOS grupos en la 50 (PACF50), uno detras de otro.

    `ofertas` da, por shortname, el (COD_UNIDAD, COD_PENSUM) de sus filas: la 50
    los usa para pulsar la oferta correcta de la asignatura.

    Devuelve {shortname: Veredicto}. Un veredicto con `tiene_curso is None`
    significa "no lo se", que NO es "no tiene curso": la direccion segura es
    seguir procesando por ISEF07.

    La 50 se consulta en SU navegador, con su sesion (ver `sesiones_sinu`), y el
    de la 07 no se mueve: compartir pantalla dejaba los filtros de la 07
    deshabilitados (28/09/2026). La 05 ya no se consulta (06/10/2026, ver
    `verificacion_grupo`).

    Raises:
        GrillaInerte: si al terminar la grilla de ISEF07 no responde.
    """
    respuestas: dict[str, Veredicto] = {}
    try:
        # Que un grupo no conteste no cancela los demas: cada uno decide sus
        # propias filas.
        for objetivo, _n in grupos:
            mat, _, gru = objetivo.partition("/")
            if not gru:
                continue
            unidad, pensum = (ofertas or {}).get(objetivo, ("", ""))
            respuesta = _consultar(
                sesiones, cfg, MODULO_PACF50, consultar_pacf50,
                cod_periodo=cod_periodo, cod_materia=mat, num_grupo=gru,
                cod_unidad=unidad, cod_pensum=pensum,
            )
            respuestas[objetivo] = verificar(objetivo, lambda r=respuesta: r)
    finally:
        # La 07 al frente y comprobada, haya contestado quien haya contestado.
        _volver_al_navegador_07(sesiones, cfg, f"{len(grupos)} grupo(s)", cod_periodo)

    return respuestas


class GrillaInerte(RuntimeError):
    """La pantalla de ISEF07 dejo de responder y no se puede seguir.

    No es un fallo de una fila: es que la sesion ya no sirve. Se distingue para
    que el lote se detenga con las filas restantes SIN marcar -- marcarlas seria
    inventarse 26 rojos, que es lo que paso el 25/09/2026 por la tarde.
    """


#: Cuanto se espera a que el filtro de cedula vuelva a aceptar texto al volver
#: de ISEF05. Corto a proposito: aqui no se esta esperando a que ISEF07 termine
#: un trabajo -- no hay ninguno en curso --, se esta comprobando si la pantalla
#: quedo viva o inerte. Los 120 s de `SEG_ESPERA_CAMPO_EDITABLE` son para lo
#: primero; gastarlos aqui es lo que convirtio el fallo de hoy en 52 minutos.
SEG_COMPROBAR_GRILLA_VIVA = 15.0


def _grilla_viva(page, cfg) -> bool:
    """True si el filtro de cedula de ISEF07 acepta texto ahora mismo."""
    limite = time.monotonic() + SEG_COMPROBAR_GRILLA_VIVA
    campo = page.locator(sel.CSS_FILTRO_CEDULA).first
    while time.monotonic() < limite:
        try:
            if campo.is_editable():
                return True
        except Exception:  # noqa: BLE001 - no poder mirarlo es no estar viva
            pass
        page.wait_for_timeout(1000)
    return False


def motivo_sin_curso(
    objetivo: str,
    por_pacf50: dict,
    por_isef07: set[str],
) -> str | None:
    """Si ya consta que ese grupo no tiene curso en MOODLE, el motivo. None si no.

    Dos fuentes dicen lo mismo y se distinguen a proposito en el texto, porque
    al operador le cambia donde mirar: PACF50 lo contesto al verificar el grupo,
    mientras que ISEF07 lo enseno al leer a un estudiante anterior DEL MISMO
    shortname. El remedio es el unico que hay en los dos casos -- crear el
    curso en MOODLE -- pero la evidencia no esta en el mismo sitio.

    Se prefiere PACF50 cuando estan las dos: es la fuente que el proceso
    considera autoritativa para esta pregunta, y trae su propio resumen.

    Funcion pura para poder probarla: el bucle de `main` abre navegadores, y la
    regla de "un grupo sin curso lo es para todas sus filas" no necesita
    ninguno.
    """
    imposible = por_pacf50.get(objetivo)
    if imposible is not None:
        return f"no tiene curso en MOODLE segun PACF50 ({imposible.resumen()})"
    if objetivo in por_isef07:
        return (
            "no tiene el check 'Curso en moodle?' en ISEF07, visto al leer una "
            "fila anterior del mismo grupo"
        )
    return None


def indizar_por_shortname(operaciones: list) -> dict[str, list[int]]:
    """{shortname: posiciones que ocupa en el lote}, en el orden definitivo.

    El shortname es 'COD_MATERIA/NUM_GRUPO' -- `operacion.objetivo` --, que es
    como se llama el curso en MOODLE. La materia SOLA no vale como clave:
    TI010/55570 y TI010/55571 son dos cursos distintos, y confundirlos saltaria
    trabajo que si se puede hacer.

    Las filas sin COD_MATERIA quedan fuera: no tienen shortname que agrupar, y
    el bucle las cierra antes por su propio camino.
    """
    indice: dict[str, list[int]] = {}
    for pos, o in enumerate(operaciones):
        if o.cod_materia:
            indice.setdefault(o.objetivo, []).append(pos)
    return indice


#: Veces que se reabre SINU en el navegador de la 07 dentro de un lote cuando la
#: pantalla deja de responder. Regla del dueno del proceso (28/09/2026): "no
#: detengas el proceso; si falla, continua hasta terminar el reporte". Pasado el
#: tope ya no se reabre, pero el lote SIGUE: las filas que no se puedan leer
#: quedan en rojo y el reporte se termina igual.
MAX_REAPERTURAS_07 = 3


def _reabrir_07(page, cfg, cod_periodo: str) -> bool:
    """Reabre SINU en la MISMA pagina de la 07: login, ISEF07 y el periodo.

    Es la cura de la pantalla inerte (el filtro deshabilitado, lecturas vacias
    en serie): la aplicacion de SmartClient se recarga de cero. Devuelve True si
    al terminar la grilla vuelve a aceptar texto.
    """
    log.warning("Reabriendo SINU en el navegador de la 07 (periodo %s).", cod_periodo)
    try:
        abrir_y_acceder(page, cfg)
        entrar_en_modulo(
            page, cfg, ACTIVIDAD_VINCULACION, "reabrir ISEF07 tras pantalla sin respuesta"
        )
        fijar_periodo(page, cfg, cod_periodo)
    except (ErrorAccesoSinu, ErrorLecturaSinu, ErrorRestriccionOperativa) as exc:
        log.error("No se pudo reabrir SINU en la 07: %s", exc)
        return False
    viva = _grilla_viva(page, cfg)
    log.warning("SINU reabierto en la 07: grilla %s.", "VIVA" if viva else "sigue sin responder")
    return viva


def ofertas_por_shortname(operaciones: list) -> dict[str, tuple[str, str]]:
    """{shortname: (COD_UNIDAD, COD_PENSUM)}, el par mas frecuente de sus filas.

    Un grupo es de una oferta (programa + pensum), y la 50 necesita esa oferta
    para pulsar la fila correcta de la asignatura. Si las filas de un mismo
    shortname trajeran pares distintos, gana el mas repetido; con empate, el
    de la primera fila.
    """
    conteo: dict[str, dict[tuple[str, str], int]] = {}
    for o in operaciones:
        if not o.cod_materia:
            continue
        par = (getattr(o, "cod_unidad", "") or "", getattr(o, "cod_pensum", "") or "")
        por_par = conteo.setdefault(o.objetivo, {})
        por_par[par] = por_par.get(par, 0) + 1
    return {
        sn: max(pares, key=lambda p: pares[p])  # max conserva el primero si empatan
        for sn, pares in conteo.items()
    }


def grupos_a_verificar(
    indice: dict[str, list[int]], minimo: int = FILAS_PARA_VERIFICAR_GRUPO
) -> list[tuple[str, int]]:
    """Los grupos que mueven el lote, de mayor a menor. [(shortname, filas)].

    Solo los que llegan a `minimo` filas. Son los que hay que verificar ANTES de
    procesar nada: uno de ellos decide decenas de filas, y descubrirlo al fallar
    la fila 40 cuesta horas que ya no se recuperan.

    Funcion pura -- el bucle de `main` abre navegadores y esta decision no
    necesita ninguno.
    """
    return sorted(
        ((k, len(v)) for k, v in indice.items() if len(v) >= minimo),
        key=lambda kv: (-kv[1], kv[0]),
    )


def filas_a_cortocircuitar(
    indice: dict[str, list[int]],
    objetivo: str,
    desde: int,
    ya_cerradas: set[int],
) -> list[int]:
    """Las filas que hay que cerrar en lote al bloquearse `objetivo`.

    Funcion pura, y por eso esta fuera de `main`: es la regla del cortocircuito
    (Regla B, 25/09/2026) y el bucle de `main` abre navegadores, asi que sin
    esto la unica regla nueva del dia se quedaria sin probar.

    Tres condiciones, y las tres importan:

      - Solo filas POSTERIORES a `desde`. La fila que fallo ya tiene su apunte,
        con su motivo propio, y pisarlo perderia la unica de la que consta que
        se intento de verdad.
      - Solo las que no se hayan cerrado ya, para no anotar dos veces la misma.
      - Solo las del shortname exacto, por lo mismo que en `indizar_por_shortname`.
    """
    return [
        pos
        for pos in indice.get(objetivo, [])
        if pos > desde and pos not in ya_cerradas
    ]


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

    if args.excluir_grupo:
        # Decision del dueno del proceso, no del codigo: hay grupos que
        # concentran tantas filas del reporte que no compensa procesarlos, y esa
        # es una decision de alcance del dia. `POS01/57ES6` el 25/09/2026 eran
        # 120 de 515 filas -- el 23% del reporte en un solo grupo.
        #
        # Las filas excluidas NO se anotan en el diario. Quedan exactamente como
        # estaban: no se intentaron, y decir cualquier otra cosa de ellas seria
        # inventarselo. Lo que se escriba sobre ellas en el Sheet se decide al
        # marcar, no aqui.
        fuera = {g.strip().upper() for g in args.excluir_grupo if g.strip()}
        antes_de_excluir = len(operaciones)
        operaciones = [o for o in operaciones if o.objetivo.upper() not in fuera]
        excluidas = antes_de_excluir - len(operaciones)
        log.info(
            "Se excluyen %d fila(s) de %s por peticion expresa.",
            excluidas,
            ", ".join(sorted(fuera)),
        )
        print()
        print(f"EXCLUIDOS: {', '.join(sorted(fuera))} -> {excluidas} fila(s) NO se procesan.")

    if args.saltar_hechas:
        ya = {
            clave
            # Solo los verdes de HOY: no depender de que el diario se rotara.
            for clave, apunte in diario.ultimo_por_unidad(date.today()).items()
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
    #: Unidades que no se intentaron porque PACF50 dijo que su grupo no tiene
    #: curso en MOODLE. No son un fallo de la corrida: son trabajo que no se
    #: puede hacer hasta que alguien cree el curso.
    sin_curso_hechas: list[str] = []

    #: Grupos 'MATERIA/GRUPO' que la propia grilla de ISEF07 enseno SIN el check
    #: 'Curso en moodle?'. Es la misma verdad que trae ISEF05, pero descubierta
    #: sobre la marcha, y hace falta porque la consulta previa no siempre
    #: contesta: cuando ISEF05 falla por un grupo, sus filas se procesaban una a
    #: una hasta el final del lote, leyendo ~20s por estudiante para llegar
    #: siempre al mismo rojo.
    #:
    #: Tener curso en MOODLE es propiedad del GRUPO, no del estudiante: el
    #: shortname del curso es 'COD_MATERIA/NUM_GRUPO'. Asi que la primera fila
    #: que lo evidencia decide por todas las demas del mismo shortname.
    sin_curso_isef07: set[str] = set()

    #: CORTOCIRCUITO POR SHORTNAME (regla del dueno del proceso, 25/09/2026).
    #:
    #: Shortnames 'MATERIA/GRUPO' que ya gastaron su unico intento en esta
    #: corrida y acabaron en ISEF05/PACF50. Las filas que queden del mismo
    #: shortname NO se abren en SINU: se marcan en lote y se sigue.
    #:
    #: Vive solo en memoria, y eso es deliberado: lo que se sabe es "este grupo
    #: fallo HOY", no "este grupo esta roto". Persistirlo convertiria un fallo de
    #: una tarde en un veto permanente, y el grupo se arregla creando el curso en
    #: MOODLE -- un cambio que el archivo no se enteraria de que ocurrio.
    #:
    #: Por que basta UN fallo para bloquear el grupo: el check "Vinculado?" no
    #: aparece por causas del GRUPO (sin curso en MOODLE, sin usuarios, sin curso
    #: semilla), no del estudiante. `DTA32/55598` es el caso medido: los cuatro
    #: estudiantes fallaron identicamente el 07, el 15 y el 16/09/2026.
    #:
    #: Y el riesgo de equivocarse esta acotado a proposito: bloquear un grupo NO
    #: escribe nada en SINU, solo deja de escribir. Si al validar en ISEF05 el
    #: grupo resulta sano, sus filas se reprocesan y ya esta -- SINU quedo como
    #: estaba. El error contrario (seguir intentando) si cuesta: ~300 s por fila.
    shortnames_bloqueados: set[str] = set()

    #: Filas cerradas por el cortocircuito, sin tocar el navegador.
    cortocircuitadas: list[str] = []

    #: Lecturas seguidas que no dieron nada util -- ni asignaturas, ni siquiera
    #: una lectura que terminara. Ver el cortafuegos de la grilla inerte.
    lecturas_vacias = 0

    # start() y no `with`: si el navegador murio, SALIR del `with` lanza
    # `InvalidStateError` y se lleva por delante un trabajo ya hecho.
    # Ver `navegador.parar_playwright` (medido el 26/09/2026).
    pw = sync_playwright().start()
    try:
        context, cerrar = abrir_contexto(pw, cfg, sin_cabeza)
        ruta_traza = None
        if args.traza:
            DIR_LOGS.mkdir(parents=True, exist_ok=True)
            ruta_traza = DIR_LOGS / f"traza_etapa4_{sello}.zip"
            context.tracing.start(screenshots=True, snapshots=True, sources=True)

        sesiones: SesionesSinu | None = None
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

            # Este navegador es el de ISEF07 y no sale de ahi en todo el lote. La
            # 50 tiene navegador y sesion propios (ver `SesionesSinu`, mas
            # abajo): pasar por ella en ESTA pantalla es lo que dejaba la grilla
            # de ISEF07 inerte.
            sin_curso: dict[str, Veredicto] = {}

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

            # Tres navegadores, cada uno con su sesion de SINU (28/09/2026): este
            # se queda en ISEF07 todo el lote; la 05 y la 50 tienen los suyos,
            # que se abren la primera vez que hacen falta. Ver `sesiones_sinu`.
            sesiones = SesionesSinu(pw, cfg, page, sin_cabeza=sin_cabeza)
            periodo_07 = lote.cod_periodo

            # --- INDICE POR SHORTNAME, antes de tocar la primera fila --------
            # Se construye una vez, sobre el orden definitivo de `operaciones`
            # (ya filtrado por --cedula/--saltar-hechas/--limite y ya reordenado
            # segun el Sheet). De aqui sale, cuando un shortname se bloquea, la
            # lista exacta de filas que quedan por delante con ese mismo grupo,
            # sin volver a recorrer el lote.
            # La muestra de desborde empieza de cero en cada lote: cada lote fija
            # su propio periodo y su propia pantalla, y es de la pantalla de lo
            # que la guarda desconfia.
            reiniciar_muestreo_desborde()

            indice_shortname = indizar_por_shortname(operaciones)
            ofertas = ofertas_por_shortname(operaciones)

            #: Posiciones ya cerradas en lote por el cortocircuito. El bucle las
            #: salta: su apunte en el diario ya esta escrito.
            cerradas_en_lote: set[int] = set()

            repetidos = {k: v for k, v in indice_shortname.items() if len(v) > 1}
            print()
            print(
                f"Shortnames distintos : {len(indice_shortname)} para "
                f"{len(operaciones)} fila(s)."
            )
            if repetidos:
                # Lo que el cortocircuito puede llegar a ahorrar hoy: cada fila
                # evitada son ~300 s (ejecucion en ISEF07 + sondeo del check +
                # lectura del estudiante) que no se gastan.
                ahorrables = sum(len(v) - 1 for v in repetidos.values())
                print(
                    f"  {len(repetidos)} grupo(s) con varias filas -> hasta "
                    f"{ahorrables} fila(s) se cortocircuitarian si su grupo falla."
                )

            #: Por que se bloqueo cada shortname. Casi siempre "sin curso"; desde
            #: el 28/09/2026 tambien "el grupo no existe en SINU", que va al
            #: Sheet con su etiqueta y en FUCSIA.
            motivo_bloqueo: dict[str, str] = {}

            def _descartar_sin_curso(
                objetivo_roto: str,
                desde: int,
                evidencia: str,
                motivo: str | None = None,
            ) -> int:
                """Descarta EN LOTE las filas de un grupo que NO tiene curso en MOODLE
                -- o, con `motivo=MOTIVO_GRUPO_NO_EXISTE`, cuyo grupo no existe.

                Solo se llama cuando PACF50 lo ha confirmado, o cuando la propia
                grilla de ISEF07 enseno la materia sin el check 'Curso en
                moodle?'. Nunca "por si acaso": descartar un grupo sano deja sin
                hacer trabajo que si se podia hacer.

                Van al Sheet como **'NO TIENE CHECK EN MOODLE'**, que es lo que
                pidio el dueno del proceso. No es un escalado: no hay nada que
                validar a mano -- hay que CREAR el curso en MOODLE, y hasta que
                exista, vincular no puede salir bien.

                `desde` es la posicion (0-based) de la fila que lo destapo: solo
                se cierran las POSTERIORES, porque esa ya tiene su propio apunte
                y pisarlo perderia la unica de la que consta que se intento.

                Devuelve cuantas se cerraron.
                """
                motivo = motivo or motivo_bloqueo.get(
                    objetivo_roto, diario.MOTIVO_SIN_CURSO_MOODLE
                )
                motivo_bloqueo.setdefault(objetivo_roto, motivo)
                shortnames_bloqueados.add(objetivo_roto)
                pendientes = filas_a_cortocircuitar(
                    indice_shortname, objetivo_roto, desde, cerradas_en_lote
                )
                if motivo == diario.MOTIVO_GRUPO_NO_EXISTE:
                    texto = (
                        f"{objetivo_roto}: el grupo NO EXISTE en SINU "
                        f"({evidencia[:150]}). No se intento."
                    )
                else:
                    texto = (
                        f"{objetivo_roto} no tiene curso en MOODLE "
                        f"({evidencia[:150]}). Vincular es imposible hasta que "
                        "el curso exista; no se intento."
                    )
                for pos in pendientes:
                    cerradas_en_lote.add(pos)
                    otra = operaciones[pos]
                    if de_verdad:
                        # En simulacion NO se apunta, igual que en el resto del
                        # bucle: el diario pinta el Sheet del dia y un ensayo no
                        # puede dejar rojos de verdad en el.
                        _anotar(otra, diario.Veredicto.ROJO, motivo, texto)
                    sin_curso_hechas.append(f"{otra.identificacion} / {objetivo_roto}")
                    cortocircuitadas.append(f"{otra.identificacion} / {objetivo_roto}")
                if pendientes:
                    print(
                        f"    -> {objetivo_roto} descartado: {len(pendientes)} "
                        f"fila(s) mas del mismo grupo se cierran sin tocar SINU"
                        + ("" if de_verdad else " (ensayo: no se apunta)"),
                        flush=True,
                    )
                return len(pendientes)

            def _preguntar_y_decidir(
                objetivo_roto: str, mat: str, gru: str, pos: int, causa: str
            ) -> bool:
                """Tras un fallo: pregunta a PACF50 y decide si el grupo se descarta.

                Es el nucleo de la regla de orden del 25/09/2026. Antes, cualquier
                fallo bloqueaba el shortname a ciegas, y eso fue un error medido:
                ese mismo dia se cerraron 68 filas de POS01/55ES2 y POS01/57ES6
                como "validar a mano" y los dos grupos estaban SANOS -- uno tenia
                la materia todavia vinculada (el check no habia refrescado) y el
                otro se reparo con un solo vincular en 44,8 s. Eran fallos del
                momento, no del grupo.

                Ahora quien decide es PACF50, que es quien lo sabe (desde el
                06/10/2026 la 05 ya no se consulta):

                  - dice que el grupo NO existe o que NO hay curso -> el grupo se
                    descarta entero. Sus filas van al Sheet con ese motivo, que
                    es lo que hay que arreglar, no algo que validar.
                  - dice que SI hay curso, o no contesta -> el grupo NO se toca.
                    El fallo era de esta fila; la siguiente se procesa normal.

                Devuelve True si el grupo quedo descartado.
                """
                if args.sin_consultar_pacf50 or not gru:
                    return False

                # En su navegador, con el periodo, programa y pensum de ESTA
                # fila. Que la fila fallara en la 07 no dice nada de la 50.
                fila_rota = operaciones[pos - 1]
                consulta = dict(
                    cod_periodo=fila_rota.cod_periodo or lote.cod_periodo,
                    cod_materia=mat,
                    num_grupo=gru,
                )

                def _con_la_50():
                    return _consultar(
                        sesiones, cfg, MODULO_PACF50, consultar_pacf50, **consulta,
                        cod_unidad=fila_rota.cod_unidad, cod_pensum=fila_rota.cod_pensum,
                    )

                try:
                    v = verificar(objetivo_roto, _con_la_50)
                finally:
                    # La 07 al frente y comprobada, haya contestado quien haya
                    # contestado. No navega: nunca salio de ISEF07.
                    _volver_al_navegador_07(
                        sesiones, cfg, objetivo_roto, consulta["cod_periodo"]
                    )

                if not v.descartar_grupo:
                    log.info(
                        "No se descarta %s (%s): el fallo de %s fue de la fila, "
                        "no del grupo. Se sigue.",
                        objetivo_roto, v.resumen(), causa,
                    )
                    print(
                        f"    -> {v.resumen()}. No se bloquea; "
                        "se sigue con la siguiente fila.",
                        flush=True,
                    )
                    return False

                if v.grupo_inexistente:
                    print(
                        f"    -> {objetivo_roto}: el GRUPO NO EXISTE en SINU segun "
                        "PACF50. Se descarta el grupo entero (FUCSIA).",
                        flush=True,
                    )
                    _descartar_sin_curso(
                        objetivo_roto, pos - 1, v.resumen(),
                        motivo=diario.MOTIVO_GRUPO_NO_EXISTE,
                    )
                    return True

                sin_curso[objetivo_roto] = v
                print(
                    f"    -> {objetivo_roto} SIN check de MOODLE segun "
                    f"{v.fuente.value}. Se descarta el grupo entero.",
                    flush=True,
                )
                _descartar_sin_curso(objetivo_roto, pos - 1, v.resumen())
                return True

            # --- PASO 5.5: VERIFICAR LOS GRUPOS QUE MUEVEN EL LOTE -----------
            # Regla del dueno del proceso (25/09/2026): un grupo que sale 120
            # veces es UNA pregunta, no 120. Se verifica ANTES de procesar nada,
            # porque descubrir al fallar la fila 40 que el grupo no tenia curso
            # cuesta horas que ya no se recuperan.
            # --- GRUPOS DECLARADOS A MANO: no existen en SINU --------------
            # Revision manual del dueno del proceso (config/grupos_no_existen.txt).
            # Se marcan en FUCSIA sin consultarlos ni procesarlos, ANTES de la
            # verificacion: no tiene sentido preguntar lo que ya se reviso.
            declarados = grupos_declarados.del_periodo(lote.cod_periodo)
            for objetivo_d, linea_d in declarados.items():
                filas_d = indice_shortname.get(objetivo_d, [])
                if not filas_d:
                    continue
                print(
                    f"  !! {objetivo_d} ({len(filas_d)} filas): declarado a mano "
                    f"como GRUPO NO EXISTE EN SINU ({linea_d}) -> FUCSIA, sin "
                    "consultar ni tocar ISEF07"
                )
                _descartar_sin_curso(
                    objetivo_d, -1,
                    f"declarado a mano por el dueno del proceso: {linea_d}",
                    motivo=diario.MOTIVO_GRUPO_NO_EXISTE,
                )

            grandes = [
                (sn, n)
                for sn, n in grupos_a_verificar(indice_shortname)
                if sn not in shortnames_bloqueados
            ]
            if grandes and not args.sin_consultar_pacf50:
                cubiertas = sum(n for _, n in grandes)
                print()
                print(
                    f"Verificando los {len(grandes)} grupo(s) que mueven el lote "
                    f"({cubiertas} de {len(operaciones)} filas, "
                    f"{cubiertas/len(operaciones)*100:.0f}%)..."
                )
                print("  En PACF50, en su propio navegador; el de ISEF07 no se mueve.")
                respuestas = _verificar_grupos_en_lote(
                    sesiones, cfg,
                    cod_periodo=lote.cod_periodo,
                    grupos=grandes,
                    ofertas=ofertas,
                )
                no_existen = 0
                for objetivo_g, n_filas in grandes:
                    v = respuestas.get(objetivo_g)
                    if v is not None and v.grupo_inexistente:
                        print(
                            f"  !! {objetivo_g}: el GRUPO NO EXISTE en SINU segun "
                            f"PACF50 -> {n_filas} fila(s) en FUCSIA, sin tocar ISEF07"
                        )
                        # -1: aqui no hay ninguna fila procesada todavia, asi que
                        # se cierran TODAS las del grupo.
                        _descartar_sin_curso(
                            objetivo_g, -1, v.resumen(),
                            motivo=diario.MOTIVO_GRUPO_NO_EXISTE,
                        )
                        no_existen += n_filas
                        continue
                    if v is None or v.tiene_curso is None:
                        # No saber NO es no tener curso: se procesa como siempre.
                        detalle = v.detalle[:90] if v is not None else "no se consulto"
                        print(
                            f"  ?  {objetivo_g} ({n_filas} filas): sin respuesta de "
                            f"ninguna, se procesara ({detalle})"
                        )
                        continue
                    if v.descartar_grupo:
                        sin_curso[objetivo_g] = v
                        print(
                            f"  !! {objetivo_g}: SIN check de MOODLE segun "
                            f"{v.fuente.value} -> {n_filas} fila(s) se descartan "
                            "sin tocar ISEF07"
                        )
                        _descartar_sin_curso(objetivo_g, -1, v.resumen())
                    else:
                        print(
                            f"  ok {objetivo_g} ({n_filas} filas): tiene check de "
                            f"MOODLE segun {v.fuente.value}"
                        )
                ahorradas = len(cerradas_en_lote)
                if ahorradas:
                    print()
                    print(
                        f"  {ahorradas} fila(s) descartadas antes de empezar "
                        f"-> ~{ahorradas * 105 // 60} min que no se gastan."
                    )
                    if no_existen:
                        print(
                            f"  {no_existen} de ellas son de grupos que NO EXISTEN en "
                            "SINU: hay que programar el grupo, no reintentar."
                        )
                    if ahorradas > no_existen:
                        print(
                            "  Las sin check NO se arreglan reintentando: hay que "
                            "CREAR el curso en MOODLE."
                        )

            #: Filas de la racha de lecturas vacias/fallidas en curso. Si la
            #: racha llega al tope, se reintentan al final del lote.
            ultimas_vacias: list = []
            reencoladas: set[int] = set()
            #: Grupo -> cedula que quedo desvinculada. No se recicla mas.
            grupos_que_desvincularon: dict[str, str] = {}

            def _recuperar_07(i: int, sintoma: str) -> None:
                """La pantalla de la 07 no responde: reabrir SINU y seguir.

                Nunca para el lote (regla del 28/09/2026). Reabre hasta
                `MAX_REAPERTURAS_07` veces; las filas de la racha se ponen al
                final del lote, una sola vez cada una.
                """
                print()
                print(f"!! {sintoma} (fila {i}): la pantalla de la 07 no responde.", flush=True)
                if sesiones.reaperturas_07 < MAX_REAPERTURAS_07:
                    sesiones.reaperturas_07 += 1
                    print(
                        f"   Se reabre SINU en el navegador de la 07 "
                        f"({sesiones.reaperturas_07} de {MAX_REAPERTURAS_07}) y se sigue.",
                        flush=True,
                    )
                    _reabrir_07(page, cfg, periodo_07)
                else:
                    print(
                        "   Tope de reaperturas alcanzado: se sigue sin reabrir.",
                        flush=True,
                    )
                for op in ultimas_vacias:
                    if id(op) in reencoladas:
                        continue
                    reencoladas.add(id(op))
                    operaciones.append(op)
                    print(
                        f"   {op.identificacion} / {op.objetivo}: se reintenta al "
                        "final del lote.",
                        flush=True,
                    )
                ultimas_vacias.clear()

            for i, operacion in enumerate(operaciones, 1):
                if (i - 1) in cerradas_en_lote:
                    # Ya se cerro en lote al bloquearse su shortname.
                    continue
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

                # El filtro de periodo de la 07 tiene que ser el de ESTA fila.
                # Dentro de un lote todas comparten periodo, asi que casi nunca
                # hace nada; si una fila llegara con otro, se ajusta antes de
                # leer al estudiante en vez de suponer que ya estaba bien.
                if operacion.cod_periodo and operacion.cod_periodo != periodo_07:
                    log.warning(
                        "%s / %s trae el periodo %s y la 07 estaba en %s: se ajusta.",
                        cedula, objetivo, operacion.cod_periodo, periodo_07,
                    )
                    fijar_periodo(page, cfg, operacion.cod_periodo)
                    periodo_07 = operacion.cod_periodo

                # Red de seguridad del cortocircuito. En condiciones normales
                # no salta: al bloquear un shortname se cierran de golpe TODAS
                # sus filas pendientes, asi que estas ya se saltaron arriba por
                # `cerradas_en_lote`. Esta aqui para que la garantia "un grupo
                # bloqueado no vuelve a abrir SINU" no dependa de que el indice
                # y `operaciones` sigan cuadrando si alguien toca el bucle.
                if objetivo in shortnames_bloqueados:
                    log.warning(
                        "%s / %s: el grupo esta bloqueado y la fila no se cerro "
                        "en lote. Se cierra aqui.",
                        cedula,
                        objetivo,
                    )
                    _descartar_sin_curso(objetivo, i - 2, "grupo ya bloqueado")
                    continue

                # Ya se sabe que en este grupo no hay curso en MOODLE, sea
                # porque PACF50 lo dijo antes de empezar o porque la grilla de
                # un estudiante anterior del MISMO shortname lo enseno. No se
                # abre el estudiante siquiera: sin curso no hay nada a lo que
                # vincular, y el sondeo del check daria el mismo NO.
                fuente = motivo_sin_curso(objetivo, sin_curso, sin_curso_isef07)
                if fuente is not None:
                    # En simulacion NO se apunta, igual que con las unidades que
                    # si se procesan: el diario pinta el Sheet del dia, y un
                    # ensayo no puede dejar rojos de verdad en el.
                    if de_verdad:
                        _anotar(
                            operacion,
                            diario.Veredicto.ROJO,
                            diario.MOTIVO_SIN_CURSO_MOODLE,
                            f"{objetivo} {fuente}. Vincular es imposible "
                            "hasta que el curso exista; no se intento.",
                        )
                    sin_curso_hechas.append(f"{cedula} / {objetivo}")
                    print(
                        f"[{i}/{len(operaciones)}] {cedula} / {objetivo}: "
                        "sin curso en MOODLE -> ROJO, no se toca"
                        + ("" if de_verdad else " (ensayo: no se apunta)"),
                        flush=True,
                    )
                    continue

                # La grilla COMPLETA: de aqui sale el check de la materia y la
                # foto contra la que se comprueba que la accion no se desborda.
                try:
                    lectura = leer_estudiante(page, cfg, cedula)
                except EstudianteAmbiguo as exc:
                    # Dos filas para una cedula es un ajuste real de matricula,
                    # no una pantalla muerta: no cuenta para el cortafuegos.
                    lecturas_vacias = 0
                    ultimas_vacias.clear()
                    detenidos.append((cedula, str(exc)))
                    log.error("%s: no se pudo leer, se omite. %s", cedula, exc)
                    _anotar(
                        operacion, diario.Veredicto.ROJO, diario.MOTIVO_NO_LEIDO, str(exc)
                    )
                    continue
                except ErrorLecturaSinu as exc:
                    # ESTO cuenta para el cortafuegos, y es el fallo que se me
                    # escapo el 25/09/2026: yo contaba solo lecturas que volvian
                    # VACIAS, y por la tarde el sintoma fue otro -- "el filtro de
                    # 'No. Identificacion' sigue DESHABILITADO tras 120s", una
                    # excepcion que este mismo `except` se tragaba. El contador
                    # nunca llegaba a verlo: 26 estudiantes seguidos, 52 minutos
                    # y 26 rojos falsos con la pantalla ya muerta.
                    lecturas_vacias += 1
                    detenidos.append((cedula, str(exc)))
                    log.error(
                        "%s: no se pudo leer (%d seguida(s)), se omite. %s",
                        cedula, lecturas_vacias, exc,
                    )
                    _anotar(
                        operacion, diario.Veredicto.ROJO, diario.MOTIVO_NO_LEIDO, str(exc)
                    )
                    ultimas_vacias.append(operacion)
                    if lecturas_vacias >= VACIAS_PARA_PARAR:
                        # No se para (28/09/2026): se reabre SINU y se sigue.
                        _recuperar_07(i, f"{lecturas_vacias} lecturas seguidas fallaron")
                        lecturas_vacias = 0
                    continue

                # --- CORTAFUEGOS DE LA GRILLA INERTE ----------------------
                # Medido el 25/09/2026: a las 10:48:07 la grilla de ISEF07 se
                # quedo inerte y los 29 estudiantes siguientes leyeron "0
                # asignaturas" seguidos, a 42 s cada uno (30 s de clic
                # interceptado). 20 minutos leyendo nada, y cada lectura vacia
                # se anotaba como 'materia-no-esta-en-sinu' -- un ROJO que dice
                # "este estudiante no tiene esa matricula" cuando lo que pasa es
                # que la pantalla esta muerta. 29 rojos falsos.
                #
                # Un estudiante con 0 asignaturas existe (pasa), pero 0 varias
                # veces SEGUIDAS no es una coincidencia: es la pantalla. La
                # cura ya esta en este archivo -- reabrir SINU, lo mismo que se
                # hace al volver de ISEF05 -- asi que se aplica en vez de
                # seguir gastando el lote.
                #
                # OJO con el "0 a 0 de 0": el 28/09/2026 en 26V05 la grilla dijo
                # "cargada: 0 a 0 de 0" para 1000000004 y 1000000005, y minutos
                # despues los mismos estudiantes tenian 8 asignaturas. Un pie
                # cargado NO garantiza que la lectura sea buena, asi que toda
                # lectura vacia cuenta.
                #
                # Y desde esa fecha NO se para el lote (regla del dueno del
                # proceso: "no detengas el proceso; si falla, continua hasta
                # terminar el reporte"). Se reabre SINU en la 07 y las filas
                # vacias de la racha se reintentan al final del lote.
                if lectura.grupos:
                    lecturas_vacias = 0
                    ultimas_vacias.clear()
                else:
                    lecturas_vacias += 1
                    ultimas_vacias.append(operacion)

                if lecturas_vacias >= VACIAS_PARA_PARAR:
                    _recuperar_07(i, f"{lecturas_vacias} estudiantes seguidos con 0 asignaturas")
                    lecturas_vacias = 0
                    # Esta fila ya esta en la cola de reintento: no se anota
                    # ahora un rojo que puede ser de la pantalla.
                    continue

                fila_grilla = fila_de_materia(lectura.grupos, materia, grupo)

                # La grilla acaba de ensenar que esta materia NO tiene el check
                # 'Curso en moodle?'. Vincular es imposible, asi que esta unidad
                # se cierra en rojo sin tocar ISEF07 -- y, sobre todo, se apunta
                # el shortname: las filas que queden del mismo MATERIA/GRUPO no
                # se leeran, porque su respuesta ya se conoce.
                #
                # Un check bloqueado sigue siendo un SI (ver IMG_MARCADO en
                # selectores_sinu): lo que se mira es marcado/desmarcado, no si
                # el control se puede pulsar. Por eso se puede decidir con esto.
                if fila_grilla is not None and not fila_grilla.curso_en_moodle:
                    sin_curso_isef07.add(objetivo)
                    restantes = sum(
                        1 for o in operaciones[i:] if o.objetivo == objetivo
                    )
                    if de_verdad:
                        _anotar(
                            operacion,
                            diario.Veredicto.ROJO,
                            diario.MOTIVO_SIN_CURSO_MOODLE,
                            f"{objetivo} no tiene el check 'Curso en moodle?' en "
                            "la grilla de ISEF07. Vincular es imposible hasta que "
                            "el curso exista; no se intento.",
                        )
                    sin_curso_hechas.append(f"{cedula} / {objetivo}")
                    print(
                        f"[{i}/{len(operaciones)}] {cedula} / {objetivo}: "
                        "sin check 'Curso en moodle?' -> ROJO, no se toca"
                        + (
                            f"; {restantes} fila(s) mas de este grupo se saltaran"
                            if restantes
                            else ""
                        )
                        + ("" if de_verdad else " (ensayo: no se apunta)"),
                        flush=True,
                    )
                    continue

                secuencia = decidir_secuencia(fila_grilla)
                minimo, maximo = estimar_segundos(secuencia)
                print(
                    f"[{i}/{len(operaciones)}] {cedula} / {objetivo}: "
                    f"{len(lectura.grupos)} materias en la grilla, se toca 1 "
                    f"-> {secuencia.value} ({minimo}-{maximo}s)",
                    flush=True,
                )

                # Un grupo que ya dejo a un estudiante DESVINCULADO no se vuelve a
                # reciclar en este lote (28/09/2026: TI002/55524 en 26V05 dejo
                # desvinculados a sus tres estudiantes, uno tras otro -- el
                # desvincular funcionaba y el vincular no devolvia el check).
                # La fila no se toca: se marca para validar a mano y se sigue.
                if secuencia is TipoSecuencia.RECICLAR and objetivo in grupos_que_desvincularon:
                    _anotar(
                        operacion, diario.Veredicto.ROJO,
                        diario.MOTIVO_ESCALADO_VALIDACION_MANUAL,
                        f"No se recicla: en {objetivo} el vincular no devolvio el "
                        f"check a {grupos_que_desvincularon[objetivo]} en este lote. "
                        "No se toco esta matricula; validar el grupo a mano.",
                    )
                    escalados.append((f"{cedula} / {objetivo}", "grupo que desvinculo"))
                    print(
                        f"    -> no se recicla: {objetivo} ya dejo a un estudiante "
                        "desvinculado en este lote. Se marca para validar a mano.",
                        flush=True,
                    )
                    continue

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
                    print(f"    -> no se pudo procesar: {exc}", flush=True)
                    if _preguntar_y_decidir(objetivo, materia, grupo, i, "check no confirmado"):
                        continue
                except CicloAbierto as exc:
                    # Lo peor que puede pasar: el estudiante quedo desvinculado.
                    # Y el grupo ya no se recicla mas en este lote.
                    grupos_que_desvincularon.setdefault(objetivo, cedula)
                    _anotar(
                        operacion, diario.Veredicto.ROJO,
                        diario.MOTIVO_CICLO_ABIERTO, str(exc),
                    )
                    abiertos.append(f"{cedula} / {objetivo}")
                    log.error("%s", exc)
                    print(f"    !! {exc}", flush=True)
                    if _preguntar_y_decidir(objetivo, materia, grupo, i, "quedo desvinculada"):
                        continue
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
        except GrillaInerte as exc:
            # La grilla de la 07 dejo de responder. No se reabre SINU: se para
            # con lo hecho y se avisa. Las filas restantes quedan sin marcar.
            log.error("%s", exc)
            print()
            print(f"!! {exc}", flush=True)
            print(
                "   Relanzar con --saltar-hechas cuando SINU vuelva a responder.",
                flush=True,
            )
            return 2
        except Exception:
            log.exception("Fallo inesperado durante la etapa 4")
            return 1
        finally:
            if ruta_traza is not None:
                context.tracing.stop(path=str(ruta_traza))
                log.info("Traza: playwright show-trace %s", ruta_traza)
            # Los navegadores de la 05 y la 50 se cierran siempre: dejarlos
            # abiertos en una tarea desatendida son dos Edge colgados por lote.
            if sesiones is not None:
                sesiones.cerrar()
            cerrar()

    finally:
        parar_playwright(pw)
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
    if sin_curso_hechas:
        print()
        print(
            f"-> {len(sin_curso_hechas)} UNIDAD(ES) NO SE INTENTARON: su grupo no "
            "tiene curso en MOODLE (PACF50 o la grilla de ISEF07)."
        )
        for linea in sin_curso_hechas[:10]:
            print(f"   {linea}")
        print("   Esto NO se valida ni se reintenta: hay que CREAR el curso en")
        print("   MOODLE. Mientras no exista, vincular es imposible.")
    if cortocircuitadas:
        print()
        print(
            f"-> {len(cortocircuitadas)} FILA(S) CORTOCIRCUITADAS en "
            f"{len(shortnames_bloqueados)} grupo(s) bloqueado(s):"
        )
        for linea in cortocircuitadas[:10]:
            print(f"   {linea}")
        if len(cortocircuitadas) > 10:
            print(f"   ... y {len(cortocircuitadas) - 10} mas")
        print(
            f"   Grupos bloqueados: {', '.join(sorted(shortnames_bloqueados))}"
        )
        print("   NO se abrio SINU para estas filas, asi que SINU quedo como estaba.")
        print(
            f"   Hay que validar el GRUPO en "
            f"{' y '.join(m.upper() for m in MODULOS_DE_ESCALADO)}. Si esta sano, "
            "basta con volver a correr el lote."
        )
        # El ahorro, en la unidad en la que duele: ~300 s por fila evitada
        # (ejecucion en ISEF07 + sondeo de 90 s + lectura del estudiante).
        print(
            f"   Tiempo no gastado: ~{len(cortocircuitadas) * 300 // 60} min."
        )
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
