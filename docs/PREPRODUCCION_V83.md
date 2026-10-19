# CuotaGO 1.27.0-rc1 / Operaciones v83

## Estado: candidato para depuracion, NO autorizacion de produccion

Base: CuotaGO.rar + UI79 + UI80 + restauracion 81 + iconos 82. No se recibio el snapshot local de las 12:14. Los paquetes se reconstruyeron y verificaron por SHA-256. No se ha ejecutado este cambio contra la base local del usuario ni contra Railway.

**Antes de descargar/aplicar el ZIP ChatBridge, pausar cualquier despliegue automatico asociado al push.** ChatBridge aplica, hace commit y push; este paquete no controla el panel de Railway ni separa ramas automaticamente. No descargar/aplicar con un despliegue productivo automatico activo.

## 1. Arranque para pruebas en Windows

1. Aplicar el paquete mediante ChatBridge con el despliegue automatico pausado.
2. Abrir `chatbridge-run.bat` desde el proyecto. Prepara dependencias dentro de `.venv`, sin modificar Python global y sin solicitar permisos de administrador.
3. Usar opcion 5 para configurar una conexion PostgreSQL **local**, con una base distinta, por defecto `cuotago_test`. El usuario y la contrasena se solicitan localmente. Se guarda `.env.preproduction`, excluido de Git. `.env` no se modifica.
4. Usar opcion 2, escribir exactamente el nombre de la base de pruebas y preparar/migrar esa base. Si no existe puede crearla usando los permisos del usuario PostgreSQL. No elimina ninguna base. Si ese usuario no tiene permiso de creacion, solicitar una base de pruebas a quien administra PostgreSQL.
5. Usar opcion 1. Abre CuotaGO en `http://127.0.0.1:5001`. Registrar una cuenta ficticia de prueba. No importar clientes reales durante esta primera depuracion.
6. Usar opcion 3 para las pruebas automatizadas, incluyendo HTTP/PostgreSQL. Cada prueba integrada crea un esquema aleatorio `cuotago_qa_<uuid>` y solo elimina ese esquema. La base debe ser exclusiva para pruebas.
7. Opcion 4 muestra controles de preparacion. Un resultado de esquema correcto NO certifica dinero, seguridad o capacidad de produccion.

El lanzador fuerza notificaciones y scheduler desactivados, sin claves VAPID, sin superadmin automatico, con depurador desactivado y servidor solo en localhost. La PWA instalada en el telefono requiere un entorno HTTPS de pruebas separado: no se puede abrir este localhost desde otro dispositivo.

Se requiere Python compatible, PostgreSQL local y acceso a las dependencias de requirements. El lanzador no instala PostgreSQL ni clientes pg_dump/pg_restore ni altera software global. Conserva errores en consola.

## 2. Cambios incorporados

| Area | Alcance implementado |
| --- | --- |
| Inventario | Promedio movil sobre existencias pertinentes, no sobre todas las unidades historicamente compradas. Nuevos acuerdos guardan costo unitario. Anulaciones recuperan costo original. |
| Fechas | Clasificacion de cobros y reversiones por dia comercial; limites UTC y cierre de mes, tambien en recibos. |
| Reintentos | Claves de solicitud persistentes para compras, cobros, gastos, inversiones y operaciones nuevas. Misma clave con otro contenido se rechaza; no confiar solo en deshabilitar botones. |
| Reversiones | Recibo original conservado, movimiento contrario, motivo, actor y codigo de reversion. PDF/HTML marcado. Asignaciones de principal/mora se conservan. |
| Caja | Apertura individual, registro de efectivo, arqueo, diferencias con motivo y cierre inmutable. Control opcional para exigir caja abierta. |
| Ordenes | Nuevo flujo Proveedor / Articulos / Confirmar; orden no mueve stock; recepcion parcial y pagos al proveedor separados; anticipos y cancelacion del remanente. Se conserva la compra directa anterior. |
| Importacion | CSV de clientes, cartera inicial y extractos; vista previa, vencimiento, integridad, confirmacion completa y control de duplicados. |
| Cobradores | Asignacion de clientes y restriccion opcional por cartera. Los calculos de existencias siguen leyendo todos los compromisos del articulo. |
| Banco | Conciliacion manual de extractos con movimientos existentes. Nunca crea dinero a partir de un archivo bancario. |
| Portal | Enlace privado temporal/revocable, solo consulta del cliente asociado. No revela costos, notas internas ni acceso al negocio. |
| Seguridad | Segundo factor TOTP opcional, codigos de recuperacion de un uso, sesiones por dispositivo, revocacion y contrasena real al reautenticar. |
| Suscripcion | Nuevas cuentas tienen prueba con vencimiento; gracia configurable de suscripciones activas. No bloqueo retroactivo de cuentas antiguas pending sin fin. |
| Calendario | Etiquetas explicitas: cada 14 dias (valor antiguo biweekly), cada 15, dia 15/fin de mes y mensual con ancla. No cambia calendarios ya creados. |
| Reportes | Agregados SQL de cobros/reversiones, rango de fechas, saldo registrado y movimientos de v83 distinguidos. No es contabilidad de partida doble. |
| Recuperacion | Herramienta de pg_dump cifrado y ensayo de restauracion a base vacia; no es un respaldo programado ni un ensayo ya realizado en la infraestructura del usuario. |

