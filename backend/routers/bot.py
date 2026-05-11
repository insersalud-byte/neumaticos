"""
API pública para el asistente de WhatsApp.

Endpoints:
- /catalogo  → JSON estructurado
- /contexto  → texto markdown listo para inyectar al prompt del LLM
- /buscar    → búsqueda de un producto puntual
- /empresa   → datos de contacto

Auth opcional: si BOT_API_KEY está seteada en variables de entorno,
exige el header X-Bot-Key. Si no, queda abierto (lectura pública).
"""
from fastapi import APIRouter, Depends, HTTPException, Header, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_
from core.database import get_db
from models.models import Producto, Servicio
import os
import re

# Marcas conocidas de neumáticos para extraer de la descripción
MARCAS_CONOCIDAS = [
    "PIRELLI", "FATE", "BRIDGESTONE", "FIRESTONE", "GOODYEAR", "MICHELIN",
    "CONTINENTAL", "DUNLOP", "YOKOHAMA", "HANKOOK", "KUMHO", "NEXEN",
    "GT RADIAL", "HABILEAD", "WANLI", "LINGLONG", "ROADCRUZA", "SAILUN",
    "TRIANGLE", "MAXXIS", "DURABLE", "XBRI", "SUNSET", "FRASLE", "LPR",
    "BOSCH",
]
# Patrones para medidas. Probamos en orden de más específico a menos.
# Soporta: 31x10.50R15, 175/65R14, 175/65 R14, 175 / 65 R14, 175 65 R 14, etc.
MEDIDA_RES = [
    # 31x10.50R15 (flotante)
    re.compile(r'\b(?:LT|P)?(\d{2,3})\s*[xX]\s*(\d{1,2}\.\d{1,2})\s*[rR]\s*(\d{2})\b'),
    # 175/65R14, 175/65 R14, 175 / 65 R 14, 175/65 R 14C (camionetas)
    re.compile(r'\b(?:LT|P)?(\d{2,3})\s*/\s*(\d{2,3})\s*[rR]\s*(\d{2})C?\b', re.IGNORECASE),
    # 175 65 R14 (sin slash, solo espacios)
    re.compile(r'\b(?:LT|P)?(\d{3})\s+(\d{2})\s*[rR]\s*(\d{2})\b', re.IGNORECASE),
]
def _buscar_medida(texto):
    """Devuelve (match, medida_normalizada). La medida queda en formato canónico
    sin espacios: '175/65R14', '31x10.50R15', etc."""
    for rgx in MEDIDA_RES:
        m = rgx.search(texto)
        if m:
            # Reconstruir normalizado a partir de los grupos capturados
            g = m.groups()
            prefijo = (m.group(0)[:2].upper() if m.group(0).upper().startswith(('LT', 'P')) and m.group(0)[1].isalpha() else '')
            # Detectar si era el formato flotante (segundo grupo con punto)
            if g[1] and '.' in g[1]:
                medida_norm = f"{prefijo}{g[0]}x{g[1]}R{g[2]}"
            else:
                medida_norm = f"{prefijo}{g[0]}/{g[1]}R{g[2]}"
            return m, medida_norm
    return None, ''

