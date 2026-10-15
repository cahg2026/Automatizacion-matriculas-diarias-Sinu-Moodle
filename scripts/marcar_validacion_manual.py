"""Pinta de MORADO las unidades que necesitan que una persona mire SINU.

Que problema resuelve
---------------------
El PASO 5 (`marcar_gestion.py`) pinta verde lo vinculado y rojo todo lo demas.
Eso basta para saber que algo no salio, pero no distingue dos cosas muy
distintas:

    ROJO    -> se intento y no se pudo. SINU quedo como estaba.
    MORADO  -> se dejo una operacion A MEDIAS. SINU quedo peor que antes.

El caso morado es el de un ciclo desvincular+vincular que se corto entre las
dos acciones: el estudiante queda DESVINCULADO y sin volver a vincular. Pasa
poco, pero cuando pasa hay que ir a arreglarlo a mano, y en rojo se confunde
con los fallos normales que no rompieron nada.

Por que morado y no naranja ni lila: los dos estaban cogidos. NARANJA es
"campo obligatorio vacio" de la Fase 1 y LILA es "sin matricula academica"
del Caso 3. Reusar cualquiera de los dos haria ilegible el reporte.

Ocurrio el 23/09/2026 con 1000000001 / ESP168 (se reparo al reanudar), y al
mirar el libro aparecieron DOS ciclos del 21/09/2026 que llevaban dos dias
abiertos sin que nadie lo supiera: la informacion estaba, pero solo en un
.jsonl que nadie abre.

De donde sale
-------------
De `logs/ciclos_abiertos.jsonl`, que la etapa 4 escribe al empezar y al cerrar
cada desvincular+vincular. Un ciclo esta ABIERTO si su ultimo apunte no es
'cerrado'. El libro es append-only, asi que se queda el ultimo estado de cada
(cedula, periodo, materia).

Cuando ejecutarlo
-----------------
DESPUES del PASO 5, sobre el `_gestion_*.xlsx` que produce. Si se ejecuta
antes, el paso 5 lo sobreescribe.

Uso:
    python scripts/marcar_validacion_manual.py <reporte_gestion.xlsx>
                                               [--salida X.xlsx]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from openpyxl import load_workbook  # noqa: E402
from openpyxl.styles import PatternFill  # noqa: E402

from moodle_sinu import registro  # noqa: E402
from moodle_sinu.config import DIR_LOGS, asegurar_directorios  # noqa: E402
from moodle_sinu.constantes import (  # noqa: E402
    COL_COD_MATERIA,
    COL_COD_PERIODO,
    COL_IDENTIFICACION,
    COL_NUM_GRUPO,
    COL_VALIDACION_RPA,
    Color,
)

log = logging.getLogger("marcar_validacion_manual")

RUTA_CICLOS = DIR_LOGS / "ciclos_abiertos.jsonl"

#: Todos los diarios de la etapa 4: el vivo y los rotados de dias anteriores.
#: Un ciclo puede abrirse un dia y repararse otro, asi que mirar solo el vivo
#: dejaria abiertos ciclos que se cerraron hace dos dias.
PATRON_DIARIOS = "resultados_etapa4*.jsonl"

#: El apunte que dice que el ciclo termino bien. Cualquier otro estado como
#: ultimo apunte significa que quedo a medias.
ESTADO_CERRADO = "cerrado"

VEREDICTO_VERDE = "verde"


def _leer_jsonl(ruta: Path) -> list[dict]:
    """Las lineas legibles de un .jsonl. Una corrupta no tumba el resto."""
    if not ruta.is_file():
        return []
    salida = []
    for numero, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), 1):
        linea = linea.strip()
        if not linea:
            continue
        try:
            salida.append(json.loads(linea))
        except json.JSONDecodeError:
            log.warning("Linea %d de %s ilegible; se salta.", numero, ruta.name)
    return salida


def ultimo_verde_por_unidad(dir_logs: Path = DIR_LOGS) -> dict[tuple, str]:
    """Cuando fue la ultima vez que cada unidad quedo VERDE, en cualquier diario.

    Clave: (cedula, periodo, 'MATERIA/GRUPO'), que es como el libro de ciclos
    nombra la unidad.
    """
    verdes: dict[tuple, str] = {}
    for ruta in sorted(dir_logs.glob(PATRON_DIARIOS)):
        for d in _leer_jsonl(ruta):
            if d.get("veredicto") != VEREDICTO_VERDE:
                continue
            clave = (
                str(d.get("identificacion", "")),
                str(d.get("cod_periodo", "")),
                str(d.get("objetivo", "")),
            )
            momento = str(d.get("momento", ""))
            if momento > verdes.get(clave, ""):
                verdes[clave] = momento
    return verdes


def ciclos_abiertos(
    ruta: Path = RUTA_CICLOS, dir_logs: Path | None = None
) -> list[dict]:
    """Los ciclos que de verdad siguen a medias, del mas viejo al mas nuevo.

    Dos filtros, y el segundo es el que hace util a este script.

    1. El libro es append-only y reescribe la misma clave varias veces
       (desvinculando -> desvinculado-pendiente-vincular -> cerrado), asi que
       no vale filtrar por estado: hay que quedarse con el ULTIMO apunte de
       cada unidad y mirar ese.

    2. **El libro miente por exceso.** Cuando un ciclo se repara mas tarde con
       un 'vincular' suelto -- que es como se arregla, porque el estudiante ya
       esta desvinculado -- nadie vuelve a escribir el 'cerrado'. El ciclo se
       queda abierto para siempre aunque el estudiante este perfecto. Por eso
       se cruza con el diario: si hay un VERDE posterior al apunte, la unidad
       esta bien y no se marca.

    Sin el cruce, el 23/09/2026 habrian salido 4 ciclos y solo 1 era real:
    1000000001 (verde 19 min despues), 1000000002 (verde 1 min despues) y
    30000001 (verde al dia siguiente) estaban los tres sanos. Marcar en morado
    a un estudiante que esta bien gasta el unico recurso que tiene una alerta,
    que es que quien la ve se la crea.

    Los apuntes viejos (25 de los 984 el 23/09/2026) no traen 'materia'. Se
    aceptan igual, con la materia vacia: perder un aviso por un cambio de
    formato seria justo lo contrario de para lo que existe este libro.
    """
    apuntes = _leer_jsonl(ruta)
    if not apuntes:
        return []

    ultimo: dict[tuple[str, str, str], dict] = {}
    for d in apuntes:
        clave = (
            str(d.get("identificacion", "")),
            str(d.get("cod_periodo", "")),
            str(d.get("materia", "")),
        )
        ultimo[clave] = d

    verdes = ultimo_verde_por_unidad(dir_logs if dir_logs is not None else DIR_LOGS)

    abiertos = []
    for clave, d in ultimo.items():
        if d.get("estado") == ESTADO_CERRADO:
            continue
        verde = verdes.get(clave, "")
        if verde and verde > str(d.get("momento", "")):
            log.debug(
                "%s: el libro lo da por abierto, pero hay un verde en %s. Sano.",
                clave,
                verde,
            )
            continue
        abiertos.append(d)

    return sorted(abiertos, key=lambda d: d.get("momento", ""))


def _indices(ws) -> dict[str, int]:
    return {
        str(ws.cell(row=1, column=c).value or "").strip(): c
        for c in range(1, ws.max_column + 1)
    }


def _texto(ws, fila: int, col: int | None) -> str:
    if not col:
        return ""
    return str(ws.cell(row=fila, column=col).value or "").strip()


def marcar(ws, abiertos: list[dict]) -> tuple[int, list[str]]:
    """Pinta las filas de los ciclos abiertos. Devuelve (pintadas, no ubicadas).

    Se busca por (cedula, materia) recorriendo la hoja, y no por numero de fila
    como hace el paso 5: un ciclo abierto puede venir de una corrida de otro
    dia, y entonces el numero de fila de aquel reporte no significa nada en
    este. Si la unidad no esta en este reporte se dice, no se adivina.
    """
    cols = _indices(ws)
    col_rpa = cols.get(COL_VALIDACION_RPA)
    if not col_rpa:
        col_rpa = ws.max_column + 1
        ws.cell(row=1, column=col_rpa, value=COL_VALIDACION_RPA)
    ultima_col = ws.max_column

    relleno = PatternFill(
        start_color=Color.MORADO.value,
        end_color=Color.MORADO.value,
        fill_type="solid",
    )

    pintadas = 0
    no_ubicadas: list[str] = []

    for d in abiertos:
        cedula = str(d.get("identificacion", ""))
        materia_grupo = str(d.get("materia", ""))
        materia = materia_grupo.split("/")[0] if materia_grupo else ""
        periodo = str(d.get("cod_periodo", ""))

        fila_encontrada = None
        for fila in range(2, ws.max_row + 1):
            if _texto(ws, fila, cols.get(COL_IDENTIFICACION)) != cedula:
                continue
            if materia and _texto(ws, fila, cols.get(COL_COD_MATERIA)).upper() != materia.upper():
                continue
            if periodo and _texto(ws, fila, cols.get(COL_COD_PERIODO)) != periodo:
                continue
            fila_encontrada = fila
            break

        if fila_encontrada is None:
            no_ubicadas.append(
                f"{cedula} / {materia_grupo or '(sin materia)'} ({periodo}) "
                f"- {d.get('estado', '')} desde {str(d.get('momento', ''))[:16]}"
            )
            continue

        for col in range(1, ultima_col + 1):
            ws.cell(row=fila_encontrada, column=col).fill = relleno
        ws.cell(
            row=fila_encontrada,
            column=col_rpa,
            value=(
                f"VALIDAR A MANO - ciclo sin cerrar: {d.get('estado', '')} "
                f"(desde {str(d.get('momento', ''))[:16]})"
            ),
        )
        pintadas += 1

    return pintadas, no_ubicadas


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("reporte", help="El _gestion_*.xlsx que dejo el paso 5.")
    p.add_argument("--salida", default="", help="Por defecto, <entrada>_validar_<sello>.xlsx")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args(argv)

    asegurar_directorios()
    registro.configurar(
        logging.DEBUG if args.verbose else logging.INFO,
        etiqueta="marcar_validacion_manual",
    )

    entrada = Path(args.reporte)
    if not entrada.is_file():
        raise SystemExit(f"No existe {entrada}")

    abiertos = ciclos_abiertos()
    if not abiertos:
        print("No hay ciclos sin cerrar. Nada que marcar a mano.")
        return 0

    wb = load_workbook(entrada)
    ws = wb.active
    pintadas, no_ubicadas = marcar(ws, abiertos)

    salida = (
        Path(args.salida)
        if args.salida
        else entrada.with_name(
            f"{entrada.stem}_validar_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
        )
    )
    wb.save(salida)

    print()
    print(f"Ciclos sin cerrar   : {len(abiertos)}")
    print(f"  pintados MORADO   : {pintadas}")
    print(f"  no estan en este reporte: {len(no_ubicadas)}")
    for x in no_ubicadas:
        print(f"    - {x}")
    print()
    print(f"Archivo: {salida}")
    print()
    print("MORADO = la operacion quedo A MEDIAS en SINU (peor que no tocarla).")
    print("Hay que abrir ISEF07 y comprobar como quedo cada una.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