### UI preservada

No se alteran dashboard.html, home.css, app.css, launcher-v82.css ni el motor de preferencias de iconos. Se mantienen cuatro columnas, iconos/bordes configurables, tema y menu aprobados. El CSS nuevo solo aplica a `.op`, las pantallas nuevas de operaciones. La version de recursos cambia para invalidar cache.

Accesos nuevos: Configuracion -> Operaciones; Configuracion -> Seguridad y dispositivos. En Compras: nueva orden; en un recibo: Revertir (solo usuarios autorizados). Los permisos se verifican en servidor.

## 3. Reglas financieras que deben entenderse al depurar

- Costo de reposicion: la correccion es **prospectiva**. No recalcula el costo registrado de ventas historicas. Caso de control: quedan 1 unidad a 100, entran 10 a 200: nuevo costo 190.91. Revisar por separado cualquier diferencia de inventario antigua.
- Acuerdos antiguos sin costo original: antes de devolverlos al inventario, se solicita costo comprobado. No se inventa a partir del saldo financiado.
- Reversion no es reembolso bancario. Caja abierta: se corrige la caja de origen. Caja cerrada: el arqueo queda intacto y la correccion no se descuenta de la caja del autorizador. Cualquier entrega fisica posterior de dinero debe conciliarse aparte.
- Pagos antiguos, iniciales o calendarios reemplazados sin evidencia completa: el importe reabierto se muestra como cuota explicita de correccion de hoy. No se reconstruye una asignacion historica inexistente ni se genera mora retroactiva adicional. Confirmar esta politica con el negocio antes de usarla fuera de pruebas.
- Importar una cartera inicial no crea recibos ni ingresos de hoy. El total pagado historico es una apertura, no efectivo disponible. Los articulos virtuales de apertura no entran al inventario vendible.
- Caja y diario monetario empiezan con v83. No reconstruyen efectivo historico ni saldos bancarios. Un saldo inicial de caja debe provenir de un conteo real, no del total por cobrar.
- Una compra antigua/directa registrada no equivale a pago a proveedor. El flujo nuevo registra recepcion y pago por separado.
- Los arqueos no incluyen tarjetas ni transferencias como efectivo. Una diferencia de arqueo exige motivo; no se corrige borrando movimientos.
- Los enlaces de portal son credenciales de consulta: cualquiera que reciba el enlace puede verlo hasta su vencimiento. No publicarlos. El token viaja en fragmento URL y se intercambia por POST, no en los logs de la URL del servidor.
- No se otorga automaticamente certificacion fiscal, confirmacion bancaria ni cumplimiento contable por usar estas funciones.

## 4. Importaciones

Descargar las plantillas desde Operaciones -> Importar datos. CSV UTF-8, maximo 500 filas y 1 MB por lote; importes decimales con punto, sin separadores de miles. No es un importador XLSX.

Clientes: `external_id,full_name,document_id,phone,email,address`.
Cartera: `external_id,client_id,description,total,paid,balance,first_due,count,frequency,cost`.
Banco: `external_id,date,amount,reference`, mas nombre interno de cuenta en el formulario.

`client_id` es el identificador interno creado en CuotaGO. `external_id` debe ser estable y unico por origen/lote segun validacion. Revisar el archivo exportado o ficha del cliente para resolver identificadores; no adivinar relaciones por nombre.

La cartera inicial exige `total = paid + balance`, importe finito, frecuencia valida y costo entre 0 y total. Para casos historicos de perdidas con costo mayor a total, no alterar numeros para forzar la importacion: requieren adaptar esa validacion y probarlos antes.

Vista previa: ningun cliente/acuerdo/movimiento de negocio se escribe. Se guarda temporalmente un lote privado de revision. Confirmacion: transaccion unica y misma persona/organizacion; vencimiento de una hora. No existe limpieza programada de lotes vencidos todavia, por lo que debe definirse retencion antes de produccion.

