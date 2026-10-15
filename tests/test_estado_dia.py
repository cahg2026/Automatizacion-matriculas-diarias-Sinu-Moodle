"""El contrato de estado del dia (`logs/estado/estado_AAAAMMDD.json`)."""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from moodle_sinu import estado_dia  # noqa: E402

HOY = date(2026, 9, 28)
A_LAS_9 = datetime(2026, 9, 28, 9, 0, 17, tzinfo=timezone(timedelta(hours=-5)))


class TestPausaPorTableroViejo:
    def test_escribe_el_contrato_pedido(self, tmp_path):
        ruta = estado_dia.registrar_pausa_bi_viejo(HOY, carpeta=tmp_path, ahora=A_LAS_9)
        assert ruta == tmp_path / "estado_20260928.json"
        assert json.loads(ruta.read_text(encoding="utf-8")) == {
            "fase": "A",
            "estado": "PAUSADO_BI_VIEJO",
            "paso_detenido": 1,
            "motivo": "Tablero Power BI desactualizado",
            "timestamp": "2026-09-28T09:00:17-05:00",
        }

    def test_crea_la_carpeta(self, tmp_path):
        carpeta = tmp_path / "no" / "existe"
        estado_dia.registrar_pausa_bi_viejo(HOY, carpeta=carpeta)
        assert (carpeta / "estado_20260928.json").is_file()

    def test_no_deja_temporales(self, tmp_path):
        estado_dia.registrar_pausa_bi_viejo(HOY, carpeta=tmp_path)
        assert [p.name for p in tmp_path.iterdir()] == ["estado_20260928.json"]


class TestMezcla:
    def test_conserva_lo_que_otra_etapa_anoto(self, tmp_path):
        estado_dia.registrar(HOY, {"sheet_url": "https://x"}, carpeta=tmp_path)
        estado_dia.registrar_pausa_bi_viejo(HOY, carpeta=tmp_path)
        datos = estado_dia.leer(HOY, carpeta=tmp_path)
        assert datos["sheet_url"] == "https://x"
        assert datos["estado"] == "PAUSADO_BI_VIEJO"

    def test_un_json_roto_no_impide_escribir(self, tmp_path):
        (tmp_path / "estado_20260928.json").write_text("{a medias", encoding="utf-8")
        estado_dia.registrar_pausa_bi_viejo(HOY, carpeta=tmp_path)
        assert estado_dia.leer(HOY, carpeta=tmp_path)["fase"] == "A"

    def test_sin_archivo_se_lee_vacio(self, tmp_path):
        assert estado_dia.leer(HOY, carpeta=tmp_path) == {}
