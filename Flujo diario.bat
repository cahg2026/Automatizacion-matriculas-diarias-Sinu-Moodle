@echo off
rem Abre el panel del flujo diario con doble clic.
rem
rem Es un .bat y no un .ps1 a proposito: Kaspersky bloqueo dia_completo.ps1 al
rem cargarlo (ScriptContainedMaliciousContent), y no tiene sentido dejar puesta
rem otra pieza de PowerShell esperando el mismo destino.
rem
rem `pythonw.exe` en vez de `python.exe` para que no quede una consola negra
rem abierta detras de la ventana.

cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
    echo No se encuentra el entorno virtual .venv
    echo Crearlo con:  py -3.11 -m venv .venv
    echo y luego:      .venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)

start "" ".venv\Scripts\pythonw.exe" "scripts\panel.py"