def _normalizar_producto(p: Producto) -> dict:
    """
    Para NEUMÁTICOS: si marca/modelo/medida están vacíos, los extrae desde
    `descripcion`. Para repuestos y otros productos, devuelve los campos tal cual
    están en la DB (no se inventa nada).
    Detección de neumático: tipo='neumatico' O se encuentra una medida en la descripcion.
    """
    marca = (p.marca or "").strip()
    modelo = (p.modelo or "").strip()
    medida = (p.medida or "").strip()
    desc = (p.descripcion or "").strip()
    tipo = (p.tipo or "").strip().lower()

    # Buscar medida en descripcion (solo si falta)
    medida_match = None
    medida_desc = ""
    if desc:
        medida_match, medida_desc = _buscar_medida(desc)

    # ¿Es neumático? Sólo normalizamos si SÍ.
    es_neumatico = tipo == "neumatico" or bool(medida_match)
    if not es_neumatico:
        # Repuestos, accesorios, etc → devolver tal cual
        return {"marca": marca, "modelo": modelo, "medida": medida}

    # 1. Extraer medida si falta
    if not medida and medida_desc:
        medida = medida_desc

    # 2. Extraer marca si falta
    if not marca and desc:
        upper_desc = desc.upper()
        for mk in MARCAS_CONOCIDAS:
            if mk in upper_desc:
                marca = mk.title()
                break

    # 3. Construir modelo desde lo que queda en descripcion
    if not modelo and desc:
        sin_medida = desc
        if medida_match:
            sin_medida = (sin_medida[:medida_match.start()] + sin_medida[medida_match.end():]).strip()
        if marca:
            sin_medida = re.sub(re.escape(marca), "", sin_medida, flags=re.IGNORECASE).strip()
        # Sacar códigos de carga/velocidad: "82T", "82 T", "95/93 T", "88 H", "112 H"
        sin_medida = re.sub(r'\b\d{2,3}\s*/\s*\d{2,3}\s*[A-Z]\b', '', sin_medida).strip()
        sin_medida = re.sub(r'\b\d{2,3}\s+[A-Z]\b', '', sin_medida).strip()
        sin_medida = re.sub(r'\b\d{2,3}[A-Z]\b', '', sin_medida).strip()
        # Sacar separadores y palabras de tipo (XL, A/S, U/P, etc no se sacan)
        sin_medida = re.sub(r'^[\s\-_|]+|[\s\-_|]+$', '', sin_medida).strip()
        sin_medida = re.sub(r'\s+', ' ', sin_medida)
        if sin_medida and len(sin_medida) >= 2:
            modelo = sin_medida

    return {"marca": marca, "modelo": modelo, "medida": medida}

router = APIRouter(prefix="/api/v1/bot", tags=["bot"])

EMPRESA = {
    "nombre": "Giorda Neumáticos",
    "direccion": "Caraffa 2154, Córdoba Capital",
    "telefono": "+54 9 351 235 0349",
    "horario": "Lunes a Sábado 8:30 a 13:00 / 16:00 a 20:00",
    "web": "https://giordaneumaticos.com.ar",
    "turnos": "https://giordaneumaticos.com.ar/turnos",
    "metodos_pago": "Efectivo, débito, crédito en cuotas, Mercado Pago",
}

# Palabras genéricas que no aportan a la búsqueda
STOPWORDS = {
    "neumatico", "neumático", "neumaticos", "neumáticos",
    "cubierta", "cubiertas", "rueda", "ruedas",
    "el", "la", "los", "las", "un", "una", "unos", "unas",
    "de", "del", "para", "con", "sin", "y", "o",
    "tienen", "tienes", "hay", "tenes", "tenés",
    "precio", "precios", "costo", "costos",
}


def require_api_key(x_bot_key: str | None = Header(None, alias="X-Bot-Key")):
    """Dep que valida X-Bot-Key si BOT_API_KEY está seteada."""
    expected = os.environ.get("BOT_API_KEY")
    if not expected:
        return  # API abierta
    if x_bot_key != expected:
        raise HTTPException(status_code=401, detail="API key inválida o ausente")


def _filter_terms(query: str) -> list[str]:
    return [
        t for t in query.strip().lower().split()
        if t and t not in STOPWORDS and len(t) >= 2
    ]


def _build_search_query(base_query, terms: list[str]):
    for t in terms:
        like = f"%{t}%"
        base_query = base_query.filter(
            or_(
                Producto.marca.ilike(like),
                Producto.modelo.ilike(like),
                Producto.medida.ilike(like),
                Producto.descripcion.ilike(like),
                Producto.categoria.ilike(like),
            )
        )
    return base_query


def _precio_contado(p: Producto) -> int:
    # None-safe: 0 es un precio válido, no caer al precio de lista
    if p.precio_venta_contado is not None and p.precio_venta_contado > 0:
        return round(p.precio_venta_contado)
    if p.precio_venta_final is not None and p.precio_venta_final > 0:
        return round(p.precio_venta_final)
    return 0


