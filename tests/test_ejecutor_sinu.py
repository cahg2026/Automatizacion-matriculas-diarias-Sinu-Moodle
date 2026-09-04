"""Tests de la etapa 4: la regla de negocio y las guardas de seguridad.

La unidad de trabajo es **(cedula, materia)**, la que registra el reporte. Antes
del 03/09/2026 era el estudiante completo, y esa premisa falsa reciclo 34
asignaturas cuando correspondian 5. La decision es una funcion pura a proposito:
es donde un error deja matriculas desvinculadas, asi que se prueba entera sin
navegador.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from moodle_sinu import ejecutor_sinu as ej  # noqa: E402
from moodle_sinu import selectores_sinu_escritura as sesc  # noqa: E402
from moodle_sinu.clasificador_sinu import FilaGrupoSinu  # noqa: E402
from moodle_sinu.config import Config  # noqa: E402
from moodle_sinu.ejecutor_sinu import (  # noqa: E402
    AccionSeDesbordo,
    CicloAbierto,
    ErrorEjecucionSinu,
    TipoSecuencia,
    acciones_de,
    decidir_secuencia,
    ejecutar_materia,
    estimar_segundos,
    fila_de_materia,
)
from moodle_sinu.restricciones_sinu import (  # noqa: E402
    ErrorRestriccionOperativa,
    exigir_modulo_escribible,
)

#: La materia que usan los tests como "la del reporte".
MATERIA = "A1I01"
GRUPO = "50609"


def _g(vinculado: bool, materia=MATERIA, grupo=GRUPO, moodle=True):
    return FilaGrupoSinu(
        cod_materia=materia, num_grupo=grupo, curso_en_moodle=moodle,
        vinculado=vinculado,
    )


def _releer_prohibido():
    """Centinela para los casos que NO deben releer la grilla.

    En simulacion, y cuando la materia no esta, no hay nada que confirmar.
    Pasar esto en vez de un `lambda: []` hace que el test compruebe ademas que
    la relectura no ocurre -- cada relectura cuesta ~15 s en el sistema real.
    """
    raise AssertionError("no se debia releer la grilla en este caso")


class TestLocalizarLaMateria:
    """`fila_de_materia`: elegir la fila equivocada es ejecutar sobre la
    matricula equivocada."""

    def test_encuentra_la_materia_entre_varias(self):
        grupos = [_g(True, "IED32", "50101"), _g(False, "IED36", "30101")]
        fila = fila_de_materia(grupos, "IED36", "30101")
        assert fila is not None and fila.cod_materia == "IED36"
        assert fila.vinculado is False

    def test_no_esta_devuelve_none(self):
        assert fila_de_materia([_g(True, "IED32", "50101")], "IED36", "30101") is None

    def test_el_grupo_desempata(self):
        grupos = [_g(True, "IED36", "30101"), _g(False, "IED36", "30110")]
        assert fila_de_materia(grupos, "IED36", "30110").vinculado is False
        assert fila_de_materia(grupos, "IED36", "30101").vinculado is True

    def test_grupo_que_no_existe_no_cae_en_otra_fila(self):
        # Sustituir por "la otra del mismo codigo" seria actuar sobre el grupo
        # equivocado. Mejor None y que el CLI lo reporte.
        grupos = [_g(True, "IED36", "30101")]
        assert fila_de_materia(grupos, "IED36", "99999") is None

    def test_sin_grupo_y_con_ambiguedad_devuelve_none(self):
        grupos = [_g(True, "IED36", "30101"), _g(False, "IED36", "30110")]
        assert fila_de_materia(grupos, "IED36") is None

    def test_no_distingue_mayusculas_ni_espacios(self):
        assert fila_de_materia([_g(True, "IED36", "30101")], " ied36 ", "30101")


class TestReglaDeNegocio:
    """Sobre LA materia del reporte: con check -> reciclar; sin check -> vincular."""

    def test_materia_sin_check_solo_vincula(self):
        assert decidir_secuencia(_g(False)) is TipoSecuencia.SOLO_VINCULAR

    def test_materia_con_check_recicla(self):
        assert decidir_secuencia(_g(True)) is TipoSecuencia.RECICLAR

    def test_materia_ausente_no_hace_nada(self):
        assert decidir_secuencia(None) is TipoSecuencia.NADA

    def test_las_otras_asignaturas_no_influyen(self):
        """La correccion del 03/09/2026, en una sola asercion.

        Antes bastaba UNA materia vinculada entre todas para reciclar al
        estudiante completo. Ahora la decision solo mira la del reporte: si esa
        no tiene check, se vincula y no se recicla nada, por muchas otras
        vinculadas que tenga el estudiante.
        """
        grupos = [_g(True, "OTRA1"), _g(True, "OTRA2"), _g(False, MATERIA)]
        fila = fila_de_materia(grupos, MATERIA, GRUPO)
        assert decidir_secuencia(fila) is TipoSecuencia.SOLO_VINCULAR

    def test_el_orden_del_reciclado_es_desvincular_y_luego_vincular(self):
        # Al reves dejaria la materia desvinculada.
        assert acciones_de(TipoSecuencia.RECICLAR) == (
            sesc.OPCION_DESVINCULAR,
            sesc.OPCION_VINCULAR,
        )

    def test_solo_vincular_no_desvincula_nunca(self):
        assert sesc.OPCION_DESVINCULAR not in acciones_de(TipoSecuencia.SOLO_VINCULAR)

    def test_nada_no_ejecuta_acciones(self):
        assert acciones_de(TipoSecuencia.NADA) == ()

    def test_el_reciclado_tarda_el_doble(self):
        assert estimar_segundos(TipoSecuencia.RECICLAR) > estimar_segundos(
            TipoSecuencia.SOLO_VINCULAR
        )


class TestBarreraDeEscritura:
    def test_solo_isef07_puede_ejecutar(self):
        exigir_modulo_escribible("ISEF07", sesc.OPCION_VINCULAR)
        for modulo in ("ISEF05", "PACF50", "ISEF88"):
            with pytest.raises(ErrorRestriccionOperativa):
                exigir_modulo_escribible(modulo, sesc.OPCION_DESVINCULAR)

    def test_la_etapa_3_no_conoce_los_controles_de_escritura(self):
        # Garantia estructural: el lector no puede pulsar lo que no importa.
        fuente = (
            Path(__file__).resolve().parents[1]
            / "src" / "moodle_sinu" / "lector_sinu.py"
        ).read_text(encoding="utf-8")
        assert "selectores_sinu_escritura" not in fuente
        assert "OPCION_DESVINCULAR" not in fuente

    def test_el_clasificador_tampoco(self):
        fuente = (
            Path(__file__).resolve().parents[1]
            / "src" / "moodle_sinu" / "clasificador_sinu.py"
        ).read_text(encoding="utf-8")
        assert "selectores_sinu_escritura" not in fuente

    def test_la_premisa_falsa_no_ha_vuelto(self):
        """Centinela contra la regresion que costo 34 asignaturas.

        La frase "todas sus asignaturas" venia de la referencia de negocio y se
        habia copiado a ocho archivos. Si alguien la reintroduce como
        afirmacion de lo que hace la accion, este test lo caza.
        """
        raiz = Path(__file__).resolve().parents[1]
        for ruta in (
            raiz / "src" / "moodle_sinu" / "ejecutor_sinu.py",
            raiz / "src" / "moodle_sinu" / "plan_vinculacion.py",
        ):
            fuente = ruta.read_text(encoding="utf-8").lower()
            # Se permite nombrarla al explicar el error historico ("era falso",
            # "sin acotar"); lo que no se permite es la premisa como regla.
            assert "la accion es por estudiante, no por materia" not in fuente
            assert "se recicla el estudiante completo" not in fuente


class TestCiclosAbiertos:
    @pytest.fixture(autouse=True)
    def _registro_en_tmp(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ej, "RUTA_CICLOS_ABIERTOS", tmp_path / "ciclos.jsonl")

    def test_sin_registro_no_hay_ciclos(self):
        assert ej.ciclos_abiertos() == []

    def test_un_ciclo_sin_cerrar_se_reporta(self):
        ej._apuntar_ciclo("111", "26V05", "desvinculando", "A1I01/50609")
        assert len(ej.ciclos_abiertos()) == 1

    def test_un_ciclo_cerrado_desaparece(self):
        ej._apuntar_ciclo("111", "26V05", "desvinculando", "A1I01/50609")
        ej._apuntar_ciclo("111", "26V05", "cerrado", "A1I01/50609")
        assert ej.ciclos_abiertos() == []

    def test_dos_materias_del_mismo_estudiante_son_dos_ciclos(self):
        """Sin la materia en la clave, cerrar la primera borraba la segunda.

        Y la segunda es justo la que podia haber quedado desvinculada.
        """
        ej._apuntar_ciclo("111", "26V05", "desvinculando", "A1I01/50609")
        ej._apuntar_ciclo("111", "26V05", "desvinculando", "B2I02/30101")
        ej._apuntar_ciclo("111", "26V05", "cerrado", "A1I01/50609")
        abiertos = ej.ciclos_abiertos()
        assert [c["materia"] for c in abiertos] == ["B2I02/30101"]

    def test_distingue_estudiantes_y_periodos(self):
        ej._apuntar_ciclo("111", "26V05", "desvinculando", "A1I01/50609")
        ej._apuntar_ciclo("222", "26V05", "desvinculando", "A1I01/50609")
        ej._apuntar_ciclo("111", "26V04", "desvinculando", "A1I01/50609")
        assert len(ej.ciclos_abiertos()) == 3

    def test_una_linea_corrupta_no_rompe_la_lectura(self):
        ej._apuntar_ciclo("111", "26V05", "desvinculando", "A1I01/50609")
        with ej.RUTA_CICLOS_ABIERTOS.open("a", encoding="utf-8") as fh:
            fh.write("{no es json\n")
        assert len(ej.ciclos_abiertos()) == 1

    def test_apuntes_viejos_sin_materia_siguen_funcionando(self):
        ej._apuntar_ciclo("111", "26V05", "desvinculando")
        assert len(ej.ciclos_abiertos()) == 1
        ej._apuntar_ciclo("111", "26V05", "cerrado")
        assert ej.ciclos_abiertos() == []


class TestReintentosDelVincular:
    def test_se_reintenta_mas_que_en_el_resto_del_proyecto(self):
        assert ej.REINTENTOS_VINCULAR_TRAS_DESVINCULAR >= 3

    def test_ciclo_abierto_es_un_error_aparte(self):
        assert issubclass(CicloAbierto, ErrorEjecucionSinu)

    def test_el_desborde_es_un_error_aparte(self):
        assert issubclass(AccionSeDesbordo, ErrorEjecucionSinu)


class _PageFalsa:
    """Lo minimo que el ejecutor usa de `Page` cuando no toca la interfaz."""

    def __init__(self):
        self.esperas = 0

    def wait_for_timeout(self, ms):
        self.esperas += 1


class _Escenario:
    """Un estudiante en ISEF07, con la grilla que devuelven las relecturas."""

    def __init__(self, monkeypatch, *, antes, despues=None, fallo=None):
        self.antes = antes
        self.despues = despues if despues is not None else antes
        self.pedidas: list[str] = []
        self.lecturas_materia = 0
        self.lecturas_todas = 0
        self._fallo = fallo

        def falsa(page, cfg, opcion, antes_de_ejecutar=None):
            self.pedidas.append(opcion)
            if antes_de_ejecutar is not None:
                antes_de_ejecutar()
            if self._fallo is not None:
                raise self._fallo

        monkeypatch.setattr(ej, "_ejecutar_una", falsa)

    def releer_materia(self):
        self.lecturas_materia += 1
        return [g for g in self.despues if g.cod_materia == MATERIA]

    def releer_todas(self):
        self.lecturas_todas += 1
        return list(self.despues)

    def ejecutar(self, **extra):
        kwargs = dict(
            identificacion="111",
            cod_periodo="2026C",
            cod_materia=MATERIA,
            num_grupo=GRUPO,
            grupos=self.antes,
            releer_materia=self.releer_materia,
            releer_todas=self.releer_todas,
        )
        kwargs.update(extra)
        return ejecutar_materia(
            _PageFalsa(), Config(modo_simulacion=False), **kwargs
        )


class TestModoSimulacion:
    """La barrera que impide tocar matriculas mientras se valida."""

    def test_simulacion_no_ejecuta_nada(self):
        r = ejecutar_materia(
            None, Config(modo_simulacion=True),
            identificacion="111", cod_periodo="2026C",
            cod_materia=MATERIA, num_grupo=GRUPO,
            grupos=[_g(True)],
            releer_materia=_releer_prohibido, releer_todas=_releer_prohibido,
        )
        assert r.simulado
        assert r.secuencia is TipoSecuencia.RECICLAR
        assert not r.ciclo_abierto

    def test_simulacion_informa_de_lo_que_haria(self):
        r = ejecutar_materia(
            None, Config(modo_simulacion=True),
            identificacion="111", cod_periodo="2026C",
            cod_materia=MATERIA, num_grupo=GRUPO,
            grupos=[_g(True)],
            releer_materia=_releer_prohibido, releer_todas=_releer_prohibido,
        )
        assert sesc.OPCION_DESVINCULAR in r.acciones_ejecutadas
        assert sesc.OPCION_VINCULAR in r.acciones_ejecutadas
        assert "SIMULACION" in r.detalle

    def test_simulacion_con_page_none_prueba_que_no_toca_el_navegador(self):
        # Si intentara pulsar algo, reventaria con AttributeError sobre None.
        for grupos in ([_g(False)], [_g(True)], []):
            ejecutar_materia(
                None, Config(modo_simulacion=True),
                identificacion="111", cod_periodo="2026C",
                cod_materia=MATERIA, num_grupo=GRUPO, grupos=grupos,
                releer_materia=_releer_prohibido, releer_todas=_releer_prohibido,
            )

    def test_materia_ausente_no_hace_nada_ni_en_real(self):
        r = ejecutar_materia(
            None, Config(modo_simulacion=False),
            identificacion="111", cod_periodo="2026C",
            cod_materia="NOESTA", num_grupo="00000",
            grupos=[_g(True)],
            releer_materia=_releer_prohibido, releer_todas=_releer_prohibido,
        )
        assert r.secuencia is TipoSecuencia.NADA
        assert r.acciones_ejecutadas == []
        assert "no aparece" in r.detalle


class TestSoloLaMateriaDelReporte:
    """El corazon de la correccion del 03/09/2026."""

    @pytest.fixture(autouse=True)
    def _registros_en_tmp(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ej, "RUTA_CICLOS_ABIERTOS", tmp_path / "ciclos.jsonl")
        monkeypatch.setattr(ej, "RUTA_ESCALADO", tmp_path / "escalado.jsonl")
        # Sin esto el sondeo gira los 90 s reales: `_PageFalsa.wait_for_timeout`
        # no duerme, asi que la espera se consume a toda velocidad de reloj.
        monkeypatch.setattr(ej, "SEG_SONDEO_CHECK", 0)
        monkeypatch.setattr(ej, "SEG_ENTRE_SONDEOS", 0)

    def test_no_recicla_por_culpa_de_otras_asignaturas(self, monkeypatch):
        """El caso de 1015475860: 7 vinculadas mas la del reporte sin check.

        Lo correcto es UN vincular sobre la del reporte. Lo que hacia antes:
        desvincular y revincular las 8.
        """
        antes = [
            _g(True, "IED32", "50101"), _g(True, "IED33", "30110"),
            _g(False, MATERIA, GRUPO),
        ]
        despues = [
            _g(True, "IED32", "50101"), _g(True, "IED33", "30110"),
            _g(True, MATERIA, GRUPO),
        ]
        esc = _Escenario(monkeypatch, antes=antes, despues=despues)
        r = esc.ejecutar()
        assert esc.pedidas == [sesc.OPCION_VINCULAR]
        assert sesc.OPCION_DESVINCULAR not in esc.pedidas
        assert r.cod_materia == MATERIA and r.num_grupo == GRUPO
        assert r.total_materias == 1
        assert not r.requiere_escalado

    def test_recicla_solo_si_la_del_reporte_tiene_check(self, monkeypatch):
        antes = [_g(False, "OTRA", "11111"), _g(True, MATERIA, GRUPO)]
        esc = _Escenario(
            monkeypatch, antes=antes,
            despues=[_g(False, "OTRA", "11111"), _g(True, MATERIA, GRUPO)],
        )
        r = esc.ejecutar()
        assert esc.pedidas == [sesc.OPCION_DESVINCULAR, sesc.OPCION_VINCULAR]
        assert not r.ciclo_abierto
        assert ej.ciclos_abiertos() == []


class TestGuardaDeDesborde:
    """Si acotar la grilla no confina la accion, hay que enterarse y parar."""

    @pytest.fixture(autouse=True)
    def _registros_en_tmp(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ej, "RUTA_CICLOS_ABIERTOS", tmp_path / "ciclos.jsonl")
        monkeypatch.setattr(ej, "RUTA_ESCALADO", tmp_path / "escalado.jsonl")
        # Sin esto el sondeo gira los 90 s reales: `_PageFalsa.wait_for_timeout`
        # no duerme, asi que la espera se consume a toda velocidad de reloj.
        monkeypatch.setattr(ej, "SEG_SONDEO_CHECK", 0)
        monkeypatch.setattr(ej, "SEG_ENTRE_SONDEOS", 0)

    def test_si_cambia_otra_asignatura_se_detiene(self, monkeypatch):
        """El escenario que se teme: el filtro no confina y la accion arrasa."""
        antes = [_g(True, "OTRA", "11111"), _g(False, MATERIA, GRUPO)]
        # La accion vinculo la del reporte Y desvinculo la otra.
        despues = [_g(False, "OTRA", "11111"), _g(True, MATERIA, GRUPO)]
        esc = _Escenario(monkeypatch, antes=antes, despues=despues)
        with pytest.raises(AccionSeDesbordo) as exc:
            esc.ejecutar()
        assert "OTRA/11111" in str(exc.value)
        assert "no confina" in str(exc.value)

    def test_la_materia_objetivo_puede_cambiar_sin_disparar_la_guarda(self, monkeypatch):
        antes = [_g(True, "OTRA", "11111"), _g(False, MATERIA, GRUPO)]
        despues = [_g(True, "OTRA", "11111"), _g(True, MATERIA, GRUPO)]
        esc = _Escenario(monkeypatch, antes=antes, despues=despues)
        esc.ejecutar()  # no levanta
        assert esc.lecturas_todas >= 1

    def test_el_desborde_se_detecta_tras_el_desvincular_no_al_final(self, monkeypatch):
        """Enterarse antes de haber hecho el resto de la secuencia."""
        antes = [_g(True, "OTRA", "11111"), _g(True, MATERIA, GRUPO)]
        despues = [_g(False, "OTRA", "11111"), _g(False, MATERIA, GRUPO)]
        esc = _Escenario(monkeypatch, antes=antes, despues=despues)
        with pytest.raises(AccionSeDesbordo):
            esc.ejecutar()
        # Solo el desvincular: la guarda corto antes del vincular.
        assert esc.pedidas == [sesc.OPCION_DESVINCULAR]

    def test_se_puede_apagar_cuando_este_confirmado(self, monkeypatch):
        monkeypatch.setattr(ej, "COMPROBAR_DESBORDE", False)
        antes = [_g(True, "OTRA", "11111"), _g(False, MATERIA, GRUPO)]
        despues = [_g(False, "OTRA", "11111"), _g(True, MATERIA, GRUPO)]
        esc = _Escenario(monkeypatch, antes=antes, despues=despues)
        esc.ejecutar()
        assert esc.lecturas_todas == 0


class TestConfirmacionDelCheck:
    """El dialogo "Proceso terminado" no basta: hay que sondear el check."""

    @pytest.fixture(autouse=True)
    def _sin_esperas(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ej, "RUTA_CICLOS_ABIERTOS", tmp_path / "ciclos.jsonl")
        monkeypatch.setattr(ej, "RUTA_ESCALADO", tmp_path / "escalado.jsonl")
        # Sondeo instantaneo: los tests no esperan 90 s reales.
        monkeypatch.setattr(ej, "SEG_SONDEO_CHECK", 0)
        monkeypatch.setattr(ej, "SEG_ENTRE_SONDEOS", 0)

    def test_check_confirmado_no_escala(self, monkeypatch):
        esc = _Escenario(monkeypatch, antes=[_g(False)], despues=[_g(True)])
        r = esc.ejecutar()
        assert not r.requiere_escalado
        assert r.vinculadas_despues == 1
        assert ej.escalados_pendientes() == []

    def test_vinculado_sin_check_escala(self, monkeypatch):
        esc = _Escenario(monkeypatch, antes=[_g(False)], despues=[_g(False)])
        with pytest.raises(ej.CheckNoConfirmado) as exc:
            esc.ejecutar()
        assert "ISEF05" in str(exc.value) and "PACF50" in str(exc.value)
        pendientes = ej.escalados_pendientes()
        assert [p["motivo"] for p in pendientes] == [ej.MOTIVO_SIN_CHECK]
        assert pendientes[0]["materias_sin_check"] == [f"{MATERIA}/{GRUPO}"]

    def test_reintenta_antes_de_escalar(self, monkeypatch):
        esc = _Escenario(monkeypatch, antes=[_g(False)], despues=[_g(False)])
        with pytest.raises(ej.CheckNoConfirmado):
            esc.ejecutar()
        assert len(esc.pedidas) == ej.INTENTOS_HASTA_ESCALAR

    def test_isef07_no_permite_vincular_escala(self, monkeypatch):
        esc = _Escenario(
            monkeypatch, antes=[_g(False)], despues=[_g(False)],
            fallo=ej.AccionNoSeleccionada("desplegable vacio"),
        )
        with pytest.raises(ej.CheckNoConfirmado):
            esc.ejecutar()
        assert [p["motivo"] for p in ej.escalados_pendientes()] == [
            ej.MOTIVO_NO_PERMITE_VINCULAR
        ]

    def test_reciclado_sin_check_final_deja_el_ciclo_abierto(self, monkeypatch):
        """La materia venia con check y no volvio: quedo PEOR que al empezar."""
        esc = _Escenario(monkeypatch, antes=[_g(True)], despues=[_g(False)])
        with pytest.raises(CicloAbierto) as exc:
            esc.ejecutar()
        assert "QUEDO DESVINCULADA" in str(exc.value)
        assert len(ej.ciclos_abiertos()) == 1
        assert len(ej.escalados_pendientes()) == 1

    def test_desvincular_no_reflejado_avisa_pero_sigue_vinculando(self, monkeypatch):
        # El check nunca se va, pero al final esta puesto: es el estado buscado.
        esc = _Escenario(monkeypatch, antes=[_g(True)], despues=[_g(True)])
        r = esc.ejecutar()
        assert r.reciclado_incompleto
        assert esc.pedidas == [sesc.OPCION_DESVINCULAR, sesc.OPCION_VINCULAR]
        assert not r.ciclo_abierto
        assert ej.ciclos_abiertos() == []

    def test_no_poder_releer_tras_vincular_deja_ciclo_abierto(self, monkeypatch):
        esc = _Escenario(monkeypatch, antes=[_g(True)], despues=[_g(False)])
        estado = {"n": 0}

        def releer_materia():
            estado["n"] += 1
            if estado["n"] == 1:
                return [_g(False)]  # desvinculacion confirmada
            raise RuntimeError("la grilla no cargo")

        esc.releer_materia = releer_materia
        with pytest.raises(CicloAbierto):
            esc.ejecutar(releer_materia=releer_materia)
        assert len(ej.ciclos_abiertos()) == 1
        assert [p["motivo"] for p in ej.escalados_pendientes()] == [
            ej.MOTIVO_NO_VERIFICABLE
        ]

    def test_el_sondeo_acepta_un_check_que_tarda(self, monkeypatch):
        """El falso negativo del 03/09/2026: el check aparecio mas tarde."""
        monkeypatch.setattr(ej, "SEG_SONDEO_CHECK", 30)
        lecturas = iter([[_g(False)], [_g(False)], [_g(True)]])
        esc = _Escenario(monkeypatch, antes=[_g(False)], despues=[_g(True)])
        esc.releer_materia = lambda: next(lecturas)
        r = esc.ejecutar(releer_materia=esc.releer_materia)
        # Un solo vincular: el sondeo espero en vez de reintentar la escritura.
        assert esc.pedidas == [sesc.OPCION_VINCULAR]
        assert not r.requiere_escalado
