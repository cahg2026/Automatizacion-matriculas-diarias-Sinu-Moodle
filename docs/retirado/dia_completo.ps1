<#
.SYNOPSIS
    Flujo completo del dia, de Power BI a la columna de gestion en el Sheet.

.DESCRIPTION
    Encadena las cinco etapas sin que haya que copiar valores de una salida a la
    siguiente, que es lo que convertia el proceso diario en algo manual:

      1. Power BI  -> descarga el tablero a data\raw\
      2. Fase 1    -> marca calidad, ordena A-Z por periodo, sube el Sheet
      3. ISEF07    -> procesa las matriculas, periodo por periodo
      4. Gestion   -> escribe el resultado por fila y sube el Sheet marcado
      5. Cierre    -> revisa ciclos a medias y devuelve el cerrojo

    Los valores intermedios NO se piden ni se parsean a mano:

    - El .xlsx descargado y la copia coloreada se localizan por fecha de
      modificacion dentro de data\raw\ y data\processed\. Mas fiable que leer
      rutas de un log, que cambian de formato.
    - 'NO MATRICULADO' NO se pasa: `subir_reporte.py` cuenta las filas del
      .xlsx cuando falta, y cuentan lo mismo -- la vista de Power BI ya viene
      filtrada a VALIDACION != MATRICULADO. Un dato menos que teclear.
    - La URL del Sheet es lo unico que hay que leer de una salida. Si no
      aparece, el script se detiene y lo dice, en vez de seguir sin ella.

.PARAMETER EjecutarDeVerdad
    Modifica matriculas en SINU. Sin esto, las etapas 3 y 4 solo informan.

    Este parametro abre el cerrojo `MODO_SIMULACION` al empezar y lo CIERRA al
    terminar, pase lo que pase. Es deliberado: tener que editar el .env a mano
    cada manana y acordarse de revertirlo por la noche es justo como se queda
    abierto sin que nadie lo note. Aqui la decision es un flag explicito y el
    archivo vuelve a su estado seguro solo.

.PARAMETER Reporte
    Salta la etapa 1 y usa este .xlsx. Para reanudar sin volver a bajar el
    tablero.

.PARAMETER SheetUrl
    Salta las etapas 1 y 2 y usa este Sheet. Para reanudar cuando el reporte ya
    esta subido.

.PARAMETER HastaSubir
    Se detiene despues de subir el Sheet, sin tocar SINU.

.PARAMETER SinRotarDiario
    No rota `logs\resultados_etapa4.jsonl`.

    Por defecto SI se rota, y conviene: `--saltar-hechas` compara por
    (periodo, cedula, materia) sin mirar la fecha, asi que con el diario de
    ayer dentro saltaria unidades de hoy creyendolas hechas. Rotandolo, el
    diario del dia empieza limpio y reanudar es seguro.

.PARAMETER Periodos
    Solo estos periodos, separados por coma. Para retomar los que fallaron.

.EXAMPLE
    # El dia completo, de verdad
    .\scripts\dia_completo.ps1 -EjecutarDeVerdad

.EXAMPLE
    # Ensayo: recorre todo y dice que haria, sin escribir
    .\scripts\dia_completo.ps1

