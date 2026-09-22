# CuotaGo MOBILE PWA v1.14.3 · PostgreSQL + Railway

Esta version mantiene PostgreSQL/Railway y prioriza una UX PWA mas directa, con launcher compacto y acuerdos guiados paso a paso.

> Para GitHub/Railway, `.env` sigue ignorado. Conserva tu `.env` local y configura los secretos desde Variables en Railway.


## Cambios v1.14.3

- **Nuevo módulo Documentos:** añade una guía de uso dentro de CuotaGo, accesible desde el launcher principal.
- **Guía sincronizada con los módulos:** Inicio y Documentos consumen el mismo catálogo interno, evitando que el manual quede desactualizado al ampliar el sistema.
- **Manual práctico y buscable:** incluye inicio rápido, pasos por módulo, recomendaciones, enlaces directos y buscador por palabras clave.
- **Launcher mantenible:** los módulos del inicio ya no están duplicados a mano en la plantilla; se generan desde el catálogo central.
- **PWA:** caché de interfaz actualizada a `1.14.3-ui-v32`.

## Cambios v1.14.2

- **Compras por órdenes:** registra proveedor, fecha, referencia, varios artículos, cantidades y costo unitario en una sola orden. La compra aumenta automáticamente la existencia.
- **Proveedores reutilizables:** el proveedor es obligatorio; puede seleccionarse de la lista o crearse sin salir de la orden.
- **Compras no cambia el precio de venta:** una reposición solo actualiza costo promedio y stock. El precio objetivo sigue administrándose desde Inventario.
- **Costo y venta separados:** Inventario ahora distingue cuánto costó cada unidad de cuánto se venderá, mostrando margen estimado por producto.
- **Margen precargado en Acuerdos:** al elegir un producto, CuotaGo toma el costo registrado y usa el precio objetivo para precargar el porcentaje de ganancia; todavía puede ajustarse para un acuerdo específico.
- **Rentabilidad en Reportes:** el panel muestra margen de ganancia, ganancia esperada, valor del inventario a costo, venta estimada, ganancia potencial e inversión del periodo en Compras.
- **Compatibilidad con datos anteriores:** `estimated_value` conserva el costo/base histórico usado por los acuerdos existentes; `sale_price` agrega el precio objetivo sin romper contratos previos.
- **Superadmin:** al vaciar/eliminar una empresa también se limpia el historial de Compras y se puede limpiar ese módulo de forma independiente.

## Cambios v1.13.0

- **Superadmin reorganizado:** el listado principal ya no mezcla empresas con botones destructivos. Ahora hay navegación separada para **Resumen, Planes y Actividad**.
- **Suscripciones reales por empresa:** plan, estado, precio personalizado, inicio de periodo, vencimiento, periodo de gracia y nota interna. Los estados `suspended`, `cancelled` y `expired` bloquean el acceso operativo conservando los datos.
- **Cobros de suscripción:** el superadmin registra pagos, método, referencia y periodo cubierto. Cada pago renueva las fechas y queda en historial; si hubo un error, se **anula** sin borrar el rastro de auditoría.
- **Planes administrables:** crear, editar, archivar y reactivar planes sin romper suscripciones históricas. No se inventan planes ni precios al instalar.
- **Panel comercial:** KPIs de empresas, suscripciones activas, MRR estimado en DOP, cobrado del mes, renovaciones próximas y cuentas que requieren atención.
- **Directorio profesional:** búsqueda por empresa/propietario/correo, filtros por estado y plan, orden por renovación y exportación CSV.
- **Soporte de usuarios:** crear y editar usuarios, corregir correo/rol, bloquear o habilitar accesos, ver último login y restablecer una contraseña temporal sin guardar el valor en auditoría.
- **Auditoría administrativa:** cambios de planes, suscripciones, pagos, usuarios y borrados quedan registrados con fecha, actor y detalle.
- **Mantenimiento seguro:** limpiar módulos, vaciar una empresa o eliminarla está fuera del listado principal. Las operaciones sensibles exigen escribir el nombre exacto de la empresa; eliminar además exige confirmación explícita.
- **Alta de clientes desde superadmin:** se puede crear empresa + propietario + suscripción inicial desde una sola pantalla.
- Se conservan el launcher PWA, acuerdos guiados, calendario, inventario por cantidad, mora configurable, recordatorios Push repetidos, reportes y modo oscuro.

