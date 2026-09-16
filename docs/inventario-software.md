# Inventario de software y versiones

**Medido el 16/09/2026** sobre el equipo donde corre la automatización. Todos los valores salen de consultar la máquina, no de lo que debería estar instalado.

Cada bloque incluye **el comando que lo regenera**, para que este documento se pueda volver a levantar en cinco minutos cuando cambie algo o cuando se monte un equipo nuevo.

---

## 1. Sistema operativo

| | |
|---|---|
| Sistema | Microsoft Windows 11 Pro |
| Versión | 10.0.26200 (build 26200) |
| Arquitectura | 64 bits |

```powershell
Get-CimInstance Win32_OperatingSystem |
  Select-Object Caption, Version, BuildNumber, OSArchitecture
```

---

## 2. Python

| | Versión | Ruta |
|---|---|---|
| **Del entorno virtual** (el que usa todo) | **3.11.9** | `.venv\Scripts\python.exe` |
| Del sistema, 3.11 | 3.11.x | `%LOCALAPPDATA%\Programs\Python\Python311\python.exe` |
| Del sistema, por defecto | **3.14** ⚠️ | `%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe` |
| pip (dentro del venv) | 26.2.1 | |

> ⚠️ **El Python por defecto de esta máquina es el 3.14, no el 3.11.**
> Por eso el comando de instalación es `py -3.11 -m venv .venv` y no `py -m venv .venv`: sin el `-3.11` el entorno se crearía sobre 3.14, donde estas versiones de Playwright y openpyxl no están probadas. Es un fallo silencioso — el entorno se crea bien y revienta más tarde.

```powershell
.\.venv\Scripts\python.exe --version
py -0p                                   # todos los Python, con * en el de por defecto
```

---

## 3. Dependencias de Python

### 3.1 Directas — declaradas en `requirements.txt`

Son las cuatro que el proyecto pide de forma explícita, todas fijadas con `==`:

| Paquete | Versión | Para qué |
|---|---|---|
| `playwright` | **1.47.0** | Conduce Chrome. Etapas 1 a 5: Power BI, Drive, SINU, Calendar |
| `openpyxl` | **3.1.5** | Lee y escribe el `.xlsx` del reporte, y lo colorea |
| `python-dotenv` | **1.0.1** | Carga `config/.env` |
| `pytest` | **8.3.3** | Las 539 pruebas |

> **`pandas` no se usa en este proyecto.** No aparece en ningún `import`. El Excel se maneja con `openpyxl` directamente, que es suficiente para lo que se hace y evita una dependencia de ~50 MB.

### 3.2 Transitivas — las instala pip sola

No hay que declararlas ni fijarlas; se listan para que un `pip freeze` de otro equipo se pueda comparar con este.

| Paquete | Versión | Viene de |
|---|---|---|
| `greenlet` | 3.0.3 | playwright |
| `pyee` | 12.0.0 | playwright |
| `typing_extensions` | 4.16.0 | playwright / pyee |
| `et_xmlfile` | 2.0.0 | openpyxl |
| `pluggy` | 1.6.0 | pytest |
| `iniconfig` | 2.3.0 | pytest |
| `packaging` | 26.3 | pytest |
| `colorama` | 0.4.6 | pytest (color en consola de Windows) |

### 3.3 Instaladas en el entorno pero **no declaradas**

Están en este `.venv` y no en `requirements.txt`. Son herramientas de mantenimiento, no dependencias de ejecución: **un equipo nuevo funciona sin ellas.**

| Paquete | Versión | Qué es |
|---|---|---|
| `git-filter-repo` | 2.47.0 | Reescritura de historia de Git. Se usó el 02/09/2026 para purgar el `config/.env.respaldo_*` que llegó a GitHub con contraseñas |
| `pyflakes` | 3.4.0 | Análisis estático, uso puntual |

> Es deriva menor, no un problema: si alguien quiere dejarlo limpio, lo correcto es un `requirements-dev.txt` aparte, no meterlas en el de producción.

```powershell
.\.venv\Scripts\python.exe -m pip freeze
```

---

## 4. Navegador y motor de automatización

| Componente | Versión | Nota |
|---|---|---|
| **Google Chrome** (el que se automatiza) | **152.0.7977.83** | Es el Chrome instalado en el sistema |
| Playwright (Python) | 1.47.0 | |
| Node.js del driver de Playwright | 20.17.0 | Va dentro del paquete; no se instala aparte |
| Chromium descargado por Playwright | build 1134 | **Presente pero sin usar** por defecto |
| ffmpeg de Playwright | build 1010 | Solo para grabar vídeo de trazas |

**Cuál se usa de verdad:** `NAVEGADOR_CANAL=chrome` en `config/.env` hace que Playwright abra el **Chrome del sistema**, no el Chromium empaquetado. Por eso `playwright install` no es un paso obligatorio de la instalación. El `chromium-1134` que aparece arriba quedó de alguna prueba y no estorba.

> **Chrome 136 y posteriores prohíben automatizar el perfil personal por defecto**, y el cifrado ABE impide copiar sus cookies. De ahí que la automatización use un perfil dedicado (`NAVEGADOR_PERFIL=proyecto`) en el que hay que autenticarse una vez. Con Chrome 152 esto sigue igual.

