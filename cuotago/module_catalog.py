"""Single source of truth for CuotaGo's user-facing modules.

The dashboard launcher and the in-app user guide both consume this catalog.
When a module is added here, the launcher and documentation stay in sync.
"""

MODULE_CATALOG = [
    {
        "slug": "agreements",
        "name": "Acuerdos",
        "endpoint": "main.contracts",
        "icon": "home-agreements",
        "accent": "accent-blue",
        "home_description": "Crear y gestionar acuerdos",
        "guide_summary": "Crea el financiamiento o préstamo de un artículo y define cómo lo pagará el cliente.",
        "guide_steps": [
            "Entra a Acuerdos y toca Nuevo acuerdo.",
            "Selecciona o crea el cliente y el artículo del inventario.",
            "Indica cantidad, inicial, cuotas, frecuencia y mora si aplica.",
            "Revisa el resumen y guarda. El inventario se descuenta automáticamente.",
        ],
        "guide_tips": [
            "Puedes crear un acuerdo sin mora y activarla más adelante; comienza a correr desde la fecha en que la agregas.",
            "Desde el detalle del acuerdo puedes registrar pagos, enviar avisos por WhatsApp y consultar el saldo.",
        ],
    },
    {
        "slug": "collections",
        "name": "Cobros",
        "endpoint": "main.collections",
        "icon": "home-payments",
        "accent": "accent-coral",
        "home_description": "Pagos y abonos",
        "guide_summary": "Revisa quién debe pagar y registra cuotas o abonos sin pasos adicionales.",
        "guide_steps": [
            "Abre Cobros para ver pagos pendientes y vencidos.",
            "Entra al acuerdo correspondiente.",
            "Pulsa Registrar pago o Abonar, indica el monto y confirma.",
            "CuotaGo actualiza el saldo y el calendario automáticamente.",
        ],
        "guide_tips": [
            "No necesitas abrir ni cerrar una caja para cobrar.",
            "Los pagos registrados alimentan automáticamente Reportes.",
        ],
    },
    {
        "slug": "notifications",
        "name": "Notificaciones",
        "endpoint": "main.notifications",
        "icon": "home-alerts",
        "accent": "accent-red",
        "home_description": "Alertas de cobro",
        "guide_summary": "Concentra los pagos vencidos, los que vencen hoy y los próximos vencimientos.",
        "guide_steps": [
            "Abre Notificaciones para revisar alertas activas.",
            "Toca una alerta para ir directamente al acuerdo.",
            "Registra el pago o usa el aviso por WhatsApp cuando corresponda.",
        ],
        "guide_tips": [
            "Una alerta desaparece automáticamente cuando el pago queda saldado.",
            "Puedes activar notificaciones del dispositivo desde Ajustes.",
        ],
    },
    {
        "slug": "clients",
        "name": "Clientes",
        "endpoint": "main.clients",
        "icon": "home-clients",
        "accent": "accent-cyan",
        "home_description": "Personas y contactos",
        "guide_summary": "Administra los datos de las personas que tienen o tendrán acuerdos.",
        "guide_steps": [
            "Entra a Clientes y toca Nuevo cliente.",
            "Completa nombre, teléfono y los datos necesarios.",
            "Guarda y luego selecciónalo al crear un acuerdo.",
        ],
        "guide_tips": [
            "También puedes crear un cliente durante el flujo de un acuerdo cuando todavía no existe.",
        ],
    },
    {
        "slug": "purchases",
        "name": "Compras",
        "endpoint": "main.purchases",
        "icon": "home-purchases",
        "accent": "accent-green",
        "home_description": "Órdenes y proveedores",
        "guide_summary": "Registra compras en lote, proveedores y el costo real de entrada del inventario.",
        "guide_steps": [
            "Crea una orden y selecciona un proveedor o crea uno nuevo.",
            "Agrega todos los artículos necesarios en la misma orden.",
            "En cada línea selecciona un artículo existente o crea uno nuevo.",
            "Indica cantidad y costo unitario, revisa el total y guarda la orden.",
        ],
        "guide_tips": [
            "Compras solo modifica el costo de compra; nunca cambia silenciosamente el precio de venta definido en Inventario.",
            "Las reposiciones actualizan existencia y costo promedio del artículo.",
        ],
    },
    {
        "slug": "inventory",
        "name": "Inventario",
        "endpoint": "main.assets",
        "icon": "home-inventory",
        "accent": "accent-teal",
        "home_description": "Artículos y existencias",
        "guide_summary": "Controla carros, motores, celulares y otros artículos disponibles para acuerdos.",
        "guide_steps": [
            "Entra a Inventario para revisar existencias y artículos asignados.",
            "Crea o edita un artículo con su cantidad, costo y precio de venta.",
            "Usa ese artículo al crear un acuerdo.",
        ],
        "guide_tips": [
            "El costo puede venir de Compras y el precio de venta se administra aquí.",
            "Cuando se crea un acuerdo, la cantidad asignada deja de estar disponible automáticamente.",
        ],
    },
    {
        "slug": "calendar",
        "name": "Calendario",
        "endpoint": "main.payment_calendar",
        "icon": "home-calendar",
        "accent": "accent-purple",
        "home_description": "Fechas de pago",
        "guide_summary": "Visualiza próximos pagos y atrasos organizados por fecha.",
        "guide_steps": [
            "Abre Calendario y cambia de mes cuando lo necesites.",
            "Busca por cliente para localizar rápidamente sus fechas.",
            "Toca un pago para abrir el acuerdo relacionado.",
        ],
        "guide_tips": [
            "Los vencidos se destacan para que puedas priorizar el seguimiento.",
        ],
    },
    {
        "slug": "reports",
        "name": "Reportes",
        "endpoint": "main.reports",
        "icon": "home-reports",
        "accent": "accent-gold",
        "home_description": "Resultados del negocio",
        "guide_summary": "Consulta cartera, cobros, mora, compras, inventario y margen de ganancia.",
        "guide_steps": [
            "Abre Reportes para ver los indicadores generales.",
            "Revisa capital, ganancia esperada, margen, mora e inventario.",
            "Usa la actividad reciente para comprobar movimientos importantes.",
        ],
        "guide_tips": [
            "Los indicadores se calculan con la información registrada en acuerdos, pagos, compras e inventario.",
            "El margen compara el costo registrado con el valor de venta correspondiente.",
        ],
    },
    {
        "slug": "documents",
        "name": "Documentos",
        "endpoint": "main.documents",
        "icon": "home-documents",
        "accent": "accent-orange",
        "home_description": "Guía y documentos",
        "guide_summary": "Consulta la guía de uso de CuotaGo, generada a partir de los módulos activos del sistema.",
        "guide_steps": [
            "Abre Documentos desde Inicio.",
            "Usa el buscador o el índice para encontrar el módulo que necesitas.",
            "Lee los pasos rápidos, recomendaciones y comportamiento de cada función.",
        ],
        "guide_tips": [
            "La guía y el Inicio usan el mismo catálogo de módulos, por lo que permanecen sincronizados al ampliar CuotaGo.",
        ],
    },
    {
        "slug": "settings",
        "name": "Ajustes",
        "endpoint": "main.settings",
        "icon": "home-settings",
        "accent": "accent-slate",
        "home_description": "Cuenta y aplicación",
        "guide_summary": "Configura la cuenta, apariencia y funciones de la aplicación.",
        "guide_steps": [
            "Entra a Ajustes desde Inicio.",
            "Activa o desactiva las opciones disponibles.",
            "Guarda los cambios de cuenta o configuración cuando corresponda.",
        ],
        "guide_tips": [
            "Desde aquí puedes probar y activar las notificaciones del dispositivo cuando el navegador lo permita.",
        ],
    },
]


def module_catalog():
    """Return a fresh list so templates cannot mutate the canonical catalog."""
    return [dict(module) for module in MODULE_CATALOG]
