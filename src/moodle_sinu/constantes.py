"""Constantes del proceso: columnas del reporte, colores y etiquetas de validacion.

Todo lo que sea una regla de negocio acordada con el dueno del proceso vive aqui,
para que cambiarla no obligue a tocar la logica.
"""

from __future__ import annotations

from enum import Enum

# ---------------------------------------------------------------------------
# Columnas del reporte exportado de Power BI (hoja "Export")
# Orden y nombres verificados contra una exportacion real (ejemplo.xlsx).
# ---------------------------------------------------------------------------

COL_IDENTIFICACION = "IDENTIFICACION"
COL_NOMBRE_COMPLETO = "NOMBRE_COMPLETO"
COL_CORREO = "CORREO"
COL_CELULAR = "CELULAR"
COL_TELEFONO = "TELEFONO"
COL_COD_UNIDAD = "COD_UNIDAD"
COL_COD_PENSUM = "COD_PENSUM"
COL_COD_MATERIA = "COD_MATERIA"
COL_ID_GRUPO = "ID_GRUPO"
COL_NUM_GRUPO = "NUM_GRUPO"
COL_BLOQUE = "BLOQUE"
COL_PAGO = "PAGO"
COL_COD_PERIODO = "COD_PERIODO"
COL_LLAVE = "LLAVE"
COL_VALIDACION = "VALIDACION"

#: Columnas esperadas, en el orden exacto en que las exporta Power BI (A..O).
COLUMNAS_ESPERADAS: tuple[str, ...] = (
    COL_IDENTIFICACION,
    COL_NOMBRE_COMPLETO,
    COL_CORREO,
    COL_CELULAR,
    COL_TELEFONO,
    COL_COD_UNIDAD,
    COL_COD_PENSUM,
    COL_COD_MATERIA,
    COL_ID_GRUPO,
    COL_NUM_GRUPO,
    COL_BLOQUE,
    COL_PAGO,
    COL_COD_PERIODO,
    COL_LLAVE,
    COL_VALIDACION,
)

#: Columna nueva que escribe la automatizacion. NO se sobrescribe VALIDACION,
#: que es un campo calculado por Power BI con su propio dominio de valores
#: (MATRICULADO / NO_MATRICULADO) y se conserva como dato de origen.
COL_VALIDACION_RPA = "VALIDACION_RPA"

#: Campos obligatorios: si alguno esta vacio la fila se omite del proceso en SINU.
#: Decision del dueno del proceso (21/08/2026): CORREO es obligatorio.
#: Impacto medido en ejemplo.xlsx: 1159 de 1323 filas omitidas (87,6%) por
#: CORREO ausente. Cambiar esta tupla es el unico ajuste necesario si se
#: reconsidera el criterio.
CAMPOS_OBLIGATORIOS: tuple[str, ...] = (
    COL_IDENTIFICACION,
    COL_NOMBRE_COMPLETO,
    COL_CORREO,
    COL_COD_MATERIA,
)

#: Campos que forman la llave de deteccion de duplicados.
CAMPOS_LLAVE_DUPLICADO: tuple[str, ...] = (
    COL_IDENTIFICACION,
    COL_COD_MATERIA,
)

#: Campos que la automatizacion usa como claves de busqueda en SINU.
#: Sirve para distinguir "dato faltante que bloquea la busqueda" de
#: "dato faltante que solo es informativo".
CAMPOS_BUSQUEDA_SINU: tuple[str, ...] = (
    COL_IDENTIFICACION,
    COL_COD_MATERIA,
    COL_COD_PERIODO,
)

#: Texto con el que Power BI abre la fila de pie de la exportacion
#: "Datos con diseno actual". Esa fila no es un registro y se descarta.
MARCADOR_PIE_FILTROS = "Filtros aplicados:"


# ---------------------------------------------------------------------------
# Colores (hex sin '#', formato que espera openpyxl: AARRGGBB o RRGGBB)
# ---------------------------------------------------------------------------


class Color(str, Enum):
    """Paleta acordada para el marcado del reporte."""

    #: Fase 1 - celda con espacios corregidos
    AZUL_CLARO = "ADD8E6"
    #: Fase 1 - celda de campo obligatorio vacio
    NARANJA = "FFA500"
    #: Fase 1 - fila duplicada con datos distintos
    AMARILLO = "FFFF00"
    #: Fase 2 - Caso 1, vinculacion exitosa
    VERDE_CLARO = "90EE90"
    #: Fase 2 - Caso 2, grupo sin integracion a Moodle
    ROJO_CLARO = "FFC7CE"
    #: Fase 2 - Caso 3, sin matricula academica
    LILA = "E6E6FA"

    def __str__(self) -> str:  # pragma: no cover - conveniencia de log
        return self.value


