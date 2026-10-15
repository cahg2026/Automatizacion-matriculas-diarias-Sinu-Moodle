"""Tabla dinamica del reporte por SHORTNAME (COD_MATERIA/NUM_GRUPO).

Por que existe
--------------
El reporte se lee como una lista de estudiantes, y esa lectura engana sobre
donde esta el trabajo. Medido sobre el reporte del 25/09/2026:

    596 filas con shortname  ->  120 grupos distintos
    POS01/57ES6  120 filas   20% del reporte
    POS01/55ES2   95              36% acumulado
    POS01/55ES5   65              47%
    POS01/55ES1   60              57%
    TI001/55577   45              65%
    POS01/55ES6   44              72%
    ... y 101 grupos de UNA sola fila

Seis grupos son 429 de las 596 filas. Tener curso en MOODLE es propiedad del
GRUPO -- el shortname del curso es 'COD_MATERIA/NUM_GRUPO' --, no del
estudiante, asi que **esos seis grupos son seis preguntas, no 429**.

De ahi la regla del dueno del proceso (26/09/2026):

  > Los grupos que tengan de 30 personas afectadas hacia arriba se verifican
  > PRIMERO, antes de empezar a procesar por la 07. Si se identifica que no
  > tiene check de MOODLE, automaticamente se marcan todas las filas que
  > compartan ese mismo shortname como 'NO TIENE CHECK EN MOODLE'.

Que cuenta este modulo, y que no
--------------------------------
Cuenta **filas procesables**, las que saldrian del plan de trabajo -- no las
filas crudas del .xlsx. Las naranjas de la Fase 1 (campo obligatorio vacio) no
llegan a ISEF07, asi que contarlas inflaria el tamano de un grupo y podria
mandar a verificar uno que no mueve nada.

Las filas sin COD_MATERIA o sin NUM_GRUPO quedan fuera de la tabla y se cuentan
aparte: no tienen shortname que agrupar, y no se puede preguntar por ellas en
ISEF05. Inventarles una clave las mezclaria con grupos reales.

Todo aqui es funcion pura: recibe operaciones y devuelve datos. Decidir a quien
se pregunta no necesita ningun navegador, y asi la regla se puede probar.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Umbral de filas a partir del cual un grupo se verifica ANTES de procesarlo.
#:
#: **10**, decision del dueno del proceso (26/09/2026). Es el UNICO sitio donde
#: vive este numero: `ejecutar_sinu.FILAS_PARA_VERIFICAR_GRUPO` lo importa de
#: aqui. Tenerlo en dos sitios con dos valores es como se cuelan los errores que
#: nadie ve hasta que el reparto del reporte cambia.
#:
#: Las cuentas, sobre el reporte del 25/09/2026 (515 filas procesables):
#:
#:     >= 30 filas ->  6 grupos, 429 filas (83% del reporte)
#:     >= 20 filas ->  6 grupos, 429 filas (83%)
#:     >= 10 filas ->  8 grupos, 457 filas (89%)   <- aqui
#:     >=  5 filas -> 11 grupos, 475 filas (92%)
#:
#: Bajar de 30 a 10 anade `POS01/55ES4` (16 filas) y `TI003/55539` (12): dos
#: consultas de ~40 s que deciden 28 filas, o sea ~49 min si hubiera que
#: procesarlas una a una. El punto de equilibrio es que el grupo este roto un 4%
#: de las veces; por debajo de ~5 filas ya no compensa y cuesta mas preguntar
#: que enterarse procesando.
#:
#: Lo que hacia caro bajarlo, y ya no: la verificacion salia de ISEF07 y volvia,
#: y cada regreso era una oportunidad de que la grilla quedara inerte. Desde el
#: 28/09/2026 la 05 y la 50 tienen pestana y sesion propias y la de la 07 no se
#: mueve (ver `sesiones_sinu`), asi que un grupo mas solo cuesta su consulta.
UMBRAL_VERIFICACION = 10

#: Coste medio de una fila que se procesa hasta el final en ISEF07, en segundos.
#: Lectura del estudiante (~22 s medidos el 25/09/2026) + ejecucion y sondeo.
#: Se usa solo para estimar lo que se ahorra al descartar un grupo entero.
SEG_POR_FILA = 105


@dataclass(frozen=True)
class GrupoDelReporte:
    """Un shortname y cuanto reporte mueve."""

    shortname: str
    cod_periodo: str
    n_filas: int
    n_estudiantes: int
    """Cedulas distintas. Suele coincidir con `n_filas`; difiere si un mismo
    estudiante repite el mismo grupo en dos filas, que es un dato a mirar."""

    filas_reporte: tuple[int, ...] = ()
    """Numeros de fila del .xlsx, para poder ir a verlas."""

    @property
    def cod_materia(self) -> str:
        return self.shortname.partition("/")[0]

    @property
    def num_grupo(self) -> str:
        return self.shortname.partition("/")[2]

    @property
    def minutos_en_juego(self) -> int:
        """Lo que costaria procesar este grupo fila por fila hasta el final."""
        return self.n_filas * SEG_POR_FILA // 60


@dataclass(frozen=True)
class TablaGrupos:
    """La tabla dinamica completa de un reporte."""

    grupos: tuple[GrupoDelReporte, ...]
    """De mayor a menor numero de filas. El orden es el de la verificacion:
    el grupo que mas mueve se pregunta primero, porque si resulta sin curso es
    el que mas dia ahorra."""

    sin_shortname: int = 0
    """Operaciones sin COD_MATERIA o sin NUM_GRUPO. No se pueden agrupar ni
    consultar en ISEF05."""

    @property
    def n_filas(self) -> int:
        return sum(g.n_filas for g in self.grupos)

    @property
    def n_grupos(self) -> int:
        return len(self.grupos)

    def a_verificar(self, umbral: int = UMBRAL_VERIFICACION) -> tuple[GrupoDelReporte, ...]:
        """Los grupos que hay que preguntar ANTES de procesar nada."""
        return tuple(g for g in self.grupos if g.n_filas >= umbral)

    def cobertura(self, umbral: int = UMBRAL_VERIFICACION) -> tuple[int, int, float]:
        """(grupos, filas, % del reporte) que cubre ese umbral."""
        sel = self.a_verificar(umbral)
        filas = sum(g.n_filas for g in sel)
        pct = filas / self.n_filas * 100 if self.n_filas else 0.0
        return len(sel), filas, pct


def construir(operaciones) -> TablaGrupos:
    """Agrupa las operaciones del plan por shortname.

    Args:
        operaciones: iterable de `OperacionSinu` (o cualquier objeto con
            `objetivo`, `cod_materia`, `num_grupo`, `cod_periodo`,
            `identificacion` y `fila`).

    El orden de salida es por numero de filas descendente y, a igualdad, por
    shortname: hace falta que sea estable para que dos corridas con el mismo
    reporte pregunten en el mismo orden y los logs se puedan comparar.
    """
    filas: dict[str, list] = {}
    periodo: dict[str, str] = {}
    cedulas: dict[str, set] = {}
    sin_shortname = 0

    for op in operaciones:
        if not op.cod_materia or not op.num_grupo:
            sin_shortname += 1
            continue
        sn = op.objetivo
        filas.setdefault(sn, []).append(op.fila)
        cedulas.setdefault(sn, set()).add(op.identificacion)
        # El primero que se vea: un shortname pertenece a un solo periodo, y si
        # apareciera en dos seria un dato a revisar en origen, no algo que este
        # modulo deba promediar.
        periodo.setdefault(sn, op.cod_periodo)

    grupos = [
        GrupoDelReporte(
            shortname=sn,
            cod_periodo=periodo[sn],
            n_filas=len(nums),
            n_estudiantes=len(cedulas[sn]),
            filas_reporte=tuple(sorted(n for n in nums if n)),
        )
        for sn, nums in filas.items()
    ]
    grupos.sort(key=lambda g: (-g.n_filas, g.shortname))
    return TablaGrupos(grupos=tuple(grupos), sin_shortname=sin_shortname)


#: Umbrales del reparto que se imprime. Sirven para ver de un vistazo si el
#: reporte esta concentrado (pocos grupos, mucho reporte) o disperso.
UMBRALES_REPARTO: tuple[int, ...] = (40, 30, 20, 10, 5, 2)


def formatear(tabla: TablaGrupos, umbral: int = UMBRAL_VERIFICACION, tope: int = 15) -> str:
    """La tabla dinamica en texto, lista para la consola o la bitacora.

    Sin acentos a proposito: la consola de Windows es cp1252 y esto se imprime
    tambien dentro de la bitacora del flujo del dia.
    """
    lineas: list[str] = []
    total = tabla.n_filas
    lineas.append(
        f"{tabla.n_grupos} grupos distintos para {total} fila(s) procesables."
    )
    if tabla.sin_shortname:
        lineas.append(
            f"  ({tabla.sin_shortname} fila(s) sin COD_MATERIA o sin NUM_GRUPO: "
            "no se pueden agrupar ni consultar en ISEF05)"
        )
    lineas.append("")
    lineas.append(
        f"{'#':>3} {'shortname':<16}{'periodo':<9}{'filas':>6}{'estud':>7}"
        f"{'%':>7}{'acum':>7}{'min':>6}"
    )
    acumulado = 0
    for i, g in enumerate(tabla.grupos[:tope], 1):
        acumulado += g.n_filas
        pct = g.n_filas / total * 100 if total else 0.0
        acc = acumulado / total * 100 if total else 0.0
        lineas.append(
            f"{i:>3} {g.shortname:<16}{g.cod_periodo:<9}{g.n_filas:>6}"
            f"{g.n_estudiantes:>7}{pct:>6.1f}%{acc:>6.1f}%{g.minutos_en_juego:>6}"
        )
    if tabla.n_grupos > tope:
        resto = tabla.grupos[tope:]
        lineas.append(
            f"    ... y {len(resto)} grupo(s) mas con "
            f"{sum(g.n_filas for g in resto)} fila(s)"
        )

    lineas.append("")
    lineas.append("Reparto por tamano de grupo:")
    for lim in UMBRALES_REPARTO:
        n_grupos, n_filas, pct = tabla.cobertura(lim)
        if not n_grupos:
            continue
        lineas.append(
            f"  >= {lim:>2} filas: {n_grupos:>3} grupo(s) -> {n_filas:>4} fila(s) "
            f"({pct:>3.0f}% del reporte)"
        )
    de_una = sum(1 for g in tabla.grupos if g.n_filas == 1)
    if de_una:
        lineas.append(f"  == 1 fila  : {de_una:>3} grupo(s) -> {de_una:>4} fila(s)")

    sel = tabla.a_verificar(umbral)
    lineas.append("")
    if not sel:
        lineas.append(
            f"Ningun grupo llega a {umbral} filas: el reporte esta disperso y no "
            "hay verificacion previa que rentabilice. Se procesa por ISEF07."
        )
        return "\n".join(lineas)

    _, filas_cubiertas, pct = tabla.cobertura(umbral)
    minutos = sum(g.minutos_en_juego for g in sel)
    lineas.append(
        f"VERIFICAR PRIMERO (>= {umbral} filas): {len(sel)} grupo(s), "
        f"{filas_cubiertas} fila(s), {pct:.0f}% del reporte."
    )
    lineas.append(
        f"  Son {len(sel)} consulta(s) que deciden hasta {minutos} minutos de gestion."
    )
    for g in sel:
        lineas.append(
            f"    {g.shortname:<16}{g.cod_periodo:<9}{g.n_filas:>4} filas "
            f"(~{g.minutos_en_juego} min si se procesa fila a fila)"
        )
    return "\n".join(lineas)


def a_csv(tabla: TablaGrupos) -> str:
    """La tabla entera en CSV, para pegarla en el Sheet del dia.

    Todas las filas, no solo las del tope: el CSV es para mirar, no para caber
    en una pantalla.
    """
    total = tabla.n_filas
    salida = ["shortname,cod_periodo,filas,estudiantes,pct_reporte,pct_acumulado"]
    acumulado = 0
    for g in tabla.grupos:
        acumulado += g.n_filas
        pct = g.n_filas / total * 100 if total else 0.0
        acc = acumulado / total * 100 if total else 0.0
        salida.append(
            f"{g.shortname},{g.cod_periodo},{g.n_filas},{g.n_estudiantes},"
            f"{pct:.1f},{acc:.1f}"
        )
    return "\n".join(salida) + "\n"
