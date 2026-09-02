"""Tests de la etapa 2 sin red, centrados en la deteccion de sesion.

Esta cobertura faltaba, y su ausencia permitio que la deteccion del 404
desapareciera del codigo sin que ningun test lo notara.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from moodle_sinu import selectores_drive as sel  # noqa: E402
from moodle_sinu.subidor_drive import (  # noqa: E402
    ErrorSubidaDrive,
    _exigir_dentro_de,
    _rejilla,
    _verificar_sesion,
    es_pagina_de_error,
    es_selector_de_cuenta,
    id_de_url,
)


class PaginaFalsa:
    """Doble minimo de Page: solo url y title, que es lo que se inspecciona."""

    def __init__(self, url: str, titulo: str = ""):
        self.url = url
        self._titulo = titulo

    def title(self) -> str:
        return self._titulo


ID = "1P4tdPPMcTdZofHtGysBOiUz-akbQZ98Q"
URL_OK = f"https://drive.google.com/drive/folders/{ID}"


class TestPaginaDeError:
    """La funcion pura que reconoce una pagina de error de Drive."""

    def test_reconoce_el_404_real(self):
        # Titulo exacto observado el 21/08/2026 con un perfil sin sesion.
        assert es_pagina_de_error("Error 404 (No se ha encontrado.)!!1")

    @pytest.mark.parametrize(
        "titulo",
        ["Error 404", "404. That's an error.", "error", "ERROR 500", "  Error  "],
    )
    def test_reconoce_variantes(self, titulo):
        assert es_pagina_de_error(titulo)

    @pytest.mark.parametrize(
        "titulo",
        [
            "REPORTES 2026 - Google Drive",
            "AGOSTO - Google Drive",
            "Mi unidad - Google Drive",
            "",
        ],
    )
    def test_no_confunde_una_pagina_normal(self, titulo):
        assert not es_pagina_de_error(titulo)

    def test_un_archivo_llamado_error_no_es_una_pagina_de_error(self):
        # 'startswith' y no 'in': un nombre de carpeta con la palabra dentro no
        # debe disparar la deteccion.
        assert not es_pagina_de_error("Informe de errores - Google Drive")


class TestVerificarSesion:
    def test_una_carpeta_normal_pasa(self):
        _verificar_sesion(PaginaFalsa(URL_OK, "REPORTES 2026 - Google Drive"), ID)

    def test_el_404_se_detecta_y_explica_las_dos_causas(self):
        # El caso real: Drive NO redirige al login, devuelve 404.
        pagina = PaginaFalsa(URL_OK, "Error 404 (No se ha encontrado.)!!1")
        with pytest.raises(ErrorSubidaDrive) as exc:
            _verificar_sesion(pagina, ID)
        mensaje = str(exc.value)
        assert "404" in mensaje
        assert "sesion de Google" in mensaje  # causa 1
        assert "GOOGLE_CARPETA_RAIZ_ID" in mensaje  # causa 2

    def test_el_mensaje_nombra_la_carpeta(self):
        with pytest.raises(ErrorSubidaDrive, match=ID):
            _verificar_sesion(PaginaFalsa(URL_OK, "Error 404"), ID)

    def test_la_redireccion_al_login_tambien_se_detecta(self):
        pagina = PaginaFalsa("https://accounts.google.com/signin/v2", "Iniciar sesion")
        with pytest.raises(ErrorSubidaDrive, match="login"):
            _verificar_sesion(pagina, ID)

    def test_signin_en_la_ruta_se_detecta(self):
        pagina = PaginaFalsa("https://drive.google.com/signin?x=1", "Drive")
        with pytest.raises(ErrorSubidaDrive):
            _verificar_sesion(pagina, ID)

    def test_no_se_confia_solo_en_la_url(self):
        # Regresion de la version que perdio la deteccion: comprobar solo la URL
        # deja pasar el 404, porque la URL de la carpeta no cambia.
        pagina = PaginaFalsa(URL_OK, "Error 404 (No se ha encontrado.)!!1")
        assert "accounts.google.com" not in pagina.url
        assert "/signin" not in pagina.url
        with pytest.raises(ErrorSubidaDrive):
            _verificar_sesion(pagina, ID)


class TestSelectorDeCuenta:
    """El selector de cuenta NO es falta de sesion, y el remedio es otro.

    Comprobado el 01/09/2026: con las cookies de autenticacion presentes y
    validas, Drive se quedaba en `accountchooser` sin moverse. Confundirlo con
    "no hay sesion" manda a iniciar sesion otra vez, que no arregla nada.
    """

    URL_CHOOSER = (
        "https://accounts.google.com/v3/signin/accountchooser"
        "?continue=https://drive.google.com/drive/folders/" + ID
    )

    def test_se_reconoce_el_selector_de_cuenta(self):
        assert es_selector_de_cuenta(self.URL_CHOOSER)

    def test_una_url_de_drive_no_es_el_selector(self):
        assert not es_selector_de_cuenta(URL_OK)

    def test_un_login_normal_no_es_el_selector(self):
        assert not es_selector_de_cuenta(
            "https://accounts.google.com/signin/v2/identifier"
        )

    def test_el_mensaje_explica_que_la_sesion_puede_estar_bien(self):
        pagina = PaginaFalsa(self.URL_CHOOSER, "Google Drive: Acceso")
        with pytest.raises(ErrorSubidaDrive) as exc:
            _verificar_sesion(pagina, ID)
        mensaje = str(exc.value)
        assert "SELECTOR DE CUENTA" in mensaje
        assert "NO significa que falte la sesion" in mensaje
        # Y tiene que dar el remedio concreto, no solo el diagnostico.
        assert "probar_perfil.py" in mensaje

    def test_el_selector_gana_al_chequeo_generico_de_login(self):
        """Su URL contiene 'accounts.google.com', asi que el orden importa: el
        chequeo generico daria el mensaje equivocado."""
        pagina = PaginaFalsa(self.URL_CHOOSER, "Google Drive: Acceso")
        with pytest.raises(ErrorSubidaDrive) as exc:
            _verificar_sesion(pagina, ID)
        assert "no tiene sesion de Google" not in str(exc.value)


class TestListaEnCarpetaVacia:
    """Drive cambia el ROL del contenedor segun si la carpeta tiene contenido.

    Comprobado el 01/09/2026 en la misma corrida y con la misma sesion:

        carpeta con 7 subcarpetas  -> grid: 1, table: 0
        carpeta VACIA (SEPTIEMBRE) -> grid: 0, table: 1

    Exigir solo 'grid' hacia que la etapa 2 agotase los 120 s y abortara en
    cuanto la carpeta del mes estuviera vacia. Es decir, **el dia 1 de cada
    mes**: justo cuando hay que crearla y subir el primer reporte. El fallo se
    presentaba como "el selector cambio", que manda a depurar donde no esta.
    """

    def test_se_contemplan_los_dos_roles(self):
        assert "grid" in sel.ROLES_REJILLA
        assert "table" in sel.ROLES_REJILLA

    def test_grid_va_primero(self):
        """Es el caso normal: una carpeta con reportes dentro."""
        assert sel.ROLES_REJILLA[0] == "grid"

    def test_el_rol_antiguo_sigue_siendo_el_preferido(self):
        """ROL_REJILLA se conserva por compatibilidad y debe coincidir."""
        assert sel.ROL_REJILLA == sel.ROLES_REJILLA[0]


class LocalizadorFalso:
    """Doble de Locator: solo `count()` y `first`, que es lo que desempata."""

    def __init__(self, rol: str, cuantos: int):
        self.rol = rol
        self._cuantos = cuantos
        self.first = f"<{rol}>"

    def count(self) -> int:
        return self._cuantos


class PaginaConRoles:
    """Doble de Page que declara cuantos elementos hay de cada rol."""

    def __init__(self, **cuentas: int):
        self.cuentas = cuentas

    def get_by_role(self, rol: str) -> LocalizadorFalso:
        return LocalizadorFalso(rol, self.cuentas.get(rol, 0))


class TestDesempateDeRejilla:
    """`grid` y `table` NO son excluyentes, y elegir mal rompe la busqueda.

    Comprobado el 01/09/2026 contra el Drive real:

        carpeta raiz     -> grid: 1, table: 1   (el 'table' NO es la lista)
        carpeta vacia    -> grid: 0, table: 1

    Un `or_(...).first` resolvia al 'table' equivocado en la raiz:
    `_buscar_fila` no encontraba 'SEPTIEMBRE' aunque estaba delante, y el flujo
    intentaba crear una carpeta duplicada en el Drive del usuario.
    """

    def test_con_los_dos_roles_presentes_gana_grid(self):
        pagina = PaginaConRoles(grid=1, table=1)
        assert _rejilla(pagina) == "<grid>"

    def test_sin_grid_se_cae_a_table(self):
        """Es la carpeta del mes recien creada: vacia, sin 'grid'."""
        pagina = PaginaConRoles(grid=0, table=1)
        assert _rejilla(pagina) == "<table>"

    def test_sin_ninguno_se_devuelve_el_preferido(self):
        """Para que el mensaje de error hable del rol normal, no del respaldo."""
        pagina = PaginaConRoles()
        assert _rejilla(pagina) == "<grid>"


class TestGuardaDeCarpetaDestino:
    """Toda accion que MODIFIQUE Drive verifica primero donde esta.

    Su ausencia costo tres incidentes reales el 01/09/2026 sobre el Drive del
    usuario: una carpeta 'SEPTIEMBRE' creada en 'Mi unidad', un reporte subido
    fuera de la carpeta del mes, y una subida a medias dada por buena. Que un
    fallo deje el Drive intacto es el requisito; limpiar a mano lo que la
    automatizacion desparrama cuesta mas que la corrida.
    """

    def test_se_extrae_el_id_de_la_url(self):
        assert id_de_url(f"https://drive.google.com/drive/folders/{ID}") == ID

    def test_se_extrae_el_id_aunque_haya_indice_de_cuenta(self):
        assert id_de_url(f"https://drive.google.com/drive/u/0/folders/{ID}") == ID

    def test_mi_unidad_no_tiene_id_de_carpeta(self):
        """Es exactamente la vista donde acabaron los archivos sueltos."""
        assert id_de_url("https://drive.google.com/drive/my-drive") is None

    def test_dentro_de_la_carpeta_correcta_deja_pasar(self):
        pagina = PaginaFalsa(f"https://drive.google.com/drive/folders/{ID}", "x")
        _exigir_dentro_de(pagina, ID, "subir el archivo")  # no levanta

    def test_en_mi_unidad_se_aborta_antes_de_tocar_nada(self):
        pagina = PaginaFalsa("https://drive.google.com/drive/my-drive", "Mi unidad")
        with pytest.raises(ErrorSubidaDrive) as exc:
            _exigir_dentro_de(pagina, ID, "subir el archivo")
        mensaje = str(exc.value)
        assert "Mi unidad" in mensaje
        assert "ANTES de tocar nada" in mensaje

    def test_en_otra_carpeta_se_aborta_y_se_nombran_las_dos(self):
        otra = "OTRAxCARPETAxID"
        pagina = PaginaFalsa(f"https://drive.google.com/drive/folders/{otra}", "x")
        with pytest.raises(ErrorSubidaDrive) as exc:
            _exigir_dentro_de(pagina, ID, "crear la carpeta 'SEPTIEMBRE'")
        assert ID in str(exc.value)
        assert otra in str(exc.value)