# ---------------------------------------------------------------------------
# Etiquetas de la columna VALIDACION_RPA
# ---------------------------------------------------------------------------


class Validacion(str, Enum):
    """Valores posibles de la columna VALIDACION_RPA."""

    OK = "OK"
    SIN_CHECK_MOODLE = "NO TIENE CHECK EN MOODLE"
    SIN_MATRICULA = "NO CUENTA CON MATRÍCULA"
    PENDIENTE_REVISAR = "PENDIENTE POR REVISAR"

    YA_VINCULADO = "YA VINCULADO"
    """'Curso en moodle?' SI y 'Vinculado?' tambien SI: la vinculacion ya
    estaba hecha antes de que el robot llegara.

    Se etiqueta aparte de OK porque no lo vinculo el robot hoy; mezclarlos
    inflaria el recuento de vinculaciones realizadas.

    OJO: desde el 21/08/2026 esto SI requiere accion. La regla del dueno del
    proceso manda **reciclar** lo ya vinculado (desvincular y volver a
    vincular), no dejarlo como esta. Ver `ejecutor_sinu`."""
    SIN_MARCA_PAGO = "NO CUENTA CON MARCA DE PAGO"
    """Variante del Caso 3 (decision del dueno del proceso, 24/08/2026): sin
    registro en isef07/isef05/pacf50 y, al confirmar en matf88, la materia
    tampoco tiene marca de pago.

    OJO: hoy NADIE produce esta etiqueta. Solo puede salir de consultar matf88,
    que aun no esta implementado. Del reporte no puede venir: la vista de Power
    BI ya viene filtrada a `pago = PAGO`, asi que las 131 filas del 24/08 traen
    todas PAGO y ninguna sin marca."""

    DUPLICADO = "DUPLICADO - VALIDAR ORIGEN"
    DATO_INCOMPLETO = "DATO INCOMPLETO - NO PROCESADO"

    def __str__(self) -> str:  # pragma: no cover - conveniencia de log
        return self.value


class Caso(Enum):
    """Casos del arbol de decision de SINU (Fase 2)."""

    CASO_1_VINCULADO = 1
    CASO_2_SIN_CHECK = 2
    CASO_3_SIN_MATRICULA = 3

    CASO_3_SIN_MARCA_PAGO = 5
    """Variante del Caso 3 en la que matf88 confirma que ademas no hay marca de
    pago. Mismo color que el Caso 3; etiqueta propia."""

    CASO_1_YA_VINCULADO = 4
    """Variante del Caso 1 en la que la vinculacion ya estaba hecha.

    Requiere accion: la regla del 21/08/2026 manda desvincular y volver a
    vincular. Es la unica secuencia que pasa por una accion destructiva, asi
    que la etapa 4 la trata como estado critico."""


#: Mapeo caso -> (color de fila, etiqueta de VALIDACION_RPA).
RESULTADO_POR_CASO: dict[Caso, tuple[Color, Validacion]] = {
    Caso.CASO_1_VINCULADO: (Color.VERDE_CLARO, Validacion.OK),
    Caso.CASO_1_YA_VINCULADO: (Color.VERDE_CLARO, Validacion.YA_VINCULADO),
    Caso.CASO_2_SIN_CHECK: (Color.ROJO_CLARO, Validacion.SIN_CHECK_MOODLE),
    Caso.CASO_3_SIN_MATRICULA: (Color.LILA, Validacion.SIN_MATRICULA),
    Caso.CASO_3_SIN_MARCA_PAGO: (Color.LILA, Validacion.SIN_MARCA_PAGO),
}

#: Casos que requieren ejecutar algo en ISEF07 (etapa 4). Todo lo demas se
#: clasifica y se deja quieto.
#:
#: `CASO_1_YA_VINCULADO` entra aqui desde el 21/08/2026: la regla del dueno del
#: proceso recicla lo ya vinculado en vez de saltarlo. La secuencia concreta la
#: decide `ejecutor_sinu.decidir_secuencia`, porque depende del conjunto de
#: materias del estudiante y no de una fila sola.
CASOS_CON_ACCION: frozenset[Caso] = frozenset(
    {Caso.CASO_1_VINCULADO, Caso.CASO_1_YA_VINCULADO}
)
