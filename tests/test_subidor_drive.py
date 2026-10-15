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


class PaginaQueTardaEnPintar:
    """Doble de Page cuyo listado aparece tras N lecturas.

    Reproduce lo que hace Drive de verdad: la rejilla existe y esta visible
    desde el primer instante, pero vacia, porque la aplicacion todavia no ha
    cambiado de carpeta.
    """

    def __init__(self, filas_finales: list[str], lecturas_en_blanco: int):
        self.filas_finales = filas_finales
        self.restantes = lecturas_en_blanco
        self.lecturas = 0
        self.esperas_ms = 0

    def wait_for_timeout(self, ms: float) -> None:
        self.esperas_ms += ms

    def leer(self) -> list[tuple[str, str]]:
        self.lecturas += 1
        if self.restantes > 0:
            self.restantes -= 1
            return []
        return [(n, f"<fila {n}>") for n in self.filas_finales]


class TestEsperarFilas:
    """El listado se lee cuando TIENE filas, no cuando existe la rejilla.

    El 14/09/2026 una sola lectura instantanea devolvio vacio, el flujo dedujo
    que 'SEPTIEMBRE' no existia y la creo en 'Mi unidad'. Y al volver a
    buscarla tampoco la encontro: acababa de crearla, asi que existia con
    certeza. Lo que fallaba era la lectura, no el Drive.
    """

    def test_reintenta_hasta_que_aparecen(self, monkeypatch):
        from moodle_sinu import subidor_drive as sd

        pagina = PaginaQueTardaEnPintar(["ABRIL", "SEPTIEMBRE"], lecturas_en_blanco=3)
        monkeypatch.setattr(sd, "_obtener_filas", lambda p: p.leer())
        filas = sd._esperar_filas(pagina, "la raiz")
        assert [n for n, _ in filas] == ["ABRIL", "SEPTIEMBRE"]
        assert pagina.lecturas == 4  # 3 en blanco y la buena

    def test_si_estan_a_la_primera_no_espera(self, monkeypatch):
        from moodle_sinu import subidor_drive as sd

        pagina = PaginaQueTardaEnPintar(["AGOSTO"], lecturas_en_blanco=0)
        monkeypatch.setattr(sd, "_obtener_filas", lambda p: p.leer())
        sd._esperar_filas(pagina, "la raiz")
        assert pagina.esperas_ms == 0

    def test_se_rinde_y_devuelve_vacio(self, monkeypatch):
        """Vacio significa "no vi ni una fila", no "la carpeta esta vacia".
        Quien decida algo peligroso con eso debe tratarlo como "no lo se"."""
        from moodle_sinu import subidor_drive as sd

        monkeypatch.setattr(sd, "SEG_ESPERA_FILAS", 0.05)
        monkeypatch.setattr(sd, "SEG_SONDEO_FILAS", 0.01)
        pagina = PaginaQueTardaEnPintar([], lecturas_en_blanco=10_000)
        monkeypatch.setattr(sd, "_obtener_filas", lambda p: p.leer())
        assert sd._esperar_filas(pagina, "la raiz") == []


class TestNoSeCreaACiegas:
    """La raiz NUNCA esta vacia: tiene una carpeta por mes.

    Asi que "cero filas en la raiz" no puede significar "esta vacia", solo
    puede significar "no cargo". Y con esa duda no se crea nada: crear es la
    accion que ensucia el Drive y que hay que limpiar a mano.
    """

    def test_el_mensaje_explica_por_que_no_se_crea(self):
        from moodle_sinu import subidor_drive as sd
        import inspect

        fuente = inspect.getsource(sd._entrar_en_carpeta_mes)
        assert "_esperar_filas" in fuente
        assert "if not filas:" in fuente
        # y que aborta en vez de crear
        i_guarda = fuente.index("if not filas:")
        i_crear = fuente.index("_crear_carpeta")
        assert i_guarda < i_crear, "la guarda debe ir ANTES de crear"

    def test_abrir_carpeta_espera_las_filas(self):
        from moodle_sinu import subidor_drive as sd
        import inspect

        fuente = inspect.getsource(sd._abrir_carpeta)
        assert "_esperar_filas" in fuente


