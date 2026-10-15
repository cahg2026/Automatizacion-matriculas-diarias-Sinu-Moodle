"""La regla de "un grupo sin curso en MOODLE lo es para TODAS sus filas".

Tener curso en MOODLE es propiedad del GRUPO -- el shortname del curso es
'COD_MATERIA/NUM_GRUPO' --, no del estudiante. Asi que en cuanto una fila lo
evidencia, las demas filas del mismo shortname tienen la respuesta dada y no
hay que abrir a esos estudiantes.

Antes del 24/09/2026 eso solo valia si ISEF05 contestaba ANTES del lote. Si la
consulta fallaba por un grupo, sus filas se leian una a una -- ~20s por
estudiante -- para llegar siempre al mismo rojo.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

_spec = importlib.util.spec_from_file_location(
    "ejecutar_sinu_script", RAIZ / "scripts" / "ejecutar_sinu.py"
)
assert _spec and _spec.loader
ejecutar_sinu = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ejecutar_sinu)

motivo_sin_curso = ejecutar_sinu.motivo_sin_curso
indizar_por_shortname = ejecutar_sinu.indizar_por_shortname
filas_a_cortocircuitar = ejecutar_sinu.filas_a_cortocircuitar
grupos_a_verificar = ejecutar_sinu.grupos_a_verificar


class RespuestaPacf50:
    """Lo minimo que el motivo necesita de un veredicto de PACF50."""

    def __init__(self, texto: str = "grupo sin curso") -> None:
        self._texto = texto

    def resumen(self) -> str:
        return self._texto


def test_sin_noticias_no_se_salta_nada():
    """La direccion segura es procesar de mas, no de menos."""
    assert motivo_sin_curso("TI010/55570", {}, set()) is None


def test_pacf50_lo_dijo_antes_de_empezar():
    motivo = motivo_sin_curso(
        "DTA32/55598",
        {"DTA32/55598": RespuestaPacf50("sin curso creado")},
        set(),
    )
    assert motivo is not None
    assert "PACF50" in motivo
    assert "ISEF05" not in motivo
    assert "sin curso creado" in motivo


def test_isef07_lo_enseno_en_una_fila_anterior():
    motivo = motivo_sin_curso("TI010/55570", {}, {"TI010/55570"})
    assert motivo is not None
    assert "ISEF07" in motivo
    assert "fila anterior" in motivo


def test_pacf50_manda_cuando_lo_dicen_las_dos():
    """Es la fuente autoritativa y trae su propio resumen."""
    motivo = motivo_sin_curso(
        "DTA32/55598",
        {"DTA32/55598": RespuestaPacf50("sin curso creado")},
        {"DTA32/55598"},
    )
    assert motivo is not None
    assert "PACF50" in motivo


class _Op:
    """Lo minimo que el indice necesita de una operacion del plan."""

    def __init__(self, cedula: str, materia: str, grupo: str) -> None:
        self.identificacion = cedula
        self.cod_materia = materia
        self.num_grupo = grupo

    @property
    def objetivo(self) -> str:
        return f"{self.cod_materia}/{self.num_grupo}" if self.num_grupo else self.cod_materia


class TestCortocircuitoPorShortname:
    """Regla B del dueno del proceso (25/09/2026).

    Si un shortname falla en su unico intento, las filas que queden de ese mismo
    MATERIA/GRUPO no abren SINU: se cierran en lote. Es el caso `DTA32/55598`
    (26V05), cuyos cuatro estudiantes fallaron identicamente el 07, el 15 y el
    16/09/2026 -- tres corridas gastando ~300 s por fila para llegar al mismo NO.
    """

    def _lote(self) -> list[_Op]:
        return [
            _Op("111", "DTA32", "55598"),   # 0  <- la que falla
            _Op("222", "AED31", "55522"),   # 1
            _Op("333", "DTA32", "55598"),   # 2  <- se cortocircuita
            _Op("444", "DTA32", "55599"),   # 3  otro grupo de la misma materia
            _Op("555", "DTA32", "55598"),   # 4  <- se cortocircuita
        ]

    def test_el_indice_agrupa_por_shortname_completo(self):
        indice = indizar_por_shortname(self._lote())
        assert indice["DTA32/55598"] == [0, 2, 4]
        assert indice["DTA32/55599"] == [3]
        assert indice["AED31/55522"] == [1]

    def test_las_filas_sin_materia_no_entran_en_el_indice(self):
        indice = indizar_por_shortname([_Op("111", "", ""), _Op("222", "DTA32", "55598")])
        assert indice == {"DTA32/55598": [1]}

    def test_solo_se_cierran_las_filas_posteriores(self):
        """La que fallo conserva su propio apunte.

        Es la unica fila de la que consta que se INTENTO vincular. Pisarla con
        'no se abrio SINU para esta fila' seria mentir sobre lo unico que se
        hizo de verdad en ese grupo.
        """
        indice = indizar_por_shortname(self._lote())
        assert filas_a_cortocircuitar(indice, "DTA32/55598", 0, set()) == [2, 4]

    def test_no_arrastra_a_otro_grupo_de_la_misma_materia(self):
        """DTA32/55598 y DTA32/55599 son dos cursos distintos en MOODLE."""
        indice = indizar_por_shortname(self._lote())
        assert 3 not in filas_a_cortocircuitar(indice, "DTA32/55598", 0, set())

    def test_no_se_cierra_dos_veces_la_misma_fila(self):
        """Cerrarla dos veces anotaria la unidad dos veces en el diario."""
        indice = indizar_por_shortname(self._lote())
        assert filas_a_cortocircuitar(indice, "DTA32/55598", 0, {2}) == [4]

    def test_un_shortname_sin_mas_filas_no_cierra_nada(self):
        indice = indizar_por_shortname(self._lote())
        assert filas_a_cortocircuitar(indice, "AED31/55522", 1, set()) == []

    def test_un_shortname_desconocido_no_revienta(self):
        assert filas_a_cortocircuitar({}, "NOEXISTE/00000", 0, set()) == []

    def test_desde_menos_uno_incluye_la_fila_actual(self):
        """Es como lo llama la red de seguridad del bucle, que SI tiene que
        cerrar la fila que esta mirando: llega ahi sin haberse cerrado."""
        indice = indizar_por_shortname(self._lote())
        assert filas_a_cortocircuitar(indice, "DTA32/55598", -1, set()) == [0, 2, 4]


class TestGruposQueMuevenElLote:
    """Un grupo que sale 120 veces es UNA pregunta, no 120.

    Regla del dueno del proceso (25/09/2026). La economia medida ese dia: 515
    filas procesables eran solo 45 grupos, y seis de ellos cubrian el 83% del
    reporte. Verificarlos ANTES cuesta seis consultas; descubrirlo al fallar la
    fila 40 cuesta horas.
    """

    def _indice(self, **tam):
        return {k: list(range(n)) for k, n in tam.items()}

    def test_ordena_de_mayor_a_menor(self):
        indice = self._indice(**{
            "POS01/55ES2": 95, "POS01/57ES6": 120, "POS01/55ES5": 65,
        })
        assert grupos_a_verificar(indice, 20) == [
            ("POS01/57ES6", 120), ("POS01/55ES2", 95), ("POS01/55ES5", 65),
        ]

    def test_deja_fuera_los_grupos_pequenos(self):
        """Los 30 grupos de UNA fila del 25/09/2026.

        Consultarlos cuesta mas que procesarlos: la consulta obliga a cambiar de
        modulo y volver, y el bucle ya se entera solo al leer al estudiante.
        """
        indice = self._indice(**{"GRANDE/1": 44, "CHICO/1": 1, "MEDIANO/1": 19})
        assert grupos_a_verificar(indice, 20) == [("GRANDE/1", 44)]

    def test_el_umbral_manda(self):
        indice = self._indice(**{"A/1": 10, "B/1": 5})
        assert grupos_a_verificar(indice, 5) == [("A/1", 10), ("B/1", 5)]
        assert grupos_a_verificar(indice, 50) == []

    def test_sin_grupos_grandes_no_se_consulta_nada(self):
        """Un reporte repartido no tiene palanca: se procesa y ya."""
        assert grupos_a_verificar(self._indice(**{f"G{i}/1": 1 for i in range(30)}), 20) == []

    def test_empate_se_resuelve_por_nombre(self):
        """Estable: dos corridas del mismo lote consultan en el mismo orden."""
        indice = self._indice(**{"B/1": 30, "A/1": 30})
        assert grupos_a_verificar(indice, 20) == [("A/1", 30), ("B/1", 30)]

    def test_la_concentracion_real_del_25_09(self):
        """Los numeros que motivaron la regla, como prueba de regresion."""
        indice = self._indice(**{
            "POS01/57ES6": 120, "POS01/55ES2": 95, "POS01/55ES5": 65,
            "POS01/55ES1": 60, "TI001/55577": 45, "POS01/55ES6": 44,
            "POS01/55ES4": 16, "TI003/55539": 12,
        })
        grandes = grupos_a_verificar(indice, 20)
        assert len(grandes) == 6
        # 429 de las 515 filas del reporte: el 83%.
        assert sum(n for _, n in grandes) == 429


def test_la_evidencia_no_se_desborda_a_otro_grupo():
    """Es por shortname COMPLETO: otro grupo de la MISMA materia no hereda nada.

    TI010/55570 y TI010/55571 son dos cursos distintos en MOODLE. Saltarse el
    segundo porque el primero no tiene curso dejaria sin procesar trabajo que
    si se puede hacer.
    """
    assert motivo_sin_curso("TI010/55571", {}, {"TI010/55570"}) is None
    assert (
        motivo_sin_curso(
            "TI010/55571", {"TI010/55570": RespuestaPacf50()}, set()
        )
        is None
    )


# ---------------------------------------------------------------------------
# La verificacion previa, solo en PACF50 (06/10/2026)
#
# La 50 se consulta en su navegador y con su sesion: la 07 no sale nunca de
# ISEF07. La 05 ya no se consulta.
# ---------------------------------------------------------------------------


class _PaginaFalsa:
    def __init__(self, nombre="isef07"):
        self.nombre = nombre
        self.al_frente = 0

    def bring_to_front(self):
        self.al_frente += 1


def _sesiones(acceder=None):
    """SesionesSinu de verdad sobre navegadores falsos. El login no hace nada."""
    from moodle_sinu.sesiones_sinu import SesionesSinu

    abiertos = []

    def abrir():
        nombre = f"nav{len(abiertos) + 1}"
        abiertos.append(nombre)

        class _Contexto:
            def new_page(self):
                return _PaginaFalsa(nombre)

        return _Contexto(), lambda: None

    return SesionesSinu(
        object(), object(), _PaginaFalsa("isef07"),
        abrir_navegador=abrir,
        acceder=acceder or (lambda page, cfg: True),
    )


class _EspiaSinu:
    """Registra QUE se consulto, EN QUE NAVEGADOR y CON QUE DATOS."""

    def __init__(self, resp50, viva=True):
        self.resp50 = resp50
        self.viva = viva
        self.eventos = []
        self.paginas = set()
        self.ofertas_50 = {}
        self.comprobada = []

    def consultar50(
        self, page, cfg, *, cod_periodo, cod_materia, num_grupo,
        cod_unidad="", cod_pensum="",
    ):
        from moodle_sinu.lector_sinu import ErrorLecturaSinu

        objetivo = f"{cod_materia}/{num_grupo}"
        self.eventos.append(("pacf50", objetivo, cod_periodo))
        self.paginas.add(page.nombre)
        self.ofertas_50[objetivo] = (cod_unidad, cod_pensum)
        if objetivo not in self.resp50:
            raise ErrorLecturaSinu("PACF50 no contesta en la prueba")
        valor = self.resp50[objetivo]
        if isinstance(valor, Exception):
            raise valor
        return valor

    def entrar(self, page, cfg, modulo, motivo):
        self.eventos.append(("modulo", modulo, page.nombre))

    def fijar(self, page, cfg, periodo):
        self.eventos.append(("periodo", periodo, page.nombre))

    def grilla_viva(self, page, cfg):
        self.comprobada.append(page.nombre)
        return self.viva


class _RespuestaPacf50:
    def __init__(self, imposible, existe=True):
        self.vincular_es_imposible = imposible
        self.existe = existe

    def resumen(self):
        if self.existe is False:
            return "grupo NO EXISTE"
        return "moodle=NO" if self.vincular_es_imposible else "moodle=si"


def _espiar(monkeypatch, resp50, viva=True):
    espia = _EspiaSinu(resp50, viva)
    monkeypatch.setattr(ejecutar_sinu, "consultar_pacf50", espia.consultar50)
    monkeypatch.setattr(ejecutar_sinu, "entrar_en_modulo", espia.entrar)
    monkeypatch.setattr(ejecutar_sinu, "fijar_periodo", espia.fijar)
    monkeypatch.setattr(ejecutar_sinu, "_grilla_viva", espia.grilla_viva)
    return espia


def _si(existe=True):
    return _RespuestaPacf50(False, existe)


def test_la_05_ya_no_se_consulta():
    """Retirada el 06/10/2026: el script ni la importa."""
    assert not hasattr(ejecutar_sinu, "consultar_grupo")
    assert not hasattr(ejecutar_sinu, "MODULO_ISEF05")


def test_el_navegador_de_la_07_no_navega(monkeypatch):
    """Ni un cambio de modulo en la 07. Ese viaje por #home es lo que dejaba
    los filtros deshabilitados."""
    grupos = [(f"M{i:02d}/55{i:03d}", 12) for i in range(8)]
    espia = _espiar(monkeypatch, {sn: _si() for sn, _ in grupos})
    ejecutar_sinu._verificar_grupos_en_lote(
        _sesiones(), object(), cod_periodo="26V05", grupos=grupos
    )
    assert len([e for e in espia.eventos if e[0] == "pacf50"]) == 8
    assert [e for e in espia.eventos if e[0] in ("modulo", "periodo")] == []
    assert espia.comprobada == ["isef07"]  # una comprobacion, al terminar


def test_solo_se_abre_el_navegador_de_la_50(monkeypatch):
    grupos = [("A/1", 20), ("B/2", 15)]
    espia = _espiar(monkeypatch, {"A/1": _si(), "B/2": _si()})
    sesiones = _sesiones()
    ejecutar_sinu._verificar_grupos_en_lote(
        sesiones, object(), cod_periodo="26V05", grupos=grupos
    )
    assert espia.paginas == {"nav1"}
    assert sesiones.abiertas == ("pacf50",)


def test_cada_consulta_lleva_el_periodo_del_lote(monkeypatch):
    espia = _espiar(monkeypatch, {"A/1": _si()})
    ejecutar_sinu._verificar_grupos_en_lote(
        _sesiones(), object(), cod_periodo="26ES5", grupos=[("A/1", 20)]
    )
    assert {e[2] for e in espia.eventos if e[0] == "pacf50"} == {"26ES5"}


def test_la_50_recibe_programa_y_pensum(monkeypatch):
    """Para pulsar la oferta correcta de la asignatura, no la primera POS01."""
    espia = _espiar(monkeypatch, {"POS01/55ES1": _si()})
    ejecutar_sinu._verificar_grupos_en_lote(
        _sesiones(), object(), cod_periodo="26ES5", grupos=[("POS01/55ES1", 38)],
        ofertas={"POS01/55ES1": ("EMPVI", "EMVIR")},
    )
    assert espia.ofertas_50["POS01/55ES1"] == ("EMPVI", "EMVIR")


def test_el_grupo_que_no_existe_en_la_50_se_descarta(monkeypatch):
    """POS01/55ES1 en 26ES5: en la 50 'No hay informacion para mostrar'."""
    _espiar(monkeypatch, {"POS01/55ES1": _RespuestaPacf50(False, existe=False)})
    r = ejecutar_sinu._verificar_grupos_en_lote(
        _sesiones(), object(), cod_periodo="26ES5", grupos=[("POS01/55ES1", 38)]
    )
    assert r["POS01/55ES1"].grupo_inexistente
    assert r["POS01/55ES1"].descartar_grupo


def test_un_grupo_que_no_contesta_no_cancela_los_demas(monkeypatch):
    from moodle_sinu.lector_sinu import ErrorLecturaSinu

    _espiar(
        monkeypatch,
        {"A/1": ErrorLecturaSinu("la rejilla no contesta"), "B/2": _RespuestaPacf50(True)},
    )
    r = ejecutar_sinu._verificar_grupos_en_lote(
        _sesiones(), object(), cod_periodo="26V05", grupos=[("A/1", 20), ("B/2", 15)]
    )
    assert r["A/1"].tiene_curso is None and not r["A/1"].descartar_grupo
    assert r["B/2"].tiene_curso is False and r["B/2"].descartar_grupo


def test_un_timeout_crudo_de_playwright_es_no_lo_se(monkeypatch):
    """30/09/2026, 26P05: una capa modal de SmartClient tapo un clic y el
    TimeoutError de Playwright tumbo el lote entero sin llegar a la 07. Tiene
    que ser un "no contesto", como cualquier otro."""
    from playwright.sync_api import TimeoutError as TimeoutPlaywright

    _espiar(monkeypatch, {"61117/55529": TimeoutPlaywright("Timeout 30000ms exceeded.")})
    r = ejecutar_sinu._verificar_grupos_en_lote(
        _sesiones(), object(), cod_periodo="26P05", grupos=[("61117/55529", 12)]
    )
    assert r["61117/55529"].tiene_curso is None
    assert not r["61117/55529"].descartar_grupo


def test_si_no_se_puede_abrir_la_sesion_de_la_50_es_no_lo_se(monkeypatch):
    """Un login fallido de la 50 no descarta nada ni tumba el lote."""
    from moodle_sinu.acceso_sinu import ErrorAccesoSinu

    def acceder(page, cfg):
        raise ErrorAccesoSinu("SINU no cargo")

    espia = _espiar(monkeypatch, {"A/1": _si(), "B/2": _si()})
    r = ejecutar_sinu._verificar_grupos_en_lote(
        _sesiones(acceder), object(), cod_periodo="26V05",
        grupos=[("A/1", 20), ("B/2", 15)],
    )
    assert [e for e in espia.eventos if e[0] == "pacf50"] == []
    assert r["A/1"].tiene_curso is None and not r["A/1"].descartar_grupo
    assert r["B/2"].tiene_curso is None and not r["B/2"].descartar_grupo


def test_si_la_07_no_responde_se_reabre_y_se_sigue(monkeypatch):
    """Regla del 28/09/2026: no se para el lote. Se reabre SINU en la 07."""
    _espiar(monkeypatch, {"A/1": _si()}, viva=False)
    reaperturas = []
    monkeypatch.setattr(
        ejecutar_sinu, "_reabrir_07",
        lambda page, cfg, periodo: reaperturas.append(periodo) or True,
    )
    sesiones = _sesiones()
    r = ejecutar_sinu._verificar_grupos_en_lote(
        sesiones, object(), cod_periodo="26V05", grupos=[("A/1", 20)]
    )
    assert "A/1" in r  # no lanzo: la verificacion se devuelve
    assert reaperturas == ["26V05"]  # con el periodo del lote
    assert sesiones.reaperturas_07 == 1


def test_pasado_el_tope_no_se_reabre_pero_tampoco_se_para(monkeypatch):
    _espiar(monkeypatch, {"A/1": _si()}, viva=False)
    reaperturas = []
    monkeypatch.setattr(
        ejecutar_sinu, "_reabrir_07",
        lambda page, cfg, periodo: reaperturas.append(periodo) or True,
    )
    sesiones = _sesiones()
    sesiones.reaperturas_07 = ejecutar_sinu.MAX_REAPERTURAS_07
    ejecutar_sinu._verificar_grupos_en_lote(
        sesiones, object(), cod_periodo="26V05", grupos=[("A/1", 20)]
    )
    assert reaperturas == []


def test_el_navegador_que_se_usa_va_al_frente(monkeypatch):
    _espiar(monkeypatch, {"A/1": _si()})
    sesiones = _sesiones()
    ejecutar_sinu._verificar_grupos_en_lote(
        sesiones, object(), cod_periodo="26V05", grupos=[("A/1", 20)]
    )
    assert sesiones.isef07.al_frente == 1


def test_ofertas_por_shortname_elige_el_par_mas_frecuente():
    from moodle_sinu.plan_vinculacion import OperacionSinu

    def op(u, p):
        return OperacionSinu(
            identificacion="1", nombre="x", cod_periodo="26ES5",
            cod_materia="POS01", num_grupo="55ES1", cod_unidad=u, cod_pensum=p,
        )

    ops = [op("EMPVI", "EMVIR"), op("OTRO", "X"), op("EMPVI", "EMVIR")]
    assert ejecutar_sinu.ofertas_por_shortname(ops) == {"POS01/55ES1": ("EMPVI", "EMVIR")}



def test_el_umbral_de_diez_cubre_mas_reporte():
    """Los numeros que justifican la decision del 26/09/2026, sobre el reparto
    real del reporte del 25/09 (515 filas procesables)."""
    indice = {}
    for sn, n in [
        ("POS01/57ES6", 120), ("POS01/55ES2", 95), ("POS01/55ES5", 65),
        ("POS01/55ES1", 60), ("TI001/55577", 45), ("POS01/55ES6", 44),
        ("POS01/55ES4", 16), ("TI003/55539", 12), ("TI002/55524", 7),
    ]:
        indice[sn] = list(range(n))
    assert sum(n for _, n in grupos_a_verificar(indice, 30)) == 429
    assert sum(n for _, n in grupos_a_verificar(indice, 10)) == 457
    assert len(grupos_a_verificar(indice, 10)) == 8