Conciliacion: coincidencia manual de importe, signo, medio no efectivo y fecha dentro de siete dias. No verifica identidad del banco ni llama a su API. Un movimiento no puede asociarse a dos lineas.

## 5. Segundo factor y sesiones

Probar con usuario ficticio. Al activar TOTP se muestra clave manual; introducirla en un autenticador de seis digitos/30 segundos. Conservar codigos de recuperacion fuera del dispositivo. Cada codigo se consume una vez. Activar/desactivar revoca las sesiones anteriores.

Conservar **SECRET_KEY** fuera del repositorio: cifra secretos TOTP ademas de firmar sesiones. Cambiarla sin plan puede impedir descifrar autenticadores. Restaurar la base sin su clave correcta no restaura esos accesos. Recuperacion administrativa de MFA requiere procedimiento controlado; no se incorpora una puerta trasera.

Una cuenta con segundo factor activo requiere codigo al iniciar/reanudar. Revocar otro dispositivo debe impedir su siguiente solicitud. Probar cookies de recordar sesion y reautenticacion de acciones sensibles.

## 6. Migracion y paso futuro a staging/produccion

**No ejecutar ahora contra produccion.** Para un staging dedicado con credenciales propias y HTTPS, el responsable configura APP_ENV=staging, SECRET_KEY robusta, COOKIE_SECURE=1, AUTO_CREATE_DB=0, PUBLIC_BASE_URL=https://..., CHECK_SCHEMA_ON_START=1. Especificar solo proxies reales mediante TRUST_PROXY_COUNT; no copiar valores sin conocer el despliegue.

Desde ese entorno separado, la fabrica de mantenimiento permite `flask --app tools.maintenance_app migrate-v83`. No crea/migra al importarse. En APP_ENV=production se requiere ademas `--confirm-production`; esa opcion no sustituye respaldar ni autoriza el despliegue.

Migracion v83 es aditiva y se marca en cuotago_schema_migrations. El comando tambien ejecuta migraciones heredadas del proyecto: una base muy antigua puede recibir los ajustes historicos que ya existian, incluida conversion de iniciales antiguas en recibos. Ensayar sobre una copia de esa misma version antes de migrar el negocio real.

El arranque productivo por defecto no migra: se detiene si falta la version del esquema. Una clave ausente/corta/de respaldo, DEBUG o cookies inseguras en produccion detienen el arranque. Revisar variables actuales: valores AUTO_CREATE_DB explicitos siguen siendo respetados; establecerlo expresamente en 0.

Rollback: antes de escribir operaciones v83 se puede volver a la version probada sobre su copia coherente. **Despues de crear reversiones o saldos iniciales v83, no volver solo al codigo UI82:** el codigo antiguo no entiende esas marcas y puede mostrar totales incorrectos. Detener escrituras y recuperar codigo + base + claves del mismo punto validado; no hay downgrade destructivo automatico.

## 7. Alcance pendiente (bloqueos de salida)

- Integracion completa Flask/PostgreSQL, migraciones contra copia real y carreras concurrentes. Las pruebas incluidas deben ejecutarse en la base aislada; no se ejecutaron en el entorno del asistente.
- Verificacion de telefono fisico, Safari/PWA, Push real y red intermitente con servidor real.
- Ensayo real pg_dump/pg_restore, retencion, almacenamiento externo, cifrado de llaves y tiempo de recuperacion. La herramienta no programa respaldos ni configura Railway.
- Pruebas de carga y toda la optimizacion de reportes. Se redujo carga de pagos, pero siguen existiendo consultas amplias de contratos/cuotas.
- Consolidacion del CSS historico: aplazada para no alterar la UI aprobada.
- e-CF, proveedor fiscal, pasarela de pago, webhooks bancarios, WhatsApp automatizado y cobros sin conexion no estan conectados ni simulados como reales.
- No se agrega contabilidad de partida doble, motor de amortizacion sobre saldo, inventario por lotes/capas historicas, devoluciones de recepciones, transferencias entre cajas, retiros/remesas de cobradores o portal con descarga completa de documentos. No anunciar estas capacidades como disponibles.
- El portal es una primera consulta privada por enlace, no un sistema de identidad del comprador ni una pasarela.
- Comercializacion: plan propuesto en PLAN_COMERCIAL_V83.md; no se contactaron personas, publicaron anuncios ni crearon contratos comerciales.

Resultado: candidato funcional para depuracion local. No es una certificacion financiera/de seguridad ni una entrega lista para produccion.
