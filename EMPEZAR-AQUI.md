# Empezar aquí

Guía para dejar funcionando la automatización de matrículas en su computador.

Son **6 pasos**. La primera vez toma unos 30 minutos, casi todos de espera. No
hace falta saber programar: se copian comandos y se pegan.

En todo el proceso **no se modifica ninguna matrícula**. Eso solo pasa al
final, y solo si usted lo pide expresamente.

---

## Antes de empezar: pida estas cosas

Escríbale a la persona que le compartió el proyecto y pídale:

1. **El usuario y la contraseña de Power BI.** Es una cuenta del área que todos
   comparten.
2. **La dirección (URL) del informe de Power BI** `ValidacionMoodle`.
3. **Que le den permiso de escritura** en la carpeta de Google Drive
   `REPORTES 2026`, con el correo de Google que usted va a usar.

Los dos primeros datos no vienen en el proyecto a propósito: el repositorio es
público y ahí no se publican cuentas ni contraseñas. Sin estas tres cosas el
proceso no puede terminar.

Y asegúrese de tener:

- **Un navegador compatible.** La automatización funciona con **Microsoft
  Edge** (viene con Windows y es el que trae configurado) o con **Google
  Chrome**. Para usar otro, se cambia una línea en `config\.env`
  (`NAVEGADOR_CANAL`); no hace falta tocar el programa.
- **Su usuario y contraseña de SINU**, con permiso para entrar al módulo
  **ISEF07**. Si no sabe si lo tiene, el programa se lo dirá claramente.

---

## Paso 1 — Instalar Python

Python es el lenguaje en el que está escrita la automatización. Se instala una
sola vez.

1. Abra su navegador y vaya a **https://www.python.org/downloads/release/python-3119/**
2. Baje hasta el final de la página, a la tabla de archivos.
3. Haga clic en **Windows installer (64-bit)**.
4. Abra el archivo que se descargó.
5. **MUY IMPORTANTE**: antes de darle a «Install Now», marque la casilla de
   abajo que dice **«Add python.exe to PATH»**.
6. Clic en **Install Now** y espere a que termine.

> Si ya tenía Python instalado, salte este paso.

---

## Paso 2 — Descargar el proyecto

1. Abra su navegador y entre al repositorio que le compartieron en GitHub.
2. Busque el botón verde que dice **Code** y haga clic.
3. Elija **Download ZIP**.
4. Cuando termine de bajar, busque el archivo en su carpeta de Descargas.
5. Haga **clic derecho** sobre el ZIP → **Extraer todo…** → **Extraer**.
6. Le quedará una carpeta. **Muévala a un sitio fácil**, por ejemplo su
   Escritorio.

> Si le suena `git`, también puede hacer `git clone` de la rama **`main`**. Es
> la única rama que existe, así que no hay forma de equivocarse.

---

## Paso 3 — Preparar el programa

Aquí se instalan las piezas que la automatización necesita.

1. Abra la carpeta del proyecto.
2. Haga clic en la **barra de dirección** de la ventana (donde se ve la ruta),
   escriba `cmd` y pulse **Enter**. Se abrirá una ventana negra.
3. Copie esta línea, péguela en la ventana negra y pulse **Enter**:

```
py -3.11 -m venv .venv
```

4. Espere a que vuelva a aparecer el cursor. Luego copie y pegue esta otra:

