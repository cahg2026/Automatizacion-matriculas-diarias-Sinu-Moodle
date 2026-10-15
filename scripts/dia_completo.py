"""Flujo completo del dia, de Power BI a la columna de gestion en el Sheet.

Sustituye a `dia_completo.ps1`, que Kaspersky bloquea al cargarlo:

    dia_completo.ps1: 1 Caracter: 1
    Este script contiene elementos malintencionados y ha sido bloqueado
    por el software antivirus.
    FullyQualifiedErrorId : ScriptContainedMaliciousContent

El bloqueo es de AMSI y ocurre al ANALIZAR el archivo, antes de ejecutar su
primera instruccion: no dejaba ni bitacora, lo que hacia el fallo mudo. No se
intento reescribir el .ps1 "para que no lo detecte": remodelar codigo hasta
esquivar una regla de antivirus es, en la forma, evasion de deteccion, y en el
fondo es adivinar contra una heuristica opaca que puede cambiar cualquier dia.
Se cambio de tecnologia, que es lo que resuelve el problema de verdad.

Y de paso arregla lo que el .ps1 no podia dar:

  - La logica del dia entra en pytest. Los tres defectos del 07/09/2026
    (bitacora en UTF-16, rotacion del diario mal colocada, `--saltar-hechas`
    que no se pasaba) vivian todos en la capa que no se podia probar.
  - `subprocess` recibe LISTAS de argumentos, asi que no hay shell que
    reinterprete comillas. Con una ruta que tiene espacios y acentos, eso
    quita toda una clase de fallos.
  - La bitacora recoge stdout Y stderr. El .ps1 perdia stderr, que es justo
    donde Python escribe sus logs.

Las seis etapas:

    0. Perfil de navegador y sesion de Google (navegando, no contando cookies)
    1. Cerrojo: se actualizo el tablero HOY? Si no, avisa y NO exporta
    2. Power BI -> .xlsx en data/raw/
    3. Fase 1: calidad, orden A-Z por periodo, subida del Sheet
    4. ISEF07: procesa las matriculas, periodo por periodo
    5. Gestion: escribe la columna Q y sube el Sheet marcado
    6. Cierre: ciclos a medias, escalados y aviso con metricas

Uso:
    python scripts\\dia_completo.py --ejecutar-de-verdad
    python scripts\\dia_completo.py                    # ensayo, no escribe
    python scripts\\dia_completo.py --hasta-subir
"""

from __future__ import annotations

import argparse
import logging
import os
import queue
import re
import subprocess
import sys
import threading
import time
from datetime import date, datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from moodle_sinu import (  # noqa: E402
    estado_dia,
    notificaciones,
    perfil_navegador,
    resumen_dia,
)
from moodle_sinu.config import (  # noqa: E402
    DIR_CRUDO,
    DIR_LOGS,
    DIR_PROCESADO,
    RUTA_ENV,
    Config,
    asegurar_directorios,
)

log = logging.getLogger("dia_completo")

PY = RAIZ / ".venv" / "Scripts" / "python.exe"
DIARIO = DIR_LOGS / "resultados_etapa4.jsonl"
ESCALADOS = DIR_LOGS / "escalado_isef05_pacf50.jsonl"

#: Lo que devuelve scripts/verificar_actualizacion.py.
CERROJO_OK = 0
CERROJO_DESACTUALIZADO = 3
CERROJO_ILEGIBLE = 4

#: Lo que devuelve scripts/probar_perfil.py cuando la sesion de Google no
#: sirve, comprobada navegando y no contando cookies.
CERROJO_SESION_CAIDA = 5

RX_SHEET = re.compile(r"https://docs\.google\.com/spreadsheets/d/[A-Za-z0-9_-]+")

#: MODO_SIMULACION, tal cual aparece en config/.env.
RX_SIMULACION = re.compile(r"^\s*MODO_SIMULACION\s*=", re.IGNORECASE)


class FalloDelFlujo(RuntimeError):
    """Una etapa fallo de forma que no tiene sentido continuar."""


class PasoEnCurso:
    """Recuerda por donde va el flujo para que el aviso pueda decirlo.

    Antes del 23/09/2026 el aviso de fallo decia solo "El flujo se interrumpió
    antes de terminar": cierto, y sin ningun valor a las 9:02 en el movil.
    Saber si murio bajando el tablero o marcando la columna Q cambia lo que
    hay que hacer, asi que el paso viaja hasta el aviso.
    """

    def __init__(self) -> None:
        self.nombre = "el arranque del flujo"
        self.intentos = ""

    def en(self, nombre: str) -> None:
        self.nombre = nombre
        self.intentos = ""


# ---------------------------------------------------------------------------
# El cerrojo de escritura
# ---------------------------------------------------------------------------


def leer_simulacion() -> str:
    if not RUTA_ENV.is_file():
        return "(sin .env)"
    for linea in RUTA_ENV.read_text(encoding="utf-8").splitlines():
        if RX_SIMULACION.match(linea):
            return linea.split("=", 1)[1].strip()
    return "(no definido)"


