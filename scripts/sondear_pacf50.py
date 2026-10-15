"""Sonda de PACF50 (Programacion de grupos). SOLO LEE. No escribe nada.

Por que existe
--------------
`SKILL.md` marca PACF50 como *(pendiente de documentar)*: nadie ha descrito esa
pantalla, asi que no hay lector. Y el 26/09/2026 eso costo el dia entero: ISEF05
no contesto por los 4 grupos grandes (165 filas, el 94% del lote), no habia
ningun sitio donde validarlos, y el robot se puso a procesarlos uno a uno.

Regla del dueno del proceso (26/09/2026):

    Recuerda que si no te sale la 05, tienes que validarla por la 50. Y si no te
    sale por la 50, pues la validas por la 05. Siempre se tienen que validar en
    ambas.

Para escribir ese lector hace falta ver la pantalla real. Escribir selectores a
ojo es exactamente como se cometio el incidente n.o 2 (interpretar
`unchecked_Disabled.gif` como marcado), y aqui el error seria peor: marcar un
grupo sano como roto deja sin hacer trabajo que si se podia hacer.

Esta sonda no decide nada ni toca ninguna matricula. Abre el modulo, opcionalmente
filtra por un grupo, y vuelca lo que ve: columnas, filtros e imagenes de check.

Uso:
    python scripts/sondear_pacf50.py --visible
    python scripts/sondear_pacf50.py --periodo 26ES5 --materia POS01 --grupo 55ES2
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

from playwright.sync_api import sync_playwright  # noqa: E402

from moodle_sinu import registro  # noqa: E402
from moodle_sinu.acceso_sinu import abrir_y_acceder  # noqa: E402
from moodle_sinu.config import DIR_LOGS, Config, asegurar_directorios  # noqa: E402
from moodle_sinu.constantes_sinu import (  # noqa: E402
    ACTIVIDAD_PROGRAMACION_GRUPOS,
    ACTIVIDAD_VINCULACION,
)
from moodle_sinu.lector_sinu import entrar_en_modulo, fijar_periodo  # noqa: E402
from moodle_sinu.navegador import abrir_contexto, parar_playwright  # noqa: E402

log = logging.getLogger("sondear_pacf50")

#: Vuelca la forma de la pantalla: cajas de filtro, cabeceras y checks.
GUION_FORMA = """
() => {
  const filtros = [...document.querySelectorAll('input')]
    .filter(e => e.getBoundingClientRect().width > 0)
    .map(e => ({name: e.name || '', id: e.id || '', clase: e.className || '',
                habilitado: !e.disabled, valor: e.value || ''}));

  const cabeceras = [...document.querySelectorAll('td, div, span')]
    .filter(e => {
      const t = (e.innerText || '').replace(/\\s+/g,' ').trim();
      const r = e.getBoundingClientRect();
      return t && t.length < 60 && r.width > 0 && r.height > 0 &&
             /moodle|curso|grupo|asignatura|codigo|c.digo|vincula|usuario|semilla|estado/i.test(t);
    })
    .map(e => {
      const r = e.getBoundingClientRect();
      return {texto: (e.innerText||'').replace(/\\s+/g,' ').trim(),
              x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width)};
    });

  const vistos = new Set();
  const textos = cabeceras.filter(c => {
    const k = c.texto + '|' + c.x + '|' + c.y;
    if (vistos.has(k)) return false;
    vistos.add(k); return true;
  });

  const imgs = {};
  for (const e of document.querySelectorAll('img')) {
    const n = (e.src || '').split('/').pop();
    if (!n) continue;
    imgs[n] = (imgs[n] || 0) + 1;
  }

  return {url: location.href, filtros, textos, imagenes: imgs};
}
"""


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--periodo", default="", help="COD_PERIODO a fijar (opcional)")
    p.add_argument("--materia", default="", help="COD_MATERIA a buscar (opcional)")
    p.add_argument("--grupo", default="", help="NUM_GRUPO a buscar (opcional)")
    p.add_argument("--visible", action="store_true", help="Navegador con ventana")
    args = p.parse_args()

    asegurar_directorios()
    registro.configurar(logging.INFO, etiqueta="sondear_pacf50")
    cfg = Config.desde_entorno()
    sello = datetime.now().strftime("%Y%m%d_%H%M%S")
    destino = DIR_LOGS / f"sonda_pacf50_{sello}.json"

    pw = sync_playwright().start()
    try:
        context, cerrar = abrir_contexto(
            pw, cfg, headless=not args.visible
        )
        try:
            pagina = context.pages[0] if context.pages else context.new_page()
            abrir_y_acceder(pagina, cfg)

            # Por el camino verificado: clic en la celda del codigo desde
            # #home. Mover `location.hash` NO carga el modulo -- comprobado el
            # 26/09/2026: desde #home, el hash a #pacf50 deja la pantalla con
            # los campos del menu y ninguno de la rejilla.
            entrar_en_modulo(pagina, cfg, ACTIVIDAD_PROGRAMACION_GRUPOS, "sondear")
            p50 = pagina
            p50.wait_for_timeout(5000)
            if args.periodo:
                fijar_periodo(p50, cfg, args.periodo)
                p50.wait_for_timeout(2000)

            forma = p50.evaluate(GUION_FORMA)
            forma["periodo_fijado"] = args.periodo
            forma["buscado"] = f"{args.materia}/{args.grupo}" if args.materia else ""

            destino.write_text(
                json.dumps(forma, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            captura = DIR_LOGS / f"sonda_pacf50_{sello}.png"
            p50.screenshot(path=str(captura), full_page=False)

            print("=" * 70)
            print(f"PACF50 sondeado: {forma['url']}")
            print("=" * 70)
            print(f"\nFILTROS ({len(forma['filtros'])}):")
            for f in forma["filtros"][:25]:
                estado = "editable" if f["habilitado"] else "DESHABILITADO"
                print(f"   name={f['name']!r:28} {estado:14} clase={f['clase'][:40]}")
            print(f"\nTEXTOS RELEVANTES ({len(forma['textos'])}):")
            for t in forma["textos"][:30]:
                print(f"   x={t['x']:>5} y={t['y']:>5} w={t['w']:>4}  {t['texto']}")
            print("\nIMAGENES (los checks salen aqui):")
            for n, c in sorted(forma["imagenes"].items(), key=lambda kv: -kv[1])[:20]:
                print(f"   {c:>4}x  {n}")
            print(f"\nJSON    : {destino}")
            print(f"Captura : {captura}")
            return 0
        finally:
            cerrar()
    finally:
        parar_playwright(pw)


if __name__ == "__main__":
    raise SystemExit(main())
