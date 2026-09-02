<#
.SYNOPSIS
    Graba el flujo de subida en Google Drive para extraer los selectores reales.

.DESCRIPTION
    Los selectores de `selectores_drive.py` estan SIN VERIFICAR: se dedujeron de
    la estructura conocida de la UI de Drive, no de una grabacion.

    Sobre la sesion: `playwright codegen` NO acepta `--user-data-dir` -- eso es
    un parametro de `launch_persistent_context` en la API, no del CLI. Y sin
    perfil, codegen abre un navegador aislado y en blanco, sin sesiones.

    Por eso esto no llama al CLI: delega en `scripts/grabar.py`, que usa
    `launch_persistent_context` con el perfil real y `channel="chrome"`, de modo
    que el navegador abre tal como lo ve el usuario, con sus sesiones vivas.

    OJO con la sesion de Google: el perfil dedicado (-Perfil proyecto) se creo
    para Power BI y NO tiene sesion de Google (comprobado el 21/08/2026: Drive
    devolvia 404). Para Drive hay dos caminos: iniciar sesion una vez en ese
    perfil, o usar -Perfil chrome con Chrome cerrado.

    Que hay que grabar, en este orden:
      1. Entrar en la carpeta del mes (o crearla con Nuevo -> Nueva carpeta).
      2. Nuevo -> Subir archivo, y elegir un .xlsx de prueba.
      3. Si el archivo NO queda como Sheet: clic derecho -> Abrir con ->
         Hojas de calculo de Google -> Archivo -> Guardar como Hojas de calculo.
      4. Clic derecho -> Cambiar nombre -> escribir 'REPORTE 21/08/2026 #999'.
      5. Borrar el archivo de prueba a mano al terminar.

    IMPORTANTE: codegen escribe en el script generado todo lo que se teclee. El
    archivo esta en .gitignore; extraer los selectores y borrarlo.

.EXAMPLE
    .\scripts\grabar_drive.ps1
    .\scripts\grabar_drive.ps1 -SoloComprobar
#>

[CmdletBinding()]
param(
    # Carpeta donde empezar. Por defecto, la raiz de GOOGLE_CARPETA_RAIZ_ID.
    [string] $IdCarpeta,

    # Archivo de salida de la grabacion.
    [string] $Salida = "drive_grabado.py",

    # 'proyecto' (POWERBI_PERFIL_NAVEGADOR), 'chrome' (el perfil real de
    # Chrome del usuario) o una ruta explicita.
    [string] $Perfil = 'proyecto',

    # Navegador a abrir. 'chrome' usa el Chrome instalado.
    [ValidateSet('chrome','chrome-beta','msedge','chromium')]
    [string] $Canal = 'chrome',

    # Muestra el comando que se lanzaria y no abre nada.
    [switch] $SoloComprobar
)

$ErrorActionPreference = 'Stop'

$raiz = Split-Path -Parent $PSScriptRoot
$python = Join-Path $raiz '.venv\Scripts\python.exe'
$env_file = Join-Path $raiz 'config\.env'

function Fallar($mensaje) {
    Write-Host ''
    Write-Host "ERROR: $mensaje" -ForegroundColor Red
    exit 1
}

function Valor-Env($clave) {
    if (-not (Test-Path $env_file)) { return '' }
    $lineas = Get-Content $env_file -Encoding UTF8
    $linea = $lineas | Where-Object { $_ -match "^\s*$clave\s*=" } | Select-Object -First 1
    if ($null -eq $linea) { return '' }
    return ($linea -replace "^\s*$clave\s*=", '').Trim()
}

Write-Host '=== Grabacion del flujo de Google Drive (etapa 2) ===' -ForegroundColor Cyan
Write-Host ''

if (-not (Test-Path $python)) {
    Fallar "No existe $python. Crear el entorno primero (ver README)."
}

if ([string]::IsNullOrWhiteSpace($IdCarpeta)) {
    $IdCarpeta = Valor-Env 'GOOGLE_CARPETA_RAIZ_ID'
}
if ([string]::IsNullOrWhiteSpace($IdCarpeta)) {
    Fallar "No hay GOOGLE_CARPETA_RAIZ_ID en config\.env ni se paso -IdCarpeta."
}