def fijar_simulacion(valor: str) -> None:
    """Fija MODO_SIMULACION en config/.env Y en el entorno de este proceso.

    Las dos cosas, y el entorno NO es un extra: es la mitad que faltaba.

    El 08/09/2026 una corrida entera con --ejecutar-de-verdad se fue en
    simulacion sin escribir nada. La secuencia era esta:

      1. este script llama a `Config.desde_entorno()`, que hace
         `load_dotenv(override=False)` y deja MODO_SIMULACION=true en
         os.environ, porque en ese instante el .env decia true;
      2. luego se reescribe el ARCHIVO a false;
      3. los subprocesos heredan os.environ, donde sigue true;
      4. su propio `load_dotenv(override=False)` se niega a pisar una
         variable que ya existe, asi que leen true y simulan.

    El .ps1 no tenia el problema porque nunca importaba `config` en su propio
    proceso. Lo introdujo la migracion a Python, y solo se vio leyendo la
    bitacora: el fallo era mudo y del lado seguro (no escribe), que es
    precisamente lo que lo hace facil de no notar.

    Se toca el .env linea por linea a proposito: lleva comentarios que
    documentan cada variable, y reescribirlo entero los perderia.
    """
    if RUTA_ENV.is_file():
        lineas = RUTA_ENV.read_text(encoding="utf-8").splitlines()
        nuevas = [
            f"MODO_SIMULACION={valor}" if RX_SIMULACION.match(l) else l
            for l in lineas
        ]
        RUTA_ENV.write_text("\n".join(nuevas) + "\n", encoding="utf-8")

    # Lo que de verdad leen los subprocesos.
    os.environ["MODO_SIMULACION"] = valor


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------


def mas_reciente(carpeta: Path, patron: str) -> Path | None:
    """El archivo mas nuevo que casa con el patron. None si no hay ninguno.

    Se localiza por fecha de modificacion y no leyendo rutas de un log: el
    formato de los logs cambia, la fecha del archivo no.
    """
    if not carpeta.is_dir():
        return None
    candidatos = sorted(
        carpeta.glob(patron), key=lambda p: p.stat().st_mtime, reverse=True
    )
    return candidatos[0] if candidatos else None


def url_de_sheet(texto: str) -> str | None:
    """La primera URL de Google Sheet que aparezca en una salida."""
    m = RX_SHEET.search(texto or "")
    return m.group(0) if m else None


def toca_rotar(diario: Path, hoy: date) -> bool:
    """True si el diario es de otro dia.

    Hace falta rotarlo porque `--saltar-hechas` compara por
    (periodo, cedula, materia) SIN mirar la fecha: con el diario de ayer
    dentro saltaria unidades de hoy creyendolas hechas.
    """
    if not diario.is_file():
        return False
    return date.fromtimestamp(diario.stat().st_mtime) != hoy


# ---------------------------------------------------------------------------
# Ejecucion de etapas
# ---------------------------------------------------------------------------


class Bitacora:
    """Escribe en UTF-8 y por consola a la vez.

    El .ps1 usaba `Tee-Object`, que en PowerShell 5.1 no acepta -Encoding y
    escribia UTF-16: la bitacora salia ilegible en cualquier editor o grep.
    """

    def __init__(self, ruta: Path) -> None:
        self.ruta = ruta
        ruta.parent.mkdir(parents=True, exist_ok=True)

    def escribir(self, texto: str) -> None:
        with self.ruta.open("a", encoding="utf-8") as f:
            f.write(texto + "\n")
        print(texto, flush=True)


def titulo(bit: Bitacora, texto: str) -> None:
    bit.escribir("")
    bit.escribir("=" * 72)
    bit.escribir(texto)
    bit.escribir("=" * 72)


