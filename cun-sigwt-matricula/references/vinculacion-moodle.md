# Caso de uso: Vinculación individual de estudiantes a MOODLE (ISEF07)

Actividad del sistema: **ISEF07 – Vinculación individual de estudiantes a MOODLE**, pestaña "Grupos" (hay también pestaña "Traza", no usada en este flujo).

## Qué hace

Vincula (o desvincula) a un estudiante puntual, con todas sus asignaturas matriculadas del periodo activo, a sus cursos de Moodle. Se trabaja estudiante por estudiante, cruzando la lista de cédulas contra un Excel de matrícula.

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
4. **No verificar el check "Vinculado?" fila por fila** — el usuario valida al final con un reporte aparte que él mismo genera. No es parte de este flujo confirmar el estado individual de cada asignatura.
5. **Elegir la acción**: en el desplegable **"Acción a realizar"** (debajo de la grilla Grupos), seleccionar **"1 Vincular grupos matriculados"**. (La opción "2 Desvincular grupos matriculados" es la inversa, para deshacer — no es el flujo normal salvo que el usuario pida explícitamente desvincular.) El desplegable suele conservar la última selección entre estudiantes; verifícalo igual.
6. **Ejecutar**: clic en el primer icono (el de más arriba de tres, tipo engranaje) a la izquierda del desplegable.
7. **Esperar el resultado**: barra de progreso + contador de segundos, entre 15 y 40s según cuántas asignaturas tenga el estudiante. Toma capturas cada 5-10s hasta ver el diálogo **"Nota" / "Proceso terminado"**. No hagas clics adicionales mientras corre.
8. **Cerrar el diálogo**: clic en **OK**.
9. **Siguiente cédula**: repetir desde el paso 1. El Periodo (paso 0) no se vuelve a tocar.

## Errores comunes de este caso

- Cero o más de un resultado al filtrar por cédula → parar y avisar.
- El desplegable "Acción a realizar" vuelve a quedar vacío entre estudiantes → seleccionarlo de nuevo antes de ejecutar.
- Usar la hoja cruda del Excel (con varios periodos mezclados) en vez de la ya filtrada al periodo activo → se buscan cédulas que no aplican a ese periodo.
