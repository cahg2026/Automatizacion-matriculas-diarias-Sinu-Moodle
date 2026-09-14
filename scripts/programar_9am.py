"""Registra (o quita) la tarea de las 9:00, de lunes a viernes.

Sustituye a `programar_9am.ps1`. Ese aun funcionaba, pero era PowerShell, y
`dia_completo.ps1` ya cayo bloqueado por Kaspersky con
`ScriptContainedMaliciousContent`. Dejar la programacion en un .ps1 que
ademas registra una tarea -- construyendo la linea de comando en una cadena,
que es un patron de persistencia de manual -- es dejar puesta la siguiente
pieza que se va a bloquear. Aqui se habla con `schtasks.exe`, que es un
ejecutable normal del sistema.

Por que el Programador de tareas y NO `schedule`/APScheduler en Python: una
tarea del sistema sobrevive a reinicios, a cierres de sesion y a que se cierre
la consola. Un bucle de Python vive solo mientras viva su proceso, y basta un
reinicio nocturno para que el dia siguiente no se procese y nadie se entere --
que es exactamente el fallo que todo este montaje pretende evitar.

Se registra por XML y no con `/TR`: el XML permite fijar los ajustes que de
verdad deciden si la tarea corre (arrancar aunque el equipo estuviera apagado,
no rendirse con la bateria) y evita el infierno de comillas de `/TR` con una
ruta que tiene espacios y acentos.

Uso:
    python scripts\\programar_9am.py --simulacion   # estreno prudente
    python scripts\\programar_9am.py                # produccion
    python scripts\\programar_9am.py --quitar
    python scripts\\programar_9am.py --solo-mostrar
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from moodle_sinu.config import Config  # noqa: E402

PY = RAIZ / ".venv" / "Scripts" / "python.exe"
ORQUESTADOR = "scripts/dia_completo.py"
NOMBRE_POR_DEFECTO = "MoodleSinu-FlujoDiario"

#: 8 horas. El 07/09/2026 el dia entero tardo 148 min mas 27 de reintento, y el
#: 08/09 se estimaron ~4 h para 79 unidades. A eso hay que sumarle la ventana de
#: gracia del cerrojo (CERROJO_ESPERA_MIN, 90 min por defecto), asi que 6 h se
#: quedaban demasiado justas: la tarea se cortaria a mitad de la etapa 4, que es
#: la unica que escribe.
LIMITE_EJECUCION = "PT8H"

RX_HORA = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def _schtasks(*argumentos: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["schtasks.exe", *argumentos],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def existe(nombre: str) -> bool:
    return _schtasks("/Query", "/TN", nombre).returncode == 0


#: Lunes a viernes. El proceso es de gestion academica: en sabado y domingo no
#: hay quien atienda una alerta, y el tablero tampoco se mueve.
DIAS_LABORABLES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")

#: 0 = lunes ... 4 = viernes, 5 y 6 el fin de semana (weekday() de Python).
ULTIMO_LABORABLE = 4


def primer_disparo(hora: str, ahora: datetime | None = None) -> datetime:
    """Cuando debe dispararse por primera vez, saltando el fin de semana.

    HOY si esa hora aun no ha pasado; si ya paso, el siguiente dia laborable.
    Y si cae en sabado o domingo, se mueve al lunes.

    Los dos detalles importan y los dos costaron algo:

    - La primera version ponia siempre manana "para no programar una hora
      pasada". Registrada el 09/09/2026 a las 08:12 con la hora en 09:00, la
      tarea quedo para el DIA SIGUIENTE: se habria esperado a las 9:00 de ese
      mismo dia sin que pasara nada. Un fallo mudo, que solo salio al mirar
      NextRunTime.
    - El StartBoundary tiene que caer en un dia laborable. Windows respeta el
      DaysOfWeek del disparador, pero dejar el arranque un domingo hace que la
      "proxima ejecucion" se lea rara y complica comprobar que quedo bien.
    """
    referencia = ahora or datetime.now()
    h, m = (int(x) for x in hora.split(":"))
    candidato = referencia.replace(hour=h, minute=m, second=0, microsecond=0)
    if candidato <= referencia:
        candidato += timedelta(days=1)
    while candidato.weekday() > ULTIMO_LABORABLE:
        candidato += timedelta(days=1)
    return candidato


def _disparador_xml(arranque: datetime, una_vez: bool) -> str:
    """El bloque <Triggers> de la tarea.

    "Un solo dia" NO es la tarea semanal desactivada: es un disparador de una
    sola vez. La diferencia importa -- asi corre el dia pedido y despues se
    queda quieta SOLA, sin que nadie tenga que acordarse de apagarla. Y
    acordarse es justo lo que falla: el cerrojo MODO_SIMULACION estuvo abierto
    seis dias (01-07/09/2026) porque dependia de que alguien lo revirtiera.
    """
    inicio = f"      <StartBoundary>{arranque:%Y-%m-%dT%H:%M:%S}</StartBoundary>"
    if una_vez:
        return "\n".join(
            (
                "    <TimeTrigger>",
                inicio,
                "      <Enabled>true</Enabled>",
                "    </TimeTrigger>",
            )
        )

    dias = "\n".join(f"          <{d} />" for d in DIAS_LABORABLES)
    return "\n".join(
        (
            "    <CalendarTrigger>",
            inicio,
            "      <Enabled>true</Enabled>",
            "      <ScheduleByWeek>",
            "        <DaysOfWeek>",
            dias,
            "        </DaysOfWeek>",
            "        <WeeksInterval>1</WeeksInterval>",
            "      </ScheduleByWeek>",
            "    </CalendarTrigger>",
        )
    )


def construir_xml(
    hora: str, *, simulacion: bool, descripcion: str, una_vez: bool = False
) -> str:
    """El XML de la tarea.

    Los ajustes NO son adorno:

    StartWhenAvailable
        Si el equipo estaba apagado a las 9:00, la tarea corre en cuanto
        arranque. Sin esto el dia se salta sin dejar rastro, que es el modo de
        fallo mas silencioso posible.

    DisallowStartIfOnBatteries / StopIfGoingOnBatteries en false
        El defecto de Windows es NO arrancar sin corriente. En un portatil eso
        perderia el dia por estar desenchufado.

    InteractiveToken
        El flujo NECESITA sesion interactiva: la subida a Drive falla sin
        ventana (comprobado el 03/09/2026) y Chrome usa el perfil de este
        usuario. Con S4U ("ejecutar aunque el usuario no haya iniciado
        sesion") el navegador no tiene escritorio y la subida se cae.
    """
    argumentos = ORQUESTADOR if simulacion else f"{ORQUESTADOR} --ejecutar-de-verdad"
    usuario = os.environ.get("USERNAME", "")
    dominio = os.environ.get("USERDOMAIN", "")
    quien = f"{dominio}\\{usuario}" if dominio else usuario
    arranque = primer_disparo(hora)

    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>{escape(descripcion)}</Description>
  </RegistrationInfo>
  <Triggers>
{_disparador_xml(arranque, una_vez)}
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{escape(quien)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <ExecutionTimeLimit>{LIMITE_EJECUCION}</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(str(PY))}</Command>
      <Arguments>{escape(argumentos)}</Arguments>
      <WorkingDirectory>{escape(str(RAIZ))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def _avisar_si_no_hay_canal() -> None:
    cfg = Config.desde_entorno()
    if cfg.tiene_canal_de_aviso:
        return
    print()
    print("ATENCION: no hay canal de notificacion configurado.")
    print("La tarea correra, pero los avisos solo quedaran en logs/avisos/,")
    print("que nadie mira a las 9:05. Para que el desatendido sirva de algo,")
    print("anadir a config/.env UNA de estas dos cosas:")
    print()
    print("  NOTIFICAR_WEBHOOK=https://<...>   # Teams o Slack, sin contrasenas")
    print()
    print("  NOTIFICAR_SMTP_SERVIDOR=smtp.office365.com")
    print("  NOTIFICAR_SMTP_USUARIO=<cuenta>")
    print("  NOTIFICAR_SMTP_PASSWORD=<contrasena de aplicacion>")
    print("  NOTIFICAR_DESTINATARIOS=alguien@cun.edu.co")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--hora", default="09:00", help="Hora de disparo, HH:mm.")
    p.add_argument("--nombre", default=NOMBRE_POR_DEFECTO, help="Nombre de la tarea.")
    p.add_argument("--quitar", action="store_true", help="Borra la tarea.")
    p.add_argument(
        "--simulacion",
        action="store_true",
        help=(
            "Registra la tarea SIN --ejecutar-de-verdad: recorre el flujo y "
            "avisa, pero no escribe en SINU. Es la forma sensata de estrenar "
            "el desatendido."
        ),
    )
    p.add_argument(
        "--una-vez",
        action="store_true",
        help="Programa UNA sola ejecucion en vez de la repeticion de lunes a "
        "viernes. La tarea corre ese dia y se queda quieta sola, sin que nadie "
        "tenga que acordarse de apagarla.",
    )
    p.add_argument(
        "--solo-mostrar",
        action="store_true",
        help="Imprime lo que haria y no toca el Programador.",
    )
    args = p.parse_args(argv)

    print("=" * 72)

    # --- Quitar -------------------------------------------------------------
    if args.quitar:
        print(f"Quitando la tarea '{args.nombre}'")
        print("=" * 72)
        if not existe(args.nombre):
            print("No estaba registrada. Nada que hacer.")
            return 0
        if args.solo_mostrar:
            print(f"(--solo-mostrar) Se borraria la tarea '{args.nombre}'.")
            return 0
        r = _schtasks("/Delete", "/TN", args.nombre, "/F")
        if r.returncode != 0:
            print(f"ERROR al borrar: {r.stderr.strip() or r.stdout.strip()}")
            return 1
        print(f"Tarea '{args.nombre}' borrada. El flujo ya NO corre solo.")
        return 0

    # --- Comprobaciones previas --------------------------------------------
    cuando = "UNA SOLA VEZ" if args.una_vez else "de lunes a viernes"
    print(f"Programando el flujo a las {args.hora}, {cuando}")
    print("=" * 72)

    if not RX_HORA.match(args.hora):
        print(f"ERROR: --hora debe ser HH:mm en 24 horas (recibido '{args.hora}').")
        return 1
    if not PY.is_file():
        print(f"ERROR: no existe {PY}. Rehacer el entorno (ver README).")
        return 1
    if not (RAIZ / ORQUESTADOR).is_file():
        print(f"ERROR: no existe {RAIZ / ORQUESTADOR}.")
        return 1

    _avisar_si_no_hay_canal()

    descripcion = (
        "Flujo diario Moodle-SINU. Comprueba que el tablero de Power BI se "
        "actualizo hoy; si no, avisa y no exporta. Ver el README del proyecto."
    )
    xml = construir_xml(
        args.hora,
        simulacion=args.simulacion,
        descripcion=descripcion,
        una_vez=args.una_vez,
    )

    print()
    print("La tarea ejecutara:")
    print(f"  {PY} {ORQUESTADOR}" + ("" if args.simulacion else " --ejecutar-de-verdad"))
    print(f"  desde: {RAIZ}")
    print()
    if args.simulacion:
        print("MODO SIMULACION: recorre y avisa, pero NO escribe en SINU.")
    else:
        print("MODO REAL: modificara matriculas en SINU sin supervision.")

    if args.solo_mostrar:
        print()
        print("(--solo-mostrar: no se toco el Programador de tareas)")
        print()
        print(xml)
        return 0

    # --- Registro -----------------------------------------------------------
    # schtasks quiere el XML en UTF-16; con UTF-8 responde un error opaco.
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".xml", encoding="utf-16", delete=False
    ) as f:
        f.write(xml)
        ruta_xml = Path(f.name)

    registrada = False
    try:
        if existe(args.nombre):
            print()
            print(f"La tarea '{args.nombre}' ya existia: se reemplaza.")
        r = _schtasks("/Create", "/TN", args.nombre, "/XML", str(ruta_xml), "/F")
        registrada = r.returncode == 0
        if not registrada:
            print()
            print("ERROR al registrar la tarea:")
            print(f"  {r.stderr.strip() or r.stdout.strip()}")
            print()
            print(f"El XML quedo en {ruta_xml} para poder importarlo a mano")
            print("desde el Programador de tareas (Accion > Importar tarea).")
            return 1
    finally:
        # Solo se borra si se registro: si fallo, el XML es lo que permite
        # importar la tarea a mano. Y `registrada` empieza en False, asi que
        # una excepcion en `_schtasks` tampoco lo borra ni revienta aqui.
        if registrada:
            ruta_xml.unlink(missing_ok=True)

    print()
    if args.una_vez:
        print(f"Tarea '{args.nombre}' registrada: {args.hora}, UNA SOLA VEZ.")
    else:
        print(f"Tarea '{args.nombre}' registrada: {args.hora}, de lunes a viernes.")
    print(f"Primer disparo: {primer_disparo(args.hora):%A %d/%m/%Y %H:%M}")
    print()
    print("Comprobarla:")
    print(f'  schtasks /Query /TN "{args.nombre}" /V /FO LIST')
    print()
    print("Lanzarla ahora, sin esperar a manana:")
    print(f'  schtasks /Run /TN "{args.nombre}"')
    print()
    print("Quitarla:")
    print("  python scripts/programar_9am.py --quitar")
    print()
    print("IMPORTANTE: el equipo tiene que estar encendido y con la sesion de")
    print(f"{os.environ.get('USERNAME', '')} iniciada. El flujo abre Chrome con")
    print("ventana porque la subida a Drive no funciona sin escritorio.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