## PostgreSQL local configurado

Esta entrega conserva la aplicación v1.8 y cambia únicamente la persistencia local a PostgreSQL. Está configurada con:

- host: `127.0.0.1`
- puerto: `5432`
- usuario: `postgres`
- clave: la definida en tu `.env` local
- base: `cuotago`

Primero ejecuta `COMPROBAR_POSTGRES.bat`. Si muestra PostgreSQL OK, inicia normalmente con `INICIAR_WINDOWS.bat`.

## Lo que ya funciona

- Registro de propietario y login con contraseña cifrada.
- Cada cuenta trabaja dentro de su propio negocio/organización.
- Inicio tipo launcher, sin sidebar, con tarjetas grandes e iconos dominantes en una cuadrícula móvil 2×4.
- Clientes: alta, búsqueda y edición.
- Bienes: vehículos, celulares, motores, computadoras, electrodomésticos y otros.
- IMEI/placa/identificador, serial, marca, modelo, valor y notas.
- Venta a crédito o préstamo/alquiler.
- Inicial, número de cuotas y frecuencia semanal/quincenal/mensual; el monto de cada cuota se calcula automáticamente.
- Generación automática del calendario de cuotas.
- Pagos parciales o completos y aplicación automática a las cuotas más antiguas.
- Estado del acuerdo y estado del bien actualizados al completar el saldo.
- Cobros vencidos, de hoy y próximos.
- Calendario completo de cuotas pendientes, incluyendo vencidas, hoy y todas las fechas futuras.
- Botón de WhatsApp con mensaje de cobro prellenado.
- Reportes de saldo por cobrar, vencido y cobrado en el mes.
- PWA instalable con manifest, service worker, iconos y pantalla offline.
- Centro de **Notificaciones** independiente con vencidos, pagos de hoy y próximos 7 días; cada alerta abre directamente el acuerdo/cobro correcto.
- Alertas dentro de CuotaGo con banner, sonido y vibración cuando el dispositivo la soporte; funcionan también en la demo local HTTP mientras la app está abierta.
- Web Push real para avisos con la PWA cerrada cuando el despliegue tenga HTTPS, con prueba desde Ajustes.
- Sonido de notificación del sistema; en Android también se solicita vibración.
- Interfaz móvil con pinch/doble-tap/focus zoom desactivados para sensación nativa.
- Responsive para PC, tablet y móvil; se retiró la barra inferior para dejar más espacio útil y una navegación más limpia.
- `/healthz` para comprobar que aplicación y base de datos están vivas.
- Headers básicos de seguridad y soporte correcto detrás de proxy/reverse proxy.

## Opción 1 — Windows, sin Docker

Esta es la forma más rápida para comenzar.

1. Descomprime el ZIP.
2. Entra a la carpeta de CuotaGo v1.14.3.
3. Haz doble clic en `INICIAR_WINDOWS.bat`.
4. El script crea `venv`, instala dependencias, comprueba `.env` y la base de datos, y arranca la aplicación.
5. Abre `http://127.0.0.1:5000`.
6. Pulsa **Crear cuenta** y registra el propietario real.

La aplicación local usa PostgreSQL directamente. Conserva tu `.env` actual o crea uno desde `.env.example` con esta conexión:

`postgresql+psycopg://postgres:TU_CLAVE@127.0.0.1:5432/cuotago`

Debe estar iniciado PostgreSQL y debe existir la base `cuotago`. Las tablas de CuotaGo se crean automáticamente al primer arranque. No hay usuario de demostración: la primera cuenta la crea el propietario desde Registro.


## Demo local en tu negocio (sin hosting)

Para enseñarle CuotaGo a un cliente en tu local **no necesitas subirla a Internet**. En Windows ejecuta:

`DEMO_LOCAL_WINDOWS.bat`

El script detecta la IP local de la PC y te muestra una dirección similar a:

`http://192.168.1.25:5000`

Conecta el iPhone/Android y la PC a la misma Wi-Fi y abre esa dirección en el teléfono. La aplicación, login, clientes, acuerdos, cobros y reportes funcionan localmente. Las notificaciones Push con la PWA cerrada son la única función que queda pendiente hasta disponer de HTTPS.

