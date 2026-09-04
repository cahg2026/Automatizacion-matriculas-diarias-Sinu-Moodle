"""Vuelve a vincular las MATERIAS que quedaron desvinculadas a medias.

Cuando un reciclado se corta entre el desvincular y el vincular, esa materia
queda peor que al empezar. `logs/ciclos_abiertos.jsonl` la registra con su
codigo; esto la arregla.

Que se repara, exactamente
--------------------------
La materia del apunte y nada mas. Antes del 03/09/2026 este script vinculaba al
estudiante completo, apoyandose en que "Vincular grupos matriculados" actua
sobre TODAS sus asignaturas, asi que un solo vincular lo dejaba completo. Esa
premisa venia de la referencia de negocio y era falsa: la regla del proceso es
que por la 07 solo se toca el codigo de materia que registre el reporte.

Los apuntes anteriores a esa fecha no dicen QUE materia quedo a medias. No se
adivina: se reportan para revisar a mano. Reparar la materia equivocada seria
tocar una matricula que nadie pidio tocar.

Nunca recicla
-------------
Si la materia ya tiene el check, el apunte se cierra y no se toca nada.
Desvincularla otra vez volveria a abrir la ventana de riesgo sin necesidad, que
es justo lo que este script existe para cerrar. Y si no lo tiene, la decision de
`ejecutar_materia` es SOLO_VINCULAR por construccion.

Se verifica leyendo antes y despues -- con sondeo del check, no una sola
lectura -- y solo se cierra el apunte si esa materia quedo de verdad vinculada.

Uso:
    python scripts/reparar_desvinculados.py --sheet-url URL [--ejecutar-de-verdad]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from playwright.sync_api import sync_playwright  # noqa: E402

from moodle_sinu import registro  # noqa: E402
from moodle_sinu import selectores_sinu_escritura as sesc  # noqa: E402
from moodle_sinu.acceso_sinu import ErrorAccesoSinu, abrir_y_acceder  # noqa: E402
from moodle_sinu.config import Config, asegurar_directorios  # noqa: E402
from moodle_sinu.constantes_sinu import ACTIVIDAD_VINCULACION  # noqa: E402
from moodle_sinu.ejecutor_sinu import (  # noqa: E402
    RUTA_CICLOS_ABIERTOS,
    AccionSeDesbordo,
    ErrorEjecucionSinu,
    _apuntar_ciclo,
    ciclos_abiertos,
    ejecutar_materia,
    fila_de_materia,
)
from moodle_sinu.lector_sinu import (  # noqa: E402
    ErrorLecturaSinu,
    entrar_en_modulo,
    fijar_periodo,
    filtrar_grupos_por_materia,
    leer_estudiante,
    limpiar_filtro_de_materia,
)
from moodle_sinu.navegador import abrir_contexto  # noqa: E402
from moodle_sinu.periodo_sheet import (  # noqa: E402
    ErrorPeriodoSheet,
    ErrorSecuencia,
    leer_periodo,
)
from moodle_sinu.restricciones_sinu import resumen_permisos  # noqa: E402

log = logging.getLogger("reparar")


def _argumentos() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Repara estudiantes desvinculados a medias")
    p.add_argument(
        "--sheet-url",
        required=True,
        help="URL del Google Sheet del dia. Se abre ANTES de SINU, como manda la "
        "regla del proceso.",
    )
    p.add_argument(
        "--ejecutar-de-verdad",
        action="store_true",
        help="Sin esto solo informa de lo que haria.",
    )
    p.add_argument("--visible", action="store_true", help="Navegador con ventana")
    p.add_argument("--verbose", "-v", action="store_true", help="Log en DEBUG")
    return p.parse_args()


def _releer_todas(page, cfg, cedula: str):
    """La grilla Grupos SIN filtro de materia, para la guarda de desborde."""
    limpiar_filtro_de_materia(page, cfg)
    return leer_estudiante(page, cfg, cedula).grupos


def main() -> int:
    args = _argumentos()
    asegurar_directorios()
    archivo_log = registro.configurar(
        logging.DEBUG if args.verbose else logging.INFO, etiqueta="reparar"
    )
    cfg = Config.desde_entorno()

    pendientes = ciclos_abiertos()
    if not pendientes:
        print("No hay ciclos sin cerrar. Nada que reparar.")
        return 0

    de_verdad = args.ejecutar_de_verdad and not cfg.modo_simulacion
    print(f"Ciclos sin cerrar : {len(pendientes)}")
    print(f"Modo              : {'REPARACION REAL' if de_verdad else 'SIMULACION'}")
    print()
    print(resumen_permisos())

    arreglados: list[str] = []
    intactos: list[str] = []
    fallidos: list[tuple[str, str]] = []

    with sync_playwright() as pw:
        context, cerrar = abrir_contexto(pw, cfg, not args.visible)
        try:
            # El Sheet primero, tambien aqui: la regla no tiene excepciones.
            pagina_sheet = context.pages[0] if context.pages else context.new_page()
            pagina_sheet.goto(
                args.sheet_url,
                wait_until="domcontentloaded",
                timeout=cfg.timeout_render_seg * 1000,
            )
            pagina_sheet.wait_for_timeout(5000)
            try:
                print(f"Periodo en el Sheet: {leer_periodo(pagina_sheet, cfg)}")
            except (ErrorSecuencia, ErrorPeriodoSheet) as exc:
                log.error("PROCESO DETENIDO: %s", exc)
                return 1

            page = context.new_page()
            try:
                abrir_y_acceder(page, cfg)
                entrar_en_modulo(page, cfg, ACTIVIDAD_VINCULACION, "reparar ciclos")
            except (ErrorAccesoSinu, ErrorLecturaSinu) as exc:
                log.error("%s", exc)
                return 1
            page.wait_for_timeout(6000)

            for apunte in pendientes:
                cedula = apunte.get("identificacion", "")
                periodo = apunte.get("cod_periodo", "")
                objetivo = apunte.get("materia", "")
                etiqueta = f"{cedula} / {objetivo}" if objetivo else cedula
                print()
                print("=" * 62)
                print(f"{etiqueta} ({periodo}) - anotado como '{apunte.get('estado')}'")

                if not objetivo:
                    # Apunte anterior al 03/09/2026: no dice QUE materia quedo a
                    # medias. No se adivina -- reparar la materia equivocada es
                    # tocar una matricula que nadie pidio tocar.
                    print(
                        "  -> el apunte no dice la materia (formato anterior al "
                        "03/09/2026). Revisar a mano en ISEF07."
                    )
                    fallidos.append((etiqueta, "apunte sin materia: revisar a mano"))
                    continue

                cod_materia, _, num_grupo = objetivo.partition("/")

                try:
                    fijar_periodo(page, cfg, periodo)
                    antes = leer_estudiante(page, cfg, cedula)
                except ErrorLecturaSinu as exc:
                    log.error("No se pudo leer a %s: %s", cedula, exc)
                    fallidos.append((etiqueta, f"no se pudo leer: {exc}"))
                    continue

                fila = fila_de_materia(antes.grupos, cod_materia, num_grupo)
                if fila is None:
                    print(
                        f"  -> {objetivo} no aparece entre las "
                        f"{len(antes.grupos)} asignaturas del estudiante."
                    )
                    fallidos.append((etiqueta, "la materia no esta en la grilla"))
                    continue

                print(f"  antes: {objetivo} vinculado={fila.vinculado}")

                if fila.vinculado:
                    # Nada que reparar. Y NO se recicla: reciclar aqui volveria a
                    # abrir la ventana de riesgo sin necesidad, que es justo lo
                    # que este script existe para cerrar.
                    print("  -> ya estaba vinculada; se cierra el apunte.")
                    if de_verdad:
                        _apuntar_ciclo(cedula, periodo, "cerrado", objetivo)
                    intactos.append(etiqueta)
                    continue

                if not de_verdad:
                    print(f"  -> [SIMULACION] se habria vinculado {objetivo}.")
                    continue

                # Acotar la grilla: se repara ESA materia, no el estudiante.
                try:
                    filtrar_grupos_por_materia(page, cfg, cod_materia)
                except ErrorLecturaSinu as exc:
                    fallidos.append((etiqueta, f"no se pudo acotar: {exc}"))
                    continue

                # `ejecutar_materia` trae las guardas buenas: sondeo del check,
                # comprobacion de desborde y cierre del apunte. Y como la materia
                # NO tiene check, su decision es SOLO_VINCULAR -- nunca recicla.
                try:
                    r = ejecutar_materia(
                        page,
                        cfg,
                        identificacion=cedula,
                        cod_periodo=periodo,
                        cod_materia=cod_materia,
                        num_grupo=num_grupo,
                        grupos=antes.grupos,
                        releer_materia=lambda m=cod_materia: filtrar_grupos_por_materia(
                            page, cfg, m
                        ),
                        releer_todas=lambda ced=cedula: _releer_todas(page, cfg, ced),
                    )
                except AccionSeDesbordo as exc:
                    log.error("%s", exc)
                    print(f"  !! {exc}")
                    print("  Se detiene la reparacion.")
                    return 2
                except ErrorEjecucionSinu as exc:
                    log.error("Fallo el vincular de %s: %s", etiqueta, exc)
                    fallidos.append((etiqueta, str(exc)[:150]))
                    continue

                _apuntar_ciclo(cedula, periodo, "cerrado", objetivo)
                arreglados.append(etiqueta)
                print(f"  -> ARREGLADO ({r.segundos}s) y apunte cerrado.")
        finally:
            cerrar()

    print()
    print("=" * 62)
    print(f"Arreglados : {len(arreglados)} {arreglados}")
    print(f"Ya estaban : {len(intactos)} {intactos}")
    print(f"Fallidos   : {len(fallidos)}")
    for cedula, motivo in fallidos:
        print(f"   {cedula}: {motivo}")
    print()
    print(f"Registro de ciclos: {RUTA_CICLOS_ABIERTOS}")
    print(f"Log de la corrida : {archivo_log}")
    return 1 if fallidos else 0


if __name__ == "__main__":
    raise SystemExit(main())
