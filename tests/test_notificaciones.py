"""Los avisos del flujo desatendido."""

from __future__ import annotations

import smtplib
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from moodle_sinu import notificaciones as n  # noqa: E402
from moodle_sinu.config import Config  # noqa: E402

HOY = date(2026, 9, 8)


def _cfg(**kw) -> Config:
    """Config para pruebas, con Calendar APAGADO salvo que se pida.

    Calendar viene activo por defecto en produccion (es el unico canal que no
    pide credenciales), pero en una prueba abriria un navegador de verdad. Aqui
    se apaga y se enciende solo donde se este comprobando ese canal.
    """
    kw.setdefault("notificar_calendar", False)
    return Config(**kw)


@pytest.fixture(autouse=True)
def _avisos_en_tmp(tmp_path, monkeypatch):
    """El respaldo no escribe en logs/ del proyecto durante las pruebas."""
    monkeypatch.setattr(n, "DIR_AVISOS", tmp_path / "avisos")


class TestRedaccion:
    def test_alerta_lleva_asunto_y_fecha_pedidos(self):
        a = n.aviso_tablero_desactualizado("tablero de ayer", hoy=HOY)
        assert a.asunto == "⚠️ ALERTA: Tablero Power BI sin actualizar - 08/09/2026"
        assert "se ha pausado para gestión con el departamento" in a.cuerpo
        assert a.critico

    def test_el_texto_critico_va_literal_y_primero(self):
        """El dueno del proceso lo especifico palabra por palabra, y va en la
        primera linea: es lo que se ve en la vista previa de Teams o del
        correo, que es donde se decide si alguien abre el aviso."""
        a = n.aviso_tablero_desactualizado("tablero de ayer", hoy=HOY)
        assert a.cuerpo.startswith(
            "CRÍTICO: El tablero no se ha actualizado el día de hoy. La fecha "
            "de última actualización detectada en el reporte es anterior a la "
            "fecha actual."
        )

    def test_exito_lleva_asunto_y_metricas(self):
        a = n.aviso_exito("54/54 unidades, 39 verdes", hoy=HOY)
        assert a.asunto == "✅ ÉXITO: Flujo de procesamiento finalizado - 08/09/2026"
        assert "se completó correctamente" in a.cuerpo
        assert "54/54 unidades, 39 verdes" in a.cuerpo
        assert not a.critico

    def test_no_poder_leer_no_es_lo_mismo_que_estar_viejo(self):
        """Son dos alertas distintas porque la accion del operador difiere."""
        viejo = n.aviso_tablero_desactualizado("x", hoy=HOY)
        ilegible = n.aviso_no_se_pudo_leer("x", hoy=HOY)
        assert viejo.asunto != ilegible.asunto
        assert "sondear_actualizacion" in ilegible.cuerpo

    def test_hay_aviso_de_fallo(self):
        a = n.aviso_fallo("2 periodos fallaron", hoy=HOY)
        assert a.critico
        assert "2 periodos fallaron" in a.cuerpo


