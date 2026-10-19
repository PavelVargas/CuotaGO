# UI82 - Iconos y bordes del Inicio

Base: CuotaGO.rar + UI79 + UI80 + restore81, entregados en este chat.

## Alcance

- Iconos del Inicio mas grandes. Las tarjetas crecen dentro de su columna.
- Se conserva el contrato UI81: cuatro columnas en celular y PWA. La distribucion de escritorio no cambia.
- Se mantienen nombres, orden, colores, menus, resumen inferior y tipografia.
- Ajustes > Preferencias > Iconos del inicio: tamano 76-100%, esquinas 16-36%, vista previa y Restablecer.
- Valores iniciales: tamano 96%, esquinas 30%. El radio maximo no llega al 50% de un circulo.
- El porcentaje de tamano se refiere al espacio disponible, con un limite de 112 px para no producir iconos desproporcionados en escritorio/tablets.

## Guardado

Preferencia local del dispositivo/navegador: `cuotago-launcher-appearance-v1`.
La vista previa responde al mover cada deslizador y el valor se guarda al terminar el gesto. El cambio de una preferencia conserva la otra.
Se conserva una eleccion antigua deliberada de tamano, sin modificar la clave antigua. El anterior valor inicial de 72 px usa el nuevo valor inicial.
Restablecer afecta solo a tamano y esquinas, nunca a tema, sonidos, permisos ni datos del negocio.
Si el navegador bloquea el almacenamiento, la interfaz sigue funcionando y muestra que no fue posible guardar.
La restauracion de pagina al volver atras y los cambios entre pestanas releen las preferencias.

## Implementacion

`_launcher_preferences.html` es la unica fuente de lectura, normalizacion y aplicacion. Se ejecuta antes de los estilos sin una solicitud adicional para evitar parpadeo al iniciar.
`launcher-v82.css` solo modifica la geometria de los iconos del Inicio y la seccion de preferencias nueva. No cambia las pantallas de Reportes, Acuerdos, Compras u otros modulos.
Se retira el controlador antiguo que limitaba el tamano a 78 px y podia sobrescribir el nuevo ajuste.
Los recursos usan el sufijo `-restore81-icons82`; el CSS nuevo queda incluido en el cache del service worker.
No hay cambios de base de datos, dependencias, credenciales ni arranque. `chatbridge-run.bat` sigue intacto.

## Verificacion

- 60 pruebas pytest: integracion, plantillas, navegacion, launcher, restauracion y regresion.
- 22 pruebas Node del controlador real: limites, migracion, valores corruptos, cambios independientes, guardado, restablecer, navegacion atras y almacenamiento bloqueado.
- Pruebas existentes de sonido y notificacion de ejemplo: correctas.
- Chromium: plantillas/estilos/scripts reales en paginas de prueba aisladas, sin red. Diez combinaciones de pantalla/modo, desde 320x568 hasta 1440x900, incluyendo PWA horizontal y modo claro/oscuro. Comprobados tamano maximo, columnas, separacion de iconos, menu y resumen inferior, controles y restauracion.
- Datos y almacenamiento simulados en las pruebas de navegador. No se ejecuto PostgreSQL, un iPhone fisico ni una prueba Push real.
