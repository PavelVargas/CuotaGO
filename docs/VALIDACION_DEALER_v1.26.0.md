# Validación de CuotaGo 1.26.0

## Ejecutado en copia aislada

| Comprobación | Resultado |
|---|---|
| Pruebas automatizadas seleccionadas | 99 aprobadas; 1 módulo PostgreSQL omitido deliberadamente |
| Sintaxis Python (incluye pruebas) | 30 archivos sin errores |
| Sintaxis Jinja | 51 plantillas sin errores |
| Endpoints main.* literales utilizados en plantillas | Nombres encontrados en las rutas declaradas por el proyecto |
| JavaScript y service worker | Verificación node --check sin errores |
| Vistas renderizadas | 40 combinaciones: 4 fichas/vistas, 5 tamaños, claro/oscuro |
| Desbordamiento horizontal / imágenes fallidas / errores JS en esas vistas | No detectados |
| Menú móvil y buscador global | 3 vistas comprobadas |
| Lanzador Windows | Archivo existente conservado sin cambios |

Las 99 pruebas cubren resúmenes monetarios, anulaciones, selecciones, contexto de origen, permisos, consultas documentales por organización, exportación y hashes, plantillas y regresiones de los PDF de cliente, inicio, ventas y acuerdos. Se observaron 85 advertencias heredadas de deprecación relacionadas con datetime.utcnow.

Las pruebas de consultas usan SQLAlchemy sobre SQLite aislado. Las de bloqueo verifican orden, recarga y compilación SQL para PostgreSQL: NO prueban exclusión real entre transacciones PostgreSQL.

Las vistas se renderizaron con Jinja y el CSS/JavaScript real del proyecto en Chromium; datos de prueba y fotografía de una captura aportada por el usuario. Esos datos no se insertan en el producto ni en ninguna base del cliente. Tamaños: 1366x768, 1024x768, 768x1024, 390x844 y 320x740.

## Límites de esta validación

No fue posible iniciar el servidor Flask ni PostgreSQL en este entorno por dependencias/conectividad no disponibles. La navegación HTTP está restringida: las vistas de navegador se cargaron como HTML renderizado con recursos embebidos. No se verificaron el servidor desplegado, la base real, restauración, concurrencia real, push, integración del navegador entre páginas ni un iPhone físico.

Por tanto, este informe NO certifica la aplicación completa para producción. No representa la ejecución de toda la suite de tests/test_app.py.

## Repetir pruebas aisladas

Desde un entorno de desarrollo con las dependencias de prueba instaladas:

```sh
python -m pytest -q tests/test_customer_sale_receipt.py tests/test_sales_ui_contract.py tests/test_launcher_ui_contract.py tests/test_agreement_motion_ui.py tests/test_dealer_workflows.py tests/test_dealer_transactions.py tests/test_dealer_document_queries.py tests/test_dealer_postgres.py
```

## Concurrencia real pendiente

Se incluye tests/test_dealer_postgres.py. Por defecto se omite para impedir el uso accidental de una base configurada para producción.

Solo en una base PostgreSQL SEPARADA de pruebas, con el stack del proyecto instalado, habilitar CUOTAGO_RUN_PG_TESTS=1 y TEST_DATABASE_URL apuntando a esa base. Ejecutar exclusivamente:

```sh
python -m pytest -q tests/test_dealer_postgres.py
```

Cada prueba crea un esquema aleatorio cuotago_qa_* y elimina exclusivamente su esquema al finalizar. Se requiere un usuario de pruebas con permisos para crear esquemas. Aun con ese aislamiento, no usar una base de producción.

Casos incluidos: dos ventas de la última unidad (clave igual y diferente), venta frente a acuerdo de la misma unidad, dos pagos que juntos superarían el saldo. Esta sesión NO ejecutó esos casos sobre PostgreSQL.

## Validación de despliegue recomendada

1. Confirmar copia de seguridad PostgreSQL del proveedor y restaurarla en una base separada. Comprobar clientes, unidades, imágenes, operaciones y saldos antes de considerar la recuperación validada. La exportación ZIP no sustituye este paso.
2. En pruebas, completar una venta y un acuerdo desde vehículo y desde cliente; verificar preselecciones, disponibilidad y regreso a la ficha.
3. Registrar un pago, anular una venta y consultar documentos con propietario, vendedor y cobrador. Verificar que no se puedan consultar registros de otra organización.
4. Abrir los PDF del cliente y confirmar ausencia de costos y notas internas. Revisar escritorio y PWA en dispositivos del negocio, incluyendo teclado, menú, navegación y fotografías reales.
5. Verificar que se cargan los recursos 1.26.0-ui-v70 en el despliegue y que los respaldos periódicos permanecen activos.

No se guardan credenciales ni cadenas de conexión del cliente en estos archivos.
