"""El contrato de estado del dia: `logs/estado/estado_AAAAMMDD.json`.

Lo escribe el orquestador cuando la Fase A (pasos 0 a 3) termina o se detiene,
para que quien mire -- una persona, o la corrida siguiente -- sepa en que punto
quedo el dia sin leer la bitacora.

Hoy solo lo escribe la pausa por tablero viejo (28/09/2026):

    {
      "fase": "A",
      "estado": "PAUSADO_BI_VIEJO",
      "paso_detenido": 1,
      "motivo": "Tablero Power BI desactualizado",
      "timestamp": "2026-09-28T09:00:17-05:00"
    }

Se escribe MEZCLANDO con lo que hubiera: el contrato va a ir ganando campos
(reporte, Sheet del dia) y una pausa no debe borrar lo que otra etapa anoto. Y
se escribe por archivo temporal + `replace`, para que un corte a mitad no deje
un JSON truncado que la siguiente lectura no pueda abrir.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path

from .config import DIR_LOGS

DIR_ESTADO = DIR_LOGS / "estado"

FASE_PREPARAR = "A"
ESTADO_PAUSADO_BI_VIEJO = "PAUSADO_BI_VIEJO"
MOTIVO_BI_VIEJO = "Tablero Power BI desactualizado"

#: El dia paso el paso 1 y sigue su curso. Es lo que impide que la tarea de
#: reintento de las 9:30 (`--solo-si-pausado`) arranque una SEGUNDA corrida
#: encima de una que ya esta en ISEF07: solo arranca sobre PAUSADO_BI_VIEJO.
ESTADO_EN_CURSO = "EN_CURSO"
ESTADO_TERMINADO = "TERMINADO"


def ruta(dia: date, carpeta: Path | None = None) -> Path:
    return (carpeta or DIR_ESTADO) / f"estado_{dia:%Y%m%d}.json"


def leer(dia: date, carpeta: Path | None = None) -> dict:
    """El estado del dia, o {} si no hay o no se puede leer."""
    destino = ruta(dia, carpeta)
    try:
        datos = json.loads(destino.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return datos if isinstance(datos, dict) else {}


def registrar(
    dia: date,
    campos: dict,
    *,
    carpeta: Path | None = None,
    ahora: datetime | None = None,
) -> Path:
    """Mezcla `campos` en el estado del dia y sella `timestamp`. Devuelve la ruta."""
    destino = ruta(dia, carpeta)
    destino.parent.mkdir(parents=True, exist_ok=True)

    estado = leer(dia, carpeta)
    estado.update(campos)
    estado["timestamp"] = (ahora or datetime.now()).astimezone().isoformat(
        timespec="seconds"
    )

    temporal = destino.with_suffix(".json.tmp")
    temporal.write_text(
        json.dumps(estado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporal, destino)
    return destino


def registrar_pausa_bi_viejo(
    dia: date, *, carpeta: Path | None = None, ahora: datetime | None = None
) -> Path:
    """La Fase A se detuvo en el paso 1 porque el tablero es de otro dia."""
    return registrar(
        dia,
        {
            "fase": FASE_PREPARAR,
            "estado": ESTADO_PAUSADO_BI_VIEJO,
            "paso_detenido": 1,
            "motivo": MOTIVO_BI_VIEJO,
        },
        carpeta=carpeta,
        ahora=ahora,
    )


def registrar_avance(
    dia: date,
    estado: str,
    *,
    carpeta: Path | None = None,
    ahora: datetime | None = None,
) -> Path:
    """El dia sigue (EN_CURSO) o acabo (TERMINADO): ya no esta detenido."""
    return registrar(
        dia,
        {"fase": FASE_PREPARAR, "estado": estado, "paso_detenido": None, "motivo": ""},
        carpeta=carpeta,
        ahora=ahora,
    )


def esta_pausado_por_bi_viejo(dia: date, carpeta: Path | None = None) -> bool:
    return leer(dia, carpeta).get("estado") == ESTADO_PAUSADO_BI_VIEJO