```powershell
(Get-Item "C:\Program Files\Google\Chrome\Application\chrome.exe").VersionInfo.ProductVersion
.\.venv\Lib\site-packages\playwright\driver\node.exe --version
Get-ChildItem "$env:USERPROFILE\AppData\Local\ms-playwright" | Select-Object Name
```

---

## 5. Sistemas externos

No se instalan ni se versionan desde aquí: son servicios web. Se anota lo que **sí** se puede identificar, porque cuando uno de ellos cambia, se rompen los selectores.

| Sistema | Versión / identificación | Papel |
|---|---|---|
| **SINU — Sistema académico** | **v6.0.0**, de **Acies** | Etapas 3 y 4. El único donde se escribe |
| ↳ su interfaz | **SmartGWT / SmartClient**, `isc_version=7.1`, skin `Simplicity` | Explica por qué los `id` son inestables (`isc_7O` se regenera en cada carga) y por qué las rejillas se leen por geometría |
| **Power BI** | Servicio en la nube, sin versión fija | Etapa 1: exportación del tablero |
| **Google Drive / Sheets** | Servicio en la nube | Etapas 2 y 5. Por navegador: la organización no da acceso a Google Cloud Console |
| **Google Calendar** | Servicio en la nube | Etapa 6: el aviso de cierre |
| **Moodle** | Externo, no se toca | Es el sistema contra el que SINU valida |

Para releer la versión de SINU: entrar y mirar el pie de página (`© 2026 Acies · Sistema académico · [v6.0.0]`).

---

## 6. Entorno corporativo

Afecta directamente al funcionamiento, así que forma parte del inventario.

| Software | Versión | Cómo afecta |
|---|---|---|
| **Kaspersky Endpoint Security para Windows** | **12.12.0.522** (el activo) | Dos efectos conocidos, ambos ya mitigados |
| Kaspersky Endpoint Security for Windows | 11.24.8.522 | Entradas residuales de versiones anteriores en el registro |
| Agente de red de Kaspersky Security Center | 16.0.0.254 | Gestión centralizada; el equipo no decide su configuración |
| Windows Defender | Integrado en el SO | Convive con Kaspersky |
| Git para Windows | 2.55.0.windows.3 | Solo para el repositorio |

**Los dos efectos de Kaspersky, y cómo están resueltos:**

1. **Intercepta el HTTPS.** Reemite los certificados con su propia CA, y Playwright falla con `self-signed certificate in certificate chain`. Resuelto exportando esa CA a `config/ca_kaspersky.pem`; `config.py` la publica en `NODE_EXTRA_CA_CERTS` al importarse. Mantiene la validación del certificado, que es mejor que desactivarla. `scripts\primera_vez.py` lo detecta solo y da el comando exacto.
2. **AMSI bloquea scripts de PowerShell.** El 08/09/2026 tumbó `dia_completo.ps1` con `ScriptContainedMaliciousContent` **al analizarlo**, antes de ejecutar nada — sin dejar bitácora. Por eso el orquestador se reescribió en Python y el lanzador es un `.bat`, no un `.ps1`.

```powershell
Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntiVirusProduct |
  Select-Object displayName
git --version
```

---

## 7. Qué no actualizar sin probarlo

| Componente | Riesgo al subir de versión |
|---|---|
| **Python 3.11 → 3.12+** | Ninguna necesidad. Playwright 1.47 está probado aquí sobre 3.11.9. El 3.14 del sistema **no** está probado |
| **Playwright 1.47.0** | Los cambios de versión mueven el comportamiento de `wait_for`, las trazas y los canales de navegador. Toda la capa de selectores depende de esos tiempos |
| **Chrome** | Se actualiza solo y hasta ahora no ha roto nada, pero es el que más cambia. Si un día falla la apertura del perfil, mirar aquí primero |
| **openpyxl 3.1.5** | El coloreado del `.xlsx` y los números de fila dependen de su comportamiento; los números de fila son lo que alinea el Excel con el Sheet |

Regla práctica: si hay que actualizar algo, hacerlo **de uno en uno** y correr después un día completo en ensayo (`python scripts\dia_completo.py`, sin `--ejecutar-de-verdad`), que recorre todas las etapas sin escribir en SINU.

---

## Cómo regenerar este documento entero

```powershell
.\.venv\Scripts\python.exe --version
py -0p
.\.venv\Scripts\python.exe -m pip freeze
(Get-Item "C:\Program Files\Google\Chrome\Application\chrome.exe").VersionInfo.ProductVersion
.\.venv\Lib\site-packages\playwright\driver\node.exe --version
Get-ChildItem "$env:USERPROFILE\AppData\Local\ms-playwright" | Select-Object Name
Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version, BuildNumber
Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntiVirusProduct | Select-Object displayName
git --version
```

La versión de SINU se lee en el pie de su pantalla. Las de Power BI, Drive, Sheets, Calendar y Moodle no existen como número: son servicios web que cambian sin avisar, y ese es justo el motivo de que los selectores lleven en un comentario la fecha en que se verificaron.
