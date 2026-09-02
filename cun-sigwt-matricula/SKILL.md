---
name: cun-sigwt-matricula
description: Familia de casos de uso para ajustes de matriculación en el Sistema académico de la CUN (sigwt.cun.edu.co/sgacampus/), cruzando un Excel de matrícula contra actividades del sistema para vincular/desvincular estudiantes a Moodle, y otros ajustes de matrícula que se irán agregando (integración masiva, cambios de grupo, cancelaciones, etc.). Usa esta skill siempre que el Sr. Niño mencione sigwt, sgacampus, el sistema académico de la CUN, vincular o desvincular estudiantes a Moodle, cargar un Excel de matrícula al sistema, códigos de actividad tipo ISEF07/ISEF05/PACF50, o pida repetir un proceso de "cédula por cédula" en el sistema académico. También aplica si solo dice "vamos a hacer lo de siempre en sigwt" o "carga el Excel de matrícula" sin más detalle — en ese caso confirma con el usuario cuál caso de uso de los de abajo aplica antes de arrancar.
---

# Ajustes de matriculación en sigwt (CUN) — familia de casos de uso

Esta skill agrupa varios procesos que el Sr. Niño ejecuta en el Sistema académico de la CUN (`sigwt.cun.edu.co/sgacampus/`) para ajustar matrícula, casi siempre cruzando un Excel exportado del propio sistema contra una pantalla del sistema. Está pensada para crecer: cada caso de uso vive en su propio archivo dentro de `references/`, y este SKILL.md es solo el índice más las convenciones que todos los casos comparten. Así, agregar un caso nuevo no obliga a reescribir los anteriores.

## Cómo usar esta skill

1. Identifica qué caso de uso quiere el usuario (ver tabla abajo). Si no lo dice explícito, pregúntale — no asumas cuál de los procesos es, porque cada uno tiene su propio flujo de clics.
2. Lee el archivo de `references/` correspondiente a ese caso. Ahí está el paso a paso detallado.
3. Si el usuario describe un proceso que no está en la tabla, es un caso nuevo: síguelo con él paso a paso como una sesión de aprendizaje (igual que se hizo con vinculación individual), y al final documenta ese proceso en un archivo nuevo de `references/` para que quede disponible la próxima vez. Avísale que lo vas a guardar como un caso nuevo de esta misma skill, no como una skill aparte.

## Casos de uso disponibles

| Caso de uso | Actividad del sistema | Archivo de referencia | Estado |
|---|---|---|---|
| Vinculación individual de estudiantes a Moodle (cédula por cédula) | ISEF07 | `references/vinculacion-moodle.md` | Listo |
| Integración masiva con Moodle | ISEF05 | *(pendiente de documentar)* | Por hacer — probablemente la versión masiva del mismo caso de arriba; documentar cuando el usuario lo enseñe |
| Programación de grupos | PACF50 | *(pendiente de documentar)* | Por hacer |

Cuando se documente un caso nuevo, agrega una fila aquí apuntando a su archivo de referencia. Mantén esta tabla como la puerta de entrada — es lo primero que se lee para decidir a qué referencia ir.

## Convenciones compartidas por todos los casos

Estas aplican a cualquier proceso dentro de sigwt, no solo a vinculación a Moodle:

- **El sistema es un ERP académico con grillas asíncronas.** Cada búsqueda, selección o ejecución de acción puede tardar de 1 a 40 segundos en responder. No asumas que una acción terminó solo porque el clic se ejecutó — toma una captura, y si sigue en progreso (spinner, barra de progreso, contador de segundos subiendo), espera y vuelve a capturar. No dispares el siguiente paso encima de una carga en curso.
- **El filtro de Periodo (arriba a la derecha) suele ser "de una sola vez"** al inicio de una sesión de trabajo, no por cada fila o estudiante — pero confírmalo para cada caso nuevo, porque no todas las pantallas del sistema funcionan igual.
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
