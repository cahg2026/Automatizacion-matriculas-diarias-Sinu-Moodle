"""Avisa del cierre del dia, con las metricas sacadas del diario.

El resumen NO se pasa por parametro: se calcula aqui, leyendo
`logs/resultados_etapa4.jsonl` y los registros de escalado y de ciclos
abiertos. Asi el aviso dice lo que de verdad paso, y no lo que el script que
llama creia que habia pasado.

Uso:
    python scripts\\notificar_cierre.py --estado exito
    python scripts\\notificar_cierre.py --estado fallo --nota "26I35 fallo"
    python scripts\\notificar_cierre.py --estado exito --solo-mostrar
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from moodle_sinu import notificaciones, registro, resumen_dia  # noqa: E402
from moodle_sinu.config import DIR_LOGS, Config, asegurar_directorios  # noqa: E402

log = logging.getLogger("notificar_cierre")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--estado",
        choices=("exito", "fallo"),
        required=True,
        help="'exito' si el flujo termino bien; 'fallo' si no.",
    )
    p.add_argument("--nota", default="", help="Linea extra para el cuerpo.")
    p.add_argument(
        "--solo-mostrar",
        action="store_true",
        help="Imprime el aviso y no lo manda. Para comprobar el texto.",
    )
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args(argv)

    asegurar_directorios()
    registro.configurar(
        logging.DEBUG if args.verbose else logging.INFO,
        etiqueta="notificar_cierre",
    )
    cfg = Config.desde_entorno()
    hoy = date.today()
    resumen = resumen_dia.construir(hoy, args.nota)

    if args.estado == "exito":
        aviso = notificaciones.aviso_exito(resumen, hoy=hoy)
    else:
        aviso = notificaciones.aviso_fallo(resumen, hoy=hoy)

    if args.solo_mostrar:
        # Se escribe en un archivo, no por consola: los emoji del asunto no
        # sobreviven a la consola de Windows en cp1252.
        destino = DIR_LOGS / f"aviso_previsto_{datetime.now():%Y%m%d_%H%M%S}.txt"
        destino.write_text(f"{aviso.asunto}\n\n{aviso.cuerpo}", encoding="utf-8")
        print(f"Aviso escrito (sin enviar) en: {destino}")
        return 0

    r = notificaciones.enviar(aviso, cfg)
    print(f"Aviso de {args.estado}: {r.resumen()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
