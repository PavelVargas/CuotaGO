# Respaldo cifrado y ensayo aislado

La exportacion CSV del sistema se conserva. No equivale a este respaldo de PostgreSQL. Este documento no significa que ya exista un respaldo externo del usuario.

## Requisitos

pg_dump y pg_restore compatibles con el servidor, permisos de lectura, espacio libre, acceso a la base correcta y una clave privada de respaldo separada de SECRET_KEY. No instalar herramientas globales ni cambiar permisos del servidor desde la app.

1. `python tools/postgres_backup.py generate-key` genera una clave de 64 caracteres hexadecimales. Guardarla en un gestor seguro, fuera del repositorio y fuera de la carpeta de backups. No pegarla en chats ni logs.
2. En una terminal privada, proporcionar DATABASE_URL y CUOTAGO_BACKUP_KEY como variables de entorno.
3. `python tools/postgres_backup.py backup --out /ruta/privada/copia.cgbk` crea archivo AES-GCM y metadata con SHA-256. No sobrescribe el destino. En Windows usar una ruta privada del usuario.
4. `python tools/postgres_backup.py verify /ruta/privada/copia.cgbk` autentica el cifrado y pide pg_restore --list. **No restaura ni prueba consistencia operativa.**
5. Crear una base vacia e independiente terminada en _test o _restore, de nombre diferente a la original. Proporcionar RESTORE_TEST_DATABASE_URL. Ejecutar `python tools/postgres_backup.py restore-test /ruta/privada/copia.cgbk --confirm-empty NOMBRE_EXACTO`.
6. El programa se niega si hay tablas o coincide el destino; usa una transaccion, sin --clean, sin DROP DATABASE. Solo debe apuntar a la base desechable preparada expresamente.
7. Comparar cantidades/saldos, comprobar documentos y autenticacion de la aplicacion en esa copia, medir tiempo. Conservar SECRET_KEY que corresponde a los secretos TOTP del respaldo. No usar usuarios reales para enviar notificaciones en el ensayo.

Los archivos fuente se mantienen; los temporales de descifrado se limpian. El archivo de metadata indica restoration_tested=false porque generarlo o listar su contenido no demuestra recuperacion.

Retencion, almacenamiento fuera del servidor, cifrado de claves, alertas por fallo y ejecucion periodica quedan por configurar en la infraestructura del usuario. No hay un job programado instalado por este ZIP.
