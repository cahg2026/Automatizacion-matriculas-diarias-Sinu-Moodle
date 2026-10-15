"""La tabla dinamica por shortname: quien decide a que grupos se pregunta.

Es logica pura y por eso se prueba aqui entera. La decision que toma -- "este
grupo mueve 120 filas, preguntale a ISEF05 antes de tocar ISEF07" -- vale horas
de gestion, y equivocarse en ella no da error: da un dia largo.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from moodle_sinu import tabla_grupos  # noqa: E402


@dataclass(frozen=True)
class OpFalsa:
    """Lo minimo que `construir` necesita de una OperacionSinu."""

    identificacion: str
    cod_periodo: str
    cod_materia: str
    num_grupo: str
    fila: int = 0

    @property
    def objetivo(self) -> str:
        return f"{self.cod_materia}/{self.num_grupo}" if self.num_grupo else self.cod_materia


def _ops(*definiciones) -> list[OpFalsa]:
    """(materia, grupo, cuantos estudiantes) -> operaciones con cedulas unicas."""
    salida: list[OpFalsa] = []
    n = 0
    for materia, grupo, cuantos in definiciones:
        for _ in range(cuantos):
            n += 1
            salida.append(OpFalsa(f"ced{n:04d}", "26V05", materia, grupo, fila=n + 1))
    return salida


# ---------------------------------------------------------------------------
# Agrupacion
# ---------------------------------------------------------------------------


def test_agrupa_por_shortname_no_por_materia():
    """TI010/55570 y TI010/55571 son dos cursos, no uno.

    Es la misma razon que en `indizar_por_shortname`: el curso de MOODLE se
    llama COD_MATERIA/NUM_GRUPO. Fundirlos por materia diria que un grupo mueve
    el doble de filas de las que mueve, y mandaria a verificar a ciegas.
    """
    tabla = tabla_grupos.construir(_ops(("TI010", "55570", 3), ("TI010", "55571", 2)))
    assert tabla.n_grupos == 2
    assert [g.shortname for g in tabla.grupos] == ["TI010/55570", "TI010/55571"]


def test_orden_de_mayor_a_menor():
    """El grupo que mas mueve se pregunta primero: si resulta sin curso, es el
    que mas dia ahorra."""
    tabla = tabla_grupos.construir(
        _ops(("AAA", "1", 5), ("BBB", "2", 120), ("CCC", "3", 44))
    )
    assert [g.shortname for g in tabla.grupos] == ["BBB/2", "CCC/3", "AAA/1"]
    assert [g.n_filas for g in tabla.grupos] == [120, 44, 5]


def test_empate_ordena_por_shortname():
    """Estable a proposito: dos corridas del mismo reporte tienen que preguntar
    en el mismo orden para poder comparar sus logs."""
    tabla = tabla_grupos.construir(_ops(("ZZZ", "9", 4), ("AAA", "1", 4)))
    assert [g.shortname for g in tabla.grupos] == ["AAA/1", "ZZZ/9"]


def test_las_filas_sin_grupo_no_inventan_shortname():
    """Sin NUM_GRUPO no hay curso por el que preguntar en ISEF05. Se cuentan
    aparte en vez de mezclarse con un grupo real."""
    ops = _ops(("TI010", "55570", 2))
    ops.append(OpFalsa("ced999", "26V05", "TI010", "", fila=99))
    ops.append(OpFalsa("ced998", "26V05", "", "", fila=98))
    tabla = tabla_grupos.construir(ops)
    assert tabla.n_grupos == 1
    assert tabla.sin_shortname == 2
    assert tabla.n_filas == 2


def test_estudiantes_distintos_de_filas():
    """Un estudiante con dos filas del MISMO grupo cuenta como dos filas de
    trabajo y un solo estudiante. La diferencia es un dato a mirar en origen."""
    ops = [
        OpFalsa("111", "26V05", "TI010", "55570", fila=2),
        OpFalsa("111", "26V05", "TI010", "55570", fila=3),
        OpFalsa("222", "26V05", "TI010", "55570", fila=4),
    ]
    tabla = tabla_grupos.construir(ops)
    assert tabla.grupos[0].n_filas == 3
    assert tabla.grupos[0].n_estudiantes == 2


def test_guarda_las_filas_del_reporte():
    """Para poder ir a verlas en el .xlsx sin volver a recorrerlo."""
    tabla = tabla_grupos.construir(
        [
            OpFalsa("111", "26V05", "TI010", "55570", fila=7),
            OpFalsa("222", "26V05", "TI010", "55570", fila=3),
        ]
    )
    assert tabla.grupos[0].filas_reporte == (3, 7)


# ---------------------------------------------------------------------------
# El umbral de verificacion
# ---------------------------------------------------------------------------


def test_a_verificar_respeta_el_umbral():
    tabla = tabla_grupos.construir(
        _ops(("GRANDE", "1", 120), ("MEDIANO", "2", 30), ("CHICO", "3", 29))
    )
    elegidos = [g.shortname for g in tabla.a_verificar(30)]
    assert elegidos == ["GRANDE/1", "MEDIANO/2"]


def test_el_umbral_es_inclusivo():
    """30 filas entra con umbral 30. La regla del proceso dice "de 30 hacia
    arriba", y dejar fuera justo al que lo cumple seria lo contrario."""
    tabla = tabla_grupos.construir(_ops(("JUSTO", "1", 30)))
    assert len(tabla.a_verificar(30)) == 1


