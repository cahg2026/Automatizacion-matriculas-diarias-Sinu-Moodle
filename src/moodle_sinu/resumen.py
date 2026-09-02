"""Resumen legible del resultado de la Fase 1, para consola y para el log."""

from __future__ import annotations

from collections import Counter

from .constantes import CAMPOS_OBLIGATORIOS, Color
from .modelos import ResultadoValidacion

_ANCHO = 78


def _titulo(texto: str) -> str:
    return f"\n{'=' * _ANCHO}\n{texto}\n{'=' * _ANCHO}"


def _seccion(texto: str) -> str:
    return f"\n{texto}\n{'-' * _ANCHO}"


def formatear_resumen(r: ResultadoValidacion, *, max_ejemplos: int = 10) -> str:
    lineas: list[str] = []
    add = lineas.append

    add(_titulo("FASE 1 — VALIDACION DEL REPORTE"))
    add(f"Archivo : {r.archivo}")
    add(f"Hoja    : {r.hoja}")
    add("")
    add(f"Filas de datos      : {r.total_filas}")
    add(f"  procesables (SINU): {len(r.procesables)}")
    add(f"  omitidas          : {len(r.omitidas)}")
    if r.filas_pie_descartadas:
        add(f"Filas de pie descartadas: {r.filas_pie_descartadas}")

    pct = (len(r.procesables) / r.total_filas * 100) if r.total_filas else 0.0
    add(f"Cobertura del dia   : {pct:.1f}% de las filas llegan a SINU")

    # --- regla 1 ---
    azules = r.hallazgos_por_color(Color.AZUL_CLARO)
    add(_seccion(f"REGLA 1 — Espacios corregidos  (AZUL #{Color.AZUL_CLARO.value})"))
    add(f"Celdas marcadas: {len(azules)}   Filas afectadas: {len(r.filas_afectadas(Color.AZUL_CLARO))}")
    if azules:
        add("")
        add("Por campo:")
        for campo, n in Counter(h.campo for h in azules).most_common():
            add(f"  {campo:<20} {n}")
        add("")
        add("Por tipo:")
        for det, n in Counter(h.detalle for h in azules).most_common():
            add(f"  {det:<28} {n}")
        add("")
        add(f"Ejemplos (hasta {max_ejemplos}):")
        for h in azules[:max_ejemplos]:
            add(
                f"  fila {h.fila:<6} {h.columna}{h.fila:<6} {h.campo:<18} "
                f"{h.valor_original!r} -> {h.valor_saneado!r}"
            )

    # --- regla 2 ---
    naranjas = r.hallazgos_por_color(Color.NARANJA)
    add(_seccion(f"REGLA 2 — Obligatorios vacios  (NARANJA #{Color.NARANJA.value})"))
    add(f"Campos obligatorios configurados: {', '.join(CAMPOS_OBLIGATORIOS)}")
    add(
        f"Celdas marcadas: {len(naranjas)}   "
        f"Filas omitidas: {len(r.filas_afectadas(Color.NARANJA))}"
    )
    if naranjas:
        add("")
        add("Por campo:")
        for campo, n in Counter(h.campo for h in naranjas).most_common():
            pct_campo = n / r.total_filas * 100 if r.total_filas else 0.0
            add(f"  {campo:<20} {n:<8} ({pct_campo:.1f}% de las filas)")
        add("")
        add("Por motivo:")
        for det, n in Counter(h.detalle for h in naranjas).most_common():
            add(f"  {det:<34} {n}")

    # --- regla 3 ---
    amarillas = r.hallazgos_por_color(Color.AMARILLO)
    add(_seccion(f"REGLA 3 — Duplicados con datos distintos  (AMARILLO #{Color.AMARILLO.value})"))
    filas_dup = r.filas_afectadas(Color.AMARILLO)
    add(f"Celdas marcadas: {len(amarillas)}   Filas omitidas: {len(filas_dup)}")
    if amarillas:
        add("")
        add(f"Ejemplos (hasta {max_ejemplos}):")
        vistos: set[str] = set()
        for h in amarillas:
            if h.detalle in vistos:
                continue
            vistos.add(h.detalle)
            add(f"  fila {h.fila:<6} {h.detalle}")
            if len(vistos) >= max_ejemplos:
                break

    # --- omisiones consolidadas ---
    add(_seccion("MOTIVOS DE OMISION"))
    if r.omitidas:
        for motivo, n in Counter(f.motivo_omision or "?" for f in r.omitidas).most_common():
            add(f"  {n:<8} {motivo}")
    else:
        add("  (ninguna fila omitida)")

    # --- advertencias ---
    if r.advertencias:
        add(_seccion("ADVERTENCIAS"))
        for a in r.advertencias:
            add(f"  - {a}")

    add("")
    return "\n".join(lineas)
