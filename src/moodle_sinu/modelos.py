"""Modelos de datos del proceso: fila del reporte, hallazgos y resultado de validacion."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .constantes import (
    COLUMNAS_ESPERADAS,
    COL_COD_MATERIA,
    COL_COD_PERIODO,
    COL_CORREO,
    COL_IDENTIFICACION,
    COL_NOMBRE_COMPLETO,
    COL_NUM_GRUPO,
    Caso,
    Color,
    Validacion,
)


class TipoEspacio(str, Enum):
    """Clase de anomalia de espacios detectada en una celda."""

    INICIO = "inicio"
    FINAL = "final"
    DOBLE_INTERNO = "doble-interno"


class MotivoVacio(str, Enum):
    """Por que un campo obligatorio quedo vacio."""

    CELDA_AUSENTE = "celda-ausente"
    CADENA_VACIA = "cadena-vacia"
    SOLO_ESPACIOS = "solo-espacios"


@dataclass(frozen=True)
class HallazgoCelda:
    """Marca de color a nivel de celda (Fase 1, reglas 1 y 2)."""

    fila: int
    """Numero de fila en el archivo de origen (1-based, incluye encabezado)."""

    columna: str
    """Letra de columna de Excel, p. ej. 'C'."""

    campo: str
    """Nombre de la columna, p. ej. 'CORREO'."""

    color: Color
    detalle: str
    valor_original: str | None = None
    valor_saneado: str | None = None


@dataclass
class FilaReporte:
    """Una fila del reporte, con sus valores crudos y saneados."""

    fila: int
    """Numero de fila en el archivo de origen (1-based)."""

    crudos: dict[str, str | None]
    """Valor tal como venia en el archivo. None = celda ausente."""

    saneados: dict[str, str]
    """Valor tras strip() y colapso de espacios internos. Nunca None."""

    # --- resultado de Fase 1 ---
    omitida: bool = False
    motivo_omision: str | None = None

    # --- resultado de Fase 2 (se llena en la etapa 3) ---
    caso: Caso | None = None
    validacion_rpa: Validacion | None = None
    color_fila: Color | None = None

    def valor(self, campo: str) -> str:
        """Valor saneado de un campo. Cadena vacia si no existe."""
        return self.saneados.get(campo, "")

    # --- claves de negocio ---

    @property
    def identificacion(self) -> str:
        return self.valor(COL_IDENTIFICACION)

    @property
    def nombre(self) -> str:
        return self.valor(COL_NOMBRE_COMPLETO)

    @property
    def correo(self) -> str:
        return self.valor(COL_CORREO)

    @property
    def cod_materia(self) -> str:
        return self.valor(COL_COD_MATERIA)

    @property
    def cod_periodo(self) -> str:
        return self.valor(COL_COD_PERIODO)

    @property
    def num_grupo(self) -> str:
        return self.valor(COL_NUM_GRUPO)

    @property
    def shortname(self) -> str:
        """Llave combinada del curso en Moodle: COD_MATERIA/NUM_GRUPO.

        Campo derivado, no viene como columna en el reporte. Confirmado con el
        dueno del proceso el 21/08/2026 (ejemplo: 'A1I01/50609').
        """
        return f"{self.cod_materia}/{self.num_grupo}"

    @property
    def llave_duplicado(self) -> tuple[str, ...]:
        """Llave de deteccion de duplicados: IDENTIFICACION + COD_MATERIA."""
        return (self.identificacion, self.cod_materia)

    @property
    def huella(self) -> tuple[str, ...]:
        """Huella de la fila saneada, para distinguir duplicado exacto de
        duplicado con datos distintos.

        Se calcula SOLO sobre `COLUMNAS_ESPERADAS`, no sobre todas las claves
        de `saneados`. La diferencia importa al validar un .xlsx que ya paso
        por la Fase 1: ese archivo trae la columna VALIDACION_RPA, cuyo texto
        es distinto en cada aparicion de un duplicado exacto ('' en la primera,
        'OMITIDA: duplicado exacto...' en las demas). Con la huella sobre todas
        las claves, la segunda pasada veia datos distintos donde los habia
        identicos y marcaba en amarillo filas perfectamente procesables.
        """
        return tuple(self.saneados.get(c, "") for c in COLUMNAS_ESPERADAS)


@dataclass
class ResultadoValidacion:
    """Salida completa de la Fase 1 sobre un reporte."""

    archivo: str
    hoja: str
    filas: list[FilaReporte] = field(default_factory=list)
    hallazgos: list[HallazgoCelda] = field(default_factory=list)
    filas_pie_descartadas: list[int] = field(default_factory=list)
    advertencias: list[str] = field(default_factory=list)

    @property
    def total_filas(self) -> int:
        return len(self.filas)

    @property
    def procesables(self) -> list[FilaReporte]:
        """Filas que siguen al arbol de decision de SINU."""
        return [f for f in self.filas if not f.omitida]

    @property
    def omitidas(self) -> list[FilaReporte]:
        return [f for f in self.filas if f.omitida]

    def hallazgos_por_color(self, color: Color) -> list[HallazgoCelda]:
        return [h for h in self.hallazgos if h.color is color]

    def filas_afectadas(self, color: Color) -> set[int]:
        return {h.fila for h in self.hallazgos_por_color(color)}