@router.get("/catalogo", dependencies=[Depends(require_api_key)])
def catalogo_json(
    buscar: str = Query("", description="Filtra por marca/modelo/medida"),
    solo_con_stock: bool = Query(True),
    solo_publicados: bool = Query(False, description="Si True, solo trae publicar_web=True (legacy)"),
    limite: int = Query(80, le=1000),
    db: Session = Depends(get_db),
):
    # Por defecto el bot accede a TODA la DB activa, no solo a los publicados en web
    q = db.query(Producto).filter(Producto.activo == True)
    if solo_publicados:
        q = q.filter(Producto.publicar_web == True)
    if solo_con_stock:
        q = q.filter(Producto.stock_real > 0)

    terms = _filter_terms(buscar)
    if terms:
        q_filtered = _build_search_query(q, terms)
        productos = q_filtered.limit(limite).all()
        # Fallback: si los términos eran muy específicos y no encontramos nada,
        # devolvemos algo en vez de vacío para que el modelo pueda ofrecer alternativas
        if not productos and len(terms) > 1:
            productos = q.limit(min(20, limite)).all()
    else:
        productos = q.limit(limite).all()

    servicios = db.query(Servicio).filter(Servicio.activo == True).all()

    def serializar(p):
        norm = _normalizar_producto(p)
        return {
            "id": p.id,
            "marca": norm["marca"],
            "modelo": norm["modelo"],
            "medida": norm["medida"],
            "descripcion": p.descripcion,
            "categoria": p.categoria,
            "tipo": p.tipo,
            "precio_contado": _precio_contado(p),
            "precio_lista": round(p.precio_venta_final or 0),
            "precio_6_cuotas": round(p.precio_cuota_6 or 0),
            "precio_12_cuotas": round(p.precio_cuota_12 or 0),
            "stock": p.stock_real,
            "imagen_url": p.imagen_url or "",
        }

    return {
        "empresa": EMPRESA,
        "productos": [serializar(p) for p in productos],
        "servicios": [
            {"nombre": s.nombre, "precio": round(s.precio_sugerido or 0), "descripcion": s.descripcion}
            for s in servicios
        ],
        "total_productos": len(productos),
        "total_servicios": len(servicios),
    }


@router.get(
    "/contexto",
    response_class=PlainTextResponse,
    dependencies=[Depends(require_api_key)],
)
def contexto_texto(
    buscar: str = Query(""),
    solo_con_stock: bool = Query(True, description="Si True, solo lista productos con stock>0"),
    solo_publicados: bool = Query(False, description="Si True, solo trae publicar_web=True (legacy)"),
    limite: int = Query(60, le=1000),
    db: Session = Depends(get_db),
):
    """
    Catálogo como texto markdown listo para inyectar al prompt del LLM.
    Por defecto trae TODA la DB activa (no solo publicados en web).
    """
    q_base = db.query(Producto).filter(Producto.activo == True)
    if solo_publicados:
        q_base = q_base.filter(Producto.publicar_web == True)

    terms = _filter_terms(buscar)
    if terms:
        q_search = _build_search_query(q_base, terms)
    else:
        q_search = q_base

    if solo_con_stock:
        productos_disp = q_search.filter(Producto.stock_real > 0).limit(limite).all()
        productos_agotados = (
            q_search.filter(Producto.stock_real <= 0).limit(20).all()
            if buscar  # solo mostrar agotados si el cliente buscó algo específico
            else []
        )
    else:
        productos_disp = q_search.limit(limite).all()
        productos_agotados = []

    servicios = db.query(Servicio).filter(Servicio.activo == True).all()

    lines: list[str] = []
    lines.append(f"# {EMPRESA['nombre']}")
    lines.append(f"📍 {EMPRESA['direccion']}")
    lines.append(f"📞 {EMPRESA['telefono']}")
    lines.append(f"🕐 {EMPRESA['horario']}")
    lines.append(f"🌐 {EMPRESA['web']}")
    lines.append(f"💳 {EMPRESA['metodos_pago']}")
    lines.append("")

    if servicios:
        lines.append("## Servicios")
        lines.append("| Servicio | Precio |")
        lines.append("|---|---|")
        for s in servicios:
            precio = f"${round(s.precio_sugerido or 0):,}".replace(",", ".")
            lines.append(f"| {s.nombre} | {precio} |")
        lines.append("")

    fmt = lambda n: f"${n:,}".replace(",", ".") if n else "—"

    if productos_disp:
        lines.append("## Productos disponibles (con stock)")
        lines.append("| Marca | Modelo | Medida | Precio contado | 6 cuotas | 12 cuotas | Stock |")
        lines.append("|---|---|---|---|---|---|---|")
        for p in productos_disp:
            n = _normalizar_producto(p)
            pc = _precio_contado(p)
            p6 = round(p.precio_cuota_6 or 0)
            p12 = round(p.precio_cuota_12 or 0)
            lines.append(
                f"| {n['marca'] or '—'} | {n['modelo'] or '—'} | {n['medida'] or '—'} | "
                f"{fmt(pc)} | {fmt(p6)} | {fmt(p12)} | {p.stock_real} |"
            )
        lines.append("")

    if productos_agotados:
        lines.append("## Productos sin stock momentáneo (consultar reposición)")
        lines.append("| Marca | Modelo | Medida |")
        lines.append("|---|---|---|")
        for p in productos_agotados:
            n = _normalizar_producto(p)
            lines.append(f"| {n['marca'] or '—'} | {n['modelo'] or '—'} | {n['medida'] or '—'} |")
        lines.append("")

    if not productos_disp and not productos_agotados and buscar:
        lines.append(f"_Sin resultados para: '{buscar}'_")
        lines.append("")

    lines.append("---")
    lines.append(f"Para sacar turno: {EMPRESA['turnos']}")

    return "\n".join(lines)


