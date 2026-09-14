"""La logica del orquestador del dia.

Estas pruebas son la mitad del motivo para haber salido de PowerShell: en el
.ps1 esta logica no se podia probar, y sus tres defectos del 07/09/2026
vivian justo aqui -- la bitacora en UTF-16, la rotacion del diario colocada
antes de tiempo y el `--saltar-hechas` que no se pasaba nunca.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))


def _cargar_orquestador():
    ruta = RAIZ / "scripts" / "dia_completo.py"
    spec = importlib.util.spec_from_file_location("dia_completo", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


dc = _cargar_orquestador()


# ---------------------------------------------------------------------------
# El cerrojo de escritura: lo mas delicado del script
# ---------------------------------------------------------------------------

ENV_EJEMPLO = """\
# Comentario que documenta la variable
POWERBI_USUARIO=alguien@cun.edu.co

# true -> jamas se ejecuta "Vincular grupos matriculados" en SINU.
MODO_SIMULACION=false

DEDUPLICAR_EXACTOS=true
"""


class TestCerrojoDeEscritura:
    @pytest.fixture
    def env(self, tmp_path, monkeypatch):
        ruta = tmp_path / ".env"
        ruta.write_text(ENV_EJEMPLO, encoding="utf-8")
        monkeypatch.setattr(dc, "RUTA_ENV", ruta)
        return ruta

    def test_lee_el_valor(self, env):
        assert dc.leer_simulacion() == "false"

    def test_lo_cambia(self, env):
        dc.fijar_simulacion("true")
        assert dc.leer_simulacion() == "true"

    def test_conserva_los_comentarios(self, env):
        """El .env documenta cada variable. Reescribirlo entero los perderia,
        y esos comentarios son media memoria del proyecto."""
        dc.fijar_simulacion("true")
        texto = env.read_text(encoding="utf-8")
        assert "# Comentario que documenta la variable" in texto
        assert '# true -> jamas se ejecuta "Vincular grupos matriculados"' in texto
        assert "POWERBI_USUARIO=alguien@cun.edu.co" in texto
        assert "DEDUPLICAR_EXACTOS=true" in texto

    def test_ida_y_vuelta_no_deja_rastro(self, env):
        original = env.read_text(encoding="utf-8")
        dc.fijar_simulacion("true")
        dc.fijar_simulacion("false")
        assert env.read_text(encoding="utf-8") == original

    def test_sin_env_no_revienta(self, tmp_path, monkeypatch):
        monkeypatch.setattr(dc, "RUTA_ENV", tmp_path / "no-existe")
        assert dc.leer_simulacion() == "(sin .env)"
        dc.fijar_simulacion("true")  # no debe lanzar

    def test_tambien_fija_el_entorno_del_proceso(self, env, monkeypatch):
        """El defecto del 08/09/2026, que se fue una corrida entera.

        `Config.desde_entorno()` deja MODO_SIMULACION en os.environ con el
        valor que tenia el .env en ese instante. Los subprocesos heredan ese
        entorno, y su `load_dotenv(override=False)` NO pisa una variable que ya
        existe: leen el valor viejo. Escribir solo el archivo no basta -- la
        corrida con --ejecutar-de-verdad simulo sin escribir nada, y el fallo
        era mudo porque erraba del lado seguro.
        """
        import os

        monkeypatch.setenv("MODO_SIMULACION", "true")
        dc.fijar_simulacion("false")
        assert dc.leer_simulacion() == "false"          # el archivo
        assert os.environ["MODO_SIMULACION"] == "false"  # lo que veran los hijos

    def test_el_entorno_se_fija_aunque_no_haya_env(self, tmp_path, monkeypatch):
        """Sin archivo tampoco se puede dejar el entorno con el valor viejo."""
        import os

        monkeypatch.setattr(dc, "RUTA_ENV", tmp_path / "no-existe")
        monkeypatch.setenv("MODO_SIMULACION", "true")
        dc.fijar_simulacion("false")
        assert os.environ["MODO_SIMULACION"] == "false"

    def test_variable_ausente_se_dice(self, tmp_path, monkeypatch):
        ruta = tmp_path / ".env"
        ruta.write_text("OTRA=1\n", encoding="utf-8")
        monkeypatch.setattr(dc, "RUTA_ENV", ruta)
        assert dc.leer_simulacion() == "(no definido)"


# ---------------------------------------------------------------------------
# Localizar los archivos intermedios
# ---------------------------------------------------------------------------


class TestMasReciente:
    def test_elige_el_mas_nuevo(self, tmp_path):
        viejo = tmp_path / "a.xlsx"
        nuevo = tmp_path / "b.xlsx"
        viejo.write_text("x")
        nuevo.write_text("y")
        import os

        os.utime(viejo, (1000, 1000))
        os.utime(nuevo, (2000, 2000))
        assert dc.mas_reciente(tmp_path, "*.xlsx") == nuevo

    def test_respeta_el_patron(self, tmp_path):
        (tmp_path / "crudo.xlsx").write_text("x")
        esperado = tmp_path / "algo_validado_hoy.xlsx"
        esperado.write_text("y")
        assert dc.mas_reciente(tmp_path, "*_validado_*.xlsx") == esperado

    def test_sin_nada_devuelve_none(self, tmp_path):
        assert dc.mas_reciente(tmp_path, "*.xlsx") is None

    def test_carpeta_inexistente_devuelve_none(self, tmp_path):
        assert dc.mas_reciente(tmp_path / "no-va", "*.xlsx") is None


# ---------------------------------------------------------------------------
# La URL del Sheet: el unico dato que se lee de una salida
# ---------------------------------------------------------------------------


class TestUrlDeSheet:
    def test_la_encuentra_en_una_linea_de_log(self):
        salida = (
            "2026-09-08 10:15:13 INFO subidor_drive Sheet abierto en una pestana: "
            "https://docs.google.com/spreadsheets/d/1lEPF0h7J3fYLtXeAIwexGIU33Vmq6J_0byYv3iA_3Zk"
            "/edit?gid=1000000105#gid=1000000105"
        )
        assert dc.url_de_sheet(salida) == (
            "https://docs.google.com/spreadsheets/d/"
            "1lEPF0h7J3fYLtXeAIwexGIU33Vmq6J_0byYv3iA_3Zk"
        )

    def test_recorta_lo_que_sobra(self):
        """Se queda con el id y suelta '/edit?gid=...': lo que hace falta para
        pasarlo a las etapas siguientes."""
        u = dc.url_de_sheet("x https://docs.google.com/spreadsheets/d/AB-c_9/edit#x y")
        assert u == "https://docs.google.com/spreadsheets/d/AB-c_9"

    def test_si_no_hay_devuelve_none(self):
        """Y entonces el flujo se detiene y lo dice, en vez de seguir sin ella."""
        assert dc.url_de_sheet("La subida fallo") is None
        assert dc.url_de_sheet("") is None
        assert dc.url_de_sheet(None) is None


# ---------------------------------------------------------------------------
# Rotacion del diario
# ---------------------------------------------------------------------------


class TestRotacionDelDiario:
    def test_el_de_ayer_se_rota(self, tmp_path):
        """Si no, `--saltar-hechas` saltaria unidades de hoy creyendolas
        hechas: compara por (periodo, cedula, materia) sin mirar la fecha."""
        import os

        diario = tmp_path / "resultados_etapa4.jsonl"
        diario.write_text("{}\n", encoding="utf-8")
        ayer = date.today() - timedelta(days=1)
        import datetime as _dt

        marca = _dt.datetime.combine(ayer, _dt.time(12, 0)).timestamp()
        os.utime(diario, (marca, marca))
        assert dc.toca_rotar(diario, date.today())

    def test_el_de_hoy_no_se_toca(self, tmp_path):
        """Reanudar dentro del mismo dia tiene que conservarlo: es lo que
        evita repetir trabajo ya hecho."""
        diario = tmp_path / "resultados_etapa4.jsonl"
        diario.write_text("{}\n", encoding="utf-8")
        assert not dc.toca_rotar(diario, date.today())

    def test_sin_diario_no_hay_nada_que_rotar(self, tmp_path):
        assert not dc.toca_rotar(tmp_path / "no-existe", date.today())


# ---------------------------------------------------------------------------
# La bitacora
# ---------------------------------------------------------------------------


class TestBitacora:
    def test_escribe_en_utf8(self, tmp_path, capsys):
        """El defecto del .ps1: `Tee-Object` no acepta -Encoding en
        PowerShell 5.1 y escribia UTF-16, ilegible en editor o grep."""
        bit = dc.Bitacora(tmp_path / "b.log")
        bit.escribir("periodo 26V05, materia con acentos: ñ á é")
        crudo = (tmp_path / "b.log").read_bytes()
        assert crudo.decode("utf-8").startswith("periodo 26V05")
        assert b"\x00" not in crudo  # UTF-16 mete ceros; UTF-8 no

    def test_tambien_sale_por_consola(self, tmp_path, capsys):
        bit = dc.Bitacora(tmp_path / "b.log")
        bit.escribir("hola")
        assert "hola" in capsys.readouterr().out

    def test_crea_la_carpeta_si_falta(self, tmp_path):
        bit = dc.Bitacora(tmp_path / "sub" / "otra" / "b.log")
        bit.escribir("x")
        assert bit.ruta.is_file()