class TestEnvio:
    def test_sin_canal_lo_dice_y_no_finge(self):
        """Lo importante: enviado=False. Callarse pareceria que se aviso."""
        r = n.enviar(n.aviso_exito("x", hoy=HOY), _cfg())
        assert not r.enviado
        assert any("no hay canal configurado" in f for f in r.fallos)

    def test_siempre_deja_copia_en_disco(self):
        r = n.enviar(n.aviso_exito("resumen del dia", hoy=HOY), _cfg())
        assert r.respaldo is not None and r.respaldo.is_file()
        texto = r.respaldo.read_text(encoding="utf-8")
        assert "resumen del dia" in texto
        assert "sin canal" in texto or "no hay canal" in texto

    def test_el_webhook_recibe_asunto_y_cuerpo(self, monkeypatch):
        visto = {}

        def falso(url, aviso):
            visto["url"] = url
            visto["asunto"] = aviso.asunto

        monkeypatch.setattr(n, "_enviar_webhook", falso)
        r = n.enviar(
            n.aviso_exito("x", hoy=HOY), _cfg(notificar_webhook="https://x/y")
        )
        assert r.enviado and r.canales == ["webhook"]
        assert visto["url"] == "https://x/y"
        assert "ÉXITO" in visto["asunto"]

    def test_un_canal_caido_no_tumba_el_flujo(self, monkeypatch):
        """Un aviso que revienta se llevaria por delante justo el flujo al que
        intenta avisar. Tiene que devolver el fallo, no lanzarlo."""

        def revienta(url, aviso):
            raise OSError("la red no responde")

        monkeypatch.setattr(n, "_enviar_webhook", revienta)
        r = n.enviar(
            n.aviso_tablero_desactualizado("x", hoy=HOY),
            _cfg(notificar_webhook="https://x/y"),
        )
        assert not r.enviado
        assert any("la red no responde" in f for f in r.fallos)
        assert r.respaldo is not None and r.respaldo.is_file()

    def test_smtp_sin_destinatarios_no_se_intenta(self, monkeypatch):
        """Servidor sin destinatarios no manda nada: seria un envio a nadie."""
        llamado = []
        monkeypatch.setattr(n, "_enviar_smtp", lambda c, a: llamado.append(1))
        r = n.enviar(
            n.aviso_exito("x", hoy=HOY), _cfg(notificar_smtp_servidor="smtp.x")
        )
        assert llamado == []
        assert not r.enviado

    def test_smtp_con_destinatarios_si_se_intenta(self, monkeypatch):
        monkeypatch.setattr(n, "_enviar_smtp", lambda c, a: None)
        r = n.enviar(
            n.aviso_exito("x", hoy=HOY),
            _cfg(
                notificar_smtp_servidor="smtp.x",
                notificar_destinatarios=("a@b.c",),
            ),
        )
        assert r.enviado and r.canales == ["smtp"]

    def test_un_fallo_de_smtp_queda_anotado(self, monkeypatch):
        def revienta(cfg, aviso):
            raise smtplib.SMTPAuthenticationError(535, b"credenciales")

        monkeypatch.setattr(n, "_enviar_smtp", revienta)
        r = n.enviar(
            n.aviso_exito("x", hoy=HOY),
            _cfg(
                notificar_smtp_servidor="smtp.x",
                notificar_destinatarios=("a@b.c",),
            ),
        )
        assert not r.enviado
        assert any("smtp" in f for f in r.fallos)

    def test_los_dos_canales_a_la_vez(self, monkeypatch):
        monkeypatch.setattr(n, "_enviar_webhook", lambda u, a: None)
        monkeypatch.setattr(n, "_enviar_smtp", lambda c, a: None)
        r = n.enviar(
            n.aviso_exito("x", hoy=HOY),
            _cfg(
                notificar_webhook="https://x/y",
                notificar_smtp_servidor="smtp.x",
                notificar_destinatarios=("a@b.c",),
            ),
        )
        assert r.enviado and set(r.canales) == {"webhook", "smtp"}


class TestCalendar:
    """El canal de Calendar: un evento puntual, en el instante del aviso."""

    def test_los_titulos_son_los_pedidos(self):
        alerta = n.aviso_tablero_desactualizado("x", hoy=HOY)
        exito = n.aviso_exito("x", hoy=HOY)
        assert alerta.titulo_para_calendar == "⚠️ ALERTA: Tablero Power BI sin actualizar"
        assert exito.titulo_para_calendar == "✅ ÉXITO: Flujo Moodle vs SINU completado"

    def test_el_titulo_de_calendar_no_lleva_fecha(self):
        """El evento ya esta fechado por si mismo; en la notificacion del movil
        el titulo se corta y la fecha gastaria el ancho util."""
        exito = n.aviso_exito("x", hoy=HOY)
        assert "08/09/2026" in exito.asunto
        assert "08/09/2026" not in exito.titulo_para_calendar

    def test_sin_titulo_propio_se_usa_el_asunto(self):
        a = n.aviso_no_se_pudo_leer("x", hoy=HOY)
        assert a.titulo_para_calendar == a.asunto

    def test_se_llama_a_calendar_con_titulo_y_cuerpo(self, monkeypatch):
        visto = {}

        def falso(titulo, detalles, cfg, **kw):
            visto["titulo"] = titulo
            visto["detalles"] = detalles
            from moodle_sinu.aviso_calendar import ResultadoCalendar

            return ResultadoCalendar(creado=True, detalle="ok")

        import moodle_sinu.aviso_calendar as ac

        monkeypatch.setattr(ac, "crear_evento", falso)
        r = n.enviar(
            n.aviso_exito("54/54 unidades", hoy=HOY),
            Config(notificar_calendar=True),
        )
        assert r.enviado and r.canales == ["calendar"]
        assert visto["titulo"] == "✅ ÉXITO: Flujo Moodle vs SINU completado"
        assert "54/54 unidades" in visto["detalles"]

    def test_si_calendar_falla_queda_anotado_y_no_lanza(self, monkeypatch):
        import moodle_sinu.aviso_calendar as ac
        from moodle_sinu.aviso_calendar import ResultadoCalendar

        monkeypatch.setattr(
            ac,
            "crear_evento",
            lambda *a, **k: ResultadoCalendar(detalle="no se encontro Guardar"),
        )
        r = n.enviar(
            n.aviso_exito("x", hoy=HOY), Config(notificar_calendar=True)
        )
        assert not r.enviado
        assert any("no se encontro Guardar" in f for f in r.fallos)
        assert r.respaldo is not None and r.respaldo.is_file()


