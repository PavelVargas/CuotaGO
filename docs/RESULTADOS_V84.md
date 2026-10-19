# Resultados comprobados - V84 / 1.27.0-rc2

Fecha: 19 de octubre de 2026. Copia de trabajo reconstruida del RAR y paquetes
UI79, UI80, restauracion81, iconos82 y V83RC1. Manifiestos previos verificados.
No se accedio ni modifico el repositorio, la base operativa o Railway.

## Ejecutado

- **275 pruebas Python aprobadas**, en 21 procesos/grupos aislados, mediante
  pytest con plugins automaticos desactivados. Incluyen 48 pruebas V84 nuevas.
- Las 6 suites JavaScript previas finalizaron correctamente con `node --test`.
- **89 comprobaciones de DOM e interaccion** con Chromium en 320, 390 y 1440 px,
  incluida una revision oscura: acciones, catalogo, foto local, datos multipart,
  errores, doble pulsacion, totales, recepcion y ausencia de desbordamiento.
- Generacion de orden, conduce y recepcion en el motor PDF de Chromium. Ejemplos
  de una pagina y una prueba larga de 40 lineas por tipo: las 40 aparecieron una
  vez en cada documento, con encabezado de tabla repetido. Se inspeccionaron
  imagenes de las paginas generadas, incluido el salto a otra pagina.
- Compilacion de Python y revision de sintaxis JavaScript.
- Archivos aprobados del inicio y controles de iconos comparados con la base.
  No se modifico el arranque Windows ni su configuracion operativa.

## Correcciones durante las pruebas

La prueba de versiones detecto que dos valores de respaldo seguian apuntando a
RC1; se sincronizaron base.html y app.js con RC2 y el grupo se volvio a ejecutar
correctamente. En app.js solo cambio ese valor de respaldo, no su logica.

El DOM detecto que el campo oculto action podia ocultar la propiedad form.action;
el envio ahora lee el atributo de la URL. Se comprobaron las URL y FormData
resultantes. Se ajustaron la barra movil y el ancho del subtotal para evitar
superposiciones y saltos innecesarios del importe.

## Alcance exacto, no certificacion productiva

Las pruebas de servicio usan las definiciones reales de SQLAlchemy sobre SQLite
con sustitucion del cableado de extensiones. Otras pruebas ejecutan ayudantes
extraidos del codigo y plantillas Jinja con contexto controlado. No equivalen a
levantar Flask ni a validar PostgreSQL.

El navegador no podia acceder a HTTP, ni siquiera al servidor local, por una
politica del entorno. Se renderizaron plantillas con estilos reales e instrucciones
JavaScript reales; se simularon fetch y location. La foto de prueba esta marcada
como tal. No son resultados de comunicacion cliente-servidor real.

Flask y extensiones no estaban disponibles y la instalacion no pudo descargarlas
por falta de acceso a la red. No se sustituyo esa validacion por una afirmacion de
exito. Quedan pendientes la aplicacion completa, CSRF/cookies/roles en HTTP,
concurrencia PostgreSQL, migracion real, Safari/PWA fisica e impresion fisica.

## Reproduccion y evidencia

Usar la opcion 3 del lanzador en una base `_test` preparada. Se agrego
`tests/test_v84_postgres.py` con cuatro casos HTTP/PostgreSQL (todavia no ejecutados
aqui). El ejecutor conserva la puerta de aceptacion de V83: sin esas pruebas,
Node o dependencias de test no declara aprobada la preparacion productiva.

Resultados por grupo y comprobacion: `docs/RESULTADOS_V84.json`.
Casos de depuracion funcional: `docs/DEPURACION_V84.md`.
