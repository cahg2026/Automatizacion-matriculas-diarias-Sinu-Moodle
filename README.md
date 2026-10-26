# Automatización — Validación Moodle vs. SINU

Cada día, la automatización toma el reporte comparativo Moodle vs. SINU de
Power BI, lo sube a Google Sheets y, estudiante por estudiante, vincula en SINU
(ISEF07) a quienes están matriculados pero no tienen su curso en Moodle. Al
final marca en el Sheet qué quedó resuelto y qué hay que revisar a mano.

**¿Primera vez en este proyecto?** Vaya directo a [`EMPEZAR-AQUI.md`](EMPEZAR-AQUI.md).
Es la única guía de instalación y está escrita para no programadores.

---

## Lo que tiene que estar bien antes de correr (lo que más falla)

Estas cuatro cosas se descubrieron probando con compañeros. Si una falta, el
flujo falla o deja datos mal.

| Dónde | Qué debe estar | Si no |
|---|---|---|
| **SINU** (arriba a la derecha) | **Perfil: `LMS`** seleccionado, con la empresa CORPORACION UNIFICADA NACIONAL DE EDUCACION SUPERIOR. Con otro perfil no aparecen los módulos ISEF07 / PACF50 | El flujo no encuentra el módulo y se detiene |
| **Google Drive** | Activada la opción **«Convertir archivos subidos al formato del Editor de Documentos de Google»** (⚙️ → Configuración → General). Se hace con la misma cuenta de Google que usa la automatización | El archivo sube en un formato que no es el esperado y da error de formato |
| **Carpeta de Drive** | Permiso de **escritura** en `REPORTES 2026` para su cuenta de Google | No puede subir el reporte |
| **El código** | Última versión de `main` (ver «Cómo actualizar») | Fallos ya corregidos, como el de la tabla de Power BI del 05/10 |

Y dos reglas al correr:

- **Solo una persona al día** procesa «de verdad». Dos personas el mismo día se
  pisan las matrículas.
- **No interrumpa la ventana** (ni Ctrl+C ni cerrarla). El paso 2 puede quedar
  varios minutos sin escribir nada: es normal. Interrumpirlo genera una alerta
  falsa de «Flujo incompleto».

## Cómo corre el día

El día son 6 pasos, siempre en este orden:

| Paso | Qué hace |
|---|---|
| 0 | Revisa que el navegador y la sesión de Google estén vivos |
| 1 | **Cerrojo:** comprueba que el tablero de Power BI se actualizó hoy. Si no, espera hasta 90 min y, si sigue viejo, se detiene y avisa |
| 2 | Descarga el reporte de Power BI |
| 3 | Limpia el reporte, lo ordena A–Z por período y sube el Sheet a Drive |
| 4 | **Entra a SINU (ISEF07) y vincula**, período por período. Es el único paso que escribe |
| 5 | Marca en el Sheet el color y la columna Q de cada fila |
| 6 | Cierra el día y avisa por Google Calendar |

Cada día se procesa **de cero**: lo que reaparece en el reporte se vuelve a
procesar, y las decisiones manuales («hoy no toques este período») valen solo
para ese día. PACF50 decide si un grupo existe o tiene curso; ISEF05 ya no se
consulta (desde el 06/10/2026).

## Los comandos que se usan

Se ejecutan en una ventana de PowerShell **dentro de la carpeta del proyecto**.

| Para qué | Comando |
|---|---|
| Puesta en marcha en un equipo nuevo (una vez) | `.venv\Scripts\python.exe scripts\primera_vez.py` |
| Revisar que todo esté bien, sin abrir nada | `.venv\Scripts\python.exe scripts\primera_vez.py --revisar` |
| **Ensayo:** recorre todo y dice qué haría, **no escribe nada** | `.venv\Scripts\python.exe scripts\dia_completo.py` |
| **El día de verdad** (modifica matrículas) | `.venv\Scripts\python.exe scripts\dia_completo.py --ejecutar-de-verdad` |
| Volver a iniciar sesión si caducó | `.venv\Scripts\python.exe scripts\probar_perfil.py --iniciar-sesion` |
| Panel para encender/apagar la ejecución de las 9:00 | doble clic en `Flujo diario.bat` |

