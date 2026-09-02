"""Etapa 3: clasificacion de casos leyendo ISEF07. SOLO LECTURA.

Decision del dueno del proceso (21/08/2026): la prioridad es la precision de la
clasificacion en el Excel, no la velocidad. Por tanto SI se leen los checks
"Curso en moodle?" y "Vinculado?" de cada asignatura, y de ahi salen los colores
del reporte.

Como encajan las dos unidades de trabajo
----------------------------------------
La skill de negocio y el arbol de decision parecian incompatibles, pero hablan
de cosas distintas:

- **Navegar es por estudiante.** ISEF07 se filtra por cedula; al seleccionar la
  fila, la grilla "Grupos" carga TODAS sus asignaturas del periodo activo. Son
  84 busquedas, no 164.
- **Clasificar es por asignatura.** Esa misma grilla trae una fila por
  asignatura con sus dos checks, asi que de una sola busqueda salen todas las
  clasificaciones de ese estudiante.

Resultado: precision completa (164 filas clasificadas) al coste de navegacion
del enfoque por estudiante.

Esta etapa no escribe NADA en el sistema
----------------------------------------
No toca el desplegable "Accion a realizar" ni el icono de ejecutar. No importa
siquiera la funcion que los usaria. La barrera de `restricciones_sinu.py`
protege la etapa 4; aqui la garantia es estructural: el codigo de escritura no
existe en este modulo.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from .constantes import (
    CASOS_CON_ACCION,
    RESULTADO_POR_CASO,
    Caso,
    Color,
    Validacion,
)
from .constantes_sinu import (
    ACTIVIDAD_INTEGRACION_MASIVA,
    ACTIVIDAD_MATRICULA,
    ACTIVIDAD_PROGRAMACION_GRUPOS,
)
from .modelos import FilaReporte
from .restricciones_sinu import MODULOS_LEGIBLES

log = logging.getLogger(__name__)

#: Modulos que hay que CONSULTAR para confirmar cada caso, segun el arbol de
#: decision de la Fase 2. Son consultas de solo lectura: la barrera de
#: `restricciones_sinu` sigue prohibiendo escribir en todos ellos salvo ISEF07.
MODULOS_VERIFICACION_POR_CASO: dict[Caso, tuple[str, ...]] = {
    Caso.CASO_1_VINCULADO: (),
    Caso.CASO_1_YA_VINCULADO: (),
    Caso.CASO_2_SIN_CHECK: (ACTIVIDAD_INTEGRACION_MASIVA, ACTIVIDAD_PROGRAMACION_GRUPOS),
    Caso.CASO_3_SIN_MATRICULA: (
        ACTIVIDAD_INTEGRACION_MASIVA,
        ACTIVIDAD_PROGRAMACION_GRUPOS,
        ACTIVIDAD_MATRICULA,
    ),
    Caso.CASO_3_SIN_MARCA_PAGO: (
        ACTIVIDAD_INTEGRACION_MASIVA,
        ACTIVIDAD_PROGRAMACION_GRUPOS,
        ACTIVIDAD_MATRICULA,
    ),
}

#: Si el arbol pidiera consultar un modulo que la matriz de permisos no
#: autoriza, es un error de configuracion y no algo que descubrir a mitad de una
#: corrida.
assert all(
    modulo in MODULOS_LEGIBLES
    for modulos in MODULOS_VERIFICACION_POR_CASO.values()
    for modulo in modulos
), "El arbol de decision pide consultar modulos fuera de MODULOS_LEGIBLES"


@dataclass(frozen=True)
class FilaGrupoSinu:
    """Una fila de la grilla "Grupos" de ISEF07, ya leida.

    Es el unico dato que la etapa 3 saca del sistema. Se modela aparte del
    navegador para que el arbol de decision sea una funcion pura y se pueda
    probar sin abrir Chromium.
    """

    cod_materia: str
    num_grupo: str = ""
    curso_en_moodle: bool = False
    vinculado: bool = False
    texto_crudo: str = ""
    """La fila tal como se leyo, como evidencia si hay que auditar."""

    @property
    def shortname(self) -> str:
        """Llave combinada del curso en Moodle: COD_MATERIA/NUM_GRUPO."""
        return f"{self.cod_materia}/{self.num_grupo}"


@dataclass(frozen=True)
class Clasificacion:
    """Resultado de clasificar una fila del reporte."""

    caso: Caso
    validacion: Validacion
    color: Color
    detalle: str

    grupo_sinu: FilaGrupoSinu | None = None
    """La fila de la grilla con la que se caso, si hubo alguna."""

    requiere_accion: bool = False
    """True solo si la etapa 4 debe ejecutar la vinculacion."""

    ambiguo: bool = False
    """True si el emparejamiento no fue exacto y conviene revisarlo a mano."""

    modulos_a_verificar: tuple[str, ...] = ()
    """Modulos que el arbol manda CONSULTAR para confirmar este caso. Solo
    lectura: la barrera sigue prohibiendo escribir en ellos."""


@dataclass
class ResultadoEstudiante:
    """Lo leido para un estudiante y la clasificacion de sus filas."""

    identificacion: str
    cod_periodo: str
    grupos_leidos: list[FilaGrupoSinu] = field(default_factory=list)
    clasificaciones: dict[int, Clasificacion] = field(default_factory=dict)
    """Por numero de fila del reporte."""

    advertencias: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Lectura de los checks
# ---------------------------------------------------------------------------

#: Formas en que una grilla puede expresar "marcado". Se cubren varias porque el
#: valor puede llegar del aria-checked, del texto de la celda o de un titulo.
_MARCADO = re.compile(r"^(true|1|s[íi]|si|yes|x|checked|marcado|activo)$", re.IGNORECASE)
_DESMARCADO = re.compile(r"^(false|0|no|unchecked|desmarcado|inactivo|)$", re.IGNORECASE)


def interpretar_check(valor: str | bool | None) -> bool | None:
    """Normaliza el valor de un check. None si no se pudo interpretar.

    Devolver None y no False es deliberado: un check ilegible NO es un check
    desmarcado. Confundirlos convertiria un dato ausente en un Caso 2 ("no tiene
    check en Moodle") y el reporte afirmaria algo que no se comprobo.
    """
    if isinstance(valor, bool):
        return valor
    if valor is None:
        return None

    texto = str(valor).strip()
    if _MARCADO.match(texto):
        return True
    if _DESMARCADO.match(texto):
        return False
    return None


# ---------------------------------------------------------------------------
# Emparejamiento fila del reporte <-> fila de la grilla
# ---------------------------------------------------------------------------


def emparejar(
    fila: FilaReporte, grupos: list[FilaGrupoSinu]
) -> tuple[FilaGrupoSinu | None, bool]:
    """Busca en la grilla la asignatura de una fila del reporte.

    Devuelve (grupo, ambiguo). Se prefiere el `shortname` completo
    (COD_MATERIA/NUM_GRUPO) porque un estudiante puede tener la misma materia en
    dos grupos distintos; casar solo por materia elegiria uno al azar. Si no hay
    coincidencia exacta pero si por materia, se devuelve marcada como ambigua en
    vez de descartarla: el operador decide.
    """
    exactos = [g for g in grupos if g.shortname == fila.shortname]
    if len(exactos) == 1:
        return exactos[0], False
    if len(exactos) > 1:
        # La grilla trae el mismo curso dos veces: no se elige por nuestra cuenta.
        return exactos[0], True

    por_materia = [g for g in grupos if g.cod_materia == fila.cod_materia]
    if len(por_materia) == 1:
        return por_materia[0], True
    if len(por_materia) > 1:
        return None, True
    return None, False


# ---------------------------------------------------------------------------
# El arbol de decision
# ---------------------------------------------------------------------------


def clasificar_fila(fila: FilaReporte, grupos: list[FilaGrupoSinu]) -> Clasificacion:
    """Aplica el arbol de decision de la Fase 2 a una fila del reporte.

    | Condicion en la grilla Grupos            | Caso | Color   |
    |------------------------------------------|------|---------|
    | Curso en moodle? SI, Vinculado? NO       | 1    | verde   |
    | Curso en moodle? SI, Vinculado? SI       | 1-ya | verde   |
    | Curso en moodle? NO                      | 2    | rojo    |
    | La asignatura no figura en la grilla     | 3    | lila    |

    Nunca escribe en el sistema: solo interpreta lo leido.
    """
    grupo, ambiguo = emparejar(fila, grupos)

    if grupo is None:
        # Sin registro en la grilla del periodo activo: no hay matricula que
        # vincular. La confirmacion en ISEF05/PACF50/ISEF88 es un paso aparte y
        # de solo lectura (ver restricciones_sinu).
        color, validacion = RESULTADO_POR_CASO[Caso.CASO_3_SIN_MATRICULA]
        detalle = (
            f"'{fila.shortname}' no figura en la grilla Grupos del periodo "
            f"{fila.cod_periodo}"
        )
        if ambiguo:
            detalle += " (hay varias filas con esa materia y ningun shortname casa)"
        return Clasificacion(
            caso=Caso.CASO_3_SIN_MATRICULA,
            validacion=validacion,
            color=color,
            detalle=detalle,
            ambiguo=ambiguo,
            modulos_a_verificar=MODULOS_VERIFICACION_POR_CASO[Caso.CASO_3_SIN_MATRICULA],
        )

    if not grupo.curso_en_moodle:
        color, validacion = RESULTADO_POR_CASO[Caso.CASO_2_SIN_CHECK]
        return Clasificacion(
            caso=Caso.CASO_2_SIN_CHECK,
            validacion=validacion,
            color=color,
            detalle=f"'{grupo.shortname}' sin check 'Curso en moodle?'",
            grupo_sinu=grupo,
            ambiguo=ambiguo,
            modulos_a_verificar=MODULOS_VERIFICACION_POR_CASO[Caso.CASO_2_SIN_CHECK],
        )

    if grupo.vinculado:
        caso = Caso.CASO_1_YA_VINCULADO
        color, validacion = RESULTADO_POR_CASO[caso]
        return Clasificacion(
            caso=caso,
            validacion=validacion,
            color=color,
            detalle=(
                f"'{grupo.shortname}' ya estaba vinculado; se reciclara "
                "(desvincular y volver a vincular)"
            ),
            grupo_sinu=grupo,
            requiere_accion=caso in CASOS_CON_ACCION,
            ambiguo=ambiguo,
            modulos_a_verificar=MODULOS_VERIFICACION_POR_CASO[caso],
        )

    caso = Caso.CASO_1_VINCULADO
    color, validacion = RESULTADO_POR_CASO[caso]
    return Clasificacion(
        caso=caso,
        validacion=validacion,
        color=color,
        detalle=f"'{grupo.shortname}' listo para vincular",
        grupo_sinu=grupo,
        requiere_accion=caso in CASOS_CON_ACCION,
        ambiguo=ambiguo,
        modulos_a_verificar=MODULOS_VERIFICACION_POR_CASO[caso],
    )


def clasificar_estudiante(
    filas: list[FilaReporte],
    grupos: list[FilaGrupoSinu],
    *,
    identificacion: str,
    cod_periodo: str,
) -> ResultadoEstudiante:
    """Clasifica todas las filas de un estudiante con una sola lectura.

    Es la ganancia del diseno: una busqueda en ISEF07 por estudiante, y de la
    grilla que se carga salen las clasificaciones de todas sus asignaturas.
    """
    resultado = ResultadoEstudiante(
        identificacion=identificacion,
        cod_periodo=cod_periodo,
        grupos_leidos=list(grupos),
    )

    if not grupos:
        resultado.advertencias.append(
            f"La grilla Grupos de {identificacion} llego vacia en el periodo "
            f"{cod_periodo}: todas sus filas quedan como Caso 3."
        )

    for fila in filas:
        clasificacion = clasificar_fila(fila, grupos)
        resultado.clasificaciones[fila.fila] = clasificacion
        if clasificacion.ambiguo:
            resultado.advertencias.append(
                f"Fila {fila.fila} ({fila.shortname}): emparejamiento ambiguo — "
                f"{clasificacion.detalle}"
            )
    return resultado


def aplicar_a_filas(
    filas: list[FilaReporte], resultado: ResultadoEstudiante
) -> None:
    """Escribe la clasificacion en las FilaReporte, para el .xlsx y el Sheet.

    Rellena `caso`, `validacion_rpa` y `color_fila`, que son los campos que ya
    consume `salida_excel.escribir_copia_coloreada`. No hay logica de color
    nueva: la de la Fase 1 ya sabia pintar filas por caso.
    """
    for fila in filas:
        clasificacion = resultado.clasificaciones.get(fila.fila)
        if clasificacion is None:
            continue
        fila.caso = clasificacion.caso
        fila.validacion_rpa = clasificacion.validacion
        fila.color_fila = clasificacion.color


def marcar_pendiente_revisar(fila: FilaReporte, motivo: str) -> None:
    """Marca una fila que no se pudo clasificar.

    El arbol reserva `PENDIENTE POR REVISAR` para los fallos de selector o de
    interfaz. No se le asigna color de fila: el reporte no debe afirmar un caso
    que no se comprobo.
    """
    fila.validacion_rpa = Validacion.PENDIENTE_REVISAR
    fila.caso = None
    fila.color_fila = None
    log.warning("Fila %d pendiente por revisar: %s", fila.fila, motivo)
