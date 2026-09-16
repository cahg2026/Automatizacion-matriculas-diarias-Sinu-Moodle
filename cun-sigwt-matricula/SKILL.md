---
name: cun-matriculas-diarias
description: Familia de casos de uso para la validación y ajuste de matriculación en el Sistema Académico de la CUN (sigwt.cun.edu.co/sgacampus/), cruzando reportes de Power BI y Exceles de matrícula contra Moodle y actividades de SINU (ISEF07, ISEF05, PACF50, ISEF88). Usa esta skill siempre que el Camila  mencione Matriuclas Diarias, sistema académico CUN, vinculación individual. Aplica también si pide ejecutar la extracción en Python, actualizar el reporte diario en Google Sheets, o procesar "cédula por cédula".


# Ajustes de matriculación en sigwt (CUN) — familia de casos de uso

Esta skill agrupa los procedimientos operativos para la validación, vinculación y ajuste de matrículas estudiantiles entre Power BI, Google Sheets, el Sistema Académico SINU (sigwt.cun.edu.co/sgacampus/) y Moodle. Está pensada para crecer: cada caso de uso vive en su propio archivo dentro de `references/`, y este SKILL.md es solo el índice más las convenciones que todos los casos comparten. Así, agregar un caso nuevo no obliga a reescribir los anteriores.

Entorno de Ejecución y Navegación Persistente
Perfil Activo de Google Chrome: Todas las operaciones deben ejecutarse en la sesión persistente del navegador del usuario para mantener las credenciales autenticadas y las cookies de sesión activas.

Navegación mediante Favoritos/Marcadores: El acceso a las plataformas se realiza exclusivamente desde la barra de marcadores guardados:

Power BI: Marcador directo al workspace CUN Digital / Informe ValidacionMoodle (página MOODLE-VS-SINU-EST).

Google Drive: Marcador directo a Compartidos conmigo → REPORTES 2026 → [Mes en curso].

SINU (SIGWT): Marcador directo a sigwt.cun.edu.co/sgacampus/.

## Cómo usar esta skill

dentifica qué caso de uso requiere el usuario (ver tabla de referencias).

Abre y consulta la especificación detallada en el archivo references/ correspondiente.

Si el proceso descrito es nuevo, ejecútalo en modo asistido paso a paso, documenta el flujo en un nuevo archivo dentro de references/ y registra la entrada en la tabla inferior.

## Casos de uso disponibles

| Caso de uso | Actividad del sistema | Archivo de referencia | Estado |
|---|---|---|---|
| Vinculación individual de estudiantes a Moodle (cédula por cédula) | ISEF07 | `references/vinculacion-moodle.md` | Listo |
| Integración masiva con Moodle | ISEF05 | `references/consulta-curso-moodle-isef05.md` | Listo **como consulta** (16/09/2026). La parte de ejecución masiva sigue sin documentar y no se usa |
| Programación de grupos | PACF50 | *(pendiente de documentar)* | Por hacer |

Cuando se documente un caso nuevo, agrega una fila aquí apuntando a su archivo de referencia. Mantén esta tabla como la puerta de entrada — es lo primero que se lee para decidir a qué referencia ir.

## Convenciones compartidas por todos los casos

Estas aplican a cualquier proceso dentro de sigwt, no solo a vinculación a Moodle:

