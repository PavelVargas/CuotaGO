# CuotaGO UI80 - Pantallas simplificadas

## Base y alcance

Preparado sobre CuotaGO.rar y la entrega UI79 de este chat:
`chatbridge-1-20261019-ui79-f0e68c987f6f49168a4b20ef73c6c92b.zip`.
No se dispuso de un snapshot local posterior para compararlo.
Proyecto ChatBridge: `1b88fec6-3084-49fd-9a42-b047fa387613`.

Esta actualizacion cambia presentacion y control de interacciones. No modifica
modelos, consultas, permisos de servidor, credenciales, .env, migraciones,
calculos financieros ni datos existentes. Se conserva chatbridge-run.bat;
el comando de inicio sigue siendo el mismo.

## Cambios de uso

- Tipografia Manrope para movil/escritorio, con respaldo del sistema. La hoja
  externa de Google Fonts se carga sin bloquear el primer dibujo. No hay archivos
  de fuentes incluidos. Sin acceso a Google se utiliza la fuente de respaldo.
- Inicio: iconos mayores y esquinas mas redondeadas, sin formas circulares.
  En telefonos, tres columnas y desplazamiento natural para no encoger textos.
  El nombre de cada modulo, colores, destino y resumen financiero se conservan.
- Se conserva el menu del inicio de escritorio y los margenes de las secciones.
  En vistas internas, las secciones se agrupan en un menu desplegable. En movil
  se incorporan al menu hamburguesa existente, respetando permisos.
- Reportes: Resumen, Cobros, Resultados e Inventario. Los detalles financieros
  avanzados se despliegan cuando se necesitan. El filtro conserva la vista activa.
  La impresion del navegador expande todos los reportes y restaura la vista luego.
- Acuerdos: lista centrada en cliente, saldo, siguiente pago y mora. Resumen de la
  pagina plegable; creacion conserva sus cuatro pasos. Costo/margen y otros datos
  opcionales plegados. La inicial y su metodo de pago siguen accesibles. Los datos
  completos del acuerdo permanecen en su detalle.
- Compras: Proveedor -> Articulos -> Confirmar, en ambas vistas. Puede mezclar
  inventario existente y articulos nuevos. Volver no pierde valores, los campos
  invalidos impiden avanzar y el guardado tiene bloqueo de doble envio. Los nombres
  de campos repetidos no cambian y los valores permanecen alineados para getlist.
- Clientes, inventario, ventas y gastos: filtros/datos secundarios plegados, datos
  principales visibles, menos instrucciones repetidas. Inventario mantiene visible
  la cantidad para productos; datos individuales de vehiculos usan su logica previa.
  Historiales y notas secundarias se despliegan sin eliminar informacion.
- Ajustes: Apariencia, Notificaciones, Cuenta y negocio, Contrasena y Administracion.
  Se conservan las funciones, controles de permisos y formularios originales.

## Pruebas de sonido y notificaciones

Probar sonido solo prueba el tono dentro de la app. Se reutiliza un AudioContext;
no se crean secuencias paralelas por pulsaciones repetidas. El boton permanece
ocupado durante toda la secuencia, incluida la intensidad doble. Un audio que no
reanuda en 2.5 segundos libera el control con un mensaje. Cambiar preferencias,
ocultar la app o abandonar la pagina cancela la reproduccion pendiente.

Enviar prueba, dentro de Avisos con la app cerrada, conserva la prueba Push
existente. Tiene bloqueo compartido, una sola vista previa, tiempo limite de
suscripcion/envio y breve espera antes de reintentar. Un permiso que responde
fuera del tiempo limite no desencadena posteriormente el envio de prueba.
Estos controles no sustituyen permisos ni volumen del sistema operativo.

## Validacion ejecutada

- 51 plantillas Jinja analizadas sin errores de sintaxis.
- 101 pruebas Python de interfaz, contratos, rendimiento y helpers del negocio.
  No es la suite de integracion con PostgreSQL.
- 45 comprobaciones del motor de sonido anterior.
- 32 comprobaciones nuevas de sonido: pulsaciones multiples, contexto unico,
  silencio, cancelacion, reanudacion bloqueada, limpieza y recuperacion.
- 22 comprobaciones del manejador de notificacion de prueba con servicios falsos.
- 12 pruebas de Service Worker y 8 de ciclo de vida de contadores.
- 32 vistas renderizadas con plantillas reales, datos sinteticos y recursos locales,
  sin errores JavaScript ni desbordamiento horizontal del documento.
- 135 comprobaciones de interaccion en Chromium: pasos, validacion, cambio de
  vistas, teclado, impresion, menu, sonido y tamanos de 320 a 1440 pixeles.
- Conservacion de los nombres/cantidad de campos de formularios y de todas las
  expresiones monetarias del reporte frente a UI79.

Limitaciones: no se uso la base del usuario ni un telefono fisico; no se envio un
Push real. Las pruebas de navegador bloquean la red, por lo que las capturas usan
el respaldo tipografico, no verifican la descarga externa de Manrope. Las pantallas
usan datos artificiales. Las nuevas pruebas no se ejecutan durante el inicio normal.

## Repetir comprobaciones (desarrollo)

Pruebas de sonido con Node, sin instalar paquetes de JavaScript:

```
node tests/test_notification_audio_v79.cjs
node tests/test_notification_audio_v80.cjs
node tests/test_notification_demo_v80.cjs
node tests/test_service_worker_runtime.cjs
node tests/test_badge_lifecycle.cjs
```

Los scripts de navegador son opcionales: requieren Playwright, BeautifulSoup,
Jinja2 y Chromium en el entorno de pruebas. CHROMIUM_EXECUTABLE permite indicar
la ruta al navegador; sin ella se busca Chromium o el navegador de Playwright.
No son dependencias adicionales de la aplicacion.

```
python tests/ui80_layout_checks.py
python tests/ui80_browser_checks.py
```

Los resultados se escriben en test-output/ui80; no forman parte del paquete.
