"""Las metricas del dia que van en el aviso de cierre."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from moodle_sinu import resumen_dia as rd  # noqa: E402

HOY = date(2026, 9, 8)


def _apunte(veredicto, periodo="2026D", objetivo="DCD05/20111", seg=110.0, dia="2026-09-08"):
    return {
        "momento": f"{dia}T10:00:00",
        "identificacion": "1000000001",
        "cod_periodo": periodo,
        "objetivo": objetivo,
        "veredicto": veredicto,
        "motivo": "x",
        "segundos": seg,
    }


@pytest.fixture
def diario(tmp_path, monkeypatch):
    ruta = tmp_path / "resultados_etapa4.jsonl"
    monkeypatch.setattr(rd, "RUTA_RESULTADOS", ruta)
    return ruta


def _escribir(ruta, apuntes):
    ruta.write_text(
        "\n".join(json.dumps(a) for a in apuntes) + "\n", encoding="utf-8"
    )


class TestLecturaDelDiario:
    def test_cuenta_verdes_y_rojos(self, diario):
        _escribir(diario, [_apunte("verde"), _apunte("verde"), _apunte("rojo")])
        r = rd.calcular(HOY, ciclos=[])
        assert (r.unidades, r.verdes, r.rojos) == (3, 2, 1)

    def test_solo_mira_el_dia_pedido(self, diario):
        """El diario se acumula entre corridas a proposito; el resumen no."""
        _escribir(
            diario,
            [_apunte("verde"), _apunte("verde", dia="2026-09-07")],
        )
        assert rd.calcular(HOY, ciclos=[]).unidades == 1

    def test_sin_archivo_no_es_un_error(self, diario):
        """Un dia sin corrida no es un fallo: es un dia sin corrida."""
        r = rd.calcular(HOY, ciclos=[])
        assert r.unidades == 0 and not r.hubo_trabajo

    def test_una_linea_a_medias_no_tumba_el_resumen(self, diario):
        """El diario se escribe con append desde varios procesos."""
        diario.write_text(
            json.dumps(_apunte("verde")) + "\n{ esto no es json\n" +
            json.dumps(_apunte("rojo")) + "\n",
            encoding="utf-8",
        )
        r = rd.calcular(HOY, ciclos=[])
        assert (r.unidades, r.verdes, r.rojos) == (2, 1, 1)

    def test_agrupa_por_periodo(self, diario):
        _escribir(
            diario,
            [
                _apunte("verde", periodo="2026C"),
                _apunte("verde", periodo="2026D"),
                _apunte("verde", periodo="2026D"),
            ],
        )
        assert rd.calcular(HOY, ciclos=[]).por_periodo == {"2026C": 1, "2026D": 2}


class TestDiagnosticoPorGrupo:
    def test_agrupa_los_rojos_por_materia_y_grupo(self, diario):
        """Lo que convierte una lista de 15 personas en un diagnostico de 2
        grupos. El 07/09/2026 fue exactamente asi."""
        _escribir(
            diario,
            [_apunte("rojo", objetivo="DCD05/20111") for _ in range(13)]
            + [_apunte("rojo", objetivo="DTA32/55598") for _ in range(2)]
            + [_apunte("verde", objetivo="DSIS4/30101")],
        )
        r = rd.calcular(HOY, ciclos=[])
        assert r.rojos_por_grupo == {"DCD05/20111": 13, "DTA32/55598": 2}
        # Se comprueba la intencion, no el acolchado: cada grupo con su cuenta.
        texto = rd.formatear(r)
        lineas = [" ".join(l.split()) for l in texto.splitlines()]
        assert "DCD05/20111 13 estudiante(s)" in lineas
        assert "DTA32/55598 2 estudiante(s)" in lineas
        assert "DSIS4/30101" not in texto  # los verdes no se escalan

    def test_sin_rojos_no_sale_la_seccion(self, diario):
        _escribir(diario, [_apunte("verde")])
        assert "validar a mano" not in rd.formatear(rd.calcular(HOY, ciclos=[]))


class TestCiclosAbiertos:
    def test_sin_ciclos_lo_dice_tranquilo(self, diario):
        _escribir(diario, [_apunte("verde")])
        texto = rd.formatear(rd.calcular(HOY, ciclos=[]))
        assert "0 (nadie desvinculado)" in texto

    def test_un_ciclo_abierto_va_destacado(self, diario):
        """Es lo peor que puede pasar en la etapa 4: el estudiante queda
        desvinculado. No puede leerse como una linea mas del resumen."""
        _escribir(diario, [_apunte("verde")])
        texto = rd.formatear(
            rd.calcular(
                HOY,
                ciclos=[
                    {
                        "identificacion": "1013637019",
                        "materia": "DCD05/20111",
                        "cod_periodo": "2026D",
                    }
                ],
            )
        )
        assert "!! CICLOS SIN CERRAR: 1" in texto
        assert "DESVINCULADOS ahora mismo" in texto
        assert "reparar_desvinculados" in texto


class TestTiempos:
    def test_informa_del_rango_y_la_media(self, diario):
        _escribir(
            diario,
            [_apunte("verde", seg=100.0), _apunte("verde", seg=200.0)],
        )
        texto = rd.formatear(rd.calcular(HOY, ciclos=[]))
        assert "100-200s (media 150s)" in texto

    def test_los_ceros_no_ensucian_la_media(self, diario):
        """Las rutas de excepcion anotaban segundos=0; no son medidas."""
        _escribir(
            diario,
            [_apunte("verde", seg=100.0), _apunte("rojo", seg=0)],
        )
        assert rd.calcular(HOY, ciclos=[]).segundos == [100.0]


class TestNota:
    def test_la_nota_va_al_final(self, diario):
        _escribir(diario, [_apunte("verde")])
        texto = rd.formatear(rd.calcular(HOY, ciclos=[]), nota="reintento de 3 periodos")
        assert texto.rstrip().endswith("Nota: reintento de 3 periodos")
