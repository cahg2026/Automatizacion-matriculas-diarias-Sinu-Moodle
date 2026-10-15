"""Diario de la etapa 4: un verde de ayer no vale para hoy."""

import json
from datetime import date

from moodle_sinu import diario_resultados as dr


def _escribir(ruta, apuntes):
    ruta.write_text(
        "".join(json.dumps(a, ensure_ascii=False) + "\n" for a in apuntes),
        encoding="utf-8",
    )


def _apunte(momento, veredicto="verde", cedula="111", objetivo="TI011/55526"):
    return {
        "momento": momento,
        "identificacion": cedula,
        "cod_periodo": "26V05",
        "objetivo": objetivo,
        "veredicto": veredicto,
    }


def test_sin_dia_cuenta_todo(tmp_path, monkeypatch):
    ruta = tmp_path / "resultados_etapa4.jsonl"
    monkeypatch.setattr(dr, "RUTA_RESULTADOS", ruta)
    _escribir(ruta, [_apunte("2026-10-05T10:00:00"), _apunte("2026-10-06T10:00:00", cedula="222")])

    assert len(dr.ultimo_por_unidad()) == 2


def test_con_dia_ignora_los_verdes_de_otro_dia(tmp_path, monkeypatch):
    """Si la rotacion fallo, el diario trae lo de ayer: no puede saltarse hoy."""
    ruta = tmp_path / "resultados_etapa4.jsonl"
    monkeypatch.setattr(dr, "RUTA_RESULTADOS", ruta)
    _escribir(ruta, [
        _apunte("2026-10-05T23:59:59", cedula="ayer"),
        _apunte("2026-10-06T00:00:01", cedula="hoy"),
    ])

    claves = dr.ultimo_por_unidad(date(2026, 10, 6))

    assert [c[1] for c in claves] == ["hoy"]


def test_con_dia_el_ultimo_de_hoy_manda(tmp_path, monkeypatch):
    ruta = tmp_path / "resultados_etapa4.jsonl"
    monkeypatch.setattr(dr, "RUTA_RESULTADOS", ruta)
    _escribir(ruta, [
        _apunte("2026-10-05T10:00:00", veredicto="verde"),
        _apunte("2026-10-06T09:00:00", veredicto="rojo"),
    ])

    (apunte,) = dr.ultimo_por_unidad(date(2026, 10, 6)).values()

    assert apunte["veredicto"] == "rojo"
