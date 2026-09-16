# ISEF05 — ¿este grupo tiene curso creado en Moodle?

**Estado:** documentado como **consulta** el 16/09/2026, leyendo la pantalla
real. La parte de *ejecución* masiva de ISEF05 sigue sin documentar y la
automatización no la usa.

## Para qué sirve

Responde la pregunta que ISEF07 no puede responder: cuando se ejecuta
«Vincular grupos matriculados» y el check `Vinculado?` no aparece, ISEF07 no
dice por qué. Si la causa es que el grupo **no tiene curso creado en Moodle**,
reintentar no puede funcionar — no hay nada a lo que vincular.

Es el «Caso 2: Grupo sin Integración Moodle» de
[`vinculacion-moodle.md`](vinculacion-moodle.md), contestado de forma directa.

## Cómo se consulta

1. Entrar en `isef05` desde el menú de `#home` (código en minúscula).
2. Fijar el **Periodo** en el desplegable de arriba a la derecha. Es el mismo
   control global que usa ISEF07, así que sirve la misma rutina.
3. En la rejilla **Grupos**, escribir en las cajas de filtro de columna:
   - `cod_materia` — el código de la asignatura
   - `num_grupo` — el número de grupo

   Mismos nombres de campo que en ISEF07. El filtro es **«Contiene»**, así que
   pedir el grupo `5559` también devuelve el `55598`: hay que comprobar que la
   fila que vuelve sea exactamente la pedida.
4. Leer la columna **`Cursos en moodle?`**.

### Dos trampas de la pantalla

- **Al filtrar, la rejilla se desplaza a la derecha** para enseñar la columna
  filtrada, y las columnas de Moodle se van fuera de la vista. Hay que devolver
  el scroll al origen antes de leer, o se leen celdas de otras columnas.
- **El filtro tarda en aplicarse** más de lo que tarda en volver la espera de
  «sin cargas». Hay que reintentar la lectura hasta que aparezca la fila pedida,
  no leer una sola vez.

## Las columnas

| Columna | Qué dice |
|---|---|
| `Cursos en moodle?` | **La que decide.** Si está sin marcar, vincular es imposible |
| `Usuarios en moodle?` | Informativa |
| `Vinculación en moodle?` | Informativa |
| `Curso Semilla en moodle?` | Informativa |
| `Es Subgrupo?` | Informativa |
| `Código asignatura`, `Grupo` | Identifican la fila; sirven para verificar |

Los checks son `<img>` y su estado está en el nombre del archivo, igual que en
ISEF07 — `checked.gif`, `unchecked.gif`, `checked_Disabled.gif`,
`unchecked_Disabled.gif`, `unsetcheck.gif`. En esta rejilla salen casi todos
como `_Disabled`, porque es una pantalla de consulta.

> Ojo con `unchecked_Disabled.gif`: **contiene** la subcadena
> `checked_Disabled`. Interpretarlo con una búsqueda ingenua da el valor
> invertido. Es el error que se cometió sondeando esta pantalla el 16/09/2026,
> y el mismo que ya se había cometido en ISEF07 el 01/09.

## Datos medidos (16/09/2026, periodo 26V05)

| Asignatura / grupo | `Cursos en moodle?` | Qué pasó en ISEF07 |
|---|---|---|
| `DTA32` / `55598` | ❌ no | 🔴 4 estudiantes en rojo, el 07, el 15 y el 16/09 |
| `AED31` / `55522` | ✅ sí | 🟢 verde |
| `DTA05` / `55570` | ✅ sí | 🟢 verde |

`DTA32` tiene 5 grupos en 26V05 (`54423`, `51121`, `54408`, `53336`, `55598`):
el problema es del grupo, no de la asignatura. Por eso la clave de la consulta
es **materia + grupo**, no la materia sola.

## ⚠️ Peligro de esta pantalla

ISEF05 es «Integración Masiva con MOODLE». Debajo de la rejilla tiene un
desplegable **`Actividad`** y una casilla en rojo **«Borra la actividad
seleccionada en MOODLE?»**, con barra de progreso: desde ahí se pueden **borrar
cursos de Moodle en bloque**.

Para consultar no hace falta nada de eso. La regla es: escribir en las cajas de
filtro y leer. **No** seleccionar filas (la primera columna es de selección),
**no** abrir el desplegable `Actividad`, **no** pulsar botones.

`restricciones_sinu.py` mantiene `isef05` en `MODULOS_LEGIBLES` y fuera de
`MODULOS_ESCRIBIBLES`, así que cualquier intento de acción aborta solo.

## Qué hacer con la respuesta

Si `Cursos en moodle?` está sin marcar, **no es un caso a validar**: está
validado. Lo que falta es que alguien **cree el curso en Moodle** para ese
grupo. Hasta entonces, todas las filas de ese grupo van a rojo y no se
intentan.