En modo local, la pantalla Inicio no muestra banners de Push. El centro **Notificaciones** sí funciona y muestra vencidos/hoy/próximos; la configuración de Push del teléfono vive en **Ajustes → Alertas del teléfono**.

## Opción 2 — Docker + PostgreSQL real

Requiere Docker Desktop iniciado.

Haz doble clic en:

`INICIAR_DOCKER.bat`

O desde PowerShell:

```powershell
docker compose up -d --build
```

La aplicación queda en:

`http://127.0.0.1:8080`

El estado se puede comprobar en:

`http://127.0.0.1:8080/healthz`

Docker Compose levanta dos servicios:

- `app`: Flask + Gunicorn.
- `db`: PostgreSQL 17 con volumen persistente `cuotago_postgres_data`.

Para detenerlos sin borrar los datos:

```powershell
docker compose down
```

También puedes usar `DETENER_DOCKER.bat`.

## `.env` incluido

El proyecto ya trae un `.env` funcional. Contiene:

- `SECRET_KEY` única generada para este ZIP.
- conexión PostgreSQL local: usuario `postgres`, base `cuotago`, puerto `5432`;
- moneda DOP;
- zona horaria `America/Santo_Domingo`;
- credenciales PostgreSQL generadas para Docker Compose.

No subas `.env` a GitHub. Ya está incluido en `.gitignore` y `.dockerignore`.

## Producción / Railway

El `Dockerfile` arranca con Gunicorn y escucha el puerto entregado en `PORT`. Para Railway, crea un servicio PostgreSQL y configura como variables del servicio de la app:

```text
APP_NAME=CuotaGo
APP_VERSION=1.14.3
APP_ENV=production
APP_CURRENCY=DOP
APP_TIMEZONE=America/Santo_Domingo
SECRET_KEY=<una clave privada de producción>
DATABASE_URL=<la URL privada de PostgreSQL de Railway>
AUTO_CREATE_DB=1
FLASK_DEBUG=0
COOKIE_SECURE=1
PUSH_NOTIFICATIONS_ENABLED=1
PUSH_SCHEDULER_ENABLED=1
PUSH_CHECK_INTERVAL_MINUTES=5
PUSH_ALERT_START_HOUR=8
PUSH_ALERT_END_HOUR=22
PUSH_OVERDUE_REPEAT_HOURS=4
VAPID_SUBJECT=mailto:admin@cuotago.app
VAPID_PUBLIC_KEY=<copiar del .env incluido>
VAPID_PRIVATE_KEY_B64=<copiar de tu .env local>
```

En producción conviene reemplazar la `SECRET_KEY` del ZIP por una clave exclusiva del servidor y mantenerla únicamente en las variables privadas del hosting.

### Recordatorios Push de cobros vencidos

CuotaGo revisa las deudas cada `PUSH_CHECK_INTERVAL_MINUTES` minutos. Una cuota que vence hoy genera un aviso normal; cuando ya está vencida, el cobrador recibe un recordatorio repetido mientras siga pendiente. Por defecto se repite cada `PUSH_OVERDUE_REPEAT_HOURS=4` horas, únicamente entre `PUSH_ALERT_START_HOUR=8` y `PUSH_ALERT_END_HOUR=22`. Al registrar el pago, la cuota deja de ser candidata y los recordatorios paran automáticamente. El mismo registro de Push se reutiliza, por lo que no crece una fila nueva en la base de datos por cada repetición.

## Comprobar la instalación

Después de instalar las dependencias:

```powershell
python scripts\doctor.py
```

Debe terminar mostrando:

```text
[OK] .env cargado
[OK] Base de datos accesible: ...
[OK] App: CuotaGo v1.14.3
[OK] CuotaGo esta listo para iniciar.
```

## Pruebas

Las pruebas automatizadas del flujo registro → cliente → bien → acuerdo → pago están en `tests/test_app.py`.

```powershell
python -m pip install -r requirements-dev.txt
pytest -q
```

## Archivos principales