Sin `--ejecutar-de-verdad` el encabezado dice `Modo: SIMULACION`. Con la
bandera ya no debe decirlo; si lo sigue diciendo, detener y no dejar que escriba.

## Cómo actualizar el código

El proyecto se corrige con frecuencia. Antes de correr, traiga la última
versión de `main`:

- **Con git:** `git pull` dentro de la carpeta del proyecto.
- **Con el ZIP de GitHub:** descargue el ZIP nuevo, extráigalo en cualquier
  carpeta, seleccione **todo su contenido** y péguelo encima de su carpeta
  vieja, eligiendo «Reemplazar». No se pierde nada importante: su `.venv`,
  `config\.env` y `logs` no vienen en el ZIP. **No copie el `.venv` a otra
  carpeta**, porque se daña.

Repositorio: https://github.com/cahg2026/Automatizacion-matriculas-diarias-Sinu-Moodle

## Si algo falla

| Lo que ve | Qué es | Qué hacer |
|---|---|---|
| `no tiene ningun visual de tabla o matriz` (PASO 2) | Power BI cambió el nombre de la tabla; el código viejo no la reconoce | Actualizar el código (arriba) |
| `Interrumpido a mano` + «FALLO: Flujo incompleto» | Se cortó la ventana o se pulsó Ctrl+C. No es un error real | Volver a lanzar y no tocar la ventana |
| `El tablero no se actualizó hoy` | Los datos aún no estaban listos. Se detuvo a propósito | Esperar y reintentar más tarde |
| `sesion caida` o pide iniciar sesión | Caducó una sesión | `probar_perfil.py --iniciar-sesion` |
| `Ya hay un reporte de hoy` | Otra persona ya procesó hoy | Nada que hacer |
| `no se encontró el módulo ISEF07` | Perfil de SINU distinto de `LMS`, o la cuenta no tiene el permiso | Elegir el perfil `LMS`; si sigue, pedir el permiso |
| `self-signed certificate` | El antivirus revisa el tráfico HTTPS | `primera_vez.py` da el comando exacto |

Más casos en la última sección de [`EMPEZAR-AQUI.md`](EMPEZAR-AQUI.md).

## Mapa de documentos

| Quiero… | Documento |
|---|---|
| Instalar y dejar funcionando la automatización | [`EMPEZAR-AQUI.md`](EMPEZAR-AQUI.md) |
| Entender el flujo, cómo se decide cada fila y qué significa cada color del Sheet | [`docs/flujo-y-tipificaciones.html`](docs/flujo-y-tipificaciones.html) |
| Ver el proceso completo y sus decisiones | [`docs/documentacion-proceso.html`](docs/documentacion-proceso.html) |
| Saber cómo está hoy y qué queda pendiente | [`docs/estado-20261015.md`](docs/estado-20261015.md) |
| Entender cómo está construido (para quien mantenga el código) | [`docs/arquitectura-y-mejoras.md`](docs/arquitectura-y-mejoras.md) |
| Ver versiones de software del equipo de producción | [`docs/inventario-software.md`](docs/inventario-software.md) |
| Consultar el manual técnico anterior (histórico) | [`docs/historico/`](docs/historico/) |

Los `.html` se abren con doble clic. La carpeta `cun-sigwt-matricula/` es una
skill de Claude, no documentación para personas.

## Seguridad

El repositorio es **público**. Nunca se versionan `config/.env`, `data/`,
`logs/`, los `.xlsx` ni las sesiones del navegador (ver `.gitignore`). Las
credenciales de SINU son **personales**: cada cambio queda registrado a nombre
de quien lo hizo.

## Detalles técnicos

Python 3.11.9 · Playwright con Edge o Chrome (`NAVEGADOR_CANAL`, cada uno con su
perfil dedicado) · pruebas: `.venv\Scripts\python.exe -m pytest -q`.
