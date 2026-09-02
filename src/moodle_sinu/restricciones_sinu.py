"""Matriz de permisos sobre el sistema academico. Barrera de seguridad.

Decision del dueno del proceso (21/08/2026), sin excepciones:

    Modulo   Lectura / consulta   Escritura / procesamiento
    -------  -------------------  -------------------------
    isef07   si                   SI  (unico)
    isef05   si                   NO
    pacf50   si                   NO
    matf88   si                   NO

Los codigos van en minuscula porque asi los expone el sistema. La comparacion
es indiferente a mayusculas, de modo que pasar 'ISEF07' sigue funcionando.

El robot **puede entrar y navegar** en los cuatro para verificar matriculas,
consultar grillas y revisar el estado de los checks. Lo que no puede es pulsar
nada que procese, vincule, desvincule, guarde o modifique fuera de ISEF07: esos
tres modulos funcionan en modo "solo ver".

Por que dos listas y no una
---------------------------
Antes solo existia la lista blanca de escritura, y la de lectura era implicita:
"lo que no esta prohibido escribir, se puede leer". Eso mezclaba dos permisos
distintos y hacia imposible expresar "puedo consultar este modulo pero no
tocarlo". Ahora cada permiso tiene su lista y su guarda:

- `exigir_modulo_legible()`  antes de entrar o navegar en un modulo.
- `exigir_modulo_escribible()` antes de ejecutar cualquier accion.

Ambas son **listas blancas**: un modulo que no aparezca se bloquea por defecto,
de modo que anadir modulos al sistema no abre agujeros por omision. El coste de
equivocarse es alterar matriculas reales de estudiantes.
"""

from __future__ import annotations

from .constantes_sinu import (
    ACTIVIDAD_INTEGRACION_MASIVA,
    ACTIVIDAD_MATRICULA,
    ACTIVIDAD_PROGRAMACION_GRUPOS,
    ACTIVIDAD_VINCULACION,
)

# ---------------------------------------------------------------------------
# Las dos listas blancas
# ---------------------------------------------------------------------------

#: Modulos en los que el robot puede entrar, navegar y consultar.
MODULOS_LEGIBLES: frozenset[str] = frozenset(
    {
        ACTIVIDAD_VINCULACION,  # ISEF07 - grillas Estudiantes y Grupos
        ACTIVIDAD_INTEGRACION_MASIVA,  # ISEF05 - verificacion de casos 2 y 3
        ACTIVIDAD_PROGRAMACION_GRUPOS,  # PACF50 - verificacion de casos 2 y 3
        ACTIVIDAD_MATRICULA,  # ISEF88 - verificacion del caso 3
    }
)

#: Modulos en los que el robot puede ejecutar acciones. Uno solo.
MODULOS_ESCRIBIBLES: frozenset[str] = frozenset({ACTIVIDAD_VINCULACION})

#: Derivado, no escrito a mano: asi las dos listas no pueden desincronizarse.
MODULOS_SOLO_LECTURA: frozenset[str] = MODULOS_LEGIBLES - MODULOS_ESCRIBIBLES

#: Un modulo escribible que no fuera legible seria un error de modelado.
assert MODULOS_ESCRIBIBLES <= MODULOS_LEGIBLES, (
    "Hay modulos con permiso de escritura y sin permiso de lectura: "
    f"{sorted(MODULOS_ESCRIBIBLES - MODULOS_LEGIBLES)}"
)

#: Verbos que el dueno del proceso enumero como prohibidos fuera de ISEF07.
#: Se usan en los mensajes de error para que quede claro que se bloqueo.
ACCIONES_DE_ESCRITURA: tuple[str, ...] = (
    "procesar",
    "vincular",
    "desvincular",
    "guardar",
    "modificar",
)


class ErrorRestriccionOperativa(RuntimeError):
    """Se intento algo que la matriz de permisos no autoriza.

    No es un fallo tecnico: es la barrera haciendo su trabajo. Nunca se debe
    capturar para "seguir de todos modos".
    """


def _normalizar(modulo: str) -> str:
    """Codigo en minuscula, que es como lo expone el sistema."""
    return (modulo or "").strip().lower()


def exigir_modulo_legible(modulo: str, accion: str = "consultar") -> None:
    """Autoriza entrar o navegar en un modulo, o aborta.

    Args:
        modulo: codigo de la actividad (p. ej. 'ISEF05').
        accion: que se iba a consultar, para que el mensaje sea util.

    Raises:
        ErrorRestriccionOperativa: si el modulo no esta en la lista de lectura.
    """
    codigo = _normalizar(modulo)
    if codigo in MODULOS_LEGIBLES:
        return

    raise ErrorRestriccionOperativa(
        f"BLOQUEADO: se intento '{accion}' en '{modulo}', que no esta en la "
        "lista de modulos consultables "
        f"({', '.join(sorted(MODULOS_LEGIBLES))}). Los modulos no autorizados "
        "se bloquean por defecto: para habilitarlo hace falta una decision "
        "explicita del dueno del proceso."
    )


def exigir_modulo_escribible(modulo: str, accion: str) -> None:
    """Autoriza una accion que modifica el sistema, o aborta.

    Args:
        modulo: codigo de la actividad (p. ej. 'ISEF07').
        accion: que se iba a hacer ('Vincular grupos matriculados').

    Raises:
        ErrorRestriccionOperativa: si el modulo no admite escritura.
    """
    codigo = _normalizar(modulo)

    if codigo in MODULOS_ESCRIBIBLES:
        return

    if codigo in MODULOS_SOLO_LECTURA:
        raise ErrorRestriccionOperativa(
            f"BLOQUEADO: se intento '{accion}' en {codigo}, que es de SOLO "
            "LECTURA por decision del dueno del proceso (21/08/2026). Ahi esta "
            "prohibido "
            f"{', '.join(ACCIONES_DE_ESCRITURA)}. Consultarlo si esta "
            f"permitido; modificarlo no. Unico modulo escribible: "
            f"{', '.join(sorted(MODULOS_ESCRIBIBLES))}."
        )

    raise ErrorRestriccionOperativa(
        f"BLOQUEADO: se intento '{accion}' en un modulo no reconocido "
        f"('{modulo}'). Solo se permite escribir en "
        f"{', '.join(sorted(MODULOS_ESCRIBIBLES))}; cualquier otro se trata "
        "como prohibido hasta que se autorice de forma explicita."
    )


def es_legible(modulo: str) -> bool:
    """True si el robot puede entrar y consultar el modulo."""
    return _normalizar(modulo) in MODULOS_LEGIBLES


def es_escribible(modulo: str) -> bool:
    """True si el robot puede ejecutar acciones en el modulo."""
    return _normalizar(modulo) in MODULOS_ESCRIBIBLES


def es_solo_lectura(modulo: str) -> bool:
    """True si el modulo se puede consultar pero no modificar."""
    return _normalizar(modulo) in MODULOS_SOLO_LECTURA


def resumen_permisos() -> str:
    """Tabla de permisos, para dejarla en el log de cada corrida.

    Que la matriz efectiva aparezca en el log es lo que permite auditar despues
    con que permisos corrio el robot, sin fiarse de lo que diga el README.
    """
    lineas = ["Matriz de permisos en SINU:", "  MODULO   LECTURA  ESCRITURA"]
    for modulo in sorted(MODULOS_LEGIBLES):
        escribe = "SI" if es_escribible(modulo) else "no"
        lineas.append(f"  {modulo:<8} {'si':<8} {escribe}")
    return "\n".join(lineas)
