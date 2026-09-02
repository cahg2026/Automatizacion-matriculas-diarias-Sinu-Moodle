"""Tests de la etapa 3: arbol de decision y barrera de escritura.

El arbol es una funcion pura a proposito: es la parte donde un error produce una
clasificacion incorrecta con toda la apariencia de ser correcta, asi que se
prueba entera sin abrir navegador.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from moodle_sinu.clasificador_sinu import (  # noqa: E402
    FilaGrupoSinu,
    aplicar_a_filas,
    clasificar_estudiante,
    clasificar_fila,
    emparejar,
    interpretar_check,
    marcar_pendiente_revisar,
)
from moodle_sinu.constantes import (  # noqa: E402
    CASOS_CON_ACCION,
    COL_COD_MATERIA,
    COL_COD_PERIODO,
    COL_IDENTIFICACION,
    COL_NOMBRE_COMPLETO,
    COL_NUM_GRUPO,
    Caso,
    Color,
    Validacion,
)
from moodle_sinu.modelos import FilaReporte  # noqa: E402
from moodle_sinu.clasificador_sinu import MODULOS_VERIFICACION_POR_CASO  # noqa: E402
from moodle_sinu.restricciones_sinu import (  # noqa: E402
    MODULOS_ESCRIBIBLES,
    MODULOS_LEGIBLES,
    MODULOS_SOLO_LECTURA,
    ErrorRestriccionOperativa,
    es_escribible,
    es_legible,
    es_solo_lectura,
    exigir_modulo_escribible,
    exigir_modulo_legible,
    resumen_permisos,
)


def _fila(n=2, materia="A1I01", grupo="50609", periodo="26I04", cedula="111"):
    saneados = {
        COL_IDENTIFICACION: cedula,
        COL_NOMBRE_COMPLETO: "ALUMNO X",
        COL_COD_MATERIA: materia,
        COL_NUM_GRUPO: grupo,
        COL_COD_PERIODO: periodo,
    }
    return FilaReporte(fila=n, crudos=dict(saneados), saneados=saneados)


def _grupo(materia="A1I01", grupo="50609", moodle=True, vinculado=False):
    return FilaGrupoSinu(
        cod_materia=materia,
        num_grupo=grupo,
        curso_en_moodle=moodle,
        vinculado=vinculado,
    )


# ---------------------------------------------------------------------------
# Lectura de los checks
# ---------------------------------------------------------------------------


class TestInterpretarCheck:
    @pytest.mark.parametrize(
        "valor", [True, "true", "1", "Sí", "si", "yes", "X", "checked", "marcado"]
    )
    def test_marcado(self, valor):
        assert interpretar_check(valor) is True

    @pytest.mark.parametrize("valor", [False, "false", "0", "no", "", "unchecked"])
    def test_desmarcado(self, valor):
        assert interpretar_check(valor) is False

    @pytest.mark.parametrize("valor", [None, "quizas", "???", "mixed"])
    def test_ilegible_es_none_no_false(self, valor):
        # Lo esencial: un check ilegible NO es un check desmarcado. Confundirlos
        # convertiria un dato ausente en un Caso 2 y el reporte afirmaria algo
        # que no se comprobo.
        assert interpretar_check(valor) is None


# ---------------------------------------------------------------------------
# Emparejamiento
# ---------------------------------------------------------------------------


class TestEmparejar:
    def test_casa_por_shortname_completo(self):
        grupo, ambiguo = emparejar(_fila(), [_grupo()])
        assert grupo is not None and not ambiguo

    def test_misma_materia_en_dos_grupos_no_se_elige_al_azar(self):
        # Casar solo por materia elegiria uno de los dos arbitrariamente.
        grupos = [_grupo(grupo="50609"), _grupo(grupo="99999")]
        grupo, ambiguo = emparejar(_fila(grupo="11111"), grupos)
        assert grupo is None and ambiguo

    def test_solo_por_materia_se_acepta_pero_se_marca_ambiguo(self):
        grupo, ambiguo = emparejar(_fila(grupo="OTRO"), [_grupo(grupo="50609")])
        assert grupo is not None and ambiguo

    def test_sin_coincidencia_no_es_ambiguo(self):
        grupo, ambiguo = emparejar(_fila(materia="ZZZZZ"), [_grupo()])
        assert grupo is None and not ambiguo


# ---------------------------------------------------------------------------
# El arbol de decision
# ---------------------------------------------------------------------------


class TestArbolDeDecision:
    def test_caso_1_moodle_si_vinculado_no(self):
        c = clasificar_fila(_fila(), [_grupo(moodle=True, vinculado=False)])
        assert c.caso is Caso.CASO_1_VINCULADO
        assert c.validacion is Validacion.OK
        assert c.color is Color.VERDE_CLARO
        assert c.requiere_accion

    def test_caso_1_ya_vinculado_si_requiere_accion(self):
        # Cambio del 21/08/2026: la regla del dueno del proceso recicla lo ya
        # vinculado (desvincular + vincular) en vez de saltarlo. La etiqueta
        # sigue siendo distinta de OK porque no lo vinculo el robot hoy.
        c = clasificar_fila(_fila(), [_grupo(moodle=True, vinculado=True)])
        assert c.caso is Caso.CASO_1_YA_VINCULADO
        assert c.validacion is Validacion.YA_VINCULADO
        assert c.color is Color.VERDE_CLARO
        assert c.requiere_accion

    def test_caso_2_sin_check_en_moodle(self):
        c = clasificar_fila(_fila(), [_grupo(moodle=False)])
        assert c.caso is Caso.CASO_2_SIN_CHECK
        assert c.validacion is Validacion.SIN_CHECK_MOODLE
        assert c.color is Color.ROJO_CLARO
        assert not c.requiere_accion

    def test_caso_2_manda_sobre_vinculado(self):
        # Sin check en Moodle, el estado de 'Vinculado?' es irrelevante.
        c = clasificar_fila(_fila(), [_grupo(moodle=False, vinculado=True)])
        assert c.caso is Caso.CASO_2_SIN_CHECK

    def test_caso_3_sin_registro_en_la_grilla(self):
        c = clasificar_fila(_fila(materia="ZZZZZ"), [_grupo()])
        assert c.caso is Caso.CASO_3_SIN_MATRICULA
        assert c.validacion is Validacion.SIN_MATRICULA
        assert c.color is Color.LILA
        assert not c.requiere_accion

    def test_caso_3_con_grilla_vacia(self):
        c = clasificar_fila(_fila(), [])
        assert c.caso is Caso.CASO_3_SIN_MATRICULA

    def test_solo_las_variantes_del_caso_1_disparan_accion(self):
        # Los casos 2 y 3 no se tocan: no hay curso en Moodle o no hay matricula.
        assert CASOS_CON_ACCION == frozenset(
            {Caso.CASO_1_VINCULADO, Caso.CASO_1_YA_VINCULADO}
        )
        assert Caso.CASO_2_SIN_CHECK not in CASOS_CON_ACCION
        assert Caso.CASO_3_SIN_MATRICULA not in CASOS_CON_ACCION

    def test_el_detalle_nombra_el_shortname(self):
        # El detalle es la evidencia de por que se clasifico asi.
        c = clasificar_fila(_fila(), [_grupo()])
        assert "A1I01/50609" in c.detalle


class TestClasificarEstudiante:
    def test_una_lectura_clasifica_todas_sus_filas(self):
        # La ganancia del diseno: una busqueda en ISEF07 por estudiante.
        filas = [
            _fila(2, materia="A1I01", grupo="50609"),
            _fila(3, materia="B2J02", grupo="50610"),
            _fila(4, materia="C3K03", grupo="50611"),
        ]
        grupos = [
            _grupo("A1I01", "50609", moodle=True, vinculado=False),
            _grupo("B2J02", "50610", moodle=False),
            _grupo("C3K03", "50611", moodle=True, vinculado=True),
        ]
        r = clasificar_estudiante(filas, grupos, identificacion="111", cod_periodo="26I04")
        assert r.clasificaciones[2].caso is Caso.CASO_1_VINCULADO
        assert r.clasificaciones[3].caso is Caso.CASO_2_SIN_CHECK
        assert r.clasificaciones[4].caso is Caso.CASO_1_YA_VINCULADO

    def test_grilla_vacia_deja_advertencia(self):
        r = clasificar_estudiante([_fila()], [], identificacion="111", cod_periodo="26I04")
        assert r.advertencias
        assert r.clasificaciones[2].caso is Caso.CASO_3_SIN_MATRICULA

    def test_los_emparejamientos_ambiguos_se_avisan(self):
        r = clasificar_estudiante(
            [_fila(grupo="OTRO")], [_grupo(grupo="50609")],
            identificacion="111", cod_periodo="26I04",
        )
        assert any("ambiguo" in a for a in r.advertencias)


class TestAplicarAFilas:
    def test_rellena_los_campos_que_consume_el_excel(self):
        filas = [_fila(2)]
        r = clasificar_estudiante(filas, [_grupo()], identificacion="111", cod_periodo="26I04")
        aplicar_a_filas(filas, r)
        assert filas[0].caso is Caso.CASO_1_VINCULADO
        assert filas[0].validacion_rpa is Validacion.OK
        assert filas[0].color_fila is Color.VERDE_CLARO

    def test_pendiente_por_revisar_no_asigna_color(self):
        # El reporte no debe afirmar un caso que no se comprobo.
        fila = _fila()
        marcar_pendiente_revisar(fila, "fallo de selector")
        assert fila.validacion_rpa is Validacion.PENDIENTE_REVISAR
        assert fila.color_fila is None
        assert fila.caso is None


# ---------------------------------------------------------------------------
# Barrera de escritura
# ---------------------------------------------------------------------------


class TestPermisoDeLectura:
    """Los cuatro modulos son consultables (decision del 21/08/2026)."""

    @pytest.mark.parametrize("modulo", ["isef07", "isef05", "pacf50", "matf88"])
    def test_los_cuatro_se_pueden_consultar(self, modulo):
        exigir_modulo_legible(modulo, "verificar matricula")
        assert es_legible(modulo)

    def test_la_lista_de_lectura_son_exactamente_esos_cuatro(self):
        assert MODULOS_LEGIBLES == frozenset({"isef07", "isef05", "pacf50", "matf88"})

    def test_un_modulo_no_autorizado_no_se_puede_ni_consultar(self):
        # Lista blanca tambien para lectura: entrar donde nadie autorizo es
        # navegar por datos academicos sin permiso.
        with pytest.raises(ErrorRestriccionOperativa, match="no esta en la lista"):
            exigir_modulo_legible("ISEF99", "curiosear")

    def test_es_indiferente_a_mayusculas(self):
        exigir_modulo_legible("  isef05 ", "consultar")

    def test_leer_no_implica_escribir(self):
        # El corazon del ajuste: los tres modulos se consultan pero no se tocan.
        for modulo in ("isef05", "pacf50", "matf88"):
            assert es_legible(modulo)
            assert not es_escribible(modulo)


class TestCoherenciaDeLaMatriz:
    def test_solo_lectura_es_derivado_de_las_dos_listas(self):
        # No se escribe a mano: asi las listas no pueden desincronizarse.
        assert MODULOS_SOLO_LECTURA == MODULOS_LEGIBLES - MODULOS_ESCRIBIBLES

    def test_todo_lo_escribible_es_legible(self):
        # Un modulo escribible y no legible seria un error de modelado.
        assert MODULOS_ESCRIBIBLES <= MODULOS_LEGIBLES

    def test_isef07_es_el_unico_con_ambos_permisos(self):
        ambos = {m for m in MODULOS_LEGIBLES if es_escribible(m)}
        assert ambos == {"isef07"}

    def test_el_resumen_muestra_los_cuatro_modulos(self):
        texto = resumen_permisos()
        for modulo in ("isef07", "isef05", "pacf50", "matf88"):
            assert modulo in texto

    def test_el_arbol_solo_pide_consultar_modulos_autorizados(self):
        for modulos in MODULOS_VERIFICACION_POR_CASO.values():
            for modulo in modulos:
                assert modulo in MODULOS_LEGIBLES


class TestModulosDeVerificacion:
    """Que modulos manda consultar el arbol para confirmar cada caso."""

    def test_el_caso_1_no_necesita_verificacion(self):
        c = clasificar_fila(_fila(), [_grupo(moodle=True, vinculado=False)])
        assert c.modulos_a_verificar == ()

    def test_el_caso_2_manda_a_isef05_y_pacf50(self):
        c = clasificar_fila(_fila(), [_grupo(moodle=False)])
        assert set(c.modulos_a_verificar) == {"isef05", "pacf50"}

    def test_el_caso_3_anade_isef88(self):
        c = clasificar_fila(_fila(materia="ZZZZZ"), [_grupo()])
        assert set(c.modulos_a_verificar) == {"isef05", "pacf50", "matf88"}

    def test_ninguna_verificacion_es_escribible(self):
        # Todo lo que el arbol manda consultar es de solo ver.
        for caso, modulos in MODULOS_VERIFICACION_POR_CASO.items():
            for modulo in modulos:
                assert es_solo_lectura(modulo), (caso, modulo)


class TestRestriccionOperativa:
    """Decision del dueno del proceso: solo ISEF07 se escribe."""

    def test_isef07_esta_permitido(self):
        exigir_modulo_escribible("ISEF07", "Vincular grupos matriculados")

    def test_es_indiferente_a_mayusculas_y_espacios(self):
        exigir_modulo_escribible("  isef07 ", "vincular")

    @pytest.mark.parametrize("modulo", ["isef05", "pacf50", "matf88"])
    def test_los_modulos_de_solo_lectura_estan_bloqueados(self, modulo):
        with pytest.raises(ErrorRestriccionOperativa, match="SOLO"):
            exigir_modulo_escribible(modulo, "desvincular")

    @pytest.mark.parametrize("modulo", ["isef05", "pacf50", "matf88"])
    def test_el_mensaje_nombra_el_modulo_y_la_accion(self, modulo):
        with pytest.raises(ErrorRestriccionOperativa) as exc:
            exigir_modulo_escribible(modulo, "borrar matricula")
        assert modulo in str(exc.value)
        assert "borrar matricula" in str(exc.value)

    def test_un_modulo_desconocido_se_bloquea_por_defecto(self):
        # Lista blanca, no lista negra: lo que no esta autorizado, se prohibe.
        with pytest.raises(ErrorRestriccionOperativa):
            exigir_modulo_escribible("ISEF99", "lo que sea")

    def test_isef88_ya_no_existe(self):
        # Codigo inexistente en el sistema: el modulo real es matf88. Si alguien
        # lo reintroduce, esto lo caza.
        with pytest.raises(ErrorRestriccionOperativa):
            exigir_modulo_legible("isef88", "consultar")
        assert "isef88" not in MODULOS_LEGIBLES

    def test_vacio_se_bloquea(self):
        with pytest.raises(ErrorRestriccionOperativa):
            exigir_modulo_escribible("", "accion")

    def test_solo_isef07_es_escribible(self):
        assert MODULOS_ESCRIBIBLES == frozenset({"isef07"})

    @pytest.mark.parametrize("modulo", ["isef05", "pacf50", "matf88"])
    def test_es_solo_lectura(self, modulo):
        assert es_solo_lectura(modulo)

    def test_isef07_no_es_solo_lectura(self):
        assert not es_solo_lectura("ISEF07")


class TestEtapa3NoEscribe:
    """La garantia estructural: el codigo de escritura no existe en la etapa 3."""

    def test_los_selectores_no_incluyen_controles_de_escritura(self):
        from moodle_sinu import selectores_sinu

        nombres = " ".join(dir(selectores_sinu)).lower()
        # El desplegable de accion y el icono de ejecutar no se declaran aqui:
        # la etapa 3 no puede pulsar lo que no sabe localizar.
        assert "accion_realizar" not in nombres
        assert "ejecutar" not in nombres

    def test_el_lector_no_importa_la_accion_de_vincular(self):
        from moodle_sinu import lector_sinu

        fuente = Path(lector_sinu.__file__).read_text(encoding="utf-8")
        assert "ACCION_VINCULAR" not in fuente
        assert "ACCION_DESVINCULAR" not in fuente
