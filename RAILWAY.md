# CuotaGo v1.16.0 en Railway

Esta carpeta esta preparada para Railway con PostgreSQL.

## 1. GitHub

El archivo `.env` local esta ignorado por Git. No lo publiques.

En PowerShell, dentro de la carpeta:

```powershell
.\SUBIR_A_GITHUB.ps1
```

El script pedira la URL HTTPS de un repositorio GitHub vacio.

## 2. Crear el proyecto en Railway

1. New Project.
2. Deploy from GitHub repo.
3. Selecciona el repositorio de CuotaGo.
4. Si Railway intenta desplegar antes de tener la base, no importa: agrega PostgreSQL y las variables antes del despliegue final.

Railway detectara el `Dockerfile` automaticamente. Tambien existe `railway.toml` con `/healthz` como healthcheck.

## 3. Agregar PostgreSQL

En el mismo proyecto:

1. `+ New`.
2. Database.
3. PostgreSQL.

Railway crea sus propias credenciales de PostgreSQL. No uses `127.0.0.1` ni tus credenciales locales en produccion.

## 4. Variables del servicio CuotaGo

Agrega estas variables en el servicio WEB de CuotaGo:

```text
APP_NAME=CuotaGo
APP_VERSION=1.16.0
APP_ENV=production
APP_CURRENCY=DOP
APP_TIMEZONE=America/Santo_Domingo
AUTO_CREATE_DB=true
FLASK_DEBUG=false
COOKIE_SECURE=true
PUSH_NOTIFICATIONS_ENABLED=true
PUSH_SCHEDULER_ENABLED=true
PUSH_CHECK_INTERVAL_MINUTES=5
PUSH_ALERT_START_HOUR=8
PUSH_ALERT_END_HOUR=22
PUSH_OVERDUE_REPEAT_HOURS=4

# Superadmin
SUPERADMIN_EMAIL=admin@cuotago.app
SUPERADMIN_PASSWORD=USA_UNA_CLAVE_LARGA_Y_UNICA
SUPERADMIN_NAME=Superadmin
SUPERADMIN_ORG_NAME=CuotaGo Administracion
```

Ademas agrega:

- `SECRET_KEY`: una clave larga y privada.
- `DATABASE_URL`: crea una Reference Variable hacia `DATABASE_URL` del servicio PostgreSQL. Si el servicio se llama `Postgres`, Railway la representa como `${{Postgres.DATABASE_URL}}`.
- `VAPID_SUBJECT`: por ejemplo `mailto:tu-correo@dominio.com`.
- `VAPID_PUBLIC_KEY`: copia el valor desde tu `.env` local actual.
- `VAPID_PRIVATE_KEY_B64`: copia el valor desde tu `.env` local actual.

No publiques esos secretos en GitHub.

## 5. Dominio HTTPS

En CuotaGo -> Settings -> Networking/Public Networking, genera un dominio Railway.

Luego prueba:

```text
https://TU-DOMINIO.up.railway.app/healthz
```

Debe responder con `ok: true`, `database: postgresql` y la base de Railway.

## 6. PWA y Push

En iPhone:

1. Abre la URL HTTPS en Safari.
2. Compartir -> Anadir a pantalla de inicio.
3. Abre CuotaGo desde el icono instalado.
4. Inicia sesion.
5. Ajustes -> activa las notificaciones.
6. Usa **Simular con app cerrada**: CuotaGo programa un Push real a 10 segundos; sal de la PWA y espera la alerta del sistema.

Las notificaciones Push con la PWA cerrada requieren HTTPS y que el usuario conceda permiso desde una accion directa. El sonido/haptico final de una notificacion Web Push lo controla iOS/Android segun los ajustes del telefono.

## 7. Superadmin

Al arrancar, si `SUPERADMIN_EMAIL` y `SUPERADMIN_PASSWORD` estan configurados, CuotaGo crea o actualiza esa cuenta con rol `superadmin`. El panel `/superadmin` ahora incluye:

- directorio de empresas con búsqueda y filtros;
- alta de empresas y propietarios;
- planes de suscripción editables y archivables;
- estados de suscripción, vencimiento y gracia;
- registro, historial y anulación auditable de pagos de suscripción;
- extensión manual de días;
- creación/edición de usuarios, bloqueo/habilitación y restablecimiento de contraseña;
- exportación CSV;
- auditoría de acciones administrativas;
- mantenimiento de módulos, vaciado completo y eliminación definitiva con confirmación reforzada.

Las suscripciones `suspended`, `cancelled` o vencidas fuera del periodo de gracia redirigen al cliente a una pantalla de estado de suscripción. Sus datos no se borran. Las cuentas `pending`, `trial`, `active` y `past_due` continúan teniendo acceso.

## Actualización v1.14.2

- Crea la tabla `suppliers` si todavía no existe.
- Agrega `purchases.supplier_id` y `purchases.batch_key` sin borrar compras existentes.
- Compras registra únicamente costo/stock; `assets.sale_price` ya no se modifica al recibir mercancía.
- El Service Worker usa caché `1.14.2-ui-v29` para forzar la interfaz nueva de órdenes de compra.

Esta actualización es **hacia adelante y no borra datos existentes**. `db.create_all()` crea las tablas nuevas `subscription_plans`, `organization_subscriptions`, `subscription_payments` y `admin_audit_logs`. Para instalaciones PostgreSQL existentes, el arranque agrega de forma segura `users.is_enabled` y `users.last_login_at` con `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`. Las empresas que ya existían aparecen como **Sin configurar** hasta que el superadmin les asigne una suscripción; no quedan bloqueadas por ese motivo.

## Actualización v1.15.0

- Agrega de forma segura tablas para promesas de pago, notas de cobranza, historial de reprogramaciones, gastos y auditoría por empresa.
- Amplía `payments` con referencia, tipo de pago, código de recibo y usuario que registró el movimiento.
- Amplía `installments` con base de mora reprogramada para conservar recargos previos sin detener la acumulación futura.
- Agrega Expediente del cliente, Agenda de cobranza, reprogramación, recibos/estado de cuenta, módulo Gastos y flujo neto en Reportes.
- El Service Worker usa caché `1.15.0-ui-v33`.

La actualización es hacia adelante: usa `CREATE TABLE IF NOT EXISTS` y `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`; no borra acuerdos ni pagos existentes.


### Seguridad 1.16.0
En Railway `SESSION_COOKIE_SECURE` se activa automáticamente. Solo usa `SESSION_COOKIE_SECURE=0` para desarrollo local por HTTP. La actualización crea/usa `schema_migrations` y aplica una sola vez las ampliaciones de esquema pendientes.
