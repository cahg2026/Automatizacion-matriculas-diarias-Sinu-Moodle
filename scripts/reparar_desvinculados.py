"""Vuelve a vincular a los estudiantes que quedaron desvinculados a medias.

Cuando un reciclado se corta entre el desvincular y el vincular, el estudiante
queda peor que al empezar. `logs/ciclos_abiertos.jsonl` los registra; esto los
arregla.

Por que fuerza VINCULAR y no la secuencia normal
------------------------------------------------
`decidir_secuencia` mira si ALGUNA materia esta vinculada y, si lo esta, recicla
-- o sea, desvincula otra vez. Para un estudiante a medio arreglar eso vuelve a
abrir la ventana de riesgo sin necesidad: "Vincular grupos matriculados" actua
sobre TODAS sus asignaturas del periodo, asi que un solo vincular lo deja
completo, venga de 0 o de 3 de 6.

Se verifica leyendo antes y despues, y solo se cierra el apunte del ciclo si de
verdad quedaron todas vinculadas.

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
    ErrorEjecucionSinu,
    _apuntar_ciclo,
    ciclos_abiertos,
    esperar_proceso_terminado,
    pulsar_ejecutar,
    seleccionar_accion,
)
from moodle_sinu.lector_sinu import (  # noqa: E402
    ErrorLecturaSinu,
    entrar_en_modulo,
    fijar_periodo,
    leer_estudiante,
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
                print()
                print("=" * 62)
                print(f"{cedula} ({periodo}) - anotado como '{apunte.get('estado')}'")
                try:
                    fijar_periodo(page, cfg, periodo)
                    antes = leer_estudiante(page, cfg, cedula)
                except ErrorLecturaSinu as exc:
                    log.error("No se pudo leer a %s: %s", cedula, exc)
                    fallidos.append((cedula, f"no se pudo leer: {exc}"))
                    continue

                total = len(antes.grupos)
                vinculadas = sum(1 for g in antes.grupos if g.vinculado)
                print(f"  antes: {vinculadas} de {total} vinculadas")

                if total and vinculadas == total:
                    print("  -> ya estaba completo; se cierra el apunte.")
                    if de_verdad:
                        _apuntar_ciclo(cedula, periodo, "cerrado")
                    intactos.append(cedula)
                    continue

                if not de_verdad:
                    print("  -> [SIMULACION] se habria ejecutado Vincular.")
                    continue

                try:
                    seleccionar_accion(page, cfg, sesc.OPCION_VINCULAR)
                    pulsar_ejecutar(page, cfg)
                    esperar_proceso_terminado(page, cfg)
                except ErrorEjecucionSinu as exc:
                    log.error("Fallo el vincular de %s: %s", cedula, exc)
                    fallidos.append((cedula, str(exc)[:150]))
                    continue

                # Se comprueba de verdad, no se da por hecho.
                try:
                    despues = leer_estudiante(page, cfg, cedula)
                except ErrorLecturaSinu as exc:
                    fallidos.append((cedula, f"vinculado pero no verificable: {exc}"))
                    continue
                ahora = sum(1 for g in despues.grupos if g.vinculado)
                print(f"  despues: {ahora} de {len(despues.grupos)} vinculadas")
                if len(despues.grupos) and ahora == len(despues.grupos):
                    _apuntar_ciclo(cedula, periodo, "cerrado")
                    arreglados.append(cedula)
                    print("  -> ARREGLADO y apunte cerrado.")
                else:
                    fallidos.append((cedula, f"quedo en {ahora}/{len(despues.grupos)}"))
                    print("  -> SIGUE INCOMPLETO. El apunte queda abierto.")
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