def test_cobertura_dice_cuanto_reporte_deciden():
    """Es el numero que justifica la verificacion previa: pocas preguntas,
    mucho reporte."""
    tabla = tabla_grupos.construir(
        _ops(("GRANDE", "1", 60), ("CHICO", "2", 20), ("CHICO", "3", 20))
    )
    n_grupos, n_filas, pct = tabla.cobertura(30)
    assert (n_grupos, n_filas) == (1, 60)
    assert round(pct) == 60


def test_reporte_disperso_no_manda_verificar_nada():
    """Si ningun grupo llega al umbral, preguntar cuesta mas que procesar: la
    consulta son ~40 s y ademas es lo que puede dejar inerte la grilla de
    ISEF07. Se procesa y se descubre sobre la marcha."""
    tabla = tabla_grupos.construir(_ops(("A", "1", 1), ("B", "2", 1), ("C", "3", 2)))
    assert tabla.a_verificar(30) == ()
    assert "Ningun grupo llega a 30 filas" in tabla_grupos.formatear(tabla, umbral=30)


def test_umbral_por_defecto_es_el_de_la_regla():
    """10 filas, decision del dueno del proceso (26/09/2026). Sobre el reporte
    del 25/09 sube la cobertura del 83% al 89% por dos consultas mas."""
    assert tabla_grupos.UMBRAL_VERIFICACION == 10


def test_el_umbral_vive_en_un_solo_sitio():
    """El flujo en vivo tiene que usar EXACTAMENTE el mismo numero que la tabla
    que el operador mira antes de empezar.

    Estuvieron separados unas horas el 26/09/2026 -- 20 en el flujo y 30 en la
    tabla -- y con el reporte de ese dia daban los mismos 6 grupos, asi que no se
    habria notado hasta que el reparto cambiara. Una tabla que promete un plan
    distinto del que se ejecuta es peor que no tener tabla.
    """
    import importlib.util
    import sys as _sys
    from pathlib import Path as _Path

    raiz = _Path(__file__).resolve().parents[1]
    _sys.path.insert(0, str(raiz / "src"))
    ruta = raiz / "scripts" / "ejecutar_sinu.py"
    spec = importlib.util.spec_from_file_location("ejecutar_sinu_umbral", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    assert modulo.FILAS_PARA_VERIFICAR_GRUPO == tabla_grupos.UMBRAL_VERIFICACION


# ---------------------------------------------------------------------------
# Estimacion y salidas
# ---------------------------------------------------------------------------


def test_minutos_en_juego():
    """120 filas a ~105 s son ~3,5 h. Es lo que se decide con UNA consulta."""
    tabla = tabla_grupos.construir(_ops(("POS01", "57ES6", 120)))
    assert tabla.grupos[0].minutos_en_juego == 120 * 105 // 60


def test_materia_y_grupo_se_recuperan_del_shortname():
    """Los lectores de la 05 y la 50 necesitan las dos piezas por separado."""
    g = tabla_grupos.construir(_ops(("POS01", "57ES6", 1))).grupos[0]
    assert (g.cod_materia, g.num_grupo) == ("POS01", "57ES6")


def test_formatear_lista_los_grupos_a_verificar():
    tabla = tabla_grupos.construir(_ops(("POS01", "57ES6", 120), ("X", "1", 1)))
    texto = tabla_grupos.formatear(tabla, umbral=30)
    assert "VERIFICAR PRIMERO (>= 30 filas): 1 grupo(s)" in texto
    assert "POS01/57ES6" in texto
    # Sin acentos: esto se imprime en la consola cp1252 y en la bitacora.
    assert texto.isascii()


def test_csv_lleva_todos_los_grupos_no_solo_el_tope():
    """El CSV es para pegarlo en el Sheet y mirarlo, no para caber en pantalla."""
    tabla = tabla_grupos.construir(_ops(*[(f"M{i:03d}", "1", 1) for i in range(40)]))
    lineas = tabla_grupos.a_csv(tabla).strip().splitlines()
    assert len(lineas) == 41  # cabecera + 40 grupos


def test_csv_acumula_hasta_cien():
    tabla = tabla_grupos.construir(_ops(("A", "1", 3), ("B", "2", 1)))
    ultima = tabla_grupos.a_csv(tabla).strip().splitlines()[-1]
    assert ultima.endswith("100.0")
