# CuotaGO V84 / 1.27.0-rc2 - Orden de compra en una pantalla

## Base y alcance

Este parche requiere el paquete V83 RC1 (`preprod83rc1`) aplicado sobre UI82.
No contiene el repositorio completo ni vuelve a instalar las funciones de V83.
Se conserva el inicio de cuatro columnas, sus iconos, sus controles de tamano y
bordes, la fuente aprobada y los sonidos. El CSS nuevo de separadores se carga
solo dentro de modulos; no en el inicio ni en las paginas de acceso.

## Preparar la prueba, sin produccion

ChatBridge aplicara archivos y hara commit/push al descargar un paquete valido.
Mantener pausado el despliegue automatico de produccion mientras se depura.
No usar una base de datos operativa para las pruebas.

1. Usar el lanzador existente `chatbridge-run.bat`, sin copiar archivos ni usar Git.
2. Si no se configuro antes, elegir su opcion 5 para una base separada con nombre
   terminado en `_test`; la configuracion se guarda en `.env.preproduction`.
3. Elegir la opcion 2 para preparar el esquema de esa base. La entrada existente
   `migrate-v83` ahora encadena tambien V84: no hace falta otro comando.
4. Elegir la opcion 1 para iniciar la revision local. La opcion 3 sigue disponible
   para pruebas automatizadas, incluida la aceptacion HTTP/PostgreSQL.

La migracion V84 agrega solamente revision al borrador y datos/MIME de foto a las
lineas de orden. No borra tablas, no cambia costos historicos y no incrementa
inventario. El inicio verifica el marcador del esquema para evitar trabajar con
un esquema incompleto. Las ordenes anteriores conservan su estado y cantidades.
No se incluye `.env`, claves, datos operativos ni software global en el paquete.

## Flujo aprobado

Abrir **Compras / Ordenes / Nueva orden**. Elegir proveedor y agregar productos
con **+ Existente** o **+ Nuevo**. Cantidades, costos y total se muestran juntos.
Referencia, fecha esperada y nota son opcionales, en un solo desplegable.
No hay pantallas ni botones Siguiente/Anterior.

- **Guardar borrador:** persiste proveedor y lineas para reabrir. Puede guardarse
  sin productos o con costo cero; no crea existencias ni pagos.
- **Descartar:** abandona cambios no guardados. En un borrador guardado, lo marca
  descartado con auditoria y lo retira de la lista habitual; el filtro Descartada
  permite consultar el registro. No elimina compras confirmadas.
- **Confirmar orden:** requiere proveedor, al menos un producto y costos positivos.
  Guarda la orden y abre su detalle. No exige guardarla primero como borrador.
  No recibe mercancia ni paga al proveedor de forma implicita.

Un borrador abierto en dos ventanas lleva revision. Un envio atrasado se rechaza;
no debe sobrescribir silenciosamente lo que guardo la otra ventana. Los reintentos
con la misma clave y los mismos datos no deben duplicar la orden ni su recepcion.

## Fotos

Los existentes se buscan en un catalogo con fotos, nombre, identificacion y costo.
La busqueda consulta todo el inventario de la cuenta mediante paginas, no solo
los primeros productos cargados. Se excluyen los saldos iniciales virtuales.

Se puede seleccionar foto para nuevos o cambiar la foto de una linea. El servidor
valida JPG/PNG/WebP hasta 6 MB por imagen, retira metadatos y guarda una version
WebP acotada. El formulario limita el conjunto de fotos a 15 MB para respetar el
limite de 16 MB de la solicitud completa. HEIC no se acepta en esta version.

La foto de la linea es independiente: cambiarla no reemplaza la foto de un
producto existente. Si es un producto nuevo, su foto se copia al inventario al
registrar la primera recepcion. Quitar foto de una linea se conserva al reabrir;
no vuelve a aparecer la del inventario por error. Las URLs son privadas y se
comprueba organizacion y permiso; no se publican archivos de clientes.

## Recepcion e impresion

En el detalle, **Completar pendientes** rellena las cantidades aun no recibidas.
Se puede ajustar cualquiera y confirmar la recepcion parcial. Solo ese acto
incorpora existencias. Cada entrega genera su propio comprobante imprimible.

**Imprimir orden:** pedido con fotos, cantidades, costos y total.
**Imprimir conduce:** mercancia solicitada para traslado, sin costos internos;
no certifica una recepcion ni registra una salida de inventario.
**Imprimir recepcion:** cantidades efectivamente registradas en esa entrega,
sin sumar entregas anteriores. La primera recepcion no cambia al imprimirla
despues de una segunda. Incluye campos de entrega/recibido y firma.

La vista de impresion usa el dialogo del navegador para imprimir o guardar PDF.
Son documentos operativos; no son facturas fiscales ni comprobantes de pago.
La disponibilidad de guardar PDF/AirPrint depende del dispositivo. Requiere
sesion vigente para cargar fotos; no promete imprimir desconectado.

## Pruebas manuales de aceptacion

1. Abrir una nueva orden en escritorio y PWA: sin asistente y sin desbordamiento.
2. Seleccionar proveedor, guardar sin productos y reabrir: mismo borrador.
3. Agregar dos existentes, uno nuevo y foto; comprobar cantidades y total.
4. Cambiar foto, guardar, salir, reabrir: imagen conservada y foto original intacta.
5. Quitar foto de existente, guardar/reabrir: sigue sin foto en la orden.
6. Confirmar con costo cero, negativo o cantidad fraccionaria: rechazado.
7. Confirmar directamente una orden nueva: aparece una sola orden confirmada.
8. Enviar dos veces la misma confirmacion por mala conexion: no duplica registros.
9. Editar el mismo borrador en dos ventanas: el segundo envio atrasado se rechaza.
10. Descartar guardado: sin efectos de inventario/caja y registro auditable.
11. Confirmar orden: comparar inventario antes/despues, debe quedar igual.
12. Recibir 1 de 3 unidades: aumenta 1, quedan 2 pendientes; imprimir recepcion.
13. Recibir las 2 restantes y repetir envio: llega a 3, nunca 5.
14. Imprimir otra vez la primera recepcion: sigue mostrando solo 1.
15. Completar pendientes con varias lineas: no supera cantidades pendientes.
16. Intentar recibir/pagar/imprimir conduce de un borrador: rechazado.
17. Abrir foto, orden y recepcion de otra organizacion: acceso rechazado.
18. Probar foto no valida, demasiado pesada y sesion expirada: mensaje util y sin duplicar.
19. Imprimir orden, conduce y recepcion, tambien con multiples paginas.
20. Revisar Acuerdos, Reportes, Inventario, Clientes y Configuracion en claro/oscuro:
    menos divisores decorativos, pero campos, totales y foco siguen distinguibles.
21. Comprobar inicio y configuracion de iconos: cuatro columnas y preferencias intactas.

## Limites de la entrega

Los tests aislados no validan bloqueos reales de PostgreSQL, cookies, CSRF en HTTP,
la migracion sobre tu copia, AirPrint ni una impresora fisica. Se incluyen cuatro
pruebas nuevas de aceptacion PostgreSQL para ejecutar de forma explicita en una
base de pruebas; no se afirman aprobadas en este entorno. Ver RESULTADOS_V84.md.

No restaurar solamente codigo viejo despues de registrar borradores/revisiones:
el codigo anterior desconoce esos estados. Usar respaldo coherente de codigo y
base en un entorno aislado si es necesario retroceder. No tocar la base real.