- `app.py`: entrada local.
- `.env`: configuración real incluida.
- `config.py`: configuración de Flask/DB/cookies.
- `cuotago/models.py`: datos y relaciones.
- `cuotago/auth.py`: registro, login y logout.
- `cuotago/main.py`: clientes, bienes, acuerdos, cuotas, cobros, calendario y reportes.
- `cuotago/templates/`: interfaz.
- `cuotago/static/`: CSS, JS, iconos y PWA.
- `docker-compose.yml`: app + PostgreSQL.
- `Dockerfile`: imagen de producción.
- `scripts/doctor.py`: diagnóstico de instalación.

## Alcance de esta primera versión

Ya permite trabajar el flujo central de negocio. La siguiente fase natural sería agregar contrato PDF, fotos/documentos del cliente y del bien, firma, comprobantes de pago, usuarios/roles, historial de gestiones y recordatorios automáticos programados.

## Mobile/PWA v1.7

Esta revisión prioriza el uso diario desde iPhone y Android:

- interfaz **mobile-first** en todas las vistas;
- navegación móvil simplificada sin barra inferior fija, conservando safe areas (`env(safe-area-inset-*)`);
- formularios con controles táctiles de 44–48 px y fuente de 16 px en móvil para evitar el zoom automático de Safari;
- login y registro rediseñados alrededor del icono real de la PWA;
- splash HTML warm-white que se muestra **solo en el primer arranque de la PWA por sesión**; las navegaciones internas ya no repiten el splash;
- splash screens nativos para tamaños modernos de iPhone; incluso la variante asociada al modo oscuro usa fondo claro para evitar el arranque negro;
- modo claro, oscuro y “seguir sistema”, persistido por dispositivo;
- listas/tablas convertidas en tarjetas legibles en móvil;
- menú de usuario tipo bottom sheet en móvil;
- service worker v1.7 sin guardar páginas autenticadas en Cache Storage;
- manifest con accesos rápidos a Nuevo acuerdo, Notificaciones, Cobros y Clientes;
- indicador de conexión y pantalla offline segura.


### Cambios de simplicidad de v1.3

- **Nuevo acuerdo en una sola pantalla:** si el cliente o el bien no existen, se crean dentro del mismo formulario; ya no hay que salir a Clientes o Bienes primero.
- El flujo principal pide solo cliente, bien, total, cuota, frecuencia y primer pago; inicial, fecha de entrega y notas quedan en **Más opciones**.
- En **Cobros**, el botón **Cobrar** registra la cuota completa directamente sin obligar a abrir el acuerdo.
- La ficha del acuerdo pone **Registrar cobro** antes del calendario y deja detalles/historial plegados.
- Formularios de Cliente y Bien muestran primero los datos esenciales y esconden el resto en **Más datos**.
- Logo/PWA actualizado al nuevo icono naranja de billetera con check, usado en login, barra superior, iconos de instalación y splash.

Los splash screens se pueden regenerar después de instalar `requirements-dev.txt`:

```powershell
python -m pip install -r requirements-dev.txt
python scripts\generate_pwa_splash.py
```

## v1.4 · alertas push y PWA sin zoom

Esta version agrega Web Push real para la PWA. En Ajustes -> Alertas de cobro, el usuario puede activar notificaciones y ejecutar una prueba. Cuando una cuota queda vencida, el servidor revisa los atrasos cada 5 minutos y envia una alerta al dispositivo registrado. El toque de la notificacion abre directamente el acuerdo correspondiente.

El paquete incluye una pareja VAPID unica en `.env`, `pywebpush`, un scheduler interno y tablas nuevas (`push_subscriptions` y `push_notification_logs`). `db.create_all()` crea esas tablas automaticamente al iniciar una base existente sin borrar datos.

Para evitar duplicar schedulers, Gunicorn queda configurado con un solo worker y varios threads. Si en el futuro se escala a varias instancias, conviene mover el chequeo de vencimientos a un worker/cron separado.

En Android se solicita vibracion y la notificacion usa el sonido del sistema. En iPhone/iPad, Web Push usa el sonido/haptico que iOS permita segun la configuracion del usuario; una PWA no puede imponer un archivo de audio personalizado cuando esta cerrada. Cuando CuotaGo esta abierta, tambien se incluye un timbre local `static/sounds/alert.wav`.