class TestGuardaDeCoordinacion:
    """Un reporte del dia ya en Drive significa que alguien ya proceso.

    Es la unica guarda posible entre equipos: el diario que lleva la cuenta de
    lo hecho (`logs/resultados_etapa4.jsonl`) es LOCAL a cada maquina, asi que
    `--saltar-hechas` no sabe lo que hizo otra persona. Drive si es compartido.

    Y salta en la etapa 3, que va ANTES de la 4: se aborta sin haber tocado una
    sola matricula. El riesgo que evita no es el trabajo duplicado -- es que un
    equipo desvincule lo que el otro acaba de vincular, y que un fallo en esa
    ventana deje al estudiante desvinculado.
    """

    def _mensaje(self) -> str:
        from moodle_sinu import subidor_drive as sd
        import inspect

        return inspect.getsource(sd.subir_reporte)

    def test_aborta_si_ya_hay_reporte_del_dia(self):
        fuente = self._mensaje()
        assert "if del_dia and not reemplazar:" in fuente
        assert "ErrorSubidaDrive" in fuente

    def test_el_mensaje_dice_que_otro_pudo_procesar(self):
        """Sin esto se lee como un choque de nombres de archivo, y quien lo vea
        no entiende que es una senal de coordinacion."""
        fuente = self._mensaje()
        assert "YA SE EJECUTO" in fuente
        assert "otra persona" in fuente

    def test_el_mensaje_dice_que_no_se_toco_SINU(self):
        fuente = self._mensaje()
        assert "ANTES de tocar ninguna matricula" in fuente

    def test_el_mensaje_ofrece_las_tres_salidas(self):
        """No basta con abortar: hay que decir que hacer en cada caso.

        Se normalizan los espacios porque el mensaje se parte en varias lineas
        de codigo y una asercion literal se rompe al reajustar el texto.
        """
        fuente = " ".join(self._mensaje().split())
        # Cada marca se comprueba suelta: el mensaje se parte en varias lineas
        # de codigo y una frase entera cruzaria el corte entre literales.
        assert "otra persona ya proceso hoy" in fuente   # no hay nada que hacer
        assert "--reemplazar" in fuente                  # reprocesar a proposito
        assert "probar sin escribir" in fuente           # la via segura
        assert "--ejecutar-de-verdad" in fuente

    def test_reemplazar_aparta_y_no_borra(self):
        """Apartar y no borrar: el archivo lleva datos de matricula y su enlace
        puede estar abierto en la pestana de alguien."""
        fuente = self._mensaje()
        assert "if del_dia and reemplazar:" in fuente


class PaginaConTeclado:
    """Doble de Page para la ventana de gracia: teclado y esperas contadas."""

    def __init__(self):
        self.teclas: list[str] = []
        self.esperas_ms = 0.0
        self.keyboard = self

    def press(self, tecla: str) -> None:
        self.teclas.append(tecla)

    def wait_for_timeout(self, ms: float) -> None:
        self.esperas_ms += ms


