<#
.SYNOPSIS
    Registra (o quita) la tarea diaria de las 9:00 en el Programador de Windows.

.DESCRIPTION
    Deja el flujo corriendo solo, todos los dias, sin que nadie teclee nada.

    Por que el Programador de tareas y NO `schedule`/APScheduler en Python:
    una tarea del sistema sobrevive a reinicios, a cierres de sesion y a que
    se cierre la consola. Un bucle de Python solo vive mientras su proceso
    viva, y basta un reinicio nocturno para que el dia siguiente no se procese
    y nadie se entere -- que es exactamente el fallo que este montaje pretende
    evitar.

    La tarea corre `dia_completo.ps1 -EjecutarDeVerdad`, que a su vez:
      1. comprueba que el tablero se actualizo HOY; si no, avisa y NO exporta
      2. si esta al dia, hace el flujo entero
      3. avisa del cierre, con las metricas sacadas del diario
      4. devuelve MODO_SIMULACION a true, pase lo que pase

.PARAMETER Hora
    Hora de disparo, formato HH:mm. Por defecto 09:00.

.PARAMETER Nombre
    Nombre de la tarea. Por defecto 'MoodleSinu-FlujoDiario'.

.PARAMETER Quitar
    Borra la tarea en vez de crearla.

.PARAMETER Simulacion
    Registra la tarea SIN -EjecutarDeVerdad. Recorre el flujo entero y avisa,
    pero no escribe en SINU. Es la forma sensata de estrenar el desatendido:
    un par de dias asi ensenan como se comporta antes de dejarle escribir.

.PARAMETER SoloMostrar
    Imprime lo que haria y no toca el Programador.

.EXAMPLE
    # Estreno prudente: unos dias en simulacion
    .\scripts\programar_9am.ps1 -Simulacion

.EXAMPLE
    # Produccion
    .\scripts\programar_9am.ps1

.EXAMPLE
    .\scripts\programar_9am.ps1 -Quitar
#>

[CmdletBinding()]
param(
    [string] $Hora = '09:00',
    [string] $Nombre = 'MoodleSinu-FlujoDiario',
    [switch] $Quitar,
    [switch] $Simulacion,
    [switch] $SoloMostrar
)

$ErrorActionPreference = 'Stop'
$raiz = Split-Path -Parent $PSScriptRoot

function Titulo($texto) {
    Write-Host ''
    Write-Host ('=' * 72) -ForegroundColor Cyan
    Write-Host $texto -ForegroundColor Cyan
    Write-Host ('=' * 72) -ForegroundColor Cyan
}

# --- Quitar -----------------------------------------------------------------
if ($Quitar) {
    Titulo "Quitando la tarea '$Nombre'"
    $existe = Get-ScheduledTask -TaskName $Nombre -ErrorAction SilentlyContinue
    if ($null -eq $existe) {
        Write-Host 'No estaba registrada. Nada que hacer.' -ForegroundColor Yellow
        exit 0
    }
    if ($SoloMostrar) {
        Write-Host "Se borraria la tarea '$Nombre'." -ForegroundColor Yellow
        exit 0
    }
    Unregister-ScheduledTask -TaskName $Nombre -Confirm:$false
    Write-Host "Tarea '$Nombre' borrada. El flujo ya NO corre solo." -ForegroundColor Green
    exit 0
}

# --- Comprobaciones previas -------------------------------------------------
$script = Join-Path $raiz 'scripts\dia_completo.ps1'
if (-not (Test-Path $script)) {
    Write-Host "ERROR: no existe $script" -ForegroundColor Red
    exit 1
}
if ($Hora -notmatch '^\d{1,2}:\d{2}$') {
    Write-Host "ERROR: -Hora debe ser HH:mm (recibido '$Hora')." -ForegroundColor Red
    exit 1
}

Titulo "Programando el flujo diario a las $Hora"

