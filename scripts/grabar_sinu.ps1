<#
.SYNOPSIS
    Graba el flujo de ISEF07 para extraer los selectores reales.

.DESCRIPTION
    Los selectores de `selectores_sinu.py` estan SIN VERIFICAR: se derivaron de
    la descripcion del proceso en la skill de negocio, no de una grabacion.

    Sobre la sesion: `playwright codegen` NO acepta `--user-data-dir` -- eso es
    un parametro de `launch_persistent_context` en la API, no del CLI. Y sin
    perfil, codegen abre un navegador aislado y en blanco, sin sesiones.

    Por eso esto no llama al CLI: delega en `scripts/grabar.py`, que usa
    `launch_persistent_context` con el perfil real y `channel="chrome"`, de modo
    que el navegador abre tal como lo ve el usuario, con sus sesiones vivas.

    Que hay que grabar, en este orden (SOLO LECTURA, no ejecutar nada):
      1. Fijar el filtro de Periodo (arriba a la derecha).
      2. En la grilla Estudiantes: triple-clic en el filtro de la columna
         "No. Identificacion", escribir una cedula, Enter.
      3. Clic en la fila del estudiante, para que cargue la grilla Grupos.
      4. Pasar el raton por las columnas "Curso en moodle?" y "Vinculado?"
         para que queden en la grabacion.
      5. PARAR AHI. No tocar "Accion a realizar" ni el icono de ejecutar:
         eso es la etapa 4 y no se graba en esta pasada.

    IMPORTANTE: codegen escribe en el script generado todo lo que se teclee.
    Si hay que iniciar sesion a mano, la contrasena queda ahi en claro. El
    archivo esta en .gitignore; extraer los selectores y borrarlo.

.EXAMPLE
    .\scripts\grabar_sinu.ps1
    .\scripts\grabar_sinu.ps1 -SoloComprobar
#>

[CmdletBinding()]
param(
    [string] $Salida = "sinu_grabado.py",

    # 'chrome' (el perfil personal), 'proyecto' (POWERBI_PERFIL_NAVEGADOR) o
    # una ruta explicita. Sin especificar manda NAVEGADOR_PERFIL de config\.env:
    # la grabacion tiene que abrir el MISMO perfil que el robot, o lo que se
    # grabe no sera lo que el vea (cambian favoritos y sesiones).
    [string] $Perfil = '',

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

Write-Host '=== Grabacion del flujo de ISEF07 (etapa 3) ===' -ForegroundColor Cyan
Write-Host ''

if (-not (Test-Path $python)) {
    Write-Host "ERROR: no existe $python" -ForegroundColor Red
    exit 1
}

$url = Valor-Env 'SINU_URL'
if ([string]::IsNullOrWhiteSpace($url)) { $url = 'https://sigwt.cun.edu.co/sgacampus' }
# La barra final importa: sin ella Tomcat puede responder 404.
if (-not $url.EndsWith('/')) { $url = "$url/" }
$idioma = Valor-Env 'POWERBI_IDIOMA'
if ([string]::IsNullOrWhiteSpace($idioma)) { $idioma = 'es-CO' }

Write-Host "[ok] URL    : $url"
Write-Host "[ok] Idioma : $idioma"

# --- Perfil persistente con sesiones abiertas -----------------------------
# No se usa el CLI de codegen: no admite --user-data-dir, asi que abriria un
# navegador en blanco. scripts/grabar.py usa launch_persistent_context.
$perfilEfectivo = $Perfil
if ([string]::IsNullOrWhiteSpace($perfilEfectivo)) {
    $perfilEfectivo = Valor-Env 'NAVEGADOR_PERFIL'
    if ([string]::IsNullOrWhiteSpace($perfilEfectivo)) { $perfilEfectivo = 'chrome' }
}

if ($perfilEfectivo -eq 'proyecto') {
    $rutaPerfil = Valor-Env 'POWERBI_PERFIL_NAVEGADOR'
    if ([string]::IsNullOrWhiteSpace($rutaPerfil)) {
        Fallar "POWERBI_PERFIL_NAVEGADOR esta vacio en config\.env. Rellenarlo, o usar -Perfil chrome."
    }
    Write-Host "[ok] Perfil  : $rutaPerfil (dedicado a la automatizacion)"
}
elseif ($perfilEfectivo -eq 'chrome') {
    Write-Host '[ok] Perfil  : el Chrome PERSONAL del usuario'
    $procesos = @(Get-Process chrome -ErrorAction SilentlyContinue)
    if ($procesos.Count -gt 0) {
        Write-Host ''
        Write-Host "[!] Chrome esta abierto ($($procesos.Count) procesos) y bloquea su perfil." -ForegroundColor Yellow
        Write-Host '    Cerrarlo por completo antes de grabar, o usar -Perfil proyecto.' -ForegroundColor Yellow
    }
}
else {
    Write-Host "[ok] Perfil  : $perfilEfectivo"
}
Write-Host "[ok] Canal   : $Canal"

$salidaCompleta = Join-Path $raiz $Salida
$argumentos = @(
    (Join-Path $raiz 'scripts\grabar.py'),
    $url,
    '--canal', $Canal,
    '--idioma', $idioma,
    '--salida', $salidaCompleta,
    '--sinu'
)
# Sin -Perfil no se pasa la opcion, y grabar.py toma NAVEGADOR_PERFIL.
if (-not [string]::IsNullOrWhiteSpace($Perfil)) {
    $argumentos += @('--perfil', $Perfil)
}

Write-Host ''
Write-Host 'Que grabar (SOLO LECTURA):' -ForegroundColor Cyan
Write-Host '  1. Fijar el filtro de Periodo.'
Write-Host '  2. Triple-clic en el filtro de "No. Identificacion", cedula, Enter.'
Write-Host '  3. Clic en la fila del estudiante (carga la grilla Grupos).'
Write-Host '  4. Recorrer las columnas "Curso en moodle?" y "Vinculado?".'
Write-Host ''
Write-Host '  NO tocar "Accion a realizar" ni el icono de ejecutar.' -ForegroundColor Yellow
Write-Host '  Eso es la etapa 4 y no se graba aqui.' -ForegroundColor Yellow
Write-Host ''
Write-Host "Salida: $salidaCompleta"
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
    Write-Host "=== El grabador termino con codigo $codigo ===" -ForegroundColor Yellow
}

exit $codigo