@router.get("/buscar", dependencies=[Depends(require_api_key)])
def buscar_producto(
    q: str = Query(..., min_length=2),
    db: Session = Depends(get_db),
):
    terms = _filter_terms(q)
    query = db.query(Producto).filter(Producto.activo == True)
    if terms:
        query = _build_search_query(query, terms)

    resultados = query.limit(20).all()
    productos_out = []
    for p in resultados:
        n = _normalizar_producto(p)
        productos_out.append({
            "marca": n["marca"],
            "modelo": n["modelo"],
            "medida": n["medida"],
            "descripcion": p.descripcion,
            "precio_contado": _precio_contado(p),
            "precio_6_cuotas": round(p.precio_cuota_6 or 0),
            "precio_12_cuotas": round(p.precio_cuota_12 or 0),
            "stock": p.stock_real,
            "disponible": p.stock_real > 0,
        })
    return {
        "consulta": q,
        "encontrados": len(resultados),
        "productos": productos_out,
    }


@router.get("/empresa", dependencies=[Depends(require_api_key)])
def info_empresa():
    return EMPRESA


@router.get("/diagnostico")
def diagnostico_db(
    db: Session = Depends(get_db),
):
    """
    Diagnóstico de productos: cuántos hay activos, publicados, con stock,
    cuántos por marca encontrada en descripcion (Goodyear, Pirelli, etc.).
    Útil para saber por qué algunos productos no aparecen en el bot.
    """
    todos_activos = db.query(Producto).filter(Producto.activo == True).all()
    publicados = [p for p in todos_activos if p.publicar_web]
    no_publicados = [p for p in todos_activos if not p.publicar_web]

    # Buscar marcas de neumáticos conocidas en TODOS los productos activos
    marcas_test = ["GOODYEAR", "BRIDGESTONE", "FATE", "MICHELIN", "CONTINENTAL", "FIRESTONE", "DUNLOP", "YOKOHAMA", "PIRELLI", "HANKOOK", "NEXEN"]
    detalle_marcas = {}
    for marca in marcas_test:
        en_publicados = sum(1 for p in publicados if marca in (p.descripcion or "").upper() or marca in (p.marca or "").upper())
        en_no_publicados = sum(1 for p in no_publicados if marca in (p.descripcion or "").upper() or marca in (p.marca or "").upper())
        detalle_marcas[marca] = {
            "publicados": en_publicados,
            "no_publicados": en_no_publicados,
            "total": en_publicados + en_no_publicados,
        }

    # Productos con "oferta" en descripcion o categoria
    ofertas = [p for p in todos_activos if "oferta" in (p.descripcion or "").lower() or "oferta" in (p.categoria or "").lower()]

    # Muestra de valores raw del campo publicar_web (para debug)
    sample_no_pub = no_publicados[:5]
    raw_publicar_web = [
        {"id": p.id, "valor_raw": repr(p.publicar_web), "tipo": type(p.publicar_web).__name__, "stock": p.stock_real, "desc": (p.descripcion or "")[:60]}
        for p in sample_no_pub
    ]

    return {
        "total_activos": len(todos_activos),
        "publicados_web": len(publicados),
        "no_publicados_web": len(no_publicados),
        "raw_no_publicados_sample": raw_publicar_web,
        "con_stock": sum(1 for p in todos_activos if p.stock_real > 0),
        "marcas_neumaticos": detalle_marcas,
        "productos_oferta": {
            "cantidad": len(ofertas),
            "ejemplos": [
                {"id": p.id, "descripcion": p.descripcion, "publicar_web": p.publicar_web, "stock": p.stock_real}
                for p in ofertas[:10]
            ],
        },
    }


