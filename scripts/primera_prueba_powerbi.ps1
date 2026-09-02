<#
.SYNOPSIS
    Primera prueba visual de la etapa 1: exportacion desde Power BI.

.DESCRIPTION
    Ejecuta la exportacion con ventana visible, traza y captura del dialogo, y
    con el perfil de navegador persistente para que el segundo factor se
    resuelva una sola vez.

    Comprueba antes de arrancar lo que suele fallar: el .venv, la contrasena
    en config/.env y el directorio del perfil. Es preferible avisar aqui que
    despues de abrir Chromium.

    Compatible con Windows PowerShell 5.1 (sin '&&' ni operador ternario).

.EXAMPLE
    .\scripts\primera_prueba_powerbi.ps1
#>

[CmdletBinding()]
param(
    # Ruta del .xlsx de salida. Por defecto, data\raw\ con sello temporal.
    [string] $Salida,

    # Repite la prueba sin ventana, una vez validada en pantalla.
    [switch] $SinVentana,

    # Solo valida la configuracion y muestra el comando; no abre el navegador.
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

Write-Host '=== Etapa 1: primera prueba de exportacion desde Power BI ===' -ForegroundColor Cyan
Write-Host ''

# --- 1. Entorno -----------------------------------------------------------
if (-not (Test-Path $python)) {
    Fallar "No existe $python. Crear el entorno primero (ver README, 'Instalacion')."
}
Write-Host "[ok] Entorno virtual: $python"

if (-not (Test-Path $env_file)) {
    Fallar "No existe $env_file. Copiar config\.env.example y rellenarlo."
}
Write-Host "[ok] Configuracion: $env_file"

# --- 2. Credenciales ------------------------------------------------------
# Solo se comprueba que existan; el valor no se imprime nunca.
$lineas = Get-Content $env_file -Encoding UTF8

function Valor-Env($clave) {
    $linea = $lineas | Where-Object { $_ -match "^\s*$clave\s*=" } | Select-Object -First 1
    if ($null -eq $linea) { return '' }
    return ($linea -replace "^\s*$clave\s*=", '').Trim()
}

$usuario = Valor-Env 'POWERBI_USUARIO'
$password = Valor-Env 'POWERBI_PASSWORD'
$perfil = Valor-Env 'POWERBI_PERFIL_NAVEGADOR'
$url_informe = Valor-Env 'POWERBI_URL_INFORME'

if ([string]::IsNullOrWhiteSpace($usuario)) {
    Fallar "POWERBI_USUARIO esta vacio en config\.env."
}
Write-Host "[ok] Usuario: $usuario"

if ([string]::IsNullOrWhiteSpace($password)) {
    Fallar @'
POWERBI_PASSWORD esta vacio en config\.env.

La contrasena anterior quedo expuesta en la grabacion de codegen (archivo ya
borrado) y debe considerarse comprometida. Rotarla en la cuenta y escribir la
nueva en config\.env antes de ejecutar esta prueba.
'@
}
Write-Host '[ok] Contrasena presente (no se muestra)'

# --- 3. Perfil persistente ------------------------------------------------
if ([string]::IsNullOrWhiteSpace($perfil)) {
    Write-Host '[!] POWERBI_PERFIL_NAVEGADOR esta vacio: la sesion NO se guardara' -ForegroundColor Yellow
    Write-Host '    y habra que repetir el login (y el MFA) en cada corrida.' -ForegroundColor Yellow
}
else {
    if (-not (Test-Path $perfil)) {
        New-Item -ItemType Directory -Force -Path $perfil | Out-Null
        Write-Host "[ok] Perfil creado: $perfil"
    }
    else {
        Write-Host "[ok] Perfil existente: $perfil (la sesion puede estar viva)"
    }
    if ($perfil.StartsWith($raiz, [System.StringComparison]::OrdinalIgnoreCase)) {
        Write-Host '[!] El perfil esta DENTRO del repo: guarda cookies de sesion.' -ForegroundColor Yellow
        Write-Host '    Conviene moverlo fuera antes de versionar nada.' -ForegroundColor Yellow
    }
}

# --- 4. Camino hasta el informe -------------------------------------------
if ([string]::IsNullOrWhiteSpace($url_informe)) {
    Write-Host '[!] POWERBI_URL_INFORME esta vacio: se navegara por la UI, que' -ForegroundColor Yellow
    Write-Host '    depende del idioma de la cuenta. Tras esta prueba, copiar la' -ForegroundColor Yellow
    Write-Host '    URL del informe desde la barra de direcciones a config\.env.' -ForegroundColor Yellow
}
else {
    Write-Host '[ok] Se abrira el informe por URL directa'
}

# --- 5. Ejecucion ---------------------------------------------------------
$argumentos = @((Join-Path $raiz 'scripts\exportar_reporte.py'), '--traza', '--captura', '--verbose')
if ($SinVentana) {
    $argumentos += '--headless'
}
else {
    $argumentos += '--visible'
}
if (-not [string]::IsNullOrWhiteSpace($Salida)) {
    $argumentos += @('--salida', $Salida)
}

if ($SoloComprobar) {
    Write-Host ''
    Write-Host '=== Comprobacion superada; no se ejecuto nada ===' -ForegroundColor Green
    Write-Host "Comando que se lanzaria: python $($argumentos -join ' ')"
    exit 0
}

Write-Host ''
Write-Host 'Que mirar mientras corre:' -ForegroundColor Cyan
Write-Host '  1. El login del SSO y el dialogo "Mantener la sesion iniciada".'
Write-Host '  2. Que en el dialogo de exportacion quede marcado'
Write-Host '     "Datos con diseno actual" (ese paso no venia en la grabacion).'
Write-Host '  3. Cualquier linea "!" del resumen final: son pasos sin confirmar.'
Write-Host ''
Write-Host "Ejecutando: python $($argumentos -join ' ')" -ForegroundColor DarkGray
Write-Host ''

& $python @argumentos
$codigo = $LASTEXITCODE

Write-Host ''
if ($codigo -eq 0) {
    Write-Host '=== Exportacion completada ===' -ForegroundColor Green
    Write-Host 'Revisar la captura del dialogo que aparece arriba para confirmar'
    Write-Host 'que la opcion "Datos con diseno actual" estaba seleccionada, y que'
    Write-Host 'el .xlsx trae las 15 columnas y el pie "Filtros aplicados:".'
    Write-Host ''
    Write-Host 'Cuando la prueba pase, poner POWERBI_HEADLESS=true en config\.env'
    Write-Host 'para las corridas diarias desatendidas.'
}
else {
    Write-Host "=== Exportacion fallida (codigo $codigo) ===" -ForegroundColor Red
    Write-Host 'Abrir la traza para ver en que paso se detuvo:'
    Write-Host "  & '$python' -m playwright show-trace logs\traza_powerbi_<sello>.zip"
}

exit $codigo