- **El sistema es un ERP académico con grillas asíncronas.** Cada búsqueda, selección o ejecución de acción puede tardar de 1 a 40 segundos en responder. No asumas que una acción terminó solo porque el clic se ejecutó — toma una captura, y si sigue en progreso (spinner, barra de progreso, contador de segundos subiendo), espera y vuelve a capturar. No dispares el siguiente paso encima de una carga en curso.
- **El filtro de Periodo (arriba a la derecha) suele ser "de una sola vez"** al inicio de una sesión de trabajo verificar segun el reporte de google sheett el primer periodo y lobuscas en sigwt para inicar la gestion se debe estar validando cada fila y tener encuenta que cuenta  que cuando cambie el periodo este tambien debera cambair el sigwt , no por cada fila o estudiante — pero confírmalo para cada caso nuevo, porque no todas las pantallas del sistema funcionan igual.
- **Usa `browser_batch`** para agrupar clics/tecleo/capturas cuando el siguiente paso es predecible (limpiar un campo + escribir + Enter, por ejemplo), pero nunca agrupes un paso que depende de que el sistema termine de procesar algo — eso necesita su propia espera y captura.
- **No inventes validaciones que no pidió el usuario.** Si dice que él valida al final con un reporte aparte, no te desvíes intentando confirmar checkboxes o estados por tu cuenta.
- **Ante un resultado inesperado (cero o varias filas donde se esperaba una, un botón que no aparece, un mensaje de error), detente y avisa** en vez de adivinar — esto son ajustes reales de matrícula de estudiantes.
- **Antes de lanzar un lote largo sin supervisión**, dile al usuario cuántos registros hay y el tiempo estimado, y pregúntale si prefiere todo seguido, en lotes con pausas, o continuar él mismo manualmente. Si el usuario dice que se va a ausentar o que va a corregir algo en el sistema primero, no arranques el lote hasta que confirme que puedes seguir.

## Convenciones del Excel de matrícula

Los Exceles de matrícula que trae el usuario (exportados del propio sigwt) suelen tener esta forma, aunque el nombre del archivo varía:

- Columnas típicas: `IDENTIFICACION`, `NOMBRE_COMPLETO`, `CORREO`, `CELULAR`, `TELEFONO`, `COD_UNIDAD`, `COD_PENSUM`, `COD_MATERIA`, `ID_GRUPO`, `NUM_GRUPO`, `BLOQUE`, `PAGO`, `COD_PERIODO`, `LLAVE`, `VALIDACION`.
- **Una fila por asignatura matriculada, no por estudiante.** Un mismo estudiante aparece varias veces si tiene varias materias. Para procesos que trabajan por estudiante (como vinculación a Moodle), hay que deduplicar por `IDENTIFICACION` y conservar el orden de aparición.
- **Puede traer más de una hoja**: una "cruda" con varios periodos mezclados (columna `COD_PERIODO` variada) y otra ya filtrada a un solo periodo, lista para cruzar contra el sistema. Si hay duda sobre cuál hoja usar, pregunta al usuario — no asumas.

El script `scripts/extract_cedulas.py` extrae la lista de cédulas únicas de una hoja, en orden de aparición:

```bash
python3 scripts/extract_cedulas.py "<ruta al xlsx>" --sheet "<nombre hoja>" --column IDENTIFICACION
```

Es un helper genérico — sirve para cualquier caso de uso de esta familia que necesite recorrer cédulas del Excel, no solo para vinculación a Moodle.

Árbol de Decisión Global y Marcado en Reporte (Google Sheets)CasoCondición en SINU (ISEF07)Verificación CruzadaAcción OperativaMarcado en Google SheetsCaso 1: Vinculación ExitosaCédula encontrada.Asignatura visible.Curso en moodle? = ✓Vinculado? = ☐N/ASeleccionar 1 Vincular grupos matriculados → Ejecutar engranaje → Confirmar modal OK.Fila en Verde ClaroColumna Validación = OKCaso 2: Grupo sin IntegraciónCédula encontrada.Curso en moodle? = ☐Consultar PACF50 e ISEF05 (confirmar falta de check Moodle?).No accionable desde ISEF07.Fila en Rojo ClaroColumna Validación = NO TIENE CHECK EN MOODLECaso 3: Sin Matrícula AcadémicaBúsqueda por cédula arroja 0 resultados.Consultar ISEF05, PACF50 e ISEF88 (Consulta de estudiantes).No accionable. El estudiante no posee matrícula en el periodo.Fila en LilaColumna Validación = NO CUENTA CON MATRÍCULA
