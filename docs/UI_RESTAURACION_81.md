# UI81 - Restauracion de la interfaz anterior

Base: CuotaGO.rar + UI79 + UI80, los archivos disponibles en este chat.
Este paquete revierte la capa visual y los flujos introducidos por UI80.
No utiliza los prototipos/capturas de intentos cancelados como codigo fuente.

## Resultado

- Inicio PWA y navegador movil: CUATRO columnas. Nunca tres columnas para
  la parrilla principal de modulos, tampoco en tablet o al cambiar orientacion.
- Se recuperan las plantillas completas anteriores de Reportes, Acuerdos,
  Inventario, Clientes, Ventas, Gastos, Compras y Ajustes.
- Compras recupera el formulario completo anterior, no el asistente UI80.
- Se restaura la navegacion directa de escritorio y el menu movil de UI79.
- Se mantienen los margenes laterales de escritorio, el orden de modulos,
  sus colores y formas UI79, el modo oscuro, las metricas y la agenda.
- Se elimina Manrope y vuelve la pila tipografica de UI79.
- Se retiran simple-v80.css, simple-v80.js y purchases-v80.js, sus referencias,
  el documento del rediseno y las pruebas especificas de ese rediseno.

## Correcciones no visuales conservadas

- Motor de sonido y bloqueo de pruebas repetidas, con liberacion por tiempo
  limite o salida de la pagina. Se conservan sus pruebas automatizadas.
- Zoom accesible disponible. No se restituyen bloqueos globales de gestos.
- El formulario de Compras determina si hay inventario directamente desde
  assets en su bloque de scripts: una variable local de otro bloque Jinja
  no puede usarse como fuente de esa decision.
- Nuevo identificador de recursos restore81 para no reutilizar el CSS de UI80.
  No se eliminan preferencias, localStorage, bases de datos ni suscripciones.

## Contrato para futuros cambios

1. La parrilla de modulos del inicio PWA no puede tener tres columnas.
   La regla final esta en layout-v79.css y tiene pruebas de regresion.
2. Conservar estructura, permisos, informacion financiera, filtros, acciones,
   formularios y funciones de un sistema completo.
3. No convertir los modulos en versiones reducidas ni ocultar secciones
   completas bajo pestanas o acordeones sin autorizacion expresa.
4. No cambiar el menu de escritorio ni el orden de modulos por iniciativa propia.
5. Las mejoras visuales posteriores deben ser acotadas, no otro rediseno global.

## Alcance y validacion

- No se modifican main.py, models.py, permisos, calculos financieros, la base
  PostgreSQL, credenciales ni configuracion del servidor.
- chatbridge-run.bat y el arranque Windows existentes se conservan sin cambios.
- 78 pruebas Python seleccionadas aprobadas; las advertencias existentes
  sobre datetime.utcnow de las pruebas de SQLAlchemy no son fallos.
- 99 comprobaciones JS de sonido/pruebas de notificacion aprobadas.
- 128 comprobaciones de navegador aprobadas, sin errores JavaScript capturados.
  Incluyen 14 tamanos/orientaciones PWA, preferencias de iconos antiguas/nuevas,
  12 vistas en movil/escritorio, navegacion y lineas de compra con totales.
- La revision del navegador utilizo plantillas reales, recursos locales
  incrustados y datos/respuestas de prueba en Chromium. No ejecuta Flask ni
  usa PostgreSQL, no prueba un telefono fisico ni envia Push reales.
- El manifest y todos los SHA-256 del ZIP se verifican contra sus bytes.

Comando de regresion sin PostgreSQL:

```sh
python -m pytest -q tests/test_launcher_ui_contract.py tests/test_layout_v79.py tests/test_workspace_ui.py tests/test_agreement_motion_ui.py tests/test_sales_ui_contract.py tests/test_pwa_performance.py tests/test_sw_performance.py tests/test_ui_restoration_v81.py
node tests/test_notification_audio_v79.cjs
node tests/test_notification_audio_v80.cjs
node tests/test_notification_demo_v80.cjs
```

Las dos pruebas de sonido con sufijo v80 se conservan porque verifican la
correccion de concurrencia, no porque se mantenga la interfaz UI80.
