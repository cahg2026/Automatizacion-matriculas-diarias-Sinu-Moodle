"""Tests de la etapa 4: la regla de negocio y las guardas de seguridad.

La decision de que secuencia ejecutar es una funcion pura a proposito: es donde
un error deja estudiantes desvinculados, asi que se prueba entera sin navegador.
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
    CicloAbierto,
    ErrorEjecucionSinu,
    TipoSecuencia,
    acciones_de,
    decidir_secuencia,
    ejecutar_estudiante,
    estimar_segundos,
)
from moodle_sinu.restricciones_sinu import (  # noqa: E402
    ErrorRestriccionOperativa,
    exigir_modulo_escribible,
)


def _g(vinculado: bool, materia="A1I01", grupo="50609"):
    return FilaGrupoSinu(
        cod_materia=materia, num_grupo=grupo, curso_en_moodle=True, vinculado=vinculado
    )


class TestReglaDeNegocio:
    """Vinculado? False -> vincular. True -> desvincular y vincular."""

    def test_ninguna_vinculada_solo_vincula(self):
        assert decidir_secuencia([_g(False), _g(False, "B2")]) is TipoSecuencia.SOLO_VINCULAR

    def test_una_vinculada_recicla(self):
        assert decidir_secuencia([_g(True)]) is TipoSecuencia.RECICLAR

    def test_basta_una_vinculada_entre_varias(self):
        # La accion de ISEF07 es por estudiante, no por materia: no se puede
        # reciclar solo una. Con una vinculada, se recicla el estudiante.
        grupos = [_g(False, "A"), _g(True, "B"), _g(False, "C")]
        assert decidir_secuencia(grupos) is TipoSecuencia.RECICLAR

    def test_grilla_vacia_no_hace_nada(self):
        assert decidir_secuencia([]) is TipoSecuencia.NADA

    def test_el_orden_del_reciclado_es_desvincular_y_luego_vincular(self):
        # Al reves dejaria al estudiante desvinculado.
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


class TestModoSimulacion:
    """La barrera que impide tocar matriculas mientras se valida."""

    def test_simulacion_no_ejecuta_nada(self):
        cfg = Config(modo_simulacion=True)
        r = ejecutar_estudiante(
            page=None, cfg=cfg, identificacion="111", cod_periodo="26V05",
            grupos=[_g(True)],
        )
        assert r.simulado
        assert r.secuencia is TipoSecuencia.RECICLAR
        assert not r.ciclo_abierto

    def test_simulacion_informa_de_lo_que_haria(self):
        cfg = Config(modo_simulacion=True)
        r = ejecutar_estudiante(
            page=None, cfg=cfg, identificacion="111", cod_periodo="26V05",
            grupos=[_g(True)],
        )
        assert sesc.OPCION_DESVINCULAR in r.acciones_ejecutadas
        assert sesc.OPCION_VINCULAR in r.acciones_ejecutadas
        assert "SIMULACION" in r.detalle

    def test_simulacion_con_page_none_prueba_que_no_toca_el_navegador(self):
        # Si intentara pulsar algo, reventaria con AttributeError sobre None.
        cfg = Config(modo_simulacion=True)
        for grupos in ([_g(False)], [_g(True)], []):
            ejecutar_estudiante(
                page=None, cfg=cfg, identificacion="111", cod_periodo="26V05",
                grupos=grupos,
            )

    def test_sin_materias_no_hace_nada_ni_en_real(self):
        cfg = Config(modo_simulacion=False)
        r = ejecutar_estudiante(
            page=None, cfg=cfg, identificacion="111", cod_periodo="26V05", grupos=[]
        )
        assert r.secuencia is TipoSecuencia.NADA
        assert r.acciones_ejecutadas == []


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


class TestCiclosAbiertos:
    """El registro que sobrevive a que el proceso muera a mitad del reciclado."""

    @pytest.fixture(autouse=True)
    def registro_aislado(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ej, "RUTA_CICLOS_ABIERTOS", tmp_path / "ciclos.jsonl")

    def test_sin_registro_no_hay_ciclos(self):
        assert ej.ciclos_abiertos() == []

    def test_un_ciclo_sin_cerrar_se_reporta(self):
        ej._apuntar_ciclo("111", "26V05", "desvinculado-pendiente-vincular")
        abiertos = ej.ciclos_abiertos()
        assert len(abiertos) == 1
        assert abiertos[0]["identificacion"] == "111"

    def test_un_ciclo_cerrado_desaparece(self):
        ej._apuntar_ciclo("111", "26V05", "desvinculando")
        ej._apuntar_ciclo("111", "26V05", "cerrado")
        assert ej.ciclos_abiertos() == []

    def test_distingue_estudiantes_y_periodos(self):
        ej._apuntar_ciclo("111", "26V05", "desvinculando")
        ej._apuntar_ciclo("222", "26V05", "desvinculando")
        ej._apuntar_ciclo("111", "26V05", "cerrado")
        abiertos = ej.ciclos_abiertos()
        assert [a["identificacion"] for a in abiertos] == ["222"]

    def test_el_mismo_estudiante_en_otro_periodo_es_otro_ciclo(self):
        ej._apuntar_ciclo("111", "26V05", "desvinculando")
        ej._apuntar_ciclo("111", "26I04", "desvinculando")
        ej._apuntar_ciclo("111", "26V05", "cerrado")
        assert [a["cod_periodo"] for a in ej.ciclos_abiertos()] == ["26I04"]

    def test_una_linea_corrupta_no_rompe_la_lectura(self):
        ej.RUTA_CICLOS_ABIERTOS.write_text("esto no es json\n", encoding="utf-8")
        assert ej.ciclos_abiertos() == []


class TestReintentosDelVincular:
    def test_se_reintenta_mas_que_en_el_resto_del_proyecto(self):
        # Si este vincular falla, un estudiante queda desvinculado: merece mas
        # intentos que una operacion cualquiera.
        assert ej.REINTENTOS_VINCULAR_TRAS_DESVINCULAR >= 3

    def test_ciclo_abierto_es_un_error_aparte(self):
        # Nunca debe tratarse como "un fallo mas" en un except genérico.
        assert issubclass(CicloAbierto, ErrorEjecucionSinu)
        assert CicloAbierto is not ErrorEjecucionSinu