```
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

5. Espere. Tarda unos minutos y escribe mucho texto: es normal.

**¿Cómo sé que salió bien?** Copie y pegue esto:

```
.venv\Scripts\python.exe -m pytest -q
```

Al final debe decir algo como **`539 passed`**. Lo que importa no es el número
—va creciendo— sino que diga **`passed`** y que **no aparezca la palabra
`failed`**. Si es así, el programa está bien instalado.

---

## Paso 4 — Poner sus contraseñas

1. En la ventana negra, copie y pegue:

```
.venv\Scripts\python.exe scripts\primera_vez.py
```

2. El programa le dirá que faltan **6 datos**. Ahora los va a poner.
3. Copie y pegue esto para abrir el archivo:

```
notepad config\.env
```

4. Se abre el Bloc de notas. Busque estas **seis líneas** y escriba el valor
   **justo después del signo igual, sin espacios**:

| Línea | Qué escribir |
|---|---|
| `POWERBI_USUARIO=` | El usuario de Power BI que le pasaron |
| `POWERBI_PASSWORD=` | La contraseña de Power BI que le pasaron |
| `POWERBI_URL_INFORME=` | La dirección del informe que le pasaron |
| `SINU_USUARIO=` | **Su** usuario de SINU |
| `SINU_PASSWORD=` | **Su** contraseña de SINU |
| `POWERBI_PERFIL_NAVEGADOR=` | La carpeta donde el navegador guardará las sesiones de la automatización, por ejemplo `C:\Users\<su usuario de Windows>\.playwright-perfil-msedge`. **No la ponga dentro de OneDrive** |

Debe quedar así (con sus datos reales; estos son de ejemplo):

```
POWERBI_USUARIO=cuenta.del.area@ejemplo.edu.co
POWERBI_PASSWORD=LaQueLePasaron
POWERBI_URL_INFORME=https://app.powerbi.com/groups/...
SINU_USUARIO=1234567890
SINU_PASSWORD=SuContraseña
POWERBI_PERFIL_NAVEGADOR=C:\Users\su_usuario\.playwright-perfil-msedge
```

> Si usa Chrome en lugar de Edge, cambie también `NAVEGADOR_CANAL=msedge` por
> `NAVEGADOR_CANAL=chrome` y use otra carpeta de perfil
> (`.playwright-perfil-chrome`). Cada navegador necesita la suya.

5. **Guarde** con `Ctrl + S` y cierre el Bloc de notas.

> **Las de SINU son SUYAS y no se comparten con nadie.** Cada matrícula que la
> automatización modifique queda registrada a nombre de quien la hizo. Si usa
> la cuenta de otra persona, aparecerán a su nombre cambios que no hizo.

> Este archivo **nunca se sube a GitHub**. Está configurado para quedarse solo
> en su computador.

---

## Paso 5 — Entrar a las páginas

Ahora va a iniciar sesión una sola vez en cada sitio. El programa abre las
páginas por usted; **usted solo escribe sus contraseñas**.

1. En la ventana negra, copie y pegue otra vez:

```
.venv\Scripts\python.exe scripts\primera_vez.py
```

2. Se abrirá el navegador configurado (**Edge**, si no lo cambió) y pasará por cuatro páginas, una por una:

| | Con qué cuenta entrar |
|---|---|
| **Power BI** | La cuenta del área que le pasaron |
| **SINU** | **La suya** |
| **Google Drive** | **La suya** |
| **Google Calendar** | **La suya** |

3. En cada una: si le pide usuario y contraseña, escríbalos. Si le pide un
   código al celular, póngalo.
4. Cuando la página ya se vea cargada, **cierre esa pestaña** y el programa
   pasará sola a la siguiente.
5. Al final, el programa comprueba las cuatro y le dice si quedaron bien.

**Debe verse así:**

```
[ok] Power BI: sesion viva.
[ok] SINU: sesion viva.
[ok] Google Drive: sesion viva.
[ok] Google Calendar: sesion viva.
```

Si alguna dice otra cosa, vuelva a ejecutar el mismo comando y entre otra vez
en esa página.

> Esto se hace **una sola vez**. La sesión queda guardada. Cada varios meses
> Google puede volver a pedirle que confirme que es usted; si pasa, repita este
> paso y listo.

---

## Paso 6 — Probar sin tocar nada

Esta es la prueba de verdad, y **no modifica ninguna matrícula**. Recorre todo
el proceso, entra a SINU, lee la información y le dice qué haría.

```
.venv\Scripts\python.exe scripts\dia_completo.py
```

Tarda **entre 1 y 3 horas**. Puede dejarlo corriendo y seguir con lo suyo, pero
**no use SINU mientras tanto**: el programa está usando su sesión.

Al terminar verá un resumen con cuántas matrículas habría procesado.

**Si llegó hasta aquí, ya está todo listo.**

---

## Y de aquí en adelante, ¿qué hago cada día?

Nada. El programa puede hacerlo solo.

Haga **doble clic** en el archivo **`Flujo diario.bat`**, dentro de la carpeta
del proyecto. Se abre una ventanita:

```
ENCENDIDA - L a V
Próxima ejecución: martes 15/09/2026 a las 09:00
Modo REAL: modificará matrículas en SINU.
─────────────────────────────────────────
[Todos los días (L-V)]  [Solo mañana]  [Apagar]
```

| Botón | Qué hace |
|---|---|
| **Todos los días (L-V)** | Se ejecuta solo a las 9:00, de lunes a viernes |
| **Solo mañana** | Se ejecuta una vez y se apaga sola |
| **Apagar** | No se ejecuta solo |

Lea siempre la línea del medio antes de cerrar: le dice **si va a modificar
matrículas de verdad o solo va a ensayar**.

Para que funcione sola, el computador tiene que estar **encendido y con su
sesión de Windows iniciada** a esa hora.

### Le avisará en su calendario

Cuando termine, le llega un evento a Google Calendar:

- ✅ **ÉXITO: Flujo Moodle vs SINU completado** — con el resumen del día.
- ⚠️ **ALERTA: Tablero Power BI sin actualizar** — si los datos del día aún no
  estaban listos. En ese caso **no toca nada** y avisa.

Si no le llega la notificación al celular, entre a Google Calendar →
**Configuración** → **Notificaciones de eventos**, y ponga el aviso en **«a la
hora del evento»**.

---

## ⚠️ Antes de procesar matrículas de verdad

Hay una regla que hay que respetar entre todos:

> **Solo una persona al día** debe ejecutar el proceso en modo real.

El programa lleva la cuenta de lo hecho **en su propio computador**, así que no
sabe lo que hizo otra persona en el suyo. Si dos lo ejecutan el mismo día,
pueden desvincular una matrícula que el otro acaba de dejar bien.

El programa se protege solo —si detecta que alguien ya procesó hoy, se detiene
antes de tocar nada—, pero **acuérdenlo igual entre ustedes**.

Para probar cuantas veces quiera: use el Paso 6, que no escribe nada.

---

## Para entender el proceso

Todo está en la carpeta **`docs`**. Los `.html` se abren con doble clic.

| Documento | Para qué sirve |
|---|---|
| `docs/flujo-y-tipificaciones.html` | **Empiece por este.** Diagrama del día en 6 pasos, el árbol que decide el color de cada fila y qué hacer con cada color del Sheet |
| `docs/documentacion-proceso.html` | El proceso completo explicado, con sus decisiones |
| `docs/guia-instalacion.html` | Esta misma guía de instalación, con más detalle |
| `docs/estado-20261015.md` | Cómo está la automatización al 15/10/2026 y qué queda pendiente |

Dos reglas que conviene tener presentes:

- **Cada día se procesa de cero.** La integración mueve matrículas todos los
  días, así que lo que vuelva a salir en el reporte se procesa otra vez.
- **Las decisiones manuales valen solo para ese día.** Si se pide no procesar
  un período o un grupo, no se deja configurado para los días siguientes.

---

## Si algo sale mal

| Lo que ve | Qué significa y qué hacer |
|---|---|
| `Faltan N claves por rellenar` | Vuelva al **Paso 4** |
| `sesion caida` o le pide entrar | Repita el **Paso 5** |
| `self-signed certificate` | Su antivirus revisa el tráfico. Ejecute `scripts\primera_vez.py`: le da el comando exacto para arreglarlo |
| `Ya hay un reporte de hoy` | Otra persona ya procesó hoy. No hay nada que hacer |
| `El tablero no se actualizó hoy` | Los datos aún no estaban listos. No es un error: el programa se detuvo a propósito |
| `no se encontró el módulo ISEF07` | Su cuenta de SINU no tiene ese permiso. Hay que pedirlo |

**Para revisar todo de una vez**, sin que abra nada:

```
.venv\Scripts\python.exe scripts\primera_vez.py --revisar
```

Le dirá qué está bien y qué falta.

---

## Resumen de los comandos

Todos se pegan en la ventana negra, dentro de la carpeta del proyecto:

```
py -3.11 -m venv .venv                                   (una vez)
.venv\Scripts\python.exe -m pip install -r requirements.txt   (una vez)
.venv\Scripts\python.exe scripts\primera_vez.py          (puesta en marcha)
.venv\Scripts\python.exe scripts\primera_vez.py --revisar (revisar)
.venv\Scripts\python.exe scripts\dia_completo.py         (ensayo, no escribe)
```

Y para el día a día: **doble clic en `Flujo diario.bat`**.
