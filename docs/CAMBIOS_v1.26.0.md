# CuotaGo 1.26.0 / ui-v70 - Operación conectada del dealer

Base: v1.25.5 / ui-v69 (snapshot y parches anteriores de esta conversación).
Entrega: parche ChatBridge, no repositorio completo. No introduce tablas, columnas ni cambios de esquema.

## Cambios incluidos

### Ficha del vehículo o producto

- Acciones según disponibilidad y permisos: vender, crear un acuerdo, registrar un gasto, editar, ver comprobantes y operaciones relacionadas.
- Vender o financiar desde una ficha conserva la unidad seleccionada. El origen viaja en campos validados, no en URLs externas proporcionadas por el navegador.
- Fotografía real del inventario; los artículos sin imagen no reciben una fotografía ficticia. Se conservan adquisición, estado, gastos, notas e historial.
- Precio, costo e inversión objetivo por unidad separados del resultado histórico de ventas directas. Las ventas completadas utilizan los importes guardados en Sale; las anuladas se excluyen del resultado, pero siguen visibles como anuladas.
- Los acuerdos conservan su propio total, pagos y saldo. No se convierten en ventas de contado.

### Ficha del cliente

- Ventas de contado, pagado en acuerdos, saldo activo y atrasos diferenciados.
- Total recibido combina ventas completadas con pagos conservados en acuerdos. No trata el importe total de una financiación como si ya se hubiera cobrado.
- Accesos a venta, acuerdo, estado de cuenta, seguimiento, vehículos y cobro. Conserva promesas, notas y contactos.
- Las preselecciones se validan contra el negocio actual y no desaparecen por estar fuera de la primera página de opciones.

### Documentos y presentación

- Documentos reúne comprobantes de venta, recibos de pago y estados de cuenta ya generados por el sistema, con búsqueda, filtros y permisos.
- El manual permanece en Ayuda (/help). No se implementa almacenamiento de adjuntos externos, matrículas escaneadas ni galerías.
- Componentes compartidos, iconos SVG con texto, tarjetas redondeadas, diseño adaptable y tema oscuro en las nuevas fichas.
- En esas fichas, las utilidades móviles pasan al menú de tres puntos para no cubrir importes. El inicio aprobado, sus accesos, el título y la disposición de módulos se conservan.
- El comprobante para compradores sigue separado de la ficha interna: no incluye costo, inversiones, utilidad, margen ni notas internas.

### Consistencia y protecciones

- Reportes denomina el indicador existente «Ingresos menos gastos» y explica que no es el saldo completo de caja/bancos. No se supone que una compra se pagó al registrarla.
- Bloqueos de escritura con orden compartido: inventario, después acuerdo/venta. Se refrescan los valores tras esperar el bloqueo y se revisan claves de solicitudes repetidas.
- Lecturas de inventario/reportes no reparan estados mediante escrituras implícitas que puedan pisar cambios simultáneos.
- Exportación interna con proveedores, gastos anulados, imágenes disponibles, manifest de integridad y protección de textos CSV interpretables como fórmulas.
- La exportación contiene costos y datos personales. NO entregar a compradores. NO es copia completa de PostgreSQL ni dispone de restauración automática.

## No incluido ni afirmado

No se agregan reglas de consignación, parte de pago, reservas, cotizaciones o liquidaciones. No se reescriben ventas históricas, no se borran datos, no se modifican secretos ni se conectó al servidor del cliente. Las protecciones de concurrencia requieren validación de integración con PostgreSQL antes de considerarlas verificadas en producción.

La forma de arranque no cambió. Se conserva chatbridge-run.bat desde su propia carpeta.
Ver VALIDACION_DEALER_v1.26.0.md para resultados y limitaciones.