# El canal de aviso se comprueba AHORA. En desatendido, un flujo que no puede
# avisar es un flujo que falla en silencio, y eso es peor que no programarlo.
$py = Join-Path $raiz '.venv\Scripts\python.exe'
$tieneCanal = & $py -c "import sys; sys.path.insert(0,'src'); from moodle_sinu.config import Config; print(Config.desde_entorno().tiene_canal_de_aviso)"
if ($tieneCanal.Trim() -ne 'True') {
    Write-Host ''
    Write-Host 'ATENCION: no hay canal de notificacion configurado.' -ForegroundColor Red
    Write-Host 'La tarea correra, pero los avisos solo quedaran en logs\avisos\,' -ForegroundColor Yellow
    Write-Host 'que nadie mira a las 9:05. Para que el desatendido sirva de algo,' -ForegroundColor Yellow
    Write-Host 'anadir a config\.env UNA de estas dos cosas:' -ForegroundColor Yellow
    Write-Host ''
    Write-Host '  NOTIFICAR_WEBHOOK=https://<...>   # Teams o Slack, sin contrasenas' -ForegroundColor Cyan
    Write-Host ''
    Write-Host '  NOTIFICAR_SMTP_SERVIDOR=smtp.office365.com' -ForegroundColor Cyan
    Write-Host '  NOTIFICAR_SMTP_USUARIO=<cuenta>' -ForegroundColor Cyan
    Write-Host '  NOTIFICAR_SMTP_PASSWORD=<contrasena de aplicacion>' -ForegroundColor Cyan
    Write-Host '  NOTIFICAR_DESTINATARIOS=alguien@cun.edu.co' -ForegroundColor Cyan
    Write-Host ''
}

# --- La orden que ejecutara la tarea ----------------------------------------
$argumentos = @(
    '-NoProfile'
    '-ExecutionPolicy', 'Bypass'
    '-File', "`"$script`""
)
if (-not $Simulacion) { $argumentos += '-EjecutarDeVerdad' }

$linea = 'powershell.exe ' + ($argumentos -join ' ')
Write-Host ''
Write-Host 'La tarea ejecutara:' -ForegroundColor Cyan
Write-Host "  $linea"
Write-Host ''
if ($Simulacion) {
    Write-Host 'MODO SIMULACION: recorre y avisa, pero NO escribe en SINU.' -ForegroundColor Green
} else {
    Write-Host 'MODO REAL: modificara matriculas en SINU sin supervision.' -ForegroundColor Yellow
}

if ($SoloMostrar) {
    Write-Host ''
    Write-Host '(-SoloMostrar: no se toco el Programador de tareas)' -ForegroundColor Yellow
    exit 0
}

# --- Registro ---------------------------------------------------------------
$accion = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument ($argumentos -join ' ') -WorkingDirectory $raiz

$disparador = New-ScheduledTaskTrigger -Daily -At $Hora

# StartWhenAvailable: si el equipo estaba apagado a las 9:00, la tarea corre
# en cuanto arranque, en vez de saltarse el dia sin dejar rastro.
# DontStopIfGoingOnBatteries y AllowStartIfOnBatteries: en portatil, el
# defecto de Windows es NO arrancar sin corriente, y eso perderia el dia.
$ajustes = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 6) `
    -MultipleInstances IgnoreNew

# El flujo NECESITA sesion interactiva: la subida a Drive falla sin ventana
# (comprobado el 03/09/2026), y Chrome usa el perfil de este usuario. Por eso
# -LogonType Interactive y NO 'ejecutar aunque el usuario no haya iniciado
# sesion': con S4U el navegador no tiene escritorio y la subida se cae.
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

$existe = Get-ScheduledTask -TaskName $Nombre -ErrorAction SilentlyContinue
if ($null -ne $existe) {
    Write-Host ''
    Write-Host "La tarea '$Nombre' ya existia: se reemplaza." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $Nombre -Confirm:$false
}

Register-ScheduledTask -TaskName $Nombre -Action $accion -Trigger $disparador `
    -Settings $ajustes -Principal $principal `
    -Description ("Flujo diario Moodle-SINU. Comprueba que el tablero de Power BI " +
                  "se actualizo hoy; si no, avisa y no exporta. Ver README.") | Out-Null

Write-Host ''
Write-Host "Tarea '$Nombre' registrada para las $Hora, todos los dias." -ForegroundColor Green
Write-Host ''
Write-Host 'Comprobarla:' -ForegroundColor Cyan
Write-Host "  Get-ScheduledTask -TaskName '$Nombre' | Get-ScheduledTaskInfo"
Write-Host ''
Write-Host 'Lanzarla ahora, sin esperar a manana:' -ForegroundColor Cyan
Write-Host "  Start-ScheduledTask -TaskName '$Nombre'"
Write-Host ''
Write-Host 'Quitarla:' -ForegroundColor Cyan
Write-Host "  .\scripts\programar_9am.ps1 -Quitar"
Write-Host ''
Write-Host 'IMPORTANTE: el equipo tiene que estar encendido y con la sesion de' -ForegroundColor Yellow
Write-Host $env:USERNAME -ForegroundColor Yellow -NoNewline
Write-Host ' iniciada. El flujo abre Chrome con ventana porque la subida' -ForegroundColor Yellow
Write-Host 'a Drive no funciona sin escritorio.' -ForegroundColor Yellow
