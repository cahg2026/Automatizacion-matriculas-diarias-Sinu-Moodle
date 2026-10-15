"""PACF50 como segunda via de verificacion. SOLO LEE.

Regla del dueno del proceso (26/09/2026):

    Si no te sale la 05, tienes que validarla por la 50. Y si no te sale por la
    50, pues la validas por la 05. Siempre se tienen que validar en ambas.

    La 05 y la 50 es para verificar si tiene o no check y dejar eso plasmado en
    el reporte. No es para procesar nada de vinculado o desvinculado.

Lo segundo no depende de la buena voluntad de este modulo: `restricciones_sinu`
mantiene pacf50 fuera de MODULOS_ESCRIBIBLES, y aqui se comprueba.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from moodle_sinu.lector_pacf50 import GrupoEnPacf50  # noqa: E402
from moodle_sinu.restricciones_sinu import (  # noqa: E402
    ErrorRestriccionOperativa,
    exigir_modulo_escribible,
    exigir_modulo_legible,
)


def _g(moodle, enviado=None):
    return GrupoEnPacf50(
        cod_periodo="26ES5", cod_materia="POS01", num_grupo="55ES2",
        moodle=moodle, enviado=enviado,
    )


class TestPacf50NoEscribeNunca:
    def test_se_puede_leer(self):
        exigir_modulo_legible("pacf50", "verificar el check")  # no lanza

    def test_NO_se_puede_escribir(self):
        """Es la garantia de la regla: la 50 verifica, no procesa."""
        with pytest.raises(ErrorRestriccionOperativa):
            exigir_modulo_escribible("pacf50", "vincular grupos matriculados")

    def test_isef05_tampoco(self):
        with pytest.raises(ErrorRestriccionOperativa):
            exigir_modulo_escribible("isef05", "vincular grupos matriculados")


class TestQueDecideElDescarte:
    def test_sin_check_vincular_es_imposible(self):
        assert _g(False).vincular_es_imposible is True

    def test_con_check_se_procesa(self):
        """POS01/55ES2 el 26/09/2026: Moodle?=checked.gif. Y encaja con que el
        25/09 se vincularan 37 estudiantes de ese grupo -- no se puede vincular
        a un curso que no existe."""
        assert _g(True).vincular_es_imposible is False

    def test_ilegible_NO_es_lo_mismo_que_no_tener(self):
        """La direccion segura es seguir procesando. Descartar un grupo sano
        deja sin hacer trabajo que si se podia hacer: el 25/09 se cerraron 68
        filas como 'validar a mano' y los dos grupos estaban sanos."""
        assert _g(None).vincular_es_imposible is False

    def test_el_resumen_distingue_los_tres_estados(self):
        assert "moodle=si" in _g(True).resumen()
        assert "moodle=NO" in _g(False).resumen()
        assert "moodle=ilegible" in _g(None).resumen()

    def test_el_resumen_dice_de_donde_viene(self):
        """Al operador le cambia donde mirar: 05 y 50 son pantallas distintas."""
        assert "PACF50" in _g(True).resumen()

    def test_el_objetivo_es_el_shortname(self):
        assert _g(True).objetivo == "POS01/55ES2"


class TestMismoContratoQueIsef05:
    def test_las_dos_vias_responden_igual(self):
        """El flujo pregunta a una o a otra sin saber cual: si el contrato
        difiriera, la segunda via seria una fuente de decisiones distintas."""
        from moodle_sinu.lector_isef05 import GrupoEnMoodle

        a = GrupoEnMoodle(
            cod_periodo="26ES5", cod_materia="POS01", num_grupo="55ES2",
            curso=False, usuarios=None, vinculacion=None, semilla=None,
        )
        b = _g(False)
        assert a.vincular_es_imposible == b.vincular_es_imposible
        assert a.objetivo == b.objetivo


# ---------------------------------------------------------------------------
# "No hay informacion para mostrar": el grupo no existe (28/09/2026)
# ---------------------------------------------------------------------------


class _PaginaRejilla:
    """Una pagina de PACF50 simulada, vuelta a vuelta del sondeo.

    `pasos`, uno por vuelta (el ultimo se repite):
      "fila"      -> aparece la fila del grupo con su check
      "vacia"     -> "No hay informacion para mostrar", sin carga
      "cargando"  -> hay carga en curso (cursor de espera, 'Cargando datos')
      "nada"      -> ni lo uno ni lo otro
    """

    def __init__(self, pasos, filtro="55ES1"):
        self.pasos = list(pasos)
        self.i = 0
        self.filtro = filtro

    def evaluate(self, guion, cfg):
        from moodle_sinu import lector_pacf50 as l50

        paso = self.pasos[min(self.i, len(self.pasos) - 1)]
        if guion is l50._GUION_FILA:
            if paso == "fila":
                return {"fila": 500.0, "estados": {"Moodle?": "checked.gif"}}
            return {"fila": None}
        # El guion de estado cierra la vuelta.
        self.i += 1
        return {"cabecera": 446, "vacia": paso == "vacia", "cargando": paso == "cargando"}

    def wait_for_timeout(self, ms):
        pass

    def locator(self, css):
        pagina = self

        class _Caja:
            @property
            def first(self):
                return self

            def is_editable(self):
                return True

            def input_value(self):
                return pagina.filtro

        return _Caja()


@pytest.fixture
def reloj(monkeypatch):
    """Cada lectura del reloj avanza 1 s: las pruebas no esperan de verdad."""
    from moodle_sinu import lector_pacf50 as l50

    t = {"ahora": 0.0}

    def monotonic():
        t["ahora"] += 1.0
        return t["ahora"]

    monkeypatch.setattr(l50.time, "monotonic", monotonic)
    return t


def _leer(pagina):
    from moodle_sinu import lector_pacf50 as l50

    return l50._leer_fila_del_grupo(
        pagina, None, num_grupo="55ES1", objetivo="POS01/55ES1"
    )


class TestGrupoQueNoExiste:
    def test_la_fila_del_grupo_se_lee(self, reloj):
        estados, _y = _leer(_PaginaRejilla(["fila"]))
        assert estados["Moodle?"] == "checked.gif"

    def test_sin_informacion_estable_es_que_no_existe(self, reloj):
        from moodle_sinu import lector_pacf50 as l50

        assert _leer(_PaginaRejilla(["vacia"])) is l50.SIN_INFORMACION

    def test_mientras_carga_no_se_concluye_nada(self, reloj):
        """Regla del dueno del proceso: si el cursor esta cargando, se espera.
        Una rejilla vacia MIENTRAS carga no dice nada del grupo."""
        pagina = _PaginaRejilla(["vacia", "cargando", "vacia", "cargando"] * 3 + ["fila"])
        estados, _ = _leer(pagina)
        assert estados["Moodle?"] == "checked.gif"

    def test_se_espera_mas_alla_del_plazo_si_sigue_cargando(self, reloj):
        """Cargando no cuenta como 'no contesto': se sigue mas alla de los 60 s."""
        from moodle_sinu import lector_pacf50 as l50

        n = int(l50.SEG_ESPERA_REJILLA_GRUPOS) + 10  # 1 s de reloj por vuelta
        assert n < l50.SEG_TOPE_MIENTRAS_CARGA
        estados, _ = _leer(_PaginaRejilla(["cargando"] * n + ["fila"]))
        assert estados["Moodle?"] == "checked.gif"

    def test_sin_carga_el_plazo_normal_si_cuenta(self, reloj):
        """Lo mismo pero SIN carga en curso: pasado el plazo, "no lo se"."""
        from moodle_sinu import lector_pacf50 as l50

        n = int(l50.SEG_ESPERA_REJILLA_GRUPOS) + 10
        assert _leer(_PaginaRejilla(["nada"] * n + ["fila"])) is None

    def test_pero_no_para_siempre(self, reloj):
        assert _leer(_PaginaRejilla(["cargando"])) is None

    def test_un_vistazo_vacio_suelto_no_basta(self, reloj):
        """El instante entre que SmartClient borra la rejilla y pinta el
        resultado tambien se ve vacio."""
        estados, _ = _leer(_PaginaRejilla(["vacia", "nada", "vacia", "nada", "fila"]))
        assert estados["Moodle?"] == "checked.gif"

    def test_vacia_con_otro_filtro_no_es_que_no_exista(self, reloj):
        """Si el filtro no tiene el grupo pedido, la rejilla vacia no habla de el."""
        assert _leer(_PaginaRejilla(["vacia"], filtro="")) is None

    def test_el_resumen_lo_dice(self):
        g = GrupoEnPacf50(
            cod_periodo="26ES5", cod_materia="POS01", num_grupo="55ES1",
            moodle=None, enviado=None, existe=False,
        )
        assert "NO EXISTE" in g.resumen()
        assert g.vincular_es_imposible is False  # no es "sin curso": es otra cosa
