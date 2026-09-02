"""Copia del perfil personal de Chrome a una carpeta que si se pueda automatizar.

Por que hace falta esto
-----------------------
El dueno del proceso pidio usar el perfil personal de Chrome, para tener
contrasenas, cookies y la barra de favoritos. Comprobado el 31/08/2026 con
Chrome 151, **Chrome se niega**:

    DevTools remote debugging requires a non-default data directory.
    Specify this using --user-data-dir.

Desde Chrome 136 el navegador bloquea la depuracion remota -- que es el canal
por el que lo manejan Playwright y Selenium -- cuando `--user-data-dir` apunta a
su directorio de datos por defecto. El navegador arranca, pero nunca deja
conectarse: la corrida muere por timeout a los 180 s.

El veto es al DIRECTORIO, no al contenido. Una copia del perfil en otra carpeta
si es automatizable, y lleva dentro exactamente lo que se buscaba.

Lo que ademas se gana
---------------------
1. **Las corridas ya no exigen Chrome cerrado.** Solo la siembra lo exige, para
   copiar archivos que Chrome mantiene bloqueados. Despues, el robot trabaja
   sobre su copia mientras el usuario navega tranquilamente.
2. **El perfil de diario deja de estar en riesgo.** La automatizacion no lo
   abre, asi que no puede degradarlo.

Lo que hay que tener en cuenta
------------------------------
La copia es una FOTO. Un favorito nuevo o una sesion renovada no aparecen solos:
hay que volver a sembrar. Es barato (`scripts/sembrar_perfil.py`) y no hace
falta a diario.

Las cookies van cifradas con una clave que vive en `Local State` y que Windows
protege por usuario (DPAPI), asi que se copia tambien. Aun asi, las versiones
recientes de Chrome anaden un cifrado ligado a la instalacion (App-Bound
Encryption) que puede invalidar parte de las cookies al moverlas. Por eso la
siembra no promete sesiones: `scripts/probar_perfil.py` cuenta cuantas
sobrevivieron, y las que falten se resuelven entrando una vez con `--visible`.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

#: Archivo de `User Data` (no del perfil) con la clave de cifrado de cookies.
#: Se copia SOLO si el destino no tiene uno: sobrescribirlo en un refresco
#: rotaria la clave y dejaria ilegibles las cookies que el perfil de trabajo ya
#: hubiera ganado por su cuenta.
ARCHIVO_ESTADO_GLOBAL = "Local State"

#: Archivos que NO se copian NUNCA, aunque existan en el origen.
#:
#: Son los que Chrome protege con App-Bound Encryption (127+): viajan byte a
#: byte pero llegan ilegibles, porque la clave esta ligada a la instalacion y
#: al directorio de origen. Comprobado el 31/08/2026: tras copiar 851.968 bytes
#: de cookies, el perfil abrio con CERO.
#:
#: No es solo que sean inutiles: copiarlos hace dano. Un refresco de la siembra
#: pisaria las cookies que el perfil de trabajo SI tiene -- las de la sesion que
#: se inicio a mano una vez -- y obligaria a volver a autenticarse. Que es justo
#: lo que la siembra existe para evitar.
ARCHIVOS_CIFRADOS_INUTILES: frozenset[str] = frozenset(
    {
        "Cookies",
        "Cookies-journal",
        "Login Data",
        "Login Data-journal",
        "Login Data For Account",
        "Login Data For Account-journal",
    }
)

#: Claves de `Preferences` / `Secure Preferences` con las firmas que Chrome usa
#: para detectar manipulaciones. La semilla incluye la RUTA del perfil, asi que
#: al mover la carpeta dejan de validar y Chrome **descarta los favoritos**:
#: escribe un `Bookmarks` vacio y deja el bueno en `Bookmarks.bak` (comprobado
#: el 31/08/2026: 46 favoritos -> 0).
#:
#: Quitandolas, Chrome no tiene contra que validar, acepta el contenido y lo
#: vuelve a firmar con la semilla del sitio nuevo.
CLAVES_DE_PROTECCION: tuple[str, ...] = ("protection", "super_mac")

#: Lo que se copia SIEMPRE. Es una lista blanca, no una exclusion: de todo el
#: perfil personal, lo unico que la automatizacion necesita de verdad son los
#: favoritos, que es de donde salen los accesos directos a SINU y al Sheet.
#:
#: La primera version copiaba el arbol entero menos las caches (1474 archivos,
#: 101,7 MB) y eso causo un fallo real el 01/09/2026: al refrescar la siembra,
#: el `Preferences` del perfil personal se copio encima del de trabajo. Ese
#: archivo lleva la IDENTIDAD de la cuenta con sesion, asi que quedo
#: descuadrado -- cookies de una cuenta, preferencias de otra -- y Google
#: planto a Drive en el selector de cuenta. Copiar poco no es solo mas rapido:
#: es lo que hace que refrescar sea seguro.
ARCHIVOS_SIEMPRE: tuple[str, ...] = (
    "Bookmarks",
    "Favicons",  # los iconos de la barra de favoritos
)

#: Lo que se copia SOLO si el destino no lo tiene: un perfil recien creado
#: agradece las preferencias del personal (idioma, zona horaria), pero
#: sobrescribirlas en un refresco pisa el estado de sesion. Ver arriba.
ARCHIVOS_SOLO_PRIMERA_VEZ: tuple[str, ...] = (
    "Preferences",
    "Secure Preferences",
)

#: Archivos donde viven las firmas a neutralizar.
ARCHIVOS_CON_PROTECCION: tuple[str, ...] = ("Secure Preferences", "Preferences")

#: La pieza sin la que la siembra no ha servido de nada. Solo es informativo:
#: sirve para avisar. Cookies y contrasenas NO estan aqui a proposito, porque no
#: pueden viajar: ver ARCHIVOS_CIFRADOS_INUTILES.
ARCHIVOS_CLAVE: tuple[str, ...] = ("Bookmarks",)


class ErrorSiembraPerfil(RuntimeError):
    """No se pudo sembrar el perfil. El mensaje dice que hacer."""


@dataclass
class ResultadoSiembra:
    """Que se copio y que falto."""

    destino: Path
    archivos: int = 0
    megabytes: float = 0.0
    omitidos_por_bloqueo: list[str] = None  # type: ignore[assignment]
    omitidos_por_cifrado: list[str] = None  # type: ignore[assignment]
    claves_ausentes: list[str] = None  # type: ignore[assignment]
    protecciones_retiradas: list[str] = None  # type: ignore[assignment]
    conservados: list[str] = None  # type: ignore[assignment]
    """Archivos que el destino ya tenia y NO se pisaron, para no romper su
    estado de sesion."""

    def __post_init__(self) -> None:
        if self.omitidos_por_bloqueo is None:
            self.omitidos_por_bloqueo = []
        if self.omitidos_por_cifrado is None:
            self.omitidos_por_cifrado = []
        if self.claves_ausentes is None:
            self.claves_ausentes = []
        if self.protecciones_retiradas is None:
            self.protecciones_retiradas = []
        if self.conservados is None:
            self.conservados = []


def _copiar_uno(
    origen: Path, destino: Path, resultado: ResultadoSiembra, *, solo_si_falta: bool
) -> None:
    """Copia un archivo de la lista blanca. Anota y sigue si no se puede.

    Un archivo bloqueado no aborta la siembra: Chrome deja candados sueltos y
    morir por uno de ellos seria peor que continuar con lo que si llego.
    """
    if not origen.is_file():
        log.debug("No existe en el origen: %s", origen.name)
        return
    if origen.name in ARCHIVOS_CIFRADOS_INUTILES:  # pragma: no cover - lista blanca
        resultado.omitidos_por_cifrado.append(origen.name)
        return
    if solo_si_falta and destino.is_file():
        log.info(
            "'%s' ya existe en el destino: se conserva, para no pisar el estado "
            "de sesion del perfil de trabajo.",
            origen.name,
        )
        resultado.conservados.append(origen.name)
        return

    destino.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(origen, destino)
    except OSError as exc:
        log.warning("No se pudo copiar '%s': %s", origen.name, exc)
        resultado.omitidos_por_bloqueo.append(origen.name)
        return
    resultado.archivos += 1
    try:
        resultado.megabytes += origen.stat().st_size / (1024 * 1024)
    except OSError:  # pragma: no cover - el archivo acaba de copiarse
        pass


def _retirar_protecciones(perfil: Path, resultado: ResultadoSiembra) -> None:
    """Quita de `Preferences` las firmas que invalidarian los favoritos.

    Chrome firma `Bookmarks` con un MAC cuya semilla incluye la ruta del
    perfil. Al mover la carpeta la firma no valida, Chrome lo toma por
    manipulado y **resetea los favoritos**: escribe un `Bookmarks` vacio y
    renombra el bueno a `Bookmarks.bak`.

    Retirando las firmas no hay contra que validar, asi que Chrome acepta el
    contenido y lo vuelve a firmar con la semilla del sitio nuevo.
    """
    import json

    for nombre in ARCHIVOS_CON_PROTECCION:
        ruta = perfil / nombre
        if not ruta.is_file():
            continue
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.warning("No se pudo leer '%s' para retirar sus firmas: %s", nombre, exc)
            continue

        retiradas = [clave for clave in CLAVES_DE_PROTECCION if clave in datos]
        if not retiradas:
            continue
        for clave in retiradas:
            datos.pop(clave, None)
        try:
            ruta.write_text(json.dumps(datos), encoding="utf-8")
        except OSError as exc:  # pragma: no cover - destino recien escrito
            log.warning("No se pudo reescribir '%s': %s", nombre, exc)
            continue
        resultado.protecciones_retiradas.extend(f"{nombre}:{c}" for c in retiradas)
        log.info("Firmas retiradas de '%s': %s", nombre, ", ".join(retiradas))


def sembrar(
    user_data: Path,
    destino: Path,
    *,
    directorio: str = "Default",
    rehacer: bool = False,
) -> ResultadoSiembra:
    """Copia el perfil personal a `destino`, listo para automatizar.

    La estructura de `destino` imita la de `User Data` -- `Local State` arriba y
    el perfil en su subcarpeta -- porque es lo que espera Chrome cuando recibe
    la carpeta como `--user-data-dir`.

    Args:
        user_data: carpeta 'User Data' de Chrome.
        destino: carpeta de trabajo de la automatizacion.
        directorio: perfil a copiar ('Default', 'Profile 1'...).
        rehacer: borra `destino` antes de copiar. Sin esto se copia encima, que
            es lo que interesa para refrescar sesiones sin perder lo demas.

    Raises:
        ErrorSiembraPerfil: si el origen no existe o el destino no es valido.
    """
    origen_perfil = user_data / directorio
    if not origen_perfil.is_dir():
        raise ErrorSiembraPerfil(
            f"No existe el perfil '{directorio}' en {user_data}. "
            "Comprobar NAVEGADOR_PERFIL_DIRECTORIO."
        )

    destino = Path(destino)
    if destino.resolve() == user_data.resolve():
        raise ErrorSiembraPerfil(
            "El destino de la siembra no puede ser el propio 'User Data' de "
            "Chrome: la copia existe precisamente para no automatizar esa "
            "carpeta, que es la que Chrome bloquea."
        )

    if rehacer and destino.exists():
        log.info("Borrando la copia anterior en %s", destino)
        shutil.rmtree(destino, ignore_errors=True)

    resultado = ResultadoSiembra(destino=destino)

    # 1. 'Local State' SOLO si el destino no tiene uno. Sobrescribirlo en un
    #    refresco rotaria la clave de cifrado y dejaria ilegibles las cookies
    #    que el perfil de trabajo ya hubiera ganado iniciando sesion.
    estado = user_data / ARCHIVO_ESTADO_GLOBAL
    destino.mkdir(parents=True, exist_ok=True)
    if not estado.is_file():
        log.warning("No hay '%s' en %s.", ARCHIVO_ESTADO_GLOBAL, user_data)
    elif (destino / ARCHIVO_ESTADO_GLOBAL).is_file():
        log.info(
            "'%s' ya existe en el destino: se conserva, para no invalidar las "
            "cookies que el perfil de trabajo ya tenga.",
            ARCHIVO_ESTADO_GLOBAL,
        )
    else:
        try:
            shutil.copy2(estado, destino / ARCHIVO_ESTADO_GLOBAL)
            resultado.archivos += 1
        except OSError as exc:
            log.warning("No se pudo copiar '%s': %s", ARCHIVO_ESTADO_GLOBAL, exc)
            resultado.omitidos_por_bloqueo.append(ARCHIVO_ESTADO_GLOBAL)

    # 2. La lista blanca del perfil, en su subcarpeta.
    log.info("Copiando %s -> %s", origen_perfil, destino / directorio)
    destino_perfil = destino / directorio
    for nombre in ARCHIVOS_SIEMPRE:
        _copiar_uno(
            origen_perfil / nombre, destino_perfil / nombre, resultado, solo_si_falta=False
        )
    for nombre in ARCHIVOS_SOLO_PRIMERA_VEZ:
        _copiar_uno(
            origen_perfil / nombre, destino_perfil / nombre, resultado, solo_si_falta=True
        )

    # 3. Sin retirar las firmas, Chrome descartaria los favoritos al abrir.
    _retirar_protecciones(destino / directorio, resultado)

    resultado.claves_ausentes = [
        nombre
        for nombre in ARCHIVOS_CLAVE
        if not (destino / directorio / nombre).is_file()
    ]
    log.info(
        "Siembra terminada: %d archivos, %.1f MB, %d bloqueados, %d omitidos por "
        "cifrado, %d claves ausentes.",
        resultado.archivos,
        resultado.megabytes,
        len(resultado.omitidos_por_bloqueo),
        len(resultado.omitidos_por_cifrado),
        len(resultado.claves_ausentes),
    )
    return resultado