$idioma = Valor-Env 'POWERBI_IDIOMA'
if ([string]::IsNullOrWhiteSpace($idioma)) { $idioma = 'es-CO' }

$url = "https://drive.google.com/drive/folders/$IdCarpeta"
Write-Host "[ok] Carpeta : $url"
Write-Host "[ok] Idioma  : $idioma"

# --- Perfil persistente con sesiones abiertas -----------------------------
# No se usa el CLI de codegen: no admite --user-data-dir, asi que abriria un
# navegador en blanco. scripts/grabar.py usa launch_persistent_context.
if ($Perfil -eq 'proyecto') {
    $rutaPerfil = Valor-Env 'POWERBI_PERFIL_NAVEGADOR'
    if ([string]::IsNullOrWhiteSpace($rutaPerfil)) {
        Fallar "POWERBI_PERFIL_NAVEGADOR esta vacio en config\.env. Rellenarlo, o usar -Perfil chrome."
    }
    Write-Host "[ok] Perfil  : $rutaPerfil (dedicado a la automatizacion)"
    Write-Host '[!] Ese perfil se creo para Power BI y puede NO tener sesion de' -ForegroundColor Yellow
    Write-Host '    Google. Si Drive responde 404, iniciar sesion en la ventana' -ForegroundColor Yellow
    Write-Host '    que se abre, o usar -Perfil chrome con Chrome cerrado.' -ForegroundColor Yellow
}
elseif ($Perfil -eq 'chrome') {
    Write-Host "[ok] Perfil  : el Chrome real del usuario (con su sesion de Google)"
    $procesos = @(Get-Process chrome -ErrorAction SilentlyContinue)
    if ($procesos.Count -gt 0) {
        Write-Host ''
        Write-Host "[!] Chrome esta abierto ($($procesos.Count) procesos) y bloquea su perfil." -ForegroundColor Yellow
        Write-Host '    Cerrarlo por completo antes de grabar, o usar -Perfil proyecto.' -ForegroundColor Yellow
    }
}
else {
    Write-Host "[ok] Perfil  : $Perfil"
}
Write-Host "[ok] Canal   : $Canal"

$salidaCompleta = Join-Path $raiz $Salida
$argumentos = @(
    (Join-Path $raiz 'scripts\grabar.py'),
    $url,
    '--perfil', $Perfil,
    '--canal', $Canal,
    '--idioma', $idioma,
    '--salida', $salidaCompleta
)

Write-Host ''
Write-Host 'Que grabar, en este orden:' -ForegroundColor Cyan
Write-Host '  1. Entrar en la carpeta del mes (o crearla).'
Write-Host '  2. Nuevo -> Subir archivo, y elegir un .xlsx de prueba.'
Write-Host '  3. Si NO queda como Sheet: clic derecho -> Abrir con -> Hojas de'
Write-Host '     calculo de Google -> Archivo -> Guardar como Hojas de calculo.'
Write-Host '  4. Clic derecho -> Cambiar nombre -> REPORTE 21/08/2026 #999'
Write-Host ''
Write-Host "Salida: $salidaCompleta"
Write-Host 'Despues: borrar el archivo de prueba de Drive.'
Write-Host ''

if ($SoloComprobar) {
    Write-Host '=== Comprobacion; no se ejecuto nada ===' -ForegroundColor Green
    Write-Host "Comando: python $($argumentos -join ' ')"
    exit 0
}

& $python @argumentos
$codigo = $LASTEXITCODE

Write-Host ''
if ((Test-Path $salidaCompleta) -and ($codigo -eq 0)) {
    Write-Host "=== Grabacion guardada en $salidaCompleta ===" -ForegroundColor Green
    Write-Host 'Esta en .gitignore. Extraer los selectores y borrarla.'
}
else {
    Write-Host "=== El grabador termino con codigo $codigo y sin archivo ===" -ForegroundColor Yellow
}

exit $codigo
