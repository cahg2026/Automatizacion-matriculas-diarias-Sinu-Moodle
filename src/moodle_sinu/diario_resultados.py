"""Diario de resultados de la etapa 4, una linea por unidad de trabajo.

Por que existe
--------------
Hasta el 04/09/2026 el resultado de cada operacion solo quedaba en el texto de
los logs. Los registros en disco que habia -- `ciclos_abiertos.jsonl` y
`escalado_isef05_pacf50.jsonl` -- son **de excepciones**: cuentan lo que salio
mal, no lo que salio bien. Asi que para saber que se vinculo con exito habia que
parsear logs con expresiones regulares, y eso no es una fuente de la que se
pueda pintar un Sheet.

Este diario es esa fuente. Una linea por **(cedula, materia)** procesada, con su
veredicto, escrita justo despues de cada operacion. De aqui sale el marcado del
Sheet -- en vivo o retroactivo -- sin depender de los logs.

Se escribe con `flush` por el mismo motivo que los otros dos registros: tiene
que sobrevivir a que el proceso muera. El 03/09/2026 una corrida se corto por la
noche cuando la maquina se durmio, y lo unico que permitio reconstruir el estado
fueron los apuntes ya volcados a disco.

Dos veredictos, no mas
----------------------
El dueno del proceso pidio dos colores en el Sheet (04/09/2026): verde para lo
vinculado y validado, rojo para todo lo demas -- fallo, sin correspondencia en
SINU, o check de Moodle sin confirmar. El `motivo` guarda el detalle para que
"rojo" no pierda la razon por la que es rojo.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from enum import Enum

from .config import DIR_LOGS

log = logging.getLogger(__name__)

#: Un registro por operacion. Se acumula entre corridas a proposito: el Sheet
#: del dia se pinta con todo lo hecho, no solo con la ultima invocacion.
RUTA_RESULTADOS = DIR_LOGS / "resultados_etapa4.jsonl"


class Veredicto(str, Enum):
    """Lo que se pinta en el Sheet."""

    VERDE = "verde"
    """Vinculada y con el check confirmado releyendo la grilla."""

    ROJO = "rojo"
    """Todo lo demas: fallo, sin correspondencia en SINU, o check sin confirmar."""

    def __str__(self) -> str:  # pragma: no cover - conveniencia de log
        return self.value


#: Motivos normalizados, para poder contar por categoria sin leer prosa.
MOTIVO_OK = "vinculada-y-confirmada"
MOTIVO_SIN_CORRESPONDENCIA = "materia-no-esta-en-sinu"
MOTIVO_CHECK_NO_CONFIRMADO = "check-no-confirmado"
MOTIVO_CICLO_ABIERTO = "quedo-desvinculada"
MOTIVO_NO_LEIDO = "no-se-pudo-leer"
MOTIVO_DESBORDE = "accion-se-desbordo"

#: Fallo tecnico en ISEF07 (clic que no prende, plazo agotado, grilla que no
#: responde). ANTES se anotaba como MOTIVO_CHECK_NO_CONFIRMADO, y eso engana:
#: manda a validar un check en ISEF05/PACF50 cuando lo que paso es que la
#: automatizacion no pudo operar. Son dos acciones distintas para el operador:
#: uno se valida a mano, el otro se reintenta.
MOTIVO_FALLO_TECNICO = "fallo-tecnico"

#: ISEF05 dice que el grupo NO tiene curso creado en MOODLE, asi que vincular
#: es imposible y no se intenta. Va aparte de MOTIVO_CHECK_NO_CONFIRMADO a
#: proposito, porque lo que hay que hacer es lo contrario:
#:
#:   - check-no-confirmado : se intento, no se sabe por que fallo -> validar.
#:   - sin-curso-en-moodle : se sabe por que, y no hay nada que validar ->
#:     CREAR EL CURSO en MOODLE. Hasta que exista, reintentar no puede salir
#:     bien.
#:
#: Confundirlos mandaria al operador a verificar en ISEF05 algo que ISEF05 ya
#: contesto. `DTA32/55598` (26V05) se reintento asi el 07, el 15 y el 16/09/2026:
#: cuatro estudiantes, tres intentos cada uno, ~24 minutos por corrida.
MOTIVO_SIN_CURSO_MOODLE = "sin-curso-en-moodle"


def apuntar(
    *,
    identificacion: str,
    cod_periodo: str,
    cod_materia: str,
    num_grupo: str = "",
    fila: int = 0,
    veredicto: Veredicto,
    motivo: str,
    detalle: str = "",
    acciones: list[str] | None = None,
    segundos: float = 0.0,
) -> None:
    """Anota el resultado de UNA unidad de trabajo. Debe sobrevivir al proceso.

    Args:
        fila: fila del reporte (1-based, como en el .xlsx y en el Sheet). Es la
            llave con la que se pinta: el Sheet conserva el orden del .xlsx
            porque se sube ya ordenado A-Z por COD_PERIODO.
    """
    RUTA_RESULTADOS.parent.mkdir(parents=True, exist_ok=True)
    apunte = {
        "momento": datetime.now().isoformat(timespec="seconds"),
        "identificacion": identificacion,
        "cod_periodo": cod_periodo,
        "cod_materia": cod_materia,
        "num_grupo": num_grupo,
        "objetivo": f"{cod_materia}/{num_grupo}" if num_grupo else cod_materia,
        "fila": fila,
        "veredicto": veredicto.value if isinstance(veredicto, Veredicto) else veredicto,
        "motivo": motivo,
        "detalle": detalle[:300],
        "acciones": acciones or [],
        "segundos": segundos,
    }
    with RUTA_RESULTADOS.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(apunte, ensure_ascii=False) + "\n")
        fh.flush()


def leer() -> list[dict]:
    """Todos los apuntes, en orden de escritura. Las lineas corruptas se ignoran."""
    if not RUTA_RESULTADOS.is_file():
        return []
    apuntes = []
    for linea in RUTA_RESULTADOS.read_text(encoding="utf-8").splitlines():
        if not linea.strip():
            continue
        try:
            apuntes.append(json.loads(linea))
        except ValueError:
            continue
    return apuntes


def ultimo_por_unidad() -> dict[tuple[str, str, str], dict]:
    """El apunte MAS RECIENTE de cada (periodo, cedula, materia).

    Una unidad se puede reprocesar -- un reintento, una reparacion -- y lo que
    hay que pintar es como acabo, no como empezo. Al recorrer en orden de
    escritura, el ultimo sobreescribe a los anteriores.
    """
    estado: dict[tuple[str, str, str], dict] = {}
    for apunte in leer():
        clave = (
            apunte.get("cod_periodo", ""),
            apunte.get("identificacion", ""),
            apunte.get("objetivo", ""),
        )
        estado[clave] = apunte
    return estado


def resumen() -> dict[str, int]:
    """Cuenta por veredicto, sobre el estado final de cada unidad."""
    cuenta: dict[str, int] = {}
    for apunte in ultimo_por_unidad().values():
        v = apunte.get("veredicto", "?")
        cuenta[v] = cuenta.get(v, 0) + 1
    return cuenta