class TestVentanaDeGracia:
    """Un corte breve de red no puede tirar la corrida entera.

    El 17/09/2026 el DNS dejo de resolver unos 15 s justo despues de pulsar
    'Cambiar nombre'. El dialogo carga su JavaScript bajo demanda, el chunk no
    llego y el dialogo nunca aparecio. El renombrado es el ULTIMO gesto de la
    etapa 3, asi que se perdieron tambien las etapas 4 a 6: cero matriculas
    procesadas por un corte que ya se habia resuelto solo.
    """

    @pytest.fixture
    def sd(self, monkeypatch):
        from moodle_sinu import subidor_drive as sd

        monkeypatch.setattr(sd, "SEG_GRACIA_RED", 5.0)
        monkeypatch.setattr(sd, "SEG_SONDEO_RED", 0.0)
        monkeypatch.setattr(sd, "_abrir_carpeta", lambda *a, **k: None)
        monkeypatch.setattr(sd, "_buscar_fila", lambda p, n: None)
        return sd

    def test_reintenta_y_lo_consigue(self, sd, monkeypatch):
        llamadas = []

        def renombrar(page, cfg, actual, definitivo):
            llamadas.append(definitivo)
            if len(llamadas) == 1:
                raise sd.ErrorSubidaDrive("No se encontro el campo de nombre")

        monkeypatch.setattr(sd, "_renombrar", renombrar)
        sd._renombrar_con_gracia(PaginaConTeclado(), None, "prov", "def", "ID")
        assert len(llamadas) == 2

    def test_cierra_el_menu_antes_de_reintentar(self, sd, monkeypatch):
        """Un menu a medio abrir se come el clic derecho del intento siguiente."""
        llamadas = []

        def renombrar(page, cfg, actual, definitivo):
            llamadas.append(definitivo)
            if len(llamadas) == 1:
                raise sd.ErrorSubidaDrive("dialogo que no aparece")

        monkeypatch.setattr(sd, "_renombrar", renombrar)
        pagina = PaginaConTeclado()
        sd._renombrar_con_gracia(pagina, None, "prov", "def", "ID")
        assert pagina.teclas == ["Escape"]

    def test_si_el_nombre_ya_esta_no_reintenta(self, sd, monkeypatch):
        """El fallo pudo ser solo de la comprobacion final.

        Si el dialogo se confirmo y lo que fallo fue refrescar la lista, el
        reintento buscaria el nombre PROVISIONAL, que ya no existe, y abortaria
        por una razon inventada.
        """
        llamadas = []

        def renombrar(page, cfg, actual, definitivo):
            llamadas.append(definitivo)
            raise sd.ErrorSubidaDrive("no aparecio en la lista")

        monkeypatch.setattr(sd, "_renombrar", renombrar)
        monkeypatch.setattr(sd, "_buscar_fila", lambda p, n: object())
        sd._renombrar_con_gracia(PaginaConTeclado(), None, "prov", "def", "ID")
        assert len(llamadas) == 1

    def test_se_rinde_al_agotar_la_gracia(self, sd, monkeypatch):
        monkeypatch.setattr(sd, "SEG_GRACIA_RED", 0.0)
        monkeypatch.setattr(
            sd,
            "_renombrar",
            lambda *a: (_ for _ in ()).throw(sd.ErrorSubidaDrive("sigue sin red")),
        )
        with pytest.raises(sd.ErrorSubidaDrive) as exc:
            sd._renombrar_con_gracia(PaginaConTeclado(), None, "prov", "def", "ID")
        mensaje = str(exc.value)
        # El ultimo fallo real viaja en el mensaje: "se agoto la gracia" a secas
        # no distingue un corte de red de un selector que cambio.
        assert "sigue sin red" in mensaje
        assert "ventana de gracia" in mensaje

    def test_espera_a_que_drive_responda(self, monkeypatch):
        """Se sondea, no se reintenta el gesto a ciegas: cada intento fallido
        del renombrado cuesta ~60 s de plazos agotados."""
        from moodle_sinu import subidor_drive as sd

        monkeypatch.setattr(sd, "SEG_SONDEO_RED", 0.0)
        aperturas = []

        def abrir(page, id_carpeta, cfg, descripcion):
            aperturas.append(id_carpeta)
            if len(aperturas) < 3:
                raise sd.ErrorSubidaDrive("ERR_NAME_NOT_RESOLVED")

        monkeypatch.setattr(sd, "_abrir_carpeta", abrir)
        import time as _t

        assert sd._esperar_a_drive(
            PaginaConTeclado(), None, "ID", _t.monotonic() + 5.0
        )
        assert len(aperturas) == 3

    def test_el_sondeo_se_rinde_al_agotarse_la_ventana(self, monkeypatch):
        from moodle_sinu import subidor_drive as sd

        monkeypatch.setattr(sd, "SEG_SONDEO_RED", 0.0)
        monkeypatch.setattr(
            sd,
            "_abrir_carpeta",
            lambda *a: (_ for _ in ()).throw(sd.ErrorSubidaDrive("sin red")),
        )
        import time as _t

        assert not sd._esperar_a_drive(PaginaConTeclado(), None, "ID", _t.monotonic())

    def test_la_subida_usa_la_version_con_gracia(self):
        """Regresion: si alguien vuelve a llamar a `_renombrar` pelado aqui, el
        corte de red vuelve a costar la corrida entera."""
        from moodle_sinu import subidor_drive as sd
        import inspect

        fuente = inspect.getsource(sd.subir_reporte)
        assert "_renombrar_con_gracia" in fuente
        assert "\n                _renombrar(" not in fuente

    def test_son_tres_minutos(self):
        """La cifra la fijo quien opera el flujo."""
        from moodle_sinu import subidor_drive as sd

        assert sd.SEG_GRACIA_RED == 180.0