def correr(orden: list[str], bit: Bitacora) -> tuple[int, str]:
    """Lanza una etapa y devuelve (codigo, salida completa).

    stderr se une a stdout: Python escribe sus logs en stderr, y el .ps1 los
    perdia. La bitacora tiene que contener el porque de un fallo, no solo el
    hecho de que fallo.
    """
    bit.escribir(f"$ {' '.join(str(x) for x in orden)}")
    proceso = subprocess.Popen(
        [str(x) for x in orden],
        cwd=str(RAIZ),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    recogido: list[str] = []
    assert proceso.stdout is not None
    for linea in proceso.stdout:
        linea = linea.rstrip("\n")
        recogido.append(linea)
        bit.escribir(linea)
    proceso.wait()
    return proceso.returncode, "\n".join(recogido)


#: La linea en que verificar_actualizacion.py dice que fecha leyo:
#:   "Estado       : desactualizado (ultima actualizacion 27/09/2026 ...)"
RX_ESTADO_TABLERO = re.compile(r"^\s*Estado\s*:\s*(.+)$", re.MULTILINE)


def detalle_del_cerrojo(salida: str) -> str:
    """Lo que el cerrojo leyo del tablero, para el cuerpo del aviso."""
    m = RX_ESTADO_TABLERO.search(salida or "")
    if m:
        return m.group(1).strip()
    return "la fecha del tablero es anterior a hoy"


def pausar_por_tablero_viejo(
    bit: Bitacora, cfg: Config, hoy: date, salida: str, *, avisar: bool
) -> None:
    """El paso 1 dijo 3: tablero de otro dia. Se pausa el dia, limpio.

    Desde el 28/09/2026 no se espera a que el tablero llegue: se registra la
    pausa en el contrato de la Fase A, se avisa (webhook/correo + evento en
    Calendar, todo en `notificaciones.enviar`) y el orquestador sale con 0 sin
    tocar el paso 2.

    El aviso lo da AQUI el orquestador y no el cerrojo, que ya no avisa en el
    caso 3: con los dos avisando llegarian dos alertas y dos eventos.

    Nunca lanza: un estado que no se puede escribir no debe impedir el aviso,
    y un aviso fallido no debe convertir en rojo una pausa correcta.
    """
    titulo(bit, "PAUSADO: el tablero de Power BI no se actualizo hoy")
    bit.escribir("No se exporto nada y no se toco SINU.")

    try:
        ruta = estado_dia.registrar_pausa_bi_viejo(hoy)
        bit.escribir(f"Estado del dia: {ruta} ({estado_dia.ESTADO_PAUSADO_BI_VIEJO})")
    except OSError as exc:
        bit.escribir(f"No se pudo escribir el estado del dia: {exc}")

    if avisar:
        detalle = detalle_del_cerrojo(salida)
        r = notificaciones.enviar(
            notificaciones.aviso_tablero_desactualizado(
                detalle, hoy=hoy, hora=f"{datetime.now():%H:%M}"
            ),
            cfg,
        )
        bit.escribir(f"Aviso de tablero viejo: {r.resumen()}")

    bit.escribir("")
    bit.escribir("Cuando el tablero este al dia:")
    bit.escribir("  python scripts/dia_completo.py --ejecutar-de-verdad")


#: scripts/exportar_reporte.py devuelve 2 cuando le pasaron argumentos
#: incompatibles. Eso no se arregla repitiendolo.
EXPORTACION_MAL_USADA = 2

RX_MOTIVO = re.compile(r"(?:Exportacion fallida|ERROR)\s*[:\-]\s*(.+)$")


def motivo_del_fallo(salida: str) -> str:
    """Saca de la salida de una etapa la linea que explica el fallo.

    Se busca de abajo arriba: la ultima linea de error es la que describe por
    que se rindio, y las de mas arriba suelen ser sintomas intermedios.
    """
    for linea in reversed(salida.splitlines()):
        m = RX_MOTIVO.search(linea.strip())
        if m:
            return m.group(1).strip()
    return ""


def limpiar_chrome_colgado(bit: Bitacora, cfg: Config) -> int:
    """Cierra los Chrome que quedaron colgando del perfil de la automatizacion.

    Con el perfil PERSONAL no se toca nada: ahi los procesos de Chrome son el
    navegador de diario del operador, y cerrarlos por detras seria pasarse de
    la raya -- la automatizacion estaria cerrando pestanas suyas para poder
    reintentar la suya.
    """
    try:
        perfil = perfil_navegador.resolver(cfg)
    except Exception as exc:  # noqa: BLE001 - limpieza oportunista
        bit.escribir(f"No se pudo resolver el perfil para limpiarlo: {exc}")
        return 0

    if perfil.es_chrome_real:
        bit.escribir(
            "Perfil PERSONAL: no se cierra ningun Chrome (seria el del operador)."
        )
        return 0

    # El canal va explicito: hasta el 25/09/2026 esta llamada buscaba siempre
    # 'chrome.exe' y el canal es 'msedge' desde el 24/09, asi que no encontraba
    # nada y la limpieza entre reintentos llevaba un dia sin existir.
    cerrados = perfil_navegador.cerrar_chrome_del_perfil(perfil.ruta, perfil.canal)
    if cerrados:
        bit.escribir(
            f"Cerrados {cerrados} proceso(s) de "
            f"{perfil_navegador.proceso_de(perfil.canal)} colgados del perfil."
        )
    return cerrados


def exportar_con_reintentos(bit: Bitacora, cfg: Config, paso: PasoEnCurso) -> None:
    """Corre la etapa 2 hasta que salga bien o se agoten los intentos.

    Por que existe
    --------------
    El proceso principal de Chrome revienta de vez en cuando justo al arrancar
    la descarga: `0xC0000005` dentro de `chrome.dll`, leyendo la direccion -1,
    con el volcado en `.playwright-perfil-powerbi\\Crashpad\\reports`. Paso el
    18, el 22 y el 23/09/2026, en tres versiones distintas de Chrome, asi que
    no es una regresion de una compilacion concreta ni algo que podamos
    parchear desde aqui.

    Lo que si esta en nuestra mano es que no cueste el dia. Hasta ahora una
    sola caida ahi terminaba la corrida con 0 matriculas procesadas, y eso
    pese a que el reintento a mano pasaba a la primera (22/09).

    Los dos detalles que lo hacen funcionar
    ---------------------------------------
    1. Cada intento abre un navegador NUEVO -- son subprocesos distintos, asi
       que eso sale gratis.
    2. Entre intento e intento se cierran los Chrome que quedaron colgando del
       perfil. Sin esto el reintento hereda el navegador envenenado: el del
       23/09 a las 09:09 fallo ya al abrir el informe, antes de la descarga.
    """
    intentos = max(1, cfg.exportacion_reintentos)
    espera = max(0, cfg.exportacion_espera_seg)
    motivo = ""

    for intento in range(1, intentos + 1):
        if intento > 1:
            bit.escribir("")
            bit.escribir(f"--- Reintento {intento} de {intentos} ---")
        codigo, salida = correr(
            [PY, "scripts/exportar_reporte.py", "--captura", "-v"], bit
        )
        if codigo == 0:
            if intento > 1:
                bit.escribir("")
                bit.escribir(f"La exportacion salio bien en el intento {intento}.")
            paso.intentos = f"{intento} de {intentos}"
            return

        motivo = motivo_del_fallo(salida) or f"la etapa devolvio el codigo {codigo}"
        paso.intentos = f"{intento} de {intentos}"

        if codigo == EXPORTACION_MAL_USADA:
            raise FalloDelFlujo(
                f"La exportacion se llamo mal ({motivo}). Repetirla no lo "
                f"arregla: hay que corregir la orden."
            )

        bit.escribir("")
        bit.escribir(f"Intento {intento} de {intentos} fallido: {motivo}")

        if intento == intentos:
            break

        limpiar_chrome_colgado(bit, cfg)
        bit.escribir(f"Esperando {espera}s antes del siguiente intento...")
        time.sleep(espera)

    raise FalloDelFlujo(
        f"La exportacion de Power BI fallo en los {intentos} intentos. "
        f"Ultimo motivo: {motivo}"
    )


#: Intentos de la etapa 3 (Fase 1 + subida a Drive). DOS: el original y UNO mas.
#:
#: Hasta el 26/09/2026 era uno solo, y era el unico paso del flujo sin red:
#: cualquier tropiezo de Drive -- una subida por *drop* que no prende, una
#: conversion a Sheet que tarda de mas -- mataba el dia entero, y lo mataba en el
#: peor momento: con el cerrojo de escritura ya abierto y el reporte ya
#: descargado. Un segundo intento cuesta ~90 s.
#:
#: Y solo UNO mas, no cinco como la exportacion. La diferencia es que aqui el
#: reintento NO sale gratis (ver `subir_con_reintento`): si la primera subida
#: llego a crear el Sheet, la segunda crea otro. Cinco intentos serian hasta
#: cinco Sheets del mismo dia en Drive, que es peor que no subir nada -- con dos,
#: el operador como mucho tiene que borrar uno.
SUBIDA_INTENTOS = 2


def subir_con_reintento(
    bit: Bitacora, reporte: str, paso: PasoEnCurso
) -> tuple[str, str]:
    """Corre la etapa 3 y la reintenta UNA vez. Devuelve (salida, validado).

    Por que el reintento no es un bucle sin mas
    -------------------------------------------
    `subir_reporte.py` hace dos cosas en una: la Fase 1 (local, deterministica)
    y la subida a Drive (por navegador, y por *drop*, que es donde falla). Un
    reintento a ciegas repetiria las dos, y eso tiene dos efectos feos:

    - **Otra copia coloreada.** La Fase 1 escribe un `_validado_<sello>.xlsx`
      nuevo cada vez. Repetirla no rompe nada pero ensucia `data/processed/`, y
      sobre todo deja dos candidatas a "la copia coloreada de hoy", que es lo que
      las etapas 4 y 5 localizan por fecha.
    - **Otro Sheet.** Si la primera subida llego a crear el Sheet y murio
      despues, el reintento crea un SEGUNDO Sheet del mismo dia. Entonces el
      operador tiene dos hojas casi iguales y ninguna forma rapida de saber cual
      es la que esta procesando el robot.

    Asi que antes de reintentar se mira lo que dejo el intento fallido:

    1. **Si en su salida ya aparece una URL de Sheet**, la subida SI ocurrio y lo
       que fallo vino despues. NO se reintenta -- crear un segundo Sheet seria
       destruir informacion, no recuperarla. Se aborta diciendo la URL y el
       comando exacto para reanudar.
    2. **Si ya dejo una copia coloreada**, el reintento la reutiliza con
       `--ya-validado` en vez de rehacer la Fase 1.

    Raises:
        FalloDelFlujo: si los dos intentos fallan, o si el Sheet ya existe.
    """
    antes = mas_reciente(DIR_PROCESADO, "*_validado_*.xlsx")

    for intento in range(1, SUBIDA_INTENTOS + 1):
        if intento > 1:
            bit.escribir("")
            bit.escribir(f"--- Reintento {intento} de {SUBIDA_INTENTOS} ---")

        orden = [PY, "scripts/subir_reporte.py"]
        coloreada = mas_reciente(DIR_PROCESADO, "*_validado_*.xlsx")
        ya_hay_copia = coloreada is not None and coloreada != antes
        if intento > 1 and ya_hay_copia:
            # La Fase 1 del intento anterior si termino: se reaprovecha en vez
            # de generar otra copia identica con otro sello.
            bit.escribir(f"Se reutiliza la copia coloreada ya hecha: {coloreada.name}")
            orden += [str(coloreada), "--ya-validado"]
        else:
            orden.append(reporte)
        orden += ["--visible", "--traza", "-v"]

        codigo, salida = correr(orden, bit)
        paso.intentos = f"{intento} de {SUBIDA_INTENTOS}"

        if codigo == 0:
            if intento > 1:
                bit.escribir("")
                bit.escribir(f"La subida salio bien en el intento {intento}.")
            coloreada = mas_reciente(DIR_PROCESADO, "*_validado_*.xlsx")
            if coloreada is None:
                raise FalloDelFlujo("No aparecio la copia coloreada en data/processed.")
            return salida, str(coloreada)

        motivo = motivo_del_fallo(salida) or f"la etapa devolvio el codigo {codigo}"
        bit.escribir("")
        bit.escribir(f"Intento {intento} de {SUBIDA_INTENTOS} fallido: {motivo}")

        # El Sheet ya existe: reintentar crearia un segundo. Se para aqui.
        url_creada = url_de_sheet(salida)
        if url_creada:
            raise FalloDelFlujo(
                f"La etapa 3 fallo DESPUES de crear el Sheet, asi que la hoja de "
                f"hoy ya existe: {url_creada}\n"
                f"NO se reintenta: una segunda subida dejaria dos Sheets del "
                f"mismo dia en Drive.\n"
                f"Comprobar la hoja y reanudar con:\n"
                f'  python scripts/dia_completo.py --ejecutar-de-verdad '
                f'--sheet-url "{url_creada}" --reporte "<copia coloreada>"'
            )

        if intento == SUBIDA_INTENTOS:
            raise FalloDelFlujo(
                f"La subida a Drive fallo en los {SUBIDA_INTENTOS} intentos. "
                f"Ultimo motivo: {motivo}"
            )

        bit.escribir("Se reintenta una vez: la subida por *drop* falla de forma")
        bit.escribir("transitoria, y este es el unico paso que mataba el dia entero.")

    # Inalcanzable: el bucle sale por return o por FalloDelFlujo.
    raise FalloDelFlujo("La subida a Drive fallo.")  # pragma: no cover


# ---------------------------------------------------------------------------
# El dia
# ---------------------------------------------------------------------------


def _argumentos(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--ejecutar-de-verdad",
        action="store_true",
        help=(
            "Modifica matriculas en SINU. Abre el cerrojo MODO_SIMULACION al "
            "empezar y lo CIERRA al terminar, pase lo que pase."
        ),
    )
    p.add_argument("--reporte", default="", help="Salta la etapa 2 y usa este .xlsx.")
    p.add_argument(
        "--sheet-url", default="", help="Salta las etapas 2 y 3 y usa este Sheet."
    )
    p.add_argument(
        "--hasta-subir",
        action="store_true",
        help="Se detiene tras subir el Sheet, sin tocar SINU.",
    )
    p.add_argument(
        "--sin-rotar-diario",
        action="store_true",
        help="No rota logs/resultados_etapa4.jsonl. Para reintentar el mismo dia.",
    )
    p.add_argument(
        "--periodos", default="", help="Solo estos periodos, separados por coma."
    )
    p.add_argument(
        "--sin-verificar-actualizacion",
        action="store_true",
        help="Salta el cerrojo del tablero. Para relanzar a mano.",
    )
    p.add_argument(
        "--sin-avisar", action="store_true", help="No manda ninguna notificacion."
    )
    p.add_argument(
        "--solo-si-pausado",
        action="store_true",
        help=(
            "Solo corre si el dia quedo PAUSADO_BI_VIEJO (tablero viejo en una "
            "corrida anterior de hoy); si no, sale con 0 sin tocar nada. Es la "
            "tarea de reintento de las 9:30."
        ),
    )
    return p.parse_args(argv)


def debe_reintentar(hoy: date) -> tuple[bool, str]:
    """Para `--solo-si-pausado`: ¿hay una pausa por tablero viejo que retomar?

    Solo PAUSADO_BI_VIEJO da paso. Cualquier otro estado -- EN_CURSO,
    TERMINADO, o que no haya estado -- significa que no hay nada que retomar,
    y en el caso EN_CURSO arrancar seria abrir una SEGUNDA corrida sobre el
    mismo perfil de navegador mientras la primera esta en ISEF07.
    """
    estado = estado_dia.leer(hoy).get("estado") or "(sin estado de hoy)"
    return estado == estado_dia.ESTADO_PAUSADO_BI_VIEJO, estado


def _registrar_avance(bit: Bitacora, hoy: date, estado: str) -> None:
    try:
        estado_dia.registrar_avance(hoy, estado)
    except OSError as exc:
        bit.escribir(f"No se pudo escribir el estado del dia ({estado}): {exc}")


def main(argv: list[str] | None = None) -> int:
    args = _argumentos(argv)

    # La consola de Windows es cp1252 y no traga los acentos de los logs ni los
    # emoji de los asuntos. Sin esto, un aviso correcto reventaria al imprimirse.
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(errors="replace")
        except AttributeError:  # pragma: no cover
            pass

    if not PY.is_file():
        print(f"ERROR: no existe {PY}. Rehacer el entorno (ver README).")
        return 1

    asegurar_directorios()
    sello = datetime.now().strftime("%Y%m%d_%H%M%S")
    bit = Bitacora(DIR_LOGS / f"dia_completo_{sello}.log")
    hoy = date.today()
    cfg = Config.desde_entorno()

    # La guarda va ANTES de abrir el cerrojo de escritura y antes del try: si
    # no hay nada que retomar, esta corrida no debe tocar ni el .env ni avisar.
    if args.solo_si_pausado:
        reintentar, estado = debe_reintentar(hoy)
        if not reintentar:
            bit.escribir(
                f"--solo-si-pausado: el dia no esta pausado por tablero viejo "
                f"(estado: {estado}). Nada que hacer."
            )
            return 0
        bit.escribir(
            "--solo-si-pausado: el dia quedo PAUSADO_BI_VIEJO. Se vuelve a "
            "mirar el tablero."
        )

    reporte = args.reporte
    sheet_url = args.sheet_url
    validado = ""
    codigo_isef07 = 0
    flujo_completo = False
    aviso_ya_dado = False
    paso = PasoEnCurso()
    motivo_fallo = ""

    titulo(bit, f"FLUJO DEL DIA - {hoy:%d/%m/%Y} {datetime.now():%H:%M}")
    if args.ejecutar_de_verdad:
        bit.escribir("Modo    : EJECUCION REAL (se modificaran matriculas en SINU)")
    else:
        bit.escribir("Modo    : SIMULACION (no se toca nada)")
    bit.escribir(f"Bitacora: {bit.ruta}")
    bit.escribir(f"MODO_SIMULACION antes de empezar: {leer_simulacion()}")
    if not args.sin_avisar and not cfg.tiene_canal_de_aviso:
        bit.escribir("")
        bit.escribir("AVISO: no hay canal de notificacion configurado.")
        bit.escribir("       Los avisos solo quedaran en logs/avisos/.")

    try:
        esperado = "false" if args.ejecutar_de_verdad else "true"
        fijar_simulacion(esperado)

        # Se comprueba lo que van a leer los HIJOS, no lo que creemos haber
        # escrito. Es la guarda del fallo del 08/09/2026: el archivo decia
        # false, el entorno heredado decia true, y la corrida entera simulo
        # creyendo que escribia.
        efectivo = os.environ.get("MODO_SIMULACION", "(sin definir)")
        bit.escribir(f"MODO_SIMULACION en .env      : {leer_simulacion()}")
        bit.escribir(f"MODO_SIMULACION que veran los hijos: {efectivo}")
        if efectivo != esperado:
            raise FalloDelFlujo(
                f"El cerrojo no quedo como debia: los subprocesos leerian "
                f"MODO_SIMULACION={efectivo} y hace falta {esperado}. Sin esto "
                f"la corrida haria lo contrario de lo que se le pidio."
            )
        if args.ejecutar_de_verdad:
            bit.escribir("Cerrojo MODO_SIMULACION abierto para esta corrida.")

        # --- 0. Perfil -----------------------------------------------------
        titulo(bit, "PASO 0/6 - Perfil de navegador y sesion de Google")
        paso.en("PASO 0/6 - Perfil de navegador y sesion de Google")
        codigo, _ = correr([PY, "scripts/probar_perfil.py"], bit)
        if codigo == CERROJO_SESION_CAIDA:
            # Se detecta AQUI a proposito. El 08/09/2026 la sesion de Google
            # estaba caida y el paso 0 la dio por buena (contaba cookies, que
            # estaban todas): se exporto Power BI, se abrio el cerrojo de
            # escritura, y el fallo salio en el paso 3. Comprobarla de verdad
            # al principio ahorra todo eso.
            raise FalloDelFlujo(
                "La sesion de Google no sirve, asi que la subida del Sheet "
                "fallaria de todas formas. Resolverlo una vez, a mano:\n"
                "  python scripts/probar_perfil.py --iniciar-sesion\n"
                "Ojo: las cookies pueden estar TODAS y la sesion estar caida "
                "igualmente -- la cookie dice que el navegador la guarda, no "
                "que el servidor la acepte."
            )
        if codigo != 0:
            raise FalloDelFlujo("El perfil de navegador no se pudo abrir.")

        # --- 1. El cerrojo del dia -----------------------------------------
        # Solo cuando se va a exportar. Al reanudar con --sheet-url el tablero
        # ya se valido en la corrida original, y volver a mirarlo validaria un
        # dato distinto del que se va a procesar.
        va_a_exportar = not sheet_url and not reporte
        if not args.sin_verificar_actualizacion and va_a_exportar:
            titulo(bit, "PASO 1/6 - Cerrojo: se actualizo el tablero hoy?")
            paso.en("PASO 1/6 - Cerrojo del tablero")
            orden = [PY, "scripts/verificar_actualizacion.py"]
            if args.sin_avisar:
                orden.append("--sin-avisar")
            codigo, salida_cerrojo = correr(orden, bit)

            if codigo == CERROJO_DESACTUALIZADO:
                pausar_por_tablero_viejo(
                    bit, cfg, hoy, salida_cerrojo, avisar=not args.sin_avisar
                )
                # Salir con 0 es deliberado: el Programador de tareas marcaria
                # en rojo un dia que se resolvio exactamente como debia.
                aviso_ya_dado = True
                return 0

            if codigo == CERROJO_ILEGIBLE:
                titulo(bit, "DETENIDO: no se pudo leer la fecha del tablero")
                bit.escribir("Ojo: NO es lo mismo que un tablero viejo. La")
                bit.escribir("comprobacion en si fallo, probablemente porque el")
                bit.escribir("tablero cambio de forma. Para verlo:")
                bit.escribir("  python scripts/sondear_actualizacion.py --visible")
                aviso_ya_dado = True
                return 0

            if codigo != CERROJO_OK:
                raise FalloDelFlujo("El cerrojo del dia fallo tecnicamente.")
        elif not args.sin_verificar_actualizacion:
            bit.escribir("")
            bit.escribir("Cerrojo omitido: se reanuda sobre un reporte ya exportado.")

        # Pasado el paso 1 -- o saltado a mano --, el dia ya no esta pausado.
        # Sin esto, una corrida relanzada a mano con --sin-verificar-actualizacion
        # dejaria el estado en PAUSADO_BI_VIEJO y la tarea de las 9:30 arrancaria
        # una segunda corrida encima.
        _registrar_avance(bit, hoy, estado_dia.ESTADO_EN_CURSO)

        # --- 2. Power BI ---------------------------------------------------
        if va_a_exportar:
            titulo(bit, "PASO 2/6 - Power BI: descarga del tablero")
            paso.en("PASO 2/6 - Power BI: descarga del tablero")
            bit.escribir(
                f"Hasta {cfg.exportacion_reintentos} intentos, "
                f"{cfg.exportacion_espera_seg}s entre uno y otro."
            )
            exportar_con_reintentos(bit, cfg, paso)
            descargado = mas_reciente(DIR_CRUDO, "*.xlsx")
            if descargado is None:
                raise FalloDelFlujo("No aparecio ningun .xlsx en data/raw.")
            reporte = str(descargado)
            bit.escribir(f"Reporte descargado: {reporte}")

        # --- 3. Fase 1 y subida --------------------------------------------
        if not sheet_url:
            titulo(bit, "PASO 3/6 - Limpieza, orden A-Z y subida del Sheet")
            paso.en("PASO 3/6 - Limpieza y subida del Sheet a Drive")
            bit.escribir("Con ventana a proposito: la subida a Drive falla en headless.")
            bit.escribir(f"Hasta {SUBIDA_INTENTOS} intentos.")
            # `--no-matriculado` se omite: sin el, subir_reporte cuenta las
            # filas del .xlsx, que da el mismo numero.
            salida, validado = subir_con_reintento(bit, reporte, paso)
            sheet_url = url_de_sheet(salida) or ""
            if not sheet_url:
                raise FalloDelFlujo(
                    "La subida no informo de la URL del Sheet. Buscarla en Drive y "
                    "relanzar con --sheet-url <url> --reporte <copia coloreada>."
                )
            bit.escribir(f"Sheet del dia: {sheet_url}")
        else:
            bit.escribir(f"Se usa el Sheet indicado: {sheet_url}")
            validado = reporte

        # La copia COLOREADA es la que va a las etapas 4 y 5: sus numeros de
        # fila son los que coinciden con el Sheet, y de ahi sale el marcado de
        # la columna Q. Con el .xlsx crudo la gestion se escribiria desplazada.
        if not validado:
            raise FalloDelFlujo(
                "No se pudo determinar la copia coloreada. Pasarla con --reporte."
            )
        bit.escribir(f"Archivo de trabajo: {validado}")

        if args.hasta_subir:
            titulo(bit, "DETENIDO EN EL PASO 3 (--hasta-subir)")
            bit.escribir(f"Sheet   : {sheet_url}")
            bit.escribir(f"Archivo : {validado}")
            bit.escribir("")
            bit.escribir("Para seguir mas tarde:")
            bit.escribir(
                f"  python scripts/dia_completo.py --ejecutar-de-verdad "
                f'--sheet-url "{sheet_url}" --reporte "{validado}"'
            )
            aviso_ya_dado = True
            return 0

        # --- Rotacion del diario -------------------------------------------
        # Aqui y no al principio: si la corrida se detiene antes, rotar el
        # diario seria mover un archivo por nada.
        if not args.sin_rotar_diario and toca_rotar(DIARIO, hoy):
            dia_diario = date.fromtimestamp(DIARIO.stat().st_mtime)
            destino = DIR_LOGS / f"resultados_etapa4_{dia_diario:%Y%m%d}.jsonl"
            DIARIO.replace(destino)
            bit.escribir(f"Diario rotado: {destino.name}")

        # --- 4. ISEF07 ------------------------------------------------------
        titulo(bit, "PASO 4/6 - Procesar las matriculas en ISEF07")
        paso.en("PASO 4/6 - Procesar las matriculas en ISEF07")
        bit.escribir("NO uses SINU mientras corre: entra con la misma cuenta.")
        orden = [
            PY,
            "scripts/procesar_dia.py",
            validado,
            "--sheet-url",
            sheet_url,
            # Va SIEMPRE, y es seguro porque el diario se acaba de rotar: solo
            # puede contener verdes de HOY. Es lo que hace que reanudar una
            # corrida cortada no repita materias ya vinculadas.
            "--saltar-hechas",
            "-v",
        ]
        if args.ejecutar_de_verdad:
            orden.append("--ejecutar-de-verdad")
        for p in (x.strip() for x in args.periodos.split(",")):
            if p:
                orden += ["--solo", p]
        codigo_isef07, _ = correr(orden, bit)
        if codigo_isef07 != 0:
            bit.escribir("")
            bit.escribir("Algun periodo fallo. Se continua con la gestion y el")
            bit.escribir("cierre: lo hecho hasta ahora hay que marcarlo igual.")

        # --- 5. Columna Q ---------------------------------------------------
        titulo(bit, "PASO 5/6 - Marcar la gestion en el Sheet")
        paso.en("PASO 5/6 - Marcar la gestion en el Sheet")
        orden = [PY, "scripts/marcar_gestion.py", validado, "-v"]
        if args.ejecutar_de_verdad:
            orden += ["--subir", "--visible", "--reemplazar"]
        codigo, _ = correr(orden, bit)
        if codigo != 0:
            bit.escribir("El marcado fallo. El archivo local puede estar escrito.")

        # --- 6. Cierre ------------------------------------------------------
        titulo(bit, "PASO 6/6 - Cierre del dia")
        paso.en("PASO 6/6 - Cierre del dia")
        resumen = resumen_dia.calcular(hoy)
        bit.escribir(resumen_dia.formatear(resumen))
        if ESCALADOS.is_file():
            cola = ESCALADOS.read_text(encoding="utf-8").splitlines()[-10:]
            if cola:
                bit.escribir("")
                bit.escribir("Casos a validar en ISEF05/PACF50 (ultimos 10):")
                for linea in cola:
                    bit.escribir(f"  {linea}")

        titulo(bit, "FIN")
        bit.escribir(f"Sheet del dia : {sheet_url}")
        bit.escribir(f"Archivo       : {validado}")
        bit.escribir(f"Bitacora      : {bit.ruta}")
        if codigo_isef07 != 0:
            bit.escribir("")
            bit.escribir("Hubo periodos con fallo. Para reintentar SOLO esos:")
            bit.escribir(
                f"  python scripts/dia_completo.py --ejecutar-de-verdad "
                f'--sheet-url "{sheet_url}" --reporte "{validado}" '
                f"--periodos <PERIODO1,PERIODO2> --sin-rotar-diario"
            )

        if not args.sin_avisar:
            nota = (
                ""
                if codigo_isef07 == 0
                else "Algun periodo termino con error; ver la bitacora."
            )
            cuerpo = resumen_dia.formatear(resumen, nota)
            aviso = (
                notificaciones.aviso_exito(cuerpo, hoy=hoy)
                if codigo_isef07 == 0
                else notificaciones.aviso_fallo(
                    cuerpo,
                    hoy=hoy,
                    paso="PASO 4/6 - Procesar las matriculas en ISEF07",
                    motivo="Algun periodo termino con error.",
                    bitacora=str(bit.ruta),
                )
            )
            r = notificaciones.enviar(aviso, cfg)
            bit.escribir("")
            bit.escribir(f"Aviso de cierre: {r.resumen()}")
            aviso_ya_dado = True

        flujo_completo = True
        _registrar_avance(bit, hoy, estado_dia.ESTADO_TERMINADO)
        return 0 if codigo_isef07 == 0 else 1

    except FalloDelFlujo as exc:
        motivo_fallo = str(exc)
        bit.escribir("")
        bit.escribir(f"ERROR: {exc}")
        return 1
    except KeyboardInterrupt:
        motivo_fallo = "Interrumpido a mano (Ctrl+C)."
        bit.escribir("")
        bit.escribir("Interrumpido a mano.")
        return 130
    except Exception as exc:  # noqa: BLE001 - el finally tiene que correr siempre
        # El tipo va delante: un aviso que dice solo "list index out of range"
        # no orienta, y "IndexError: list index out of range" si.
        motivo_fallo = f"Fallo inesperado ({type(exc).__name__}): {exc}"
        log.exception("Fallo inesperado en el flujo del dia")
        bit.escribir("")
        bit.escribir("FALLO INESPERADO. Traza en el log.")
        return 1
    finally:
        # El cerrojo se cierra SIEMPRE, tambien si algo revento a mitad. Es el
        # motivo de gestionarlo aqui: del 01 al 07/09/2026 quedo abierto seis
        # dias porque dependia de que alguien se acordara de revertirlo.
        fijar_simulacion("true")
        bit.escribir("")
        bit.escribir(f"MODO_SIMULACION devuelto a: {leer_simulacion()}")

        # Un flujo que revento tiene que avisar. Sin esto, en desatendido un
        # fallo se ve exactamente igual que un dia sin novedades: silencio.
        if not args.sin_avisar and not flujo_completo and not aviso_ya_dado:
            try:
                r = notificaciones.enviar(
                    notificaciones.aviso_fallo(
                        resumen_dia.formatear(resumen_dia.calcular(hoy)),
                        hoy=hoy,
                        paso=paso.nombre,
                        motivo=motivo_fallo,
                        intentos=paso.intentos,
                        bitacora=str(bit.ruta),
                    ),
                    cfg,
                )
                bit.escribir(f"Aviso de fallo: {r.resumen()}")
            except Exception:  # noqa: BLE001
                log.exception("Tampoco se pudo avisar del fallo")


if __name__ == "__main__":
    raise SystemExit(main())
