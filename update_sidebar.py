import re, os

ADMIN_DIR = os.path.join(os.path.dirname(__file__), "frontend", "admin")

SIDEBAR_CSS = """
  <style>
    .sidebar-link {
      display: flex; align-items: center; gap: 10px;
      padding: 7px 12px; border-radius: 8px;
      color: #6b7280; font-size: 13px; font-weight: 500;
      transition: all 0.15s; margin: 1px 8px;
      text-decoration: none;
    }
    .sidebar-link:hover { background: #111113; color: #e5e7eb; }
    .sidebar-link.active { background: #18181b; color: #fff; border-left: 3px solid #dc2626; padding-left: 9px; }
    .sidebar-section-title {
      font-size: 9px; text-transform: uppercase; letter-spacing: 0.12em;
      color: #374151; padding: 14px 20px 4px; font-weight: 800;
    }
  </style>"""

def make_sidebar(active_page):
    def link(href, icon_class, icon_color, label, page_key):
        active = ' active' if page_key == active_page else ''
        return f'    <a href="{href}" class="sidebar-link{active}">\n      <i class="{icon_class} w-6 text-center {icon_color}"></i>\n      <span>{label}</span>\n    </a>'

    return f"""  <!-- SIDEBAR -->
  <aside id="sidebar" class="fixed md:relative inset-y-0 left-0 z-50 w-64 bg-[#050505] border-r border-[#1f1f22] flex flex-col flex-shrink-0 transform -translate-x-full md:translate-x-0 transition-transform duration-300 ease-in-out">

    <!-- LOGO -->
    <div class="h-16 flex items-center justify-between px-6 border-b border-[#1f1f22]">
      <h1 class="text-xl font-black italic tracking-tighter text-white flex items-center gap-2 select-none">
        <div class="bg-red-600 text-white w-8 h-8 flex items-center justify-center rounded-lg shadow-red-900/50 shadow-lg">
          <i class="fas fa-tire"></i>
        </div>
        <span>GIORDA<span class="text-red-600">OS</span></span>
      </h1>
      <button class="md:hidden text-gray-500 hover:text-white" onclick="document.getElementById('sidebar').classList.add('-translate-x-full')">
        <i class="fas fa-times"></i>
      </button>
    </div>

    <!-- NAV -->
    <nav class="flex-1 overflow-y-auto py-2 space-y-0.5">
      <div class="sidebar-section-title">Mostrador &amp; Ventas</div>
{link("pos-mostrador.html", "fas fa-cash-register", "text-green-500", "Punto de Venta", "pos")}
{link("pedidos-demo.html", "fas fa-globe", "text-blue-400", "Cotizacion - Pedidos", "pedidos")}
      <div class="sidebar-section-title">Planta &amp; Taller</div>
{link("recepcion-taller.html", "fas fa-clipboard-list", "text-orange-400", "Recepción Vehículos", "recepcion")}
{link("taller-control.html", "fas fa-wrench", "text-gray-400", "Tablero Mecánicos", "taller")}
{link("turnos-demo.html", "fas fa-calendar-alt", "text-purple-400", "Agenda de Turnos", "turnos")}
      <div class="sidebar-section-title flex items-center gap-2">Back Office <i class="fas fa-lock text-[9px] text-red-900"></i></div>
{link("inventario.html", "fas fa-boxes", "text-yellow-500", "Inventario &amp; Stock", "inventario")}
{link("#", "fas fa-list-ul", "text-gray-500", "Servicios &amp; MO", "servicios")}
{link("#", "fas fa-layer-group", "text-gray-500", "Stock Gestión", "stock")}
{link("#", "fas fa-file-invoice-dollar", "text-gray-500", "Compras (Proveedores)", "compras")}
{link("#", "fas fa-chart-pie", "text-red-500", "Finanzas &amp; Caja", "finanzas")}
{link("#", "fas fa-users", "text-blue-500", "Cuentas Corrientes", "cuentas")}
{link("#", "fas fa-credit-card", "text-green-400", "Planes Tarjetas", "tarjetas")}
    </nav>

    <!-- FOOTER -->
    <div class="p-4 border-t border-[#1f1f22] bg-[#0a0a0c]">
      <div class="flex items-center gap-3">
        <div class="w-9 h-9 rounded-lg bg-gradient-to-br from-gray-800 to-black border border-gray-700 flex items-center justify-center text-white font-bold text-sm">S</div>
        <div class="flex-1 min-w-0">
          <p class="text-xs font-bold text-white truncate">Sergio Giorda</p>
          <p class="text-[10px] text-gray-600 truncate">gerencia</p>
        </div>
        <button onclick="logout()" class="text-gray-600 hover:text-red-500 transition" title="Salir">
          <i class="fas fa-power-off text-sm"></i>
        </button>
      </div>
    </div>
  </aside>"""

PAGE_MAP = {
    "pos-mostrador.html":    "pos",
    "pedidos-demo.html":     "pedidos",
    "recepcion-taller.html": "recepcion",
    "taller-control.html":   "taller",
    "turnos-demo.html":      "turnos",
    "inventario.html":       "inventario",
}

for filename, page_key in PAGE_MAP.items():
    path = os.path.join(ADMIN_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # Inject CSS before </head>
    if SIDEBAR_CSS not in content:
        content = content.replace("</head>", SIDEBAR_CSS + "\n</head>")

    # Replace <aside ...> block (any format)
    new_sidebar = make_sidebar(page_key)
    content = re.sub(
        r'  <aside\b.*?</aside>',
        new_sidebar,
        content,
        flags=re.DOTALL
    )

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"OK {filename}")

print("Sidebar actualizado en todos los archivos.")
