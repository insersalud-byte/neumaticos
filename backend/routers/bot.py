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
    limite: int = Query(80, le=200),
    db: Session = Depends(get_db),
):
    q = db.query(Producto).filter(
        Producto.activo == True, Producto.publicar_web == True
    )
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

    return {
        "empresa": EMPRESA,
        "productos": [
            {
                "id": p.id,
                "marca": p.marca,
                "modelo": p.modelo,
                "medida": p.medida,
                "descripcion": p.descripcion,
                "categoria": p.categoria,
                "tipo": p.tipo,
                "precio_contado": _precio_contado(p),
                "precio_lista": round(p.precio_venta_final or 0),
                "precio_6_cuotas": round(p.precio_cuota_6 or 0),
                "precio_12_cuotas": round(p.precio_cuota_12 or 0),
                "stock": p.stock_real,
            }
            for p in productos
        ],
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
    limite: int = Query(60, le=200),
    db: Session = Depends(get_db),
):
    """
    Catálogo como texto markdown listo para inyectar al prompt del LLM.
    """
    q_base = db.query(Producto).filter(
        Producto.activo == True, Producto.publicar_web == True
    )

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
            pc = _precio_contado(p)
            p6 = round(p.precio_cuota_6 or 0)
            p12 = round(p.precio_cuota_12 or 0)
            lines.append(
                f"| {p.marca or '—'} | {p.modelo or '—'} | {p.medida or '—'} | "
                f"{fmt(pc)} | {fmt(p6)} | {fmt(p12)} | {p.stock_real} |"
            )
        lines.append("")

    if productos_agotados:
        lines.append("## Productos sin stock momentáneo (consultar reposición)")
        lines.append("| Marca | Modelo | Medida |")
        lines.append("|---|---|---|")
        for p in productos_agotados:
            lines.append(f"| {p.marca or '—'} | {p.modelo or '—'} | {p.medida or '—'} |")
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
    query = db.query(Producto).filter(
        Producto.activo == True, Producto.publicar_web == True
    )
    if terms:
        query = _build_search_query(query, terms)

    resultados = query.limit(20).all()
    return {
        "consulta": q,
        "encontrados": len(resultados),
        "productos": [
            {
                "marca": p.marca,
                "modelo": p.modelo,
                "medida": p.medida,
                "descripcion": p.descripcion,
                "precio_contado": _precio_contado(p),
                "precio_6_cuotas": round(p.precio_cuota_6 or 0),
                "precio_12_cuotas": round(p.precio_cuota_12 or 0),
                "stock": p.stock_real,
                "disponible": p.stock_real > 0,
            }
            for p in resultados
        ],
    }


@router.get("/empresa", dependencies=[Depends(require_api_key)])
def info_empresa():
    return EMPRESA
