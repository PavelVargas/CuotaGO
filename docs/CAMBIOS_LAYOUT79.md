# CuotaGo - Layout79 (19 de octubre de 2026)

## Base de esta entrega

Copia disponible: CuotaGO.rar, subida a la Biblioteca el 19 de octubre de 2026.
Version declarada por esa copia: 1.26.8 / 1.26.8-ui-v78.
No se tuvo acceso al snapshot chatbridge-context-1-20261019-121424.zip ni se
pudo comparar esta copia con el ultimo estado del repositorio remoto.

## Cambios

- Escritorio: el menu conserva su estructura y ancho. El contenido de las
  secciones se centra con margenes laterales: 90% desde 1024 px, maximo 1440 px;
  formularios estrechos hasta 1080 px. Las tablas anchas desplazan su propio
  contenido, sin ensanchar la pagina.
- Tipografia nativa del dispositivo, sin peticiones a Google Fonts. Mejora de
  tamanos de campos, registros y nombres de modulos. No se distribuyen fuentes.
- Movil/PWA: iconos de modulos con esquinas suaves (no circulos), solo nombre
  del modulo, mismo orden, colores, permisos y resumen inferior.
- Menu movil: un boton hamburguesa sustituye los accesos flotantes separados.
  Conserva Buscar, Notificaciones, Inicio, Configuracion, tema y cerrar sesion.
  Se reutiliza el dialogo nativo con cierre por Escape, boton y fondo. Se corrige
  la antigua regla que ocultaba el dialogo en Inicio incluso estando abierto.
- Sonidos: Clasico, Cristal, Suave y Pulso; volumen 0-100%; intensidad suave,
  normal o fuerte (doble aviso). Preferencias por cuenta y dispositivo.
  Probar sonido no solicita permisos push ni envia notificaciones remotas.
- Ventas movil: se restaura la cuadrilla de dos columnas que una regla de
  escritorio sobrescribia. Los filtros y datos no se salen de la pantalla.
- Sufijo local de recursos '-layout79' para actualizar CSS/JavaScript y el
  service worker sin modificar .env, config.py ni las versiones del backend.

## Alcance del sonido

Estos controles afectan al sonido dentro de la app abierta. El volumen general,
el modo silencio y el sonido de las notificaciones con la app cerrada dependen
del telefono o navegador. 0% no desactiva los avisos visuales ni las alertas push.
Los tonos se sintetizan localmente con Web Audio; no necesitan descargas.
No se supera la ganancia unitaria; se limita la amplitud y se suavizan los picos.

## Comprobaciones realizadas

- 71 pruebas de contratos de interfaz, recursos, permisos y logica aislada.
- 45 aserciones del motor de audio: cuatro tonos, intensidad doble, silencio,
  limites de volumen, preferencias invalidas, almacenamiento bloqueado, cuenta
  separada, contexto suspendido, deduplicacion y liberacion de nodos.
- Renderizado de las plantillas reales con datos sinteticos en Chromium:
  Inicio, Clientes, Ajustes, Ventas e Inventario; escritorio y PWA emulada,
  modo claro y oscuro, incluyendo anchos de 320, 390, 667, 768, 1024, 1366,
  1440 y 1920 px. Se comprobo el menu abierto/cerrado y el desplazamiento.
- La prueba de sonido activo Web Audio en Chromium y persistio los ajustes
  en el almacenamiento simulado del banco de pruebas.

La navegacion de Chromium en este entorno estaba restringida. Para validar la
interfaz se renderizaron las plantillas con sus recursos reales embebidos;
las peticiones de red y el almacenamiento se simularon en esas pruebas.
No se ejecuto la aplicacion completa con PostgreSQL, no se tocaron datos reales
ni se probo la entrega push en un iPhone/Android fisico. Esas comprobaciones
siguen pendientes en el entorno del usuario.

## Archivos que permanecen intactos

Conexion a PostgreSQL, .env, config.py, VERSION.txt, modelos, rutas de negocio,
permisos y requisitos de instalacion. Se conserva el chatbridge-run.bat existente
en la raiz, que inicia este proyecto mediante INICIAR_WINDOWS.bat.