.EXAMPLE
    # Reanudar con el Sheet ya subido, solo dos periodos
    .\scripts\dia_completo.ps1 -EjecutarDeVerdad `
        -SheetUrl "https://docs.google.com/spreadsheets/d/xxx/edit" `
        -Reporte "data\processed\reporte_..._validado_....xlsx" `
        -Periodos "26V05,2026D"
#>

[CmdletBinding()]
param(
    [switch] $EjecutarDeVerdad,
    [string] $Reporte = "",
    [string] $SheetUrl = "",
    [switch] $HastaSubir,
    [switch] $SinRotarDiario,
    [string] $Periodos = "",
    [switch] $SinVerificarActualizacion,
    [switch] $SinAvisar
)

$ErrorActionPreference = 'Stop'
$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz

$py = Join-Path $raiz '.venv\Scripts\python.exe'
$env_file = Join-Path $raiz 'config\.env'
$sello = Get-Date -Format 'yyyyMMdd_HHmmss'
$bitacora = Join-Path $raiz "logs\dia_completo_$sello.log"

function Titulo($texto) {
    Write-Host ''
    Write-Host ('=' * 72) -ForegroundColor Cyan
    Write-Host $texto -ForegroundColor Cyan
    Write-Host ('=' * 72) -ForegroundColor Cyan
}

function Registrar {
    # Sustituye a `Tee-Object`: en PowerShell 5.1 este NO acepta -Encoding y
    # escribe UTF-16, con lo que la bitacora sale ilegible en un editor o en
    # `grep`. Esto deja pasar la linea tal cual y la anade en UTF-8.
    param([Parameter(ValueFromPipeline = $true)] $linea)
    process {
        if ($null -eq $linea) { $texto = '' } else { $texto = [string]$linea }
        Add-Content -Path $bitacora -Value $texto -Encoding UTF8
        $texto
    }
}

function Fallar($mensaje) {
    Write-Host ''
    Write-Host "ERROR: $mensaje" -ForegroundColor Red
    Write-Host "Bitacora: $bitacora" -ForegroundColor Yellow
    exit 1
}

function MasReciente($carpeta, $patron) {
    if (-not (Test-Path $carpeta)) { return $null }
    $f = Get-ChildItem -Path $carpeta -Filter $patron -File -ErrorAction SilentlyContinue |
         Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($null -eq $f) { return $null }
    return $f.FullName
}

function FijarSimulacion($valor) {
    # $valor: 'true' o 'false'
    if (-not (Test-Path $env_file)) { return }
    $lineas = Get-Content $env_file -Encoding UTF8
    $nuevas = $lineas | ForEach-Object {
        if ($_ -match '^\s*MODO_SIMULACION\s*=') { "MODO_SIMULACION=$valor" } else { $_ }
    }
    Set-Content -Path $env_file -Value $nuevas -Encoding UTF8
}

function LeerSimulacion() {
    if (-not (Test-Path $env_file)) { return '(sin .env)' }
    $l = Get-Content $env_file -Encoding UTF8 |
         Where-Object { $_ -match '^\s*MODO_SIMULACION\s*=' } | Select-Object -First 1
    if ($null -eq $l) { return '(no definido)' }
    return ($l -replace '^\s*MODO_SIMULACION\s*=', '').Trim()
}

# --- Comprobaciones previas -------------------------------------------------
if (-not (Test-Path $py)) {
    Fallar "No existe $py. Rehacer el entorno: ver la seccion Instalacion del README."
}
New-Item -ItemType Directory -Force (Join-Path $raiz 'logs') | Out-Null

Titulo "FLUJO DEL DIA - $(Get-Date -Format 'dd/MM/yyyy HH:mm')"
if ($EjecutarDeVerdad) {
    Write-Host 'Modo   : EJECUCION REAL (se modificaran matriculas en SINU)' -ForegroundColor Yellow
} else {
    Write-Host 'Modo   : SIMULACION (no se toca nada)' -ForegroundColor Green
}
Write-Host "Bitacora: $bitacora"
Write-Host "MODO_SIMULACION en .env, antes de empezar: $(LeerSimulacion)"

$simulacionOriginal = LeerSimulacion

# Distinguen las tres formas de acabar, que el `finally` no puede diferenciar
# por si solo:
#   llego al final            -> $flujoCompleto  = $true   (ya aviso)
#   salida prevista y avisada -> $avisoNoHaceFalta = $true  (el cerrojo aviso)
#   revento a mitad           -> ninguna de las dos        -> avisar del fallo
$flujoCompleto = $false
$avisoNoHaceFalta = $false

try {
    if ($EjecutarDeVerdad) {
        FijarSimulacion 'false'
        Write-Host 'Cerrojo MODO_SIMULACION abierto para esta corrida.' -ForegroundColor Yellow
    } else {
        FijarSimulacion 'true'
    }

    # --- Etapa 0: el perfil de navegador ------------------------------------
    Titulo 'PASO 0/6 - Perfil de navegador'
    & $py scripts\probar_perfil.py | Registrar
    if ($LASTEXITCODE -ne 0) {
        Fallar 'El perfil de navegador no se pudo abrir. Ver la salida de arriba.'
    }

    # --- Etapa 1: el cerrojo del dia ----------------------------------------
    # Solo cuando se va a exportar. Al reanudar con -SheetUrl el tablero ya se
    # valido en la corrida original, y volver a mirarlo daria un resultado
    # distinto si se refresco entre medias: se estaria validando otro dato del
    # que se va a procesar.
    if (-not $SinVerificarActualizacion -and
        [string]::IsNullOrWhiteSpace($SheetUrl) -and
        [string]::IsNullOrWhiteSpace($Reporte)) {

        Titulo 'PASO 1/6 - Cerrojo: se actualizo el tablero hoy?'
        $ordenCerrojo = @('scriptserificar_actualizacion.py')
        if ($SinAvisar) { $ordenCerrojo += '--sin-avisar' }
        & $py @ordenCerrojo | Registrar
        $codigoCerrojo = $LASTEXITCODE

        # 3 y 4 son desenlaces previstos, no averias: el guardian ya aviso y
        # ya explico. Salir con 0 es deliberado -- el Programador de tareas
        # marcaria en rojo un dia que se resolvio como debia.
        if ($codigoCerrojo -eq 3) {
            Titulo 'DETENIDO: el tablero no se actualizo hoy'
            Write-Host 'No se exporto nada y no se toco SINU.' -ForegroundColor Yellow
            Write-Host 'Alerta enviada (o dejada en logsvisos\).' -ForegroundColor Yellow
            Write-Host ''
            Write-Host 'Cuando el tablero este al dia:' -ForegroundColor Cyan
            Write-Host '  .\scripts\dia_completo.ps1 -EjecutarDeVerdad'
            $avisoNoHaceFalta = $true   # el cerrojo ya mando la alerta
            exit 0
        }
        if ($codigoCerrojo -eq 4) {
            Titulo 'DETENIDO: no se pudo leer la fecha del tablero'
            Write-Host 'Ojo: NO es lo mismo que un tablero viejo. La comprobacion' -ForegroundColor Yellow
            Write-Host 'en si fallo, probablemente porque el tablero cambio de forma.' -ForegroundColor Yellow
            Write-Host ''
            Write-Host 'Para verlo:' -ForegroundColor Cyan
            Write-Host '  python scripts\sondear_actualizacion.py --visible'
            $avisoNoHaceFalta = $true   # el cerrojo ya mando la alerta
            exit 0
        }
        if ($codigoCerrojo -ne 0) { Fallar 'El cerrojo del dia fallo tecnicamente.' }
    }
    elseif (-not $SinVerificarActualizacion) {
        Write-Host ''
        Write-Host 'Cerrojo omitido: se reanuda sobre un reporte ya exportado.' -ForegroundColor Yellow
    }

    # --- Etapa 1: Power BI ---------------------------------------------------
    if ([string]::IsNullOrWhiteSpace($SheetUrl) -and [string]::IsNullOrWhiteSpace($Reporte)) {
        Titulo 'PASO 2/6 - Power BI: descarga del tablero'
        & $py scripts\exportar_reporte.py --captura -v | Registrar
        if ($LASTEXITCODE -ne 0) { Fallar 'La exportacion de Power BI fallo.' }

        $Reporte = MasReciente (Join-Path $raiz 'data\raw') '*.xlsx'
        if ($null -eq $Reporte) { Fallar 'No aparecio ningun .xlsx en data\raw.' }
        Write-Host "Reporte descargado: $Reporte" -ForegroundColor Green
    }

    # --- Etapa 2: Fase 1 + subida a Drive -----------------------------------
    $validado = ''
    if ([string]::IsNullOrWhiteSpace($SheetUrl)) {
        Titulo 'PASO 3/6 - Limpieza, orden A-Z y subida del Sheet'
        Write-Host 'Con ventana a proposito: la subida a Drive falla en headless.' -ForegroundColor Yellow

        # `--no-matriculado` se omite: sin el, subir_reporte cuenta las filas del
        # .xlsx, que es el mismo numero. Un dato menos que copiar a mano.
        $salida = & $py scripts\subir_reporte.py "$Reporte" --visible --traza -v | Registrar
        if ($LASTEXITCODE -ne 0) { Fallar 'La subida a Drive fallo.' }

        $linea = $salida | Where-Object { $_ -match 'docs\.google\.com/spreadsheets/d/' } |
                 Select-Object -First 1
        if ($null -eq $linea) {
            Fallar ("La subida no informo de la URL del Sheet. Buscarla en Drive y " +
                    "relanzar con -SheetUrl '<url>' -Reporte '<copia coloreada>'.")
        }
        $SheetUrl = ([regex]'https://docs\.google\.com/spreadsheets/d/[A-Za-z0-9_-]+').Match($linea).Value
        Write-Host "Sheet del dia: $SheetUrl" -ForegroundColor Green

        $validado = MasReciente (Join-Path $raiz 'data\processed') '*_validado_*.xlsx'
        if ($null -eq $validado) { Fallar 'No aparecio la copia coloreada en data\processed.' }
    } else {
        Write-Host "Se usa el Sheet indicado: $SheetUrl" -ForegroundColor Yellow
        $validado = $Reporte
    }

    # La copia COLOREADA es la que se pasa a las etapas 3 y 4: sus numeros de
    # fila son los que coinciden con el Sheet, y de ahi sale el marcado. Con el
    # .xlsx crudo las filas no cuadran y la gestion se escribiria desplazada.
    if ([string]::IsNullOrWhiteSpace($validado)) {
        Fallar 'No se pudo determinar la copia coloreada. Pasarla con -Reporte.'
    }
    Write-Host "Archivo de trabajo: $validado" -ForegroundColor Green

    if ($HastaSubir) {
        Titulo 'DETENIDO EN EL PASO 3 (-HastaSubir)'
        Write-Host "Sheet   : $SheetUrl"
        Write-Host "Archivo : $validado"
        Write-Host ''
        Write-Host 'Para seguir mas tarde:' -ForegroundColor Cyan
        Write-Host ("  .\scripts\dia_completo.ps1 -EjecutarDeVerdad -SheetUrl '{0}' -Reporte '{1}'" -f $SheetUrl, $validado)
        $avisoNoHaceFalta = $true   # parada pedida a proposito, no un fallo
        exit 0
    }

    # --- Rotacion del diario ------------------------------------------------
    # Aqui y no al principio: si la corrida se detiene en -HastaSubir nunca se
    # llega a la etapa 4, y rotar el diario seria mover un archivo por nada.
    $diario = Join-Path $raiz 'logs\resultados_etapa4.jsonl'
    if ((Test-Path $diario) -and (-not $SinRotarDiario)) {
        $dia_diario = (Get-Item $diario).LastWriteTime.ToString('yyyyMMdd')
        $hoy = (Get-Date).ToString('yyyyMMdd')
        if ($dia_diario -ne $hoy) {
            $destino = Join-Path $raiz "logs\resultados_etapa4_$dia_diario.jsonl"
            Move-Item $diario $destino -Force
            Write-Host "Diario rotado: $(Split-Path -Leaf $destino)" -ForegroundColor Yellow
        }
    }

    # --- Etapa 3: ISEF07 -----------------------------------------------------
    Titulo 'PASO 4/6 - Procesar las matriculas en ISEF07'
    Write-Host 'NO uses SINU mientras corre: la automatizacion entra con la misma cuenta.' -ForegroundColor Yellow

    # `--saltar-hechas` va SIEMPRE, y es seguro porque el diario se acaba de
    # rotar: solo puede contener verdes de HOY. Es lo que hace que reanudar una
    # corrida cortada a mitad no repita materias ya vinculadas.
    $orden3 = @("scripts\procesar_dia.py", "$validado", "--sheet-url", "$SheetUrl",
                "--saltar-hechas", "-v")
    if ($EjecutarDeVerdad) { $orden3 += '--ejecutar-de-verdad' }
    if (-not [string]::IsNullOrWhiteSpace($Periodos)) {
        foreach ($p in $Periodos.Split(',')) {
            $t = $p.Trim()
            if ($t) { $orden3 += @('--solo', $t) }
        }
    }
    & $py @orden3 | Registrar
    $codigo3 = $LASTEXITCODE
    if ($codigo3 -ne 0) {
        Write-Host ''
        Write-Host 'Algun periodo fallo. Se continua con la gestion y el cierre: lo hecho' -ForegroundColor Yellow
        Write-Host 'hasta ahora hay que marcarlo y revisarlo igual.' -ForegroundColor Yellow
    }

    # --- Etapa 4: marcar la gestion -----------------------------------------
    Titulo 'PASO 5/6 - Marcar la gestion en el Sheet'
    $orden4 = @("scripts\marcar_gestion.py", "$validado", "-v")
    if ($EjecutarDeVerdad) { $orden4 += @('--subir', '--visible', '--reemplazar') }
    & $py @orden4 | Registrar
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'El marcado fallo. El archivo local puede estar escrito; revisar.' -ForegroundColor Yellow
    }

    # --- Etapa 5: cierre -----------------------------------------------------
    Titulo 'PASO 6/6 - Cierre del dia'
    & $py -c "import sys; sys.path.insert(0,'src'); from moodle_sinu.ejecutor_sinu import ciclos_abiertos; a=ciclos_abiertos(); print('Materias a medias sin cerrar:', len(a)); [print('   ', x) for x in a]" | Registrar

    $escalado = Join-Path $raiz 'logs\escalado_isef05_pacf50.jsonl'
    if (Test-Path $escalado) {
        Write-Host ''
        Write-Host 'Casos a validar en ISEF05/PACF50 (ultimos 10):' -ForegroundColor Yellow
        Get-Content $escalado -Tail 10 | Registrar
    }

    Titulo 'FIN'
    Write-Host "Sheet del dia : $SheetUrl"
    Write-Host "Archivo       : $validado"
    Write-Host "Bitacora      : $bitacora"
    if ($codigo3 -ne 0) {
        Write-Host ''
        Write-Host 'Hubo periodos con fallo. Para reintentar SOLO esos:' -ForegroundColor Yellow
        Write-Host ("  .\scripts\dia_completo.ps1 -EjecutarDeVerdad -SheetUrl '{0}' -Reporte '{1}' -Periodos '<PERIODO1,PERIODO2>' -SinRotarDiario" -f $SheetUrl, $validado)
    }

    # --- El aviso de cierre --------------------------------------------------
    # Las metricas NO se pasan desde aqui: notificar_cierre.py las saca del
    # diario. Asi el aviso cuenta lo que de verdad paso, y no lo que este
    # script creia que estaba pasando.
    if (-not $SinAvisar) {
        if ($codigo3 -eq 0) { $estado = 'exito' } else { $estado = 'fallo' }
        if ($codigo3 -eq 0) { $nota = '' } else { $nota = 'Algun periodo termino con error; ver la bitacora.' }
        $ordenAviso = @('scripts
otificar_cierre.py', '--estado', $estado)
        if ($nota) { $ordenAviso += @('--nota', $nota) }
        & $py @ordenAviso | Registrar
    }
    $flujoCompleto = $true
}
finally {
    # El cerrojo se cierra SIEMPRE, tambien si algo revento a mitad. Es el punto
    # de gestionarlo aqui: que no quede abierto por un fallo o un Ctrl+C.
    FijarSimulacion 'true'
    Write-Host ''
    Write-Host "MODO_SIMULACION devuelto a: $(LeerSimulacion)" -ForegroundColor Green

    # Un flujo que revento a mitad tiene que avisar. Sin esto, en desatendido
    # un fallo se ve exactamente igual que un dia sin novedades: silencio.
    # $flujoCompleto solo es $true si se llego al final del bloque try; las
    # salidas previstas (cerrojo, -HastaSubir) ponen $avisoNoHaceFalta.
    if (-not $SinAvisar -and -not $flujoCompleto -and -not $avisoNoHaceFalta) {
        & $py scripts
otificar_cierre.py --estado fallo `
            --nota "El flujo se interrumpio antes de terminar. Bitacora: $bitacora" |
            Registrar
    }
    if ($simulacionOriginal -ne 'true') {
        Write-Host "(estaba en '$simulacionOriginal' al empezar)" -ForegroundColor Yellow
    }
}
