# Caso de uso: Vinculación individual de estudiantes a MOODLE (ISEF07)

Actividad del sistema: **ISEF07 – Vinculación individual de estudiantes a MOODLE**, pestaña "Grupos" (hay también pestaña "Traza", no usada en este flujo).

## Qué hace

Vincula (o desvincula) a un estudiante en **una asignatura concreta** de su curso de Moodle. Se trabaja estudiante por estudiante y, dentro de cada uno, **solo la materia que figura en el reporte**.

> **CORRECCIÓN del dueño del proceso (03/09/2026).** Este documento decía antes
> que la acción se aplica *"con todas sus asignaturas matriculadas del periodo
> activo"*. **Eso es falso y causó daño.** La regla real es:
>
> > Por la 07 únicamente se debe procesar, por estudiante, el código de la
> > materia que registre en el reporte. No otro, no todos, no algunos:
> > únicamente el que registre en el reporte.
>
> La frase original se propagó a ocho archivos del proyecto y llevó a reciclar
> asignaturas que nadie había pedido tocar: el 03/09/2026, en 5 estudiantes, se
> desvincularon y revincularon **34 asignaturas cuando correspondían 5**.
> Ninguna quedó rota, pero el reporte no vigila esas materias, así que un fallo
> ahí habría pasado inadvertido.
>
> No volver a escribir aquí que la acción es "por estudiante" ni "por todas sus
> asignaturas". La unidad de trabajo es **(cédula, materia)**.

## Insumos que debe traer el usuario

1. El Excel de matrícula (típicamente "Matricula sin correo.xlsx" o similar).
2. La hoja del Excel ya filtrada al periodo que se va a trabajar (ver "Convenciones del Excel de matrícula" en el SKILL.md principal — estos Exceles suelen traer una hoja cruda con varios periodos y una hoja aparte ya filtrada a uno solo).
3. La pestaña del navegador ya en `sigwt.cun.edu.co/sgacampus/` con esta actividad (ISEF07) abierta.

## Paso 0 — Filtro de Periodo (SOLO UNA VEZ)

En la esquina superior derecha, el campo **Periodo** (p. ej. `26V05`). Se ajusta una sola vez al inicio, al periodo que corresponde a la hoja del Excel. No se vuelve a tocar entre estudiante y estudiante.

## Extraer la lista de cédulas

```bash
python3 scripts/extract_cedulas.py "<ruta al xlsx>" --sheet "<hoja filtrada al periodo>" --column IDENTIFICACION
```

Deduplica automáticamente: el Excel trae una fila por asignatura matriculada, no por estudiante, así que hay que recorrer cédulas únicas, no filas.

## Ciclo por cada cédula única

1. **Filtrar el estudiante**: en la grilla **Estudiantes** (arriba), clic en el filtro de la columna "No. Identificación" (triple-click para seleccionar cualquier valor previo), escribir la cédula, Enter.
2. **Esperar el resultado** (1-2s). Debe quedar exactamente una fila. Si aparecen cero o más de una, detente y avisa al usuario — no sigas con el estudiante equivocado.
3. **Seleccionar la fila**: clic sobre ella. Dispara la carga automática de la grilla **Grupos** (abajo) con las asignaturas matriculadas de ese estudiante en el periodo activo.
4. **Acotar a la materia del reporte**: escribir el `COD_MATERIA` del reporte en el filtro de esa columna de la grilla **Grupos**. Este paso NO es opcional: sin él la acción alcanza asignaturas que el reporte no menciona.
5. **Mirar el check "Vinculado?" de esa materia**, y solo de esa:
   - **con check** → *Desvincular*, esperar la **confirmación de la desvinculación**, y solo entonces *Vincular* y esperar a que quede **vinculado**.
   - **sin check** → *Vincular* directamente.
6. **Elegir la acción** en el desplegable **"Acción a realizar"** (debajo de la grilla Grupos). El desplegable suele conservar la última selección entre estudiantes; verifícalo igual.
7. **Ejecutar**: clic en el primer icono (el de más arriba de tres, tipo engranaje) a la izquierda del desplegable.
8. **Esperar el resultado**: barra de progreso + contador de segundos. Toma capturas cada 5-10s hasta ver el diálogo **"Nota" / "Proceso terminado"**. No hagas clics adicionales mientras corre.
9. **Cerrar el diálogo**: clic en **OK**.
10. **Confirmar el check de esa materia** volviendo a leer la fila. El diálogo *"Proceso terminado"* dice que el proceso corrió, **no** que la materia quedara vinculada. Medido el 03/09/2026: el check puede tardar más de 17 s en aparecer, así que hay que sondear hasta que se estabilice y no leer una sola vez.
11. **Si la 07 no permite vincular, o si tras vincular la materia sigue sin check**: abrir **ISEF05** y **PACF50**, validar el check en Moodle y dejar registrada esa información en el Google Sheet. No insistir en la 07.
12. **Siguiente fila del reporte**: repetir desde el paso 1. El Periodo (paso 0) no se vuelve a tocar.

## Errores comunes de este caso

- Cero o más de un resultado al filtrar por cédula → parar y avisar.
- El desplegable "Acción a realizar" vuelve a quedar vacío entre estudiantes → seleccionarlo de nuevo antes de ejecutar.
- Usar la hoja cruda del Excel (con varios periodos mezclados) en vez de la ya filtrada al periodo activo → se buscan cédulas que no aplican a ese periodo.
- **Ejecutar sin acotar la grilla Grupos al `COD_MATERIA` del reporte** → la acción alcanza asignaturas que nadie pidió tocar. Es el error que costó 34 asignaturas recicladas de más el 03/09/2026.
- **Dar por vinculada una materia porque salió "Proceso terminado"** → eso confirma que el proceso corrió, no que el check quedara puesto.
