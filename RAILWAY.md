# CuotaGo v1.8.1 en Railway

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

Railway crea sus propias credenciales de PostgreSQL. No uses `127.0.0.1` ni la clave local `12345` en produccion.

## 4. Variables del servicio CuotaGo

Agrega estas variables en el servicio WEB de CuotaGo:

```text
APP_NAME=CuotaGo
APP_VERSION=1.8.1
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
5. Ajustes -> activa/probar notificaciones.

Las notificaciones Push con la PWA cerrada requieren HTTPS y que el usuario conceda permiso desde una accion directa.
