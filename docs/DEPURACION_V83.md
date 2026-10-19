# Casos de aceptacion antes de publicar

Usar solo base de pruebas y datos ficticios. Registrar para cada caso: usuario, pasos, resultado esperado, resultado obtenido, hora y captura. Un error monetario, fuga entre negocios o una doble operacion bloquea la salida.

| Prueba | Resultado esperado |
| --- | --- |
| Iniciar UI82 | Inicio con cuatro columnas PWA; controles de tamano/bordes siguen funcionando; menu/tema no cambian. |
| Reponer despues de vender | 10 a 100; vender 9; recibir 10 a 200 => quedan 11, costo unitario 190.91. |
| Anular venta tras reponer | Costo original vuelve a ponderarse; la venta conserva su costo historico. No duplicar existencias al repetir anular. |
| Pago al cierre de mes | UTC 1 de noviembre 01:00 se clasifica el 31 de octubre, 21:00 Santo Domingo. |
| Reintentar compra/cobro | Enviar dos veces la misma clave => una operacion. Misma clave con otro monto => rechazo. |
| Dos usuarios ultima unidad | Solo una venta/acuerdo puede consumir la ultima unidad. |
| Dos pagos sobre saldo 100 | Dos intentos simultaneos de 75 no deben producir 150 cobrados. |
| Revertir pago nuevo | Original visible marcado, registro contrario, saldo reabierto y motivo/usuario documentados. |
| Revertir inicial/legacy | Cuota explicita de correccion, sin reconstruccion falsa ni mora retroactiva nueva. |
| Repetir reversion | No duplicar movimiento contrario. |
| Revertir por otro usuario | Caja abierta de origen se corrige; no cambia efectivo de la caja del autorizador. |
| Revertir caja cerrada | Arqueo cerrado permanece inmutable; correccion fuera de cajas abiertas. |
| Caja requerida | Sin caja abierta el cobro en efectivo falla sin guardar pago parcial. Transferencia no se suma al efectivo. |
| Cerrar caja | Diferencia necesita motivo; contado no negativo; un segundo cierre no modifica el anterior. |
| Orden por pasos | Proveedor, articulos, confirmar; regresar conserva datos; una orden no suma inventario. |
| Recepcion parcial | Pedir 5, recibir 2: inventario +2, pendientes 3. Reintento no suma otra vez. |
| Anticipo a proveedor | Pago y recepcion separados; el saldo refleja recibido/pagado, no una supuesta factura completa. |
| Importar clientes | Vista previa no crea clientes; confirmar dos veces solo un lote; duplicados rechazados. |
| Importar cartera | Total=pagado+saldo; centavos conservados; sin ingresos ni existencias vendibles ficticias. |
| Archivo invalido | NaN, Infinity, duplicados o datos ajenos => rechazo completo, sin media importacion. |
| Conciliar banco | Signo/importe/fecha coinciden; una evidencia solo una vez; CSV no crea cobro. |
| Aislamiento A/B | Usuario A no ve ni modifica clientes, recibos, ordenes ni importaciones de B aunque cambie IDs. |
| Cobrador restringido | Solo clientes asignados; el stock sigue contabilizando otros acuerdos del mismo articulo. |
| Portal | Solo cliente del enlace, sin costos/notas; vencido/revocado no permite nueva consulta. |
| Segundo factor | Clave privada, seis digitos y recuperacion una vez; un OTP repetido en la misma ventana falla. |
| Revocar dispositivo | La siguiente solicitud del otro dispositivo deja de estar autorizada. |
| Suscripcion nueva | Trial con fecha fin; no cambiar silenciosamente cuentas antiguas pending. |
| Recibos | PDFs de pago revertido marcados; fecha local; costos internos no aparecen. |
| Respaldar/restaurar | Base aislada vacia recupera tablas, importes, documentos y accesos; claves correctas; medir tiempo. |

## Comandos reproducibles

Desde la carpeta del proyecto y el entorno virtual:

- `python tools/run_checks.py`: pruebas aisladas; devuelve codigo 2 si falta la verificacion PostgreSQL (resultado incompleto, no fallo monetario).
- `chatbridge-run.bat` opcion 3: configura exclusivamente TEST_DATABASE_URL a partir de .env.preproduction y ejecuta la suite con PostgreSQL.
- Resultado JSON: `test-results/cuotago-v83.json`.

Node es opcional para iniciar la app, pero necesario para ejecutar la bateria JavaScript. Si falta se marca pendiente. No se instala globalmente desde este paquete. Las dependencias de pruebas van en requirements-test.txt.

La suite grande heredada tests/test_app.py ahora exige opt-in y usa esquemas aislados, en lugar de borrar tablas del esquema por defecto. No forma parte del comando curado v83 porque sus escenarios antiguos necesitan actualizar algunas claves/formularios; no se presenta como validada. Las pruebas integradas nuevas y las carreras existentes si estan en el comando --postgres.

## Condicion de salida

Cero duplicados, cero errores de saldos/stock y cero fugas entre negocios en los casos de aceptacion. Respaldo restaurado y comparado. Aprobacion del dueno del negocio sobre politicas de costos, reversos y mora. Medicion en telefono real. Solo despues planificar publicacion con copia previa y ventana de mantenimiento.