@router.post("/normalizar-productos-db")
def normalizar_productos_db(
    aplicar: bool = False,
    db: Session = Depends(get_db),
):
    """
    Recorre todos los productos activos y rellena marca/modelo/medida en la DB
    cuando están vacíos, extrayendo la info desde descripción.
    Solo aplica a neumáticos (cuando se detecta una medida).

    Modo dry-run por defecto. Pasar ?aplicar=true para escribir.
    """
    productos = db.query(Producto).filter(Producto.activo == True).all()
    cambios = []
    actualizados = 0
    for p in productos:
        norm = _normalizar_producto(p)
        # Sólo actualizamos campos que estaban vacíos
        nueva_marca = norm["marca"] if not (p.marca or "").strip() and norm["marca"] else None
        nuevo_modelo = norm["modelo"] if not (p.modelo or "").strip() and norm["modelo"] else None
        nueva_medida = norm["medida"] if not (p.medida or "").strip() and norm["medida"] else None
        if not (nueva_marca or nuevo_modelo or nueva_medida):
            continue
        cambios.append({
            "id": p.id,
            "descripcion": p.descripcion,
            "marca": {"antes": p.marca, "despues": nueva_marca} if nueva_marca else None,
            "modelo": {"antes": p.modelo, "despues": nuevo_modelo} if nuevo_modelo else None,
            "medida": {"antes": p.medida, "despues": nueva_medida} if nueva_medida else None,
        })
        if aplicar:
            if nueva_marca: p.marca = nueva_marca
            if nuevo_modelo: p.modelo = nuevo_modelo
            if nueva_medida: p.medida = nueva_medida
            actualizados += 1
    if aplicar:
        db.commit()
    return {
        "modo": "aplicado" if aplicar else "dry-run (pasá ?aplicar=true para ejecutar)",
        "productos_recorridos": len(productos),
        "productos_a_actualizar": len(cambios),
        "actualizados": actualizados,
        "muestra": cambios[:15],
    }


@router.post("/publicar-todos")
def publicar_todos(
    aplicar: bool = False,
    solo_con_stock: bool = True,
    db: Session = Depends(get_db),
):
    """
    Marca como publicar_web=True a todos los productos activos.
    Por defecto solo aplica a los que tienen stock>0 para no exponer agotados sin info.

    Modo dry-run por defecto. Pasá ?aplicar=true para ejecutar.
    """
    # Trata NULL y False como "no publicado". `!= True` no matchea NULL en SQL.
    from sqlalchemy import or_ as _or
    q = db.query(Producto).filter(
        Producto.activo == True,
        _or(Producto.publicar_web == False, Producto.publicar_web.is_(None)),
    )
    if solo_con_stock:
        q = q.filter(Producto.stock_real > 0)

    productos = q.all()

    if aplicar:
        for p in productos:
            p.publicar_web = True
        db.commit()

    return {
        "modo": "aplicado" if aplicar else "dry-run (pasá ?aplicar=true para ejecutar)",
        "productos_a_publicar": len(productos),
        "ejemplos": [
            {"id": p.id, "descripcion": p.descripcion, "stock": p.stock_real}
            for p in productos[:10]
        ],
    }
