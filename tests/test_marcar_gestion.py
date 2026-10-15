"""La columna Q: que lee la persona que tiene que arreglar cada fila roja.

Hasta el 25/09/2026 todo lo que no fuera verde ponia 'REVISAR'. Eso no dice
DONDE revisar, y los motivos del diario llevan a sitios distintos: un grupo sin
curso en MOODLE hay que CREARLO, un check sin confirmar hay que VALIDARLO en
ISEF05/PACF50, y una materia que quedo desvinculada hay que vincularla a mano en
ISEF07 cuanto antes. Mandar los tres a 'REVISAR' obliga a abrir el .jsonl para
saber cual es cual, y el .jsonl no lo abre nadie.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

_spec = importlib.util.spec_from_file_location(
    "marcar_gestion_script", RAIZ / "scripts" / "marcar_gestion.py"
)
assert _spec and _spec.loader
marcar_gestion = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(marcar_gestion)

from moodle_sinu import diario_resultados as diario  # noqa: E402
from moodle_sinu.constantes import Validacion  # noqa: E402

etiqueta_de = marcar_gestion.etiqueta_de


def test_el_verde_manda_sobre_el_motivo():
    assert etiqueta_de(diario.MOTIVO_OK, es_verde=True) == "VINCULADA Y VALIDADA"


def test_el_cortocircuito_dice_a_donde_ir():
    """El texto exacto que pide la regla del 25/09/2026."""
    etiqueta = etiqueta_de(
        diario.MOTIVO_ESCALADO_VALIDACION_MANUAL, es_verde=False
    )
    assert etiqueta == Validacion.ESCALADO_VALIDACION_MANUAL.value
    assert "ISEF05" in etiqueta and "PACF50" in etiqueta


def test_el_check_sin_confirmar_va_al_mismo_sitio():
    """Distinto motivo, mismo destino: los dos se validan a mano.

    Se distinguen en el motivo, que va detras en la misma celda, porque a uno
    se le ejecuto el vincular y al otro no se le toco.
    """
    assert etiqueta_de(diario.MOTIVO_CHECK_NO_CONFIRMADO, es_verde=False) == (
        Validacion.ESCALADO_VALIDACION_MANUAL.value
    )


def test_sin_curso_no_manda_a_validar():
    """Validar en ISEF05 un grupo que ISEF05 ya contesto es perder el viaje."""
    etiqueta = etiqueta_de(diario.MOTIVO_SIN_CURSO_MOODLE, es_verde=False)
    assert etiqueta == "SIN CHECK DE MOODLE"
    assert "ISEF05" not in etiqueta


def test_sin_check_y_grupo_inexistente_van_sin_sufijo():
    """Regla del 07/10/2026: solo la etiqueta, sin motivo ni fecha detras."""
    texto_celda = marcar_gestion.texto_celda
    for motivo, esperado in (
        (diario.MOTIVO_SIN_CURSO_MOODLE, "SIN CHECK DE MOODLE"),
        (diario.MOTIVO_GRUPO_NO_EXISTE, "GRUPO NO EXISTE EN SINU"),
    ):
        apunte = {"motivo": motivo, "momento": "2026-10-07T09:14:00"}
        assert texto_celda(apunte, es_verde=False) == esperado


def test_los_demas_conservan_motivo_y_fecha():
    apunte = {"motivo": diario.MOTIVO_OK, "momento": "2026-10-07T09:04:08"}
    assert marcar_gestion.texto_celda(apunte, es_verde=True) == (
        "VINCULADA Y VALIDADA - vinculada-y-confirmada (2026-10-07T09:04)"
    )


def test_la_desvinculada_pide_ir_a_isef07():
    """Es la unica que deja al estudiante PEOR que antes: no se valida, se repara."""
    etiqueta = etiqueta_de(diario.MOTIVO_CICLO_ABIERTO, es_verde=False)
    assert "ISEF07" in etiqueta and "A MANO" in etiqueta


def test_un_motivo_desconocido_sigue_cayendo_en_revisar():
    """Un motivo nuevo no puede dejar la celda vacia ni reventar el paso 5."""
    assert etiqueta_de("motivo-que-no-existe-aun", es_verde=False) == "REVISAR"
    assert etiqueta_de("", es_verde=False) == "REVISAR"


# ---------------------------------------------------------------------------
# Grupo que no existe en SINU: FUCSIA (28/09/2026)
# ---------------------------------------------------------------------------


def test_el_grupo_inexistente_lleva_su_etiqueta():
    assert etiqueta_de(diario.MOTIVO_GRUPO_NO_EXISTE, es_verde=False) == (
        "GRUPO NO EXISTE EN SINU"
    )


def test_el_grupo_inexistente_va_en_fucsia():
    from moodle_sinu.constantes import Color

    color = marcar_gestion.color_de(diario.MOTIVO_GRUPO_NO_EXISTE, es_verde=False)
    assert color is Color.FUCSIA


def test_los_demas_rojos_siguen_en_rojo_y_el_verde_en_verde():
    rojo = marcar_gestion.color_de(diario.MOTIVO_SIN_CURSO_MOODLE, es_verde=False)
    assert rojo is marcar_gestion.ROJO
    assert marcar_gestion.color_de(diario.MOTIVO_OK, es_verde=True) is marcar_gestion.VERDE