Tambien se deshabilito el zoom de la interfaz movil con viewport fijo, bloqueo de pinch/gesture/doble-tap y campos de 16px para evitar el zoom automatico de Safari al enfocar inputs.


### Comprobacion manual del monitor de atrasos

El scheduler corre automaticamente, pero tambien puedes ejecutar el mismo chequeo manualmente:

```powershell
flask --app app notify-overdue
```

## v1.5 · recuperación Web Push

- El Service Worker se registra sin cache intermedio y se actualiza antes de suscribirse.
- Si `PushManager.subscribe()` devuelve `Registration failed - push service error`, CuotaGo limpia solo sus caches/registro PWA, vuelve a registrar el Service Worker y reintenta una vez automáticamente.
- Mensajes específicos para Safari/iOS, Chrome/Edge, Brave y Opera; ya no se muestra el error crudo del navegador al usuario.
- En iPhone/iPad Web Push requiere la PWA instalada en la pantalla de inicio y abierta desde el icono.
- Si el permiso de notificación existe pero el proveedor Push del navegador no responde, hay un respaldo local mientras CuotaGo permanece abierta. Las alertas con la PWA completamente cerrada siguen requiriendo una suscripción Web Push válida.
- Sin zoom: viewport bloqueado, pinch/doble-tap bloqueados y `touch-action: pan-y` para mantener scroll vertical sin gesto de ampliación.


## v1.7 · MuseoModerno + centro de notificaciones + launcher móvil pulido

- **MuseoModerno** se usa como tipografía principal en toda la interfaz, formularios, botones, login y splash HTML.
- Nuevo módulo **Notificaciones** y campana en la barra superior con contador de pagos que requieren atención.
- Las notificaciones de pago muestran vencidos, cobros para hoy y próximos 7 días. Tocar una alerta abre directamente el acuerdo en `#pay`.
- Nuevo monitor de alertas dentro de la app: consulta pagos pendientes cada minuto, muestra banner, reproduce `alert.wav` y solicita vibración cuando el navegador/dispositivo la soporta. Este monitor funciona en la red local HTTP mientras CuotaGo está abierta.
- Botón **Probar sonido** en Notificaciones para comprobar el aviso durante una demostración local.
- Se retiró completamente la barra de navegación inferior móvil.
- Launcher rediseñado a 3 columnas en teléfono: tarjetas/iconos más grandes, iconos de 46 px y espacios más compactos.
- Web Push permanece separado en Ajustes y se activa cuando CuotaGo disponga de HTTPS; no interrumpe una demo local.

## Cambios anteriores de PWA, perfil y alertas

- Menu de perfil redisenado: en movil/PWA abre desde abajo como bottom sheet y ya no queda pegado o recortado por la barra superior de Safari.
- Fondo modal, boton de cerrar, cuenta visible y zonas tactiles mas grandes.
- En escritorio conserva un popover compacto bajo el area del perfil.

- MuseoModerno se mantiene en todo el sistema, pero con pesos, espaciado y alturas de linea mas legibles.
- Las alertas locales ya no dependen de `alert.wav`: usan Web Audio desbloqueado por el primer toque, con tres tonos y vibracion cuando el navegador la soporta.
- El centro de notificaciones revisa pagos urgentes cada 20 segundos mientras CuotaGo esta abierta.
- Una deuda urgente puede volver a avisar despues de 30 minutos si sigue pendiente.
- Ajustes separa claramente `Alertas dentro de CuotaGo` de `Alertas con la app cerrada`.
- `Probar alerta y sonido` funciona tambien en la demostracion por Wi-Fi local.
- Las pruebas Push se envian a la suscripcion del telefono actual, no a cualquier suscripcion antigua de la cuenta.
- El Service Worker usa opciones de notificacion mas compatibles con Safari/iOS y, si CuotaGo esta abierta, tambien muestra el aviso dentro de la app.
- Las fechas de cobro usan la zona horaria configurada de la app.

> En iPhone, una PWA en HTTP local puede mostrar alertas **dentro de CuotaGo** y reproducir sonido despues de una interaccion del usuario. Las notificaciones del sistema con la app cerrada siguen requiriendo HTTPS/Web Push y el sonido final lo controla iOS.