class TestUrlDeCalendar:
    def test_lleva_titulo_detalles_y_zona(self):
        from datetime import datetime

        from moodle_sinu.aviso_calendar import construir_url

        u = construir_url(
            "⚠️ ALERTA: Tablero Power BI sin actualizar",
            "el tablero es del 05/09/2026",
            ahora=datetime(2026, 9, 8, 9, 0, 0),
        )
        assert u.startswith("https://calendar.google.com/calendar/render?")
        assert "action=TEMPLATE" in u
        assert "ctz=America%2FBogota" in u
        assert "ALERTA" in u

    def test_es_un_evento_puntual_no_recurrente(self):
        """El requisito: no llenar la agenda. Ni RRULE ni recurrencia."""
        from datetime import datetime

        from moodle_sinu.aviso_calendar import construir_url

        u = construir_url("x", "y", ahora=datetime(2026, 9, 8, 9, 0, 0))
        assert "RRULE" not in u.upper()
        assert "recur" not in u.lower()

    def test_se_adelanta_unos_minutos_para_que_el_aviso_salte(self):
        """Un recordatorio cuyo momento ya paso no se dispara. El adelanto es
        el margen minimo para que llegue a pantalla y movil."""
        from datetime import datetime

        from moodle_sinu.aviso_calendar import construir_url

        u = construir_url(
            "x", "y", ahora=datetime(2026, 9, 8, 9, 0, 0), minutos_por_delante=2
        )
        assert "dates=20260908T090200%2F20260908T091200" in u

    def test_los_invitados_van_en_add(self):
        """Es lo que hace que Google mande su propia invitacion por correo, sin
        que tengamos que montar un servidor."""
        from datetime import datetime

        from moodle_sinu.aviso_calendar import construir_url

        u = construir_url(
            "x", "y", invitados=("a@b.co", "c@d.co"),
            ahora=datetime(2026, 9, 8, 9, 0, 0),
        )
        assert "add=a%40b.co%2Cc%40d.co" in u

    def test_sin_invitados_no_aparece_add(self):
        from datetime import datetime

        from moodle_sinu.aviso_calendar import construir_url

        u = construir_url("x", "y", ahora=datetime(2026, 9, 8, 9, 0, 0))
        assert "add=" not in u


class TestCanalConfigurado:
    def test_calendar_solo_ya_es_canal(self):
        """Y por eso viene activo por defecto: no pide credenciales nuevas."""
        assert Config().tiene_canal_de_aviso
        assert Config().notificar_calendar

    def test_sin_nada_no_hay_canal(self):
        assert not _cfg().tiene_canal_de_aviso

    def test_el_webhook_basta(self):
        assert _cfg(notificar_webhook="https://x").tiene_canal_de_aviso

    def test_smtp_necesita_destinatarios(self):
        assert not _cfg(notificar_smtp_servidor="smtp.x").tiene_canal_de_aviso
        assert _cfg(
            notificar_smtp_servidor="smtp.x", notificar_destinatarios=("a@b.c",)
        ).tiene_canal_de_aviso


class TestListaDeDestinatarios:
    def test_admite_coma_y_punto_y_coma(self, monkeypatch):
        """Los correos se copian de Outlook, que separa con punto y coma."""
        from moodle_sinu.config import _lista

        monkeypatch.setenv("X", "a@b.c; d@e.f , g@h.i")
        assert _lista("X") == ("a@b.c", "d@e.f", "g@h.i")

    def test_vacia_si_no_hay_nada(self, monkeypatch):
        from moodle_sinu.config import _lista

        monkeypatch.delenv("X", raising=False)
        assert _lista("X") == ()
