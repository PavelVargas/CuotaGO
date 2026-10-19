# CuotaGO UI85 - Iconos 3D integrados

## Base y alcance

Actualizacion visual sobre V84 (1.27.0-rc2). Mantiene las operaciones de V83/V84.
No contiene un servidor nuevo, una maqueta como sustituto de la app ni el repositorio completo.
Las diez ilustraciones del diseno aprobado se integran como archivos WebP transparentes locales.
Los enlaces siguen saliendo del catalogo de modulos y sus permisos, no de URLs de ejemplo.

## Incluido

- Inicio: Acuerdos, Ventas, Cobros, Clientes, Compras, Inventario, Calendario, Reportes, Gastos y Documentos en 3D.
- Cuatro columnas en PWA/celular, incluyendo PWA instalada en tablet u orientacion horizontal.
- Cinco columnas en navegador de escritorio, con ilustraciones de mayor tamano.
- Tarjetas claras/oscuras con sombras suaves y esquinas regulables, no circulos.
- Nombres sin subtitulos; conserva los avisos urgentes que ya existian en escritorio.
- Configuracion: vista previa 3D y los mismos controles de tamano/redondez y almacenamiento de UI82.
- Fallback al SVG original si falta una ilustracion; los enlaces no dependen de JavaScript.
- Recursos locales con version de cache actualizada y precarga limitada por el service worker existente.
- Normal flow en inicio de escritorio para evitar que los iconos mayores tapen el menu en ventanas bajas.

No se ha anadido la barra lateral ni textos de demostracion del mockup. Se conserva el menu aprobado.
No se modifica la tipografia, ni Compras/recepciones/conduces, ni los reportes financieros.

## Aplicacion

Aplicar el ZIP de ChatBridge sobre V84. Mantener la rama de preproduccion y el despliegue
productivo pausado durante la revision, como en las entregas anteriores. El mismo
chatbridge-run.bat sigue arrancando el proyecto; no se requiere migracion, preparar otra
base, cambiar .env ni instalar nuevas dependencias para esta capa visual.

La app usa una nueva version de recursos. Al volver a abrir Inicio debe solicitar los
recursos nuevos. No borres almacenamiento ni datos de clientes para cambiar los iconos.

## Verificacion realizada

142 pruebas Python aisladas aprobadas (325 advertencias ya existentes por datetime.utcnow).
Siete suites JavaScript aprobadas, incluida la nueva de fallback.
105 comprobaciones visuales/DOM en Chromium: 14 tamanos/modos y Configuracion.
Se probaron cuatro columnas, fotos cargadas, ausencia de scroll horizontal, separacion del
resumen inferior, tamanos minimos/maximos, redondez, guardado, restablecimiento y fallback.

El navegador de este entorno bloquea navegar a URLs. La revision visual utilizo las
plantillas reales con assets locales embebidos en memoria, sin servidor Flask ni PostgreSQL.
No equivale a probar navegacion real, instalacion del worker ni Safari/iPhone fisico.
Los totales que aparecen en las capturas son datos de prueba, no consultas de produccion.
Detalle legible por herramientas: docs/RESULTADOS_UI85.json.

## Depuracion local recomendada

1. Abrir Inicio en PWA: deben aparecer los 10 modulos permitidos, en cuatro columnas.
2. Entrar en cada modulo y volver: conserva sus rutas y datos.
3. Configuracion > Preferencias > Iconos del inicio: cambiar tamano y bordes; volver al
   inicio y comprobar que se conservan tras cerrar y abrir la app.
4. Probar modo claro/oscuro y orientacion horizontal; los controles inferiores deben
   seguir accesibles. Las pantallas de poca altura pueden desplazarse para no recortar.
5. Probar con cache previa y confirmar en Red que las imagenes se sirven localmente desde
   /static/icons/modules-3d/. Sin imagen, debe verse el SVG original, no perderse el acceso.

## Reversion de esta capa visual

No hay cambios de esquema ni de datos. Para retirar solo UI85, restaurar los archivos de
interfaz de V84 y usar otra version nueva de cache. No revertir las migraciones ni las
operaciones nuevas de V83/V84 por un cambio de iconos.
