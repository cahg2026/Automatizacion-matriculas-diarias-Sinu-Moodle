"""Metricas del dia, sacadas del diario de resultados.

Vive en un modulo y no dentro de un script porque lo usan dos sitios -- el
orquestador y `scripts/notificar_cierre.py` -- y porque asi entra en pytest.
Esa fue la leccion del 07/09/2026: la logica que vivia solo en el .ps1 no se
podia probar, y sus tres defectos (bitacora en UTF-16, rotacion del diario mal
colocada, `--saltar-hechas` que no se pasaba) estaban justo ahi.

El resumen se calcula LEYENDO el diario, nunca se recibe por parametro. Asi
cuenta lo que de verdad paso y no lo que el que llama creia que pasaba.
"""

from __future__ import annotations

import collections
import json
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .config import DIR_LOGS
from .diario_resultados import RUTA_RESULTADOS

log = logging.getLogger(__name__)

RUTA_ESCALADOS = DIR_LOGS / "escalado_isef05_pacf50.jsonl"


@dataclass
class ResumenDia:
    """Lo que paso hoy, ya contado."""

    unidades: int = 0
    verdes: int = 0
    rojos: int = 0
    por_periodo: dict[str, int] = field(default_factory=dict)
    rojos_por_grupo: dict[str, int] = field(default_factory=dict)
    segundos: list[float] = field(default_factory=list)
    ciclos_abiertos: list[dict] = field(default_factory=list)

    @property
    def hubo_trabajo(self) -> bool:
        return self.unidades > 0


def apuntes_de(ruta: Path, dia: date) -> list[dict]:
    """Registros del diario cuyo `momento` cae en `dia`.

    Lista vacia si el archivo no existe: un dia sin corrida no es un error.
    Las lineas ilegibles se saltan en silencio -- el diario se escribe con
    append desde varios procesos y una linea a medias no debe tumbar el
    resumen del dia entero.
    """
    if not ruta.is_file():
        return []
    prefijo = dia.strftime("%Y-%m-%d")
    salida: list[dict] = []
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea:
            continue
        try:
            d = json.loads(linea)
        except json.JSONDecodeError:
            log.debug("Linea ilegible en %s, se salta.", ruta.name)
            continue
        if str(d.get("momento", "")).startswith(prefijo):
            salida.append(d)
    return salida


def calcular(dia: date | None = None, ciclos: list[dict] | None = None) -> ResumenDia:
    """Cuenta el dia. `ciclos` se inyecta en las pruebas."""
    objetivo = dia or date.today()
    apuntes = apuntes_de(RUTA_RESULTADOS, objetivo)

    veredictos = collections.Counter(
        str(a.get("veredicto", "?")).lower() for a in apuntes
    )
    if ciclos is None:
        # Se importa aqui y no arriba: ejecutor_sinu arrastra Playwright, y
        # este modulo lo usan scripts que no abren navegador.
        from .ejecutor_sinu import ciclos_abiertos

        ciclos = ciclos_abiertos()

    return ResumenDia(
        unidades=len(apuntes),
        verdes=veredictos.get("verde", 0),
        rojos=veredictos.get("rojo", 0),
        por_periodo=dict(
            sorted(collections.Counter(a.get("cod_periodo", "?") for a in apuntes).items())
        ),
        rojos_por_grupo=dict(
            collections.Counter(
                a.get("objetivo", "?")
                for a in apuntes
                if str(a.get("veredicto", "")).lower() == "rojo"
            ).most_common()
        ),
        segundos=[float(a["segundos"]) for a in apuntes if a.get("segundos")],
        ciclos_abiertos=list(ciclos),
    )


def formatear(resumen: ResumenDia, nota: str = "") -> str:
    """El resumen en texto plano, para el cuerpo de un aviso."""
    lineas = [
        f"  Unidades procesadas (cedula + materia) : {resumen.unidades}",
        f"  Vinculadas y confirmadas (verde)       : {resumen.verdes}",
        f"  Con incidencia (rojo)                  : {resumen.rojos}",
    ]

    if resumen.por_periodo:
        lineas.append(
            "  Periodos                               : "
            + ", ".join(f"{p} ({n})" for p, n in resumen.por_periodo.items())
        )
    if resumen.segundos:
        s = resumen.segundos
        lineas.append(
            f"  Tiempo medido por unidad               : "
            f"{min(s):.0f}-{max(s):.0f}s (media {sum(s) / len(s):.0f}s)"
        )

    # Agrupar los rojos por materia/grupo es lo que convierte una lista de 15
    # personas en un diagnostico de 2 grupos, que es lo accionable. El
    # 07/09/2026 fue exactamente asi: 13 de DCD05/20111 y 2 de DTA32/55598,
    # y en los dos el patron era el mismo.
    if resumen.rojos_por_grupo:
        lineas.append("")
        lineas.append("  A validar a mano en ISEF05/PACF50, por grupo:")
        for objetivo, n in resumen.rojos_por_grupo.items():
            lineas.append(f"    {objetivo:<18} {n} estudiante(s)")

    lineas.append("")
    if resumen.ciclos_abiertos:
        lineas.append(f"  !! CICLOS SIN CERRAR: {len(resumen.ciclos_abiertos)}")
        lineas.append("     Esos estudiantes pueden estar DESVINCULADOS ahora mismo.")
        for a in resumen.ciclos_abiertos[:10]:
            lineas.append(
                f"     {a.get('identificacion', '')} {a.get('materia', '')} "
                f"({a.get('cod_periodo', '')})"
            )
        lineas.append("     Reparar con: python scripts/reparar_desvinculados.py")
    else:
        lineas.append("  Ciclos sin cerrar                      : 0 (nadie desvinculado)")

    if nota:
        lineas.append("")
        lineas.append(f"  Nota: {nota}")

    return "\n".join(lineas)


def construir(dia: date | None = None, nota: str = "") -> str:
    """Atajo: calcular y formatear de una vez."""
    return formatear(calcular(dia), nota)
