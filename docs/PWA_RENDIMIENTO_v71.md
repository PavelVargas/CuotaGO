# CuotaGo v1.26.1 / ui-v71 - Correccion de rendimiento de la PWA

## Base y alcance

Parche contra v1.26.0 / ui-v70, reconstruida desde el snapshot
`chatbridge-context-6-20261005-010004.zip` y los parches posteriores de esta
conversacion. Se verificaron los manifests y hashes de los parches de entrada.
No se conecto al servidor del cliente ni se modificaron registros reales.

El objetivo es reducir tareas repetidas durante la navegacion, sin eliminar
modulos, fotografias, permisos, controles financieros ni el diseno aprobado.
No se incluye una migracion de esquema ni nuevas dependencias de la aplicacion.
El lanzador Windows existente mantiene su funcionamiento.

## Hallazgos y cambios

### Campana y consultas de fondo

El inicio de cada pagina solicitaba la lista completa de hasta 500 avisos para
actualizar un contador. Esa ruta tambien sincronizaba moras. Ahora el contador
utiliza `/api/notifications?summary=1`: dos consultas agregadas de solo lectura,
sin cargar clientes, productos, cuerpos de notificacion o historiales, y sin
solicitar bloqueos de escritura.

La lista completa sigue disponible al abrir el centro de notificaciones. La
campana reutiliza solamente un numero y una fecha durante un maximo de 90
segundos en la PWA (60 en escritorio), separados por usuario en sessionStorage.
No se guardan saldos, contactos ni importes en ese cache. El envio de formularios
y los mensajes push invalidan el numero; se cancela cualquier respuesta antigua
que pudiera reponer un contador obsoleto. Las consultas se detienen al ocultar
la pagina y al salir de ella, y tienen cancelacion y limite de espera.

### Moras y transacciones

`sync_contract_late_fees` comprueba primero si hay un importe que actualizar.
Una lectura de cuotas con la mora ya actualizada no necesita bloquear el
vehiculo ni volver a cargar todo su historial. Cuando hay una modificacion real,
se mantiene el bloqueo existente y se vuelve a calcular con los datos recien
leidos bajo ese bloqueo. No se sustituyen las transacciones por datos del cache.
Las fechas de activacion, pagos y reglas de calculo previas se conservan.

### Fotografias y recursos publicos

La ruta de miniaturas selecciona directamente la miniatura en la misma consulta
de metadatos. Antes tambien leia el archivo completo de la base de datos aunque
solo se hubiera pedido `thumb=1`. Las imagenes antiguas que no tengan miniatura
conservan su conversion diferida; las fichas y el producto seleccionado conservan
la imagen grande. Las tarjetas pequenas de ventas ya no eligen la foto completa
solo por la densidad de pixeles del telefono.

Las fotos siguen siendo privadas, con autenticacion, permiso y filtro por
organizacion. Solo CSS, JavaScript y otros recursos publicos conocidos evitan la
resolucion innecesaria de usuario/suscripcion. Para las peticiones privadas, la
carga del usuario anticipa su organizacion y suscripcion en una misma consulta.

### Desplazamiento y animaciones

El gesto de actualizar usa escuchas pasivas: no cancela el desplazamiento del
navegador. Ignora controles y listas con desplazamiento propio. Se comprueba que
el gesto comience arriba y sea vertical antes de mostrar el indicador.

Se eliminan las transiciones de captura de toda la pagina. Se mantienen entradas
breves en encabezados pequenos, cancelables al tocar, y la preferencia de
reducir movimiento. No se anima toda la ficha ni se retrasa el cambio de pagina.
El codigo de animaciones se carga diferido. Los ajustes de posicion del rail de
Inicio se agrupan por fotograma y solo escriben estilos si cambia la posicion.
El splash deja de esperar a todas las fotos/fuentes para mostrar la pantalla.

### Service worker y modo sin conexion

