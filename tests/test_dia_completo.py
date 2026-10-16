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
            "https://docs.google.com/spreadsheets/d/1HojaDeEjemploFicticia0000000000000000000000"
            "/edit?gid=1000000105#gid=1000000105"
        )
        assert dc.url_de_sheet(salida) == (
            "https://docs.google.com/spreadsheets/d/"
            "1HojaDeEjemploFicticia0000000000000000000000"
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


# ---------------------------------------------------------------------------
# Los reintentos de la etapa 2
#
# El hueco que tapan: el 18, el 22 y el 23/09/2026 el proceso principal de
# Chrome reviento justo al arrancar la descarga (0xC0000005 en chrome.dll) y
# el dia entero termino con 0 matriculas procesadas, pese a que el reintento a
# mano pasaba a la primera.
# ---------------------------------------------------------------------------


class _CfgFalsa:
    """Lo minimo que mira `exportar_con_reintentos`."""

    def __init__(self, reintentos=5, espera=90):
        self.exportacion_reintentos = reintentos
        self.exportacion_espera_seg = espera


class TestMotivoDelFallo:
    def test_saca_el_texto_tras_exportacion_fallida(self):
        salida = (
            "INFO Abriendo el informe\n"
            "ERROR exportar_reporte Exportacion fallida: Error de Playwright "
            "durante la exportacion: Download.save_as: Target page, context or "
            "browser has been closed\n"
        )
        assert "Download.save_as" in dc.motivo_del_fallo(salida)

    def test_se_queda_con_el_ultimo_error(self):
        salida = "ERROR: primero\nERROR: segundo\n"
        assert dc.motivo_del_fallo(salida) == "segundo"

    def test_sin_errores_devuelve_vacio(self):
        assert dc.motivo_del_fallo("todo fue bien\n") == ""


class TestExportarConReintentos:
    @pytest.fixture
    def sin_esperas(self, monkeypatch):
        """Ni duerme ni mata procesos: la prueba no debe tardar 90s."""
        monkeypatch.setattr(dc.time, "sleep", lambda _s: None)
        monkeypatch.setattr(dc, "limpiar_chrome_colgado", lambda _b, _c: 0)

    def _con_resultados(self, monkeypatch, resultados):
        llamadas = []

        def falso_correr(orden, bit):
            llamadas.append(orden)
            return resultados[len(llamadas) - 1]

        monkeypatch.setattr(dc, "correr", falso_correr)
        return llamadas

    def test_a_la_primera_no_reintenta(self, tmp_path, monkeypatch, sin_esperas):
        llamadas = self._con_resultados(monkeypatch, [(0, "")])
        paso = dc.PasoEnCurso()
        dc.exportar_con_reintentos(dc.Bitacora(tmp_path / "b.log"), _CfgFalsa(), paso)
        assert len(llamadas) == 1
        assert paso.intentos == "1 de 5"

    def test_reintenta_hasta_que_sale_bien(self, tmp_path, monkeypatch, sin_esperas):
        """Lo que de verdad importa: la caida de Chrome ya no cuesta el dia."""
        llamadas = self._con_resultados(
            monkeypatch,
            [
                (1, "ERROR: Download.save_as: browser has been closed"),
                (1, "ERROR: Download.save_as: browser has been closed"),
                (0, ""),
            ],
        )
        paso = dc.PasoEnCurso()
        dc.exportar_con_reintentos(dc.Bitacora(tmp_path / "b.log"), _CfgFalsa(), paso)
        assert len(llamadas) == 3
        assert paso.intentos == "3 de 5"

    def test_se_rinde_tras_agotarlos_y_dice_el_motivo(
        self, tmp_path, monkeypatch, sin_esperas
    ):
        self._con_resultados(monkeypatch, [(1, "ERROR: se cayo Chrome")] * 5)
        paso = dc.PasoEnCurso()
        with pytest.raises(dc.FalloDelFlujo) as exc:
            dc.exportar_con_reintentos(
                dc.Bitacora(tmp_path / "b.log"), _CfgFalsa(), paso
            )
        assert "5 intentos" in str(exc.value)
        assert "se cayo Chrome" in str(exc.value)
        assert paso.intentos == "5 de 5"

    def test_limpia_chrome_entre_intentos_pero_no_tras_el_ultimo(
        self, tmp_path, monkeypatch
    ):
        """Sin esta limpieza el reintento hereda el navegador envenenado: es
        lo que hundio el reintento a mano del 23/09/2026 a las 09:09."""
        monkeypatch.setattr(dc.time, "sleep", lambda _s: None)
        limpiezas = []
        monkeypatch.setattr(
            dc, "limpiar_chrome_colgado", lambda _b, _c: limpiezas.append(1)
        )
        self._con_resultados(monkeypatch, [(1, "ERROR: x")] * 3)
        with pytest.raises(dc.FalloDelFlujo):
            dc.exportar_con_reintentos(
                dc.Bitacora(tmp_path / "b.log"), _CfgFalsa(reintentos=3), dc.PasoEnCurso()
            )
        assert len(limpiezas) == 2  # entre 1-2 y 2-3, no despues del 3

    def test_un_uso_incorrecto_no_se_reintenta(self, tmp_path, monkeypatch, sin_esperas):
        """Codigo 2 = argumentos incompatibles. Repetirlo cinco veces solo
        gasta diez minutos para volver a fallar igual."""
        llamadas = self._con_resultados(
            monkeypatch, [(2, "ERROR: --visible y --headless son incompatibles.")]
        )
        with pytest.raises(dc.FalloDelFlujo) as exc:
            dc.exportar_con_reintentos(
                dc.Bitacora(tmp_path / "b.log"), _CfgFalsa(), dc.PasoEnCurso()
            )
        assert len(llamadas) == 1
        assert "Repetirla no lo" in str(exc.value)


# ---------------------------------------------------------------------------
# El reintento de la etapa 3 (26/09/2026)
#
# Era el unico paso del flujo sin red, y fallaba en el peor momento: con el
# cerrojo de escritura ya abierto y el reporte ya descargado. Pero el reintento
# NO sale gratis como el de la exportacion -- si la primera subida llego a crear
# el Sheet, la segunda crea otro --, y eso es lo que estas pruebas sostienen.
# ---------------------------------------------------------------------------


class TestSubirConReintento:
    def _con_resultados(self, monkeypatch, resultados, copias=None):
        """`copias` es lo que `mas_reciente` devuelve, llamada a llamada.

        El orden de las llamadas en `subir_con_reintento` es: una al principio
        (la foto de `antes`), una al empezar cada intento, y una mas al salir
        bien. Agotada la lista se repite el ultimo valor, para que la prueba no
        sea fragil frente a una llamada de mas.
        """
        llamadas = []
        vistas = list(copias or [None])

        def falso_correr(orden, bit):
            llamadas.append(orden)
            return resultados[len(llamadas) - 1]

        def falso_mas_reciente(_carpeta, _patron):
            return vistas.pop(0) if len(vistas) > 1 else vistas[0]

        monkeypatch.setattr(dc, "correr", falso_correr)
        monkeypatch.setattr(dc, "mas_reciente", falso_mas_reciente)
        return llamadas

    def test_a_la_primera_no_reintenta(self, tmp_path, monkeypatch):
        copia = tmp_path / "r_validado_1.xlsx"
        llamadas = self._con_resultados(
            monkeypatch, [(0, "https://docs.google.com/spreadsheets/d/ABC")],
            copias=[None, None, copia],
        )
        paso = dc.PasoEnCurso()
        salida, validado = dc.subir_con_reintento(
            dc.Bitacora(tmp_path / "b.log"), "r.xlsx", paso
        )
        assert len(llamadas) == 1
        assert validado == str(copia)
        assert paso.intentos == "1 de 2"

    def test_reintenta_una_vez_y_sale_bien(self, tmp_path, monkeypatch):
        """El caso que motiva el cambio: un tropiezo de Drive ya no mata el dia."""
        copia = tmp_path / "r_validado_1.xlsx"
        llamadas = self._con_resultados(
            monkeypatch,
            [
                (1, "ERROR: no se pudo soltar el archivo en Drive"),
                (0, "https://docs.google.com/spreadsheets/d/ABC"),
            ],
            copias=[None, None, None, copia],
        )
        paso = dc.PasoEnCurso()
        dc.subir_con_reintento(dc.Bitacora(tmp_path / "b.log"), "r.xlsx", paso)
        assert len(llamadas) == 2
        assert paso.intentos == "2 de 2"

    def test_no_reintenta_si_el_sheet_ya_se_creo(self, tmp_path, monkeypatch):
        """La proteccion clave. Si la subida SI ocurrio y lo que fallo vino
        despues, un segundo intento deja DOS Sheets del mismo dia en Drive y el
        operador no sabe cual esta procesando el robot."""
        llamadas = self._con_resultados(
            monkeypatch,
            [(1, "Sheet: https://docs.google.com/spreadsheets/d/ABC\nERROR: se colgo")],
            copias=[None],
        )
        with pytest.raises(dc.FalloDelFlujo) as exc:
            dc.subir_con_reintento(dc.Bitacora(tmp_path / "b.log"), "r.xlsx", dc.PasoEnCurso())
        assert len(llamadas) == 1
        assert "spreadsheets/d/ABC" in str(exc.value)
        assert "dos Sheets" in str(exc.value)

    def test_el_reintento_reusa_la_copia_coloreada(self, tmp_path, monkeypatch):
        """Si la Fase 1 ya termino, no se rehace: generaria otra copia identica
        con otro sello, y las etapas 4 y 5 localizan 'la de hoy' por fecha."""
        copia = tmp_path / "r_validado_1.xlsx"
        llamadas = self._con_resultados(
            monkeypatch,
            [(1, "ERROR: fallo la subida"), (0, "https://docs.google.com/spreadsheets/d/ABC")],
            copias=[None, None, copia, copia],
        )
        dc.subir_con_reintento(dc.Bitacora(tmp_path / "b.log"), "r.xlsx", dc.PasoEnCurso())
        assert "--ya-validado" in llamadas[1]
        assert str(copia) in [str(x) for x in llamadas[1]]
        assert "--ya-validado" not in llamadas[0]

    def test_los_dos_intentos_fallan(self, tmp_path, monkeypatch):
        llamadas = self._con_resultados(
            monkeypatch,
            [(1, "ERROR: fallo la subida"), (1, "ERROR: fallo otra vez")],
            copias=[None, None, None],
        )
        with pytest.raises(dc.FalloDelFlujo) as exc:
            dc.subir_con_reintento(dc.Bitacora(tmp_path / "b.log"), "r.xlsx", dc.PasoEnCurso())
        assert len(llamadas) == 2
        assert "fallo otra vez" in str(exc.value)

    def test_solo_un_reintento(self):
        """Dos y no cinco: aqui el reintento puede duplicar el Sheet."""
        assert dc.SUBIDA_INTENTOS == 2


class TestPasoEnCurso:
    def test_arranca_con_un_nombre_util(self):
        assert dc.PasoEnCurso().nombre

    def test_en_cambia_el_paso_y_borra_los_intentos(self):
        p = dc.PasoEnCurso()
        p.intentos = "3 de 5"
        p.en("PASO 4/6 - Procesar las matriculas en ISEF07")
        assert p.nombre == "PASO 4/6 - Procesar las matriculas en ISEF07"
        assert p.intentos == ""


# ---------------------------------------------------------------------------
# La pausa por tablero viejo (paso 1 -> codigo 3), desde el 28/09/2026
# ---------------------------------------------------------------------------

SALIDA_CERROJO_VIEJO = (
    "Tablero dice : 'Datos actualizados el 27/9/26'\n"
    "Interpretado : 27/09/2026\n"
    "Estado       : desactualizado (ultima actualizacion 27/09/2026, hace 1 dia)\n"
    "-> NO ACTUALIZADO HOY. El flujo NO debe continuar.\n"
)


class TestDetalleDelCerrojo:
    def test_saca_la_linea_de_estado(self):
        assert dc.detalle_del_cerrojo(SALIDA_CERROJO_VIEJO) == (
            "desactualizado (ultima actualizacion 27/09/2026, hace 1 dia)"
        )

    def test_sin_linea_hay_un_texto_por_defecto(self):
        assert dc.detalle_del_cerrojo("") == "la fecha del tablero es anterior a hoy"


@pytest.fixture
def avisos(monkeypatch):
    enviados = []

    class _R:
        def resumen(self):
            return "enviado (prueba)"

    def falso_enviar(aviso, cfg):
        enviados.append(aviso)
        return _R()

    monkeypatch.setattr(dc.notificaciones, "enviar", falso_enviar)
    return enviados


class TestPausarPorTableroViejo:
    @pytest.fixture(autouse=True)
    def estado_en_tmp(self, tmp_path, monkeypatch):
        monkeypatch.setattr(dc.estado_dia, "DIR_ESTADO", tmp_path / "estado")
        return tmp_path / "estado"

    def test_registra_el_estado_y_avisa(self, tmp_path, avisos, estado_en_tmp):
        hoy = date(2026, 9, 28)
        dc.pausar_por_tablero_viejo(
            dc.Bitacora(tmp_path / "b.log"), object(), hoy, SALIDA_CERROJO_VIEJO,
            avisar=True,
        )
        import json

        datos = json.loads((estado_en_tmp / "estado_20260928.json").read_text("utf-8"))
        assert datos["estado"] == "PAUSADO_BI_VIEJO"
        assert datos["paso_detenido"] == 1
        assert len(avisos) == 1
        assert avisos[0].titulo_para_calendar == "⚠️ Tablero Power BI no actualizado"
        assert "27/09/2026" in avisos[0].cuerpo

    def test_sin_avisar_registra_pero_no_avisa(self, tmp_path, avisos, estado_en_tmp):
        dc.pausar_por_tablero_viejo(
            dc.Bitacora(tmp_path / "b.log"), object(), date(2026, 9, 28), "",
            avisar=False,
        )
        assert avisos == []
        assert (estado_en_tmp / "estado_20260928.json").is_file()

    def test_si_el_estado_no_se_escribe_se_avisa_igual(
        self, tmp_path, monkeypatch, avisos
    ):
        def revienta(_dia):
            raise OSError("disco lleno")

        monkeypatch.setattr(dc.estado_dia, "registrar_pausa_bi_viejo", revienta)
        dc.pausar_por_tablero_viejo(
            dc.Bitacora(tmp_path / "b.log"), object(), date(2026, 9, 28), "",
            avisar=True,
        )
        assert len(avisos) == 1


class TestDiaConTableroViejo:
    """`main` de punta a punta, con las etapas simuladas."""

    @pytest.fixture
    def entorno(self, tmp_path, monkeypatch, avisos):
        env = tmp_path / ".env"
        env.write_text(ENV_EJEMPLO.replace("=false", "=true"), encoding="utf-8")
        py = tmp_path / "python.exe"
        py.write_text("", encoding="utf-8")

        monkeypatch.setattr(dc, "RUTA_ENV", env)
        monkeypatch.setattr(dc, "PY", py)
        monkeypatch.setattr(dc, "DIR_LOGS", tmp_path / "logs")
        monkeypatch.setattr(dc, "asegurar_directorios", lambda: None)
        monkeypatch.setattr(dc.estado_dia, "DIR_ESTADO", tmp_path / "estado")
        monkeypatch.setenv("MODO_SIMULACION", "true")

        class _Cfg:
            tiene_canal_de_aviso = True

        monkeypatch.setattr(dc.Config, "desde_entorno", classmethod(lambda cls: _Cfg()))

        lanzados = []

        def falso_correr(orden, bit):
            script = Path(str(orden[1])).name
            lanzados.append(script)
            if script == "verificar_actualizacion.py":
                return dc.CERROJO_DESACTUALIZADO, SALIDA_CERROJO_VIEJO
            return 0, ""

        monkeypatch.setattr(dc, "correr", falso_correr)
        return env, lanzados

    def test_para_limpio_sin_llegar_al_paso_2(self, entorno, avisos):
        env, lanzados = entorno
        assert dc.main(["--ejecutar-de-verdad"]) == 0
        assert lanzados == ["probar_perfil.py", "verificar_actualizacion.py"]
        assert len(avisos) == 1  # uno solo: ni el cerrojo ni el finally repiten

    def test_deja_el_estado_pausado(self, entorno, tmp_path):
        dc.main(["--ejecutar-de-verdad"])
        estados = list((tmp_path / "estado").glob("estado_*.json"))
        assert len(estados) == 1
        assert '"PAUSADO_BI_VIEJO"' in estados[0].read_text(encoding="utf-8")

    def test_el_cerrojo_de_escritura_vuelve_a_true(self, entorno):
        env, _ = entorno
        dc.main(["--ejecutar-de-verdad"])
        assert "MODO_SIMULACION=true" in env.read_text(encoding="utf-8")


class TestReintentoDeLas930:
    """`--solo-si-pausado`: la tarea de las 9:30 solo actua sobre una pausa."""

    @pytest.fixture
    def entorno(self, tmp_path, monkeypatch, avisos):
        env = tmp_path / ".env"
        env.write_text(ENV_EJEMPLO.replace("=false", "=true"), encoding="utf-8")
        py = tmp_path / "python.exe"
        py.write_text("", encoding="utf-8")
        monkeypatch.setattr(dc, "RUTA_ENV", env)
        monkeypatch.setattr(dc, "PY", py)
        monkeypatch.setattr(dc, "DIR_LOGS", tmp_path / "logs")
        monkeypatch.setattr(dc, "asegurar_directorios", lambda: None)
        monkeypatch.setattr(dc.estado_dia, "DIR_ESTADO", tmp_path / "estado")
        monkeypatch.setattr(dc.time, "sleep", lambda _s: None)
        monkeypatch.setattr(dc, "limpiar_chrome_colgado", lambda _b, _c: 0)
        monkeypatch.setattr(dc.resumen_dia, "calcular", lambda _hoy: None)
        monkeypatch.setattr(dc.resumen_dia, "formatear", lambda *_a: "resumen")
        monkeypatch.setenv("MODO_SIMULACION", "true")

        class _Cfg:
            tiene_canal_de_aviso = True
            exportacion_reintentos = 1
            exportacion_espera_seg = 0

        monkeypatch.setattr(dc.Config, "desde_entorno", classmethod(lambda cls: _Cfg()))

        lanzados = []
        codigo_cerrojo = {"valor": dc.CERROJO_DESACTUALIZADO}

        def falso_correr(orden, bit):
            script = Path(str(orden[1])).name
            lanzados.append(script)
            if script == "verificar_actualizacion.py":
                return codigo_cerrojo["valor"], SALIDA_CERROJO_VIEJO
            if script == "exportar_reporte.py":
                return 1, "ERROR: corte de la prueba"
            return 0, ""

        monkeypatch.setattr(dc, "correr", falso_correr)
        return env, lanzados, codigo_cerrojo

    ARGS = ["--ejecutar-de-verdad", "--solo-si-pausado"]

    def test_sin_estado_de_hoy_no_hace_nada(self, entorno, avisos):
        env, lanzados, _ = entorno
        antes = env.read_text(encoding="utf-8")
        assert dc.main(self.ARGS) == 0
        assert lanzados == []
        assert avisos == []
        assert env.read_text(encoding="utf-8") == antes  # ni toca el cerrojo

    @pytest.mark.parametrize("estado", ["EN_CURSO", "TERMINADO"])
    def test_con_el_dia_en_marcha_no_hace_nada(self, entorno, avisos, estado):
        """El caso que la guarda existe para evitar: las 9:00 salieron bien y a
        las 9:30 esa corrida esta en ISEF07."""
        _, lanzados, _ = entorno
        dc.estado_dia.registrar_avance(date.today(), estado)
        assert dc.main(self.ARGS) == 0
        assert lanzados == []
        assert avisos == []

    def test_sobre_una_pausa_vuelve_a_mirar_el_tablero(self, entorno, avisos):
        _, lanzados, _ = entorno
        dc.estado_dia.registrar_pausa_bi_viejo(date.today())
        assert dc.main(self.ARGS) == 0
        assert lanzados == ["probar_perfil.py", "verificar_actualizacion.py"]
        assert len(avisos) == 1  # sigue viejo: se avisa otra vez
        assert dc.estado_dia.esta_pausado_por_bi_viejo(date.today())

    def test_si_ya_esta_al_dia_sigue_y_deja_de_estar_pausado(self, entorno):
        """Pasado el paso 1 el estado es EN_CURSO: un tercer disparo ya no
        arrancaria nada."""
        _, lanzados, codigo_cerrojo = entorno
        dc.estado_dia.registrar_pausa_bi_viejo(date.today())
        codigo_cerrojo["valor"] = dc.CERROJO_OK
        dc.main(self.ARGS)  # la prueba corta en la exportacion
        assert "exportar_reporte.py" in lanzados
        assert dc.estado_dia.leer(date.today())["estado"] == "EN_CURSO"
