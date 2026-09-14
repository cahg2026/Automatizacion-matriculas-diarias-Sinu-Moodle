"""Sonda de SOLO LECTURA: que dice el tablero sobre su ultima actualizacion.

No existe todavia un lector de "fecha de actualizacion" porque no se sabia si
el dato esta disponible, y donde. Esta sonda lo averigua sobre el tablero real
antes de escribir el lector, en vez de suponerlo:

  - el .xlsx exportado NO la trae (su pie solo lista los filtros aplicados)
  - las tarjetas del tablero, hoy, son solo 'MATRICULADO' y 'NO MATRICULADO'

Vuelca todos los candidatos que encuentra y deja una captura. Con eso se decide
de donde leer la fecha en `actualizacion_powerbi.py`.

Uso:
    python scripts\\sondear_actualizacion.py --visible -v
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from playwright.sync_api import sync_playwright  # noqa: E402

from moodle_sinu import registro, selectores_powerbi as sel  # noqa: E402
from moodle_sinu.config import (  # noqa: E402
    DIR_LOGS,
    Config,
    asegurar_directorios,
)
from moodle_sinu.exportador_powerbi import (  # noqa: E402
    _abrir_informe,
    _verificar_pagina,
)
from moodle_sinu.navegador import abrir_contexto  # noqa: E402

log = logging.getLogger("sondear_actualizacion")

#: Cualquier cosa con pinta de fecha, en los formatos que usa Power BI en
#: es-CO y en en-US. Se busca a lo bruto a proposito: la sonda no sabe aun
#: donde vive el dato, y un falso positivo cuesta una linea de log.
RX_FECHAS = re.compile(
    r"\d{1,2}/\d{1,2}/\d{2,4}"
    r"|\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}\s+de\s+\w+\s+de\s+\d{4}"
    r"|\w+\s+\d{1,2},\s+\d{4}",
    re.IGNORECASE,
)

#: Palabras que suelen acompanar al dato que se busca.
RX_PISTAS = re.compile(
    r"actualiz|refresh|ultima|últim|corte|vigencia|generado|fecha",
    re.IGNORECASE,
)


def _volcar(titulo: str, lineas: list[str]) -> None:
    print()
    print(f"--- {titulo} ({len(lineas)}) ---")
    if not lineas:
        print("    (nada)")
        return
    for x in lineas[:40]:
        print(f"    {x}")
    if len(lineas) > 40:
        print(f"    ... y {len(lineas) - 40} mas")


def sondear(page, cfg: Config) -> None:
    """Vuelca todo lo que pueda contener la fecha de actualizacion."""

    # 1. Las tarjetas: es donde ya se lee 'NO MATRICULADO'.
    tarjetas = page.locator(sel.css_tarjetas())
    etiquetas = []
    for i in range(tarjetas.count()):
        t = tarjetas.nth(i)
        txt = (t.get_attribute("aria-label") or t.inner_text() or "").strip()
        etiquetas.append(txt.replace("\n", " ")[:160])
    _volcar("TARJETAS del tablero", etiquetas)

    # 2. Todos los visuales: por titulo, buscando pistas.
    visuales = page.locator(sel.CSS_CONTENEDOR_VISUAL)
    con_pista = []
    for i in range(visuales.count()):
        v = visuales.nth(i)
        etiqueta = (v.get_attribute("aria-label") or "").strip()
        rol = (v.get_attribute("aria-roledescription") or "").strip()
        texto = ""
        try:
            texto = (v.inner_text() or "").strip().replace("\n", " ")[:200]
        except Exception:  # noqa: BLE001 - la sonda nunca debe reventar
            pass
        junto = f"{etiqueta} | {texto}"
        if RX_PISTAS.search(junto) or RX_FECHAS.search(junto):
            con_pista.append(f"[{rol or 'sin rol'}] {junto[:170]}")
    _volcar("VISUALES con pista de fecha", con_pista)

    # 3. El texto completo de la pagina: cualquier fecha suelta.
    try:
        cuerpo = page.locator("body").inner_text()
    except Exception:  # noqa: BLE001
        cuerpo = ""
    fechas = sorted(set(RX_FECHAS.findall(cuerpo)))
    _volcar("FECHAS en el texto de la pagina", fechas)

    lineas_pista = [
        l.strip()[:170]
        for l in cuerpo.splitlines()
        if l.strip() and RX_PISTAS.search(l)
    ]
    _volcar("LINEAS con palabra de actualizacion", sorted(set(lineas_pista)))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--visible", action="store_true", help="Navegador con ventana")
    p.add_argument("--verbose", "-v", action="store_true", help="Log en DEBUG")
    args = p.parse_args(argv)

    asegurar_directorios()
    sello = datetime.now().strftime("%Y%m%d_%H%M%S")
    registro.configurar(
        logging.DEBUG if args.verbose else logging.INFO,
        etiqueta="sondear_actualizacion",
    )
    cfg = Config.desde_entorno()
    sin_cabeza = False if args.visible else cfg.powerbi_headless

    with sync_playwright() as pw:
        context, cerrar = abrir_contexto(pw, cfg, sin_cabeza)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page_informe, _ = _abrir_informe(context, page, cfg)
            # Sin esto la sonda lee la pantalla de carga y lo informa todo
            # vacio: es la espera del lienzo, hasta TIMEOUT_RENDER_SEG.
            _verificar_pagina(page_informe, cfg, [])
            page_informe.wait_for_timeout(4000)
            sondear(page_informe, cfg)
            captura = DIR_LOGS / f"sonda_actualizacion_{sello}.png"
            page_informe.screenshot(path=str(captura), full_page=True)
            print()
            print(f"Captura: {captura}")
        finally:
            cerrar()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
