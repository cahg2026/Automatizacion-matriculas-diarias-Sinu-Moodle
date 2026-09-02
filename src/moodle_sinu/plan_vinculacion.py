"""Plan de trabajo en SINU: de filas del reporte a operaciones de ISEF07.

Traduce el resultado de la Fase 1 en la lista de cosas que hay que hacer en el
sistema academico, siguiendo dos reglas que vienen de la skill de negocio
`cun-sigwt-matricula` y que NO son evidentes desde el reporte:

1. **La unidad de trabajo es el estudiante, no la fila.** El reporte trae una
   fila por asignatura matriculada, pero "Vincular grupos matriculados" de
   ISEF07 actua sobre el estudiante completo: vincula de golpe todas sus
   asignaturas del periodo activo. Procesar por fila repetiria el mismo
   estudiante una vez por materia, y cada repeticion cuesta 15-40 s.

2. **El filtro de Periodo se fija una sola vez por sesion.** Por eso el trabajo
   se agrupa por `COD_PERIODO`: cada lote es una sesion de ISEF07 con su periodo
   ya fijado. La referencia marca como error comun trabajar con una hoja que
   mezcla periodos.

Se conserva el **orden de aparicion** en el reporte, como pide la referencia:
asi una corrida interrumpida se puede reanudar donde se quedo comparando contra
el reporte original.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .constantes_sinu import (
    SEG_EJECUCION_VINCULACION,
    SEG_FILTRO_CEDULA,
)
from .modelos import FilaReporte, ResultadoValidacion


@dataclass(frozen=True)
class OperacionSinu:
    """Un estudiante a procesar dentro de un periodo: una pasada por ISEF07."""

    identificacion: str
    nombre: str
    cod_periodo: str

    filas: tuple[int, ...] = ()
    """Filas del reporte que cubre esta operacion (1-based, como en el .xlsx)."""

    materias: tuple[str, ...] = ()
    """COD_MATERIA de esas filas. Informativo: ISEF07 vincula todas las
    asignaturas del periodo, no una a una."""

    @property
    def n_materias(self) -> int:
        return len(self.materias)


@dataclass
class LotePeriodo:
    """Todas las operaciones de un mismo periodo: una sesion de ISEF07."""

    cod_periodo: str
    operaciones: list[OperacionSinu] = field(default_factory=list)

    @property
    def n_estudiantes(self) -> int:
        return len(self.operaciones)

    @property
    def n_filas(self) -> int:
        return sum(len(o.filas) for o in self.operaciones)

    @property
    def cedulas(self) -> list[str]:
        """Cedulas unicas, en orden de aparicion en el reporte."""
        return [o.identificacion for o in self.operaciones]


@dataclass
class PlanVinculacion:
    """El trabajo completo derivado de un reporte validado."""

    lotes: list[LotePeriodo] = field(default_factory=list)
    sin_periodo: list[OperacionSinu] = field(default_factory=list)
    """Operaciones cuyo COD_PERIODO viene vacio: no se puede fijar el filtro de
    Periodo, asi que no son ejecutables sin intervencion."""

    @property
    def n_operaciones(self) -> int:
        return sum(lote.n_estudiantes for lote in self.lotes)

    @property
    def n_filas_cubiertas(self) -> int:
        return sum(lote.n_filas for lote in self.lotes)

    @property
    def n_periodos(self) -> int:
        return len(self.lotes)

    @property
    def cedulas_unicas(self) -> list[str]:
        """Cedulas distintas del plan, en orden de aparicion.

        Puede ser menor que `n_operaciones`: un estudiante matriculado en dos
        periodos necesita una operacion en cada sesion.
        """
        vistas: dict[str, None] = {}
        for lote in self.lotes:
            for op in lote.operaciones:
                vistas.setdefault(op.identificacion, None)
        return list(vistas)


def extraer_cedulas(filas: list[FilaReporte]) -> list[str]:
    """Cedulas unicas en orden de aparicion.

    Equivale a `scripts/extract_cedulas.py` de la skill, pero sobre filas ya
    parseadas por `lector_reporte`. La diferencia importa: el script original
    lee la columna en crudo y, sobre una exportacion de Power BI, se traga la
    fila de pie 'Filtros aplicados:' como si fuera una cedula (comprobado el
    21/08/2026: devolvia 237 cedulas, una de ellas 'pago es PAGO'). Nuestro
    parser ya descarta ese pie y ademas normaliza los numericos, de modo que
    50609.0 no se cuela como '50609.0'.
    """
    vistas: dict[str, None] = {}
    for fila in filas:
        cedula = fila.identificacion
        if cedula:
            vistas.setdefault(cedula, None)
    return list(vistas)


def construir_plan(resultado: ResultadoValidacion) -> PlanVinculacion:
    """Agrupa las filas procesables en operaciones de ISEF07 por periodo.

    Solo entran las filas procesables: las que la Fase 1 omitio (campo
    obligatorio vacio, duplicado con datos distintos) no van a SINU.
    """
    # (periodo, cedula) -> operacion en construccion. Un dict normal conserva el
    # orden de insercion, que es justo el orden de aparicion que hay que mantener.
    acumulado: dict[tuple[str, str], dict] = {}

    for fila in resultado.procesables:
        cedula = fila.identificacion
        if not cedula:
            # No deberia pasar: IDENTIFICACION es obligatorio y la Fase 1 ya
            # omitio las filas sin el. Se ignora en vez de romper el plan.
            continue
        clave = (fila.cod_periodo, cedula)
        entrada = acumulado.setdefault(
            clave,
            {"nombre": fila.nombre, "filas": [], "materias": []},
        )
        entrada["filas"].append(fila.fila)
        if fila.cod_materia:
            entrada["materias"].append(fila.cod_materia)

    lotes: dict[str, LotePeriodo] = {}
    sin_periodo: list[OperacionSinu] = []

    for (periodo, cedula), datos in acumulado.items():
        operacion = OperacionSinu(
            identificacion=cedula,
            nombre=datos["nombre"],
            cod_periodo=periodo,
            filas=tuple(datos["filas"]),
            materias=tuple(datos["materias"]),
        )
        if not periodo:
            sin_periodo.append(operacion)
            continue
        lotes.setdefault(periodo, LotePeriodo(cod_periodo=periodo)).operaciones.append(
            operacion
        )

    # Los lotes se ordenan por COD_PERIODO de la A a la Z (decision del dueno
    # del proceso, 24/08/2026). Es el mismo orden que queda en el Google Sheet
    # al ordenar esa columna, de modo que el operador puede seguir la corrida
    # mirando la tabla.
    #
    # El orden sale de aqui y NO de releer el Sheet ya ordenado: es
    # determinista, se puede probar sin navegador y no depende de que una accion
    # de la interfaz de Sheets haya funcionado. Si el orden dependiera de la UI
    # y esta fallara en silencio, se procesaria en un orden equivocado sin que
    # nadie se enterase.
    ordenados = sorted(lotes.values(), key=lambda l: l.cod_periodo)
    return PlanVinculacion(lotes=ordenados, sin_periodo=sin_periodo)


def estimar_duracion(n_operaciones: int) -> tuple[int, int]:
    """Segundos minimo y maximo que tardaria ejecutar n operaciones.

    Sale de los tiempos observados en la referencia: 1-2 s por filtrar la cedula
    y 15-40 s por la ejecucion, segun cuantas asignaturas tenga el estudiante.
    Sirve para cumplir la convencion de la skill: antes de lanzar un lote largo,
    decirle al operador cuantos registros hay y cuanto va a tardar.
    """
    minimo = n_operaciones * (SEG_FILTRO_CEDULA[0] + SEG_EJECUCION_VINCULACION[0])
    maximo = n_operaciones * (SEG_FILTRO_CEDULA[1] + SEG_EJECUCION_VINCULACION[1])
    return minimo, maximo


def _hhmm(segundos: int) -> str:
    minutos, seg = divmod(segundos, 60)
    if minutos < 60:
        return f"{minutos}m {seg:02d}s"
    horas, minutos = divmod(minutos, 60)
    return f"{horas}h {minutos:02d}m"


def formatear_plan(plan: PlanVinculacion) -> str:
    """Resumen legible del plan, para decidir antes de tocar SINU."""
    lineas: list[str] = []
    ancho = 78
    lineas.append("=" * ancho)
    lineas.append("PLAN DE VINCULACION EN SINU (ISEF07)")
    lineas.append("=" * ancho)

    minimo, maximo = estimar_duracion(plan.n_operaciones)
    lineas.append(f"Operaciones (estudiante x periodo): {plan.n_operaciones}")
    lineas.append(f"  cubren {plan.n_filas_cubiertas} filas procesables del reporte")
    lineas.append(f"  estudiantes distintos            : {len(plan.cedulas_unicas)}")
    lineas.append(f"Sesiones de ISEF07 (una por periodo): {plan.n_periodos}")
    lineas.append(f"Duracion estimada: entre {_hhmm(minimo)} y {_hhmm(maximo)}")
    lineas.append("")
    lineas.append("Los lotes van en orden A-Z de COD_PERIODO: el primero es el")
    lineas.append("'periodo actual' con el que arranca la corrida. Al pasar de un")
    lineas.append("lote al siguiente hay que cambiar el filtro de Periodo en ISEF07.")
    lineas.append("")
    lineas.append(f"{'PERIODO':<10} {'ESTUD.':>7} {'FILAS':>7}  PRIMERAS CEDULAS")
    lineas.append("-" * ancho)
    for lote in plan.lotes:
        muestra = ", ".join(lote.cedulas[:3])
        if lote.n_estudiantes > 3:
            muestra += f", ... (+{lote.n_estudiantes - 3})"
        lineas.append(
            f"{lote.cod_periodo:<10} {lote.n_estudiantes:>7} {lote.n_filas:>7}  {muestra}"
        )

    multiples = [
        op for lote in plan.lotes for op in lote.operaciones if op.n_materias > 1
    ]
    if multiples:
        lineas.append("")
        lineas.append(
            f"{len(multiples)} estudiantes traen mas de una asignatura "
            f"(maximo {max(o.n_materias for o in multiples)})."
        )
        lineas.append(
            "ISEF07 las vincula todas de una vez, asi que son UNA operacion, "
            "no una por materia."
        )

    if plan.sin_periodo:
        lineas.append("")
        lineas.append(f"!! {len(plan.sin_periodo)} operaciones SIN COD_PERIODO:")
        lineas.append("   no se puede fijar el filtro de Periodo, asi que quedan fuera")
        lineas.append("   del plan automatico. Revisar a mano:")
        for op in plan.sin_periodo[:10]:
            lineas.append(f"     {op.identificacion}  {op.nombre[:40]}")

    lineas.append("=" * ancho)
    return "\n".join(lineas)