La precarga se limita a cuatro recursos simultaneos, en vez de lanzar todos a
la vez. Los recursos versionados reutilizan cache. La entrega de un recurso
estatico no espera a la escritura opcional en disco. Se evita registrar de
nuevo el mismo worker desde cada pagina; las comprobaciones explicitas del
worker existente se espacian. El limite de espera de navegacion incluye la
respuesta precargada, que antes podia esperar sin limite.

La pantalla sin conexion es un documento neutral, sin barra del usuario, datos
del negocio ni consultas de notificaciones. No se guardan paginas financieras,
respuestas de API, fotos privadas ni comprobantes en el cache del worker. Esta
optimizacion no habilita registrar operaciones financieras sin conexion.

## Comprobaciones ejecutadas

- 107 pruebas pytest aprobadas en las suites aisladas seleccionadas. Incluyen
  dos pruebas lanzadoras que ejecutan 20 casos JavaScript en Node (12 del worker
  y 8 del ciclo de vida de la campana). No sumar esos 20 como pruebas pytest
  independientes. Se observaron 85 advertencias existentes de `datetime.utcnow`.
- Consultas reales de SQLAlchemy sobre SQLite aislado: resumen mediante dos
  SELECT, aislamiento por organizacion, limites de avisos, y miniatura sin
  seleccionar el campo de imagen original. SQLite no verifica los bloqueos de
  PostgreSQL; las pruebas de recomputo usan dobles de transaccion.
- 58 comprobaciones en Chromium con HTML real renderizado localmente, recursos
  embebidos y API/almacenamiento simulados. Incluyen 18 vistas a 320, 390 y 1366
  pixeles, ausencia de errores JS/desbordamientos horizontales, movimiento
  reducido y desplazamiento mediante eventos tactiles nativos enviados por CDP.
- En cuatro inicializaciones de pagina del ensayo: cuatro peticiones completas
  de notificaciones antes, una peticion de resumen despues. No es una medicion
  de tiempos reales de navegacion ni una promesa porcentual de velocidad.
- En Inicio del mismo ensayo: cinco escrituras de posicion del rail antes, una
  despues. Las animaciones verificadas no usan superficies mayores de 320px de
  altura.
- Sintaxis validada: 32 archivos Python, 51 plantillas Jinja y 8 archivos JS en
  ese momento (incluidos los dos archivos de pruebas JavaScript).

Comando de pruebas reproducible, desde la raiz y con dependencias de desarrollo:

```sh
python -m pytest -q tests/test_pwa_performance.py tests/test_sw_performance.py tests/test_agreement_motion_ui.py tests/test_launcher_ui_contract.py tests/test_sales_ui_contract.py tests/test_dealer_transactions.py tests/test_dealer_workflows.py tests/test_dealer_document_queries.py
```

Node solo se usa en pruebas opcionales; no es necesario para arrancar CuotaGo.
Si no esta instalado, las dos pruebas lanzadoras lo indican como omitido.

## Limites de la verificacion

No se pudo ejecutar la aplicacion Flask completa en este entorno ni acceder a
PostgreSQL. La navegacion HTTP del navegador de pruebas esta bloqueada por la
politica del entorno, por lo que se uso renderizado local; los casos del worker
usan dobles de red/cache, no una instalacion real del service worker. No se
probaron un iPhone/Android fisicos, Railway, la red del cliente ni la velocidad
real con su volumen de datos. No se afirma que toda lentitud quede resuelta.

Despues de que ChatBridge aplique el ZIP y la version quede publicada, cerrar y
volver a abrir la PWA permite cargar la nueva version. No es necesario borrar
los datos ni reinstalar la aplicacion. Si sigue habiendo demoras, diferenciar
entre el desplazamiento que se traba y la espera al abrir un modulo, indicando
el dispositivo y si se usa el servidor local o el despliegue publicado. El
servidor conserva `Server-Timing` y el registro de peticiones lentas existentes
para esa comprobacion posterior.
